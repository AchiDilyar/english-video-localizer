"""Standalone B preflight and local audio preparation, independent of shared APIs.

Python 3.11+; standard library only. Does not invoke ASR, agents or network services.
"""
from __future__ import annotations

import argparse
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tempfile
import time
import wave

ROOT = Path(__file__).resolve().parents[3]


class MediaError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


def tool_path(name: str, override: str | None = None) -> str:
    candidate = override or shutil.which(name)
    if not candidate:
        local = ROOT / '.tools' / 'ffmpeg' / 'bin' / (name + ('.exe' if os.name == 'nt' else ''))
        candidate = str(local) if local.is_file() else None
    if not candidate or not Path(candidate).is_file():
        raise MediaError('DEPENDENCY_MISSING', f'{name} not found; use --{name} or project-local .tools/ffmpeg/bin')
    return str(Path(candidate).resolve())


def run(args: list[str], timeout: float = 60) -> subprocess.CompletedProcess:
    try:
        result = subprocess.run(args, capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        raise MediaError('PROCESS_TIMEOUT', f'{Path(args[0]).name} exceeded {timeout} seconds') from exc
    except OSError as exc:
        raise MediaError('PROCESS_START_FAILED', f'Cannot start {Path(args[0]).name}: {exc}') from exc
    if result.returncode:
        raise MediaError('MEDIA_COMMAND_FAILED', result.stderr[-2000:].strip() or f'Exit {result.returncode}')
    return result


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as f:
        while block := f.read(1024 * 1024):
            h.update(block)
    return h.hexdigest()


def number(value) -> Decimal | None:
    try:
        n = Decimal(str(value))
        return n if n.is_finite() else None
    except InvalidOperation:
        return None


def ms(seconds: Decimal) -> int:
    return int((seconds * 1000).quantize(Decimal('1'), rounding=ROUND_HALF_UP))


def probe(path: Path, ffprobe: str) -> dict:
    if not path.is_file():
        raise MediaError('INPUT_NOT_FOUND', f'Local input does not exist: {path}')
    result = run([ffprobe, '-v', 'error', '-protocol_whitelist', 'file,pipe',
                  '-show_format', '-show_streams', '-of', 'json', str(path.resolve())])
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise MediaError('PROBE_INVALID', 'ffprobe did not return valid JSON') from exc
    if not data.get('streams'):
        raise MediaError('MEDIA_INVALID', 'No media streams found')
    return data


def choose_stream(streams: list[dict], kind: str, index: int | None = None) -> dict:
    candidates = [s for s in streams if s.get('codec_type') == kind
                  and not s.get('disposition', {}).get('attached_pic')]
    if index is not None:
        candidates = [s for s in candidates if s['index'] == index]
    if not candidates:
        raise MediaError('AUDIO_MISSING' if kind == 'audio' else 'VIDEO_MISSING', f'No matching {kind} stream')
    if len(candidates) > 1:
        raise MediaError('STREAM_SELECTION_REQUIRED', f'Multiple {kind} streams; specify --{kind}-stream with absolute stream index')
    return candidates[0]


def inspect(path: Path, ffprobe: str, audio_index: int | None, video_index: int | None) -> dict:
    data = probe(path, ffprobe)
    audio = choose_stream(data['streams'], 'audio', audio_index)
    video = choose_stream(data['streams'], 'video', video_index)
    origin = number(video.get('start_time'))
    duration = number(video.get('duration'))
    duration_source = 'video_stream'
    if duration is None:
        start = number(data.get('format', {}).get('start_time'))
        total = number(data.get('format', {}).get('duration'))
        duration = start + total - origin if all(v is not None for v in [start, total, origin]) else None
        duration_source = 'container_end_minus_video_start'
    audio_start = number(audio.get('start_time'))
    warnings = []
    if origin is None or audio_start is None:
        warnings.append('Unknown video/audio start; extraction requires explicit known timestamps.')
    if duration is None or duration <= 0:
        warnings.append('Unknown/nonpositive presentation duration; extraction is unavailable.')
    if duration_source != 'video_stream':
        warnings.append('Duration falls back to container end; verify final picture duration manually.')
    return {
        'kind': 'b_standalone_media_inspection', 'source_path': str(path.resolve()),
        'source_sha256': sha256(path), 'source_bytes': path.stat().st_size,
        'video_stream_index': video['index'], 'audio_stream_index': audio['index'],
        'video_origin_sec': str(origin) if origin is not None else None,
        'audio_start_sec': str(audio_start) if audio_start is not None else None,
        'audio_offset_ms': ms(audio_start - origin) if origin is not None and audio_start is not None else None,
        'duration_ms': ms(duration) if duration is not None and duration > 0 else None,
        'duration_source': duration_source, 'warnings': warnings, 'probe_raw': data,
    }


def extract(path: Path, output: Path, ffprobe: str, ffmpeg: str,
            audio_index: int | None, video_index: int | None, timeout: float) -> dict:
    started = time.perf_counter()
    info = inspect(path, ffprobe, audio_index, video_index)
    if info['video_origin_sec'] is None or info['audio_start_sec'] is None or not info['duration_ms']:
        raise MediaError('TIMELINE_UNKNOWN', 'Known stream starts and positive duration are required; inspect and resolve before extraction')
    output.mkdir(parents=True, exist_ok=True)
    destinations = [output / 'audio.wav', output / 'media-report.json']
    if any(p.exists() for p in destinations):
        raise MediaError('OUTPUT_EXISTS', 'audio.wav or media-report.json already exists; use a new output directory')
    samples = info['duration_ms'] * 16
    # Preserve original PTS, shift to the selected video origin, fill/trim to sample 0.
    # Padding and end_sample then make the whole video timeline explicit, including silence.
    filters = (f"asetpts=PTS-({info['video_origin_sec']})/TB,"
               f'aresample=16000:async=1:first_pts=0,apad,atrim=end_sample={samples}')
    with tempfile.TemporaryDirectory(prefix='b-extract-', dir=output) as temp:
        temp_audio = Path(temp) / 'audio.wav'
        command = [ffmpeg, '-hide_banner', '-loglevel', 'error', '-nostdin', '-n',
                   '-copyts', '-protocol_whitelist', 'file,pipe', '-i', str(path.resolve()),
                   '-map', f"0:{info['audio_stream_index']}", '-vn', '-af', filters,
                   '-ac', '1', '-ar', '16000', '-c:a', 'pcm_s16le', str(temp_audio)]
        run(command, timeout=timeout)
        with wave.open(str(temp_audio), 'rb') as wav:
            actual = {'sample_rate_hz': wav.getframerate(), 'channels': wav.getnchannels(),
                      'sample_width_bytes': wav.getsampwidth(), 'frame_count': wav.getnframes()}
        if actual != {'sample_rate_hz': 16000, 'channels': 1, 'sample_width_bytes': 2, 'frame_count': samples}:
            raise MediaError('AUDIO_VALIDATION_FAILED', f'Unexpected WAV properties: {actual}')
        info.update({'kind': 'b_standalone_audio_preparation', 'audio': actual,
                     'audio_path': 'audio.wav', 'audio_sha256': sha256(temp_audio),
                     'timeline_origin_ms': 0, 'command': command,
                     'ffmpeg_version': run([ffmpeg, '-version']).stdout.splitlines()[0],
                     'ffprobe_version': run([ffprobe, '-version']).stdout.splitlines()[0],
                     'elapsed_sec': time.perf_counter() - started,
                     'asr_executed': False, 'manual_sync_verified': False})
        temp_report = Path(temp) / 'media-report.json'
        temp_report.write_text(json.dumps(info, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        # Refuse replacement even if another process wrote a destination during extraction.
        if any(p.exists() for p in destinations):
            raise MediaError('OUTPUT_EXISTS', 'Output appeared during extraction; not replacing it')
        # Single-writer output directory required; consumers must require both files.
        temp_audio.rename(destinations[0])
        temp_report.rename(destinations[1])
    return info


def environment(ffmpeg: str | None, ffprobe: str | None) -> dict:
    result = {'kind': 'b_environment_check', 'python': sys.version, 'executable': sys.executable,
              'planned_python': '3.11', 'python_matches_plan': sys.version_info[:2] == (3, 11),
              'platform': platform.platform(), 'modules': {}, 'tools': {}}
    for name in ['langgraph', 'pydantic', 'faster_whisper', 'pyannote', 'torch']:
        result['modules'][name] = {'discoverable': importlib.util.find_spec(name) is not None,
                                    'runtime_verified': False}
    for name, override in [('ffmpeg', ffmpeg), ('ffprobe', ffprobe)]:
        try:
            binary = tool_path(name, override)
            result['tools'][name] = {'path': binary, 'version': run([binary, '-version']).stdout.splitlines()[0]}
            if name == 'ffmpeg':
                filters = run([binary, '-hide_banner', '-filters']).stdout
                result['tools'][name]['subtitles_filter'] = any(' subtitles ' in line for line in filters.splitlines())
        except MediaError as exc:
            result['tools'][name] = {'error': exc.code, 'message': str(exc)}
    return result


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest='action', required=True)
    for action in ['check', 'inspect', 'extract']:
        c = sub.add_parser(action)
        c.add_argument('--ffprobe')
        c.add_argument('--ffmpeg')
        if action != 'check':
            c.add_argument('--input', type=Path, required=True, help='Local video file only; no URLs')
            c.add_argument('--audio-stream', type=int, help='Absolute ffprobe stream index')
            c.add_argument('--video-stream', type=int, help='Absolute ffprobe stream index')
        if action == 'extract':
            c.add_argument('--output', type=Path, required=True)
            c.add_argument('--timeout', type=float, default=120, help='Extraction timeout in seconds')
    return p


def main(argv: list[str] | None = None) -> int:
    for stream in [sys.stdout, sys.stderr]:
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8')
    args = parser().parse_args(argv)
    try:
        if args.action == 'check':
            result = environment(args.ffmpeg, args.ffprobe)
        else:
            if args.action == 'extract' and (args.timeout <= 0 or args.timeout > 3600 or not math.isfinite(args.timeout)):
                raise MediaError('CONFIG_INVALID', 'timeout must be finite and in (0, 3600]')
            probe_exe = tool_path('ffprobe', args.ffprobe)
            if args.action == 'inspect':
                result = inspect(args.input, probe_exe, args.audio_stream, args.video_stream)
            else:
                result = extract(args.input, args.output, probe_exe, tool_path('ffmpeg', args.ffmpeg),
                                 args.audio_stream, args.video_stream, args.timeout)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        if args.action == 'check' and any('error' in t for t in result['tools'].values()):
            return 3
        return 0
    except MediaError as exc:
        print(json.dumps({'ok': False, 'code': exc.code, 'message': str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 3
    except OSError as exc:
        print(json.dumps({'ok': False, 'code': 'FILESYSTEM_ERROR', 'message': str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 3


if __name__ == '__main__':
    raise SystemExit(main())
