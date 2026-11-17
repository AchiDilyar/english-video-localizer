"""review_blocks mock 的验证用例。

运行：
    uv run pytest tests/mocks/test_review_blocks.py -q

工作目录固定在 tests/tmp/mocks/review_blocks/<用例名>/，用例前清空、用例后保留。
本节点不读输入视频，fixture 不复制视频。
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path

import pytest

import utils.paths
from contracts import GraphState, Segment, TranslatedSegment
from mocks import review_blocks as mock_module
from utils.io import read_artifact

_REPO_ROOT = Path(__file__).resolve().parents[2]
_TMP_ROOT = _REPO_ROOT / "tests" / "tmp" / "mocks" / "review_blocks"

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
    utils.paths.set_work_dir(str(path))
    return path


def _segment(index: int) -> Segment:
    start_ms = (index - 1) * 1000
    return Segment(
        segment_id=f"seg_{index:04d}",
        speaker_id="spk_1",
        start_ms=start_ms,
        end_ms=start_ms + 800,
        text_en=f"sentence {index}",
    )


def _translated(index: int, *, zh: str | None = None) -> TranslatedSegment:
    return TranslatedSegment(
        segment_id=f"seg_{index:04d}",
        block_id="blk_0001",
        zh_subtitle=zh if zh is not None else f"译文 {index}",
    )


def _messages(caplog) -> list[str]:
    return [record.getMessage() for record in caplog.records]


def test_passes_through_translated_blocks(work_dir):
    segments = [_segment(index) for index in range(1, 12)]
    translated = [_translated(index) for index in range(1, 12)]

    result = mock_module.review_blocks(
        GraphState(segments=segments, translated_blocks=translated)
    )

    reviewed = result["reviewed_blocks"]
    assert reviewed == translated
    assert [item.segment_id for item in reviewed] == [
        item.segment_id for item in translated
    ]
    assert read_artifact("reviewed_blocks") == translated


def test_coverage_mismatch_warns_but_keeps_data(work_dir, caplog):
    segments = [_segment(index) for index in range(1, 4)]
    translated = [_translated(1), _translated(2)]

    with caplog.at_level(logging.WARNING, logger=mock_module.__name__):
        result = mock_module.review_blocks(
            GraphState(segments=segments, translated_blocks=translated)
        )

    assert result["reviewed_blocks"] == translated
    messages = _messages(caplog)
    assert any("[覆盖不符]" in message and "seg_0003" in message for message in messages), (
        messages
    )


def test_none_segments_raises(work_dir):
    with pytest.raises(ValueError):
        mock_module.review_blocks(GraphState(translated_blocks=[_translated(1)]))


def test_empty_segments_warns_and_returns_empty(work_dir, caplog):
    with caplog.at_level(logging.WARNING, logger=mock_module.__name__):
        result = mock_module.review_blocks(
            GraphState(segments=[], translated_blocks=[_translated(1)])
        )

    assert result["reviewed_blocks"] == []
    assert read_artifact("reviewed_blocks") == []
    assert any("[segments 为空]" in message for message in _messages(caplog))


def test_none_translated_blocks_raises(work_dir):
    with pytest.raises(ValueError):
        mock_module.review_blocks(GraphState(segments=[_segment(1)]))


def test_empty_translated_blocks_warns_and_returns_empty(work_dir, caplog):
    with caplog.at_level(logging.WARNING, logger=mock_module.__name__):
        result = mock_module.review_blocks(
            GraphState(segments=[_segment(1)], translated_blocks=[])
        )

    assert result["reviewed_blocks"] == []
    assert read_artifact("reviewed_blocks") == []
    assert any("[translated_blocks 为空]" in message for message in _messages(caplog))


def test_duplicate_translated_id_raises(work_dir):
    with pytest.raises(ValueError, match="重复"):
        mock_module.review_blocks(
            GraphState(
                segments=[_segment(1)],
                translated_blocks=[_translated(1), _translated(1)],
            )
        )


def test_duplicate_segment_id_raises(work_dir):
    with pytest.raises(ValueError, match="重复"):
        mock_module.review_blocks(
            GraphState(
                segments=[_segment(1), _segment(1)],
                translated_blocks=[_translated(1)],
            )
        )


def test_rerun_overwrites_artifact(work_dir):
    state = GraphState(
        segments=[_segment(1), _segment(2)],
        translated_blocks=[_translated(1), _translated(2)],
    )

    first = mock_module.review_blocks(state)
    second = mock_module.review_blocks(state)

    assert first["reviewed_blocks"] == second["reviewed_blocks"]
    assert read_artifact("reviewed_blocks") == second["reviewed_blocks"]
