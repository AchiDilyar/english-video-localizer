"""Local-only API configuration. Saved keys are revealed individually on request."""

import hmac
import io
import json
import re
import secrets
import tomllib
from hashlib import sha256
from urllib.parse import urlsplit

import httpx
from dotenv import dotenv_values
from nodes.translate_blocks._deepseek import DeepSeekError, chat_url, generate_json
from workflow_modes import ConfigChanged, replace_config

_SALT = secrets.token_bytes(32)
FIELDS = {
    "DEEPSEEK_TRANSPORT": "api",
    "DEEPSEEK_BASE_URL": "https://api.deepseek.com",
    "DEEPSEEK_MODEL": "",
    "DASHSCOPE_REGION": "ap-southeast-1",
    "DASHSCOPE_WORKSPACE": "",
}
KEYS = ("DEEPSEEK_API_KEY", "DASHSCOPE_API_KEY")


def read_saved_key(env_path, name):
    if name not in KEYS:
        raise ValueError("未知密钥字段。")
    return (dotenv_values(env_path, interpolate=False).get(name) or ""
            if env_path.exists() else "")


def test_translation_connection(env_path, payload):
    if not isinstance(payload, dict):
        raise ValueError("测试请求无效。")
    base_url, model, api_key = (payload.get(name) for name in ("base_url", "model", "api_key"))
    if any(not isinstance(value, str) or len(value) > 2048 or
           any(ord(char) < 32 for char in value) for value in (base_url, model, api_key)):
        raise ValueError("请检查接口地址、模型标识及密钥格式。")
    if not model.strip():
        raise ValueError("请填写翻译模型标识。")
    target = urlsplit(chat_url(base_url))
    if not api_key.strip():
        saved = dotenv_values(env_path, interpolate=False) if env_path.exists() else {}
        previous = urlsplit(chat_url(saved.get("DEEPSEEK_BASE_URL") or FIELDS["DEEPSEEK_BASE_URL"]))
        if (target.hostname, target.port or 443) != (previous.hostname, previous.port or 443):
            raise ValueError("接口域名或端口已更改，请填写该接口的 API Key 再测试。")
        api_key = saved.get("DEEPSEEK_API_KEY") or ""
    with httpx.Client(timeout=15.0, follow_redirects=False) as client:
        generate_json(client, 'Return a JSON object with "ok" set to true.',
                      {"test": "connectivity"}, api_key=api_key, model=model.strip(),
                      base_url=base_url)


def snapshot(env_path, tts_path):
    raw = env_path.read_bytes() if env_path.exists() else b""
    tts = tts_path.read_bytes()
    values = dotenv_values(stream=io.StringIO(raw.decode("utf-8-sig")), interpolate=False)
    return {
        "revision": hmac.new(_SALT, raw + b"\0" + tts, sha256).hexdigest(),
        "values": {name: values.get(name) or default for name, default in FIELDS.items()},
        "configured": {name: bool(values.get(name)) for name in KEYS},
        "tts_model": tomllib.loads(tts.decode("utf-8")).get("model", "cosyvoice-v3-flash"),
    }


def save(env_path, tts_path, payload):
    current = snapshot(env_path, tts_path)
    if not isinstance(payload, dict) or payload.get("revision") != current["revision"]:
        raise ConfigChanged("配置已变化，请重新打开 API 设置后保存。")
    values = payload.get("values")
    if not isinstance(values, dict) or set(values) != set(FIELDS):
        raise ValueError("API 配置字段不完整。")
    secret_values = payload.get("secrets", {})
    clear = payload.get("clear", [])
    if (
        not isinstance(secret_values, dict)
        or set(secret_values) - set(KEYS)
        or not isinstance(clear, list)
        or any(name not in KEYS for name in clear)
    ):
        raise ValueError("密钥字段无效。")
    updates = dict(values)
    for name in KEYS:
        candidate = secret_values.get(name, "")
        if not isinstance(candidate, str):
            raise ValueError("密钥必须为文本。")
        if name in clear and candidate.strip():
            raise ValueError("不能同时填写与清除同一密钥。")
        if name in clear or candidate.strip():
            updates[name] = candidate.strip() if name not in clear else ""
    model = payload.get("tts_model")
    if not isinstance(model, str) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,100}", model):
        raise ValueError("配音模型标识无效。")
    if any(
        not isinstance(v, str) or len(v) > 2048 or "${" in v or any(ord(c) < 32 for c in v)
        for v in updates.values()
    ):
        raise ValueError("配置不能包含换行或控制字符，且长度不能超过2048。")
    updates = {k: v.strip() for k, v in updates.items()}
    if updates["DEEPSEEK_TRANSPORT"] != "api":
        raise ValueError("网页运行请使用 API 直连方式。")
    try:
        chat_url(updates["DEEPSEEK_BASE_URL"])
    except DeepSeekError:
        raise ValueError("请填写不含账号、密码或查询参数的 HTTPS 接口地址。") from None
    if not updates["DEEPSEEK_MODEL"]:
        raise ValueError("请填写学校或服务商提供的翻译模型标识。")
    if not re.fullmatch(r"[a-z]{2}(?:-[a-z0-9]+)+", updates["DASHSCOPE_REGION"]) or len(updates["DASHSCOPE_REGION"]) > 64:
        raise ValueError("请填写有效的地域标识，例如 ap-southeast-1。")
    original = env_path.read_bytes() if env_path.exists() else b""
    text = original.decode("utf-8-sig")
    for name, value in updates.items():
        text = re.sub(rf"(?m)^[ \t]*(?:export[ \t]+)?{name}[ \t]*=[^\r\n]*(?:\r?\n|$)", "", text)
        # dotenv double-quote syntax; never put input into a shell command.
        encoded = value.replace("\\", "\\\\").replace('"', '\\"')
        text = text.rstrip("\r\n") + f'\n{name}="{encoded}"\n'
    parsed = dotenv_values(stream=io.StringIO(text), interpolate=False)
    if any(parsed.get(k) != v for k, v in updates.items()):
        raise ValueError("配置编码校验失败。")
    tts_original = tts_path.read_bytes()
    tts_text = tts_original.decode("utf-8")
    config = tomllib.loads(tts_text)
    if "model" in config:
        tts_text, count = re.subn(
            r"(?m)^model[ \t]*=[^\r\n]*", lambda _: "model = " + json.dumps(model), tts_text
        )
        if count != 1:
            raise ValueError("配音模型配置位置无效。")
    else:
        tts_text = "model = " + json.dumps(model) + "\n" + tts_text
    expected = {**config, "model": model}
    if tomllib.loads(tts_text) != expected:
        raise ValueError("无法保留配音配置结构。")
    # The server holds the worker lock throughout; running tasks never see partial settings.
    replace_config(tts_path, tts_original, tts_text.encode("utf-8"))
    try:
        if not env_path.exists():
            env_path.touch(mode=0o600, exist_ok=False)
        replace_config(env_path, original, text.encode("utf-8"))
    except Exception:
        replace_config(tts_path, tts_text.encode("utf-8"), tts_original)
        raise
    return snapshot(env_path, tts_path)
