"""全片时间轴分段模型。"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Segment(BaseModel):
    """全片时间轴分段，由 asr_diarize 生成，落盘为 segments/segments.json。"""

    model_config = ConfigDict(extra="forbid")

    segment_id: str = Field(
        pattern=r"^seg_\d{4,}$",
        description="全片唯一分段 ID，格式 seg_ 加至少 4 位数字，如 seg_0001",
    )
    speaker_id: str = Field(
        pattern=r"^spk_[A-Za-z0-9_]+$",
        description="全片唯一说话人 ID，格式 spk_ 加字母数字下划线，如 spk_1",
    )
    start_ms: int = Field(ge=0, description="起始时间，毫秒整数")
    end_ms: int = Field(gt=0, description="结束时间，毫秒整数，必须大于 start_ms")
    text_en: str = Field(description="英文转写文本")

    @model_validator(mode="after")
    def _check_time_range(self) -> "Segment":
        if self.end_ms <= self.start_ms:
            raise ValueError("end_ms 必须大于 start_ms")
        return self