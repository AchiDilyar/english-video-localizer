"""tts_align 节点测试：音色映射、时长对齐、音轨组装与产物契约。

测试临时目录按 `architecture.md` 第 9 节放在 `tests/tmp/` 下，不提交。
真实 TTS 由本文件内的假合成器替代，运行测试不需要 `DASHSCOPE_API_KEY`。

运行：`uv run --locked pytest tests/nodes/tts_align`
"""
from __future__ import annotations

import math
import os
import shutil
import uuid
import wave
from pathlib import Path

import pytest
from contracts import GraphState, Segment, TranslatedSegment
from nodes import tts_align
from utils.io import read_artifact
from utils.paths import set_work_dir

TESTS_DIR = Path(__file__).resolve().parents[2]
TMP_ROOT = TESTS_DIR / "tmp" / "tts_align"
WORK_SUBDIRS = (
    "audio",
    "segments",
    "translated",
    "tts",
    "subtitles",
    "cover",
    "video",
    "package",
    "logs",
)
SAMPLE_RATE = 24000

requires_ffmpeg = pytest.mark.skipif(
    shutil.which("ffmpeg") is None and not os.getenv("LOCALIZER_FFMPEG"),
    reason="需要 ffmpeg：加入 PATH 或设置 LOCALIZER_FFMPEG",
)


# ---------------------------------------------------------------------------
# 测试替身与夹具
# ---------------------------------------------------------------------------


def write_tone(path: Path, seconds: float, sample_rate: int = SAMPLE_RATE) -> None:
    """写一段正弦音 WAV，用作合成结果。"""
    frames = int(seconds * sample_rate)
    data = bytearray()
    for index in range(frames):
        value = int(12000 * math.sin(2 * math.pi * 440 * index / sample_rate))
        data += value.to_bytes(2, "little", signed=True)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        handle.writeframes(bytes(data))


def fake_synthesize(text, voice_id, model, sample_rate, out_path) -> None:
    """假合成器：时长按字数估算（0.12 秒/字，最少 0.4 秒）。"""
    write_tone(Path(out_path), max(0.4, len(text) * 0.12), sample_rate)


@pytest.fixture()
def work_dir():
    """按 CLI 的职责建好工作目录与子目录，结束后清理。"""
    root = TMP_ROOT / uuid.uuid4().hex
    for name in WORK_SUBDIRS:
        (root / name).mkdir(parents=True)
    set_work_dir(str(root))
    try:
        yield root
    finally:
        shutil.rmtree(root, ignore_errors=True)


@pytest.fixture()
def plan():
    return tts_align.build_voice_plan(
        {
            "model": "test-model",
            "sample_rate": SAMPLE_RATE,
            "voices": ["v1", "v2"],
            "fallback_voice": "fb",
            "overrides": {},
        }
    )


def make_segment(segment_id: str, speaker_id: str, start_ms: int, end_ms: int) -> Segment:
    return Segment(
        segment_id=segment_id,
        speaker_id=speaker_id,
        start_ms=start_ms,
        end_ms=end_ms,
        text_en="placeholder",
    )


def make_reviewed(segment_id: str, text: str) -> TranslatedSegment:
    return TranslatedSegment(
        segment_id=segment_id,
        block_id="blk_0001",
        zh_subtitle=text,
        zh_dub=text,
    )


# ---------------------------------------------------------------------------
# 音色映射
# ---------------------------------------------------------------------------


def test_voice_pool_follows_first_appearance(plan):
    mapping = tts_align.assign_voices(plan, ["spk_2", "spk_1"])
    assert mapping == {"spk_2": "v1", "spk_1": "v2"}


def test_same_speaker_keeps_one_voice():
    plan = tts_align.build_voice_plan({"voices": ["v1", "v2"]})
    mapping = tts_align.assign_voices(plan, ["spk_1", "spk_2"])
    assert mapping["spk_1"] == "v1"
    assert mapping["spk_2"] == "v2"


def test_unknown_speaker_uses_fallback_without_consuming_pool(plan):
    mapping = tts_align.assign_voices(plan, ["spk_unknown", "spk_1", "spk_2"])
    assert mapping["spk_unknown"] == "fb"
    assert mapping["spk_1"] == "v1"
    assert mapping["spk_2"] == "v2"


def test_custom_unknown_speaker_token_is_respected():
    plan = tts_align.build_voice_plan(
        {"voices": ["v1"], "fallback_voice": "fb", "unknown_speaker": "spk_na"}
    )
    mapping = tts_align.assign_voices(plan, ["spk_na", "spk_1"])
    assert mapping["spk_na"] == "fb"
    assert mapping["spk_1"] == "v1"


def test_override_wins_over_pool():
    plan = tts_align.build_voice_plan(
        {"voices": ["v1"], "overrides": {"spk_1": "merged"}}
    )
    mapping = tts_align.assign_voices(plan, ["spk_1", "spk_2"])
    assert mapping == {"spk_1": "merged", "spk_2": "v1"}


def test_more_speakers_than_voices_reuses_pool():
    plan = tts_align.build_voice_plan({"voices": ["v1", "v2"]})
    mapping = tts_align.assign_voices(plan, ["spk_1", "spk_2", "spk_3"])
    assert mapping["spk_3"] == "v1"


def test_invalid_overrides_raises():
    with pytest.raises(TypeError):
        tts_align.build_voice_plan({"overrides": ["spk_1"]})


def test_invalid_sample_rate_raises():
    with pytest.raises(ValueError):
        tts_align.build_voice_plan({"sample_rate": 0})


