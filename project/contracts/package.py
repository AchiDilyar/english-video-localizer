"""发布包清单模型。"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class ManifestEntry(BaseModel):
    """发布包清单条目。"""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(description="产物名")
    zip_path: str = Field(description="ZIP 内相对路径，如 video/final.mp4")
    description: str | None = Field(default=None, description="可选说明")


class PackageManifest(BaseModel):
    """发布包清单，由 collect_manifest 生成，落盘为 package/manifest.json。

    entries 必须包含 manifest.json 自身，即存在一条
    name="manifest", zip_path="manifest.json" 的条目。
    """

    model_config = ConfigDict(extra="forbid")

    entries: list[ManifestEntry] = Field(
        min_length=1,
        description="发布包内文件清单",
    )