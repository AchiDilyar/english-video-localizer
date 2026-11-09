"""配置加载入口。

对应 architecture.md §5.2。
"""

from __future__ import annotations

import tomllib
from pathlib import Path


# project/utils/config.py -> project -> english-video-localizer -> config/
_CONFIG_DIR = Path(__file__).resolve().parent.parent.parent / "config"


def load_config(filename: str) -> dict:
    """从 config/ 目录加载指定 TOML 配置文件，返回 dict，不做 schema 校验。"""
    path = _CONFIG_DIR / filename
    with path.open("rb") as f:
        return tomllib.load(f)