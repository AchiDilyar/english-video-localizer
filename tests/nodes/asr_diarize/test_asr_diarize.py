import pytest
pytest.importorskip("numpy", reason="Install B test dependencies with uv sync --extra b-asr")
pytest.importorskip("spacy", reason="Install B test dependencies with uv sync --extra b-asr")
pytest.importorskip("en_core_web_sm", reason="Install B test dependencies with uv sync --extra b-asr")
pytest.importorskip("faster_whisper", reason="Install B test dependencies with uv sync --extra b-asr")

import copy
import json
from pathlib import Path
from types import SimpleNamespace
import wave

from langgraph.graph import END, START, StateGraph

from contracts import GraphState, Segment
from nodes.asr_diarize import asr_diarize
from nodes.asr_diarize import node
from nodes.probe_input import probe_input, media
from nodes.probe_input import integration


def turns():
    # The first sentence has a small boundary intrusion; its main speaker still wins.
    return {"speaker_ids": ["voice-A", "voice-B"], "metadata": {}, "turns": [
        {"start_ms": 0, "end_ms": 650, "speaker_id": "voice-A"},
        {"start_ms": 650, "end_ms": 1300, "speaker_id": "voice-B"},
        {"start_ms": 1400, "end_ms": 1900, "speaker_id": "voice-A"},
    ]}


def test_final_ids_and_speakers_preserve_text_and_timing(sentence_table):
    from nodes.asr_diarize.pipeline.diarization import assign_speakers

    original = copy.deepcopy(sentence_table)
    segments = node.to_segments(assign_speakers(sentence_table, turns()))
    assert [s.segment_id for s in segments] == ["seg_0001", "seg_0002", "seg_0003"]
    assert [s.speaker_id for s in segments] == ["spk_1", "spk_2", "spk_1"]
    assert [(s.start_ms, s.end_ms, s.text_en) for s in segments] == [
        (r["start_ms"], r["end_ms"], r["en"]) for r in original["sentences"]
    ]
    assert sentence_table == original
    assert set(segments[0].model_dump()) == {"segment_id", "speaker_id", "start_ms", "end_ms", "text_en"}


@pytest.mark.parametrize("kind", ["unknown", "untimed", "overlap", "empty"])
def test_unusable_handoff_is_rejected(sentence_table, kind):
    for row in sentence_table["sentences"]:
        row["speaker_id"] = "voice-A"
    if kind == "unknown":
        sentence_table["sentences"][0]["speaker_id"] = None
    elif kind == "untimed":
        sentence_table["review"]["untimed_utterances"] = [{"en": "Unaligned phrase."}]
    elif kind == "overlap":
        sentence_table["sentences"][1]["start_ms"] = 500
    else:
        sentence_table["sentences"] = []
    with pytest.raises(ValueError):
        node.to_segments(sentence_table)


