"""发布文案模型。"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class EditAssets(BaseModel):
    """发布文案，由 edit_assets 生成，不落盘，仅在 GraphState 中传递。

    package_zip 从 GraphState 读取，序列化为 ZIP 内 edit_assets.json，
    并在 PackageManifest 中作为普通 ManifestEntry 列出。
    """

    model_config = ConfigDict(extra="forbid")

    title: str = Field(description="标题")
    description: str = Field(description="简介")
    cover_text: str = Field(description="封面文案")