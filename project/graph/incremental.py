"""增量节点异常隔离代理。

事实源：architecture.md 8.2（增量节点异常隔离）与 workflow.md 第 3 节
（节点版本归属）。代理只保证异常不外抛并返回空增量；基础版节点不经过
本模块包装。

限制说明：
- 代理无法回滚增量节点在抛异常前对 state 的原地修改。8.2 中“基础版字段
  保持执行前状态”依赖节点不原地修改 state，代理只保证不合并返回值。
- 代理无法回滚增量节点在抛异常前已写入磁盘的文件。8.2 中“增量节点不得
  写入基础版产物名/路径”依赖节点实现遵守，代理不清理已写文件。
"""
from __future__ import annotations

import functools
import logging
from collections.abc import Callable

from contracts import GraphState

logger = logging.getLogger(__name__)

# 事实源：workflow.md 第 3 节“版本归属”列。当前无增量节点。
INCREMENTAL_NODE_NAMES: frozenset[str] = frozenset(
    ["repair_blocks"]
)


def wrap_incremental(
    name: str,
    func: Callable[[GraphState], dict],
) -> Callable[[GraphState], dict]:
    """包装单个增量节点：异常时记录 warning 并返回空增量。"""

    @functools.wraps(func)
    def wrapper(state: GraphState) -> dict:
        try:
            return func(state)
        except Exception:
            logger.warning(
                "增量节点 %s 执行失败，返回空增量",
                name,
                exc_info=True,
            )
            return {}

    return wrapper


def apply_incremental_proxy(
    nodes: dict[str, Callable[[GraphState], dict]],
) -> dict[str, Callable[[GraphState], dict]]:
    """按模块级 INCREMENTAL_NODE_NAMES 批量包装；非增量节点原样返回。"""
    return {
        name: wrap_incremental(name, func) if name in INCREMENTAL_NODE_NAMES else func
        for name, func in nodes.items()
    }