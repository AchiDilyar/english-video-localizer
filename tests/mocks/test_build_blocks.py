"""build_blocks mock 的验证用例。

运行：
    uv run pytest tests/mocks/test_build_blocks.py -q

工作目录固定在 tests/tmp/mocks/build_blocks/<用例名>/，用例前清空、用例后保留。
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path

import pytest

import utils.paths
from contracts import GraphState, Segment
from mocks import build_blocks as mock_module
from utils.io import read_artifact

_REPO_ROOT = Path(__file__).resolve().parents[2]
_TMP_ROOT = _REPO_ROOT / "tests" / "tmp" / "mocks" / "build_blocks"

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


def _segments(count: int, *, step_ms: int = 1000, gap_ms: int = 200) -> list[Segment]:
    """构造 count 条按时间递增的分段。"""
    segments = []
    for index in range(count):
        start_ms = index * step_ms
        segments.append(
            Segment(
                segment_id=f"seg_{index + 1:04d}",
                speaker_id="spk_1",
                start_ms=start_ms,
                end_ms=start_ms + step_ms - gap_ms,
                text_en=f"sentence {index + 1}",
            )
        )
    return segments


def _messages(caplog) -> list[str]:
    return [record.getMessage() for record in caplog.records]


def test_single_block_covers_all_segments(work_dir):
    segments = _segments(11)

    result = mock_module.build_blocks(GraphState(segments=segments))

    assert len(result["blocks"]) == 1
    block = result["blocks"][0]
    assert block.block_id == "blk_0001"
    assert block.segment_ids == [segment.segment_id for segment in segments]
    assert read_artifact("blocks") == result["blocks"]


def test_terminology_default_and_passthrough(work_dir):
    default = mock_module.build_blocks(GraphState(segments=_segments(2)))
    assert default["terminology"] == {"sample size": "样本量"}

    custom = mock_module.build_blocks(
        GraphState(segments=_segments(2), terminology={"alpha": "阿尔法"})
    )
    assert custom["terminology"] == {"alpha": "阿尔法"}


def test_none_segments_raises(work_dir):
    with pytest.raises(ValueError):
        mock_module.build_blocks(GraphState())


def test_empty_segments_returns_empty(work_dir):
    result = mock_module.build_blocks(GraphState(segments=[]))

    assert result["blocks"] == []
    assert result["terminology"] == {"sample size": "样本量"}
    assert read_artifact("blocks") == []


def test_duplicate_segment_id_raises(work_dir):
    segments = [
        Segment(
            segment_id="seg_0001",
            speaker_id="spk_1",
            start_ms=0,
            end_ms=500,
            text_en="a",
        ),
        Segment(
            segment_id="seg_0001",
            speaker_id="spk_1",
            start_ms=600,
            end_ms=900,
            text_en="b",
        ),
    ]

    with pytest.raises(ValueError, match="重复的分段 ID"):
        mock_module.build_blocks(GraphState(segments=segments))


def test_large_block_warns_by_count(work_dir, caplog):
    with caplog.at_level(logging.WARNING, logger=mock_module.__name__):
        result = mock_module.build_blocks(GraphState(segments=_segments(51)))

    assert len(result["blocks"][0].segment_ids) == 51
    messages = _messages(caplog)
    assert any("[单块过大]" in message and "分段数" in message for message in messages), (
        messages
    )


def test_large_block_warns_by_span(work_dir, caplog):
    with caplog.at_level(logging.WARNING, logger=mock_module.__name__):
        mock_module.build_blocks(GraphState(segments=_segments(2, step_ms=100_000)))

    messages = _messages(caplog)
    assert any("[单块过大]" in message and "跨度" in message for message in messages), (
        messages
    )


def test_small_block_no_warning(work_dir, caplog):
    with caplog.at_level(logging.WARNING, logger=mock_module.__name__):
        mock_module.build_blocks(GraphState(segments=_segments(11)))

    warnings = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert not warnings, f"小块不应产生 warning：{[r.getMessage() for r in warnings]}"


def test_rerun_overwrites_blocks(work_dir):
    state = GraphState(segments=_segments(11))
    first = mock_module.build_blocks(state)
    second = mock_module.build_blocks(state)

    assert first["blocks"] == second["blocks"]
    assert read_artifact("blocks") == second["blocks"]
