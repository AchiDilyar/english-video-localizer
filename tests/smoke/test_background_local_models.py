"""Opt-in real local Demucs/AST + FFmpeg; no translation, enrollment or TTS calls.

LOCALIZER_TEST_BACKGROUND_VIDEO must name an existing public/authorized MP4.
LOCALIZER_TEST_BACKGROUND_SEGMENTS optionally names B's verified segments JSON.
uv run --no-sync pytest -m slow tests/smoke/test_background_local_models.py -q -s
"""

import json
import os
import subprocess
from pathlib import Path
from time import perf_counter

import pytest
from contracts import GraphState, Segment
from nodes.b_environment import b_environment
from nodes.mix_background import mix_background, select_mix_or_dub
from nodes.probe_input.node import probe_input
from nodes.probe_input.media import probe, tool_path
from nodes.tts_align import resolve_ffmpeg
from utils.paths import artifact_path, set_work_dir


@pytest.mark.slow
def test_real_local_background(tmp_path):
    source = os.getenv('LOCALIZER_TEST_BACKGROUND_VIDEO')
    if not source:
        pytest.skip('Set an authorized local test video to opt in')
    source = Path(source).resolve()
    set_work_dir(str(tmp_path))
    (tmp_path / 'audio').mkdir()
    state = GraphState(input_video=str(source))
    state = state.model_copy(update=probe_input(state))
    segment_file = os.getenv('LOCALIZER_TEST_BACKGROUND_SEGMENTS')
    if segment_file:
        data = json.loads(Path(segment_file).read_text(encoding='utf-8'))
        segments = [Segment.model_validate(item) for item in data]
    else:
        # Empty recognized speech is only a local integration fixture, not ASR evidence.
        segments = []
    state = state.model_copy(update={'segments': segments})
    started = perf_counter()
    state = state.model_copy(update=b_environment(state))
    # Known synthetic speech stand-in to exercise real mix without paid voice generation.
    duration = state.media_info.duration_ms / 1000
    dub = Path(artifact_path('dub_audio'))
    subprocess.run([resolve_ffmpeg(), '-v', 'error', '-y', '-f', 'lavfi', '-i',
                    f'sine=frequency=800:duration={duration}', '-ar', '24000', str(dub)], check=True)
    state = state.model_copy(update=mix_background(state))
    mixed = select_mix_or_dub(state, dub, source)
    assert mixed == Path(artifact_path('mixed_track'))
    measured = probe(mixed, tool_path('ffprobe', None))
    assert abs(float(measured['format']['duration']) - duration) < 0.05
    assert state.environment_audio is not None and state.mixed_audio is not None
    report = {'source': str(source), 'duration_sec': duration, 'elapsed_sec': perf_counter() - started,
              'environment': str(artifact_path('environment_bed')), 'mixed': str(mixed),
              'restored_intervals_ms': state.environment_audio.restored_intervals_ms,
              'paid_api_calls': 0, 'dub_is_synthetic_fixture': True,
              'human_audition_confirmed': False}
    (tmp_path / 'background-validation.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
