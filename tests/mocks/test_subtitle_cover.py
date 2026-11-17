"""subtitle_cover mock 的验证用例。

运行：
    uv run pytest tests/mocks/test_subtitle_cover.py -q

工作目录固定在 tests/tmp/mocks/subtitle_cover/<用例名>/，用例前清空、用例后保留。
本节点不读输入视频，fixture 不复制视频。
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

import utils.paths
from contracts import GraphState
from mocks import subtitle_cover as mock_module
from utils.paths import artifact_path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_TMP_ROOT = _REPO_ROOT / "tests" / "tmp" / "mocks" / "subtitle_cover"

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


def _read(name: str) -> str:
    return Path(artifact_path(name)).read_text(encoding="utf-8")


def test_writes_srt_and_ass(work_dir):
    result = mock_module.subtitle_cover(GraphState())

    assert result == {}

    srt_path = Path(artifact_path("bilingual_srt"))
    ass_path = Path(artifact_path("burnin_subtitle"))
    assert srt_path.is_file() and srt_path.stat().st_size > 0
    assert ass_path.is_file() and ass_path.stat().st_size > 0

    assert "00:00:00,000 --> 00:00:01,000" in _read("bilingual_srt")

    ass_text = _read("burnin_subtitle")
    for section in ("[Script Info]", "[V4+ Styles]", "[Events]"):
        assert section in ass_text, f"ASS 缺少段落 {section}"
    assert "Style: Default," in ass_text

    events = ass_text.split("[Events]", 1)[1]
    lines = [line.strip() for line in events.splitlines() if line.strip()]
    format_line = next(line for line in lines if line.startswith("Format:"))
    dialogue_lines = [line for line in lines if line.startswith("Dialogue:")]
    assert dialogue_lines, "ASS 没有任何 Dialogue"
    expected_fields = len(format_line.split(","))
    for line in dialogue_lines:
        assert len(line.split(",")) == expected_fields, (
            f"Dialogue 字段数与 Format 不一致：{line!r}"
        )


def test_rerun_overwrites(work_dir):
    mock_module.subtitle_cover(GraphState())
    first = (_read("bilingual_srt"), _read("burnin_subtitle"))

    mock_module.subtitle_cover(GraphState())
    second = (_read("bilingual_srt"), _read("burnin_subtitle"))

    assert first == second
