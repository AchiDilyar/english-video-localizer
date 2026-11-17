"""b_environment 的 mock：增量节点，空实现。

真实节点由 B 实现：分离背景、恢复非语言事件，发布环境音与来源回执。
mock 只保证链路可跑通，不产出环境音；下游 mix_background 按缺失处理。
"""


def b_environment(state):
    return {}
