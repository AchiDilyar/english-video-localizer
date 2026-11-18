"""Compile ASS presets from the catalog shared with WebUI."""

import argparse
import json
import textwrap
from pathlib import Path

CATALOG = json.loads(
    (Path(__file__).resolve().parents[1] / "config/subtitle_styles.json").read_text(encoding="utf-8")
)
STYLES = CATALOG["styles"]
LAYOUTS = CATALOG["layouts"]
RESOLUTIONS = CATALOG["resolutions"]
DEFAULT_STYLE = CATALOG["default_style"]
DEFAULT_LAYOUT = CATALOG["default_layout"]
GEOMETRY = CATALOG["geometry"]
APPEARANCE = CATALOG["appearance"]
_LITERAL = str.maketrans({"\\": "＼", "{": "｛", "}": "｝"})


def reference_height(height):
    """Round up to a supported authoring tier, capping at 2160p."""
    return next((size for size in RESOLUTIONS if height <= size), RESOLUTIONS[-1])


def ass_color(value):
    rgb = value[1:7]
    alpha = 255 - int(value[7:9], 16) if len(value) == 9 else 0
    return f"&H{alpha:02X}{rgb[4:6]}{rgb[2:4]}{rgb[0:2]}".upper()


def style_font(style_id, layout_id=DEFAULT_LAYOUT):
    return STYLES[style_id].get("font", LAYOUTS[layout_id]["font"])


def ass_header(font_name, width, height, style_id, layout_id=DEFAULT_LAYOUT):
    layout = LAYOUTS[layout_id]
    style = APPEARANCE | STYLES[style_id]
    font = font_name or style_font(style_id, layout_id)
    play_y = reference_height(height)
    play_x = max(1, round(play_y * width / height))
    scale = play_y / GEOMETRY["height"]
    margin_x = round(GEOMETRY["margin_x"] * play_x / GEOMETRY["width"])
    color = ass_color(style["color"])
    secondary = ass_color(style["secondary"])
    border = 3 if style["box"] else 1
    styles = []
    for lang in layout["lines"]:
        size = round(GEOMETRY[f"{lang}_size"] * scale)
        margin_y = round(layout["margin_y"][lang] * scale)
        edge = ass_color(style[f"{lang}_edge"])
        background = ass_color(style.get(f"{lang}_background", style["background"]))
        outline = style[f"{lang}_outline"] * scale
        styles.append(
            f"Style: {lang.upper()},{font},{size},{color},{secondary},{edge},{background},"
            f"0,0,0,0,100,100,0,0,{border},{outline:.2f},{style['shadow'] * scale:.2f},"
            f"{GEOMETRY['alignment']},{margin_x},{margin_x},{margin_y},1"
        )
    return f"""[Script Info]
ScriptType: v4.00+
PlayResX: {play_x}
PlayResY: {play_y}
ScaledBorderAndShadow: yes
WrapStyle: {GEOMETRY["wrap_style"]}
Collisions: Normal

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
{chr(10).join(styles)}

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


def ass_dialogue(start, end, zh, en, layout_id, *, fade_enabled: bool = False, render_height=2160, wrap_english=False, wrap_chinese=False,font_sizes=None):
    if wrap_chinese:
        zh='\n'.join('\n'.join(textwrap.wrap(line,width=24,break_on_hyphens=False))
                     for line in zh.splitlines())
    if wrap_english:
        # Display-only line breaks. Never rewrite the exported English text.
        en='\n'.join('\n'.join(textwrap.wrap(line,width=64,break_long_words=False,
                    break_on_hyphens=False)) for line in en.splitlines())
    texts = {
        lang: r"\N".join(text.translate(_LITERAL).splitlines())
        for lang, text in (("zh", zh), ("en", en))
    }
    fade_tag = r"{\fad(120,120)}" if fade_enabled else ""
    layout=LAYOUTS[layout_id]
    upper_margin={}
    if len(layout['lines'])==2:
        upper,lower=layout['lines']
        lower_lines=max(1,texts[lower].count(r'\N')+1)
        if lower_lines>1:
            # Lower bottom-anchored text grows upward. Reserve its whole block.
            scale=reference_height(render_height)/GEOMETRY['height']
            upper_margin[upper]=round((layout['margin_y'][upper]+
                (lower_lines-1)*GEOMETRY[f'{lower}_size']*1.35)*scale)
    return "\n".join(
        f"Dialogue: {layer},{start},{end},{lang.upper()},,0,0,{upper_margin.get(lang,0)},,"
        f"{fade_tag}"+(r'{\fs'+str(font_sizes[lang])+'}' if font_sizes else '')+texts[lang]
        for lang, layer in (("zh", 2), ("en", 1))
        if lang in LAYOUTS[layout_id]["lines"]
    )


def ass_times(start_ms: int, end_ms: int) -> tuple[str, str]:
    """Round to ASS centiseconds, keeping at least one centisecond per cue."""
    start = (start_ms + 5) // 10
    end = max(start + 1, (end_ms + 5) // 10)
    return _ass_timestamp(start), _ass_timestamp(end)


def _ass_timestamp(centiseconds: int) -> str:
    seconds, fraction = divmod(centiseconds, 100)
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours}:{minutes:02d}:{seconds:02d}.{fraction:02d}"


def main():
    parser = argparse.ArgumentParser(description="批量生成横屏 ASS 样式样张。")
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--font-name", default=None)
    args = parser.parse_args()
    if args.font_name is not None and (
        not args.font_name.strip() or any(char in args.font_name for char in ",\r\n")
    ):
        parser.error("字体名称不能为空，也不能含逗号或换行。")
    for style in STYLES:
        for layout in LAYOUTS:
            for height in RESOLUTIONS:
                path = args.output / style / f"{layout}-{height}p.ass"
                path.parent.mkdir(parents=True, exist_ok=True)
                header = ass_header(args.font_name, round(height * 16 / 9), height, style, layout)
                sample = ass_dialogue(
                    "0:00:00.00", "0:00:04.00", "让知识跨越语言。",
                    "Let knowledge cross languages.", layout,
                    render_height=height,
                )
                path.write_text(header + sample + "\n", encoding="utf-8")
    print(f"已生成 {len(STYLES) * len(LAYOUTS) * len(RESOLUTIONS)} 份 ASS 样张：{args.output}")


if __name__ == "__main__":
    main()
