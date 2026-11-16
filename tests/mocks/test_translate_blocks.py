"""translate_blocks mock 的验证用例。

运行：
    uv run pytest tests/mocks/test_translate_blocks.py -q

工作目录固定在 tests/tmp/mocks/translate_blocks/<用例名>/，用例前清空、用例后保留。
"""

from __future__ import annotations

import json
import logging
import shutil
from pathlib import Path

import pytest

import utils.paths
from contracts import GraphState, Segment, TranslationBlock
from mocks import translate_blocks as mock_module
from utils.io import read_artifact

_REPO_ROOT = Path(__file__).resolve().parents[2]
_TMP_ROOT = _REPO_ROOT / "tests" / "tmp" / "mocks" / "translate_blocks"
_ASR_DATA = _REPO_ROOT / "project" / "mocks" / "data" / "asr_diarize.json"
_TRANSLATIONS_DATA = _REPO_ROOT / "project" / "mocks" / "data" / "translate_blocks.json"
_DEMO_VIDEO = _REPO_ROOT / "tests" / "data" / "asr_diarize" / "real_dialogue" / "input.mp4"

# 与 cli.py 的 _SUBDIRS 同源：子目录由 CLI 创建，测试直接调节点时必须自己补上。
_SUBDIRS = ("audio", "segments", "translated", "tts", "subtitles", "video", "logs")


@pytest.fixture
def work_dir(request, monkeypatch):
    monkeypatch.setattr(utils.paths, "_work_dir", None)
    path = _TMP_ROOT / request.node.name
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True)
    for name in _SUBDIRS:
        (path / name).mkdir()
    shutil.copyfile(_DEMO_VIDEO, path / "input.mp4")
    utils.paths.set_work_dir(str(path))
    return path


def _state(*, segments, blocks) -> GraphState:
    """统一带上 input_video：指纹分支需要定位工作目录下的输入视频。"""
    return GraphState(input_video="input.mp4", segments=segments, blocks=blocks)


def _segment(index: int, *, text_en: str | None = None) -> Segment:
    start_ms = (index - 1) * 1000
    return Segment(
        segment_id=f"seg_{index:04d}",
        speaker_id="spk_1",
        start_ms=start_ms,
        end_ms=start_ms + 800,
        text_en=text_en if text_en is not None else f"sentence {index}",
    )


def _segments(count: int) -> list[Segment]:
    return [_segment(index) for index in range(1, count + 1)]


def _single_block(segments: list[Segment]) -> list[TranslationBlock]:
    return [
        TranslationBlock(
            block_id="blk_0001",
            segment_ids=[segment.segment_id for segment in segments],
        )
    ]


def _messages(caplog) -> list[str]:
    return [record.getMessage() for record in caplog.records]


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_covers_all_segments_with_static_translations(work_dir):
    segments = _segments(11)

    result = mock_module.translate_blocks(
        _state(segments=segments, blocks=_single_block(segments))
    )

    drafts = result["translated_blocks"]
    assert len(drafts) == 11
    assert drafts[0].zh_subtitle == "是啊，能来这里我非常激动。"
    assert drafts[-1].zh_subtitle == "其实我经常做这类事。"
    assert {draft.block_id for draft in drafts} == {"blk_0001"}
    assert read_artifact("translated_blocks") == drafts


def test_data_covers_all_segment_ids(work_dir):
    translations = _read_json(_TRANSLATIONS_DATA)["translations"]
    upstream_ids = {item["segment_id"] for item in _read_json(_ASR_DATA)["segments"]}

    assert set(translations) == upstream_ids


def test_duplicate_block_membership_warns_and_uses_first(work_dir, caplog):
    segments = _segments(2)
    blocks = [
        TranslationBlock(block_id="blk_0001", segment_ids=["seg_0001"]),
        TranslationBlock(block_id="blk_0002", segment_ids=["seg_0001", "seg_0002"]),
    ]

    with caplog.at_level(logging.WARNING, logger=mock_module.__name__):
        result = mock_module.translate_blocks(_state(segments=segments, blocks=blocks))

    by_id = {draft.segment_id: draft.block_id for draft in result["translated_blocks"]}
    assert by_id["seg_0001"] == "blk_0001"
    assert by_id["seg_0002"] == "blk_0002"
    assert any("[重复归属]" in message for message in _messages(caplog))


