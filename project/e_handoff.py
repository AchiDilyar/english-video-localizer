"""Local B → C/D → E handoff. Run from the repository root."""

import argparse
import json
import os
import re
import shutil
import subprocess
import wave
from pathlib import Path
from tempfile import TemporaryDirectory
from zipfile import ZIP_DEFLATED, ZipFile

from PIL import Image, ImageDraw, ImageFont
from pydantic import TypeAdapter

from contracts.edit import EditAssets
from contracts.package import ManifestEntry, PackageManifest
from contracts.segment import Segment
from contracts.translated import TranslatedSegment
from nodes.probe_input import media as b_media

UNKNOWN = "spk_unknown"


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def read_b_table(path):
    """Return shared segments and a reversible ID crosswalk for B's v2 export."""
    table = read_json(path)
    if table["schema_version"] != "b-sentences-2":
        raise ValueError("请选择 B 的 sentence-v2 任务导出。")
    if table.get("status") != "ready_for_human_review":
        raise ValueError("B 任务尚未导出可供审阅的时间表。")
    if type(table["duration_ms"]) is not int or table["duration_ms"] <= 0:
        raise ValueError("B 时间表的总时长无效。")

    if not isinstance(table.get("sentences"), list) or not table["sentences"]:
        raise ValueError("B 时间表没有已对齐的句子。")

    segments, crosswalk = [], []
    speaker_ids, sentence_ids = {}, set()
    previous_end = 0
    for sequence, row in enumerate(table["sentences"], 1):
        sentence_id = row["sentence_id"]
        if not isinstance(sentence_id, str) or not sentence_id or sentence_id in sentence_ids:
            raise ValueError("B 句子 ID 为空、格式无效或重复。")
        sentence_ids.add(sentence_id)
        start, end = row["start_ms"], row["end_ms"]
        if type(start) is not int or type(end) is not int or not previous_end <= start < end <= table["duration_ms"]:
            raise ValueError(f"{sentence_id} 的时间无效、越界或与前一句重叠。")
        previous_end = end
        if not isinstance(row["en"], str) or not row["en"].strip():
            raise ValueError(f"{sentence_id} 缺少英文。")
        raw_speaker = row["speaker_id"]
        if raw_speaker is None:
            speaker = UNKNOWN
        else:
            if not isinstance(raw_speaker, str) or not raw_speaker.strip():
                raise ValueError("B 时间表中存在无效的说话人标签。")
            if raw_speaker not in speaker_ids:
                speaker_ids[raw_speaker] = f"spk_{len(speaker_ids) + 1:03d}"
            speaker = speaker_ids[raw_speaker]
        segment = Segment(
            segment_id=f"seg_{sequence:06d}",
            speaker_id=speaker,
            start_ms=row["start_ms"],
            end_ms=row["end_ms"],
            text_en=row["en"],
        )
        segments.append(segment)
        crosswalk.append({
            "segment_id": segment.segment_id,
            "b_sentence_id": row["sentence_id"],
            "b_speaker_id": raw_speaker,
            "review_status": row.get("review_status"),
            "review_issues": row.get("review_issues", []),
        })
    return table, segments, crosswalk


def inspect_b_job(job, ffprobe):
    timetable = job / "timetable.json"
    table_hash = b_media.sha256(timetable)
    table, segments, crosswalk = read_b_table(timetable)
    if b_media.sha256(timetable) != table_hash:
        raise ValueError("B 时间表在读取时发生变化，请重试。")

    source = table["source"]
    filename = source["file"]
    if not isinstance(filename, str) or not re.fullmatch(r"video\.[A-Za-z0-9]+", filename):
        raise ValueError("B 原片文件名无效。")
    video = job / "source" / filename
    if not video.resolve().is_relative_to(job.resolve()):
        raise ValueError("B 原片不在任务目录内。")
    receipt = read_json(job / "media.json")
    request = read_json(job / "request.json")
    info = b_media.inspect(video, ffprobe, request.get("audio_stream"), request.get("video_stream"))
    if not info["source_sha256"] == receipt["video_sha256"] == source["sha256"]:
        raise ValueError("B 原片与任务记录的哈希不一致。")
    if not info["duration_ms"] == receipt["duration_ms"] == table["duration_ms"]:
        raise ValueError("B 原片与时间表的时长不一致。")
    if info["video_origin_sec"] is None:
        raise ValueError("原片缺少视频起点，无法保留 B 时间轴。")
    handoff = {
        "b_schema": table["schema_version"],
        "b_status": table["status"],
        "b_timetable_sha256": table_hash,
        "source_sha256": info["source_sha256"],
        "duration_ms": table["duration_ms"],
        "video_stream_index": info["video_stream_index"],
        "unknown_speaker_segments": [s.segment_id for s in segments if s.speaker_id == UNKNOWN],
        "untimed_utterances": table.get("review", {}).get("untimed_utterances", []),
        "crosswalk": crosswalk,
    }
    return video, segments, handoff


