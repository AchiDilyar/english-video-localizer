"""utils/paths.py 的验证：路径生成。"""

from __future__ import annotations

from pathlib import Path

import pytest

from utils.paths import artifact_path, get_work_dir


def test_set_get_work_dir(work_dir: Path) -> None:
    assert Path(get_work_dir()) == work_dir.resolve()


def test_fixed_path(work_dir: Path) -> None:
    assert artifact_path("segments") == str(
        (work_dir / "segments" / "segments.json").resolve()
    )


def test_fixed_rejects_filename(work_dir: Path) -> None:
    with pytest.raises(ValueError):
        artifact_path("segments", "x.json")


def test_dir_requires_filename(work_dir: Path) -> None:
    with pytest.raises(ValueError):
        artifact_path("tts_audio")


def test_dir_with_filename(work_dir: Path) -> None:
    assert artifact_path("tts_audio", "seg_0001.wav") == str(
        (work_dir / "tts" / "seg_0001.wav").resolve()
    )


def test_root_dir_with_filename(work_dir: Path) -> None:
    """input_video：path="" 表示工作目录根。"""
    assert artifact_path("input_video", "input.mp4") == str(
        (work_dir / "input.mp4").resolve()
    )


def test_unknown_name(work_dir: Path) -> None:
    with pytest.raises(KeyError):
        artifact_path("nonexistent")


def test_no_work_dir_set() -> None:
    """未调用 set_work_dir 时抛 RuntimeError。"""
    import utils.paths
    saved = utils.paths._work_dir
    utils.paths._work_dir = None
    try:
        with pytest.raises(RuntimeError):
            artifact_path("segments")
    finally:
        utils.paths._work_dir = saved