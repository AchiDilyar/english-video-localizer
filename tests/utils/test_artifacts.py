"""utils/artifacts.py 的验证：规格表结构与 dataflow.md 一致。"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from utils.artifacts import ARTIFACT_SPECS, ArtifactSpec


# dataflow.md §3 登记的全部产物名称
EXPECTED = {
    "input_video", "source_audio", "segments", "blocks",
    "translated_blocks", "reviewed_blocks",
    "tts_clips", "tts_audio", "dub_audio",
    "bilingual_srt", "burnin_subtitle", "cover_image",
    "final_video", "manifest", "final_zip",
}

JSON_ARTIFACTS = {
    "segments", "blocks", "translated_blocks", "reviewed_blocks",
    "tts_clips", "manifest",
}

BINARY_ARTIFACTS = {
    "input_video", "source_audio", "tts_audio", "dub_audio",
    "bilingual_srt", "burnin_subtitle", "cover_image", "final_video", "final_zip",
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