"""utils/io.py 的验证：读写、校验、二进制拒绝。"""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from contracts import Segment
from utils.io import read_artifact, write_artifact


def _make_segment(seg_id: str = "seg_0001") -> Segment:
    return Segment(
        segment_id=seg_id, speaker_id="spk_1",
        start_ms=0, end_ms=1000, text_en="hello",
    )


def test_write_read_roundtrip(work_dir: Path) -> None:
    write_artifact("segments", [_make_segment()])
    back = read_artifact("segments")
    assert isinstance(back, list)
    assert all(isinstance(s, Segment) for s in back)
    assert back[0].segment_id == "seg_0001"


def test_write_accepts_raw_dicts(work_dir: Path) -> None:
    write_artifact("segments", [{
        "segment_id": "seg_0002", "speaker_id": "spk_1",
        "start_ms": 0, "end_ms": 1000, "text_en": "hi",
    }])
    back = read_artifact("segments")
    assert isinstance(back[0], Segment)
    assert back[0].segment_id == "seg_0002"


def test_invalid_write_does_not_touch_file(work_dir: Path) -> None:
    """校验失败时，磁盘上的旧文件不被覆盖。"""
    path = work_dir / "segments" / "segments.json"
    path.write_text("original", encoding="utf-8")
    with pytest.raises(ValidationError):
        write_artifact("segments", [{"segment_id": "bad"}])
    assert path.read_text(encoding="utf-8") == "original"


def test_binary_artifact_rejected(work_dir: Path) -> None:
    with pytest.raises(ValueError, match="artifact_path"):
        read_artifact("source_audio")
    with pytest.raises(ValueError, match="artifact_path"):
        write_artifact("source_audio", {})


def test_unknown_artifact_rejected(work_dir: Path) -> None:
    with pytest.raises(KeyError):
        read_artifact("nonexistent")
    with pytest.raises(KeyError):
        write_artifact("nonexistent", {})


def test_read_missing_file(work_dir: Path) -> None:
    with pytest.raises(FileNotFoundError):
        read_artifact("segments")


def test_write_does_not_create_dir(work_dir: Path) -> None:
    """父目录不存在时直接失败（节点不创建目录）。"""
    import shutil
    shutil.rmtree(work_dir / "segments")
    with pytest.raises(FileNotFoundError):
        write_artifact("segments", [_make_segment()])