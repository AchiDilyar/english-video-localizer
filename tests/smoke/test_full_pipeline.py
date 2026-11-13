"""端到端冒烟测试：前 5 个真实节点 + tts_align 真实节点（SDK 层 fake TTS）+ 后 2 个 mock 节点。

- 进程内调用 CLI（方案 B），覆盖目录创建、set_work_dir、日志初始化与 invoke；
- monkeypatch nodes.translate_blocks._text_model.request_json，禁止真实外部模型调用；
- monkeypatch dashscope.audio.tts_v2.SpeechSynthesizer，只替换云端合成入口；
  D 的 API key 检查、FFmpeg 转码、时间窗对齐、WAV 落盘、clips.json 与 dub.wav 组装均真实执行；
- 断言 final_video 可播放、全部中间产物齐全且合法、mock.toml 配置未漂移。

"""

from __future__ import annotations

import io
import shutil
import subprocess
import wave
from pathlib import Path

import pytest

import cli
from utils.config import load_config
from utils.io import read_artifact
from utils.paths import artifact_path
from datetime import datetime


_INPUT_VIDEO = (
    Path(__file__).resolve().parents[1]
    / "data"
    / "asr_diarize"
    / "real_dialogue"
    / "input.mp4"
)

_TMP_ROOT = Path(__file__).resolve().parents[1] / "tmp"

_EXPECTED_MOCK_FLAGS = {
    "probe_input": False,
    "asr_diarize" : False,
    "build_blocks" : False,
    "translate_blocks" : False,
    "review_blocks" : False,
    "repair_blocks" : False,
    "tts_align" : False,
    "subtitle_cover" : False,
    "compose_video" : False
}


def _find_ffprobe() -> str:
    """按 architecture.md 第 11 节：.tools 优先，PATH 其次，找不到 fail。"""
    repo_root = Path(__file__).resolve().parents[2]
    candidate = repo_root / ".tools" / "ffmpeg" / "bin" / "ffprobe.exe"
    if candidate.is_file():
        return str(candidate)
    found = shutil.which("ffprobe")
    if found:
        return found
    raise FileNotFoundError(
        "未找到 ffprobe；请放到仓库根 .tools/ffmpeg/bin/ffprobe.exe 或加入 PATH"
    )


def _assert_file(path: str, name: str) -> None:
    file_path = Path(path)
    assert file_path.is_file(), f"缺少产物 {name}: {file_path}"
    assert file_path.stat().st_size > 0, f"产物为空 {name}: {file_path}"


def _fake_tts_wav_bytes(duration_ms: int = 500, sample_rate: int = 24000) -> bytes:
    """生成合法 WAV bytes，供 D 的 ffmpeg pipe:0 转码。

    固定 500ms 静音：短时间窗会被 D 加速/裁剪，长时间窗会被 D 补静音，
    两种情况都能覆盖 D 的 fit_to_window 分支。
    """
    frames = int(sample_rate * duration_ms / 1000)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        handle.writeframes(b"\x00\x00" * frames)
    return buf.getvalue()


class _FakeSpeechSynthesizer:
    """仅替换云端合成调用，不替换 D 的 synthesize_clip。"""

    calls: list[tuple[str | None, str | None, str]] = []

    def __init__(self, **kwargs):
        self.model = kwargs.get("model")
        self.voice = kwargs.get("voice")

    def call(self, text: str) -> bytes:
        assert text, "D 不应传入空合成文本"
        _FakeSpeechSynthesizer.calls.append((self.model, self.voice, text))
        return _fake_tts_wav_bytes()


