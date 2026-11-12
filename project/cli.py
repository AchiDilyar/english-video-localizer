"""CLI 入口。

对应 architecture.md §7。
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from contracts import GraphState
from graph import build_graph
from utils.log import setup_logging
from utils.paths import artifact_path, set_work_dir

logger = logging.getLogger(__name__)

# dataflow.md 第 4 节工作目录结构中的子目录（含 logs/）。
# logs/ 是运行副产品目录，不是产物目录，但属于工作目录结构，由 CLI 统一创建。
# 以dataflow.md 第 4 节工作目录结构为唯一事实源，如果不一致，应尽快修改此处的代码。

_SUBDIRS = (
    "audio",
    "segments",
    "translated",
    "tts",
    "subtitles",
    "video",
    "logs",
)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="run-input")
    parser.add_argument("--work-dir", default=".", help="工作目录，必须已存在")
    parser.add_argument(
        "--input", default="input.mp4", help="工作目录根目录下的输入视频文件名"
    )
    return parser.parse_args(argv)


def _check_work_dir(work_dir: Path) -> None:
    if not work_dir.exists():
        raise FileNotFoundError(f"工作目录不存在: {work_dir}")
    if not work_dir.is_dir():
        raise NotADirectoryError(f"工作目录不是目录: {work_dir}")


def _check_input_video(filename: str) -> None:
    path = Path(artifact_path("input_video", filename))
    if not path.exists():
        raise FileNotFoundError(f"输入视频不存在: {path}")
    if not path.is_file():
        raise IsADirectoryError(f"输入视频不是文件: {path}")


def _create_subdirs(work_dir: Path) -> None:
    for name in _SUBDIRS:
        (work_dir / name).mkdir(parents=True, exist_ok=True)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    work_dir = Path(args.work_dir).resolve()
    try:
        _check_work_dir(work_dir)
        set_work_dir(str(work_dir))
        _check_input_video(args.input)
        _create_subdirs(work_dir)
        setup_logging(str(work_dir / "logs" / "run.log"))

        initial_state = GraphState(input_video=args.input)
        build_graph().invoke(initial_state)

        final_video = artifact_path("final_video")
        print(f"运行成功，最终产物: {final_video}")
        return 0
    except Exception as exc:
        logger.exception("运行失败")
        print(f"运行失败: {exc}", file=sys.stderr)
        raise


if __name__ == "__main__":
    sys.exit(main())