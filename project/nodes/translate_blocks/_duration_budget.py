"""Heuristic character budgets; measured TTS duration remains authoritative."""
import math
import unicodedata

from nodes.dubbing_timing import forward_windows
from utils.config import load_config

RULES=('每条输入的 target_zh_chars 是建议字数上限，按可用时长和约每秒4个中文字符估算。'
       '优先用简洁自然中文，保留事实、数字、否定、条件和关键术语；不加解释。'
       '极短回答用最短自然表达。预算无法容纳原意时保留关键含义并等待时长复核，禁止截字丢义。')


def spoken_chars(text):
    return sum(not c.isspace() and not unicodedata.category(c).startswith('P') for c in text)


def budgets_for(state):
    segments=state.segments or []
    try:options=load_config('translation_timing.toml')
    except FileNotFoundError:options={}
    rate=float(options.get('target_zh_chars_per_second',4.0))
    if not math.isfinite(rate) or not 1<=rate<=10:
        raise ValueError('target_zh_chars_per_second 必须在 1–10 之间')
    duration=state.media_info.duration_ms if state.media_info else max(s.end_ms for s in segments)
    windows=forward_windows(segments,duration)
    return {s.segment_id:{'available_duration_ms':windows[s.segment_id][1]-s.start_ms,
        'target_zh_chars':max(1,math.floor((windows[s.segment_id][1]-s.start_ms)/1000*rate)),
        'target_zh_chars_per_second':rate} for s in segments}
