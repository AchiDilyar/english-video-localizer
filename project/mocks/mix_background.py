"""mix_background 的 mock：增量节点，空实现。

真实节点由 E 实现：把环境音混入中文配音音轨，写混合音轨。
mock 不产出混合音轨，compose_video 会回退 dub。
"""


def mix_background(state):
    return {}
