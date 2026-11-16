"""probe_input mock 的验证用例。

运行：
    uv run pytest tests/mocks/test_probe_input.py -q

覆盖五条路径：
1. 快照命中：指纹与内部一致性均通过，直接返回快照数据，不产生 warning；
2. 指纹失配：warning + 回源 ffprobe，结果必须等于独立期望值（不是 mock 自己算的值）；
3. 快照缺失：warning + 回源 ffprobe，结果同样等于独立期望值；
4. ffprobe 缺失：节点抛 FileNotFoundError，不静默降级；
5. ffprobe 执行失败：节点抛 RuntimeError。

工作目录固定放在 tests/tmp/mocks/probe_input/<用例名>/，用例前清空、用例后保留，
与 tests/cli 的约定一致。
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path
from subprocess import CompletedProcess

import pytest

import utils.paths
from contracts import GraphState
from mocks import probe_input as mock_module

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEMO_VIDEO = _REPO_ROOT / "tests" / "data" / "asr_diarize" / "real_dialogue" / "input.mp4"
_SNAPSHOT_PATH = _REPO_ROOT / "project" / "mocks" / "data" / "probe_input.json"
_TMP_ROOT = _REPO_ROOT / "tests" / "tmp" / "mocks" / "probe_input"

# 演示视频的独立期望值：由 ffprobe 直接探测得到，不依赖 mocks/probe_input.py 的实现。
_EXPECTED_DURATION_MS = 14000
_EXPECTED_VIDEO_CODEC = "h264"
_EXPECTED_WIDTH = 854
_EXPECTED_HEIGHT = 480
_EXPECTED_AUDIO_CODEC = "aac"
_EXPECTED_SAMPLE_RATE = 44100
_EXPECTED_CHANNELS = 2


@pytest.fixture
def work_dir(request, monkeypatch):
    """隔离全局工作目录，并把演示视频复制成工作目录下的 input.mp4。"""
    monkeypatch.setattr(utils.paths, "_work_dir", None)
    path = _TMP_ROOT / request.node.name
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True)
    shutil.copyfile(_DEMO_VIDEO, path / "input.mp4")
    utils.paths.set_work_dir(str(path))
    return path


def _state() -> GraphState:
    return GraphState(input_video="input.mp4")


def _assert_matches_demo_video(media_info) -> None:
    """与硬编码的独立期望值比对，证明回源结果确实来自 ffprobe。"""
    assert media_info.duration_ms == _EXPECTED_DURATION_MS
    assert media_info.video_info.codec == _EXPECTED_VIDEO_CODEC
    assert media_info.video_info.width == _EXPECTED_WIDTH
    assert media_info.video_info.height == _EXPECTED_HEIGHT
    assert media_info.audio_info.codec == _EXPECTED_AUDIO_CODEC
    assert media_info.audio_info.sample_rate == _EXPECTED_SAMPLE_RATE
    assert media_info.audio_info.channels == _EXPECTED_CHANNELS

    streams = media_info.ffprobe_raw["streams"]
    assert any(
        stream["index"] == 0 and stream["codec_type"] == "video" for stream in streams
    ), "ffprobe_raw 中应存在 index=0 的视频流"
    assert any(
        stream["index"] == 1 and stream["codec_type"] == "audio" for stream in streams
    ), "ffprobe_raw 中应存在 index=1 的音频流"


def test_snapshot_hit_returns_snapshot(work_dir, caplog):
    if not _SNAPSHOT_PATH.is_file():
        pytest.skip(f"快照不存在，请先运行 gen_probe_snapshot.py：{_SNAPSHOT_PATH}")
    snapshot = mock_module._load_snapshot()
    assert snapshot is not None, "快照存在但加载失败"

    with caplog.at_level(logging.INFO, logger=mock_module.__name__):
        result = mock_module.probe_input(_state())

    media_info = result["media_info"]
    assert media_info.duration_ms == snapshot["duration_ms"]
    assert media_info.video_info.width == snapshot["video_info"]["width"]
    assert media_info.video_info.height == snapshot["video_info"]["height"]
    assert media_info.ffprobe_raw == snapshot["ffprobe_raw"]
    warnings = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert not warnings, f"命中快照时不应产生 warning：{[r.getMessage() for r in warnings]}"


def test_fingerprint_mismatch_falls_back_to_ffprobe(work_dir, caplog, monkeypatch):
    snapshot = mock_module._load_snapshot()
    if snapshot is None:
        pytest.skip("快照不存在或不可用，无法构造失配场景")

    doctored = dict(snapshot)
    doctored["source"] = dict(snapshot["source"])
    doctored["source"]["size_bytes"] = snapshot["source"]["size_bytes"] + 1
    doctored["duration_ms"] = 999999
    doctored["video_info"] = dict(snapshot["video_info"], width=1, height=1)
    monkeypatch.setattr(mock_module, "_load_snapshot", lambda: doctored)

    with caplog.at_level(logging.WARNING, logger=mock_module.__name__):
        result = mock_module.probe_input(_state())

    assert any(r.levelno == logging.WARNING for r in caplog.records), "回源时应记录 warning"
    _assert_matches_demo_video(result["media_info"])


def test_snapshot_missing_falls_back_to_ffprobe(work_dir, caplog, monkeypatch):
    monkeypatch.setattr(mock_module, "_load_snapshot", lambda: None)

    with caplog.at_level(logging.WARNING, logger=mock_module.__name__):
        result = mock_module.probe_input(_state())

    messages = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
    assert any("快照缺失" in message for message in messages), messages
    _assert_matches_demo_video(result["media_info"])


def test_ffprobe_missing_raises(work_dir, monkeypatch):
    def _raise_missing():
        raise FileNotFoundError("ffprobe 不存在（测试注入）")

    monkeypatch.setattr(mock_module, "_load_snapshot", lambda: None)
    monkeypatch.setattr(mock_module, "_find_ffprobe", _raise_missing)

    with pytest.raises(FileNotFoundError):
        mock_module.probe_input(_state())


def test_ffprobe_failure_raises(work_dir, monkeypatch):
    def _failed_run(*args, **kwargs):
        return CompletedProcess(args[0], 1, "", "boom: ffprobe failed")

    monkeypatch.setattr(mock_module, "_load_snapshot", lambda: None)
    monkeypatch.setattr(mock_module.subprocess, "run", _failed_run)

    with pytest.raises(RuntimeError, match="ffprobe"):
        mock_module.probe_input(_state())
