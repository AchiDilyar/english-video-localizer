"""按说话人音色合成中文口播音频，对齐原时间窗，组装整条中文配音音轨。

事实源对应：
- `workflow.md` 第 3 节 `tts_align`：读审校结果，写分段音频清单、分段音频文件、中文配音音轨；
- `dataflow.md` 第 3 节产物表（`tts_clips` / `tts_audio` / `dub_audio`）与第 4 节工作目录结构；
- `architecture.md` 第 3 节节点签名、第 5 节配置加载、第 6 节通用函数、第 9 节测试与日志。

基本版边界（`workflow.md` 第 5 节）明确不含"配音超时退回"分支，因此本节点不实现返工：
超时片段只做加速与裁剪，并在日志中留痕，不新增任何状态字段。

本节点不创建任何目录（`dataflow.md` 第 4 节），目录由 CLI 在初始化时创建。
"""
from __future__ import annotations

import logging
import os
import shutil
import subprocess
import tempfile
import wave
from dataclasses import dataclass, field
from pathlib import Path

from contracts import GraphState, TTSClip
from utils.config import load_config
from utils.io import write_artifact
from utils.paths import artifact_path

logger = logging.getLogger(__name__)

# project/nodes/tts_align.py -> project -> 仓库根
_REPO_ROOT = Path(__file__).resolve().parents[2]

CONFIG_FILE = "tts.toml"
DEFAULT_MODEL = "cosyvoice-v3-flash"
DEFAULT_VOICE = "longanyang"
DEFAULT_UNKNOWN_SPEAKER = "spk_unknown"
DEFAULT_SAMPLE_RATE = 24000
MAX_SPEEDUP = 1.15
CHANNELS = 1
SAMPLE_WIDTH = 2


@dataclass(frozen=True)
class VoicePlan:
    """音色映射方案，全部来自 `config/tts.toml`。"""

    model: str
    sample_rate: int
    voice_pool: tuple[str, ...]
    fallback_voice: str
    unknown_speaker: str = DEFAULT_UNKNOWN_SPEAKER
    overrides: dict[str, str] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# 配置与音色映射
# ---------------------------------------------------------------------------


def build_voice_plan(config: dict) -> VoicePlan:
    """把 `config/tts.toml` 的原始 dict 转成 VoicePlan。

    配置键（均可选，缺失时用内置默认值）：
    - `model`：合成模型标识，原样写入 `TTSClip.model`
    - `sample_rate`：`dub_audio` 与逐段音频的采样率
    - `voices`：音色池，按说话人首次出现顺序依次分配
    - `fallback_voice`：未分配音色时使用
    - `unknown_speaker`：未知说话人的 `speaker_id`，该值固定取 `fallback_voice`。
      这一项对应 `increments/README.md` 里仍待决策的契约问题，放在配置里，
      无论最终结论如何都不需要改代码。
    - `[overrides]`：手工指定的 speaker_id -> voice_id，优先级最高
    """
    voices = config.get("voices", [])
    if not isinstance(voices, list) or not voices:
        voices = [DEFAULT_VOICE]
    overrides = config.get("overrides", {})
    if not isinstance(overrides, dict):
        raise TypeError("config/tts.toml 的 [overrides] 必须是一个表")
    sample_rate = int(config.get("sample_rate", DEFAULT_SAMPLE_RATE))
    if sample_rate <= 0:
        raise ValueError(f"config/tts.toml 的 sample_rate 必须为正，收到 {sample_rate}")
    return VoicePlan(
        model=str(config.get("model", DEFAULT_MODEL)),
        sample_rate=sample_rate,
        voice_pool=tuple(str(voice) for voice in voices),
        fallback_voice=str(config.get("fallback_voice", DEFAULT_VOICE)),
        unknown_speaker=str(config.get("unknown_speaker", DEFAULT_UNKNOWN_SPEAKER)),
        overrides={str(k): str(v) for k, v in overrides.items()},
    )


def load_voice_plan() -> VoicePlan:
    """读取 `config/tts.toml`。文件缺失或无效时按节点失败处理。"""
    return build_voice_plan(load_config(CONFIG_FILE))


def assign_voices(plan: VoicePlan, speaker_order: list[str]) -> dict[str, str]:
    """按说话人首次出现顺序分配音色，保证同一说话人全片一致。

    - `[overrides]` 中的说话人直接取指定音色，不占用音色池名额；
    - `unknown_speaker`（默认 `spk_unknown`）固定取 `fallback_voice`，不占用音色池名额，
      避免"为了接口非空随意指派某个人"；
    - 其余说话人按顺序轮流取音色池，说话人多于音色时复用并告警。
    """
    mapping: dict[str, str] = {}
    pool_index = 0
    for speaker_id in speaker_order:
        if speaker_id in plan.overrides:
            mapping[speaker_id] = plan.overrides[speaker_id]
        elif speaker_id == plan.unknown_speaker:
            mapping[speaker_id] = plan.fallback_voice
        else:
            mapping[speaker_id] = plan.voice_pool[pool_index % len(plan.voice_pool)]
            pool_index += 1
    if pool_index > len(plan.voice_pool):
        logger.warning(
            "本片有 %d 个说话人但只配置了 %d 个音色，音色会重复使用；"
            "可在 config/tts.toml 的 voices 中补充",
            pool_index,
            len(plan.voice_pool),
        )
    return mapping


