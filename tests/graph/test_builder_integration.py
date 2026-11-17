"""真实编译 build_graph，验证当前配置下图可构建。

当前 config/mock.toml 中配置为 true 的节点对应 mocks/ 已交付，本测试应当通过。
预期寿命：B/C/D/E 节点交付并切真实后，若 nodes/ 未就绪，本测试会失败，
属预期；届时确认 nodes/ 已就绪即恢复。
"""

from __future__ import annotations

import graph
import graph.registry as registry_mod


def test_build_graph_compiles_with_current_config():
    compiled = graph.build_graph()
    node_names = set(compiled.get_graph().nodes.keys())
    missing = set(registry_mod.NODE_NAMES) - node_names
    assert not missing, f"图中缺少节点: {sorted(missing)}"