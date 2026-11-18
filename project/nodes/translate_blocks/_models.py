"""Shared translation model selection for the CLI and local workbench."""
import json
from pathlib import Path

from dotenv import dotenv_values

from ._deepseek import DEFAULT_BASE_URL, DEFAULT_MODEL, DeepSeekError, chat_url

REGISTRY_KEY = "LOCALIZER_TRANSLATION_MODELS"
STAGES = {"translate_blocks": "primary", "review_blocks": "review", "repair_blocks": "repair"}


def load_registry(env_path: Path, environ=None) -> dict:
    values = dict(dotenv_values(env_path, interpolate=False)) if env_path.exists() else {}
    raw = values.get(REGISTRY_KEY)
    legacy = {**values, **(environ or {})}
    if raw:
        registry = json.loads(raw)
    else:
        api_key = legacy.get("DEEPSEEK_API_KEY") or ""
        registry = {
            "models": [{
                "id": "legacy", "name": "默认翻译模型",
                "base_url": legacy.get("DEEPSEEK_BASE_URL") or DEFAULT_BASE_URL,
                "model": legacy.get("DEEPSEEK_MODEL") or DEFAULT_MODEL,
                "api_key": api_key,
            }] if api_key else [],
            "primary": "legacy" if api_key else "", "review": "follow", "repair": "follow",
        }
    models = registry["models"]
    ids = [item["id"] for item in models]
    if len(ids) != len(set(ids)) or registry["primary"] not in (ids or [""]):
        raise ValueError("翻译模型列表无效。")
    for stage in ("review", "repair"):
        if registry.get(stage, "follow") not in ["follow", *ids]:
            raise ValueError("审校或返工节点选择的翻译模型不存在。")
    for model in models:
        if not all(isinstance(model.get(key), str) for key in ("id", "name", "base_url", "model", "api_key")):
            raise ValueError("翻译模型字段无效。")
        chat_url(model["base_url"])
    return registry


def selected_model(env_path: Path, stage="translate_blocks", environ=None) -> dict:
    registry = load_registry(env_path, environ)
    if not registry["models"]:
        raise DeepSeekError("请在工作台的翻译模型列表中添加模型，或在本地 .env 中配置 DEEPSEEK_API_KEY。")
    selected = registry.get(STAGES.get(stage, "primary"), "follow")
    if selected == "follow":
        selected = registry["primary"]
    return next(item for item in registry["models"] if item["id"] == selected)
