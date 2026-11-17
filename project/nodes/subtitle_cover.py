"""Generate three SRT tracks and the styled ASS track for burn-in."""

import logging
from contextlib import ExitStack
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Literal

from contracts import GraphState
from pydantic import BaseModel, ConfigDict, field_validator, model_validator
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
    timing_source: Literal['source','speech'] = 'source'
    speech_model_dir: str = 'models/faster-whisper-small'
    paginate: bool = False
    semantic_pairing: bool = False
    strict_single_line: bool = False
    display_font_path: str | None = None

    @model_validator(mode='after')
    def validate_single_line_mode(self):
        if self.strict_single_line and not self.paginate:
            raise ValueError('strict_single_line requires paginate=true; cannot bypass the width gate')
        return self

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
    if state.repaired_blocks:
        state=state.model_copy(update={'reviewed_blocks':state.repaired_blocks})
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
    if options.timing_source=='speech':
        from .speech_subtitles import render_speech_subtitles
        root=Path(__file__).resolve().parents[2]
        model=Path(options.speech_model_dir)
        return render_speech_subtitles(state,options,model if model.is_absolute() else root/model)
    tracks: dict[str, list[str]] = {"english_srt": [], "chinese_srt": [], "bilingual_srt": []}
    dialogue = []
    width,height=load_compose_options().output_size(video.width,video.height)
    from .dubbing_timing import forward_windows
    limits = forward_windows(segments, state.media_info.duration_ms)
    clips = {clip.segment_id: clip for clip in state.tts_clips or []}
    if options.paginate:
        from .speech_subtitles import render_cue_tracks
        rows=[]
        for segment in sorted(segments,key=lambda item:item.start_ms):
            end=segment.end_ms;clip=clips.get(segment.segment_id)
            if clip and clip.duration_ms>0:end=min(limits[segment.segment_id][1],max(end,segment.start_ms+clip.duration_ms))
            rows.append({'cue_id':segment.segment_id,'start_ms':segment.start_ms,'end_ms':end,
                         'zh':by_id[segment.segment_id],'en':segment.text_en,'source_segment_ids':[segment.segment_id]})
        return render_cue_tracks(state,options,rows)
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

        display_end = segment.end_ms
        clip = clips.get(segment.segment_id)
        if clip and clip.duration_ms > 0:
            display_end = min(limits[segment.segment_id][1], max(display_end, segment.start_ms + clip.duration_ms))
        start, end = _timestamp(segment.start_ms), _timestamp(display_end)
        header = f"{number}\n{start} --> {end}\n"
        tracks["english_srt"].append(header + english)
        tracks["chinese_srt"].append(header + chinese)
        tracks["bilingual_srt"].append(f"{header}{chinese}\n{english}")
        ass_start, ass_end = ass_times(segment.start_ms, display_end)
        dialogue.append(ass_dialogue(
            ass_start, ass_end, chinese, english, options.layout, fade_enabled=options.fade_enabled,render_height=height,
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
