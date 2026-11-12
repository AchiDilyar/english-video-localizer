"""Real B/C nodes and F graph/utils; cached B predictions and fixed text responses."""
import pytest

pytest.importorskip("numpy", reason="Use uv run --extra b-asr pytest tests/graph")

import copy
import json
import os
import shutil
from pathlib import Path

from contracts import GraphState, Segment
from graph import build_graph, registry
from nodes.asr_diarize import node as asr_node
from nodes.probe_input import media
from nodes.translate_blocks import _text_model
from pydantic import TypeAdapter
from utils import paths
from utils.io import read_artifact

ROOT = Path(__file__).resolve().parents[2]
SAMPLE = ROOT / "tests/data/asr_diarize/real_dialogue"


def test_real_dialogue_B_C_through_F_graph(tmp_path, monkeypatch):
    try:
        media.tool_path("ffmpeg")
        media.tool_path("ffprobe")
    except media.MediaError as exc:
        pytest.skip(str(exc))
    work = tmp_path
    if os.environ.get("B_C_F_OUTPUT_DIR"):
        work = Path(os.environ["B_C_F_OUTPUT_DIR"]).resolve()
        if not work.is_relative_to((ROOT / "tests/tmp").resolve()):
            raise ValueError("Integration output must stay under tests/tmp")
        work.mkdir(parents=True, exist_ok=False)
    for folder in ["audio", "segments", "translated"]:
        (work / folder).mkdir()
    shutil.copy2(SAMPLE / "input.mp4", work / "input.mp4")
    provenance = json.loads((SAMPLE / "provenance.json").read_text(encoding="utf-8"))
    assert media.sha256(work / "input.mp4") == provenance["video_sha256"]
    expected = TypeAdapter(list[Segment]).validate_json((SAMPLE / "segments.json").read_bytes())
    assert len({s.speaker_id for s in expected}) == 2
    table = {"schema_version": "b-sentences-2", "duration_ms": 14000,
             "review": {"untimed_utterances": []}, "verification": {}, "execution": {},
             "sentences": [{"sentence_id": f"sentence_{i:06d}", "speaker_id": s.speaker_id,
                            "start_ms": s.start_ms, "end_ms": s.end_ms, "en": s.text_en,
                            "review_status": "needs_human_review", "review_issues": []}
                           for i, s in enumerate(expected, 1)]}
    cached_turns = {"speaker_ids": ["spk_1", "spk_2"], "metadata": {}, "turns": [
        {"start_ms": s.start_ms, "end_ms": s.end_ms, "speaker_id": s.speaker_id} for s in expected
    ]}
    monkeypatch.setattr(asr_node, "recognize", lambda *args: copy.deepcopy(table))
    monkeypatch.setattr(asr_node, "run_diarization", lambda *args: cached_turns)
    fixed = json.loads((ROOT / "tests/data/graph/b_c_dialogue/responses.json").read_text(encoding="utf-8"))
    texts = {item["segment_id"]: item["zh_subtitle"] for item in fixed["items"]}
    model_calls = []

    def response(**request):
        ids = [s["segment_id"] for s in request["payload"]["segments"]]
        model_calls.append(ids)
        return {"items": [{"segment_id": key, "zh_subtitle": texts[key]} for key in ids]}

    monkeypatch.setattr(_text_model, "request_json", response)
    flags = {name: name not in registry.NODE_NAMES[:5] for name in registry.NODE_NAMES}
    monkeypatch.setattr(registry, "load_config", lambda filename: flags)
    monkeypatch.setattr(paths, "_work_dir", None)
    paths.set_work_dir(str(work))
    graph = build_graph()
    events = list(graph.stream(GraphState(input_video="input.mp4"), stream_mode="updates"))
    called = [name for event in events for name in event if not name.startswith("__")]
    assert called[:5] == list(registry.NODE_NAMES[:5])
    assert set(called[5:]) == set(registry.NODE_NAMES[5:])
    source = read_artifact("segments")
    reviewed = read_artifact("reviewed_blocks")
    assert source == expected
    assert len(read_artifact("blocks")) == 1
    assert len(read_artifact("translated_blocks")) == len(reviewed) == 11
    assert [r.segment_id for r in reviewed] == [s.segment_id for s in source]
    assert all(r.zh_subtitle for r in reviewed)
    assert len(model_calls) == 2
    assert not (work / "package/final.zip").exists()
    if os.environ.get("B_C_F_OUTPUT_DIR"):
        (work / "integration-verification.json").write_text(json.dumps({
            "nodes": called, "segment_count": len(source), "speaker_count": 2,
            "duration_ms": 14000, "B_model_mode": "cached real predictions; no fresh ASR/diarization",
            "C_model_mode": "handwritten fixed responses; not live DeepSeek",
            "paid_api_calls": 0, "human_confirmed": False, "final_video_verified": False,
        }, indent=2), encoding="utf-8")