def test_shipped_config_is_usable():
    plan = tts_align.load_voice_plan()
    assert plan.model
    assert len(plan.voice_pool) >= 2
    assert plan.sample_rate > 0


# ---------------------------------------------------------------------------
# 时长对齐
# ---------------------------------------------------------------------------


@requires_ffmpeg
def test_short_clip_is_padded_to_window(work_dir):
    src = work_dir / "tts" / "src.wav"
    dst = work_dir / "tts" / "dst.wav"
    write_tone(src, 0.4)

    trimmed = tts_align.fit_to_window(src, dst, 2000, SAMPLE_RATE)

    assert trimmed is False
    assert tts_align.wav_duration_ms(dst) == pytest.approx(2000, abs=2)


@requires_ffmpeg
def test_clip_that_fits_is_not_speed_capped(work_dir):
    src = work_dir / "tts" / "src.wav"
    dst = work_dir / "tts" / "dst.wav"
    write_tone(src, 1.8)

    trimmed = tts_align.fit_to_window(src, dst, 2000, SAMPLE_RATE)

    assert trimmed is False
    assert tts_align.wav_duration_ms(dst) == pytest.approx(2000, abs=2)


@requires_ffmpeg
def test_overlong_clip_is_capped_then_trimmed(work_dir):
    src = work_dir / "tts" / "src.wav"
    dst = work_dir / "tts" / "dst.wav"
    write_tone(src, 5.0)

    trimmed = tts_align.fit_to_window(src, dst, 2000, SAMPLE_RATE)

    assert trimmed is True
    # 音轨必须填满时间窗，不能因为超时就留白
    assert tts_align.wav_duration_ms(dst) == pytest.approx(2000, abs=2)


def test_zero_window_raises(work_dir):
    with pytest.raises(ValueError):
        tts_align.fit_to_window(work_dir / "tts" / "x.wav", work_dir / "tts" / "y.wav", 0, SAMPLE_RATE)


# ---------------------------------------------------------------------------
# 节点整体行为
# ---------------------------------------------------------------------------


@requires_ffmpeg
def test_node_writes_clips_and_dub(work_dir, plan, monkeypatch):
    monkeypatch.setattr(tts_align, "load_voice_plan", lambda: plan)
    monkeypatch.setattr(tts_align, "synthesize_clip", fake_synthesize)
    state = GraphState(
        segments=[
            make_segment("seg_0001", "spk_1", 1000, 3000),
            make_segment("seg_0002", "spk_2", 3000, 5000),
        ],
        reviewed_blocks=[
            make_reviewed("seg_0001", "第一句"),
            make_reviewed("seg_0002", "第二句"),
        ],
    )

    clips = tts_align.tts_align(state)["tts_clips"]

    assert [clip.segment_id for clip in clips] == ["seg_0001", "seg_0002"]
    assert [clip.voice_id for clip in clips] == ["v1", "v2"]
    assert all(clip.duration_ms == 2000 for clip in clips)
    assert all(clip.text == "第一句" or clip.text == "第二句" for clip in clips)

    for clip in clips:
        assert (work_dir / "tts" / clip.audio_path).is_file()

    # clips.json 必须能通过公共读工具按契约校验
    saved = read_artifact("tts_clips")
    assert [clip.segment_id for clip in saved] == ["seg_0001", "seg_0002"]

    dub = work_dir / "audio" / "dub.wav"
    assert dub.is_file()
    assert tts_align.wav_duration_ms(dub) == pytest.approx(5000, abs=2)


@requires_ffmpeg
def test_dub_is_silent_before_first_segment(work_dir, plan, monkeypatch):
    monkeypatch.setattr(tts_align, "load_voice_plan", lambda: plan)
    monkeypatch.setattr(tts_align, "synthesize_clip", fake_synthesize)
    state = GraphState(
        segments=[make_segment("seg_0001", "spk_1", 1000, 2000)],
        reviewed_blocks=[make_reviewed("seg_0001", "你好")],
    )

    tts_align.tts_align(state)

    with wave.open(str(work_dir / "audio" / "dub.wav"), "rb") as handle:
        leading = handle.readframes(1000 * SAMPLE_RATE // 1000)
    assert leading and set(leading) == {0}


@requires_ffmpeg
def test_unknown_speaker_gets_fallback_voice(work_dir, plan, monkeypatch):
    monkeypatch.setattr(tts_align, "load_voice_plan", lambda: plan)
    monkeypatch.setattr(tts_align, "synthesize_clip", fake_synthesize)
    state = GraphState(
        segments=[make_segment("seg_0001", "spk_unknown", 0, 2000)],
        reviewed_blocks=[make_reviewed("seg_0001", "未知说话人")],
    )

    clips = tts_align.tts_align(state)["tts_clips"]

    assert clips[0].voice_id == "fb"


def test_empty_reviewed_returns_empty_increment(work_dir):
    assert tts_align.tts_align(GraphState()) == {}


def test_missing_segments_raises(work_dir):
    state = GraphState(reviewed_blocks=[make_reviewed("seg_0001", "孤立片段")])
    with pytest.raises(ValueError):
        tts_align.tts_align(state)


def test_reviewed_segment_without_matching_window_raises(work_dir):
    state = GraphState(
        segments=[make_segment("seg_0001", "spk_1", 0, 1000)],
        reviewed_blocks=[make_reviewed("seg_0002", "对不上的片段")],
    )
    with pytest.raises(KeyError):
        tts_align.tts_align(state)
