"""HTTP input validation and handoff to the same CLI; no network or paid models."""

import json
import sys
from pathlib import Path
from threading import Thread
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from serve_workflow_ui import WorkflowServer


@pytest.fixture
def server(tmp_path):
    server = WorkflowServer(0)
    server.jobs = tmp_path / "jobs"
    server.jobs.mkdir()
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server
    server.shutdown()
    server.server_close()
    thread.join()


def request(server, payload):
    return Request(
        f"http://127.0.0.1:{server.server_port}/api/workflow-runs",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )


@pytest.mark.parametrize(
    "value",
    [
        "https://example.com/video",
        "http://127.0.0.1/file",
        "https://www.youtube.com/playlist?list=abc",
        123,
        None,
    ],
)
def test_invalid_links_do_not_start_jobs(server, value):
    with pytest.raises(HTTPError) as error:
        urlopen(request(server, {"url": value}))
    assert error.value.code == 400
    assert list(server.jobs.iterdir()) == []
    assert not server.worker_lock.locked()


def test_url_submission_uses_standard_cli_and_reports_download(server, monkeypatch):
    import serve_workflow_ui as ui

    seen = []

    def run(command, **kwargs):
        seen.append(command)
        return type("Result", (), {"returncode": 0})()

    monkeypatch.setattr(ui.subprocess, "run", run)
    with urlopen(request(server, {"url": "https://youtu.be/jNQXAC9IVRw?t=1"})) as response:
        assert response.status == 202
        job_id = json.load(response)["job_id"]
    from time import monotonic, sleep

    deadline = monotonic() + 5
    while server.worker_lock.locked() and monotonic() < deadline:
        sleep(0.01)
    job = server.jobs / job_id
    metadata = json.loads((job / "web-run.json").read_text(encoding="utf-8"))
    assert metadata["source_url"] == "https://www.youtube.com/watch?v=jNQXAC9IVRw"
    assert seen and seen[0][1:4] == ["-u", "-m", "cli"]
    assert "--report-progress" in seen[0]
    assert seen[0][seen[0].index("--input") + 1] == metadata["source_url"]
    assert not (job / "input.mp4").exists()
    assert server.read_run_status(job)["state"] == "blocked"


def test_busy_request_returns_conflict(server):
    server.worker_lock.acquire()
    try:
        with pytest.raises(HTTPError) as error:
            urlopen(request(server, {"url": "https://youtu.be/jNQXAC9IVRw"}))
        assert error.value.code == 409
    finally:
        server.worker_lock.release()
