"""TOML options shared by the translation, review and repair nodes."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints
from utils.config import load_config

Term = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
Style = Literal["通用", "音乐行业", "影视", "新闻", "科学与技术", "文化与历史"]

_STYLE_RULES: dict[Style, str] = {
    "通用": "用自然清楚的现代汉语，保留原文语气和信息。",
    "音乐行业": "区分录音、混音、母带制作，统一乐器、曲名和制作术语。",
    "影视": "保持人物说话语气，统一人物名、片名和影视制作术语。",
    "新闻": "用客观简练的表达，保留消息来源、引述、时间、地点和数字。",
    "科学与技术": "准确保留数字、单位、技术术语和结论成立条件，区分推测与结论。",
    "文化与历史": "统一人名、地名、年代及文化称谓，保留原有历史语境。",
}


class TerminologyOptions(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    enabled: bool = False
    entries: dict[Term, Term] = Field(default_factory=dict)


class TranslationOptions(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    style: Style = "通用"
    terminology: TerminologyOptions = Field(default_factory=TerminologyOptions)


def load_options() -> TranslationOptions:
    try:
        raw = load_config("translate_blocks.toml")
    except FileNotFoundError:
        return TranslationOptions()
    return TranslationOptions.model_validate(raw)


def with_style(prompt: str) -> str:
    style = load_options().style
    return f"{prompt}\n翻译风格：{style}。{_STYLE_RULES[style]}"