def make_test_video(work):
    try:
        ffmpeg = media.tool_path("ffmpeg")
        media.tool_path("ffprobe")
    except media.MediaError as exc:
        pytest.skip(str(exc))
    media.run([ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin", "-n",
               "-f", "lavfi", "-i", "color=c=black:s=160x120:r=25:d=2",
               "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=16000:duration=2",
               "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(work / "input.mp4")])
    return work


@pytest.fixture
def real_video(shared_services):
    work, _, _ = shared_services
    return make_test_video(work)


def test_nodes_use_real_F_utils_for_config_paths_and_json(tmp_path, monkeypatch, sentence_table):
    from utils import paths
    from utils.io import read_artifact, write_artifact
    from utils.config import load_config

    # Model outputs alone are fixed; these are F's real config/path/io implementations.
    monkeypatch.setattr(paths, "_work_dir", None)
    paths.set_work_dir(str(tmp_path))
    for folder in ["audio", "segments"]:
        (tmp_path / folder).mkdir()
    make_test_video(tmp_path)
    assert integration.shared("io", "write_artifact") is write_artifact
    assert integration.shared("config", "load_config") is load_config
    monkeypatch.setattr(node, "recognize", lambda *args: copy.deepcopy(sentence_table))
    monkeypatch.setattr(node, "run_diarization", lambda *args: turns())
    initial = GraphState(input_video="input.mp4")
    media_delta = probe_input(initial)
    state = GraphState.model_validate({**initial.model_dump(), **media_delta})
    delta = asr_diarize(state)
    saved = read_artifact("segments")
    assert saved == delta["segments"]
    assert all(isinstance(segment, Segment) for segment in saved)
    assert [segment.speaker_id for segment in saved] == ["spk_1", "spk_2", "spk_1"]
    assert state.segments is None
    assert Path(paths.artifact_path("source_audio")).is_file()


def test_real_media_two_node_langgraph_uses_shared_contract(
    shared_services, real_video, sentence_table, monkeypatch
):
    work, calls, _ = shared_services
    monkeypatch.setattr(node, "recognize", lambda *args: copy.deepcopy(sentence_table))
    monkeypatch.setattr(node, "run_diarization", lambda *args: turns())
    graph = StateGraph(GraphState)
    graph.add_node("probe_input", probe_input)
    graph.add_node("asr_diarize", asr_diarize)
    graph.add_edge(START, "probe_input")
    graph.add_edge("probe_input", "asr_diarize")
    graph.add_edge("asr_diarize", END)
    result = GraphState.model_validate(graph.compile().invoke(GraphState(input_video="input.mp4")))
    assert result.media_info.duration_ms == 2000
    assert all(isinstance(s, Segment) for s in result.segments)
    assert len(calls["writes"]) == 1
    saved = json.loads((work / "segments/segments.json").read_text())
    assert saved == [s.model_dump() for s in result.segments]
    fixed = Path(__file__).resolve().parents[2] / "data/asr_diarize/segments.json"
    assert saved == json.loads(fixed.read_text())
    with wave.open(str(work / "audio/source.wav")) as audio:
        assert (audio.getframerate(), audio.getnchannels(), audio.getnframes()) == (16000, 1, 32000)
    assert {p.relative_to(work).as_posix() for p in work.rglob("*") if p.is_file()} == {
        "input.mp4", "audio/source.wav", "segments/segments.json"
    }


def test_write_failure_is_propagated_without_success_delta(
    real_video, sentence_table, monkeypatch
):
    monkeypatch.setattr(node, "recognize", lambda *args: copy.deepcopy(sentence_table))
    monkeypatch.setattr(node, "run_diarization", lambda *args: turns())

    def fail(*args):
        raise OSError("test disk failure")

    monkeypatch.setattr(integration, "write_artifact", fail)
    state = GraphState(input_video="input.mp4")
    with pytest.raises(OSError, match="test disk failure"):
        asr_diarize(state)
    assert state.segments is None
    assert not (real_video / "segments/segments.json").exists()


def test_unknown_speaker_stops_before_writing(real_video, sentence_table, monkeypatch):
    monkeypatch.setattr(node, "recognize", lambda *args: copy.deepcopy(sentence_table))
    monkeypatch.setattr(node, "run_diarization", lambda *args: {**turns(), "turns": []})
    with pytest.raises(ValueError, match="UNRESOLVED_SPEAKER"):
        asr_diarize(GraphState(input_video="input.mp4"))
    assert not (real_video / "segments/segments.json").exists()


def test_worker_failure_has_no_silent_fallback(monkeypatch, tmp_path):
    import subprocess

    monkeypatch.setattr(subprocess, "run", lambda *a, **k: SimpleNamespace(returncode=1, stderr="test worker failure"))
    with pytest.raises(RuntimeError, match="test worker failure"):
        node.run_diarization(tmp_path / "source.wav", 1000, node.ASROptions())


def test_worker_rejects_a_separate_non_uv_python(tmp_path):
    with pytest.raises(ValueError, match="current uv environment"):
        node.run_diarization(tmp_path / "source.wav", 1000,
                             node.ASROptions(community1_python=str(tmp_path / "other-python.exe")))


def test_recognition_consumes_resolved_path_without_artifact_reconstruction(monkeypatch, tmp_path):
    from unittest.mock import MagicMock
    import faster_whisper
    from nodes.asr_diarize.pipeline import common

    audio = tmp_path / "resolved audio.wav"
    audio.write_bytes(b"not decoded: model is a fixed test double")
    words = [SimpleNamespace(word=w, start=i * .4, end=i * .4 + .3)
             for i, w in enumerate("Python is useful.".split())]
    model = MagicMock()
    model.transcribe.return_value = (iter([SimpleNamespace(words=words, text="Python is useful.")]), None)
    monkeypatch.setattr(faster_whisper, "WhisperModel", lambda *a, **k: model)

    def forbidden(*args):
        raise AssertionError("Shared recognition must not reconstruct a job artifact path")

    monkeypatch.setattr(common, "artifact", forbidden)
    table = node.recognize(audio, 2000, node.ASROptions(audio_recheck=False))
    assert model.transcribe.call_args.args == (str(audio),)
    assert table["sentences"][0]["en"] == "Python is useful."
    assert list(tmp_path.iterdir()) == [audio]


def test_worker_diagnostics_use_parent_module_logger(monkeypatch, tmp_path, caplog):
    import logging
    import subprocess
    from nodes.asr_diarize.pipeline.common import digest

    audio = tmp_path / "source.wav"
    audio.write_bytes(b"fixed audio fingerprint, no inference")
    result = {"metadata": {"audio_sha256": digest(audio), "duration_ms": 1000},
              "speaker_ids": ["speaker_001"],
              "turns": [{"start_ms": 0, "end_ms": 1000, "speaker_id": "speaker_001"}]}
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: SimpleNamespace(
        returncode=0, stdout=json.dumps(result), stderr="test local worker diagnostic"
    ))
    with caplog.at_level(logging.INFO, logger=node.__name__):
        node.run_diarization(audio, 1000, node.ASROptions())
    assert any(r.name == node.__name__ and "test local worker diagnostic" in r.getMessage()
               for r in caplog.records)
