"""Check artifact-based workflow status for the SRT preparation stage."""

import sys
import json
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

from utils.artifacts import ARTIFACT_SPECS

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from serve_workflow_ui import WorkflowServer, save_job_input, write_status  # noqa: E402


def test_status_tracks_parallel_nodes_and_empty_increments(tmp_path):
    server = SimpleNamespace(active_job=tmp_path.name)
    (tmp_path / 'logs').mkdir()
    write_status(tmp_path, state='running', phase='workflow')
    events = [
        {'node':'b_environment','event':'started'},
        {'node':'build_blocks','event':'started'},
    ]
    path=tmp_path/'logs/node-progress.jsonl'
    path.write_text(''.join(json.dumps(event)+'\n' for event in events))
    status=WorkflowServer.read_run_status(server,tmp_path)
    assert set(status['active_nodes'])=={'b_environment','build_blocks'}
    # A left-over receipt does not prove the incremental completed in this run.
    (tmp_path/'audio').mkdir()
    (tmp_path/'audio/environment.source.json').write_text('{}')
    events.append({'node':'b_environment','event':'finished','has_output':False})
    path.write_text(''.join(json.dumps(event)+'\n' for event in events)+'{"partial":')
    status=WorkflowServer.read_run_status(server,tmp_path)
    assert status['node_states']['b_environment']=='no_output'
    assert 'b_environment' not in status['completed_nodes']
    assert status['active_nodes']==['build_blocks']


def test_duplicate_uploads_share_one_video(tmp_path):
    stored=[]
    for name, data in (("first", b"video"), ("again", b"video"), ("other", b"other")):
        job = tmp_path / name
        job.mkdir()
        source=save_job_input(BytesIO(data), len(data), job)
        stored.append(source)
        assert source.read_bytes() == data
        assert not (job / "input.mp4").exists()
        assert not (job / "input.upload").exists()

    first,again,other=stored
    assert first.samefile(again)
    assert not first.samefile(other)
    (tmp_path/'first').rmdir()
    assert again.read_bytes() == b"video"


def test_subtitle_status_requires_nonempty_ass(tmp_path):
    server = SimpleNamespace(active_job=None)
    write_status(tmp_path, state="blocked", message="主图已结束，未生成成片。",
                 completed_nodes=["subtitle_cover"])
    (tmp_path / "subtitles").mkdir()
    for name in ("english_srt", "bilingual_srt"):
        (tmp_path / ARTIFACT_SPECS[name].path).write_text("subtitle", encoding="utf-8")
    chinese = tmp_path / ARTIFACT_SPECS["chinese_srt"].path
    chinese.touch()

    status = WorkflowServer.read_run_status(server, tmp_path)
    assert not status["subtitle_srt_ready"]
    assert "subtitle_cover" not in status["completed_nodes"]

    chinese.write_text("字幕", encoding="utf-8")
    status = WorkflowServer.read_run_status(server, tmp_path)
    assert status["subtitle_srt_ready"]
    assert "subtitle_cover" not in status["completed_nodes"]
    assert status["message"] == "三份 SRT 已生成，烧录字幕 ASS 尚未生成。"

    ass = tmp_path / ARTIFACT_SPECS["burnin_subtitle"].path
    ass.touch()
    assert "subtitle_cover" not in WorkflowServer.read_run_status(server, tmp_path)["completed_nodes"]
    ass.write_text("[Script Info]", encoding="utf-8")
    status = WorkflowServer.read_run_status(server, tmp_path)
    assert status["completed_nodes"] == ["subtitle_cover"]
    assert status["message"] == "烧录字幕 ASS 已生成，成片尚未生成。"
    assert status["state"] == "blocked"
    assert not status["final_video_ready"]


def test_elapsed_time_survives_phase_changes_and_stops_at_finish(tmp_path, monkeypatch):
    import serve_workflow_ui

    (tmp_path / "web-run.json").write_text(json.dumps({"created_at": 1000.0}))
    server = SimpleNamespace(active_job=tmp_path.name)
    monkeypatch.setattr(serve_workflow_ui, "time", lambda: 1010.0)
    write_status(tmp_path, state="running", phase="download")
    monkeypatch.setattr(serve_workflow_ui, "time", lambda: 1050.0)
    write_status(tmp_path, state="running", phase="workflow")
    status = WorkflowServer.read_run_status(server, tmp_path)
    assert status["started_at"] == 1000.0
    assert status["elapsed_seconds"] == 50.0
    monkeypatch.setattr(serve_workflow_ui, "time", lambda: 1100.0)
    write_status(tmp_path, state="failed", message="test failure")
    monkeypatch.setattr(serve_workflow_ui, "time", lambda: 1500.0)
    status = WorkflowServer.read_run_status(server, tmp_path)
    assert status["finished_at"] == 1100.0
    assert status["elapsed_seconds"] == 100.0
