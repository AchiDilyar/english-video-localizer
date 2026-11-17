"""Edit the shared graph configuration from the local workbench."""

import re
import tomllib
from hashlib import sha256
from importlib.util import find_spec
from pathlib import Path
from stat import S_IMODE
from tempfile import NamedTemporaryFile

from graph.builder import WORKFLOW_EDGES
from graph.registry import NODE_NAMES, node_modes_from_flags
from graph.incremental import INCREMENTAL_NODE_NAMES


class ConfigChanged(Exception):
    """The user edited an outdated snapshot."""


def mode_snapshot(source: bytes) -> dict:
    return {
        "modes": node_modes_from_flags(tomllib.loads(source.decode("utf-8"))),
        "revision": sha256(source).hexdigest(),
        "available": [name for name in NODE_NAMES if find_spec(f"nodes.{name}") is not None],
    }


def save_modes(path: Path, payload: dict) -> dict:
    if not isinstance(payload, dict) or not isinstance(payload.get("modes"), dict):
        raise ValueError("请选择有效的节点模式。")
    requested = payload["modes"]
    if requested.keys() != set(NODE_NAMES) or any(
        mode not in ("mock", "real") for mode in requested.values()
    ):
        raise ValueError("请选择有效的节点模式。")
    original = path.read_bytes()
    snapshot = mode_snapshot(original)
    if payload.get("revision") != snapshot["revision"]:
        raise ConfigChanged("后端配置已变更，请重新读取后再保存。")

    unavailable = [name for name in NODE_NAMES
                   if requested[name] == "real" and name not in snapshot["available"]]
    if unavailable:
        raise ValueError(f"以下节点尚无真实实现：{', '.join(unavailable)}。")
    for source, target in WORKFLOW_EDGES:
        upstream = source if isinstance(source, tuple) else (source,)
        missing = [name for name in upstream if requested[name] == "mock"
                   and name not in INCREMENTAL_NODE_NAMES
                   and (target, name) != ("compose_video", "tts_align")]
        if requested[target] == "real" and missing:
            raise ValueError(f"{target} 需要启用真实上游节点：{', '.join(missing)}。")

    text = original.decode("utf-8")
    existing = tomllib.loads(text)
    for name in NODE_NAMES:
        if requested[name] == snapshot["modes"][name]:
            continue
        value = "true" if requested[name] == "mock" else "false"
        if name not in existing:
            newline = "\r\n" if "\r\n" in text else "\n"
            text = text.rstrip("\r\n") + newline + f"{name} = {value}" + newline
            continue
        key = rf"""(?:{name}|"{name}"|'{name}')"""
        pattern = rf"(?m)^([ \t]*{key}[ \t]*=[ \t]*)(?:true|false)\b"
        text, count = re.subn(pattern, lambda match: match[1] + value, text, count=1)
        if count != 1:
            raise ValueError(f"无法更新配置中的 {name}，请检查该行格式。")

    updated = text.encode("utf-8")
    result = mode_snapshot(updated)
    if result["modes"] != requested:
        raise ValueError("生成的节点模式与请求不一致。")
    replace_config(path, original, updated)
    return result


def replace_config(path: Path, original: bytes, updated: bytes) -> None:
    if updated == original:
        return
    candidate = None
    try:
        with NamedTemporaryFile(dir=path.parent, delete=False) as temporary:
            candidate = Path(temporary.name)
            temporary.write(updated)
        candidate.chmod(S_IMODE(path.stat().st_mode))
        if path.read_bytes() != original:
            raise ConfigChanged("后端配置已变更，请重新读取后再保存。")
        candidate.replace(path)
    finally:
        if candidate is not None:
            candidate.unlink(missing_ok=True)
