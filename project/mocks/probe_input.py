"""probe_input 的业务 mock：快照优先，指纹失配时回源 ffprobe。

设计约定：
- ffprobe 查找顺序按 architecture.md 第 11 节：仓库根 .tools/ffmpeg/bin/ffprobe.exe
  优先，其次系统 PATH；两处都没有时抛出，不静默降级。
- 快照记录输入视频的字节数与前 64KB 的 SHA-256；两者都一致才认为快照可用。
  不比对文件名，因为 CLI 默认把输入统一叫 input.mp4。
- 快照不可用（缺失 / 格式不合法 / 指纹不符 / 内部字段自相矛盾）时，记录
  warning 并改用 ffprobe 实时探测。这样「probe_input 走 mock、其余节点走真实」
  时 media_info 仍与真实输入视频一致，不会出现静默的错分辨率或错时长。
- 探测失败（含找不到 ffprobe）一律抛出，符合 architecture.md 8.1。
- 不回写快照：换视频后需重新生成 project/mocks/data/probe_input.json。

输入定位与指纹计算复用 mocks/_video.py，不再本地重复实现。
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
from datetime import datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path

from contracts import AudioStreamInfo, MediaInfo, VideoStreamInfo

from ._video import describe_mismatch, head_sha256, input_path, matches_source

logger = logging.getLogger(__name__)

SNAPSHOT_SCHEMA_VERSION = 1

_DURATION_TOLERANCE_MS = 50
_PROBE_TIMEOUT_SECONDS = 60

_SNAPSHOT_PATH = Path(__file__).resolve().parent / "data" / "probe_input.json"
_REPO_ROOT = Path(__file__).resolve().parents[2]


# ---------------------------------------------------------------------------
# ffprobe
# ---------------------------------------------------------------------------


def _ffprobe_name() -> str:
    return "ffprobe.exe" if os.name == "nt" else "ffprobe"


def _find_ffprobe() -> str:
    """按 architecture.md 第 11 节查找 ffprobe：.tools 优先，其次 PATH。"""
    candidate = _REPO_ROOT / ".tools" / "ffmpeg" / "bin" / _ffprobe_name()
    if candidate.is_file():
        return str(candidate)
    found = shutil.which("ffprobe")
    if found:
        return found
    raise FileNotFoundError(
        "probe_input mock: 未找到 ffprobe；请放到仓库根 "
        ".tools/ffmpeg/bin/ffprobe.exe 或加入 PATH"
    )


def _probe(path: Path) -> dict:
    """调用 ffprobe 探测本地视频，返回完整 probe 输出。"""
    if not path.is_file():
        raise FileNotFoundError(f"probe_input mock: 输入视频不存在: {path}")
    ffprobe = _find_ffprobe()
    result = subprocess.run(
        [
            ffprobe,
            "-v", "error",
            "-show_format",
            "-show_streams",
            "-of", "json",
            str(path),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=_PROBE_TIMEOUT_SECONDS,
    )
    if result.returncode:
        raise RuntimeError(
            f"probe_input mock: ffprobe 探测失败: {result.stderr.strip()[-500:]}"
        )
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError("probe_input mock: ffprobe 未返回合法 JSON") from exc
    if not data.get("streams"):
        raise RuntimeError("probe_input mock: ffprobe 输出中没有任何媒体流")
    return data


# ---------------------------------------------------------------------------
# 流选择与字段推导
# ---------------------------------------------------------------------------


def _select_streams(raw: dict) -> tuple[dict, dict]:
    """选出唯一的视频流与音频流；数量不为 1 时失败。"""
    streams = raw.get("streams") or []
    videos = [
        stream
        for stream in streams
        if stream.get("codec_type") == "video"
        and not stream.get("disposition", {}).get("attached_pic")
    ]
    audios = [stream for stream in streams if stream.get("codec_type") == "audio"]
    if len(videos) != 1:
        raise ValueError(f"probe_input mock: 需要恰好 1 个视频流，实际 {len(videos)} 个")
    if len(audios) != 1:
        raise ValueError(f"probe_input mock: 需要恰好 1 个音频流，实际 {len(audios)} 个")
    return videos[0], audios[0]


def _number(value) -> Decimal | None:
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return parsed if parsed.is_finite() else None


def _ms(seconds: Decimal) -> int:
    return int((seconds * 1000).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _duration_ms(raw: dict, video: dict) -> int:
    """优先用视频流时长；缺失时回退「容器结束 - 视频起点」。"""
    origin = _number(video.get("start_time"))
    duration = _number(video.get("duration"))
    if duration is None:
        start = _number(raw.get("format", {}).get("start_time"))
        total = _number(raw.get("format", {}).get("duration"))
        if start is not None and total is not None and origin is not None:
            duration = start + total - origin
    if duration is None or duration <= 0:
        raise ValueError("probe_input mock: 无法确定视频时长")
    return _ms(duration)


def _fps(video: dict) -> float | None:
    value = video.get("avg_frame_rate") or video.get("r_frame_rate")
    if not value:
        return None
    numerator, _, denominator = str(value).partition("/")
    try:
        rate = float(numerator) / float(denominator or "1")
    except (ValueError, ZeroDivisionError):
        return None
    return rate if rate > 0 else None


# ---------------------------------------------------------------------------
# 快照
# ---------------------------------------------------------------------------


def _snapshot_from(raw: dict, path: Path) -> dict:
    """由 ffprobe 输出与源文件生成快照字典（生成脚本复用同一实现）。"""
    video, audio = _select_streams(raw)
    return {
        "schema_version": SNAPSHOT_SCHEMA_VERSION,
        "probed_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "source": {
            "filename": path.name,
            "size_bytes": path.stat().st_size,
            "head_sha256": head_sha256(path),
        },
        "duration_ms": _duration_ms(raw, video),
        "video_info": {
            "codec": video["codec_name"],
            "width": int(video["width"]),
            "height": int(video["height"]),
            "fps": _fps(video),
        },
        "audio_info": {
            "codec": audio["codec_name"],
            "sample_rate": int(audio["sample_rate"]),
            "channels": int(audio["channels"]),
        },
        "ffprobe_raw": raw,
    }


def _load_snapshot() -> dict | None:
    """读取快照；缺失或结构不合法时返回 None。"""
    try:
        with _SNAPSHOT_PATH.open("r", encoding="utf-8") as handle:
            snapshot = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(snapshot, dict):
        return None
    if snapshot.get("schema_version") != SNAPSHOT_SCHEMA_VERSION:
        return None
    required = {"source", "duration_ms", "video_info", "audio_info", "ffprobe_raw"}
    if not required <= snapshot.keys():
        return None
    source = snapshot["source"]
    if not isinstance(source, dict) or not {"size_bytes", "head_sha256"} <= source.keys():
        return None
    return snapshot


def _self_consistent(snapshot: dict) -> bool:
    """快照内部字段必须与自身保存的 ffprobe_raw 一致。"""
    try:
        raw = snapshot["ffprobe_raw"]
        video, audio = _select_streams(raw)
        if abs(_duration_ms(raw, video) - int(snapshot["duration_ms"])) > _DURATION_TOLERANCE_MS:
            return False
        video_info = snapshot["video_info"]
        if (
            int(video_info["width"]),
            int(video_info["height"]),
            video_info["codec"],
        ) != (
            int(video["width"]),
            int(video["height"]),
            video["codec_name"],
        ):
            return False
        audio_info = snapshot["audio_info"]
        if (
            int(audio_info["sample_rate"]),
            int(audio_info["channels"]),
            audio_info["codec"],
        ) != (
            int(audio["sample_rate"]),
            int(audio["channels"]),
            audio["codec_name"],
        ):
            return False
    except (KeyError, TypeError, ValueError):
        return False
    return True


def _describe_snapshot_problem(snapshot: dict | None, path: Path) -> str:
    if snapshot is None:
        return "快照缺失或格式不合法"
    return describe_mismatch(path, snapshot["source"])


def _to_media_info(source: dict) -> MediaInfo:
    return MediaInfo(
        duration_ms=source["duration_ms"],
        video_info=VideoStreamInfo(
            codec=source["video_info"]["codec"],
            width=source["video_info"]["width"],
            height=source["video_info"]["height"],
            fps=source["video_info"].get("fps"),
        ),
        audio_info=AudioStreamInfo(
            codec=source["audio_info"]["codec"],
            sample_rate=source["audio_info"]["sample_rate"],
            channels=source["audio_info"]["channels"],
        ),
        ffprobe_raw=source["ffprobe_raw"],
    )


# ---------------------------------------------------------------------------
# 节点主函数
# ---------------------------------------------------------------------------


def probe_input(state) -> dict:
    """返回 media_info 增量：快照命中则用快照，否则回源 ffprobe。"""
    path = input_path(state)

    snapshot = _load_snapshot()
    if (
        snapshot is not None
        and matches_source(path, snapshot["source"])
        and _self_consistent(snapshot)
    ):
        logger.info(
            "probe_input mock: 命中快照 %s（%d 字节）",
            _SNAPSHOT_PATH.name,
            path.stat().st_size,
        )
        return {"media_info": _to_media_info(snapshot)}

    logger.warning(
        "probe_input mock: 快照不可用（%s），改用 ffprobe 实时探测 %s；"
        "请重新生成 %s",
        _describe_snapshot_problem(snapshot, path),
        path.name,
        _SNAPSHOT_PATH,
    )
    raw = _probe(path)
    return {"media_info": _to_media_info(_snapshot_from(raw, path))}
