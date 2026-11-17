"""逐段 TTS 音频记录模型。"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class TTSClip(BaseModel):
    """
    音频文件落盘于 tts/ 下，完整路径通过 artifact_path("tts_audio", filename) 获取；audio_path 只保存文件名。
    本数据类的结构化清单落盘为 tts/clips.json，产物名 tts_clips。
    """

    model_config = ConfigDict(extra="forbid")

    segment_id: str = Field(
        pattern=r"^seg_\d{4,}$",
        description="对应分段 ID，沿用 Segment.segment_id",
    )
    audio_path: str = Field(
        pattern=r"^[\w.-]+\.wav$",
        description="音频文件名，如 seg_0001.wav；完整路径由 artifact_path 生成",
    )
    duration_ms: int = Field(ge=0, description="实测音频时长，毫秒整数")
    text: str = Field(description="合成所用中文口播稿文本")
    voice_id: str = Field(description="合成所用音色标识")
    model: str = Field(description="合成所用模型标识")