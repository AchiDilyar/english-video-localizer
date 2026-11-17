"""utils/artifacts.py 的规格表快照测试。

EXPECTED / JSON_ARTIFACTS / BINARY_ARTIFACTS 是当前已知的基础版产物快照，
不自动从 dataflow.md 解析。新增、删除或调整基础版产物时，需同步更新
这里的常量；本测试保证这些已知产物在 ARTIFACT_SPECS 中登记正确，
且 JSON / 二进制分类与校验类型一致。

ARTIFACT_SPECS 允许包含此处未列出的产物（如增量产物），本测试不要求严格相等。
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from utils.artifacts import ARTIFACT_SPECS, ArtifactSpec


# 当前已知的基础版产物快照；新增/删除基础版产物时同步更新。
EXPECTED = {
    "input_video", "source_audio", "segments", "blocks",
    "translated_blocks", "reviewed_blocks",
    "tts_clips", "tts_audio", "dub_audio",
    "bilingual_srt", "burnin_subtitle", "final_video",
}

JSON_ARTIFACTS = {
    "segments", "blocks", "translated_blocks", "reviewed_blocks",
    "tts_clips",
}

BINARY_ARTIFACTS = {
    "input_video", "source_audio", "tts_audio", "dub_audio",
    "bilingual_srt", "burnin_subtitle", "final_video",
}


def test_all_documented_names_registered() -> None:
    assert EXPECTED <= set(ARTIFACT_SPECS.keys())


def test_json_artifacts_have_type_and_fixed_path() -> None:
    for name in JSON_ARTIFACTS:
        spec = ARTIFACT_SPECS[name]
        assert spec.type_ is not None, f"{name} 是 JSON 产物，应有校验类型"
        assert spec.path_kind == "fixed", f"{name} 是 JSON 产物，应为 fixed"


def test_binary_artifacts_have_no_type() -> None:
    for name in BINARY_ARTIFACTS:
        assert ARTIFACT_SPECS[name].type_ is None, f"{name} 是二进制产物，校验类型应为 None"


def test_fixed_requires_path() -> None:
    with pytest.raises(ValidationError):
        ArtifactSpec(path="", path_kind="fixed")


def test_specs_are_frozen() -> None:
    spec = ARTIFACT_SPECS["segments"]
    with pytest.raises(ValidationError):
        spec.path = "x"