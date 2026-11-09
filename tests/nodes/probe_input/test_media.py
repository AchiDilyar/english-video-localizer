"""Real FFmpeg integration checks on generated media; no speech/model calls."""
from array import array
import contextlib
import importlib.util
import io
import json
import math
import os
from pathlib import Path
import struct
import sys
import tempfile
import unittest
import wave

ROOT = Path(__file__).resolve().parents[3]
from nodes.probe_input import media as m


class MediaIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            cls.ffmpeg = m.tool_path('ffmpeg')
            cls.ffprobe = m.tool_path('ffprobe')
        except m.MediaError as exc:
            raise unittest.SkipTest(str(exc))
        test_root = (ROOT / 'tests' / 'tmp' / 'probe_input').resolve()
        if not test_root.is_relative_to(ROOT.resolve()):
            raise RuntimeError('Test workspace escaped repository')
        test_root.mkdir(parents=True, exist_ok=True)
        keep = os.environ.get('B_MEDIA_TEST_ARTIFACT_DIR')
        cls.temp = None
        if keep:
            cls.root = Path(keep).resolve()
            if not cls.root.is_relative_to((ROOT / 'tests' / 'tmp').resolve()):
                raise RuntimeError('Persistent test artifacts must stay under tests/tmp/')
            cls.root.mkdir(parents=True, exist_ok=False)
        else:
            cls.temp = tempfile.TemporaryDirectory(prefix='b media integration ', dir=test_root)
            cls.root = Path(cls.temp.name)
        cls.signal = cls.root / 'signal.wav'
        with wave.open(str(cls.signal), 'wb') as f:
            f.setparams((2, 2, 48000, 0, 'NONE', 'not compressed'))
            # Stereo, 48 kHz, first 250 ms 440 Hz then 880 Hz. Nothing is speech.
            frames = bytearray()
            for i in range(48000):
                freq = 440 if i < 12000 else 880
                v = int(10000 * math.sin(2 * math.pi * freq * i / 48000))
                frames.extend(struct.pack('<hh', v, v))
            f.writeframes(frames)
        cls.late = cls.root / 'late audio.mov'
        cls.shifted = cls.root / 'shifted origin.mov'
        cls.early = cls.root / 'early audio.mov'
        cls.silent = cls.root / 'no audio.mov'
        cls.mp4 = cls.root / 'aac video.mp4'
        base = [cls.ffmpeg, '-hide_banner', '-loglevel', 'error', '-nostdin', '-n']
        # 40 fps makes 250 ms exactly 10 frames; 25 fps quantizes it to 240 ms.
        video = ['-f', 'lavfi', '-i', 'color=c=black:s=160x120:r=40:d=2']
        encode = ['-c:v', 'mpeg4', '-c:a', 'pcm_s16le']
        m.run(base + video + ['-itsoffset', '0.25', '-i', str(cls.signal)] + encode + [str(cls.late)])
        m.run(base + video + ['-itsoffset', '0.25', '-i', str(cls.signal)] + encode + ['-output_ts_offset', '3', str(cls.shifted)])
        m.run(base + ['-itsoffset', '0.25'] + video + ['-i', str(cls.signal)] + encode + [str(cls.early)])
        m.run(base + video + ['-c:v', 'mpeg4', str(cls.silent)])
        m.run(base + video + ['-itsoffset', '0.25', '-i', str(cls.signal),
                              '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-c:a', 'aac', str(cls.mp4)])

    @classmethod
    def tearDownClass(cls):
        if cls.temp is None:
            return  # Verification runner deliberately retains raw inputs and outputs.
        if not cls.root.resolve().is_relative_to((ROOT / 'tests' / 'tmp' / 'probe_input').resolve()):
            raise RuntimeError('Refusing cleanup outside test workspace')
        cls.temp.cleanup()

    def extract(self, source, name):
        output = self.root / name
        report = m.extract(source, output, self.ffprobe, self.ffmpeg, None, None, 30)
        with wave.open(str(output / 'audio.wav'), 'rb') as f:
            samples = array('h', f.readframes(f.getnframes()))
            if sys.byteorder != 'little':
                samples.byteswap()
        return report, samples

    def test_late_audio_preserves_leading_silence_and_duration(self):
        report, samples = self.extract(self.late, 'late output')
        self.assertEqual(report['audio_offset_ms'], 250)
        self.assertEqual(report['duration_ms'], 2000)
        self.assertEqual(len(samples), 32000)
        self.assertLess(max(abs(x) for x in samples[:3000]), 2)
        self.assertGreater(max(abs(x) for x in samples[4800:6400]), 1000)
        self.assertLess(max(abs(x) for x in samples[24000:]), 2)
        self.assertFalse(report['asr_executed'])

    def test_nonzero_video_origin_is_removed_once(self):
        report, samples = self.extract(self.shifted, 'shifted output')
        self.assertEqual(report['video_origin_sec'], '3.000000')
        self.assertEqual(report['audio_offset_ms'], 250)
        self.assertEqual(len(samples), 32000)
        self.assertLess(max(abs(x) for x in samples[:3000]), 2)
        self.assertGreater(max(abs(x) for x in samples[4800:6400]), 1000)

    def test_mp4_aac_preserves_signal_onset_and_full_duration(self):
        report, samples = self.extract(self.mp4, 'mp4 output')
        self.assertEqual(report['duration_ms'], 2000)
        self.assertEqual(len(samples), 32000)
        # AAC delay/priming is container-dependent; check decoded sound, not start metadata alone.
        onset = next(i for i, sample in enumerate(samples) if abs(sample) > 1000)
        self.assertTrue(220 * 16 <= onset <= 280 * 16, onset)
        self.assertLess(max(abs(x) for x in samples[24000:]), 2)

    def test_early_audio_is_trimmed_not_shifted_to_zero(self):
        report, samples = self.extract(self.early, 'early output')
        self.assertEqual(report['audio_offset_ms'], -250)
        # After trimming first 250 ms, the first 100 ms must be 880 Hz, not 440 Hz.
        crossings = sum(a <= 0 < b for a, b in zip(samples[160:1759], samples[161:1760]))
        self.assertTrue(85 <= crossings <= 90, crossings)
        self.assertLess(max(abs(x) for x in samples[16000:]), 2)

    def test_no_audio_fails(self):
        with self.assertRaises(m.MediaError) as cm:
            m.inspect(self.silent, self.ffprobe, None, None)
        self.assertEqual(cm.exception.code, 'AUDIO_MISSING')

    def test_missing_file_fails(self):
        with self.assertRaises(m.MediaError) as cm:
            m.inspect(self.root / 'missing.mp4', self.ffprobe, None, None)
        self.assertEqual(cm.exception.code, 'INPUT_NOT_FOUND')

    def test_corrupt_media_fails(self):
        p = self.root / 'corrupt.mp4'
        p.write_bytes(b'this is not media')
        with self.assertRaises(m.MediaError):
            m.inspect(p, self.ffprobe, None, None)

    def test_existing_output_is_preserved(self):
        output = self.root / 'existing'
        output.mkdir()
        (output / 'audio.wav').write_bytes(b'keep me')
        with self.assertRaises(m.MediaError) as cm:
            m.extract(self.late, output, self.ffprobe, self.ffmpeg, None, None, 30)
        self.assertEqual(cm.exception.code, 'OUTPUT_EXISTS')
        self.assertEqual((output / 'audio.wav').read_bytes(), b'keep me')

    def test_ambiguous_streams_require_selection(self):
        streams = [{'index': 1, 'codec_type': 'audio'}, {'index': 2, 'codec_type': 'audio'}]
        with self.assertRaises(m.MediaError) as cm:
            m.choose_stream(streams, 'audio')
        self.assertEqual(cm.exception.code, 'STREAM_SELECTION_REQUIRED')
        self.assertEqual(m.choose_stream(streams, 'audio', 2)['index'], 2)

    def test_cli_error_and_help_do_not_load_models(self):
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            result = m.main(['inspect', '--input', str(self.root / 'missing.mp4'), '--ffprobe', self.ffprobe])
        self.assertEqual(result, 3)
        self.assertEqual(json.loads(stderr.getvalue())['code'], 'INPUT_NOT_FOUND')
        with contextlib.redirect_stdout(io.StringIO()), self.assertRaises(SystemExit) as cm:
            m.main(['--help'])
        self.assertEqual(cm.exception.code, 0)
