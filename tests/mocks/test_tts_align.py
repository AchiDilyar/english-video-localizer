"""tts_align mock 的验证用例。

运行：
    uv run pytest tests/mocks/test_tts_align.py -q

工作目录固定在 tests/tmp/mocks/tts_align/<用例名>/，用例前清空、用例后保留。
本节点不读输入视频，fixture 不复制视频。
"""

from __future__ import annotations

import logging
import shutil
import wave
from pathlib import Path

import pytest

import utils.paths
from contracts import GraphState, Segment, TranslatedSegment
from mocks import tts_align as mock_module
from utils.io import read_artifact
from utils.paths import artifact_path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_TMP_ROOT = _REPO_ROOT / "tests" / "tmp" / "mocks" / "tts_align"

# 与 cli.py 的 _SUBDIRS 同源：子目录由 CLI 创建，测试直接调节点时必须自己补上。
_SUBDIRS = ("audio", "segments", "translated", "tts", "subtitles", "video", "logs")

# 演示视频里的前两段（seg_0001: 0–1660，seg_0002: 1920–2140）
_SEGMENT_1 = (0, 1660)
_SEGMENT_2 = (1920, 2140)
_SAMPLE_RATE = 24000
_SAMPLES_PER_MS = _SAMPLE_RATE // 1000


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


def _segment(index: int, start_ms: int, end_ms: int) -> Segment:
    return Segment(
        segment_id=f"seg_{index:04d}",
        speaker_id="spk_1",
        start_ms=start_ms,
        end_ms=end_ms,
        text_en=f"sentence {index}",
    )


def _translated(index: int, *, zh: str | None = None) -> TranslatedSegment:
    return TranslatedSegment(
        segment_id=f"seg_{index:04d}",
        block_id="blk_0001",
        zh_subtitle=zh if zh is not None else f"译文 {index}",
    )


def _wav_frames(name: str, filename: str | None = None) -> tuple[int, int, int, int]:
    path = artifact_path(name, filename) if filename else artifact_path(name)
    with wave.open(path, "rb") as handle:
        return (
            handle.getframerate(),
            handle.getnchannels(),
            handle.getsampwidth(),
            handle.getnframes(),
        )


def _messages(caplog) -> list[str]:
    return [record.getMessage() for record in caplog.records]


def test_none_reviewed_blocks_raises(work_dir):
    with pytest.raises(ValueError):
        mock_module.tts_align(GraphState())


def test_empty_reviewed_blocks_warns_and_returns_empty(work_dir, caplog):
    with caplog.at_level(logging.WARNING, logger=mock_module.__name__):
        result = mock_module.tts_align(GraphState(reviewed_blocks=[]))

    assert result == {"tts_clips": []}
    assert read_artifact("tts_clips") == []
    assert any("[reviewed_blocks 为空]" in message for message in _messages(caplog))
    assert not Path(artifact_path("dub_audio")).exists(), "空输入时不应写配音音轨"


def test_writes_length_matched_audio(work_dir):
    segments = [
        _segment(1, *_SEGMENT_1),
        _segment(2, *_SEGMENT_2),
    ]
    reviewed = [_translated(1), _translated(2)]

    result = mock_module.tts_align(
        GraphState(segments=segments, reviewed_blocks=reviewed)
    )

    clips = result["tts_clips"]
    assert [clip.segment_id for clip in clips] == ["seg_0001", "seg_0002"]
    assert [clip.audio_path for clip in clips] == ["seg_0001.wav", "seg_0002.wav"]
    assert [clip.text for clip in clips] == ["译文 1", "译文 2"]
    assert read_artifact("tts_clips") == clips

    windows = [end - start for start, end in (_SEGMENT_1, _SEGMENT_2)]
    for clip, window_ms in zip(clips, windows):
        assert clip.duration_ms == window_ms
        assert _wav_frames("tts_audio", clip.audio_path) == (
            _SAMPLE_RATE,
            1,
            2,
            window_ms * _SAMPLES_PER_MS,
        )

    total_ms = max(end for _, end in (_SEGMENT_1, _SEGMENT_2))
    assert _wav_frames("dub_audio") == (
        _SAMPLE_RATE,
        1,
        2,
        total_ms * _SAMPLES_PER_MS,
    )


def test_none_segments_raises(work_dir):
    with pytest.raises(ValueError):
        mock_module.tts_align(GraphState(reviewed_blocks=[_translated(1)]))


def test_reviewed_id_missing_in_segments_raises(work_dir):
    with pytest.raises(KeyError):
        mock_module.tts_align(
            GraphState(
                segments=[_segment(1, *_SEGMENT_1)],
                reviewed_blocks=[_translated(2)],
            )
        )
