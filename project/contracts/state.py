"""流程顶层状态容器。"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from .block import TranslationBlock
from .edit import EditAssets
from .media import MediaInfo
from .package import PackageManifest
from .segment import Segment
from .translated import TranslatedSegment
from .tts import TTSClip


class GraphState(BaseModel):
    """LangGraph 顶层状态。

    所有字段均可选（默认 None）：流程初期很多字段尚不存在，节点按增量返回。
    列表字段的增量语义为覆盖，不是追加。
    """

    model_config = ConfigDict(extra="forbid")

    input_video: str | None = None
    media_info: MediaInfo | None = None
    segments: list[Segment] | None = None
    blocks: list[TranslationBlock] | None = None
    terminology: dict[str, str] | None = None
    translated_blocks: list[TranslatedSegment] | None = None
    reviewed_blocks: list[TranslatedSegment] | None = None
    tts_clips: list[TTSClip] | None = None
    edit_assets: EditAssets | None = None
    manifest: PackageManifest | None = None