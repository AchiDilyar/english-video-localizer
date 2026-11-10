"""验证 mocks/ 最小骨架的完整性。

事实源：workflow.md 第 3 节节点清单。
本测试只验证：模块存在、函数同名、可调用、第一个位置参数名为 state、
返回 dict、mock.toml 键集合覆盖全部节点。
不验证业务字段、不验证落盘、不依赖 GraphState 字段。

graph.registry 落地后，建议将 EXPECTED_NODES 改为从 graph.registry.NODE_NAMES 导入。
"""

from __future__ import annotations

import importlib
import inspect
from pathlib import Path

import pytest

import mocks as mocks_pkg

EXPECTED_NODES = (
    "probe_input",
    "asr_diarize",
    "build_blocks",
    "translate_blocks",
    "review_blocks",
    "tts_align",
    "edit_assets",
    "subtitle_cover",
    "compose_video",
    "collect_manifest",
    "package_zip",
)

MOCKS_DIR = Path(mocks_pkg.__path__[0])


def _mock_module_names() -> list[str]:
    return sorted(p.stem for p in MOCKS_DIR.glob("*.py") if p.stem != "__init__")


def test_mocks_dir_exists() -> None:
    assert MOCKS_DIR.is_dir(), f"mocks 目录不存在: {MOCKS_DIR}"


def test_mock_modules_cover_all_nodes() -> None:
    found = set(_mock_module_names())
    expected = set(EXPECTED_NODES)
    missing = expected - found
    extra = found - expected
    assert not missing, f"缺少 mock 模块: {sorted(missing)}"
    assert not extra, f"存在未登记的 mock 模块: {sorted(extra)}"


@pytest.mark.parametrize("node_name", EXPECTED_NODES)
def test_mock_module_defines_same_name_function(node_name: str) -> None:
    module = importlib.import_module(f"mocks.{node_name}")
    assert hasattr(module, node_name), (
        f"mocks.{node_name} 未导出名为 {node_name} 的节点函数"
    )
    assert callable(getattr(module, node_name)), (
        f"mocks.{node_name}.{node_name} 不可调用"
    )


@pytest.mark.parametrize("node_name", EXPECTED_NODES)
def test_mock_function_accepts_state(node_name: str) -> None:
    module = importlib.import_module(f"mocks.{node_name}")
    fn = getattr(module, node_name)
    params = list(inspect.signature(fn).parameters.values())
    positional = [
        p for p in params
        if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)
    ]
    assert positional, f"mocks.{node_name}.{node_name} 不接受位置参数"
    assert positional[0].name == "state", (
        f"mocks.{node_name}.{node_name} 第一个参数应命名为 state，"
        f"实际为 {positional[0].name}"
    )


def test_mock_functions_return_dict() -> None:
    """骨架阶段所有 mock 返回空 dict；不验证字段，只验证返回类型。

    将来 mock 读取 state 字段后，此处调用可能因 None 失败，
    应改为传入合法 GraphState 或删除该测试。
    """
    for name in EXPECTED_NODES:
        module = importlib.import_module(f"mocks.{name}")
        fn = getattr(module, name)
        result = fn(None)
        assert isinstance(result, dict), f"mocks.{name}.{name} 应返回 dict"


def test_mock_toml_lists_all_nodes() -> None:
    """config/mock.toml 键集合应覆盖全部节点；骨架阶段全为 true。"""
    from utils.config import load_config

    cfg = load_config("mock.toml")
    assert isinstance(cfg, dict)
    expected = set(EXPECTED_NODES)
    assert set(cfg) == expected, (
        f"mock.toml 键与节点清单不一致："
        f"缺少 {sorted(expected - set(cfg))}，多余 {sorted(set(cfg) - expected)}"
    )

def test_mock_toml_all_true_skeleton_phase() -> None:
    """骨架阶段专用断言：mock.toml 全部为 true。

    预期寿命：B/C/D/E 节点交付并逐个切真实后，本断言应当失败，
    届时删除本函数，不要注释掉。test_mock_toml_keys_cover_all_nodes 继续保留。
    """
    from utils.config import load_config

    cfg = load_config("mock.toml")
    for name in EXPECTED_NODES:
        assert cfg[name] is True, f"mock.toml 中 {name} 应为 true（骨架阶段）"