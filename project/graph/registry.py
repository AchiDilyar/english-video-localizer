"""Resolve real/mock nodes exclusively through F's mock.toml."""
from importlib import import_module

from utils.config import load_config

NODE_NAMES = (
    "probe_input", "asr_diarize", "build_blocks", "translate_blocks", "review_blocks",
    "tts_align", "edit_assets", "subtitle_cover", "compose_video", "collect_manifest",
    "package_zip",
)


def resolve_nodes() -> dict:
    flags = load_config("mock.toml")
    unknown = flags.keys() - set(NODE_NAMES)
    if unknown:
        raise ValueError(f"Unknown nodes in mock.toml: {sorted(unknown)}")
    if any(type(value) is not bool for value in flags.values()):
        raise TypeError("mock.toml node switches must be booleans")
    nodes = {}
    for name in NODE_NAMES:
        package = "mocks" if flags.get(name, False) else "nodes"
        function = getattr(import_module(f"{package}.{name}"), name)
        if not callable(function):
            raise TypeError(f"{package}.{name}.{name} must be callable")
        nodes[name] = function
    return nodes
