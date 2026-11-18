"""Expose the team's graph and its actual configuration to the local workbench."""

import json
import re
import tomllib
from hashlib import sha256
from pathlib import Path

from dotenv import dotenv_values
from graph.builder import WORKFLOW_EDGES
from graph.registry import NODE_NAMES
from graph.incremental import INCREMENTAL_NODE_NAMES
from nodes.b_environment import EnvironmentOptions
from nodes.mix_background import MixOptions
from nodes.asr_diarize.node import ASROptions
from nodes.build_blocks import DEFAULT_TERMINOLOGY, MAX_BLOCK_SPAN_MS
from nodes.compose_settings import BITRATE_LABELS, RESOLUTION_LABELS, ComposeOptions
from nodes.probe_input.node import ProbeOptions
from nodes.subtitle_cover import SubtitleCoverOptions
from nodes.translate_blocks._text_model import REQUEST_TIMEOUT_SEC, text_model_env, text_model_name
from subtitle_templates import LAYOUTS, STYLES
from workflow_modes import ConfigChanged, replace_config

OPTIONS = {
    "b_environment": EnvironmentOptions,
    "mix_background": MixOptions,
    "probe_input": ProbeOptions,
    "asr_diarize": ASROptions,
    "subtitle_cover": SubtitleCoverOptions,
    "compose_video": ComposeOptions,
}
READ_ONLY = {"community1_python"}
# Fields the workbench should not show. The backend models and save_settings
# still accept them so existing TOML values stay intact.
HIDDEN_FIELDS = {"probe_input": frozenset({"ffprobe", "ffmpeg"})}
CHOICES = {
    "device": ["cpu", "cuda"],
    "community1_device": ["cpu", "cuda"],
    "semantic_provider": ["none", "deepseek"],
    "style": list(STYLES),
    "layout": list(LAYOUTS),
    "resolution": list(RESOLUTION_LABELS),
    "bitrate": list(BITRATE_LABELS),
}
CHOICE_LABELS = {
    "style": {key: item["label"] for key, item in STYLES.items()},
    "layout": {key: item["label"] for key, item in LAYOUTS.items()},
    "resolution": RESOLUTION_LABELS,
    "bitrate": BITRATE_LABELS,
}


def workflow_schema() -> dict:
    return {
        "nodes": NODE_NAMES,
        "incremental_nodes": list(INCREMENTAL_NODE_NAMES),
        "edges": [
            [name, target]
            for source, target in WORKFLOW_EDGES
            for name in (source if isinstance(source, tuple) else (source,))
        ],
    }


def settings_snapshot(node: str, source: bytes) -> dict:
    model = OPTIONS[node]
    values = model.model_validate(tomllib.loads(source.decode("utf-8"))).model_dump()
    fields = []
    for key, schema in model.model_json_schema()["properties"].items():
        variants = schema.get("anyOf", [schema])
        spec = next(item for item in variants if item["type"] != "null")
        fields.append({
            "key": key,
            "value": values[key],
            "type": spec["type"],
            "optional": any(item["type"] == "null" for item in variants),
            "readonly": key in READ_ONLY,
            "choices": CHOICES.get(key),
            "choice_labels": CHOICE_LABELS.get(key),
            "min": spec.get("minimum", spec.get("exclusiveMinimum")),
            "max": spec.get("maximum"),
        })
    return {"revision": sha256(source).hexdigest(), "fields": fields}


def read_settings(config_dir: Path, node: str) -> dict:
    if node in OPTIONS:
        snapshot = settings_snapshot(node, (config_dir / f"{node}.toml").read_bytes())
        hidden = HIDDEN_FIELDS.get(node)
        if hidden:
            snapshot = {
                **snapshot,
                "fields": [field for field in snapshot["fields"] if field["key"] not in hidden],
            }
        return snapshot
    if node == "build_blocks":
        return {"fixed": {
            "max_block_span_ms": MAX_BLOCK_SPAN_MS, "default_terminology": DEFAULT_TERMINOLOGY,
        }}
    if node in ("translate_blocks", "review_blocks", "repair_blocks"):
        return {"fixed": {
            "model": text_model_name(dotenv_values(text_model_env()).get("DEEPSEEK_MODEL")),
            "timeout_sec": REQUEST_TIMEOUT_SEC,
        }}
    if node == "tts_align":
        config = tomllib.loads((config_dir / "tts.toml").read_text(encoding="utf-8"))
        return {"fixed": {key: config[key] for key in (
            "model", "voice_mode", "min_speed", "max_speedup", "natural_groups",
            "duration_repair_attempts", "duration_exhaustion_policy",
            "max_forward_delay_ms", "short_audio_policy"
        ) if key in config}}
    return {"fixed": {}}


def save_settings(path: Path, node: str, payload: dict) -> dict:
    if not isinstance(payload, dict) or not isinstance(payload.get("values"), dict):
        raise ValueError("配置请求无效。")
    original = path.read_bytes()
    snapshot = settings_snapshot(node, original)
    if payload.get("revision") != snapshot["revision"]:
        raise ConfigChanged("后端配置已变更，请重新读取后再保存。")

    editable = {field["key"]: field for field in snapshot["fields"] if not field["readonly"]}
    values = payload["values"]
    if not values.keys() <= editable.keys():
        raise ValueError("包含无法编辑的后端配置项。")
    text = original.decode("utf-8")
    existing = tomllib.loads(text)
    expected = existing.copy()
    for key, value in values.items():
        if value is None:
            if not editable[key]["optional"]:
                raise ValueError(f"{key} 不能为空。")
            expected.pop(key, None)
        elif value != editable[key]["value"] or type(value) is not type(editable[key]["value"]):
            expected[key] = value
    OPTIONS[node].model_validate(expected, strict=True)

    for key in values:
        if key not in existing and key not in expected:
            continue
        if key in existing and key in expected and existing[key] == expected[key]:
            continue
        pattern = rf"""(?m)^[ \t]*(?:{key}|"{key}"|'{key}')[ \t]*=[^\r\n]*(?:\r?\n|$)"""
        text, count = re.subn(pattern, "", text, count=1)
        if key in existing and count != 1:
            raise ValueError(f"无法更新 {key}，请检查 TOML 格式。")
        if key in expected:
            encoded = json.dumps(expected[key], ensure_ascii=False, allow_nan=False)
            text += ("" if not text or text.endswith("\n") else "\n") + f"{key} = {encoded}\n"

    updated = text.encode("utf-8")
    if tomllib.loads(text) != expected:
        raise ValueError("无法保留现有 TOML 结构，请检查配置文件。")
    result = settings_snapshot(node, updated)
    replace_config(path, original, updated)
    return result
