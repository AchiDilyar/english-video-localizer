"""输入视频媒体信息模型。"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class VideoStreamInfo(BaseModel):
    """视频流信息。"""

    model_config = ConfigDict(extra="forbid")

    codec: str = Field(description="视频编码，如 h264")
    width: int = Field(gt=0, description="宽度，像素")
    height: int = Field(gt=0, description="高度，像素")
    fps: float | None = Field(default=None, description="帧率；ffprobe 无法解析时为 None")


class AudioStreamInfo(BaseModel):
    """音频流信息。"""

    model_config = ConfigDict(extra="forbid")

    codec: str = Field(description="音频编码，如 aac")
    sample_rate: int = Field(gt=0, description="采样率，Hz")
    channels: int = Field(gt=0, description="声道数")


class MediaInfo(BaseModel):
    """输入视频的媒体信息，不落盘，仅在 GraphState 中传递。"""

    model_config = ConfigDict(extra="forbid")

    duration_ms: int = Field(ge=0, description="视频时长，毫秒整数")
    video_info: VideoStreamInfo
    audio_info: AudioStreamInfo
    ffprobe_raw: dict[str, Any] = Field(description="ffprobe 原始输出，供排查使用")