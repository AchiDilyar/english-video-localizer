"""CLI 入口。

对应 architecture.md §7。
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from time import time

from contracts import GraphState
from graph import build_graph
from utils.log import setup_logging
from utils.paths import artifact_path, set_work_dir

logger = logging.getLogger(__name__)

# dataflow.md 第 4 节工作目录结构中的业务子目录。
# logs/ 是运行副产品目录，不是产物目录，由 setup_logging 创建，不在此列。
# 以dataflow.md 第 4 节工作目录结构为唯一事实源，如果不一致，应尽快修改此处的代码。

_SUBDIRS = (
    "audio",
    "segments",
    "translated",
    "tts",
    "subtitles",
    "video",
)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="run-input")
    parser.add_argument("--work-dir", default=".", help="工作目录，必须已存在")
    parser.add_argument(
        "--report-progress", action="store_true", help="记录主图节点进度供 WebUI 查看"
    )
    parser.add_argument(
        "--input", default="input.mp4", help="本地输入文件名或单条YouTube视频链接"
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


def _prepare_input_video(work_dir: Path, raw_input: str) -> str:
    """把 --input 解析为工作目录下的输入视频文件名。

    本地文件名原样返回；http(s):// 链接先下载到工作目录，再返回下载后的文件名。
    本函数只负责获取，不校验文件是否存在，校验由 main 中的 _check_input_video 统一完成。
    """
    if not raw_input.startswith(("https://", "http://")):
        return raw_input
    from nodes.probe_input.youtube import prepare_youtube_input

    return prepare_youtube_input(raw_input, work_dir)


def _stream_with_progress(graph, state, destination: Path) -> None:
    """观察主图的 tasks 事件并写 JSONL；不新增节点、不替换调度。"""
    with destination.open("w", encoding="utf-8") as output:
        for event in graph.stream(state, stream_mode="tasks"):
            finished = "result" in event or "error" in event
            kind = "failed" if event.get("error") else "finished" if finished else "started"
            record = {"node": event["name"], "event": kind, "time": time()}
            if finished:
                record["has_output"] = bool(event.get("result"))
            output.write(json.dumps(record, ensure_ascii=False) + "\n")
            output.flush()


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    work_dir = Path(args.work_dir).resolve()
    try:
        _check_work_dir(work_dir)
        set_work_dir(str(work_dir))
        setup_logging(str(work_dir / "logs" / "run.log"))

        input_filename = _prepare_input_video(work_dir, args.input)
        _check_input_video(input_filename)
        _create_subdirs(work_dir)

        initial_state = GraphState(input_video=input_filename)
        graph = build_graph()
        if args.report_progress:
            _stream_with_progress(
                graph, initial_state, work_dir / "logs" / "node-progress.jsonl"
            )
        else:
            graph.invoke(initial_state)

        final_video = Path(artifact_path("final_video"))
        if final_video.is_file() and final_video.stat().st_size > 0:
            print(f"成片已生成: {final_video}")
        else:
            logger.warning("未生成成片: %s", final_video)
            print("工作流已结束，未生成成片。")
        return 0
    except Exception as exc:
        logger.exception("运行失败: %s", exc)
        raise


def run() -> int:
    """进程入口：main 已记录异常，这里只把异常转换为退出码。"""
    try:
        return main()
    except Exception:
        return 1


if __name__ == "__main__":
    sys.exit(run())
