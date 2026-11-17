"""Explicit, local-only model smoke tests; never run during ordinary regression."""
import os
from pathlib import Path

import pytest

from nodes.asr_diarize import node

ROOT = Path(__file__).resolve().parents[3]
pytestmark = pytest.mark.skipif(
    os.environ.get("B_RUN_REAL_MODELS") != "1", reason="Set B_RUN_REAL_MODELS=1 for local inference"
)


def audio_fixture() -> Path:
    audio = ROOT / "tests/data/_large/asr_diarize/speech-16s.wav"
    if not audio.is_file():
        pytest.skip("Provide the documented, authorized 16-second local speech fixture")
    return audio


def test_real_asr_uses_relocated_implementation():
    table = node.recognize(audio_fixture(), 16000, node.ASROptions(audio_recheck=False))
    assert table["sentences"]
    assert table["execution"]["transcribe_calls"] == 1
    assert not table["execution"]["raw_asr_timestamps_persisted"]
    assert "words" not in table and "segments" not in table


def test_real_community1_returns_json_without_result_file():
    options = node.ASROptions(
        community1_device=os.environ.get("B_COMMUNITY1_DEVICE", "cpu"),
    )
    data = node.run_diarization(audio_fixture(), 16000, options)
    assert data["turns"]
    assert data["metadata"]["audio_uploaded"] is False
    assert data["metadata"]["speaker_embeddings_persisted"] is False
