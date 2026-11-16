"""build_blocks 的业务 mock：全部 segments 放进同一个块 + 长度阈值告警。

定位：mocks 模块保证整条链路能跑通，**不保证输出结果正确**。

行为约定：
- `state.segments is None` → ValueError；`state.segments == []` → 不报错，输出空
  blocks（这一条与真实节点不同：真实节点对 None 和空数组都会报错）。
- 重复 `segment_id` → ValueError（与真实节点一致）。
- 所有分段按 `start_ms` 排序后放进唯一一个 `blk_0001`。
- 单块过大时记 `[单块过大]` warning：分段数超过 MAX_BLOCK_SEGMENTS，或时间跨度
  超过 MAX_BLOCK_SPAN_MS。
- 术语表：`state.terminology` 为 None 时用 DEFAULT_TERMINOLOGY，否则原样透传；
  不读 config/translate_blocks.toml（当前 terminology.enabled=false，无实际差异）。
- 产物覆盖写入。

下面三个常量**复制**自真实节点，不是 import：mock 不依赖真实节点的内部实现，
否则 C 改个常量名就会打断 mock。C 调整时需人工同步这几个值。
"""

from __future__ import annotations

import logging

from contracts import GraphState, TranslationBlock
from utils.io import write_artifact

logger = logging.getLogger(__name__)

# 同步自 nodes/build_blocks.py:MAX_BLOCK_SPAN_MS
MAX_BLOCK_SPAN_MS = 90_000
# 同步自 nodes/build_blocks.py:DEFAULT_TERMINOLOGY
DEFAULT_TERMINOLOGY = {"sample size": "样本量"}
# 单块请求的经验上限：分段数过多时，真实 translate_blocks 的 JSON 输出可能被截断。
MAX_BLOCK_SEGMENTS = 50

_BLOCK_ID = "blk_0001"


def build_blocks(state: GraphState) -> dict:
    """返回 blocks + terminology 增量：全部 segments 放进同一个块。"""
    segments = state.segments
    if segments is None:
        raise ValueError("build_blocks mock: state.segments 为 None，无法分块")

    terminology = (
        DEFAULT_TERMINOLOGY if state.terminology is None else state.terminology
    )

    if not segments:
        logger.info("build_blocks mock: segments 为空数组，输出空 blocks")
        write_artifact("blocks", [])
        return {"blocks": [], "terminology": dict(terminology)}

    seen: set[str] = set()
    for segment in segments:
        if segment.segment_id in seen:
            raise ValueError(f"build_blocks mock: 重复的分段 ID {segment.segment_id}")
        seen.add(segment.segment_id)

    ordered = sorted(segments, key=lambda segment: segment.start_ms)
    block = TranslationBlock(
        block_id=_BLOCK_ID,
        segment_ids=[segment.segment_id for segment in ordered],
    )

    span_ms = max(segment.end_ms for segment in ordered) - min(
        segment.start_ms for segment in ordered
    )
    if len(ordered) > MAX_BLOCK_SEGMENTS:
        logger.warning(
            "[单块过大] 分段数 %d 超过阈值 %d；真实 translate_blocks 一次请求返回"
            "全部条目，输出可能被截断",
            len(ordered),
            MAX_BLOCK_SEGMENTS,
        )
    if span_ms > MAX_BLOCK_SPAN_MS:
        logger.warning(
            "[单块过大] 时间跨度 %d ms 超过阈值 %d ms；真实 build_blocks 会切成多块，"
            "此处只有一块",
            span_ms,
            MAX_BLOCK_SPAN_MS,
        )

    write_artifact("blocks", [block])
    logger.info("build_blocks mock: 输出 1 个块，%d 条分段", len(block.segment_ids))
    return {"blocks": [block], "terminology": dict(terminology)}