def _patch_p0b_external_calls(monkeypatch) -> None:
    """P0b 外部调用绕过：只 patch DashScope SDK 的 SpeechSynthesizer。

    - DASHSCOPE_API_KEY 设为 dummy，让 D 的 key 检查通过；
    - 清理 LOCALIZER_FFMPEG，确保 D 使用修复后的 .tools/PATH 查找顺序；
    - 不 patch nodes.tts_align.synthesize_clip、subprocess.run、write_artifact。
    """
    _FakeSpeechSynthesizer.calls.clear()
    monkeypatch.setenv("DASHSCOPE_API_KEY", "p0b-dummy-key")
    monkeypatch.delenv("LOCALIZER_FFMPEG", raising=False)

    repo_root = Path(__file__).resolve().parents[2]
    ffmpeg = repo_root / ".tools" / "ffmpeg" / "bin" / "ffmpeg.exe"
    assert ffmpeg.is_file(), f"缺少 FFmpeg: {ffmpeg}"

    import dashscope.audio.tts_v2 as tts_v2

    monkeypatch.setattr(tts_v2, "SpeechSynthesizer", _FakeSpeechSynthesizer)


@pytest.mark.slow
def test_full_pipeline_with_mocks(monkeypatch):
    # 1. 准备 work_dir 与输入视频
    assert _INPUT_VIDEO.is_file(), f"测试输入视频不存在: {_INPUT_VIDEO}"
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    work_dir = _TMP_ROOT / f"test_full_pipeline_{timestamp}"
    work_dir.mkdir(parents=True, exist_ok=False)
    shutil.copy2(_INPUT_VIDEO, work_dir / "input.mp4")

    # 2. 断言 mock.toml 未漂移（前 5 真实 + tts_align 真实 + 后 2 mock）
    flags = load_config("mock.toml")
    assert flags == _EXPECTED_MOCK_FLAGS, (
        f"mock.toml 与预期不一致：实际={flags!r}，预期={_EXPECTED_MOCK_FLAGS!r}"
    )

    # 3. patch 外部模型：翻译模型走固定译文，issues 走空列表
    from nodes.translate_blocks import _text_model

    def fake_request_json(*, instruction, payload, output_format=None):
        if output_format is not None and "issues" in output_format:
            return {"issues": []}
        segments = payload.get("segments", [])
        return {
            "items": [
                {
                    "segment_id": seg["segment_id"],
                    "zh_subtitle": f"测试译文-{seg['segment_id']}",
                }
                for seg in segments
            ]
        }

    monkeypatch.setattr(_text_model, "request_json", fake_request_json)

    # 3b. patch DashScope SDK 合成入口，保留 D 节点其余逻辑
    _patch_p0b_external_calls(monkeypatch)

    # 4. 进程内调用 CLI
    exit_code = cli.main(
        ["--work-dir", str(work_dir), "--input", "input.mp4"]
    )
    assert exit_code == 0

    # 5. 结构化 JSON 产物可反读且数量一致
    segments = read_artifact("segments")
    blocks = read_artifact("blocks")
    translated = read_artifact("translated_blocks")
    reviewed = read_artifact("reviewed_blocks")
    tts_clips = read_artifact("tts_clips")

    assert segments, "segments 为空"
    assert blocks, "blocks 为空"
    assert len(translated) == len(segments), "translated_blocks 数量与 segments 不一致"
    assert len(reviewed) == len(segments), "reviewed_blocks 数量与 segments 不一致"
    assert len(tts_clips) == len(reviewed), "tts_clips 数量与 reviewed_blocks 不一致"

    segment_ids = {segment.segment_id for segment in segments}
    assert {item.segment_id for item in translated} == segment_ids
    assert {item.segment_id for item in reviewed} == segment_ids
    assert [clip.segment_id for clip in tts_clips] == [
        item.segment_id for item in reviewed
    ]

    # 6. 二进制/文本产物存在且非空
    for name in (
        "source_audio",
        "dub_audio",
        "bilingual_srt",
        "burnin_subtitle",
        "final_video",
    ):
        _assert_file(artifact_path(name), name)

    for clip in tts_clips:
        _assert_file(artifact_path("tts_audio", clip.audio_path), f"tts_audio/{clip.audio_path}")

    # 7. final_video 可播放（E mock 占位，仅验证可解析，不验证 D 音轨被合成）
    ffprobe = _find_ffprobe()
    result = subprocess.run(
        [
            ffprobe,
            "-v", "error",
            "-select_streams", "v:0",
            "-show_entries", "stream=codec_name",
            "-of", "default=noprint_wrappers=1",
            artifact_path("final_video"),
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"ffprobe 失败: {result.stderr}"
    assert "codec_name=" in result.stdout, f"未检测到视频流: {result.stdout!r}"

    # 8. D 专项验收：fake TTS 覆盖次数、WAV 规格、时长对齐、音色与模型
    assert len(_FakeSpeechSynthesizer.calls) == len(reviewed), (
        "fake TTS 调用次数与 reviewed_blocks 不一致，"
        f"实际={len(_FakeSpeechSynthesizer.calls)}，预期={len(reviewed)}"
    )

    tts_cfg = load_config("tts.toml")
    expected_model = tts_cfg.get("model", "cosyvoice-v3-flash")
    allowed_voices = set(tts_cfg.get("voices", [])) | {
        tts_cfg.get("fallback_voice", "longanyang")
    }

    segments_by_id = {segment.segment_id: segment for segment in segments}
    for clip in tts_clips:
        wav_path = Path(artifact_path("tts_audio", clip.audio_path))
        with wave.open(str(wav_path), "rb") as handle:
            assert handle.getnchannels() == 1, f"{clip.segment_id} 不是单声道"
            assert handle.getsampwidth() == 2, f"{clip.segment_id} 不是 16bit"
            assert handle.getframerate() == 24000, f"{clip.segment_id} 不是 24kHz"
            actual_ms = round(handle.getnframes() * 1000 / handle.getframerate())

        segment = segments_by_id[clip.segment_id]
        window_ms = segment.end_ms - segment.start_ms
        assert abs(clip.duration_ms - actual_ms) <= 2, (
            f"{clip.segment_id} duration_ms={clip.duration_ms} 与 WAV 实际 {actual_ms}ms 不一致"
        )
        assert abs(actual_ms - window_ms) <= 2, (
            f"{clip.segment_id} WAV 时长 {actual_ms}ms 未对齐时间窗 {window_ms}ms"
        )
        assert clip.model == expected_model, (
            f"{clip.segment_id} model={clip.model!r}，预期 {expected_model!r}"
        )
        assert clip.voice_id in allowed_voices, (
            f"{clip.segment_id} voice_id={clip.voice_id!r} 不在 tts.toml 允许集合 {allowed_voices!r}"
        )

    # 8b. dub_audio WAV 头合法，时长约等于已覆盖 segment 的最大 end_ms
    covered = {clip.segment_id for clip in tts_clips}
    expected_dub_ms = max(
        segment.end_ms for segment in segments if segment.segment_id in covered
    )
    with wave.open(artifact_path("dub_audio"), "rb") as handle:
        assert handle.getnchannels() == 1, "dub_audio 不是单声道"
        assert handle.getsampwidth() == 2, "dub_audio 不是 16bit"
        assert handle.getframerate() == 24000, "dub_audio 不是 24kHz"
        dub_ms = round(handle.getnframes() * 1000 / handle.getframerate())
    assert abs(dub_ms - expected_dub_ms) <= 5, (
        f"dub_audio 时长 {dub_ms}ms 与已覆盖段最大 end_ms {expected_dub_ms}ms 偏差过大"
    )

    # 8c. run.log 存在且成功路径无 traceback
    log_path = work_dir / "logs" / "run.log"
    assert log_path.is_file(), f"缺少日志: {log_path}"
    log_text = log_path.read_text(encoding="utf-8", errors="replace")
    assert log_text.strip(), "run.log 为空"
    assert "Traceback" not in log_text, "成功路径不应出现 traceback"