"""Read-only subtitle data for the workflow's review panel."""

import json
import re
import sys
from pathlib import Path

STAGES = {
    "initial": ("b/initial.srt",),
    "segmented": ("subtitles/english_segmented.srt", "b/english.srt"),
    "draft": ("subtitles/translated.srt",),
    "final": ("subtitles/bilingual.srt",),
}
TRANSLATIONS = {
    "draft": "translated/translated_blocks.json",
    "final": "translated/reviewed_blocks.json",
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


def structured_translation(job: Path, stage: str) -> list[dict] | None:
    translation_file = job / TRANSLATIONS[stage]
    segments_file = job / "segments/segments.json"
    if not translation_file.is_file() or not segments_file.is_file():
        return None
    segments = json.loads(read_text(segments_file))
    translations = json.loads(read_text(translation_file))
    by_id = {row["segment_id"]: row["zh_subtitle"] for row in translations}
    if len(by_id) != len(translations) or len(by_id) != len(segments):
        raise ValueError("译文和原文分段数量不匹配。")
    cues = []
    seen = set()
    for row in segments:
        key = row["segment_id"]
        start, end = row["start_ms"], row["end_ms"]
        original, translation = row["text_en"], by_id[key]
        if (key in seen or type(start) is not int or type(end) is not int or not 0 <= start < end
                or not original.strip() or not translation.strip()):
            raise ValueError("翻译阶段的分段或时间轴无效。")
        seen.add(key)
        cues.append(dict(start_ms=start, end_ms=end, original=original, translation=translation))
    return sorted(cues, key=lambda cue: cue["start_ms"])


def subtitle_stage(job: Path, stage: str) -> dict:
    for filename in STAGES[stage]:
        candidate = job / filename
        if candidate.is_file():
            cues = parse_srt(read_text(candidate), bilingual=stage in TRANSLATIONS)
            return {"stage": stage, "ready": True, "cues": cues}
    if stage in TRANSLATIONS:
        cues = structured_translation(job, stage)
        if cues is not None:
            return {"stage": stage, "ready": True, "cues": cues}
    return {"stage": stage, "ready": False, "cues": []}


def srt_time(value: int) -> str:
    seconds, ms = divmod(value, 1000)
    minutes, second = divmod(seconds, 60)
    hour, minute = divmod(minutes, 60)
    return f"{hour:02d}:{minute:02d}:{second:02d},{ms:03d}"


def save_initial_preview(b_job: Path) -> None:
    """Save B's first sentence snapshot without retaining native word alignments."""
    from langgraph.checkpoint.sqlite import SqliteSaver
    from nodes.asr_diarize.pipeline.sentence_mode import build_sentence_graph

    config = {"configurable": {"thread_id": b_job.name}}
    with SqliteSaver.from_conn_string(str(b_job / "checkpoints.sqlite")) as saver:
        graph = build_sentence_graph(saver)
        for state in graph.get_state_history(config):
            if state.next == ("recheck_incomplete_audio",):
                rows = state.values["table"]["sentences"]
                break
        else:
            return
    blocks = [
        f'{index}\n{srt_time(row["start_ms"])} --> {srt_time(row["end_ms"])}\n{row["en"]}'
        for index, row in enumerate(rows, 1)
        if 0 <= row["start_ms"] < row["end_ms"] and row["en"].strip()
    ]
    if blocks:
        pending = b_job / "initial.srt.tmp"
        pending.write_text("\n\n".join(blocks) + "\n", encoding="utf-8")
        pending.replace(b_job / "initial.srt")


if __name__ == "__main__":
    save_initial_preview(Path(sys.argv[1]))
