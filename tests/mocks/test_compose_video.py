"""compose_video mock 的验证用例。

运行：
    uv run pytest tests/mocks/test_compose_video.py -q

工作目录固定在 tests/tmp/mocks/compose_video/<用例名>/，用例前清空、用例后保留。
本节点不读输入视频，fixture 不复制视频。
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

import utils.paths
from contracts import GraphState
from mocks import compose_video as mock_module
from utils.paths import artifact_path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_TMP_ROOT = _REPO_ROOT / "tests" / "tmp" / "mocks" / "compose_video"

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


def _find_ffprobe() -> str | None:
    """按 architecture.md 第 11 节：.tools 优先，PATH 其次。"""
    candidate = _REPO_ROOT / ".tools" / "ffmpeg" / "bin" / "ffprobe.exe"
    if candidate.is_file():
        return str(candidate)
    return shutil.which("ffprobe")


def test_writes_playable_final_video(work_dir):
    ffprobe = _find_ffprobe()
    if ffprobe is None:
        pytest.skip("未找到 ffprobe，无法校验成片")

    result = mock_module.compose_video(GraphState())

    assert result == {}
    video = Path(artifact_path("final_video"))
    assert video.is_file(), f"缺少成片: {video}"
    assert video.stat().st_size > 0, f"成片为空: {video}"

    completed = subprocess.run(
        [
            ffprobe,
            "-v", "error",
            "-select_streams", "v:0",
            "-show_entries", "stream=codec_name",
            "-of", "default=noprint_wrappers=1",
            str(video),
        ],
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, f"ffprobe 失败: {completed.stderr}"
    assert "codec_name=h264" in completed.stdout, (
        f"未检测到 h264 视频流: {completed.stdout!r}"
    )


def test_missing_ffmpeg_raises(work_dir, monkeypatch):
    def _raise_missing():
        raise FileNotFoundError("ffmpeg 不存在（测试注入）")

    monkeypatch.setattr(mock_module, "_find_ffmpeg", _raise_missing)

    with pytest.raises(FileNotFoundError):
        mock_module.compose_video(GraphState())
