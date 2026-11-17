"""Smoke tests for the C sub-chain on a real segments.json input."""

import pytest

from utils.io import read_artifact

from nodes.build_blocks import build_blocks
from nodes.translate_blocks import translate_blocks
from nodes.review_blocks import review_blocks


def test_c_chain_produces_readable_artifacts(work_dir, seeded_state, llm_stub):
    state = seeded_state

    inc = build_blocks(state)
    state = state.model_copy(update=inc)
    assert (work_dir / "segments" / "blocks.json").exists()
    blocks = read_artifact("blocks")
    assert len(blocks) > 0
    assert all(b.block_id for b in blocks)  # TranslationBlock uses block_id

    inc = translate_blocks(state)
    state = state.model_copy(update=inc)
    assert (work_dir / "translated" / "translated_blocks.json").exists()
    drafts = read_artifact("translated_blocks")
    seg_ids = [s.segment_id for s in state.segments]
    assert [d.segment_id for d in drafts] == seg_ids

    inc = review_blocks(state)
    state = state.model_copy(update=inc)
    assert (work_dir / "translated" / "reviewed_blocks.json").exists()
    reviewed = read_artifact("reviewed_blocks")
    assert [r.segment_id for r in reviewed] == seg_ids

    assert llm_stub["calls"]["translate"] >= 1
    assert llm_stub["calls"]["review"] >= 1


def test_c_chain_fails_when_llm_missing_id(work_dir, seeded_state, llm_stub):
    llm_stub["mode"] = "missing_id"
    state = seeded_state

    inc = build_blocks(state)
    state = state.model_copy(update=inc)

    with pytest.raises(ValueError, match="遗漏"):
        translate_blocks(state)

    # Failure in translate must not leave downstream artifacts behind
    assert not (work_dir / "translated" / "translated_blocks.json").exists()
    assert not (work_dir / "translated" / "reviewed_blocks.json").exists()