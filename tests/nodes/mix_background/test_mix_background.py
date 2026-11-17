import importlib

from contracts import EnvironmentAudio, GraphState
from nodes.b_environment import segments_digest
from nodes.background_audio import digest
from utils.io import read_artifact, write_artifact
from utils.paths import set_work_dir

m = importlib.import_module("nodes.mix_background")


def test_absent_incremental_ignores_stale_files(tmp_path):
    set_work_dir(str(tmp_path))
    (tmp_path / "audio").mkdir()
    (tmp_path / "audio/mixed.wav").write_bytes(b"stale")
    state = GraphState()
    dub = tmp_path / "audio/dub.wav"
    assert m.mix_background(state) == {}
    assert m.select_mix_or_dub(state, dub, tmp_path / "input.mp4") == dub


def test_published_mix_and_stale_rejection(tmp_path, monkeypatch):
    from tests.nodes.b_environment.test_b_environment import source_state

    set_work_dir(str(tmp_path))
    (tmp_path / "audio").mkdir()
    source = tmp_path / "input.mp4"
    source.write_bytes(b"source")
    bed = tmp_path / "audio/environment.wav"
    bed.write_bytes(b"bed")
    dub = tmp_path / "audio/dub.wav"
    dub.write_bytes(b"voice")
    state = source_state()
    state.environment_audio = EnvironmentAudio(
        source_sha256=digest(source),
        environment_sha256=digest(bed),
        segments_sha256=segments_digest(state.segments),
        duration_sec=8,
    )
    write_artifact("environment_audio", state.environment_audio)

    def render(bed, dub, output, **kwargs):
        output.write_bytes(b"mixed")

    monkeypatch.setattr(m, "render_mix", render)
    monkeypatch.setattr(m, "resolve_ffmpeg", lambda: "ffmpeg")
    before = state.model_dump()
    delta = m.mix_background(state)
    assert state.model_dump() == before
    assert delta["mixed_audio"] == read_artifact("mixed_audio")
    state = state.model_copy(update=delta)
    assert m.select_mix_or_dub(state, dub, source) == tmp_path / "audio/mixed.wav"
    dub.write_bytes(b"new voice")
    assert m.select_mix_or_dub(state, dub, source) == dub
    (tmp_path / "audio/mixed.wav").unlink()
    assert m.select_mix_or_dub(state, dub, source) == dub
