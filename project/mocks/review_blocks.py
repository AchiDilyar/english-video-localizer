"""review_blocks 的业务 mock：透传 + 覆盖性告警。

定位：mocks 模块保证整条链路能跑通，**不保证输出结果正确**。真实节点会逐块调
模型审校并可能改写 `zh_subtitle`；mock 完全透传，不做任何修改。

行为约定：
- `state.segments is None` 或 `state.translated_blocks is None` → ValueError。
- `state.segments == []` → `[segments 为空]` warning，输出空 reviewed_blocks。
- `state.translated_blocks == []` → `[translated_blocks 为空]` warning，输出空
  reviewed_blocks。
- segments 或 translated_blocks 中存在重复 `segment_id` → ValueError（数据自身非法）。
- segments 与 translated_blocks 的 ID 集合不一致 → `[覆盖不符]` warning，
  **不修改数据**。
- 输出顺序与 `translated_blocks` 一致，文本原样保留。
- 不读配置（真实节点会读 translate_blocks.toml 的 style 进提示词）；产物覆盖写入。
"""

from __future__ import annotations

import logging

from contracts import GraphState
from utils.io import write_artifact

logger = logging.getLogger(__name__)


def _duplicate_ids(items) -> list[str]:
    seen: set[str] = set()
    duplicated: list[str] = []
    for item in items:
        if item.segment_id in seen:
            if item.segment_id not in duplicated:
                duplicated.append(item.segment_id)
            continue
        seen.add(item.segment_id)
    return duplicated


def review_blocks(state: GraphState) -> dict:
    """返回 reviewed_blocks 增量：原样透传 translated_blocks。"""
    segments = state.segments
    if segments is None:
        raise ValueError("review_blocks mock: state.segments 为 None")
    translated = state.translated_blocks
    if translated is None:
        raise ValueError("review_blocks mock: state.translated_blocks 为 None")

    if not segments:
        logger.warning("[segments 为空] segments 为空数组，输出空 reviewed_blocks")
        write_artifact("reviewed_blocks", [])
        return {"reviewed_blocks": []}

    if not translated:
        logger.warning(
            "[translated_blocks 为空] translated_blocks 为空数组，输出空 reviewed_blocks"
        )
        write_artifact("reviewed_blocks", [])
        return {"reviewed_blocks": []}

    for name, items in (("segments", segments), ("translated_blocks", translated)):
        duplicated = _duplicate_ids(items)
        if duplicated:
            raise ValueError(
                f"review_blocks mock: {name} 中 segment_id 重复: {', '.join(duplicated)}"
            )

    segment_ids = {segment.segment_id for segment in segments}
    translated_ids = {item.segment_id for item in translated}
    missing = sorted(segment_ids - translated_ids)
    extra = sorted(translated_ids - segment_ids)
    if missing or extra:
        logger.warning(
            "[覆盖不符] 译文与分段不一致：缺少 %s，多余 %s；按原样透传，不修改数据",
            missing or "无",
            extra or "无",
        )

    result = list(translated)
    write_artifact("reviewed_blocks", result)
    logger.info("review_blocks mock: 透传 %d 条译文", len(result))
    return {"reviewed_blocks": result}
