"""Profiles and stage overrides reach the same request adapter without exposing keys."""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import model_settings
from nodes.translate_blocks import _text_model
from nodes.translate_blocks._deepseek import DeepSeekError
from nodes.translate_blocks._models import load_registry, selected_model
from workflow_modes import ConfigChanged


def save(path, **payload):
    return model_settings.save(path, {**payload, "revision": model_settings.snapshot(path)["revision"]})


def test_model_profiles_persist_and_select_per_stage(tmp_path, monkeypatch):
    path = tmp_path / ".env"
    path.write_text('DEEPSEEK_API_KEY="original-secret"\nDEEPSEEK_MODEL="first-model"\n'
                    'DEEPSEEK_BASE_URL="https://first.example/v1"\nDEEPSEEK_TRANSPORT="school_bridge"\n')
    initial = model_settings.snapshot(path)
    assert initial["primary"] == "legacy"
    assert initial["review"] == initial["repair"] == "follow"
    assert "original-secret" not in json.dumps(initial)
    updated = save(path, action="upsert", profile={
        "name": "第二模型", "model": "second-model", "base_url": "https://second.example/v1",
        "api_key": "second-secret",
    })
    second = updated["primary"]
    assert len(updated["models"]) == 2
    assert "second-secret" not in json.dumps(updated)
    save(path, action="select", stage="review", selected="legacy")
    save(path, action="select", stage="repair", selected=second)
    calls = []
    monkeypatch.setattr(_text_model, "text_model_env", lambda: path)
    monkeypatch.setattr(_text_model, "load_dotenv", lambda *args: None)
    monkeypatch.setenv("DEEPSEEK_TRANSPORT", "api")
    monkeypatch.setattr(_text_model, "generate_json", lambda *args, **kwargs: calls.append(kwargs) or {})
    for stage in ["translate_blocks", "review_blocks", "repair_blocks"]:
        _text_model.request_for(stage, instruction="test", payload={})
    assert [item["model"] for item in calls] == ["second-model", "first-model", "second-model"]
    assert [item["api_key"] for item in calls] == ["second-secret", "original-secret", "second-secret"]
    assert [item["base_url"] for item in calls] == [
        "https://second.example/v1", "https://first.example/v1", "https://second.example/v1",
    ]
    save(path, action="select", stage="review", selected="follow")
    _text_model.request_for("review_blocks", instruction="test", payload={})
    assert calls[-1]["model"] == "second-model"
    assert model_settings.profile_key(path, second) == "second-secret"
    save(path, action="upsert", profile={
        "id": second, "name": "新名称", "model": "second-model", "base_url": "https://second.example/v1",
        "api_key": "",
    })
    assert model_settings.profile_key(path, second) == "second-secret"
    assert load_registry(path)["models"][1]["name"] == "新名称"
    assert 'DEEPSEEK_TRANSPORT="api"' in path.read_text()


def test_profile_validation_revision_and_origin_protect_saved_keys(tmp_path):
    path = tmp_path / ".env"
    path.write_text('DEEPSEEK_API_KEY="original-secret"\n')
    original = path.read_bytes()
    with pytest.raises(ValueError):
        save(path, action="upsert", profile={"name": "test", "model": "m", "base_url": "https://second.example"})
    assert path.read_bytes() == original
    with pytest.raises(ConfigChanged):
        model_settings.save(path, {"revision": "stale", "action": "select"})
    with pytest.raises(ValueError):
        save(path, action="select", stage="review", selected="missing")
    with pytest.raises(ValueError):
        model_settings.test_payload(path, {
            "id": "legacy", "base_url": "https://second.example", "model": "m", "api_key": "",
        })
    assert path.read_bytes() == original


def test_delete_active_model_and_start_again_from_empty_registry(tmp_path):
    path = tmp_path / ".env"
    assert model_settings.snapshot(path)["models"] == []
    path.write_text('DEEPSEEK_API_KEY="legacy-secret"\n')
    profile = {
        "name": "新模型", "model": "second-model", "base_url": "https://second.example/v1",
        "api_key": "second-secret",
    }
    new_id = save(path, action="upsert", profile=profile)["primary"]
    save(path, action="select", stage="review", selected=new_id)
    save(path, action="select", stage="repair", selected="legacy")

    remaining = save(path, action="delete", id=new_id)
    assert (remaining["primary"], remaining["review"], remaining["repair"]) == ("legacy", "follow", "legacy")
    with pytest.raises(ValueError, match="翻译模型不存在"):
        model_settings.profile_key(path, new_id)

    empty = save(path, action="delete", id="legacy")
    assert (empty["models"], empty["primary"], empty["review"], empty["repair"]) == ([], "", "follow", "follow")
    with pytest.raises(DeepSeekError, match="添加模型"):
        selected_model(path, environ={"DEEPSEEK_API_KEY": "legacy-secret"})
    with pytest.raises(ValueError, match="翻译模型不存在"):
        save(path, action="delete", id="legacy")
    restored = save(path, action="upsert", profile=profile)
    assert [item["id"] for item in restored["models"]] == [restored["primary"]]


def test_http_model_profiles_hide_keys_and_lock_during_run(tmp_path):
    from threading import Thread
    from urllib.error import HTTPError
    from urllib.request import Request, urlopen
    from serve_workflow_ui import WorkflowServer

    path = tmp_path / ".env"
    path.write_text('DEEPSEEK_API_KEY="original-secret"\n')
    server = WorkflowServer(0)
    server.env_path = path
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    origin = f"http://127.0.0.1:{server.server_port}"
    url = origin + "/api/translation-models"
    try:
        with urlopen(url) as response:
            data = json.load(response)
        assert "original-secret" not in json.dumps(data)
        payload = {"revision": data["revision"], "action": "upsert", "profile": {
            "name": "HTTP模型", "base_url": "https://other.example/v1", "model": "model-two",
            "api_key": "second-secret",
        }}
        request = Request(url, data=json.dumps(payload).encode(), method="PUT",
                          headers={"Content-Type": "application/json", "Origin": origin})
        server.worker_lock.acquire()
        try:
            with pytest.raises(HTTPError) as error:
                urlopen(request)
            assert error.value.code == 409
        finally:
            server.worker_lock.release()
        with urlopen(request) as response:
            data = json.load(response)
        assert "second-secret" not in json.dumps(data)
        key_url = url + "/" + data["primary"] + "/key"
        with pytest.raises(HTTPError) as error:
            urlopen(Request(key_url, method="POST"))
        assert error.value.code == 403
        with urlopen(Request(key_url, method="POST", headers={"Origin": origin})) as response:
            assert response.headers["Cache-Control"] == "no-store"
            assert json.load(response) == {"value": "second-secret"}
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
