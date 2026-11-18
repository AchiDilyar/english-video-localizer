"""Private model profiles use one atomic local .env update."""
import hmac
import json
import re
import secrets
from hashlib import sha256
from urllib.parse import urlsplit
from uuid import uuid4

from nodes.translate_blocks._models import REGISTRY_KEY, load_registry
from nodes.translate_blocks._deepseek import chat_url
from workflow_modes import ConfigChanged, replace_config

_SALT = secrets.token_bytes(32)


def snapshot(path):
    raw = path.read_bytes() if path.exists() else b""
    data = load_registry(path)
    return {
        "revision": hmac.new(_SALT, raw, sha256).hexdigest(),
        **{key: data[key] for key in ("primary", "review", "repair")},
        "models": [{key: value for key, value in item.items() if key != "api_key"} |
                   {"configured": bool(item["api_key"])} for item in data["models"]],
    }


def profile_key(path, profile_id):
    for item in load_registry(path)["models"]:
        if item["id"] == profile_id:
            return item["api_key"]
    raise ValueError("翻译模型不存在。")


def save(path, payload):
    if not isinstance(payload, dict) or payload.get("revision") != snapshot(path)["revision"]:
        raise ConfigChanged("模型配置已变化，请刷新后重试。")
    original = path.read_bytes() if path.exists() else b""
    data = load_registry(path)
    action = payload.get("action")
    if action == "select":
        stage, selected = payload.get("stage"), payload.get("selected")
        if stage not in ("primary", "review", "repair"):
            raise ValueError("未知模型选择位置。")
        ids = [item["id"] for item in data["models"]]
        if selected not in ids and not (stage != "primary" and selected == "follow"):
            raise ValueError("选择的翻译模型不存在。")
        data[stage] = selected
    elif action == "upsert":
        item = payload.get("profile")
        if not isinstance(item, dict):
            raise ValueError("模型配置无效。")
        old = next((row for row in data["models"] if row["id"] == item.get("id")), None)
        if item.get("id") and old is None:
            raise ValueError("翻译模型不存在。")
        profile = {}
        for key in ("name", "model", "base_url", "api_key"):
            value = item.get(key, "")
            if not isinstance(value, str) or len(value) > 2048 or "${" in value or any(ord(c) < 32 for c in value):
                raise ValueError("模型字段不能包含控制字符，且长度不能超过2048。")
            profile[key] = value.strip()
        if not all(profile[key] for key in ("name", "model", "base_url")):
            raise ValueError("请填写配置名称、模型标识和 API 地址。")
        chat_url(profile["base_url"])
        profile["api_key"] = profile["api_key"] or (old["api_key"] if old else "")
        if not profile["api_key"]:
            raise ValueError("新增模型需要填写 API Key。")
        profile["id"] = old["id"] if old else uuid4().hex
        if old:
            data["models"][data["models"].index(old)] = profile
        else:
            if len(data["models"]) >= 32:
                raise ValueError("最多保存32个翻译模型。")
            data["models"].append(profile)
            data["primary"] = profile["id"]
    elif action == "delete":
        profile_id = payload.get("id")
        profiles = [item for item in data["models"] if item["id"] != profile_id]
        if len(profiles) == len(data["models"]):
            raise ValueError("翻译模型不存在。")
        data["models"] = profiles
        if data["primary"] == profile_id:
            data["primary"] = profiles[0]["id"] if profiles else ""
        for stage in ("review", "repair"):
            if data[stage] == profile_id:
                data[stage] = "follow"
    else:
        raise ValueError("模型操作无效。")
    encoded = json.dumps(json.dumps(data, ensure_ascii=False), ensure_ascii=False)
    text = re.sub(rf"(?m)^[ \t]*(?:export[ \t]+)?{REGISTRY_KEY}[ \t]*=[^\r\n]*(?:\r?\n|$)",
                  "", original.decode("utf-8-sig"))
    text = re.sub(r"(?m)^[ \t]*(?:export[ \t]+)?DEEPSEEK_TRANSPORT[ \t]*=[^\r\n]*(?:\r?\n|$)",
                  "", text)
    text = text.rstrip("\r\n") + '\nDEEPSEEK_TRANSPORT="api"\n'
    updated = (text.rstrip("\r\n") + f"\n{REGISTRY_KEY}={encoded}\n").encode()
    if not path.exists():
        path.touch(mode=0o600)
    replace_config(path, original, updated)
    return snapshot(path)


def test_payload(path, payload):
    """Never reuse a stored credential for a different provider origin."""
    if not isinstance(payload, dict):
        raise ValueError("测试请求无效。")
    key = payload.get("api_key", "")
    url, model = payload.get("base_url"), payload.get("model")
    if not all(isinstance(value, str) and len(value) <= 2048 for value in (key, url, model)):
        raise ValueError("模型字段无效。")
    target = urlsplit(chat_url(url))
    if not key.strip():
        data = load_registry(path)
        profile = next((item for item in data["models"] if item["id"] == payload.get("id")), None)
        if profile is None:
            raise ValueError("请填写 API Key。")
        previous = urlsplit(chat_url(profile["base_url"]))
        if (target.hostname, target.port or 443) != (previous.hostname, previous.port or 443):
            raise ValueError("更换接口域名或端口后，请填写对应密钥。")
        key = profile["api_key"]
    return {"base_url": url, "model": model, "api_key": key}
