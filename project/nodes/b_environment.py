"""B incremental node in F's main graph: local separation and guarded event restoration."""

from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Literal

from contracts import EnvironmentAudio, GraphState
from pydantic import BaseModel, ConfigDict, Field
from utils.config import load_config
from utils.io import write_artifact
from utils.paths import artifact_path

from .background_audio import digest, separate
from .probe_input.node import input_path
from .tts_align import resolve_ffmpeg

logger = logging.getLogger(__name__)


class EnvironmentOptions(BaseModel):
    model_config = ConfigDict(extra="forbid")
    model_dir: str = "models/background-demucs"
    event_model_dir: str = "models/ast-audioset"
    device: Literal["cpu", "cuda"] = "cpu"
    restore_nonverbal: bool = True
    event_threshold: float = Field(default=0.2, ge=0, le=1)
    speech_guard_sec: float = Field(default=0.08, ge=0, le=1)
    nonverbal_gain: float = Field(default=0.8, ge=0, le=1)


def segments_digest(segments) -> str:
    data = [segment.model_dump(mode="json") for segment in segments]
    return hashlib.sha256(json.dumps(data, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def _model_path(value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else Path(__file__).resolve().parents[2] / path


def _event_gaps(segments, duration: float, padding: float):
    """Only propose events outside recognized sentence spans; no private word-time dependency."""
    cursor = 0.0
    gaps = []
    for segment in sorted(segments, key=lambda item: item.start_ms):
        left = max(0, segment.start_ms / 1000 - padding)
        if left - cursor >= 0.12:
            gaps.append((cursor, min(left, duration)))
        cursor = max(cursor, min(duration, segment.end_ms / 1000 + padding))
    if duration - cursor >= 0.12:
        gaps.append((cursor, duration))
    # AST takes <=10s features; use <=3s windows with their actual bounds.
    return [
        (a + offset / 1000, min(b, a + offset / 1000 + 3))
        for a, b in gaps
        for offset in range(0, int((b - a) * 1000), 3000)
        if min(b, a + offset / 1000 + 3) - (a + offset / 1000) >= 0.12
    ]


def b_environment(state: GraphState) -> dict:
    """Return only incremental metadata; registry proxy owns failure isolation."""
    if state.media_info is None or state.segments is None:
        raise ValueError("b_environment requires media_info and segments")
    options = EnvironmentOptions.model_validate(load_config("b_environment.toml"))
    source = input_path(state)
    source_sha256 = digest(source)
    duration = state.media_info.duration_ms / 1000
    ffmpeg = resolve_ffmpeg()
    output = Path(artifact_path("environment_bed"))
    output.parent.mkdir(parents=True, exist_ok=True)
    logger.info("b_environment: local Demucs separation, duration=%.3fs, device=%s", duration, options.device)
    # Partial media, separation stems and event features are private and cleaned on failure.
    with TemporaryDirectory(prefix=".b-environment-", dir=output.parent) as tmp:
        work = Path(tmp)
        separate(
            source,
            work,
            ffmpeg,
            _model_path(options.model_dir),
            device=options.device,
            allow_download=False,
        )
        bed = work / "background.wav"
        intervals = []
        if options.restore_nonverbal:
            from .nonverbal_events import classify, features, guarded_intervals, restore_nonverbal

            gaps = _event_gaps(state.segments, duration, options.speech_guard_sec)
            if gaps:
                logger.info("b_environment: checking %d speech-free event windows", len(gaps))
                feature_file, events = work / "events.npz", work / "events.json"
                features(work / "vocals.wav", feature_file, ffmpeg, intervals=gaps)
                classify(feature_file, _model_path(options.event_model_dir), events)
                words = [
                    {"start": s.start_ms / 1000, "end": s.end_ms / 1000} for s in state.segments
                ]
                intervals = guarded_intervals(
                    json.loads(events.read_text(encoding="utf-8"))["windows"],
                    words,
                    threshold=options.event_threshold,
                    padding=options.speech_guard_sec,
                )
                restored = work / "restored.wav"
                restore_nonverbal(
                    bed,
                    work / "vocals.wav",
                    intervals,
                    restored,
                    ffmpeg,
                    gain=options.nonverbal_gain,
                )
                bed = restored
        if digest(source) != source_sha256:
            raise ValueError("Source changed during background separation")
        receipt = EnvironmentAudio(
            source_sha256=source_sha256,
            segments_sha256=segments_digest(state.segments),
            environment_sha256=digest(bed),
            duration_sec=duration,
            restored_intervals_ms=[(round(a * 1000), round(b * 1000)) for a, b in intervals],
        )
        bed.replace(output)
        write_artifact("environment_audio", receipt)
    logger.info("b_environment: published environment.wav, restored nonverbal intervals=%d", len(intervals))
    return {"environment_audio": receipt}
