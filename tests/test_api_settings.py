"""No real credentials, network model calls or user configuration writes."""

import json
import sys
from pathlib import Path
from threading import Thread
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest
from dotenv import dotenv_values

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from api_settings import save, snapshot
from serve_workflow_ui import WorkflowServer
from workflow_modes import ConfigChanged


@pytest.fixture
def files(tmp_path):
    env = tmp_path / ".env"
    env.write_text(
        "# keep comment\nHF_TOKEN=fake-hf\nDEEPSEEK_API_KEY=fake-old-key\nDEEPSEEK_MODEL=school-model\nDASHSCOPE_REGION=ap-southeast-1\n"
    )
    tts = tmp_path / "tts.toml"
    tts.write_text('# keep tts\nmodel = "cosyvoice-v3-flash"\nvoices = ["test"]\n[overrides]\n')
    return env, tts


def payload(env, tts):
    data = snapshot(env, tts)
    return {"revision": data["revision"], "values": data["values"], "tts_model": data["tts_model"]}


def test_keys_write_only_preserve_and_clear(files):
    env, tts = files
    data = snapshot(env, tts)
    assert "fake-old-key" not in json.dumps(data)
    assert data["configured"]["DEEPSEEK_API_KEY"] is True
    request = payload(env, tts)
    request["secrets"] = {"DEEPSEEK_API_KEY": "", "DASHSCOPE_API_KEY": "fake-new-key"}
    result = save(env, tts, request)
    assert "fake-new-key" not in json.dumps(result)
    assert dotenv_values(env)["DEEPSEEK_API_KEY"] == "fake-old-key"
    assert dotenv_values(env)["DASHSCOPE_API_KEY"] == "fake-new-key"
    assert dotenv_values(env)["HF_TOKEN"] == "fake-hf"
    assert "# keep comment" in env.read_text()
    request = payload(env, tts)
    request["clear"] = ["DEEPSEEK_API_KEY"]
    request["tts_model"] = "cosyvoice-v3-plus"
    result = save(env, tts, request)
    assert not result["configured"]["DEEPSEEK_API_KEY"]
    assert 'voices = ["test"]' in tts.read_text()
    assert result["tts_model"] == "cosyvoice-v3-plus"


@pytest.mark.parametrize(
    "field,value",
    [
        ("DEEPSEEK_BASE_URL", "https://user:secret@example.org/v1"),
        ("DEEPSEEK_MODEL", "model\nDASHSCOPE_API_KEY=injected"),
        ("DASHSCOPE_REGION", "invalid"),
        ("DEEPSEEK_MODEL", "${HF_TOKEN}"),
    ],
)
def test_invalid_inputs_do_not_change_files(files, field, value):
    env, tts = files
    before = env.read_bytes(), tts.read_bytes()
    request = payload(env, tts)
    request["values"][field] = value
    with pytest.raises(ValueError):
        save(env, tts, request)
    assert before == (env.read_bytes(), tts.read_bytes())


def test_external_edits_not_overwritten(files):
    env, tts = files
    request = payload(env, tts)
    env.write_text(env.read_text() + "NEW_FIELD=keep\n")
    with pytest.raises(ConfigChanged):
        save(env, tts, request)


def test_custom_region_roundtrips_without_model_call(files):
    env, tts = files
    request = payload(env, tts)
    request['values']['DASHSCOPE_REGION'] = 'us-east-1'
    result = save(env, tts, request)
    assert result['values']['DASHSCOPE_REGION'] == 'us-east-1'
    assert dotenv_values(env)['DASHSCOPE_REGION'] == 'us-east-1'


def test_http_protection_and_no_echo(files):
    env, tts = files
    server = WorkflowServer(0)
    server.env_path = env
    server.config_dir = tts.parent
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{server.server_port}/api/api-settings"
    try:
        with urlopen(url) as response:
            assert response.headers["Cache-Control"] == "no-store"
            body = response.read()
            assert b"fake-old-key" not in body
        request = payload(env, tts)
        request["secrets"] = {"DASHSCOPE_API_KEY": "fake-http-key"}

        def put(origin=None):
            headers = {"Content-Type": "application/json"}
            if origin:
                headers["Origin"] = origin
            return urlopen(Request(url, json.dumps(request).encode(), headers, method="PUT"))

        with pytest.raises(HTTPError) as error:
            put("https://unrelated.example")
        assert error.value.code == 403
        server.worker_lock.acquire()
        try:
            with pytest.raises(HTTPError) as error:
                put()
            assert error.value.code == 409
        finally:
            server.worker_lock.release()
        with put() as response:
            body = response.read()
            assert b"fake-http-key" not in body
            assert b"fake-old-key" not in body
        assert dotenv_values(env)["DASHSCOPE_API_KEY"] == "fake-http-key"
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
