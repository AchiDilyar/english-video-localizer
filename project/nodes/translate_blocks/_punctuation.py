"""Apply the shared Chinese subtitle punctuation rules at model and export boundaries."""

import re

# Keep punctuation that carries meaning in numeric and technical expressions.
_PUNCTUATION = re.compile(
    r"(?P<protected>"
    r"(?i:https?|ftp)://[A-Za-z0-9][A-Za-z0-9._~:/?#\[\]@!$&()*+,;=%-]*(?<![.,;:!?])"
    r"|(?<![A-Za-z0-9])(?:[A-Za-z]\.){2,}(?![A-Za-z0-9])"
    r"|(?<=[A-Za-z0-9])\.(?=[A-Za-z0-9])|(?<![A-Za-z0-9.])\.(?=[0-9])"
    r"|(?<=[0-9]),(?=[0-9]{3}(?![0-9]))|(?<=[0-9]):(?=[0-9])"
    r"|(?<=[A-Za-z0-9_])::(?=[A-Za-z0-9_]))|[、，。；：,.;:]"
)
_DOUBLE_QUOTES = re.compile(r'(?<![0-9])"([^"\n]+)"')
_SINGLE_QUOTES = re.compile(
    r"(?<![A-Za-z0-9])'((?:[^'\n]|(?<=[A-Za-z])'(?=[A-Za-z]))+)'(?![A-Za-z0-9])"
)


def normalize_repaired_subtitle(text: str) -> str:
    """Convert prose punctuation and trim spaces next to closing punctuation."""
    text = _DOUBLE_QUOTES.sub(r"“\1”", text)
    text = _SINGLE_QUOTES.sub(r"‘\1’", text)
    text = _PUNCTUATION.sub(lambda match: match["protected"] or " ", text)
    return re.sub(r" +(?=[”’!?？！])", "", " ".join(text.split()))


def normalize_display_subtitle(text: str) -> str:
    """Preserve intentional visual line breaks while normalizing Chinese punctuation."""
    lines = [normalize_repaired_subtitle(line) for line in text.splitlines()]
    result = "\n".join(line for line in lines if line)
    if not result:
        raise ValueError("中文字幕去除标点后为空，无法导出。")
    return result