def test_uncovered_segment_warns_and_is_omitted(work_dir, caplog):
    segments = _segments(3)
    blocks = [TranslationBlock(block_id="blk_0001", segment_ids=["seg_0001"])]

    with caplog.at_level(logging.WARNING, logger=mock_module.__name__):
        result = mock_module.translate_blocks(_state(segments=segments, blocks=blocks))

    drafts = result["translated_blocks"]
    assert [draft.segment_id for draft in drafts] == ["seg_0001"]
    messages = _messages(caplog)
    assert any(
        "[未覆盖]" in message and "seg_0002" in message and "seg_0003" in message
        for message in messages
    ), messages


def test_empty_blocks_warns_and_returns_empty(work_dir, caplog):
    with caplog.at_level(logging.WARNING, logger=mock_module.__name__):
        result = mock_module.translate_blocks(_state(segments=_segments(2), blocks=[]))

    assert result["translated_blocks"] == []
    assert read_artifact("translated_blocks") == []
    assert any("[blocks 为空]" in message for message in _messages(caplog))


def test_none_blocks_raises(work_dir):
    with pytest.raises(ValueError):
        mock_module.translate_blocks(_state(segments=_segments(2), blocks=None))


def test_none_segments_raises(work_dir):
    with pytest.raises(ValueError):
        mock_module.translate_blocks(_state(segments=None, blocks=[]))


def test_empty_segments_returns_empty(work_dir, caplog):
    with caplog.at_level(logging.WARNING, logger=mock_module.__name__):
        result = mock_module.translate_blocks(_state(segments=[], blocks=[]))

    assert result["translated_blocks"] == []
    assert read_artifact("translated_blocks") == []
    assert any("[segments 为空]" in message for message in _messages(caplog))


def test_duplicate_segment_id_raises(work_dir):
    segments = [_segment(1), _segment(1)]
    blocks = [TranslationBlock(block_id="blk_0001", segment_ids=["seg_0001"])]

    with pytest.raises(ValueError, match="重复的分段 ID"):
        mock_module.translate_blocks(_state(segments=segments, blocks=blocks))


def test_unknown_segment_uses_fallback_text(work_dir, caplog):
    segments = [_segment(1), _segment(99)]
    blocks = _single_block(segments)

    with caplog.at_level(logging.WARNING, logger=mock_module.__name__):
        result = mock_module.translate_blocks(_state(segments=segments, blocks=blocks))

    drafts = {draft.segment_id: draft.zh_subtitle for draft in result["translated_blocks"]}
    assert drafts["seg_0001"] == "是啊，能来这里我非常激动。"
    assert drafts["seg_0099"].startswith("[模拟译文]")
    assert any("[译文缺失]" in message for message in _messages(caplog))


def test_rerun_overwrites_artifact(work_dir):
    segments = _segments(11)
    state = _state(segments=segments, blocks=_single_block(segments))

    first = mock_module.translate_blocks(state)
    second = mock_module.translate_blocks(state)

    assert first["translated_blocks"] == second["translated_blocks"]
    assert read_artifact("translated_blocks") == second["translated_blocks"]


def test_hash_match_uses_static_translations(work_dir, caplog):
    segments = _segments(11)

    with caplog.at_level(logging.WARNING, logger=mock_module.__name__):
        result = mock_module.translate_blocks(
            _state(segments=segments, blocks=_single_block(segments))
        )

    drafts = {draft.segment_id: draft.zh_subtitle for draft in result["translated_blocks"]}
    assert drafts["seg_0001"] == "是啊，能来这里我非常激动。"
    assert not any("[指纹不符]" in message for message in _messages(caplog))


def test_hash_mismatch_warns_and_uses_fallback(work_dir, caplog, monkeypatch):
    data = mock_module._load_data()
    doctored = dict(data)
    doctored["source"] = dict(
        data["source"], size_bytes=data["source"]["size_bytes"] + 1
    )
    monkeypatch.setattr(mock_module, "_load_data", lambda: doctored)

    segments = _segments(11)
    with caplog.at_level(logging.WARNING, logger=mock_module.__name__):
        result = mock_module.translate_blocks(
            _state(segments=segments, blocks=_single_block(segments))
        )

    drafts = result["translated_blocks"]
    assert len(drafts) == 11
    assert all(draft.zh_subtitle.startswith("[模拟译文]") for draft in drafts)
    assert any("[指纹不符]" in message for message in _messages(caplog))
