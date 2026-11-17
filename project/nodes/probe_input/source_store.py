"""Shared read-only source videos; task directories hold outputs, never input copies."""

from __future__ import annotations

import json
from pathlib import Path

from nodes.asr_diarize.pipeline.video_inputs import download_input, youtube_url
from nodes.background_audio import digest


def _record(root, url):
    canonical = youtube_url(url)
    return canonical, Path(root).resolve() / canonical.rsplit("=", 1)[-1] / "source.json"


def register_existing(root, url, video, metadata=None):
    canonical, record = _record(root, url)
    video = Path(video).resolve()
    if not video.is_file() or video.suffix.lower() != ".mp4" or not video.stat().st_size:
        raise ValueError("原视频不存在或不是有效的非空 MP4 文件")
    data = {
        "url": canonical,
        "source_video": str(video),
        "sha256": digest(video),
        "bytes": video.stat().st_size,
        "title": (metadata or {}).get("title") or video.name,
    }
    record.parent.mkdir(parents=True, exist_ok=True)
    with record.open("x", encoding="utf-8") as output:
        json.dump(data, output, ensure_ascii=False, indent=2)
    return data


def read_record(record):
    data = json.loads(Path(record).read_text(encoding="utf-8"))
    video = Path(data["source_video"])
    if not video.is_absolute() or not video.is_file() or video.suffix.lower() != ".mp4":
        raise ValueError("登记的原视频已移走或不存在，请恢复原下载文件")
    if video.stat().st_size != data["bytes"] or digest(video) != data["sha256"]:
        raise ValueError("原视频内容已改变，拒绝把旧来源记录用于新文件")
    return video, data


def acquire_youtube(url, root, *, max_height=720):
    canonical, record = _record(root, url)
    if record.is_file():
        return read_record(record)
    record.parent.mkdir(parents=True, exist_ok=True)
    lock = record.with_suffix(".lock")
    try:
        handle = lock.open("x")
    except FileExistsError:
        raise RuntimeError("该素材正在下载或上次下载意外中断，请先检查素材目录") from None
    try:
        with handle:
            if record.is_file():
                return read_record(record)
            # Download directly into its permanent source directory. No temporary promotion/copy.
            video, metadata = download_input(
                canonical, record.parent, allow_network=True, max_height=max_height
            )
            data = register_existing(root, canonical, video, metadata)
            return Path(data["source_video"]), data
    finally:
        lock.unlink(missing_ok=True)


def adopt_existing_jobs(jobs, root):
    """Register the earliest existing WebUI download in place, without moving or copying it."""
    jobs = Path(jobs)
    for metadata_path in sorted(jobs.glob("*/web-run.json"), key=lambda p: p.stat().st_mtime):
        try:
            meta = json.loads(metadata_path.read_text(encoding="utf-8"))
            url = meta.get("source_url")
            if not url:
                continue
            _, record = _record(root, url)
            if record.exists():
                continue
            video = (
                Path(meta["source_video"])
                if meta.get("source_video")
                else metadata_path.parent / "input.mp4"
            )
            receipt = metadata_path.parent / "logs/input-download.json"
            details = json.loads(receipt.read_text(encoding="utf-8")) if receipt.is_file() else {}
            register_existing(root, url, video, details)
        except (OSError, ValueError, KeyError, TypeError):
            continue


def catalog(root, upload_roots=()):
    rows = []
    for record in sorted(Path(root).glob("*/source.json")):
        try:
            data = json.loads(record.read_text(encoding="utf-8"))
            path = Path(data["source_video"])
            if path.is_file() and path.stat().st_size:
                rows.append(
                    {
                        "id": "youtube:" + record.parent.name,
                        "title": data["title"],
                        "path": str(path),
                        "url": data["url"],
                    }
                )
        except (OSError, ValueError, KeyError, TypeError):
            continue
    seen = set()
    for folder in upload_roots:
        for path in Path(folder).glob("*.mp4"):
            if (
                path.stem in seen
                or len(path.stem) != 64
                or any(c not in "0123456789abcdef" for c in path.stem)
            ):
                continue
            seen.add(path.stem)
            rows.append(
                {
                    "id": "upload:" + path.stem,
                    "title": "已上传素材 " + path.stem[:12],
                    "path": str(path.resolve()),
                }
            )
    return rows


def resolve_source(source_id, root, upload_roots=()):
    matches = [row for row in catalog(root, upload_roots) if row["id"] == source_id]
    if len(matches) != 1:
        raise ValueError("没有找到所选原视频，请刷新已有素材列表")
    row = matches[0]
    if source_id.startswith("youtube:"):
        return read_record(Path(root) / source_id.split(":", 1)[1] / "source.json")[0]
    path = Path(row["path"])
    if digest(path) != path.stem:
        raise ValueError("已上传素材内容改变，拒绝读取")
    return path
