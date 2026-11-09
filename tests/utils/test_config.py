"""utils/config.py 的验证：配置目录与加载。"""

from __future__ import annotations

from utils.config import _CONFIG_DIR, load_config


def test_config_dir_exists() -> None:
    assert _CONFIG_DIR.is_dir(), f"配置目录不存在: {_CONFIG_DIR}"
    assert _CONFIG_DIR.name == "config"


def test_load_config_returns_dict() -> None:
    tomls = list(_CONFIG_DIR.glob("*.toml"))
    assert tomls, "config/ 下应至少有一个 .toml 文件"
    result = load_config(tomls[0].name)
    assert isinstance(result, dict)