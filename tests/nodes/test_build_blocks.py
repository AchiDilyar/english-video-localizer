import pytest
from contracts import GraphState, Segment
from nodes.build_blocks import build_blocks
from nodes.translate_blocks._options import load_options
from pydantic import ValidationError
from utils import paths
from utils.io import read_artifact


@pytest.fixture(autouse=True)
def artifact_work_dir(tmp_path, monkeypatch):
    (tmp_path / "segments").mkdir()
    monkeypatch.setattr(paths, "_work_dir", None)
    paths.set_work_dir(str(tmp_path))


def segment(number: int, start_ms: int, end_ms: int) -> Segment:
    return Segment(
        segment_id=f"seg_{number:04d}",
        speaker_id="spk_1",
        start_ms=start_ms,
        end_ms=end_ms,
        text_en="The sample size matters.",
    )


def test_orders_segment_ids_without_changing_the_source_segments():
    segments = [segment(3, 8_000, 11_000), segment(1, 0, 3_000), segment(2, 4_000, 7_000)]
    original = [item.model_dump() for item in segments]

    result = build_blocks(GraphState(segments=segments))

    assert [block.model_dump() for block in result["blocks"]] == [
        {"block_id": "blk_0001", "segment_ids": ["seg_0001", "seg_0002", "seg_0003"]}
    ]
    assert [item.model_dump() for item in segments] == original
    assert result["terminology"] == {"sample size": "样本量"}
    assert read_artifact("blocks") == result["blocks"]


def test_breaks_at_segment_boundaries_and_keeps_the_final_block():
    segments = [
        segment(1, 0, 35_000),
        segment(2, 35_000, 90_000),
        segment(3, 90_000, 95_000),
    ]

    blocks = build_blocks(GraphState(segments=segments))["blocks"]

    assert [(block.block_id, block.segment_ids) for block in blocks] == [
        ("blk_0001", ["seg_0001", "seg_0002"]),
        ("blk_0002", ["seg_0003"]),
    ]


def test_keeps_an_oversized_segment_intact():
    segments = [segment(1, 0, 100_000), segment(2, 100_000, 104_000)]

    blocks = build_blocks(GraphState(segments=segments))["blocks"]

    assert [block.segment_ids for block in blocks] == [["seg_0001"], ["seg_0002"]]


def test_returns_the_supplied_glossary_for_the_current_task():
    glossary = {"sample size": "样本容量", "confidence interval": "置信区间"}

    result = build_blocks(GraphState(segments=[segment(1, 0, 1_000)], terminology=glossary))

    assert result["terminology"] == glossary


@pytest.mark.parametrize("enabled", [False, True])
def test_configured_terms_override_only_when_enabled(monkeypatch, enabled):
    glossary = {"sample size": "样本容量", "confidence interval": "置信区间"}
    monkeypatch.setattr("nodes.translate_blocks._options.load_config", lambda _: {
        "terminology": {
            "enabled": enabled, "entries": {"sample size": "样本量", "mix": "混音"},
        },
    })
    state = GraphState(segments=[segment(1, 0, 1_000)], terminology=glossary)
    result = build_blocks(state)
    expected = {**glossary, "sample size": "样本量", "mix": "混音"} if enabled else glossary
    assert result["terminology"] == expected
    assert state.terminology == glossary


@pytest.mark.parametrize(
    "content",
    ['style = "unknown"', '[terminology]\nenabled = "true"',
     '[terminology.entries]\n"mix" = "   "'],
)
def test_rejects_invalid_translation_toml(tmp_path, monkeypatch, content):
    monkeypatch.setattr("utils.config._CONFIG_DIR", tmp_path)
    (tmp_path / "translate_blocks.toml").write_text(content, encoding="utf-8")
    with pytest.raises(ValidationError):
        load_options()


@pytest.mark.parametrize("segments", [None, [], [segment(1, 0, 2_000), segment(1, 2_000, 4_000)]])
def test_rejects_invalid_segment_lists(segments):
    with pytest.raises(ValueError):
        build_blocks(GraphState(segments=segments))
