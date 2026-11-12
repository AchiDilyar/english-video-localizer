"""Shared fixtures for smoke tests.

Smoke scope (per integration decision D2-A / D4-A):
- C sub-chain only: build_blocks -> translate_blocks -> review_blocks
- No build_graph(), no real B nodes, no FFmpeg / ASR / Community-1 / API key
- LLM boundary replaced via monkeypatch (D1-B)
"""

import shutil
from pathlib import Path

import pytest
from contracts import GraphState
from utils.io import read_artifact
from utils.paths import set_work_dir

REPO = Path(__file__).resolve().parents[2]

SEGMENTS_SRC = REPO / "tests" / "data" / "asr_diarize" / "real_dialogue" / "segments.json"


@pytest.fixture
def work_dir(tmp_path):
    """Isolated work_dir with the subdirectories the C nodes expect."""
    w = tmp_path / "work"
    w.mkdir()
    for d in ("audio", "segments", "translated", "tts", "subtitles",
              "cover", "video", "package", "logs"):
        (w / d).mkdir()
    set_work_dir(str(w))
    return w


@pytest.fixture
def seeded_state(work_dir):
    """Copy segments.json into work_dir and read it back as a GraphState."""
    dst = work_dir / "segments" / "segments.json"
    shutil.copy(SEGMENTS_SRC, dst)
    segments = read_artifact("segments")
    return GraphState(input_video="input.mp4", segments=segments)


@pytest.fixture
def llm_stub(monkeypatch):
    """Replace the C LLM boundary; return a controller for mode and call counts."""
    import nodes.translate_blocks._text_model as tm

    ctl = {"mode": "normal", "calls": {"translate": 0, "review": 0}}

    def fake_request_json(*, instruction: str, payload: dict, output_format: str = "") -> dict:
        segs = payload["segments"]
        is_review = bool(segs) and "zh_subtitle" in segs[0]
        ctl["calls"]["review" if is_review else "translate"] += 1
        items = [
            {
                "segment_id": s["segment_id"],
                "zh_subtitle": s.get("zh_subtitle") or f"字幕-{s['segment_id']}",
            }
            for s in segs
        ]
        if ctl["mode"] == "missing_id" and items:
            items.pop()
        return {"items": items}

    monkeypatch.setattr(tm, "request_json", fake_request_json)
    return ctl