def prepare(job, work, ffprobe):
    _, segments, handoff = inspect_b_job(job, ffprobe)
    if work.exists():
        raise ValueError("交接目录已存在，请指定新的工作目录。")
    work.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix=".e-handoff-", dir=work.parent) as temp:
        stage = Path(temp) / "handoff"
        write_json(stage / "segments/segments.json", [s.model_dump() for s in segments])
        write_json(stage / "handoff.json", handoff)
        (stage / "translated").mkdir()
        (stage / "audio").mkdir()
        stage.rename(work)
    return work / "segments/segments.json"


def join_reviewed(segments, path):
    reviewed = TypeAdapter(list[TranslatedSegment]).validate_json(path.read_bytes())
    by_id = {row.segment_id: row for row in reviewed}
    if len(by_id) != len(reviewed) or set(by_id) != {s.segment_id for s in segments}:
        raise ValueError("审校译文的片段 ID 必须和 B 交接分段一一对应。")
    if any(not row.zh_subtitle.strip() or not row.zh_dub.strip() for row in reviewed):
        raise ValueError("审校译文的字幕或口播稿为空。")
    return [(segment, by_id[segment.segment_id]) for segment in segments]


def timestamp(milliseconds, *, ass=False):
    seconds, fraction = divmod(milliseconds, 1000)
    hours, seconds = divmod(seconds, 3600)
    minutes, seconds = divmod(seconds, 60)
    if ass:
        return f"{hours}:{minutes:02}:{seconds:02}.{fraction // 10:02}"
    return f"{hours:02}:{minutes:02}:{seconds:02},{fraction:03}"


