"""tts_align 的 mock 实现：结构验证用，不做真实 TTS。

- 每个 reviewed_blocks 的 segment_id 生成一条 TTSClip；
- text 取 reviewed_blocks[i].zh_subtitle（zh_dub 已弃用，不再读取）；
- 落盘 tts/clips.json、逐段空 WAV、audio/dub.wav；
- 返回增量 {"tts_clips": clips}。
"""

from __future__ import annotations

import wave

from contracts import TTSClip
from utils.io import write_artifact
from utils.paths import artifact_path


def _write_silent_wav(path: str) -> None:
    """写 0 帧的空 WAV（标准 WAV 头，约 44 字节）。"""
    with wave.open(path, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(16000)


def tts_align(state) -> dict:
    reviewed = state.reviewed_blocks
    if not reviewed:
        raise ValueError("tts_align: state.reviewed_blocks 为空，无法生成 TTS 音频")

    clips = [
        TTSClip(
            segment_id=seg.segment_id,
            audio_path=f"{seg.segment_id}.wav",
            duration_ms=0,
            text=seg.zh_subtitle,
            voice_id="placeholder_voice",
            model="placeholder_model",
        )
        for seg in reviewed
    ]

    write_artifact("tts_clips", clips)
    for clip in clips:
        _write_silent_wav(artifact_path("tts_audio", clip.audio_path))
    _write_silent_wav(artifact_path("dub_audio"))

    return {"tts_clips": clips}