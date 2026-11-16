"""translate_blocks 的业务 mock：静态真实译文 + 反查表 + 视频指纹分支。

定位：mocks 模块保证整条链路能跑通，**不保证输出结果正确**。

行为约定：
- `state.segments is None` 或 `state.blocks is None` → ValueError。
- `state.segments == []` → `[segments 为空]` warning，输出空 translated_blocks。
- `state.blocks == []` → `[blocks 为空]` warning，输出空 translated_blocks。
- 重复 `segment_id` → ValueError（数据自身非法）。
- 由 `state.blocks` 建立 `segment_id → block_id` 反查表；同一分段属于多个块时保留
  第一个，记 `[重复归属]` warning；未被任何块覆盖的分段**不输出**（不修改归属），
  记 `[未覆盖]` warning。
- 输入视频与 `project/mocks/data/translate_blocks.json` 的 `source` 指纹一致时使用
  静态译文；不一致时记 `[指纹不符]` warning，全部改用 `[模拟译文] <原文>`。
- 指纹一致但某个 `segment_id` 没有静态译文时，该条改用占位文本，记
  `[译文缺失]` warning。
- 输出顺序按 `state.segments`（真实节点按「块顺序 + 块内顺序」）。
- 不套用 SUBTITLE_PUNCTUATION_RULES 的中文标点规范；产物覆盖写入。

输入定位与指纹计算复用 mocks/_video.py。
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from contracts import GraphState, TranslatedSegment
from utils.io import write_artifact

from ._video import describe_mismatch, input_path, matches_source

logger = logging.getLogger(__name__)

DATA_SCHEMA_VERSION = 1

_DATA_PATH = Path(__file__).resolve().parent / "data" / "translate_blocks.json"
_FALLBACK_PREFIX = "[模拟译文]"


# ---------------------------------------------------------------------------
# 静态译文
# ---------------------------------------------------------------------------


def _load_data() -> dict:
    """读取静态译文数据；缺失或结构不合法时抛出。"""
    try:
        with _DATA_PATH.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
    except OSError as exc:
        raise RuntimeError(f"translate_blocks mock: 数据文件不可读: {_DATA_PATH}") from exc
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"translate_blocks mock: 数据文件不是合法 JSON: {_DATA_PATH}"
        ) from exc

    if not isinstance(data, dict) or data.get("schema_version") != DATA_SCHEMA_VERSION:
        raise RuntimeError(f"translate_blocks mock: 数据文件版本不匹配: {_DATA_PATH}")
    source = data.get("source")
    if not isinstance(source, dict) or not {"size_bytes", "head_sha256"} <= source.keys():
        raise RuntimeError(f"translate_blocks mock: 数据文件缺少 source 字段: {_DATA_PATH}")
    if not isinstance(data.get("translations"), dict):
        raise RuntimeError(f"translate_blocks mock: 数据文件缺少 translations: {_DATA_PATH}")
    return data


# ---------------------------------------------------------------------------
# 反查表
# ---------------------------------------------------------------------------


def _block_index(blocks) -> tuple[dict[str, str], list[str]]:
    """由 blocks 建立 segment_id → block_id 反查表，并收集重复归属的分段。"""
    index: dict[str, str] = {}
    duplicated: list[str] = []
    for block in blocks:
        for segment_id in block.segment_ids:
            if segment_id in index:
                if segment_id not in duplicated:
                    duplicated.append(segment_id)
                continue
            index[segment_id] = block.block_id
    return index, duplicated


# ---------------------------------------------------------------------------
# 节点主函数
# ---------------------------------------------------------------------------


def translate_blocks(state: GraphState) -> dict:
    """返回 translated_blocks 增量：静态译文 + 反查表填 block_id。"""
    segments = state.segments
    if segments is None:
        raise ValueError("translate_blocks mock: state.segments 为 None")
    blocks = state.blocks
    if blocks is None:
        raise ValueError("translate_blocks mock: state.blocks 为 None")

    if not segments:
        logger.warning("[segments 为空] segments 为空数组，输出空 translated_blocks")
        write_artifact("translated_blocks", [])
        return {"translated_blocks": []}

    if not blocks:
        logger.warning("[blocks 为空] blocks 为空数组，输出空 translated_blocks")
        write_artifact("translated_blocks", [])
        return {"translated_blocks": []}

    seen: set[str] = set()
    for segment in segments:
        if segment.segment_id in seen:
            raise ValueError(
                f"translate_blocks mock: 重复的分段 ID {segment.segment_id}"
            )
        seen.add(segment.segment_id)

    index, duplicated = _block_index(blocks)
    if duplicated:
        logger.warning(
            "[重复归属] 以下分段同时属于多个块，取第一个：%s", ", ".join(duplicated)
        )

    data = _load_data()
    path = input_path(state)
    source = data["source"]
    if matches_source(path, source):
        translations = data["translations"]
        use_static = True
    else:
        logger.warning(
            "[指纹不符] 静态译文对应的视频与输入视频不一致（%s）；"
            "全部改用 %s 占位文本",
            describe_mismatch(path, source),
            _FALLBACK_PREFIX,
        )
        translations = {}
        use_static = False

    drafts: list[TranslatedSegment] = []
    uncovered: list[str] = []
    missing: list[str] = []

    for segment in segments:
        block_id = index.get(segment.segment_id)
        if block_id is None:
            uncovered.append(segment.segment_id)
            continue
        zh_subtitle = translations.get(segment.segment_id)
        if zh_subtitle is None:
            if use_static:
                missing.append(segment.segment_id)
            zh_subtitle = f"{_FALLBACK_PREFIX} {segment.text_en}"
        drafts.append(
            TranslatedSegment(
                segment_id=segment.segment_id,
                block_id=block_id,
                zh_subtitle=zh_subtitle,
            )
        )

    if uncovered:
        logger.warning(
            "[未覆盖] 以下分段不属于任何块，已省略：%s", ", ".join(uncovered)
        )
    if missing:
        logger.warning(
            "[译文缺失] 以下分段没有静态译文，改用占位文本：%s", ", ".join(missing)
        )

    write_artifact("translated_blocks", drafts)
    logger.info(
        "translate_blocks mock: 输出 %d 条译文（静态译文%s）",
        len(drafts),
        "启用" if use_static else "未启用",
    )
    return {"translated_blocks": drafts}
