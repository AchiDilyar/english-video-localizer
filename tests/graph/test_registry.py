"""验证 graph.registry.resolve_nodes 的切换规则与配置校验。

对应 architecture.md 4.4（键为节点名、布尔值、未列出默认真实）与 4.5
（切换只在 registry，节点模块不感知真实/模拟）。

全部用 fake 模块，不依赖 nodes/* 或 mocks/* 的真实实现。
"""

from __future__ import annotations

from types import ModuleType

import pytest

from graph import registry


def _fake_module(full_name: str) -> ModuleType:
    short = full_name.rsplit(".", 1)[-1]
    module = ModuleType(full_name)
    setattr(module, short, lambda state: {})
    return module


def _install(monkeypatch, flags, importer=None):
    monkeypatch.setattr(registry, "load_config", lambda _: flags)
    if importer is not None:
        monkeypatch.setattr(registry, "import_module", importer)


def test_all_real_when_flags_empty(monkeypatch):
    """architecture.md 4.4：未列出的节点默认真实。"""
    imported: list[str] = []

    def importer(name):
        imported.append(name)
        return _fake_module(name)

    _install(monkeypatch, {}, importer)

    nodes = registry.resolve_nodes()

    assert set(nodes) == set(registry.NODE_NAMES)
    assert imported == [f"nodes.{name}" for name in registry.NODE_NAMES], (
        f"应全部走 nodes.*，实际导入顺序: {imported}"
    )


def test_switch_is_per_node(monkeypatch):
    """architecture.md 4.4：每个节点独立选择，互不影响。"""
    imported: list[str] = []

    def importer(name):
        imported.append(name)
        return _fake_module(name)

    _install(monkeypatch, {"probe_input": True, "compose_video": True}, importer)

    registry.resolve_nodes()

    mocks = [n for n in imported if n.startswith("mocks.")]
    real = [n for n in imported if n.startswith("nodes.")]
    assert mocks == ["mocks.probe_input", "mocks.compose_video"], (
        f"应仅 probe_input 与 compose_video 走 mocks.*，实际: {mocks}"
    )
    assert len(real) == len(registry.NODE_NAMES) - 2, (
        f"其余 {len(registry.NODE_NAMES) - 2} 个应走 nodes.*，实际: {real}"
    )


def test_explicit_false_falls_back_to_real(monkeypatch):
    """architecture.md 4.4：显式 false 等价于未列出。"""
    imported: list[str] = []

    def importer(name):
        imported.append(name)
        return _fake_module(name)

    _install(monkeypatch, {"probe_input": False}, importer)

    registry.resolve_nodes()

    assert "nodes.probe_input" in imported
    assert "mocks.probe_input" not in imported


def test_unknown_key_fails(monkeypatch):
    """mock.toml 出现节点清单之外的键应失败，帮助发现拼写错误。"""
    _install(monkeypatch, {"probe_inpt": True})

    with pytest.raises(ValueError, match="probe_inpt"):
        registry.resolve_nodes()


def test_non_bool_value_fails(monkeypatch):
    """mock.toml 值必须是布尔，字符串 "false" 不能被当成 True。"""
    _install(monkeypatch, {"probe_input": "false"})

    with pytest.raises(TypeError, match="boolean"):
        registry.resolve_nodes()


def test_load_config_not_dict_fails(monkeypatch):
    """错误信息应指向根因，而非在 flags.keys() 处 AttributeError。"""
    monkeypatch.setattr(registry, "load_config", lambda _: None)

    with pytest.raises(TypeError, match="dict"):
        registry.resolve_nodes()


def test_missing_function_fails(monkeypatch):
    """节点模块未导出同名函数时直接失败。"""
    _install(monkeypatch, {}, lambda name: ModuleType(name))

    with pytest.raises(AttributeError):
        registry.resolve_nodes()


def test_non_callable_fails(monkeypatch):
    """节点模块的同名属性不可调用时直接失败。"""
    def importer(name):
        module = ModuleType(name)
        setattr(module, name.rsplit(".", 1)[-1], 42)
        return module

    _install(monkeypatch, {}, importer)

    with pytest.raises(TypeError, match="callable"):
        registry.resolve_nodes()