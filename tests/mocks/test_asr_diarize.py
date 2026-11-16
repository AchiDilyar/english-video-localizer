"""asr_diarize mock 的验证用例。

运行：
    uv run pytest tests/mocks/test_asr_diarize.py -q

工作目录固定在 tests/tmp/mocks/asr_diarize/<用例名>/，用例前清空、用例后保留，
与 tests/cli 的约定一致。
"""

from __future__ import annotations

import json
import logging
import shutil
import wave
from pathlib import Path

import pytest

import utils.paths
from contracts import AudioStreamInfo, GraphState, MediaInfo, VideoStreamInfo
from mocks import asr_diarize as mock_module
from utils.io import read_artifact
from utils.paths import artifact_path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEMO_VIDEO = _REPO_ROOT / "tests" / "data" / "asr_diarize" / "real_dialogue" / "input.mp4"
_UPSTREAM_FIXTURE = (
    _REPO_ROOT / "tests" / "data" / "asr_diarize" / "real_dialogue" / "segments.json"
)
_ASR_DATA = _REPO_ROOT / "project" / "mocks" / "data" / "asr_diarize.json"
_PROBE_SNAPSHOT = _REPO_ROOT / "project" / "mocks" / "data" / "probe_input.json"
_TMP_ROOT = _REPO_ROOT / "tests" / "tmp" / "mocks" / "asr_diarize"

# 与 cli.py 的 _SUBDIRS 同源：子目录由 CLI 创建，测试直接调节点时必须自己补上。
_SUBDIRS = ("audio", "segments", "translated", "tts", "subtitles", "video", "logs")

_EXPECTED_IDS = [f"seg_{number:04d}" for number in range(1, 12)]
_VIDEO_DURATION_MS = 14000


@pytest.fixture
def work_dir(request, monkeypatch):
    """隔离全局工作目录，并把演示视频复制成工作目录下的 input.mp4。"""
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


def _media_info(duration_ms: int) -> MediaInfo:
    return MediaInfo(
        duration_ms=duration_ms,
        video_info=VideoStreamInfo(codec="h264", width=854, height=480, fps=25.0),
        audio_info=AudioStreamInfo(codec="aac", sample_rate=44100, channels=2),
        ffprobe_raw={"streams": []},
    )


def _state(duration_ms: int | None = _VIDEO_DURATION_MS) -> GraphState:
    if duration_ms is None:
        return GraphState(input_video="input.mp4")
    return GraphState(input_video="input.mp4", media_info=_media_info(duration_ms))


def _messages(caplog) -> list[str]:
    return [record.getMessage() for record in caplog.records]


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_returns_segments_and_writes_artifacts(work_dir):
    result = mock_module.asr_diarize(_state())

    assert [segment.segment_id for segment in result["segments"]] == _EXPECTED_IDS
    assert read_artifact("segments") == result["segments"]

    with wave.open(artifact_path("source_audio"), "rb") as wav:
        assert (
            wav.getframerate(),
            wav.getnchannels(),
            wav.getsampwidth(),
            wav.getnframes(),
        ) == (16000, 1, 2, _VIDEO_DURATION_MS * 16)


def test_matches_upstream_fixture(work_dir):
    assert _read_json(_ASR_DATA)["segments"] == _read_json(_UPSTREAM_FIXTURE)


def test_data_hash_matches_probe_snapshot(work_dir):
    asr_source = _read_json(_ASR_DATA)["source"]
    probe_source = _read_json(_PROBE_SNAPSHOT)["source"]

    assert asr_source["head_sha256"] == probe_source["head_sha256"]
    assert asr_source["size_bytes"] == probe_source["size_bytes"]
    assert asr_source["duration_ms"] == _read_json(_PROBE_SNAPSHOT)["duration_ms"]


def test_hash_mismatch_warns_but_continues(work_dir, caplog, monkeypatch):
    monkeypatch.setattr(mock_module, "head_sha256", lambda path: "0" * 64)

    with caplog.at_level(logging.WARNING, logger=mock_module.__name__):
        result = mock_module.asr_diarize(_state())

    assert [segment.segment_id for segment in result["segments"]] == _EXPECTED_IDS
    assert any("[指纹不符]" in message for message in _messages(caplog))


def test_end_beyond_duration_drops_segments(work_dir, caplog):
    with caplog.at_level(logging.WARNING, logger=mock_module.__name__):
        result = mock_module.asr_diarize(_state(10000))

    assert [segment.segment_id for segment in result["segments"]] == _EXPECTED_IDS[:8]
    messages = _messages(caplog)
    assert any("[丢弃]" in message and "seg_0009" in message for message in messages)
    assert any("[丢弃汇总]" in message and "3" in message for message in messages)


def test_all_segments_dropped_returns_empty(work_dir, caplog):
    with caplog.at_level(logging.WARNING, logger=mock_module.__name__):
        result = mock_module.asr_diarize(_state(1))

    assert result["segments"] == []
    assert read_artifact("segments") == []
    messages = _messages(caplog)
    assert any("[丢弃汇总]" in message for message in messages)
    assert any("[空结果]" in message for message in messages)


def test_missing_media_info_skips_duration_check(work_dir, caplog):
    with caplog.at_level(logging.INFO, logger=mock_module.__name__):
        result = mock_module.asr_diarize(_state(None))

    assert [segment.segment_id for segment in result["segments"]] == _EXPECTED_IDS
    assert any("[校验跳过]" in message for message in _messages(caplog))
    with wave.open(artifact_path("source_audio"), "rb") as wav:
        assert wav.getnframes() == 0


def test_input_video_missing_raises(work_dir):
    (work_dir / "input.mp4").unlink()

    with pytest.raises(FileNotFoundError):
        mock_module.asr_diarize(_state())


def test_rerun_overwrites_artifacts(work_dir):
    first = mock_module.asr_diarize(_state())
    second = mock_module.asr_diarize(_state())

    assert first["segments"] == second["segments"]
    assert read_artifact("segments") == second["segments"]
