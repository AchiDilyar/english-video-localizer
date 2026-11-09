"""B fixtures; shared-service doubles live only in tests, never in real nodes."""
import json
from pathlib import Path
import sys
import tomllib
from types import ModuleType

import pytest
from pydantic import TypeAdapter

from contracts import Segment

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def shared_services(tmp_path, monkeypatch):
    """A test-only implementation of F's documented path/config/io signatures."""
    for folder in ["audio", "segments"]:
        (tmp_path / folder).mkdir()
    calls = {"paths": [], "writes": []}
    overrides = {}

    def artifact_path(name, filename=None):
        calls["paths"].append((name, filename))
        if name == "input_video":
            return str(tmp_path / filename)
        return str(tmp_path / {"source_audio": "audio/source.wav", "segments": "segments/segments.json"}[name])

    def load_config(filename):
        return overrides.get(filename, tomllib.loads((ROOT / "config" / filename).read_text()))

    def write_artifact(name, obj, filename=None):
        assert name == "segments"
        validated = TypeAdapter(list[Segment]).validate_python(obj)
        calls["writes"].append(validated)
        (tmp_path / "segments/segments.json").write_bytes(TypeAdapter(list[Segment]).dump_json(validated))

    for module, functions in {
        "paths": {"artifact_path": artifact_path},
        "config": {"load_config": load_config},
        "io": {"write_artifact": write_artifact},
    }.items():
        imported = ModuleType(f"utils.{module}")
        imported.__dict__.update(functions)
        monkeypatch.setitem(sys.modules, f"utils.{module}", imported)
    return tmp_path, calls, overrides


@pytest.fixture
def sentence_table():
    return json.loads((ROOT / "tests/data/asr_diarize/node-sentences.json").read_text())
