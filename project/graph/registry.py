"""Resolve real/mock nodes exclusively through F's mock.toml."""
import logging
from collections.abc import Callable
from importlib import import_module

from contracts import GraphState
from utils.config import load_config

from .incremental import INCREMENTAL_NODE_NAMES, apply_incremental_proxy

logger = logging.getLogger(__name__)

NODE_NAMES = (
    "probe_input",
    "asr_diarize",
    "build_blocks",
    "translate_blocks",
    "review_blocks",
    "tts_align",
    "subtitle_cover",
    "compose_video",
)


def node_modes_from_flags(flags) -> dict[str, str]:
    if not isinstance(flags, dict):
        raise TypeError(f"mock.toml must parse into a dict, got {type(flags).__name__}")
    unknown = flags.keys() - set(NODE_NAMES)
    if unknown:
        raise ValueError(f"Unknown nodes in mock.toml: {sorted(unknown)}")
    if any(type(value) is not bool for value in flags.values()):
        raise TypeError("mock.toml node switches must be booleans")
    return {name: "mock" if flags.get(name, False) else "real" for name in NODE_NAMES}


def load_node_modes() -> dict[str, str]:
    return node_modes_from_flags(load_config("mock.toml"))


def _validate_incremental_names() -> None:
    """增量节点集合必须是 NODE_NAMES 的子集，防止拼写错误静默失效。"""
    unknown = INCREMENTAL_NODE_NAMES - set(NODE_NAMES)
    if unknown:
        raise ValueError(
            f"INCREMENTAL_NODE_NAMES contains unknown nodes: {sorted(unknown)}"
        )


def resolve_nodes() -> dict[str, Callable[[GraphState], dict]]:
    _validate_incremental_names()
    modes = load_node_modes()
    logger.info(
        "节点运行模式：%s",
        ", ".join(
            f"{name}={'模拟' if mode == 'mock' else '真实'}"
            for name, mode in modes.items()
        ),
    )
    nodes: dict[str, Callable[[GraphState], dict]] = {}
    for name, mode in modes.items():
        package = "mocks" if mode == "mock" else "nodes"
        function = getattr(import_module(f"{package}.{name}"), name)
        if not callable(function):
            raise TypeError(f"{package}.{name}.{name} must be callable")
        nodes[name] = function
    return apply_incremental_proxy(nodes)