"""Probe a local MP4; return typed media information without writing files."""
import logging
from pathlib import Path

from contracts import AudioStreamInfo, GraphState, MediaInfo, VideoStreamInfo
from pydantic import BaseModel, ConfigDict, Field

from . import integration, media

logger = logging.getLogger(__name__)


class ProbeOptions(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ffprobe: str | None = None
    ffmpeg: str | None = None
    audio_stream: int | None = Field(default=None, ge=0)
    video_stream: int | None = Field(default=None, ge=0)


def input_path(state: GraphState) -> Path:
    if not isinstance(state, GraphState):
        raise TypeError("Node input must be a contracts.GraphState instance")
    filename = state.input_video
    if not filename or (not Path(filename).is_absolute() and ("/" in filename or "\\" in filename)):
        raise ValueError("input_video must be a filename or an explicit absolute source path")
    path = Path(integration.artifact_path("input_video", filename))
    if path.suffix.lower() != ".mp4":
        raise ValueError("The team basic workflow accepts a local MP4")
    if not path.is_file():
        raise FileNotFoundError(path)
    return path


def inspect_input(state: GraphState):
    options = ProbeOptions.model_validate(integration.load_config("probe_input.toml"))
    path = input_path(state)
    info = media.inspect(
        path, media.tool_path("ffprobe", options.ffprobe), options.audio_stream, options.video_stream
    )
    if not info["duration_ms"]:
        raise ValueError("A positive video duration is required")
    return path, info, options


def frame_rate(value) -> float | None:
    if not value:
        return None
    numerator, _, denominator = str(value).partition("/")
    try:
        rate = float(numerator) / float(denominator or "1")
    except (ValueError, ZeroDivisionError):
        return None
    return rate if rate > 0 else None


def probe_input(state: GraphState) -> dict:
    _, info, _ = inspect_input(state)
    streams = info["probe_raw"]["streams"]
    video = next(s for s in streams if s["index"] == info["video_stream_index"])
    audio = next(s for s in streams if s["index"] == info["audio_stream_index"])
    result = MediaInfo(
        duration_ms=info["duration_ms"],
        video_info=VideoStreamInfo(
            codec=video["codec_name"], width=video["width"], height=video["height"],
            fps=frame_rate(video.get("avg_frame_rate") or video.get("r_frame_rate")),
        ),
        audio_info=AudioStreamInfo(
            codec=audio["codec_name"], sample_rate=int(audio["sample_rate"]),
            channels=audio["channels"],
        ),
        ffprobe_raw=info["probe_raw"],
    )
    logger.info("Media probe completed: duration_ms=%d", result.duration_ms)
    return {"media_info": result}
