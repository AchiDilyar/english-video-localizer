"""mocks/_video.py 的验证用例。

运行：
    uv run pytest tests/mocks/test_video_helpers.py -q

工作目录固定在 tests/tmp/mocks/video_helpers/<用例名>/，用例前清空、用例后保留。
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

import utils.paths
from contracts import GraphState
from mocks import _video

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEMO_VIDEO = _REPO_ROOT / "tests" / "data" / "asr_diarize" / "real_dialogue" / "input.mp4"
_PROBE_SNAPSHOT = _REPO_ROOT / "project" / "mocks" / "data" / "probe_input.json"
_TMP_ROOT = _REPO_ROOT / "tests" / "tmp" / "mocks" / "video_helpers"


@pytest.fixture
def work_dir(request, monkeypatch):
    monkeypatch.setattr(utils.paths, "_work_dir", None)
    path = _TMP_ROOT / request.node.name
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True)
    shutil.copyfile(_DEMO_VIDEO, path / "input.mp4")
    utils.paths.set_work_dir(str(path))
    return path


def _probe_source() -> dict:
    return json.loads(_PROBE_SNAPSHOT.read_text(encoding="utf-8"))["source"]


def _state() -> GraphState:
    return GraphState(input_video="input.mp4")


def test_head_sha256_matches_probe_snapshot(work_dir):
    assert _video.head_sha256(work_dir / "input.mp4") == _probe_source()["head_sha256"]


def test_input_path_returns_work_dir_file(work_dir):
    path = _video.input_path(_state())

    assert path.resolve() == (work_dir / "input.mp4").resolve()


def test_input_path_missing_raises(work_dir):
    (work_dir / "input.mp4").unlink()

    with pytest.raises(FileNotFoundError):
        _video.input_path(_state())


def test_matches_source_detects_mismatch(work_dir):
    path = work_dir / "input.mp4"
    source = _probe_source()

    assert _video.matches_source(path, source) is True

    doctored = dict(source, size_bytes=source["size_bytes"] + 1)
    assert _video.matches_source(path, doctored) is False
    assert "字节数不符" in _video.describe_mismatch(path, doctored)
