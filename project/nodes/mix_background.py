"""E incremental node: mix only B's current, verified environment publication."""

from __future__ import annotations

import logging
from pathlib import Path
from tempfile import TemporaryDirectory

from contracts import GraphState, MixedAudio
from pydantic import BaseModel, ConfigDict, Field
from utils.config import load_config
from utils.io import write_artifact
from utils.paths import artifact_path

from .audio_mixing import mix_background as render_mix
from .b_environment import segments_digest
from .background_audio import digest
from .probe_input.node import input_path
from .tts_align import resolve_ffmpeg

logger = logging.getLogger(__name__)


class MixOptions(BaseModel):
    model_config = ConfigDict(extra="forbid")
    background_gain: float = Field(default=0.7, ge=0, le=1)


def mix_background(state: GraphState) -> dict:
    if state.environment_audio is None:
        return {}
    source = input_path(state)
    bed, dub = Path(artifact_path("environment_bed")), Path(artifact_path("dub_audio"))
    evidence = state.environment_audio
    if state.media_info is None or state.segments is None:
        raise ValueError("Missing source timeline for environment verification")
    if (evidence.source_sha256, evidence.environment_sha256, evidence.segments_sha256) != (
        digest(source),
        digest(bed),
        segments_digest(state.segments),
    ):
        raise ValueError("Environment does not match current source/segments/audio")
    duration = state.media_info.duration_ms / 1000
    if abs(duration - evidence.duration_sec) > 0.001:
        raise ValueError("Environment duration does not match current video")
    options = MixOptions.model_validate(load_config("mix_background.toml"))
    output = Path(artifact_path("mixed_track"))
    dub_sha256 = digest(dub)
    with TemporaryDirectory(prefix=".mix-background-", dir=output.parent) as tmp:
        prepared = Path(tmp) / "mixed.wav"
        render_mix(
            bed,
            dub,
            prepared,
            ffmpeg=resolve_ffmpeg(),
            duration_sec=duration,
            background_gain=options.background_gain,
            source_video=source,
        )
        if (digest(source), digest(bed), digest(dub)) != (
            evidence.source_sha256,
            evidence.environment_sha256,
            dub_sha256,
        ):
            raise ValueError("Source, environment or dub changed during mixing")
        receipt = MixedAudio(
            source_sha256=evidence.source_sha256,
            environment_sha256=evidence.environment_sha256,
            dub_sha256=dub_sha256,
            mixed_sha256=digest(prepared),
            duration_sec=duration,
        )
        prepared.replace(output)
        write_artifact("mixed_audio", receipt)
    return {"mixed_audio": receipt}


def select_mix_or_dub(state: GraphState, dub: Path, source: Path) -> Path:
    """Absent/failed incremental data never blocks basic composition or selects stale files."""
    if state.mixed_audio is None:
        return dub
    try:
        evidence = state.mixed_audio
        mixed = Path(artifact_path("mixed_track"))
        if state.environment_audio is None:
            raise ValueError("Mix receipt is not the current graph publication")
        if (
            evidence.source_sha256,
            evidence.dub_sha256,
            evidence.mixed_sha256,
            evidence.environment_sha256,
        ) != (
            digest(source),
            digest(dub),
            digest(mixed),
            state.environment_audio.environment_sha256,
        ):
            raise ValueError("Stale or modified background mix")
        if (
            state.media_info is None
            or abs(evidence.duration_sec - state.media_info.duration_ms / 1000) > 0.001
        ):
            raise ValueError("Mixed duration does not match current video")
        return mixed
    except (OSError, ValueError, KeyError) as exc:
        logger.warning("Optional mix unavailable; composing pure Chinese dub: %s", exc)
        return dub
