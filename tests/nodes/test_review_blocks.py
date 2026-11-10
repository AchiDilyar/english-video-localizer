import pytest

from contracts import GraphState, Segment, TranslatedSegment
from nodes import _text_model
from nodes.review_blocks import ReviewIssue, find_review_issues, repair_segments, should_repair


@pytest.fixture
def state():
    first = Segment(
        segment_id="seg_0001", speaker_id="spk_1", start_ms=0, end_ms=5_000,
        text_en="Only proceed if the sample size is at least 12.",
    )
    second = Segment(
        segment_id="seg_0002", speaker_id="spk_1", start_ms=92_000, end_ms=95_000,
        text_en="Record the sample size.",
    )
    return GraphState(
        segments=[first, second],
        terminology={"sample size": "样本量"},
        translated_blocks=[
            TranslatedSegment(
                segment_id=first.segment_id, block_id="blk_0001",
                zh_subtitle="只有样本量至少为 12 时才能继续。", zh_dub="可以继续。",
            ),
            TranslatedSegment(
                segment_id=second.segment_id, block_id="blk_0002",
                zh_subtitle="记录样本量。", zh_dub="记下样本量。",
            ),
        ],
    )


def test_clean_audit_does_not_request_a_repair(state, monkeypatch):
    state.translated_blocks[0] = state.translated_blocks[0].model_copy(
        update={"zh_dub": "样本量至少为十二才能继续。"}
    )
    monkeypatch.setattr(_text_model, "request_json", lambda **kwargs: {"issues": []})
    issues = find_review_issues(state)
    assert issues == []
    assert should_repair(issues) is False

    def unexpected_request(**kwargs):
        pytest.fail("A clean result must not call the model for repair")

    monkeypatch.setattr(_text_model, "request_json", unexpected_request)
    assert repair_segments(state, issues) == state.translated_blocks


def test_audit_and_repair_only_change_the_flagged_field(state, monkeypatch):
    def audit(**request):
        assert request["payload"]["terminology"] == {"sample size": "样本量"}
        (row,) = request["payload"]["segments"]
        if row["segment_id"] == "seg_0001":
            return {"issues": [{"segment_id": "seg_0001", "reason": "口播漏掉样本量限制", "target": "dub"}]}
        return {"issues": []}

    monkeypatch.setattr(_text_model, "request_json", audit)
    issues = find_review_issues(state)
    assert [issue.model_dump() for issue in issues] == [
        {"segment_id": "seg_0001", "reason": "口播漏掉样本量限制", "target": "dub"}
    ]
    assert should_repair(issues) is True

    def rewrite(**request):
        assert request["payload"]["terminology"] == {"sample size": "样本量"}
        (row,) = request["payload"]["segments"]
        assert row["segment_id"] == "seg_0001"
        assert row["issues"][0]["reason"] == "口播漏掉样本量限制"
        return {"items": [{
            "segment_id": "seg_0001",
            "zh_subtitle": "模型提出了未经要求的字幕修改。",
            "zh_dub": "样本量至少为十二才能继续。",
        }]}

    monkeypatch.setattr(_text_model, "request_json", rewrite)
    repaired = repair_segments(state, issues)
    assert repaired[0].zh_dub == "样本量至少为十二才能继续。"
    assert repaired[0].zh_subtitle == state.translated_blocks[0].zh_subtitle
    assert repaired[0].block_id == "blk_0001"
    assert repaired[1] is state.translated_blocks[1]
    assert state.translated_blocks[0].zh_dub == "可以继续。"


def test_audit_rejects_an_id_outside_its_block(state, monkeypatch):
    monkeypatch.setattr(_text_model, "request_json", lambda **kwargs: {
        "issues": [{"segment_id": "seg_0002", "reason": "错段", "target": "both"}]
    })
    with pytest.raises(ValueError, match="seg_0002"):
        find_review_issues(state)


def test_repair_rejects_an_unrequested_segment_in_model_output(state, monkeypatch):
    monkeypatch.setattr(_text_model, "request_json", lambda **kwargs: {
        "items": [{"segment_id": "seg_0002", "zh_subtitle": "不该更新", "zh_dub": "不该更新"}]
    })
    with pytest.raises(ValueError, match="seg_0002"):
        repair_segments(state, [ReviewIssue(segment_id="seg_0001", reason="漏译", target="dub")])
