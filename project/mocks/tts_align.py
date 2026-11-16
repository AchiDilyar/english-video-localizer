"""tts_align 的 mock 实现：结构验证用，不做真实 TTS。

与真实节点对齐的部分：
- 逐段音频长度 = 该段的时间窗（`end_ms - start_ms`），`TTSClip.duration_ms` 同值；
- `dub_audio` 长度 = 已覆盖分段的 `max(end_ms)`，与 `assemble_dub` 的 `total_ms` 同口径；
- 采样率 24000，对应 `config/tts.toml` 的默认 `sample_rate`（真实节点按配置取值）。

输入处理：
- `state.reviewed_blocks is None` → ValueError；空数组 → warning 并输出空结果
  （真实节点对空 `reviewed_blocks` 是 info + 返回 {}，不中断；mock 与其它 mock 节点一致用 warning）。
- `state.segments` 为 None 或空数组 → ValueError（没有时间窗就无法生成音频，与真实节点一致）。
- `reviewed_blocks` 里的 `segment_id` 不在 `segments` 中 → KeyError（与真实节点一致）。

音频内容全部是静音：mock 不合成语音，只保证结构与长度正确。
"""

from __future__ import annotations

import logging
import wave

from contracts import GraphState, TTSClip
from utils.io import write_artifact
from utils.paths import artifact_path

logger = logging.getLogger(__name__)

SAMPLE_RATE = 24000
SAMPLE_WIDTH = 2
CHANNELS = 1
SAMPLES_PER_MS = SAMPLE_RATE // 1000


def _write_silence(path: str, frames: int) -> None:
    """写指定帧数的静音 WAV（24kHz / 单声道 / 16bit）。"""
    with wave.open(path, "wb") as handle:
        handle.setnchannels(CHANNELS)
        handle.setsampwidth(SAMPLE_WIDTH)
        handle.setframerate(SAMPLE_RATE)
        if frames > 0:
            handle.writeframes(b"\x00" * (SAMPLE_WIDTH * CHANNELS * frames))


def tts_align(state: GraphState) -> dict:
    reviewed = state.reviewed_blocks
    if reviewed is None:
        raise ValueError("tts_align mock: state.reviewed_blocks 为 None")

    if not reviewed:
        logger.warning(
            "[reviewed_blocks 为空] reviewed_blocks 为空数组，输出空 tts_clips"
        )
        write_artifact("tts_clips", [])
        return {"tts_clips": []}

    segments = state.segments
    if not segments:
        raise ValueError("tts_align mock: 缺少 segments，无法确定时间窗")

    by_id = {segment.segment_id: segment for segment in segments}
    clips: list[TTSClip] = []
    covered_end_ms: list[int] = []

    for item in reviewed:
        segment = by_id.get(item.segment_id)
        if segment is None:
            raise KeyError(
                f"tts_align mock: 审校片段 {item.segment_id} 在 segments 中不存在"
            )

        window_ms = segment.end_ms - segment.start_ms
        audio_name = f"{item.segment_id}.wav"
        _write_silence(
            artifact_path("tts_audio", audio_name), window_ms * SAMPLES_PER_MS
        )
        covered_end_ms.append(segment.end_ms)
        clips.append(
            TTSClip(
                segment_id=item.segment_id,
                audio_path=audio_name,
                duration_ms=window_ms,
                text=item.zh_subtitle,
                voice_id="placeholder_voice",
                model="placeholder_model",
            )
        )

    write_artifact("tts_clips", clips)

    total_ms = max(covered_end_ms)
    _write_silence(artifact_path("dub_audio"), total_ms * SAMPLES_PER_MS)

    logger.info(
        "tts_align mock: 输出 %d 条分段音频与 %dms 静音配音轨",
        len(clips),
        total_ms,
    )
    return {"tts_clips": clips}
