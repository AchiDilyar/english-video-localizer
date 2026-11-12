import json
import subprocess
import sys
from pathlib import Path

import httpx
import pytest
from contracts import GraphState, Segment, TranslatedSegment
from nodes.build_blocks import build_blocks
from nodes.review_blocks import review_blocks
from nodes.translate_blocks import _text_model, translate_blocks
from utils import paths
from utils.io import read_artifact


def test_c_nodes_import_without_src():
    project = Path(__file__).resolve().parents[2] / "project"
    script = """
import sys

sys.path.insert(0, sys.argv[1])
sys.modules['video_localizer'] = None
from nodes.translate_blocks import translate_blocks
from nodes.review_blocks import review_blocks
assert callable(translate_blocks) and callable(review_blocks)
"""
    result = subprocess.run(
        [sys.executable, "-I", "-B", "-c", script, str(project)],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr


@pytest.fixture(autouse=True)
def artifact_work_dir(tmp_path, monkeypatch):
    for folder in ("segments", "translated"):
        (tmp_path / folder).mkdir()
    monkeypatch.setattr(paths, "_work_dir", None)
    paths.set_work_dir(str(tmp_path))


@pytest.fixture
def source_state():
    return GraphState(
        segments=[
            Segment(
                segment_id="seg_0001",
                speaker_id="spk_1",
                start_ms=0,
                end_ms=5_000,
                text_en="This works only if the sample size is at least 12.",
            ),
            Segment(
                segment_id="seg_0002",
                speaker_id="spk_1",
                start_ms=92_000,
                end_ms=95_000,
                text_en="Do not reduce the sample size.",
            ),
        ],
    )


def item(segment_id, subtitle):
    return {"segment_id": segment_id, "zh_subtitle": subtitle}


def test_build_translate_review_handoff_preserves_both_blocks(source_state, monkeypatch):
    calls = []

    def answer(*, instruction, payload):
        assert "句中的顿号、逗号、句号、分号和冒号统一替换为一个半角空格" in instruction
        assert "句末时直接省略，末尾不留空格" in instruction
        assert "问号和感叹号按语气正常使用，句末也可以保留" in instruction
        assert "中文双引号“…”或中文单引号‘…’" in instruction
        assert "小数点等属于数字或专有写法的一部分，按原意保留" in instruction
        assert "「先录音、再混音，最后做母带。」输出为「先录音 再混音 最后做母带」" in instruction
        assert "「先录音，还是先混音？」输出为「先录音 还是先混音？」" in instruction
        assert payload["terminology"] == {"sample size": "样本量"}
        (row,) = payload["segments"]
        segment_id = row["segment_id"]
        is_review = "zh_subtitle" in row
        calls.append((is_review, segment_id))
        if segment_id == "seg_0002":
            assert row["text_en"] == "Do not reduce the sample size."
            return {"items": [item(segment_id, "不要减少样本量。")]}
        if not is_review:
            assert row["duration_ms"] == 5_000
            return {"items": [item(segment_id, "这种方法有效。")]}
        assert row["zh_subtitle"] == "这种方法有效。"
        assert set(row) == {"segment_id", "text_en", "duration_ms", "zh_subtitle"}
        return {"items": [item(segment_id, "只有样本量至少为 12 时才有效。")]}

    monkeypatch.setattr(_text_model, "request_json", answer)
    state = source_state.model_copy(update=build_blocks(source_state))
    state = state.model_copy(update=translate_blocks(state))
    reviewed = review_blocks(state)["reviewed_blocks"]
    assert read_artifact("translated_blocks") == state.translated_blocks
    assert read_artifact("reviewed_blocks") == reviewed
    assert GraphState.model_validate(
        state.model_copy(update={"reviewed_blocks": reviewed}).model_dump()
    ).reviewed_blocks == reviewed

    assert calls == [
        (False, "seg_0001"),
        (False, "seg_0002"),
        (True, "seg_0001"),
        (True, "seg_0002"),
    ]
    assert [(row.segment_id, row.block_id) for row in reviewed] == [
        ("seg_0001", "blk_0001"), ("seg_0002", "blk_0002")
    ]
    assert reviewed[0].zh_subtitle == "只有样本量至少为 12 时才有效。"
    assert reviewed[1].zh_subtitle == "不要减少样本量。"
    assert state.translated_blocks[0].zh_subtitle == "这种方法有效。"
    for row in [*state.translated_blocks, *reviewed]:
        fields = row.model_dump()
        assert fields.keys() == TranslatedSegment.model_fields.keys()
        assert set(fields[name] for name in fields.keys() - {"block_id", "segment_id"}) == {
            row.zh_subtitle
        }


@pytest.mark.parametrize("items", [
    [],
    [item("seg_0002", "错误片段")],
    [item("seg_0001", "字幕"), item("seg_0001", "重复字幕")],
    [item("seg_0001", "  ")],
])
def test_translate_rejects_bad_model_output(source_state, monkeypatch, items):
    monkeypatch.setattr(_text_model, "request_json", lambda **kwargs: {"items": items})
    with pytest.raises(ValueError):
        translate_blocks(source_state.model_copy(update=build_blocks(source_state)))


def test_review_rejects_an_incomplete_response(source_state, monkeypatch):
    state = source_state.model_copy(update=build_blocks(source_state))
    state.translated_blocks = [
        *_text_model.validate_items({"items": [item("seg_0001", "字幕一")]}, "blk_0001", ["seg_0001"]),
        *_text_model.validate_items({"items": [item("seg_0002", "字幕二")]}, "blk_0002", ["seg_0002"]),
    ]
    monkeypatch.setattr(_text_model, "request_json", lambda **kwargs: {"items": []})
    with pytest.raises(ValueError, match="seg_0001"):
        review_blocks(state)


@pytest.mark.parametrize("config_location", ["environment", "installed"])
def test_request_uses_the_node_local_deepseek_adapter(monkeypatch, tmp_path, config_location):
    if config_location == "installed":
        package = tmp_path / "venv/Lib/site-packages/nodes/translate_blocks/_text_model.py"
        monkeypatch.setattr(_text_model, "__file__", str(package))
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
        monkeypatch.delenv("DEEPSEEK_MODEL", raising=False)
        (tmp_path / ".env").write_text(
            "DEEPSEEK_API_KEY=test-key\nDEEPSEEK_MODEL=test-model\n", encoding="utf-8"
        )
    else:
        monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
        monkeypatch.setenv("DEEPSEEK_MODEL", "test-model")
    client_class = httpx.Client

    def respond(request):
        body = json.loads(request.content)
        assert request.url.host == "api.deepseek.com"
        assert request.headers["Authorization"] == "Bearer test-key"
        assert body["model"] == "test-model"
        assert body["response_format"] == {"type": "json_object"}
        assert json.loads(body["messages"][1]["content"]) == {"segments": []}
        return httpx.Response(200, json={"choices": [{
            "finish_reason": "stop", "message": {"content": '{"items": []}'},
        }]})

    monkeypatch.setattr(
        httpx, "Client", lambda **options: client_class(
            transport=httpx.MockTransport(respond), **options
        )
    )
    assert _text_model.request_json(instruction="测试", payload={"segments": []}) == {"items": []}
