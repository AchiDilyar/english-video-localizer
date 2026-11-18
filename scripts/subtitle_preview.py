"""Read-only subtitle data for the workflow's review panel."""

import re
from pathlib import Path

from pydantic import TypeAdapter
from utils.artifacts import ARTIFACT_SPECS

STAGES = {
    "initial": ("b/initial.srt",),
    "segmented": ("subtitles/english_segmented.srt", "b/english.srt"),
    "draft": ("subtitles/translated.srt",),
    "final": (ARTIFACT_SPECS["bilingual_srt"].path,),
}
TRANSLATIONS = {
    "draft": "translated_blocks",
    "final": "reviewed_blocks",
}
TIME = r"(\d{2,}:\d{2}:\d{2}[,.]\d{3})"
TIMING = re.compile(rf"^\s*{TIME}\s*-->\s*{TIME}(?:\s+.*)?$")
MAX_TEXT_BYTES = 16 * 1024 * 1024


def read_text(path: Path) -> str:
    with path.open("rb") as source:
        content = source.read(MAX_TEXT_BYTES + 1)
    if len(content) > MAX_TEXT_BYTES:
        raise ValueError("字幕产物超过预览大小限制。")
    return content.decode("utf-8-sig")


def milliseconds(stamp: str) -> int:
    hours, minutes, rest = stamp.split(":")
    seconds, fraction = re.split("[,.]", rest)
    return ((int(hours) * 60 + int(minutes)) * 60 + int(seconds)) * 1000 + int(fraction)


def parse_srt(text: str, *, bilingual: bool) -> list[dict]:
    cues = []
    text = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    for block in re.split(r"\n[ \t]*\n", text) if text else []:
        lines = block.split("\n")
        if lines[0].strip().isdigit():
            lines.pop(0)
        match = TIMING.fullmatch(lines[0])
        if not match or len(lines) < 2:
            raise ValueError("SRT 字幕块格式不正确。")
        start, end = map(milliseconds, match.groups())
        if end <= start:
            raise ValueError("SRT 字幕块的结束时间必须大于开始时间。")
        original = "\n".join(lines[2:] if bilingual else lines[1:]).strip()
        translation = lines[1].strip() if bilingual else None
        if not original or (bilingual and not translation):
            raise ValueError("字幕缺少原文或译文。")
        cues.append(dict(start_ms=start, end_ms=end, original=original, translation=translation))
    return sorted(cues, key=lambda cue: cue["start_ms"])


def read_rows(job: Path, name: str):
    # HTTP handlers can read multiple jobs concurrently. Use the shared path and
    # validation type without setting the CLI's process-global work directory.
    spec = ARTIFACT_SPECS[name]
    path = job / spec.path
    if path.is_file():
        return TypeAdapter(spec.type_).validate_json(read_text(path))
    return None


def structured_cues(job: Path, stage: str) -> list[dict] | None:
    segments = read_rows(job, "segments")
    if segments is None:
        return None
    ids = {row.segment_id for row in segments}
    if len(ids) != len(segments):
        raise ValueError("原文分段 ID 重复。")

    by_id = {}
    if stage in TRANSLATIONS:
        translations = read_rows(job, "repaired_blocks") if stage == "final" else None
        if translations is None:
            translations = read_rows(job, TRANSLATIONS[stage])
        if translations is None:
            return None
        by_id = {row.segment_id: row.zh_subtitle for row in translations}
        if len(by_id) != len(translations) or by_id.keys() != ids:
            raise ValueError("译文和原文分段不匹配。")

    cues = []
    for row in segments:
        translation = by_id.get(row.segment_id)
        if not row.text_en.strip() or (translation is not None and not translation.strip()):
            raise ValueError("字幕缺少原文或译文。")
        cues.append(dict(start_ms=row.start_ms, end_ms=row.end_ms,
                         original=row.text_en, translation=translation))
    return sorted(cues, key=lambda cue: cue["start_ms"])


def subtitle_stage(job: Path, stage: str) -> dict:
    for filename in STAGES[stage]:
        candidate = job / filename
        if candidate.is_file():
            cues = parse_srt(read_text(candidate), bilingual=stage in TRANSLATIONS)
            return {"stage": stage, "ready": True, "cues": cues}
    if stage != "initial":
        cues = structured_cues(job, stage)
        if cues is not None:
            return {"stage": stage, "ready": True, "cues": cues}
    return {"stage": stage, "ready": False, "cues": []}
