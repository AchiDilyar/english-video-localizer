"""流程顶层状态容器。"""

from __future__ import annotations

from typing import TypedDict

from .block import TranslationBlock
from .edit import EditAssets
from .media import MediaInfo
from .package import PackageManifest
from .segment import Segment
from .translated import TranslatedSegment
from .tts import TTSClip


class GraphState(TypedDict, total=False):
    """LangGraph 顶层状态。

    所有字段均为可选：流程初期很多字段尚不存在，节点按增量返回。
    列表字段的增量语义为覆盖，不是追加。
    """

    input_video: str
    media_info: MediaInfo
    segments: list[Segment]
    blocks: list[TranslationBlock]
    terminology: dict[str, str]
    translated_blocks: list[TranslatedSegment]
    reviewed_blocks: list[TranslatedSegment]
    tts_clips: list[TTSClip]
    edit_assets: EditAssets
    manifest: PackageManifest