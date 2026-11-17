import json
import math
import wave
from array import array
from types import SimpleNamespace

import pytest
from contracts import Segment
from nodes.auto_voice_profiles import ensure_profiles, reference_intervals


def segment(number, speaker, start, end):
    return Segment(
        segment_id=f"seg_{number:04d}",
        speaker_id=speaker,
        start_ms=start,
        end_ms=end,
        text_en="Test speech.",
    )


def source_audio(path, seconds=32):
    samples = array(
        "h", (round(4000 * math.sin(2 * math.pi * 180 * i / 16000)) for i in range(seconds * 16000))
    )
    with wave.open(str(path), "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(16000)
        audio.writeframes(samples.tobytes())


def test_reference_selection_never_includes_other_speaker():
    segments = [
        segment(1, "spk_1", 0, 6000),
        segment(2, "spk_2", 6000, 17000),
        segment(3, "spk_1", 17000, 23000),
    ]
    assert reference_intervals(segments, ["spk_1", "spk_2"]) == {
        "spk_1": [(0, 6000), (17000, 23000)],
        "spk_2": [(6000, 17000)],
    }
    with pytest.raises(ValueError, match="TOO_SHORT"):
        reference_intervals(
            [segment(1, "spk_1", 0, 15000), segment(2, "spk_2", 5000, 16000)], ["spk_1"]
        )


def test_auto_enrollment_requires_permission_and_reuses_matching_profiles(tmp_path, monkeypatch):
    source = tmp_path / "source.wav"
    source_audio(source)
    profile = tmp_path / "voice_profiles.json"
    segments = [segment(1, "spk_1", 0, 15000), segment(2, "spk_2", 16000, 31000)]
    calls = []

    class Client:
        def __init__(self, **kwargs):
            assert kwargs["region"] == "ap-southeast-1" and kwargs["max_retries"] == 0
            self.audio = SimpleNamespace(voices=SimpleNamespace(create=self.create))

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def create(self, **kwargs):
            calls.append(kwargs)
            return SimpleNamespace(voice_id=f"test-voice-{len(calls)}")

    options = dict(model="cosyvoice-v3-flash", region="ap-southeast-1", client_factory=Client)
    with pytest.raises(PermissionError, match="AUTHORIZATION_REQUIRED"):
        ensure_profiles(profile, source, segments, ["spk_1", "spk_2"], **options)
    assert not calls and not profile.exists()
    monkeypatch.setenv("DASHSCOPE_API_KEY", "test-only-key")
    voices = ensure_profiles(
        profile, source, segments, ["spk_1", "spk_2"], authorized=True, **options
    )
    assert len(calls) == 2 and set(voices) == {"spk_1", "spk_2"}
    assert ensure_profiles(profile, source, segments, ["spk_1", "spk_2"], **options) == voices
    assert len(calls) == 2 and not list(tmp_path.glob(".voice-reference-*"))
    assert "test-only-key" not in profile.read_text()
    with pytest.raises(ValueError, match="不匹配"):
        ensure_profiles(
            profile,
            source,
            segments,
            ["spk_1"],
            authorized=True,
            **{**options, "region": "cn-beijing"},
        )
    assert len(calls) == 2


def test_all_references_checked_before_any_network(tmp_path, monkeypatch):
    source = tmp_path / "source.wav"
    source_audio(source)
    segments = [segment(1, "spk_1", 0, 15000), segment(2, "spk_2", 16000, 18000)]

    def forbidden(**kwargs):
        pytest.fail("No client may open with an insufficient second speaker")

    with pytest.raises(ValueError, match="TOO_SHORT"):
        ensure_profiles(
            tmp_path / "voice_profiles.json",
            source,
            segments,
            ["spk_1", "spk_2"],
            model="cosyvoice-v3-flash",
            region="ap-southeast-1",
            authorized=True,
            client_factory=forbidden,
        )


def test_partial_profile_only_enrolls_missing_speaker(tmp_path, monkeypatch):
    from nodes.voice_profiles import digest

    source = tmp_path / "source.wav"
    source_audio(source)
    profile = tmp_path / "voice_profiles.json"
    profile.write_text(
        json.dumps(
            {
                "source_sha256": digest(source),
                "model": "model",
                "region": "ap-southeast-1",
                "voices": {
                    "spk_1": {
                        "voice_id": "existing-voice",
                        "sample_sha256": "previous-manual-sample",
                    }
                },
            }
        )
    )
    monkeypatch.setenv("DASHSCOPE_API_KEY", "test-only-key")
    calls = []

    class Client:
        def __init__(self, **kwargs):
            self.audio = SimpleNamespace(voices=SimpleNamespace(create=self.create))

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def create(self, **kwargs):
            calls.append(kwargs)
            return SimpleNamespace(voice_id="new-voice")

    voices = ensure_profiles(
        profile,
        source,
        [segment(1, "spk_1", 0, 15000), segment(2, "spk_2", 16000, 31000)],
        ["spk_1", "spk_2"],
        model="model",
        region="ap-southeast-1",
        authorized=True,
        client_factory=Client,
    )
    assert voices == {"spk_1": "existing-voice", "spk_2": "new-voice"} and len(calls) == 1


def test_next_job_reuses_only_identical_audio_account_model_region_and_timeline(
    tmp_path, monkeypatch
):
    import hashlib

    from nodes.auto_voice_profiles import _timeline_digest
    from nodes.voice_profiles import digest

    monkeypatch.setenv("DASHSCOPE_API_KEY", "test-key")
    segments = [segment(1, "spk_1", 0, 15000)]
    first = tmp_path / "jobs/first/audio"
    first.mkdir(parents=True)
    source = first / "source.wav"
    source_audio(source)
    data = {
        "source_sha256": digest(source),
        "model": "model",
        "region": "ap-southeast-1",
        "account_fingerprint": hashlib.sha256(b"test-key").hexdigest(),
        "speaker_timeline_sha256": _timeline_digest(segments),
        "voices": {"spk_1": {"voice_id": "existing-voice", "sample_sha256": "existing-sample"}},
    }
    (first / "voice_profiles.json").write_text(json.dumps(data))
    second = tmp_path / "jobs/second/audio"
    second.mkdir(parents=True)

    def forbidden(**kwargs):
        pytest.fail("A matching local record must not trigger enrollment")

    result = ensure_profiles(
        second / "voice_profiles.json",
        source,
        segments,
        ["spk_1"],
        model="model",
        region="ap-southeast-1",
        authorized=True,
        client_factory=forbidden,
    )
    assert result == {"spk_1": "existing-voice"}
    with pytest.raises(ValueError, match="时间轴"):
        ensure_profiles(
            second / "voice_profiles.json",
            source,
            [segment(1, "spk_1", 100, 15000)],
            ["spk_1"],
            model="model",
            region="ap-southeast-1",
            authorized=True,
            client_factory=forbidden,
        )
