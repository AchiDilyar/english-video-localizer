"""产物规格表。

事实源：dataflow.md 第 3 节产物表。两者不一致时以 dataflow.md 为准。
每个名称映射到：
- path_kind：路径规则（"fixed" / "dir"）
- path：fixed 为完整相对路径；dir 为文件夹相对路径，空字符串表示工作目录根
- type_：落盘 JSON 的 Pydantic 校验类型；二进制产物为 None
"""

from __future__ import annotations

from typing import Any, Literal

from contracts import Segment, TranslatedSegment, TranslationBlock, TTSClip
from pydantic import BaseModel, ConfigDict, model_validator


class ArtifactSpec(BaseModel):
    model_config = ConfigDict(frozen=True)

    path: str
    path_kind: Literal["fixed", "dir"]
    # type_ 用 Any 而非 type：list[Segment] 是 types.GenericAlias，
    # isinstance(list[Segment], type) 为 False，标 type 会被 Pydantic 拒绝。
    type_: Any = None

    @model_validator(mode="after")
    def _check_path(self) -> "ArtifactSpec":
        if self.path_kind == "fixed" and not self.path:
            raise ValueError("path_kind='fixed' 时 path 不能为空")
        return self


ARTIFACT_SPECS: dict[str, ArtifactSpec] = {
    # 结构化 JSON 产物
    "segments": ArtifactSpec(
        path="segments/segments.json", path_kind="fixed", type_=list[Segment]
    ),
    "blocks": ArtifactSpec(
        path="segments/blocks.json", path_kind="fixed", type_=list[TranslationBlock]
    ),
    "translated_blocks": ArtifactSpec(
        path="translated/translated_blocks.json",
        path_kind="fixed",
        type_=list[TranslatedSegment],
    ),
    "reviewed_blocks": ArtifactSpec(
        path="translated/reviewed_blocks.json",
        path_kind="fixed",
        type_=list[TranslatedSegment],
    ),
    "repaired_blocks": ArtifactSpec(
        path="translated/repaired_blocks.json",
        path_kind="fixed",
        type_=list[TranslatedSegment]
    ),
    "tts_clips": ArtifactSpec(
        path="tts/clips.json", path_kind="fixed", type_=list[TTSClip]
    ),
    # 二进制产物，路径确定
    "source_audio": ArtifactSpec(path="audio/source.wav", path_kind="fixed"),
    "dub_audio": ArtifactSpec(path="audio/dub.wav", path_kind="fixed"),
    "english_srt": ArtifactSpec(path="subtitles/english_segmented.srt", path_kind="fixed"),
    "chinese_srt": ArtifactSpec(path="subtitles/chinese.srt", path_kind="fixed"),
    "bilingual_srt": ArtifactSpec(path="subtitles/bilingual.srt", path_kind="fixed"),
    "burnin_subtitle": ArtifactSpec(path="subtitles/burnin.ass", path_kind="fixed"),
    "final_video": ArtifactSpec(path="video/final.mp4", path_kind="fixed"),
    # 二进制产物，路径不确定（path="" 表示工作目录根）
    "input_video": ArtifactSpec(path="", path_kind="dir"),
    "tts_audio": ArtifactSpec(path="tts", path_kind="dir"),
}
