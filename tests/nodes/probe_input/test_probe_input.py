import json
from pathlib import Path

import pytest

from contracts import GraphState, MediaInfo
from nodes.probe_input import probe_input
from nodes.probe_input import integration, media

ROOT = Path(__file__).resolve().parents[3]


def test_probe_returns_typed_state_without_disk_output(shared_services, monkeypatch):
    work, calls, _ = shared_services
    (work / "input.mp4").write_bytes(b"probe is replaced by a fixed ffprobe response")
    raw = json.loads((ROOT / "tests/data/probe_input/ffprobe.json").read_text())
    monkeypatch.setattr(media, "probe", lambda *args: raw)
    monkeypatch.setattr(media, "tool_path", lambda *args: "test-ffprobe")
    state = GraphState(input_video="input.mp4")
    delta = probe_input(state)
    assert set(delta) == {"media_info"}
    assert isinstance(delta["media_info"], MediaInfo)
    assert delta["media_info"].duration_ms == 2000
    assert delta["media_info"].video_info.fps == 25
    assert delta["media_info"].audio_info.sample_rate == 16000
    assert state.media_info is None
    assert calls["paths"] == [("input_video", "input.mp4")]
    assert not calls["writes"]
    assert sorted(p.name for p in work.iterdir()) == ["audio", "input.mp4", "segments"]


@pytest.mark.parametrize("filename", [None, "../escape.mp4", "folder/input.mp4", "https://example.org/x.mp4"])
def test_invalid_input_is_rejected_before_probe(shared_services, filename):
    with pytest.raises(ValueError):
        probe_input(GraphState(input_video=filename))


def test_raw_dict_is_not_a_graph_state(shared_services):
    with pytest.raises(TypeError):
        probe_input({"input_video": "input.mp4"})


def test_missing_shared_utility_has_actionable_error(monkeypatch):
    def missing(name):
        raise ModuleNotFoundError("test dependency absent", name=name)

    monkeypatch.setattr(integration, "import_module", missing)
    with pytest.raises(RuntimeError, match="SHARED_UTILITIES_UNAVAILABLE"):
        integration.artifact_path("source_audio")
