"""E: final-time single-line pages, environment mix and video delivery."""
from pathlib import Path
from utils.paths import artifact_path
from .common import run_nodes,resolve_stage_nodes


def mix_prepared_environment(state):
    from nodes.audio_mixing import mix_background
    from nodes.tts_align import resolve_ffmpeg
    audio=Path(artifact_path('dub_audio'));bed=audio.with_name('environment.wav')
    if bed.exists():
        import json
        from nodes.background_audio import digest
        from nodes.probe_input.node import input_path
        source=input_path(state);receipt=bed.with_suffix('.source.json')
        if not receipt.is_file():raise ValueError('B_ENVIRONMENT_PROVENANCE_REQUIRED')
        evidence=json.loads(receipt.read_text(encoding='utf-8'))
        if (evidence.get('source_sha256'),evidence.get('environment_sha256'))!=(digest(source),digest(bed)):
            raise ValueError('B environment belongs to another source or has changed')
        mix_background(bed,audio,audio.with_name('mixed.wav'),ffmpeg=resolve_ffmpeg(),
            duration_sec=state.media_info.duration_ms/1000,source_video=source)
    return {}


def run_e(state,nodes=None):
    if nodes is None:
        subtitle_cover,compose_video=resolve_stage_nodes(('subtitle_cover','compose_video'))
        nodes=(subtitle_cover,mix_prepared_environment,compose_video)
    return run_nodes(state,nodes)
