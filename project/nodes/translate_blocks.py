"""Translate each block into subtitles and dubbing text."""

from contracts import GraphState, TranslatedSegment
from utils.io import write_artifact

from . import _text_model


TRANSLATE_PROMPT = (
    "将每个英文片段翻译成简体中文，遵循术语表，结合本块上下文理解语义。"
    "zh_subtitle 用于屏幕阅读，zh_dub 用于自然朗读。"
    "参考 duration_ms 缩短口播，保留数字、单位、否定和成立条件。"
)


def translate_blocks(state: GraphState) -> dict:
    """Return a flat list of draft translations in block and segment order."""
    segments = state.segments or []
    by_id = {segment.segment_id: segment for segment in segments}
    blocks = state.blocks or []
    block_segment_ids = [segment_id for block in blocks for segment_id in block.segment_ids]
    if not segments or len(by_id) != len(segments):
        raise ValueError("翻译需要非空且 ID 唯一的英文分段。")
    if len(block_segment_ids) != len(by_id) or set(block_segment_ids) != by_id.keys():
        raise ValueError("翻译块必须覆盖每个英文分段恰好一次。")
    if len({block.block_id for block in blocks}) != len(blocks):
        raise ValueError("翻译块 ID 重复。")

    drafts: list[TranslatedSegment] = []
    for block in blocks:
        response = _text_model.request_json(
            instruction=TRANSLATE_PROMPT,
            payload={
                "terminology": state.terminology or {},
                "segments": [_text_model.source_fields(by_id[key]) for key in block.segment_ids],
            },
        )
        drafts.extend(_text_model.validate_items(response, block.block_id, block.segment_ids))
    write_artifact("translated_blocks", drafts)
    return {"translated_blocks": drafts}
