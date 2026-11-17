"""F main graph + real FFmpeg mix/compose; neural and paid inference replaced by fixtures."""

import importlib
import shutil
import subprocess
from pathlib import Path

import pytest
from contracts import GraphState, Segment
from graph import builder, registry
from graph.incremental import apply_incremental_proxy
from nodes.background_audio import digest
from nodes.probe_input.media import probe, tool_path
from nodes.tts_align import resolve_ffmpeg
from utils.paths import artifact_path, set_work_dir


@pytest.mark.parametrize("mode", ["success", "b_failure", "mix_failure", "absent"])
def test_main_graph_real_media_incremental_fallback(tmp_path, monkeypatch, mode):
    set_work_dir(str(tmp_path))
    for name in ("audio", "segments", "translated", "tts", "subtitles", "video", "logs"):
        (tmp_path / name).mkdir()
    ffmpeg = resolve_ffmpeg()
    source = tmp_path / "input.mp4"
    subprocess.run(
        [
            ffmpeg,
            "-v",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=s=320x180:r=10:d=2",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=300:duration=2",
            "-c:v",
            "libx264",
            "-c:a",
            "aac",
            str(source),
        ],
        check=True,
    )
    voice = tmp_path / "voice.wav"
    bed = tmp_path / "bed.wav"
    for path, hz in ((voice, 1000), (bed, 200)):
        subprocess.run(
            [
                ffmpeg,
                "-v",
                "error",
                "-y",
                "-f",
                "lavfi",
                "-i",
                f"sine=frequency={hz}:duration=2",
                "-ac",
                "2",
                "-ar",
                "48000",
                str(path),
            ],
            check=True,
        )
    # Disk leftovers must not be considered successful current publications.
    (tmp_path / "audio/mixed.wav").write_bytes(b"old-invalid-media")
    b = importlib.import_module("nodes.b_environment")
    mix = importlib.import_module("nodes.mix_background")
    monkeypatch.setattr(b, "load_config", lambda _: {"restore_nonverbal": False})

    def separate(source, folder, *args, **kwargs):
        if mode == "b_failure":
            raise RuntimeError("separator failure")
        shutil.copyfile(bed, folder / "background.wav")

    monkeypatch.setattr(b, "separate", separate)
    if mode == "mix_failure":

        def fail(*args, **kwargs):
            raise RuntimeError("mix failure")

        monkeypatch.setattr(mix, "render_mix", fail)
    monkeypatch.setattr(
        registry, "load_node_modes", lambda: {name: "real" for name in registry.NODE_NAMES}
    )
    nodes = registry.resolve_nodes()
    segment = Segment(
        segment_id="seg_0001", speaker_id="spk_001", start_ms=0, end_ms=1800, text_en="Hello."
    )
    nodes["asr_diarize"] = lambda _: {"segments": [segment]}
    for name in ("build_blocks", "translate_blocks", "review_blocks", "repair_blocks"):
        nodes[name] = lambda _: {}

    def tts(state):
        shutil.copyfile(voice, artifact_path("dub_audio"))
        return {}

    def subtitles(state):
        Path(artifact_path("burnin_subtitle")).write_text(
            "[Script Info]\nPlayResX: 320\nPlayResY: 180\n[V4+ Styles]\n"
            "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
            "Style: Default,Arial,18,&H00FFFFFF,&H00FFFFFF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,1,0,2,10,10,10,1\n"
            "[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
            "Dialogue: 0,0:00:00.00,0:00:01.80,Default,,0,0,0,,Hello\n",
            encoding="utf-8",
        )
        return {}

    nodes.update(tts_align=tts, subtitle_cover=subtitles)
    if mode == "absent":
        nodes["b_environment"] = lambda _: {}
    monkeypatch.setattr(builder, "resolve_nodes", lambda: apply_incremental_proxy(nodes))
    initial = GraphState(input_video="input.mp4")
    result = GraphState.model_validate(builder.build_graph().invoke(initial))
    assert initial.segments is None and initial.environment_audio is None
    assert (result.environment_audio is not None) == (mode in ("success", "mix_failure"))
    assert (result.mixed_audio is not None) == (mode == "success")
    final = Path(artifact_path("final_video"))
    assert final.stat().st_size > 1000
    data = probe(final, tool_path("ffprobe", None))
    assert {s["codec_type"] for s in data["streams"]} == {"audio", "video"}
    assert abs(float(data["format"]["duration"]) - 2) < 0.15
    assert digest(Path(artifact_path("dub_audio"))) == digest(voice)
