"""运行报告工具（独立辅助脚本）。

对应 handover.md 第 10 节「运行报告工具」：
- 放在 scripts/ 下，不与主程序耦合；
- 不写设计文档、不登记 increments；
- 只读一次运行的工作目录，生成 Markdown 报告；不做通过/失败判定。

用法：
    uv run python scripts/run_report.py --work-dir <工作目录> [--output 相对路径]
        [--traceback-lines 20]

`--output` 未指定时写入 `<工作目录>/report.md`；相对路径以工作目录为根。

报告内容：运行概要、结论、阶段耗时（近似）、警告汇总、产物清单、质量指标、
成品视频（ffprobe）、异常摘录、数据来源与局限。

设计约束：
- 只使用标准库，不 import project/ 下任何模块；
- 只读工作目录，唯一的写操作是生成报告文件；
- 解析失败一律降级为「未识别/缺失」，不中断报告。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import wave
from collections import OrderedDict
from datetime import datetime
from pathlib import Path

LOG_RE = re.compile(
    r"^(?P<ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3}) "
    r"\[(?P<level>[A-Z]+)\] (?P<logger>[^:]+): (?P<msg>.*)$"
)
MODE_RE = re.compile(r"节点运行模式：(?P<body>.+)$")
TS_FORMAT = "%Y-%m-%d %H:%M:%S,%f"

STRUCTURED_ARTIFACTS = (
    ("分段结果 segments", "segments/segments.json"),
    ("翻译块 blocks", "segments/blocks.json"),
    ("翻译结果 translated_blocks", "translated/translated_blocks.json"),
    ("审校结果 reviewed_blocks", "translated/reviewed_blocks.json"),
    ("修复结果 repaired_blocks", "translated/repaired_blocks.json"),
    ("分段音频清单 tts_clips", "tts/clips.json"),
)

MEDIA_ARTIFACTS = (
    ("提取音频 source_audio", "audio/source.wav"),
    ("中文配音音轨 dub_audio", "audio/dub.wav"),
    ("原文 SRT english_srt", "subtitles/english_segmented.srt"),
    ("译文 SRT chinese_srt", "subtitles/chinese.srt"),
    ("双语 SRT bilingual_srt", "subtitles/bilingual.srt"),
    ("烧录字幕 burnin_subtitle", "subtitles/burnin.ass"),
    ("成片 final_video", "video/final.mp4"),
)


# ---------------------------------------------------------------------------
# 解析与格式化
# ---------------------------------------------------------------------------


def human_size(size: int) -> str:
    """把字节数转成便于阅读的大小。"""
    if size < 1024:
        return f"{size} B"
    value = size / 1024.0
    for unit in ("KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            return f"{value:.1f} {unit}"
        value /= 1024.0
    return f"{size} B"


def fmt_ms(ms: int) -> str:
    """毫秒转 mm:ss.mmm（超过一小时用 h:mm:ss.mmm）。"""
    total_s, rem_ms = divmod(max(int(ms), 0), 1000)
    hours, rem = divmod(total_s, 3600)
    minutes, seconds = divmod(rem, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{seconds:02d}.{rem_ms:03d}"
    return f"{minutes:02d}:{seconds:02d}.{rem_ms:03d}"


def parse_modes(body: str) -> "OrderedDict[str, str]":
    """解析「节点运行模式：a=模拟, b=真实」中的模式串。"""
    modes: "OrderedDict[str, str]" = OrderedDict()
    for part in body.split(","):
        part = part.strip()
        if not part or "=" not in part:
            continue
        name, value = part.split("=", 1)
        modes[name.strip()] = value.strip()
    return modes


def parse_log(path: Path, traceback_lines: int = 20) -> dict:
    """解析 logs/run.log；缺失或格式不符时返回降级结果，不抛异常。"""
    info = {
        "exists": path.is_file(),
        "lines": 0,
        "entries": [],
        "raw": [],
        "mode": None,
        "level_warnings": [],
        "errors": [],
        "traceback": [],
    }
    if not info["exists"]:
        return info

    try:
        raw = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        info["exists"] = False
        return info

    info["lines"] = len(raw)
    info["raw"] = raw

    for line in raw:
        match = LOG_RE.match(line)
        if not match:
            continue
        try:
            ts = datetime.strptime(match.group("ts"), TS_FORMAT)
        except ValueError:
            continue
        entry = {
            "ts": ts,
            "level": match.group("level"),
            "logger": match.group("logger"),
            "msg": match.group("msg"),
        }
        info["entries"].append(entry)

        if info["mode"] is None:
            mode_match = MODE_RE.search(entry["msg"])
            if mode_match:
                info["mode"] = parse_modes(mode_match.group("body"))

        if entry["level"] == "ERROR":
            info["errors"].append(entry["msg"])

        if entry["level"] == "WARNING":
            info["level_warnings"].append(entry)

    for index, line in enumerate(raw):
        if "Traceback (most recent call last):" in line:
            excerpt: list = []
            for follow in raw[index:]:
                if len(excerpt) >= traceback_lines:
                    break
                # 摘录在遇到下一条可解析日志行时结束，避免把后续日志吞进 traceback。
                if excerpt and LOG_RE.match(follow):
                    break
                excerpt.append(follow)
            info["traceback"] = excerpt
            break

    return info


def load_json(path: Path) -> tuple:
    """读取 JSON 产物，返回 (值, 失败原因)。"""
    if not path.is_file():
        return None, "文件不存在"
    try:
        return json.loads(path.read_text(encoding="utf-8")), None
    except (OSError, ValueError) as exc:
        return None, f"解析失败: {exc}"


def wav_duration_ms(path: Path):
    """读取 WAV 时长；文件缺失或格式不符时返回 None。"""
    if not path.is_file():
        return None
    try:
        with wave.open(str(path), "rb") as handle:
            rate = handle.getframerate()
            if not rate:
                return None
            return int(round(handle.getnframes() * 1000.0 / rate))
    except (OSError, wave.Error, EOFError):
        return None


def node_of(logger_name: str) -> str:
    """从 logger 名推出节点名；非节点 logger 原样返回。"""
    if logger_name.startswith(("mocks.", "nodes.")):
        return logger_name.split(".", 1)[1]
    return logger_name


def find_ffprobe() -> str | None:
    """按 architecture.md 第 11 节查找 ffprobe：仓库根 .tools → PATH。

    `.tools/ffmpeg/bin` 分支仅 Windows 有效；其它平台只用 PATH。
    """
    if os.name == "nt":
        local = (
            Path(__file__).resolve().parents[1]
            / ".tools" / "ffmpeg" / "bin" / "ffprobe.exe"
        )
        if local.is_file():
            return str(local)
    return shutil.which("ffprobe")


def probe_video(path: Path, ffprobe: str) -> tuple:
    """调用 ffprobe 读取容器与流信息，返回 (数据, 失败原因)。"""
    command = [
        ffprobe,
        "-v", "error",
        "-show_format",
        "-show_streams",
        "-of", "json",
        str(path),
    ]
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return None, f"无法执行 ffprobe：{exc}"
    if result.returncode:
        detail = (result.stderr or "").strip()[-500:]
        return None, f"ffprobe 退出码 {result.returncode}" + (
            f"：{detail}" if detail else ""
        )
    try:
        payload = json.loads(result.stdout)
    except ValueError as exc:
        return None, f"ffprobe 输出不是合法 JSON：{exc}"
    if not isinstance(payload, dict):
        return None, "ffprobe 输出结构异常"
    return payload, None


def _fmt_bitrate(value) -> str:
    try:
        bps = int(value)
    except (TypeError, ValueError):
        return "—"
    if bps <= 0:
        return "—"
    if bps >= 1_000_000:
        return f"{bps / 1_000_000:.2f} Mbps"
    return f"{round(bps / 1000)} kbps"


def _fmt_fps(value) -> str:
    text = str(value or "")
    if not text:
        return "—"
    numerator, _, denominator = text.partition("/")
    try:
        rate = float(numerator) / float(denominator or "1")
    except (ValueError, ZeroDivisionError):
        return "—"
    if rate <= 0:
        return "—"
    return f"{rate:.3f} fps"


def _fmt_seconds(value) -> str:
    try:
        return fmt_ms(int(round(float(value) * 1000)))
    except (TypeError, ValueError):
        return "—"


# ---------------------------------------------------------------------------
# 报告各节
# ---------------------------------------------------------------------------


def _section_overview(work_dir: Path, log: dict) -> list:
    out = ["## 1. 运行概要", "", "| 项目 | 内容 |", "|---|---|"]
    out.append(f"| 工作目录 | `{work_dir}` |")

    videos = sorted(work_dir.glob("*.mp4"))
    if videos:
        described = "；".join(
            f"`{item.name}`（{human_size(item.stat().st_size)}）" for item in videos
        )
        out.append(f"| 输入视频 | {described} |")
    else:
        out.append("| 输入视频 | 未找到工作目录根目录下的 .mp4 文件 |")

    if log["mode"]:
        values = set(log["mode"].values())
        if values == {"模拟"}:
            summary = "全部模拟"
        elif values == {"真实"}:
            summary = "全部真实"
        else:
            summary = "混合（逐节点见下）"
    else:
        summary = "未识别（日志中无「节点运行模式」行）"
    out.append(f"| 节点模式 | {summary} |")

    if log["exists"]:
        out.append(
            f"| 日志文件 | `logs/run.log`（{log['lines']} 行，"
            f"可解析 {len(log['entries'])} 行） |"
        )
        if log["entries"]:
            first_ts = log["entries"][0]["ts"]
            last_ts = log["entries"][-1]["ts"]
            span = (last_ts - first_ts).total_seconds()
            out.append(
                f"| 日志时间范围 | {first_ts.strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]} → "
                f"{last_ts.strftime('%H:%M:%S.%f')[:-3]}（跨度 {span:.3f}s） |"
            )
        else:
            out.append("| 日志时间范围 | 无可解析日志行 |")
        out.append(f"| 是否含 traceback | {'是' if log['traceback'] else '否'} |")
    else:
        out.append("| 日志文件 | `logs/run.log` 缺失 |")
    out.append("")

    if log["mode"]:
        out.extend(["### 节点模式", "", "| 节点 | 模式 |", "|---|---|"])
        for name, value in log["mode"].items():
            out.append(f"| `{name}` | {value} |")
        out.append("")
    return out


def _section_conclusion(work_dir: Path, log: dict) -> list:
    out = ["## 2. 结论", ""]
    final = work_dir / "video" / "final.mp4"
    size = final.stat().st_size if final.is_file() else 0
    if final.is_file() and size > 0:
        out.append(f"成片已生成：`video/final.mp4`（{human_size(size)}）。")
    else:
        if not log["exists"]:
            clue = "日志文件缺失，无法提供线索"
        elif log["errors"]:
            clue = f"日志最后一条 ERROR：{log['errors'][-1]}"
        elif log["traceback"]:
            clue = "日志含 traceback（见第 8 节）"
        else:
            clue = "日志中无 ERROR 记录"
        state = "不存在" if not final.exists() else "大小为 0"
        out.append(f"未生成成片：`video/final.mp4` {state}。线索：{clue}。")
    out.append("")
    return out


def _section_timing(log: dict) -> list:
    out = [
        "## 3. 阶段耗时（近似）",
        "",
        "> 仅统计日志可见范围：按各 logger 首末时间戳计算，不代表真实节点耗时；"
        "无日志的节点不会出现。",
        "",
    ]
    if not log["entries"]:
        out.extend(["无可用日志行。", ""])
        return out

    grouped: "OrderedDict[str, dict]" = OrderedDict()
    for entry in log["entries"]:
        item = grouped.setdefault(
            entry["logger"], {"first": entry["ts"], "last": entry["ts"], "count": 0}
        )
        item["last"] = entry["ts"]
        item["count"] += 1

    out.extend(
        [
            "| 节点 | logger | 首条 | 末条 | 跨度 | 日志行数 |",
            "|---|---|---|---|---|---|",
        ]
    )
    for logger_name, item in sorted(grouped.items(), key=lambda pair: pair[1]["first"]):
        span = (item["last"] - item["first"]).total_seconds()
        out.append(
            f"| `{node_of(logger_name)}` | `{logger_name}` | "
            f"{item['first'].strftime('%H:%M:%S.%f')[:-3]} | "
            f"{item['last'].strftime('%H:%M:%S.%f')[:-3]} | "
            f"{span:.3f}s | {item['count']} |"
        )

    if log["mode"]:
        logged_nodes = {
            node_of(name) for name in grouped if name.startswith(("mocks.", "nodes."))
        }
        missing = [name for name in log["mode"] if name not in logged_nodes]
        if missing:
            out.extend(
                [
                    "",
                    "无日志节点："
                    + "、".join(f"`{name}`" for name in missing)
                    + "（耗时不可得）。",
                ]
            )
    out.append("")
    return out


def _truncate(text: str, limit: int = 200) -> str:
    """转义表格分隔符，并按上限截断过长原文。"""
    text = text.replace("|", "\\|")
    if len(text) > limit:
        return text[:limit] + "…"
    return text


def _section_warnings(log: dict) -> list:
    out = ["## 4. 警告汇总", "", "### WARNING 级别日志", ""]

    grouped: "OrderedDict[str, dict]" = OrderedDict()
    for entry in log["level_warnings"]:
        item = grouped.setdefault(
            entry["logger"], {"count": 0, "first": entry["msg"]}
        )
        item["count"] += 1

    if not grouped:
        out.extend(["无 WARNING 级别日志。", ""])
    else:
        out.extend(
            ["| 节点 | logger | 次数 | 首条原文 |", "|---|---|---|---|"]
        )
        for logger_name, item in grouped.items():
            out.append(
                f"| `{node_of(logger_name)}` | `{logger_name}` | "
                f"{item['count']} | {_truncate(item['first'])} |"
            )
        out.append("")
    return out


def _section_artifacts(work_dir: Path) -> list:
    out = ["## 5. 产物清单", "", "| 产物 | 路径 | 状态 | 大小 |", "|---|---|---|---|"]
    for label, rel in STRUCTURED_ARTIFACTS + MEDIA_ARTIFACTS:
        path = work_dir / rel
        if path.is_file():
            out.append(f"| {label} | `{rel}` | 存在 | {human_size(path.stat().st_size)} |")
        else:
            out.append(f"| {label} | `{rel}` | 缺失 | — |")
    out.append("")
    return out


def _section_metrics(work_dir: Path, loaded: dict) -> list:
    out = ["## 6. 质量指标", "", "| 指标 | 值 |", "|---|---|"]

    segs_value, segs_error = loaded["segments/segments.json"]
    blocks_value, blocks_error = loaded["segments/blocks.json"]
    trans_value, trans_error = loaded["translated/translated_blocks.json"]
    rev_value, rev_error = loaded["translated/reviewed_blocks.json"]
    rep_value, rep_error = loaded["translated/repaired_blocks.json"]
    clips_value, clips_error = loaded["tts/clips.json"]

    segs = segs_value if isinstance(segs_value, list) else None
    blocks = blocks_value if isinstance(blocks_value, list) else None
    trans = trans_value if isinstance(trans_value, list) else None
    rev = rev_value if isinstance(rev_value, list) else None
    rep = rep_value if isinstance(rep_value, list) else None
    clips = clips_value if isinstance(clips_value, list) else None

    seg_ids = [
        str(item.get("segment_id")) for item in segs if isinstance(item, dict)
    ] if segs is not None else []

    if segs is not None:
        out.append(f"| 分段数 | {len(segs)} |")
        speakers: list = []
        end_ms = 0
        for item in segs:
            if not isinstance(item, dict):
                continue
            speaker = item.get("speaker_id")
            if speaker and speaker not in speakers:
                speakers.append(str(speaker))
            end_ms = max(end_ms, int(item.get("end_ms") or 0))
        speaker_text = "、".join(speakers) if speakers else "无"
        out.append(f"| 说话人数 | {len(speakers)}（{speaker_text}） |")
        out.append(f"| 时间轴总长 | {fmt_ms(end_ms)} |")
    else:
        out.append(f"| 分段数 | 缺失（{segs_error or '结构不符合预期'}） |")

    if blocks is not None:
        biggest = 0
        for item in blocks:
            if isinstance(item, dict):
                biggest = max(biggest, len(item.get("segment_ids") or []))
        out.append(f"| 翻译块数 | {len(blocks)}（最大块 {biggest} 段） |")
    else:
        out.append(f"| 翻译块数 | 缺失（{blocks_error or '结构不符合预期'}） |")

    if trans is not None:
        coverage = (len(trans) / len(seg_ids) * 100.0) if seg_ids else 0.0
        out.append(f"| 译文条数 | {len(trans)}（覆盖 {coverage:.1f}%） |")
        trans_ids = {
            str(item.get("segment_id")) for item in trans if isinstance(item, dict)
        }
        missing = [seg_id for seg_id in seg_ids if seg_id not in trans_ids]
        if missing:
            shown = "、".join(missing[:10])
            more = f" 等 {len(missing)} 条" if len(missing) > 10 else ""
            out.append(f"| 译文缺失 ID | {shown}{more} |")
        else:
            out.append("| 译文缺失 ID | 无 |")
    else:
        out.append(f"| 译文条数 | 缺失（{trans_error or '结构不符合预期'}） |")

    if rev is not None and trans is not None:
        trans_id_set = {
            str(item.get("segment_id")) for item in trans if isinstance(item, dict)
        }
        rev_id_set = {
            str(item.get("segment_id")) for item in rev if isinstance(item, dict)
        }
        extra = sorted(rev_id_set - trans_id_set)
        lack = sorted(trans_id_set - rev_id_set)
        parts = []
        if extra:
            parts.append("多出 " + "、".join(extra[:10]))
        if lack:
            parts.append("缺少 " + "、".join(lack[:10]))
        diff_text = "；".join(parts) if parts else "无"
        out.append(f"| 审校 vs 译文 ID 差异 | {diff_text} |")
    else:
        out.append("| 审校 vs 译文 ID 差异 | 缺失（需译文与审校结果同时存在） |")

    if rep is not None:
        out.append(f"| 修复结果条数 | {len(rep)} |")
    else:
        out.append(f"| 修复结果条数 | 缺失（{rep_error or '结构不符合预期'}） |")

    if clips is not None:
        total_ms = 0
        voices: dict = {}
        for item in clips:
            if not isinstance(item, dict):
                continue
            total_ms += int(item.get("duration_ms") or 0)
            voice = str(item.get("voice_id") or "—")
            voices[voice] = voices.get(voice, 0) + 1
        out.append(f"| TTS 条数 | {len(clips)} |")
        out.append(f"| TTS 总时长 | {fmt_ms(total_ms)} |")
        voice_text = (
            "；".join(f"`{voice}`×{count}" for voice, count in voices.items())
            if voices
            else "无"
        )
        out.append(f"| 音色 | {voice_text} |")
    else:
        out.append(f"| TTS 条数 | 缺失（{clips_error or '结构不符合预期'}） |")

    source_ms = wav_duration_ms(work_dir / "audio" / "source.wav")
    dub_ms = wav_duration_ms(work_dir / "audio" / "dub.wav")
    source_text = fmt_ms(source_ms) if source_ms is not None else "缺失"
    dub_text = fmt_ms(dub_ms) if dub_ms is not None else "缺失"
    out.append(f"| 原音轨时长 | {source_text} |")
    out.append(f"| 配音轨时长 | {dub_text} |")
    out.append("")
    return out


def _section_final_video(work_dir: Path) -> list:
    out = ["## 7. 成品视频（ffprobe）", ""]
    final = work_dir / "video" / "final.mp4"
    if not final.is_file() or final.stat().st_size <= 0:
        out.extend(["成片不存在或为空，跳过探测。", ""])
        return out

    ffprobe = find_ffprobe()
    if ffprobe is None:
        out.extend(
            ["未找到 ffprobe（查找顺序：仓库根 `.tools/ffmpeg/bin` → PATH），跳过探测。", ""]
        )
        return out

    data, error = probe_video(final, ffprobe)
    if error:
        out.extend([f"探测失败：{error}", ""])
        return out

    fmt = data.get("format") or {}
    streams = data.get("streams") or []
    videos = [s for s in streams if s.get("codec_type") == "video"]
    audios = [s for s in streams if s.get("codec_type") == "audio"]
    subtitles = [s for s in streams if s.get("codec_type") == "subtitle"]
    others = [
        s
        for s in streams
        if s.get("codec_type") not in {"video", "audio", "subtitle"}
    ]

    size = final.stat().st_size
    mtime = datetime.fromtimestamp(final.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")
    format_name = fmt.get("format_name") or "—"
    format_long = fmt.get("format_long_name") or ""
    container = f"{format_long}（`{format_name}`）" if format_long else f"`{format_name}`"

    out.extend(
        [
            "| 项目 | 值 |",
            "|---|---|",
            f"| 文件 | `video/final.mp4`（{human_size(size)}，修改于 {mtime}） |",
            f"| 容器 | {container} |",
            f"| 时长 | {_fmt_seconds(fmt.get('duration'))} |",
            f"| 总码率 | {_fmt_bitrate(fmt.get('bit_rate'))} |",
            f"| 流统计 | {len(videos)} 视频 + {len(audios)} 音频 + "
            f"{len(subtitles)} 字幕 + {len(others)} 其他 |",
            f"| ffprobe | `{ffprobe}` |",
            "",
            f"探测命令：`ffprobe -v error -show_format -show_streams -of json {final.name}`",
            "",
        ]
    )

    out.extend(["### 视频流", ""])
    if videos:
        video = videos[0]
        codec = video.get("codec_name") or "—"
        if video.get("profile"):
            codec = f"{codec}（{video['profile']}）"
        width = video.get("width")
        height = video.get("height")
        resolution = f"{width}×{height}" if width and height else "—"
        out.extend(
            [
                "| 项目 | 值 |",
                "|---|---|",
                f"| 编码 | {codec} |",
                f"| 分辨率 | {resolution} |",
                f"| 像素格式 | {video.get('pix_fmt') or '—'} |",
                f"| 帧率 | {_fmt_fps(video.get('avg_frame_rate') or video.get('r_frame_rate'))} |",
                f"| 码率 | {_fmt_bitrate(video.get('bit_rate'))} |",
                f"| 帧数 | {video.get('nb_frames') or '—'} |",
                f"| 时长 | {_fmt_seconds(video.get('duration'))} |",
                f"| start_time | {video.get('start_time') or '—'} |",
                "",
            ]
        )
    else:
        out.extend(["无视频流。", ""])

    out.extend(["### 音频流", ""])
    if audios:
        audio = audios[0]
        codec = audio.get("codec_name") or "—"
        if audio.get("profile"):
            codec = f"{codec}（{audio['profile']}）"
        sample_rate = audio.get("sample_rate")
        sample_text = f"{sample_rate} Hz" if sample_rate else "—"
        channels = audio.get("channels")
        channel_text = f"{channels}" if channels else "—"
        if audio.get("channel_layout"):
            channel_text = f"{channel_text}（{audio['channel_layout']}）"
        out.extend(
            [
                "| 项目 | 值 |",
                "|---|---|",
                f"| 编码 | {codec} |",
                f"| 采样率 | {sample_text} |",
                f"| 声道 | {channel_text} |",
                f"| 码率 | {_fmt_bitrate(audio.get('bit_rate'))} |",
                f"| 时长 | {_fmt_seconds(audio.get('duration'))} |",
                "",
            ]
        )
    else:
        out.extend(["无音频流。", ""])
    return out


def _section_traceback(log: dict) -> list:
    out = ["## 8. 异常摘录", ""]
    if log["errors"]:
        out.extend(["ERROR 日志：", ""])
        out.extend(f"- {message}" for message in log["errors"][:20])
        out.append("")
    if log["traceback"]:
        out.extend(["```text"])
        out.extend(log["traceback"])
        out.extend(["```", ""])
    elif not log["errors"]:
        out.extend(["无。", ""])
    return out


def _section_limits(traceback_lines: int = 20) -> list:
    return [
        "## 9. 数据来源与局限",
        "",
        "- 阶段耗时按日志首末时间戳近似，仅代表日志可见范围，不是节点真实耗时；"
        "无日志的节点耗时不可得。",
        "- 节点模式取自 `run.log` 中 `graph.registry` 的「节点运行模式」行；"
        "日志缺失或格式变化时标注为未识别。",
        "- 指标来自工作目录中的 JSON 产物；文件缺失或解析失败时标注为缺失，不中断报告。",
        "- mock 模式产出的内容不代表真实质量（静音音频、占位字幕、1 秒黑屏等）。",
        "- 警告汇总只统计 WARNING 级别日志。"
        "仍可在 `run.log` 中直接 grep。",
        "- 警告首条原文超过 200 字符时截断并加省略号。",
        "- 成品视频信息由 ffprobe 探测（查找顺序见 architecture.md 第 11 节）；"
        "未找到工具或探测失败时只说明原因，不中断报告。",
        f"- 异常摘录最多 {traceback_lines} 行（`--traceback-lines` 可调），"
        "遇到下一条可解析日志行即停。",
        "- 本报告不做通过/失败判定；是否可演示请结合成片与警告人工判断。",
        "",
    ]


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------


def build_report(work_dir: Path, traceback_lines: int = 20) -> str:
    log = parse_log(work_dir / "logs" / "run.log", traceback_lines=traceback_lines)
    loaded = {
        rel: load_json(work_dir / rel) for _label, rel in STRUCTURED_ARTIFACTS
    }

    lines: list = []
    lines.append(f"# 运行报告：{work_dir.name or work_dir}")
    lines.append("")
    lines.append(f"> 生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append("> 本报告只陈述事实，不做通过/失败判定；数据来源与局限见第 9 节。")
    lines.append("")
    lines.extend(_section_overview(work_dir, log))
    lines.extend(_section_conclusion(work_dir, log))
    lines.extend(_section_timing(log))
    lines.extend(_section_warnings(log))
    lines.extend(_section_artifacts(work_dir))
    lines.extend(_section_metrics(work_dir, loaded))
    lines.extend(_section_final_video(work_dir))
    lines.extend(_section_traceback(log))
    lines.extend(_section_limits(traceback_lines))
    return "\n".join(lines).rstrip() + "\n"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="run_report",
        description="读取一次运行的工作目录，生成 Markdown 运行报告（只读，不做判定）。",
    )
    parser.add_argument("--work-dir", required=True, help="运行的工作目录")
    parser.add_argument(
        "--output",
        default=None,
        help="报告输出路径；相对路径以工作目录为根，默认 <work-dir>/report.md（已存在则覆盖）",
    )
    parser.add_argument(
        "--traceback-lines",
        type=int,
        default=20,
        help="异常摘录的最大行数，默认 20",
    )
    args = parser.parse_args(argv)
    if args.traceback_lines < 1:
        parser.error("--traceback-lines 必须 >= 1")

    work_dir = Path(args.work_dir).expanduser().resolve()
    if not work_dir.exists():
        print(f"错误：工作目录不存在: {work_dir}", file=sys.stderr)
        return 2
    if not work_dir.is_dir():
        print(f"错误：工作目录不是目录: {work_dir}", file=sys.stderr)
        return 2

    report = build_report(work_dir, traceback_lines=args.traceback_lines)

    output = Path(args.output).expanduser() if args.output else Path("report.md")
    if not output.is_absolute():
        output = work_dir / output
    existed = output.exists()
    try:
        output.write_text(report, encoding="utf-8")
    except OSError as exc:
        print(f"错误：写入报告失败: {exc}", file=sys.stderr)
        return 1

    suffix = "（覆盖已有文件）" if existed else ""
    print(f"报告已写入: {output.resolve()}{suffix}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