# ---------------------------------------------------------------------------
# 音频工具
# ---------------------------------------------------------------------------


def resolve_ffmpeg() -> str:
    """按 `architecture.md` 第 11 节定位 ffmpeg。

    查找顺序：
    1. 仓库根 `.tools/ffmpeg/bin/ffmpeg.exe`（该分支仅 Windows 有效）；
    2. 系统 `PATH`。

    两处都找不到时抛出 `FileNotFoundError`，按节点失败处理，不静默降级。
    """
    if os.name == "nt":
        candidate = _REPO_ROOT / ".tools" / "ffmpeg" / "bin" / "ffmpeg.exe"
        if candidate.is_file():
            return str(candidate)
    found = shutil.which("ffmpeg")
    if found:
        return found
    raise FileNotFoundError(
        "tts_align: 未找到 FFmpeg；请放到仓库根 .tools/ffmpeg/bin/ffmpeg.exe 或加入 PATH"
    )


def wav_duration_ms(path: Path) -> int:
    """读取 WAV 头返回时长（毫秒）。"""
    with wave.open(str(path), "rb") as handle:
        frames = handle.getnframes()
        rate = handle.getframerate()
    if rate <= 0:
        raise ValueError(f"{path} 的采样率非法：{rate}")
    return round(frames * 1000 / rate)


def _read_frames(path: Path, sample_rate: int) -> bytes:
    with wave.open(str(path), "rb") as handle:
        actual = (handle.getnchannels(), handle.getsampwidth(), handle.getframerate())
        if actual != (CHANNELS, SAMPLE_WIDTH, sample_rate):
            raise ValueError(
                f"{path} 的格式是 {actual}，"
                f"期望 ({CHANNELS}, {SAMPLE_WIDTH}, {sample_rate})"
            )
        return handle.readframes(handle.getnframes())


