"""Review the shared Chinese translation against the English source."""

from contracts import GraphState, TranslatedSegment
from utils.io import write_artifact

from .translate_blocks import _text_model
from .translate_blocks._options import with_style
from .translate_blocks._duration_budget import budgets_for, RULES

REVIEW_PROMPT = (
    "对照英文和术语表逐条核对用于显示和朗读的中文译文。"
    "修正错漏译、术语不一致、数字单位、否定和条件错误。"
    "译文应自然简洁并保留原义，参考 duration_ms。"
    "未发现问题时保留该条译文。返回审校后的完整中文译文。"
) + _text_model.SUBTITLE_PUNCTUATION_RULES + RULES


def review_blocks(state: GraphState) -> dict:
    """Return final translations with the same IDs and order as the drafts."""
    by_id, drafts, grouped = _text_model.group_translations(state.segments, state.translated_blocks, "审校")

    instruction = with_style(REVIEW_PROMPT)
    budgets = budgets_for(state)
    reviewed: dict[str, TranslatedSegment] = {}
    for block_id, block_drafts in grouped.items():
        response = _text_model.request_json(
            instruction=instruction,
            payload={
                "terminology": state.terminology or {},
                "segments": [
                    {**_text_model.translation_fields(by_id[draft.segment_id], draft), **budgets[draft.segment_id]}
                    for draft in block_drafts
                ],
            },
        )
        items = _text_model.validate_items(response, block_id, [draft.segment_id for draft in block_drafts])
        reviewed.update((item.segment_id, item) for item in items)
    result = [reviewed[draft.segment_id] for draft in drafts]
    write_artifact("reviewed_blocks", result)
    return {"reviewed_blocks": result}
