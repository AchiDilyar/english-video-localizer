"""Generate three SRT tracks and the styled ASS track for burn-in."""

import logging
from contextlib import ExitStack
from pathlib import Path
from tempfile import NamedTemporaryFile

from contracts import GraphState
from pydantic import BaseModel, ConfigDict, field_validator
from subtitle_templates import (
    DEFAULT_LAYOUT,
    DEFAULT_STYLE,
    LAYOUTS,
    STYLES,
    ass_dialogue,
    ass_header,
    ass_times,
    reference_height,
)
from utils.config import load_config
from utils.paths import artifact_path

from .compose_settings import load_compose_options

logger = logging.getLogger(__name__)


class SubtitleCoverOptions(BaseModel):
    model_config = ConfigDict(extra="forbid")

    style: str = DEFAULT_STYLE
    layout: str = DEFAULT_LAYOUT
    fade_enabled: bool = False

    @field_validator("style")
    @classmethod
    def validate_style(cls, value: str) -> str:
        if value not in STYLES:
            raise ValueError("未知的字幕风格")
        return value

    @field_validator("layout")
    @classmethod
    def validate_layout(cls, value: str) -> str:
        if value not in LAYOUTS:
            raise ValueError("未知的字幕语言排布")
        return value


def _timestamp(milliseconds: int) -> str:
    seconds, milliseconds = divmod(milliseconds, 1000)
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{milliseconds:03d}"


def _write_tracks(tracks: dict[str, str]) -> None:
    # Stage all tracks before publishing, and replace each file atomically.
    with ExitStack() as cleanup:
        staged = []
        for name, content in tracks.items():
            target = Path(artifact_path(name))
            with NamedTemporaryFile(
                mode="w", encoding="utf-8", newline="\n", dir=target.parent, delete=False
            ) as output:
                candidate = Path(output.name)
                cleanup.callback(candidate.unlink, missing_ok=True)
                output.write(content)
            staged.append((candidate, target))
        for candidate, target in staged:
            candidate.replace(target)


def subtitle_cover(state: GraphState) -> dict:
    """Write SRT and ASS using the transcription, reviewed subtitles and probed dimensions."""
    segments = state.segments
    reviewed = state.reviewed_blocks
    if not segments or not reviewed:
        raise ValueError("字幕压制准备需要非空的原文分段和审校译文。")

    source_ids = {segment.segment_id for segment in segments}
    if len(source_ids) != len(segments):
        raise ValueError("原文字幕的 segment_id 重复。")

    by_id: dict[str, str] = {}
    for item in reviewed:
        if item.segment_id in by_id:
            raise ValueError(f"审校译文的 segment_id 重复：{item.segment_id}")
        by_id[item.segment_id] = item.zh_subtitle
    missing = source_ids - by_id.keys()
    extra = by_id.keys() - source_ids
    if missing or extra:
        raise ValueError(
            f"原文和审校译文的 segment_id 不匹配，缺少译文：{sorted(missing)}，"
            f"多余译文：{sorted(extra)}"
        )

    if state.media_info is None:
        raise ValueError("字幕压制准备需要视频探测结果中的画面尺寸。")
    video = state.media_info.video_info
    options = SubtitleCoverOptions.model_validate(load_config("subtitle_cover.toml"))
    tracks: dict[str, list[str]] = {"english_srt": [], "chinese_srt": [], "bilingual_srt": []}
    dialogue = []
    for number, segment in enumerate(sorted(segments, key=lambda item: item.start_ms), start=1):
        if segment.end_ms > state.media_info.duration_ms:
            raise ValueError(f"{segment.segment_id} 的字幕结束时间超出视频时长。")

        # Blank lines delimit cues. The workbench reads one Chinese line per bilingual cue.
        english = "\n".join(line.strip() for line in segment.text_en.splitlines() if line.strip())
        chinese = " ".join(
            line.strip() for line in by_id[segment.segment_id].splitlines() if line.strip()
        )
        if not english or not chinese:
            raise ValueError(f"{segment.segment_id} 的原文或审校译文为空。")

        start, end = _timestamp(segment.start_ms), _timestamp(segment.end_ms)
        header = f"{number}\n{start} --> {end}\n"
        tracks["english_srt"].append(header + english)
        tracks["chinese_srt"].append(header + chinese)
        tracks["bilingual_srt"].append(f"{header}{chinese}\n{english}")
        ass_start, ass_end = ass_times(segment.start_ms, segment.end_ms)
        dialogue.append(ass_dialogue(
            ass_start, ass_end, chinese, english, options.layout, fade_enabled=options.fade_enabled,
        ))

    outputs = {name: "\n\n".join(cues) + "\n" for name, cues in tracks.items()}
    width, height = load_compose_options().output_size(video.width, video.height)
    header = ass_header(None, width, height, options.style, options.layout)
    # Publish the completion artifact after the three companion SRTs.
    outputs["burnin_subtitle"] = header + "\n".join(dialogue) + "\n"
    _write_tracks(outputs)
    logger.info(
        "字幕压制准备完成：已生成三份 SRT 与 burnin.ass，共 %d 条，风格=%s，排布=%s，档位=%dp。",
        len(segments), options.style, options.layout, reference_height(height),
    )
    return {}
