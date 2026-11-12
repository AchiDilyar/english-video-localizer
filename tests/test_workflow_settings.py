"""The workbench edits the same TOML shape and schema consumed by the CLI."""

import sys
import tomllib
from pathlib import Path

import pytest
from graph.builder import WORKFLOW_EDGES
from graph.registry import NODE_NAMES
from nodes.asr_diarize.node import ASROptions
from nodes.probe_input.node import ProbeOptions
from pydantic import ValidationError

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from workflow_settings import ConfigChanged, save_settings, settings_snapshot, workflow_schema  # noqa: E402


def test_canvas_topology_matches_main_graph():
    schema = workflow_schema()
    assert schema["nodes"] == NODE_NAMES
    assert set(map(tuple, schema["edges"])) == {
        (node, target)
        for sources, target in WORKFLOW_EDGES
        for node in (sources if isinstance(sources, tuple) else (sources,))
    }


def test_write_and_clear_asr_overrides(tmp_path):
    path = tmp_path / "asr_diarize.toml"
    path.write_text('# Local models\nmodel_dir = "models/local"\n')
    original = settings_snapshot("asr_diarize", path.read_bytes())
    assert {field["key"] for field in original["fields"]} == ASROptions.model_fields.keys()
    saved = save_settings(path, "asr_diarize", {
        "revision": original["revision"],
        "values": {"num_speakers": 2, "max_duration_sec": 600.5, "audio_recheck": False},
    })
    options = ASROptions.model_validate(tomllib.loads(path.read_text()))
    assert (options.num_speakers, options.max_duration_sec, options.audio_recheck) == (2, 600.5, False)
    assert options.model_dir == "models/local"
    assert path.read_text().startswith("# Local models\n")
    with pytest.raises(ConfigChanged):
        save_settings(path, "asr_diarize", {"revision": original["revision"], "values": {}})
    save_settings(path, "asr_diarize", {"revision": saved["revision"], "values": {"num_speakers": None}})
    assert "num_speakers" not in tomllib.loads(path.read_text())


@pytest.mark.parametrize("values, error", [
    ({"num_speakers": 33}, ValidationError),
    ({"num_speakers": "2"}, ValidationError),
    ({"audio_recheck": 1}, ValidationError),
    ({"community1_python": "other"}, ValueError),
    ({"vad": True}, ValueError),
])
def test_reject_unsupported_asr_settings(tmp_path, values, error):
    path = tmp_path / "asr_diarize.toml"
    original = b"audio_recheck = true\n"
    path.write_bytes(original)
    snapshot = settings_snapshot("asr_diarize", original)
    with pytest.raises(error):
        save_settings(path, "asr_diarize", {"revision": snapshot["revision"], "values": values})
    assert path.read_bytes() == original


def test_probe_round_trip(tmp_path):
    path = tmp_path / "probe_input.toml"
    path.touch()
    snapshot = settings_snapshot("probe_input", b"")
    updated = save_settings(path, "probe_input", {
        "revision": snapshot["revision"],
        "values": {"ffprobe": '/tmp/media "tools"/ffprobe', "audio_stream": 2},
    })
    options = ProbeOptions.model_validate(tomllib.loads(path.read_text()))
    assert options.ffprobe == '/tmp/media "tools"/ffprobe'
    assert options.audio_stream == 2
    assert updated == settings_snapshot("probe_input", path.read_bytes())
