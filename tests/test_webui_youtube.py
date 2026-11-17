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
    server.sources = tmp_path / "sources"
    server.config_dir = tmp_path / "config"
    server.config_dir.mkdir()
    (server.config_dir / "tts.toml").write_text('voice_mode = "system"\n')
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
    def acquire(url, folder):
        folder.mkdir(parents=True,exist_ok=True)
        source=folder/'original.mp4';source.write_bytes(b'cached-original')
        return source,{'source_video':str(source),'url':url}
    monkeypatch.setattr(ui,'acquire_youtube',acquire)

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
    assert seen[0][seen[0].index("--input") + 1] == metadata["source_video"]
    assert Path(metadata['source_video']).is_file()
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


def test_cloned_mode_requires_per_job_permission_before_start(server,monkeypatch):
    (server.config_dir/'tts.toml').write_text('voice_mode = "cloned"\n')
    with pytest.raises(HTTPError) as error:
        urlopen(request(server,{'url':'https://youtu.be/jNQXAC9IVRw'}))
    assert error.value.code==400
    assert not server.worker_lock.locked() and not list(server.jobs.iterdir())
    captured=[]
    def run(job):
        captured.append(json.loads((job/'web-run.json').read_text(encoding='utf-8')))
        server.active_job=None
        server.worker_lock.release()
    monkeypatch.setattr(server,'run_workflow',run)
    with urlopen(request(server,{'url':'https://youtu.be/jNQXAC9IVRw','authorize_voice_clone':True})) as response:
        assert response.status==202
    from time import monotonic,sleep
    deadline=monotonic()+5
    while not captured and monotonic()<deadline:sleep(.01)
    assert captured[0]['authorize_voice_clone'] is True


def test_existing_source_is_read_in_place_for_repeated_jobs(server,monkeypatch):
    import serve_workflow_ui as ui
    from io import BytesIO
    holder=server.jobs/'upload-session';holder.mkdir()
    source=ui.save_job_input(BytesIO(b'original-video'),14,holder,server.sources/'uploads')
    captured=[]
    def run(job):
        captured.append((job,json.loads((job/'web-run.json').read_text(encoding='utf-8'))))
        server.active_job=None;server.worker_lock.release()
    monkeypatch.setattr(server,'run_workflow',run)
    url=f'http://127.0.0.1:{server.server_port}/api/video-sources'
    with urlopen(url) as response:rows=json.load(response)['sources']
    assert len(rows)==1
    from time import monotonic,sleep
    for count in (1,2):
        with urlopen(request(server,{'source_id':rows[0]['id']})) as response:
            job_id=json.load(response)['job_id']
        deadline=monotonic()+5
        while len(captured)<count and monotonic()<deadline:sleep(.01)
        job,meta=captured[-1]
        assert meta['source_video']==str(source) and not (job/'input.mp4').exists()
        with urlopen(f'http://127.0.0.1:{server.server_port}/api/workflow-runs/{job_id}/preview-video') as response:
            assert response.read()==b'original-video'
    assert len(list((server.sources/'uploads').glob('*.mp4')))==1


def test_target_video_inline_and_download_share_same_file(server):
    from serve_workflow_ui import ARTIFACT_SPECS, write_status
    job_id = 'a' * 32
    job = server.jobs / job_id
    job.mkdir()
    target = job / ARTIFACT_SPECS['final_video'].path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b'final-test-video')
    write_status(job, state='complete', completed_nodes=['compose_video'])
    url = f'http://127.0.0.1:{server.server_port}/api/workflow-runs/{job_id}/final-video'
    with urlopen(url + '?download=0') as response:
        assert response.read() == b'final-test-video'
        assert response.headers.get('Content-Disposition') is None
    with urlopen(url) as response:
        assert response.headers['Content-Disposition'].startswith('attachment;')
    with urlopen(Request(url + '?download=0', headers={'Range': 'bytes=0-4'})) as response:
        assert response.status == 206
        assert response.read() == b'final'
