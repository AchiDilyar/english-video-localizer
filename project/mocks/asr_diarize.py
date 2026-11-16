"""asr_diarize 的业务 mock：静态真实转写 + 指纹与时长校验。

定位：mocks 模块保证整条链路能跑通，**不保证输出结果正确**。切换到 mock 实现
本身就意味着接受可能不正确的结果，只要这种不正确能通过 warning 排查。

行为约定：
- 数据来自 project/mocks/data/asr_diarize.json（11 条真实转写，逐字取自
  tests/data/asr_diarize/real_dialogue/segments.json）。
- 对输入视频做前 64KB SHA-256 指纹校验（与 probe_input mock 同口径）。不符时
  记一条 [指纹不符] warning 并继续执行。
- state.media_info 存在时，把 end_ms 超出视频时长的分段整条丢弃：逐条记
  [丢弃] warning，再汇总一条 [丢弃汇总]；若全部被丢弃，返回空数组并记
  [空结果] warning，不抛出。
- state.media_info 缺失时跳过时长校验（真实节点也不依赖它），记 [校验跳过]。
- 数据文件缺失/损坏、Segment 校验失败、segment_id 重复属于数据自身非法，
  直接抛出。
- 产物覆盖写入。真实节点在 audio/source.wav 或 segments/segments.json 已存在
  时会抛 FileExistsError；这里有意放宽，便于重复演示。
"""

from __future__ import annotations

import json
import logging
import wave
from pathlib import Path

from contracts import GraphState, Segment
from utils.io import write_artifact
from utils.paths import artifact_path

from ._video import head_sha256, input_path

logger = logging.getLogger(__name__)

DATA_SCHEMA_VERSION = 1

_SAMPLE_RATE = 16000
_SAMPLES_PER_MS = 16
_DATA_PATH = Path(__file__).resolve().parent / "data" / "asr_diarize.json"


# ---------------------------------------------------------------------------
# 数据文件
# ---------------------------------------------------------------------------


def _load_data() -> dict:
    """读取静态转写数据；缺失或结构不合法时抛出（无回源路径）。"""
    try:
        with _DATA_PATH.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
    except OSError as exc:
        raise RuntimeError(f"asr_diarize mock: 数据文件不可读: {_DATA_PATH}") from exc
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"asr_diarize mock: 数据文件不是合法 JSON: {_DATA_PATH}") from exc

    if not isinstance(data, dict) or data.get("schema_version") != DATA_SCHEMA_VERSION:
        raise RuntimeError(f"asr_diarize mock: 数据文件版本不匹配: {_DATA_PATH}")
    source = data.get("source")
    if not isinstance(source, dict) or not {
        "size_bytes",
        "head_sha256",
        "duration_ms",
    } <= source.keys():
        raise RuntimeError(f"asr_diarize mock: 数据文件缺少 source 字段: {_DATA_PATH}")
    if not isinstance(data.get("segments"), list):
        raise RuntimeError(f"asr_diarize mock: 数据文件缺少 segments 列表: {_DATA_PATH}")
    return data


def _build_segments(data: dict) -> list[Segment]:
    segments = [Segment.model_validate(item) for item in data["segments"]]
    seen: set[str] = set()
    for segment in segments:
        if segment.segment_id in seen:
            raise ValueError(
                f"asr_diarize mock: 数据中 segment_id 重复: {segment.segment_id}"
            )
        seen.add(segment.segment_id)
    return segments


# ---------------------------------------------------------------------------
# 产物
# ---------------------------------------------------------------------------


def _write_source_audio(duration_ms: int | None) -> None:
    """写 16kHz / 单声道 / 16bit 静音 WAV，帧数 = duration_ms × 16。"""
    frames = 0 if duration_ms is None else duration_ms * _SAMPLES_PER_MS
    with wave.open(artifact_path("source_audio"), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(_SAMPLE_RATE)
        wav.writeframes(b"\x00\x00" * frames)


# ---------------------------------------------------------------------------
# 节点主函数
# ---------------------------------------------------------------------------


def asr_diarize(state: GraphState) -> dict:
    """返回 segments 增量：静态真实转写 + 指纹/时长校验。"""
    path = input_path(state)
    data = _load_data()
    segments = _build_segments(data)

    digest = head_sha256(path)
    expected_digest = data["source"]["head_sha256"]
    if digest != expected_digest:
        logger.warning(
            "[指纹不符] 数据文件记录 %s，输入视频 %s 实际 %s；继续执行，"
            "输出内容可能与画面不一致",
            expected_digest[:12],
            path.name,
            digest[:12],
        )

    media_info = state.media_info
    duration_ms: int | None = None
    if media_info is None:
        logger.info("[校验跳过] media_info 缺失，跳过时长校验")
    else:
        duration_ms = media_info.duration_ms
        dropped = [segment for segment in segments if segment.end_ms > duration_ms]
        if dropped:
            for segment in dropped:
                logger.warning(
                    "[丢弃] %s 结束 %d ms 超出视频 %d ms，整条丢弃",
                    segment.segment_id,
                    segment.end_ms,
                    duration_ms,
                )
            segments = [
                segment for segment in segments if segment.end_ms <= duration_ms
            ]
            logger.warning(
                "[丢弃汇总] 共丢弃 %d 条，保留 %d 条", len(dropped), len(segments)
            )
            if not segments:
                logger.warning(
                    "[空结果] 全部分段都被丢弃，返回空 segments；下游会因此失败"
                )

    write_artifact("segments", segments)
    _write_source_audio(duration_ms)
    logger.info(
        "asr_diarize mock: 输出 %d 条分段，source_audio 帧数 %s",
        len(segments),
        "0" if duration_ms is None else duration_ms * _SAMPLES_PER_MS,
    )
    return {"segments": segments}