def fit_to_window(src: Path, dst: Path, window_ms: int, sample_rate: int) -> bool:
    """把 `src` 对齐到 `window_ms` 的时间窗，写入 `dst`。

    - 短于时间窗：尾部补静音；
    - 超时：最多加速到 `MAX_SPEEDUP` 倍，加速后仍超出则裁剪到时间窗。

    返回是否因超时被裁剪（用于日志留痕；基本版不实现退回分支）。
    """
    if window_ms <= 0:
        raise ValueError(f"时间窗必须为正，收到 {window_ms}ms")

    source_ms = wav_duration_ms(src)
    speed = min(MAX_SPEEDUP, source_ms / window_ms) if source_ms > window_ms else 1.0
    filters = [f"atempo={speed:.6f}"] if speed > 1.0 else []
    filters.append("apad")

    ffmpeg = resolve_ffmpeg()
    result = subprocess.run(
        [
            ffmpeg,
            "-v",
            "error",
            "-y",
            "-i",
            str(src),
            "-af",
            ",".join(filters),
            "-t",
            f"{window_ms / 1000:.3f}",
            "-ar",
            str(sample_rate),
            "-ac",
            str(CHANNELS),
            "-c:a",
            "pcm_s16le",
            str(dst),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg 对齐失败（{result.returncode}）：{result.stderr.strip()}")

    return source_ms / speed > window_ms + 1


def assemble_dub(placed: list[tuple[int, Path]], out_path: Path, total_ms: int, sample_rate: int) -> None:
    """按 `start_ms` 把逐段音频摆进整条音轨，空档补静音。

    `placed` 每项为 (start_ms, 该段 WAV 路径)。段与段重叠时后一段覆盖前一段的重叠部分
    并记录警告；`segments` 由 B 生成，实测不重叠。
    """
    if total_ms <= 0:
        raise ValueError(f"总时长必须为正，收到 {total_ms}ms")

    samples_per_ms = sample_rate / 1000
    silence = b"\x00" * SAMPLE_WIDTH
    cursor_ms = 0

    with wave.open(str(out_path), "wb") as out:
        out.setnchannels(CHANNELS)
        out.setsampwidth(SAMPLE_WIDTH)
        out.setframerate(sample_rate)
        for start_ms, path in sorted(placed, key=lambda item: item[0]):
            gap_ms = start_ms - cursor_ms
            if gap_ms > 0:
                out.writeframes(silence * int(gap_ms * samples_per_ms))
            elif gap_ms < 0:
                logger.warning(
                    "片段 %s 与上一段重叠 %dms，重叠部分被丢弃", path.name, -gap_ms
                )
            frames = _read_frames(path, sample_rate)
            out.writeframes(frames)
            written_ms = len(frames) // SAMPLE_WIDTH / samples_per_ms
            cursor_ms = max(cursor_ms, start_ms) + int(written_ms)

        if cursor_ms < total_ms:
            out.writeframes(silence * int((total_ms - cursor_ms) * samples_per_ms))


# ---------------------------------------------------------------------------
# 语音合成
# ---------------------------------------------------------------------------


def synthesize_clip(
    text: str, voice_id: str, model: str, sample_rate: int, out_path: Path
) -> None:
    """调用 DashScope CosyVoice 合成一段中文口播，写成目标规格的 WAV。

    需要环境变量 `DASHSCOPE_API_KEY`（见 `.env.example`）；若账号需要工作空间，
    另配 `DASHSCOPE_WORKSPACE`。

    合成请求固定要 `WAV_24000HZ_MONO_16BIT`：CosyVoice 原生 24kHz，直接拿无损 WAV，
    避免默认 mp3 的编解码损耗。若所用模型不支持该输出格式，改成
    `AudioFormat.MP3_24000HZ_MONO_256KBPS` 即可，后续 ffmpeg 会统一转码。
    """
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parents[2] / ".env")
    api_key = os.getenv("DASHSCOPE_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("缺少 DASHSCOPE_API_KEY，无法合成中文配音")

    import dashscope
    from dashscope.audio.tts_v2 import AudioFormat, SpeechSynthesizer

    dashscope.api_key = api_key
    synthesizer = SpeechSynthesizer(
        model=model,
        voice=voice_id,
        format=AudioFormat.WAV_24000HZ_MONO_16BIT,
        workspace=os.getenv("DASHSCOPE_WORKSPACE") or None,
    )
    audio = synthesizer.call(text)
    if not audio:
        raise RuntimeError(f"CosyVoice 返回空音频（voice={voice_id}）")

    ffmpeg = resolve_ffmpeg()
    result = subprocess.run(
        [
            ffmpeg,
            "-v",
            "error",
            "-y",
            "-i",
            "pipe:0",
            "-ar",
            str(sample_rate),
            "-ac",
            str(CHANNELS),
            "-c:a",
            "pcm_s16le",
            str(out_path),
        ],
        input=audio,
        capture_output=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg 转码 TTS 音频失败：{result.stderr.decode('utf-8', 'replace')}")


# ---------------------------------------------------------------------------
# 节点主函数
# ---------------------------------------------------------------------------


def tts_align(state: GraphState) -> dict:
    """按说话人音色合成中文口播音频，对齐时间窗并组装整条中文音轨。

    读 `state.reviewed_blocks`（取 `zh_subtitle` 作为合成文本）
    与 `state.segments`（取时间窗和 `speaker_id`）；
    写 `tts/<segment_id>.wav`、`tts/clips.json`、`audio/dub.wav`；
    返回增量 `{"tts_clips": [...]}`。
    """
    reviewed = state.reviewed_blocks
    if not reviewed:
        logger.info("tts_align：reviewed_blocks 为空，跳过")
        return {}

    segments = state.segments
    if not segments:
        raise ValueError("tts_align：缺少 segments，无法确定时间窗")

    by_id = {segment.segment_id: segment for segment in segments}
    speaker_order: list[str] = []
    for item in reviewed:
        segment = by_id.get(item.segment_id)
        if segment is None:
            raise KeyError(f"审校片段 {item.segment_id} 在 segments 中不存在")
        if segment.speaker_id not in speaker_order:
            speaker_order.append(segment.speaker_id)

    plan = load_voice_plan()
    voices = assign_voices(plan, speaker_order)

    clips: list[TTSClip] = []
    placed: list[tuple[int, Path]] = []
    trimmed: list[str] = []

    with tempfile.TemporaryDirectory(prefix="tts_align_", ignore_cleanup_errors=True) as tmp:
        for item in reviewed:
            segment = by_id[item.segment_id]
            window_ms = segment.end_ms - segment.start_ms
            voice_id = voices[segment.speaker_id]

            raw = Path(tmp) / f"{item.segment_id}.raw.wav"
            synthesize_clip(item.zh_subtitle, voice_id, plan.model, plan.sample_rate, raw)

            audio_path = Path(artifact_path("tts_audio", f"{item.segment_id}.wav"))
            if fit_to_window(raw, audio_path, window_ms, plan.sample_rate):
                trimmed.append(item.segment_id)

            clips.append(
                TTSClip(
                    segment_id=item.segment_id,
                    audio_path=audio_path.name,
                    duration_ms=wav_duration_ms(audio_path),
                    text=item.zh_subtitle,
                    voice_id=voice_id,
                    model=plan.model,
                )
            )
            placed.append((segment.start_ms, audio_path))

    write_artifact("tts_clips", clips)

    covered = {clip.segment_id for clip in clips}
    total_ms = max(
        segment.end_ms for segment in segments if segment.segment_id in covered
    )
    assemble_dub(placed, Path(artifact_path("dub_audio")), total_ms, plan.sample_rate)

    if trimmed:
        logger.warning(
            "以下片段加速到 %.2fx 仍超出时间窗，已裁剪到窗内（基本版不含退回分支）：%s",
            MAX_SPEEDUP,
            trimmed,
        )

    return {"tts_clips": clips}
