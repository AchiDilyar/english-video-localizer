"""Acquire a shared YouTube source before the single main graph, without task input copies."""

import argparse
import json
from pathlib import Path

from .source_store import acquire_youtube

DEFAULT_SOURCE_DIR = Path(__file__).resolve().parents[3] / "media" / "downloads"


def prepare_youtube_input(url, work_dir, *, max_height=720, source_dir=None):
    work = Path(work_dir).resolve()
    if not work.is_dir():
        raise FileNotFoundError(f"工作目录不存在: {work}")
    source, metadata = acquire_youtube(url, source_dir or DEFAULT_SOURCE_DIR, max_height=max_height)
    logs = work / "logs"
    logs.mkdir(exist_ok=True)
    (logs / "input-download.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return str(source)


def main(argv=None):
    parser = argparse.ArgumentParser(description="只下载或复用单条公开视频，原片保留在素材目录")
    parser.add_argument("url")
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--max-height", type=int, default=720)
    args = parser.parse_args(argv)
    if not 144 <= args.max_height <= 2160:
        parser.error("--max-height must be between 144 and 2160")
    source, _ = acquire_youtube(args.url, args.output_dir, max_height=args.max_height)
    print(f"视频已下载或复用: {source}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
