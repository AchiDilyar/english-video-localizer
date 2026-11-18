import pytest
from contracts import GraphState, Segment
from nodes.repair_blocks import ReviewIssue, find_review_issues, repair_segments
from nodes.translate_blocks import _text_model


def make_draft(segment_id, block_id, text):
    response = {"items": [{"segment_id": segment_id, "zh_subtitle": text}]}
    return _text_model.validate_items(response, block_id, [segment_id])[0]


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
        reviewed_blocks=[
            make_draft(first.segment_id, "blk_0001", "可以继续。"),
            make_draft(second.segment_id, "blk_0002", "记录样本量。"),
        ],
    )


def test_clean_audit_does_not_request_a_repair(state, monkeypatch):
    state.reviewed_blocks[0] = make_draft("seg_0001", "blk_0001", "样本量至少为十二才能继续。")
    monkeypatch.setattr(_text_model, "request_json", lambda **kwargs: {"issues": []})
    issues = find_review_issues(state)
    assert issues == []

    def unexpected_request(**kwargs):
        pytest.fail("A clean result must not call the model for repair")

    monkeypatch.setattr(_text_model, "request_json", unexpected_request)
    assert repair_segments(state, issues) == state.reviewed_blocks


@pytest.mark.parametrize(
    ("draft_text", "reason"),
    [
        pytest.param("可以继续。", "口播漏掉样本量限制", id="omission"),
        pytest.param("样本大小至少为十二才能继续。", "口播未使用术语表中的样本量", id="terminology"),
    ],
)
def test_audit_and_repair_only_change_the_flagged_segment(state, monkeypatch, draft_text, reason):
    state.reviewed_blocks[0] = make_draft("seg_0001", "blk_0001", draft_text)
    audited_ids = []

    def audit(**request):
        assert request["payload"]["terminology"] == {"sample size": "样本量"}
        (row,) = request["payload"]["segments"]
        audited_ids.append(row["segment_id"])
        if row["segment_id"] == "seg_0001":
            assert row["zh_subtitle"] == draft_text.rstrip("。")
            assert set(row) == {"segment_id", "text_en", "duration_ms", "zh_subtitle"}
            return {"issues": [{"segment_id": "seg_0001", "reason": reason, "target": "subtitle"}]}
        assert "样本量" in row["zh_subtitle"]
        return {"issues": []}

    monkeypatch.setattr(_text_model, "request_json", audit)
    issues = find_review_issues(state)
    assert audited_ids == ["seg_0001", "seg_0002"]
    assert [issue.model_dump() for issue in issues] == [
        {"segment_id": "seg_0001", "reason": reason, "target": "subtitle"}
    ]

    def rewrite(**request):
        assert request["payload"]["terminology"] == {"sample size": "样本量"}
        (row,) = request["payload"]["segments"]
        assert row["segment_id"] == "seg_0001"
        assert row["issues"][0]["reason"] == reason
        return {"items": [{
            "segment_id": "seg_0001",
            "zh_subtitle": "样本量至少为十二才能继续。",
        }]}

    monkeypatch.setattr(_text_model, "request_json", rewrite)
    repaired = repair_segments(state, issues)
    assert repaired[0].zh_subtitle == "样本量至少为十二才能继续"
    assert repaired[0].block_id == "blk_0001"
    assert repaired[1] is state.reviewed_blocks[1]
    assert state.reviewed_blocks[0].zh_subtitle == draft_text.rstrip("。")


def test_audit_rejects_an_id_outside_its_block(state, monkeypatch):
    monkeypatch.setattr(_text_model, "request_json", lambda **kwargs: {
        "issues": [{"segment_id": "seg_0002", "reason": "错段", "target": "subtitle"}]
    })
    with pytest.raises(ValueError, match="seg_0002"):
        find_review_issues(state)


def test_repair_rejects_an_unrequested_segment_in_model_output(state, monkeypatch):
    monkeypatch.setattr(_text_model, "request_json", lambda **kwargs: {
        "items": [{"segment_id": "seg_0002", "zh_subtitle": "不该更新"}]
    })
    with pytest.raises(ValueError, match="seg_0002"):
        repair_segments(state, [ReviewIssue(segment_id="seg_0001", reason="漏译", target="subtitle")])
