"""翻译结果与审校结果元素模型。"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class TranslatedSegment(BaseModel):
    """翻译结果与审校结果的元素，两者同构。

    翻译结果落盘为 translated/translated_blocks.json，
    审校结果落盘为 translated/reviewed_blocks.json。
    不保留 en 原文与冗余时间戳，原文与时间戳通过 segment_id 回溯 segments。
    """

    model_config = ConfigDict(extra="forbid")

    segment_id: str = Field(
        pattern=r"^seg_\d{4,}$",
        description="对应分段 ID，沿用 Segment.segment_id",
    )
    block_id: str = Field(
        pattern=r"^blk_\d{4,}$",
        description="所属翻译块 ID，沿用 TranslationBlock.block_id",
    )
    zh_subtitle: str = Field(description="中文文本")
    zh_dub: str | None = Field(description="该字段已弃用，请勿使用", default=None)