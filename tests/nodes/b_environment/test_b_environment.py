"""B node integration boundaries, not a claim of neural separator quality."""

import importlib

import pytest
from contracts import GraphState, MediaInfo, Segment
from utils.io import read_artifact
from utils.paths import set_work_dir

b = importlib.import_module("nodes.b_environment")


def source_state():
    return GraphState(
        input_video="input.mp4",
        media_info=MediaInfo(
            duration_ms=8000,
            video_info={"codec": "h264", "width": 320, "height": 180},
            audio_info={"codec": "aac", "sample_rate": 24000, "channels": 1},
            ffprobe_raw={},
        ),
        segments=[
            Segment(
                segment_id="seg_0001",
                speaker_id="spk_001",
                start_ms=1000,
                end_ms=4000,
                text_en="Hello.",
            )
        ],
    )


def test_event_windows_never_cross_speech_and_keep_seconds():
    state = source_state()
    gaps = b._event_gaps(state.segments, 8, 0.08)
    assert gaps == [(0, 0.92), (4.08, 7.08), (7.08, 8)]
    assert all(0 <= a < c <= 8 and c - a <= 3 for a, c in gaps)


def test_receipt_rejects_out_of_video_event_timestamps():
    from contracts import EnvironmentAudio
    from pydantic import ValidationError

    fields = dict(
        source_sha256="a" * 64,
        segments_sha256="b" * 64,
        environment_sha256="c" * 64,
        duration_sec=8,
    )
    with pytest.raises(ValidationError, match="millisecond"):
        EnvironmentAudio(**fields, restored_intervals_ms=[(7900, 8100)])
    assert EnvironmentAudio(**fields, restored_intervals_ms=[(100, 900)]).restored_intervals_ms == [
        (100, 900)
    ]


def test_b_publishes_only_after_all_work_and_keeps_state(tmp_path, monkeypatch):
    set_work_dir(str(tmp_path))
    (tmp_path / "audio").mkdir()
    (tmp_path / "input.mp4").write_bytes(b"source")

    def separate(source, folder, *args, **kwargs):
        assert kwargs["allow_download"] is False
        (folder / "background.wav").write_bytes(b"bed")
        (folder / "vocals.wav").write_bytes(b"vocals")

    monkeypatch.setattr(b, "separate", separate)
    monkeypatch.setattr(b, "resolve_ffmpeg", lambda: "ffmpeg")
    monkeypatch.setattr(b, "load_config", lambda name: {"restore_nonverbal": False})
    state = source_state()
    before = state.model_dump()
    delta = b.b_environment(state)
    assert set(delta) == {"environment_audio"}
    assert delta["environment_audio"] == read_artifact("environment_audio")
    assert state.model_dump() == before
    assert (tmp_path / "audio/environment.wav").read_bytes() == b"bed"
    assert not list((tmp_path / "audio").glob(".b-environment-*"))


def test_failed_b_does_not_publish_or_overwrite_base_audio(tmp_path, monkeypatch):
    set_work_dir(str(tmp_path))
    audio = tmp_path / "audio"
    audio.mkdir()
    (tmp_path / "input.mp4").write_bytes(b"source")
    (audio / "source.wav").write_bytes(b"base-original")
    monkeypatch.setattr(b, "resolve_ffmpeg", lambda: "ffmpeg")

    def fail(*args, **kwargs):
        raise RuntimeError("separator unavailable")

    monkeypatch.setattr(b, "separate", fail)
    from graph.incremental import wrap_incremental

    assert wrap_incremental("b_environment", b.b_environment)(source_state()) == {}
    assert (audio / "source.wav").read_bytes() == b"base-original"
    assert not (audio / "environment.wav").exists()
    assert not list(audio.glob(".b-environment-*"))
