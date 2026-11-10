"""Compile landscape ASS presets from the catalog shared with WebUI."""

import argparse
import json
from pathlib import Path

CATALOG = json.loads(
    (Path(__file__).resolve().parents[1] / "config/subtitle_styles.json").read_text(encoding="utf-8")
)
STYLES = CATALOG["styles"]
LAYOUTS = CATALOG["layouts"]
RESOLUTIONS = CATALOG["resolutions"]
DEFAULT_STYLE = CATALOG["default_style"]
DEFAULT_LAYOUT = CATALOG["default_layout"]
_LITERAL = str.maketrans({"\\": "＼", "{": "｛", "}": "｝"})


def reference_height(height):
    """Round up to a supported authoring tier, capping at 2160p."""
    return next((size for size in RESOLUTIONS if height <= size), RESOLUTIONS[-1])


def ass_color(value):
    rgb = value[1:7]
    alpha = 255 - int(value[7:9], 16) if len(value) == 9 else 0
    return f"&H{alpha:02X}{rgb[4:6]}{rgb[2:4]}{rgb[0:2]}".upper()


def ass_header(font_name, width, height, style_id):
    style = STYLES[style_id]
    play_y = reference_height(height)
    play_x = max(1, round(play_y * width / height))
    scale = play_y / 1080
    margin_x = round(style["margin_x"] * play_x / 1920)
    margin_y = round(style["margin_y"] * scale)
    edge = ass_color(style["edge_color"])
    border = 3 if style["box"] else 1
    bold = -1 if style["bold"] else 0
    styles = []
    for lang in ("zh", "en"):
        color = ass_color(style[f"{lang}_color"])
        size = round(style[f"{lang}_size"] * scale)
        styles.append(
            f"Style: {lang.upper()},{font_name},{size},{color},{color},{edge},&H80000000,"
            f"{bold},0,0,0,100,100,0,0,{border},{style['outline'] * scale:.2f},"
            f"{style['shadow'] * scale:.2f},2,{margin_x},{margin_x},{margin_y},1"
        )
    return f"""[Script Info]
ScriptType: v4.00+
PlayResX: {play_x}
PlayResY: {play_y}
ScaledBorderAndShadow: yes
WrapStyle: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
{chr(10).join(styles)}

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


def ass_dialogue(start, end, zh, en, layout_id):
    texts = {"zh": zh, "en": en}
    first, *other = LAYOUTS[layout_id]["lines"]
    text = texts[first].translate(_LITERAL)
    for lang in other:
        text += r"\N{\r" + lang.upper() + "}" + texts[lang].translate(_LITERAL)
    return f"Dialogue: 0,{start},{end},{first.upper()},,0,0,0,,{text}"


def main():
    parser = argparse.ArgumentParser(description="批量生成横屏 ASS 样式样张。")
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--font-name", default="Noto Sans CJK SC")
    args = parser.parse_args()
    if not args.font_name.strip() or any(char in args.font_name for char in ",\r\n"):
        parser.error("字体名称不能为空，也不能含逗号或换行。")
    for style in STYLES:
        for layout in LAYOUTS:
            for height in RESOLUTIONS:
                path = args.output / style / f"{layout}-{height}p.ass"
                path.parent.mkdir(parents=True, exist_ok=True)
                header = ass_header(args.font_name, height * 16 // 9, height, style)
                sample = ass_dialogue(
                    "0:00:00.00", "0:00:04.00", "让知识跨越语言。",
                    "Let knowledge cross languages.", layout,
                )
                path.write_text(header + sample + "\n", encoding="utf-8")
    print(f"已生成 {len(STYLES) * len(LAYOUTS) * len(RESOLUTIONS)} 份 ASS 样张：{args.output}")


if __name__ == "__main__":
    main()
