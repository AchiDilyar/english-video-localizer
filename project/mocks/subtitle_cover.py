"""subtitle_cover 的 mock 实现：结构验证用，不做真实字幕生成。

新 workflow 中本节点只写双语 SRT 与烧录字幕，不再生成封面图。
落盘：
- subtitles/bilingual.srt：1 条合法 SRT
- subtitles/burnin.ass：合法 ASS 头 + 1 条 Dialogue
不读取 GraphState，返回空增量。
"""

from __future__ import annotations

from pathlib import Path

from utils.paths import artifact_path


_SRT_CONTENT = """1
00:00:00,000 --> 00:00:01,000
[占位] bilingual subtitle

"""

_ASS_CONTENT = """[Script Info]
Title: Placeholder
ScriptType: v4.00+

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Arial,20,&H00FFFFFF,&H000000FF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,2,2,2,10,10,10,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: 0,0:00:00.00,0:00:01.00,Default,,0,0,0,,占位字幕
"""


def subtitle_cover(state) -> dict:
    Path(artifact_path("bilingual_srt")).write_text(_SRT_CONTENT, encoding="utf-8")
    Path(artifact_path("burnin_subtitle")).write_text(_ASS_CONTENT, encoding="utf-8")
    return {}