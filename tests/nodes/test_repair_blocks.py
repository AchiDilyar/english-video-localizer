import pytest
from contracts import GraphState, Segment, TranslatedSegment
from nodes.build_blocks import build_blocks
from nodes.repair_blocks import repair_blocks
from nodes.review_blocks import review_blocks
from nodes.translate_blocks import _text_model, translate_blocks
from utils import config
from utils.io import read_artifact


@pytest.fixture
def state(tmp_path, monkeypatch):
    monkeypatch.setattr("utils.paths._work_dir", tmp_path)
    for name in ("segments", "translated"):
        (tmp_path / name).mkdir()
    return GraphState(segments=[
        Segment(segment_id="seg_0001", speaker_id="spk_1", start_ms=0,
                end_ms=1000, text_en="Mix the tracks."),
        Segment(segment_id="seg_0002", speaker_id="spk_1", start_ms=92_000,
                end_ms=94_000, text_en="Check the sample size."),
    ])


def test_config_applies_to_both_passes_and_repair(state, tmp_path, monkeypatch):
    monkeypatch.setattr(config, "_CONFIG_DIR", tmp_path)
    (tmp_path / "translate_blocks.toml").write_text(
        'style = "音乐行业"\n[terminology]\nenabled = true\n'
        '[terminology.entries]\n"mix" = "混音"\n',
        encoding="utf-8",
    )
    calls = []

    def model(*, instruction, payload, output_format=None):
        assert "音乐行业" in instruction
        assert instruction.count(_text_model.SUBTITLE_PUNCTUATION_RULES) == 1
        assert payload["terminology"] == {"sample size": "样本量", "mix": "混音"}
        (row,) = payload["segments"]
        calls.append(row["segment_id"])
        if output_format and "issues" in output_format:
            assert row["zh_subtitle"] == "已审校"
            issues = [{"segment_id": row["segment_id"], "reason": "术语", "target": "subtitle"}]
            return {"issues": issues if row["segment_id"] == "seg_0001" else []}
        text = (
            "先混音、再做母带，电平为-3.5 dB。" if "issues" in row
            else "已审校" if "zh_subtitle" in row else "初译"
        )
        return {"items": [{"segment_id": row["segment_id"], "zh_subtitle": text}]}

    monkeypatch.setattr(_text_model, "request_json", model)
    for node in (build_blocks, translate_blocks, review_blocks):
        state = state.model_copy(update=node(state))
    before = state.model_dump()
    result = repair_blocks(state)["repaired_blocks"]
    assert calls == ["seg_0001", "seg_0002"] * 3 + ["seg_0001"]
    assert [item.zh_subtitle for item in result] == ["先混音 再做母带 电平为-3.5 dB", "已审校"]
    assert result[1] is state.reviewed_blocks[1]
    assert read_artifact("repaired_blocks") == result
    assert read_artifact("reviewed_blocks") == state.reviewed_blocks
    assert state.model_dump() == before


def test_clean_review_returns_empty_increment(state, tmp_path, monkeypatch):
    state.reviewed_blocks = [
        TranslatedSegment(segment_id=row.segment_id, block_id="blk_0001", zh_subtitle="已审校")
        for row in state.segments
    ]

    def audit(*, instruction, payload, output_format=None):
        assert output_format and "issues" in output_format
        return {"issues": []}

    monkeypatch.setattr(_text_model, "request_json", audit)
    assert repair_blocks(state) == {}
    assert not (tmp_path / "translated/repaired_blocks.json").exists()


def test_missing_review_returns_empty_increment(state, monkeypatch):
    monkeypatch.setattr(
        _text_model, "request_json", lambda **_: pytest.fail("Missing review reached the model")
    )
    assert repair_blocks(state) == {}


@pytest.mark.parametrize(
    ("returned", "expected"),
    [
        ("他说：\"增益为.5 dB。\"", "他说 “增益为.5 dB”"),
        ("用C::mix，比例2:1；先听A、B，还是C？", "用C::mix 比例2:1 先听A B 还是C？"),
        ("详见https://example.com:8443/?a=1,b=2。", "详见https://example.com:8443/?a=1,b=2"),
        ("按1,2,3的顺序，样本数为1,000。", "按1 2 3的顺序 样本数为1,000"),
        ("继续！", "继续！"),
        ("已审校。", None),
    ],
)
def test_repair_normalizes_subtitle_and_skips_no_op(state, tmp_path, monkeypatch, returned, expected):
    segment = state.segments[0]
    state.segments = [segment]
    state.reviewed_blocks = [
        TranslatedSegment(segment_id=segment.segment_id, block_id="blk_0001", zh_subtitle="已审校")
    ]
    responses = iter([
        {"issues": [{"segment_id": segment.segment_id, "reason": "漏译", "target": "subtitle"}]},
        {"items": [{"segment_id": segment.segment_id, "zh_subtitle": returned}]},
    ])
    monkeypatch.setattr(_text_model, "request_json", lambda **_: next(responses))
    result = repair_blocks(state)
    if expected is None:
        assert result == {}
        assert not (tmp_path / "translated/repaired_blocks.json").exists()
    else:
        assert result["repaired_blocks"][0].zh_subtitle == expected


def test_punctuation_only_repair_is_not_published(state, tmp_path, monkeypatch):
    segment = state.segments[0]
    state.segments = [segment]
    state.reviewed_blocks = [
        TranslatedSegment(segment_id=segment.segment_id, block_id="blk_0001", zh_subtitle="已审校")
    ]
    responses = iter([
        {"issues": [{"segment_id": segment.segment_id, "reason": "漏译", "target": "subtitle"}]},
        {"items": [{"segment_id": segment.segment_id, "zh_subtitle": "，。"}]},
    ])
    monkeypatch.setattr(_text_model, "request_json", lambda **_: next(responses))
    with pytest.raises(ValueError, match=segment.segment_id):
        repair_blocks(state)
    assert not (tmp_path / "translated/repaired_blocks.json").exists()
