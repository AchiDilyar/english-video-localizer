"""URL HTTP submission -> CLI -> F graph -> actual captioned/audio MP4 download.

Acquisition and model nodes use deterministic fixtures; no external network/paid inference.
"""

import contextlib
import importlib
import io
import json
import shutil
import subprocess
from pathlib import Path
from time import monotonic, sleep
from urllib.request import urlopen

import cli
import pytest
from contracts import Segment
from graph import builder, registry
from graph.incremental import apply_incremental_proxy
from mocks.subtitle_cover import _ASS_CONTENT
from nodes.probe_input.media import probe, tool_path
from nodes.tts_align import resolve_ffmpeg
from utils.io import write_artifact
from utils.paths import artifact_path

from tests.test_webui_youtube import request, server  # noqa: F401


@pytest.mark.parametrize("download_fails", [False, True])
def test_web_url_to_captioned_video(server, tmp_path, monkeypatch, download_fails):  # noqa: F811
    import serve_workflow_ui as ui

    ffmpeg = resolve_ffmpeg()
    source = tmp_path / "source.mp4"
    original_run = subprocess.run
    original_run(
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
    dub = tmp_path / "dub.wav"
    original_run(
        [
            ffmpeg,
            "-v",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=1000:duration=2",
            str(dub),
        ],
        check=True,
    )
    seen = []

    def acquire(url, work):
        seen.append(url)
        if download_fails:
            raise ValueError("test download unavailable")
        shutil.copyfile(source, work / "input.mp4")
        return "input.mp4"

    monkeypatch.setattr("nodes.probe_input.youtube.prepare_youtube_input", acquire)
    nodes = {name: (lambda state: {}) for name in registry.NODE_NAMES}
    nodes["probe_input"] = importlib.import_module("nodes.probe_input").probe_input
    segment = Segment(
        segment_id="seg_0001", speaker_id="spk_1", start_ms=0, end_ms=1900, text_en="Hello."
    )

    def asr(state):
        write_artifact("segments", [segment])
        return {"segments": [segment]}

    def tts(state):
        shutil.copyfile(dub, artifact_path("dub_audio"))
        return {}

    def subtitle(state):
        Path(artifact_path("burnin_subtitle")).write_text(
            _ASS_CONTENT.replace("占位字幕", "你好\\NHello."), encoding="utf-8"
        )
        return {}

    nodes.update(
        asr_diarize=asr,
        tts_align=tts,
        subtitle_cover=subtitle,
        compose_video=importlib.import_module("nodes.compose_video").compose_video,
    )
    monkeypatch.setattr(builder, "resolve_nodes", lambda: apply_incremental_proxy(nodes))

    def child(command, **kwargs):
        if command[1:4] != ["-u", "-m", "cli"]:
            return original_run(command, **kwargs)
        buffer = io.StringIO()
        code = 0
        with contextlib.redirect_stdout(buffer), contextlib.redirect_stderr(buffer):
            try:
                cli.main(command[4:])
            except Exception:
                code = 1
        kwargs["stdout"].write(buffer.getvalue().encode("utf-8"))
        return subprocess.CompletedProcess(command, code)

    monkeypatch.setattr(ui.subprocess, "run", child)
    with urlopen(request(server, {"url": "https://youtu.be/jNQXAC9IVRw"})) as response:
        job_id = json.load(response)["job_id"]
    job = server.jobs / job_id
    deadline = monotonic() + 30
    while server.worker_lock.locked() and monotonic() < deadline:
        sleep(0.03)
    assert not server.worker_lock.locked()
    status = server.read_run_status(job)
    assert seen == ["https://www.youtube.com/watch?v=jNQXAC9IVRw"]
    if download_fails:
        assert status["state"] == "failed" and not status["final_video_ready"]
        assert "test download unavailable" in status["message"]
        return
    assert status["state"] == "complete" and status["input_ready"] and status["final_video_ready"]
    assert set(status["node_states"]) == set(registry.NODE_NAMES)
    assert status["node_states"]["mix_background"] == "no_output"
    video = job / "video/final.mp4"
    metadata = probe(video, tool_path("ffprobe", None))
    assert {stream["codec_type"] for stream in metadata["streams"]} == {"audio", "video"}
    assert abs(float(metadata["format"]["duration"]) - 2) < 0.15
    with urlopen(
        f"http://127.0.0.1:{server.server_port}/api/workflow-runs/{job_id}/final-video"
    ) as response:
        assert response.status == 200 and response.headers["Content-Type"] == "video/mp4"
        assert response.read() == video.read_bytes()
