"""Group source segments into translation blocks."""

from __future__ import annotations

from contracts import GraphState, TranslationBlock
from utils.io import write_artifact

from .translate_blocks._options import load_options

MAX_BLOCK_SPAN_MS = 90_000
DEFAULT_TERMINOLOGY = {"sample size": "样本量"}


def build_blocks(state: GraphState) -> dict:
    """Persist translation blocks, keeping every upstream segment intact."""
    if not state.segments:
        raise ValueError("无法分块：没有英文分段。")
    segments = sorted(state.segments, key=lambda segment: segment.start_ms)

    seen_ids: set[str] = set()
    groups: list[list[str]] = []
    current_ids: list[str] = []
    start_ms = end_ms = segments[0].start_ms

    for segment in segments:
        if segment.segment_id in seen_ids:
            raise ValueError(f"无法分块：重复的分段 ID {segment.segment_id}。")
        seen_ids.add(segment.segment_id)

        next_end_ms = max(end_ms, segment.end_ms)
        if current_ids and next_end_ms - start_ms > MAX_BLOCK_SPAN_MS:
            groups.append(current_ids)
            current_ids = []
            start_ms = segment.start_ms
            next_end_ms = segment.end_ms

        current_ids.append(segment.segment_id)
        end_ms = next_end_ms

    groups.append(current_ids)
    blocks = [
        TranslationBlock(block_id=f"blk_{number:04d}", segment_ids=segment_ids)
        for number, segment_ids in enumerate(groups, start=1)
    ]
    terminology = DEFAULT_TERMINOLOGY if state.terminology is None else state.terminology
    options = load_options().terminology
    if options.enabled:
        terminology = {**terminology, **options.entries}
    write_artifact("blocks", blocks)
    return {"blocks": blocks, "terminology": dict(terminology)}
