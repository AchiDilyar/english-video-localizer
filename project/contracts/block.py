"""翻译与审校单位模型。"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class TranslationBlock(BaseModel):
    """翻译块，由 build_blocks 生成，落盘为 segments/blocks.json。"""

    model_config = ConfigDict(extra="forbid")

    block_id: str = Field(
        pattern=r"^blk_\d{4,}$",
        description="全片唯一翻译块 ID，格式 blk_ 加至少 4 位数字，如 blk_0001",
    )
    segment_ids: list[str] = Field(
        min_length=1,
        description="该翻译块包含的分段 ID，按时间顺序排列",
    )