def write_subtitles(directory, rows, font_name):
    srt, ass = [], []
    for number, (segment, translated) in enumerate(rows, 1):
        zh = " ".join(translated.zh_subtitle.split())
        en = " ".join(segment.text_en.split())
        start, end = segment.start_ms, segment.end_ms
        srt.append(f"{number}\n{timestamp(start)} --> {timestamp(end)}\n{zh}\n{en}")
        # ASS stores centiseconds. Round identical boundaries identically.
        start, end = ((value + 5) // 10 * 10 for value in (start, end))
        if start == end:
            raise ValueError(f"{segment.segment_id} 太短，无法按 ASS 精度表示。")
        literal = str.maketrans({"\\": "＼", "{": "｛", "}": "｝"})
        text = zh.translate(literal) + r"\N" + en.translate(literal)
        ass.append(
            f"Dialogue: 0,{timestamp(start, ass=True)},{timestamp(end, ass=True)},"
            f"Default,,0,0,0,,{text}"
        )
    (directory / "bilingual.srt").write_text("\n\n".join(srt) + "\n", encoding="utf-8")
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: 1920
PlayResY: 1080
WrapStyle: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{font_name},48,&H00FFFFFF,&H00FFFFFF,&H00101010,&H00000000,0,0,0,0,100,100,0,0,1,3,0,2,100,100,65,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    (directory / "burnin.ass").write_text(header + "\n".join(ass) + "\n", encoding="utf-8")


def chinese_font():
    configured = os.getenv("LOCALIZER_FONT_PATH")
    paths = [Path(configured).expanduser()] if configured else [
        Path("/System/Library/Fonts/Supplemental/Arial Unicode.ttf"),
        Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
        Path("C:/Windows/Fonts/msyh.ttc"),
    ]
    for path in paths:
        if path.is_file():
            return path
    raise ValueError("请将 LOCALIZER_FONT_PATH 指向可用的中文字体文件。")


def write_cover(path, cover_text, font_path):
    image = Image.new("RGB", (1920, 1080), "#182e3d")
    draw = ImageDraw.Draw(image)
    draw.rectangle((132, 188, 143, 870), fill="#78c9c1")
    draw.text((205, 220), "英文视频 · 中文译制", font=ImageFont.truetype(str(font_path), 46), fill="#9ddbd3")
    text = " ".join(cover_text.split())
    font = ImageFont.truetype(str(font_path), 110 if len(text) <= 36 else 82)
    lines, line = [], ""
    for character in text:
        if line and draw.textlength(line + character, font=font) > 1490:
            lines.append(line)
            line = ""
        line += character
    lines.append(line)
    if len(lines) > 4:
        raise ValueError("封面文案过长，请压缩到四行以内。")
    draw.multiline_text((205, 370), "\n".join(lines), font=font, fill="white", spacing=22)
    image.save(path, quality=92)


def compose(stage, video, dub, handoff, ffmpeg, ffprobe):
    duration = handoff["duration_ms"]
    with wave.open(str(dub), "rb") as source:
        audio_ms = source.getnframes() * 1000 / source.getframerate()
    if abs(audio_ms - duration) > 50:
        raise ValueError("D 的整轨 WAV 与 B 的全片时长差超过 50 ms，请检查音频组装。")

    command = [
        ffmpeg, "-nostdin", "-v", "error", "-protocol_whitelist", "file,pipe",
        "-i", str(video.resolve()), "-i", str(dub.resolve()),
        "-map", f"0:{handoff['video_stream_index']}", "-map", "1:a:0",
        "-vf", "setpts=PTS-STARTPTS,ass=subtitles/burnin.ass:fontsdir=fonts,"
        "pad=ceil(iw/2)*2:ceil(ih/2)*2",
        "-af", "asetpts=PTS-STARTPTS,apad", "-t", f"{duration / 1000:.3f}",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "20",
        "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", "video/final.mp4",
    ]
    result = subprocess.run(command, cwd=stage, capture_output=True, text=True, timeout=7200)
    if result.returncode:
        raise ValueError(f"FFmpeg 合成失败，请确认 FFmpeg 支持 libass。\n{result.stderr[-2000:]}")
    output = b_media.probe(stage / "video/final.mp4", ffprobe)
    if [(s["codec_type"], s["codec_name"]) for s in output["streams"]] != [
        ("video", "h264"), ("audio", "aac"),
    ]:
        raise ValueError("合成结果没有预期的 H.264 视频和 AAC 配音。")


def render(job, work, copy_path, ffmpeg, ffprobe):
    video, segments, handoff = inspect_b_job(job, ffprobe)
    if handoff != read_json(work / "handoff.json") or [s.model_dump() for s in segments] != read_json(
        work / "segments/segments.json"
    ):
        raise ValueError("交接分段或 B 时间表已变化，请用新的工作目录重新 prepare。")
    rows = join_reviewed(segments, work / "translated/reviewed_blocks.json")
    copy = EditAssets.model_validate_json(copy_path.read_bytes())
    if not all(value.strip() for value in copy.model_dump().values()):
        raise ValueError("标题、简介和封面文案不能为空。")
    font = chinese_font()
    font_name = ImageFont.truetype(str(font), 20).getname()[0]
    final = work / "e-preview"
    if final.exists():
        raise ValueError("审阅包已存在，请使用新的工作目录。")

    with TemporaryDirectory(prefix=".e-preview-", dir=work) as temp:
        stage = Path(temp) / "bundle"
        for name in ["subtitles", "cover", "video", "package", "fonts"]:
            (stage / name).mkdir(parents=True)
        shutil.copyfile(font, stage / "fonts" / font.name)
        write_subtitles(stage / "subtitles", rows, font_name)
        write_cover(stage / "cover/cover.jpg", copy.cover_text, font)
        compose(stage, video, work / "audio/dub.wav", handoff, ffmpeg, ffprobe)
        shutil.rmtree(stage / "fonts")
        write_json(stage / "edit_assets.json", copy.model_dump())
        write_json(stage / "review-report.json", {
            "status": "needs_human_review",
            "subtitle_count": len(rows),
            "handoff": handoff,
        })
        files = {
            "video": "video/final.mp4",
            "bilingual_srt": "subtitles/bilingual.srt",
            "burnin_subtitle": "subtitles/burnin.ass",
            "cover": "cover/cover.jpg",
            "edit_assets": "edit_assets.json",
            "review_report": "review-report.json",
            "manifest": "manifest.json",
        }
        manifest = PackageManifest(entries=[
            ManifestEntry(name=name, zip_path=path) for name, path in files.items()
        ])
        write_json(stage / "package/manifest.json", manifest.model_dump())
        with ZipFile(stage / "package/review.zip", "w", compression=ZIP_DEFLATED) as archive:
            for name, path in files.items():
                archive.write(stage / ("package/manifest.json" if name == "manifest" else path), path)
        stage.rename(final)
    return final / "package/review.zip"


def main():
    parser = argparse.ArgumentParser(description="衔接 B 时间表与 E 媒体审阅包。")
    sub = parser.add_subparsers(dest="operation", required=True)
    for name in ("prepare", "render"):
        command = sub.add_parser(name)
        command.add_argument("--b-job", type=Path, required=True)
        command.add_argument("--work-dir", type=Path, required=True)
    sub.choices["render"].add_argument("--edit-assets", type=Path, required=True)
    args = parser.parse_args()
    try:
        ffprobe = b_media.tool_path("ffprobe", os.getenv("LOCALIZER_FFPROBE"))
        if args.operation == "prepare":
            output = prepare(args.b_job, args.work_dir, ffprobe)
        else:
            ffmpeg = os.getenv("LOCALIZER_FFMPEG")
            if not ffmpeg:
                try:
                    from imageio_ffmpeg import get_ffmpeg_exe
                except ImportError:
                    ffmpeg = b_media.tool_path("ffmpeg")
                else:
                    ffmpeg = get_ffmpeg_exe()
            output = render(args.b_job, args.work_dir, args.edit_assets, ffmpeg, ffprobe)
    except (b_media.MediaError, ValueError, OSError, KeyError, TypeError,
            AttributeError, subprocess.SubprocessError, wave.Error, EOFError) as exc:
        parser.exit(1, f"{exc}\n")
    print(output)


if __name__ == "__main__":
    main()
