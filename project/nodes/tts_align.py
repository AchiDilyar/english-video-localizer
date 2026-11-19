"""按说话人音色合成中文口播音频，对齐原时间窗，组装整条中文配音音轨。

事实源对应：
- `workflow.md` 第 3 节 `tts_align`：读审校结果，写分段音频清单、分段音频文件、中文配音音轨；
- `dataflow.md` 第 3 节产物表（`tts_clips` / `tts_audio` / `dub_audio`）与第 4 节工作目录结构；
- `architecture.md` 第 3 节节点签名、第 5 节配置加载、第 6 节通用函数、第 9 节测试与日志。

按用户指定的实验策略：原开始时间为下限，连续组可按配置小幅向后顺延，再按实际时长比例变速；
保留整段语音，不以裁掉句尾处理超时，不新增任何状态字段。

本节点不创建任何目录（`dataflow.md` 第 4 节），目录由 CLI 在初始化时创建。
"""
from __future__ import annotations

import logging
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import time
import wave
from dataclasses import dataclass, field
from functools import partial
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
    voice_mode: str = 'system'
    max_speedup: float = 1.35
    natural_groups: bool = False
    max_forward_delay_ms: int = 0
    min_speed: float = 1.0
    min_speech_fill_ratio: float = 0.0
    min_slowdown_window_ms: int = 1000
    duration_repair_attempts: int = 0
    duration_exhaustion_policy: str = 'error'
    short_duration_policy: str = 'error'
    source_expression: bool = False
    source_pacing: bool = False
    shortfall_tolerance_ms: int = 0


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
    mode=config.get('voice_mode','system')
    if mode not in {'system','cloned'}:raise ValueError('voice_mode 只能是 system 或 cloned')
    max_speedup=float(config.get('max_speedup',1.35))
    if not 1<=max_speedup<=2:raise ValueError('max_speedup 必须在 1–2 之间')
    natural_groups=config.get('natural_groups',False)
    if type(natural_groups) is not bool:raise ValueError('natural_groups 必须是布尔值')
    forward_delay=config.get('max_forward_delay_ms',0)
    if type(forward_delay) is not int or not 0<=forward_delay<=2000:
        raise ValueError('max_forward_delay_ms 必须为 0–2000 之间的整数毫秒')
    min_speed=float(config.get('min_speed',1.0));fill=float(config.get('min_speech_fill_ratio',0.0))
    if not .5<=min_speed<=1:raise ValueError('min_speed 必须在 0.5–1.0 之间')
    if not 0<=fill<=1:raise ValueError('min_speech_fill_ratio 必须在 0–1 之间')
    attempts=config.get('duration_repair_attempts',0);min_window=config.get('min_slowdown_window_ms',1000)
    short_policy=config.get('short_duration_policy','error')
    shortfall_tolerance=config.get('shortfall_tolerance_ms',0)
    if type(shortfall_tolerance) is not int or not 0<=shortfall_tolerance<=1000:raise ValueError('shortfall_tolerance_ms 必须为0–1000整数')
    source_expression=config.get('source_expression',False)
    source_pacing=config.get('source_pacing',False)
    if type(source_pacing) is not bool:raise ValueError('source_pacing 必须为布尔值')
    if type(source_expression) is not bool:raise ValueError('source_expression 必须为布尔值')
    if short_policy not in {'error','warn'}:raise ValueError('short_duration_policy 必须为 error 或 warn')
    if type(attempts) is not int or not 0<=attempts<=8:raise ValueError('duration_repair_attempts 必须为 0–8')
    exhaustion=config.get('duration_exhaustion_policy','error')
    if exhaustion not in {'error','use_best','use_latest'}:raise ValueError('duration_exhaustion_policy 必须为 error、use_best 或 use_latest')
    if type(min_window) is not int or min_window<0:raise ValueError('min_slowdown_window_ms 必须为非负整数')
    return VoicePlan(
        model=str(config.get("model", DEFAULT_MODEL)),
        sample_rate=sample_rate,
        voice_pool=tuple(str(voice) for voice in voices),
        fallback_voice=str(config.get("fallback_voice", DEFAULT_VOICE)),
        unknown_speaker=str(config.get("unknown_speaker", DEFAULT_UNKNOWN_SPEAKER)),
        overrides={str(k): str(v) for k, v in overrides.items()},
        voice_mode=mode,max_speedup=max_speedup,natural_groups=natural_groups,max_forward_delay_ms=forward_delay,
        min_speed=min_speed,min_speech_fill_ratio=fill,min_slowdown_window_ms=min_window,duration_repair_attempts=attempts,duration_exhaustion_policy=exhaustion,
        short_duration_policy=short_policy,
        source_expression=source_expression,
        source_pacing=source_pacing,
        shortfall_tolerance_ms=shortfall_tolerance,
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
    1. 仓库根 `.tools/ffmpeg/bin/ffmpeg`（Windows 使用 `ffmpeg.exe`）；
    2. 系统 `PATH`。

    两处都找不到时抛出 `FileNotFoundError`，按节点失败处理，不静默降级。
    """
    filename = "ffmpeg.exe" if os.name == "nt" else "ffmpeg"
    candidate = _REPO_ROOT / ".tools" / "ffmpeg" / "bin" / filename
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


def fit_to_window(src: Path, dst: Path, window_ms: int, sample_rate: int, *, max_speedup=None,min_speed=1.0,distribute_pause_padding=False) -> bool:
    """Fit complete speech with bounded tempo, then pad residue; never crop speech.

    Returns False for compatibility with the former trimming flag. Excessive
    speed is warned about, rather than silently dropping words.
    """
    if window_ms <= 0:
        raise ValueError(f"时间窗必须为正，收到 {window_ms}ms")
    if not .5<=min_speed<=1:raise ValueError('放慢下限必须在 0.5–1.0 之间')
    source_ms = wav_duration_ms(src)
    if source_ms <= 0:
        raise ValueError("合成音频没有有效时长")
    speed = max(1.0, source_ms / max(1, window_ms - min(30, window_ms * .05))) if source_ms > window_ms else 1.0
    if source_ms<window_ms:speed=max(min_speed,source_ms/window_ms)
    if max_speedup is not None:
        if source_ms/window_ms>max_speedup:
            raise ValueError('TTS_TEXT_TOO_LONG: 请精简译文，不能超过设定语速')
        speed=min(speed,max_speedup)
    ffmpeg = resolve_ffmpeg()

    def encode(target, filters, limit=None):
        command = [ffmpeg, '-v', 'error', '-y', '-i', str(src), '-af', ','.join(filters),
                   '-ar', str(sample_rate), '-ac', str(CHANNELS), '-c:a', 'pcm_s16le']
        if limit is not None:
            command += ['-t', f'{limit / 1000:.3f}']
        command += [str(target)]
        result = subprocess.run(command, capture_output=True)
        if result.returncode:
            raise RuntimeError('ffmpeg 配音变速失败：' + result.stderr.decode('utf-8', errors='replace')[-1000:])

    with tempfile.TemporaryDirectory(prefix='dub_fit_') as folder:
        compressed = Path(folder) / 'complete.wav'
        for _ in range(3):
            remaining = speed
            filters = []
            while remaining > 2.0:
                filters.append('atempo=2.0')
                remaining /= 2.0
            filters.append(f'atempo={remaining:.9f}')
            encode(compressed, filters)
            actual = wav_duration_ms(compressed)
            if actual <= window_ms:
                break
            speed *= actual / window_ms * 1.02
            if max_speedup is not None and speed>max_speedup:
                raise ValueError('TTS_TEXT_TOO_LONG: 编码测时后仍需过高语速，请精简译文')
        else:
            raise RuntimeError('完整配音仍无法放入时间窗，拒绝截断句尾')
        pause_receipt={'distributed_pause_ms':0,'pause_insertions':[]}
        if distribute_pause_padding and window_ms-actual>250:
            from .pause_padding import distribute
            pause_receipt=distribute(compressed,window_ms)
            actual=wav_duration_ms(compressed)
        # This time limit can only remove padding: the entire compressed speech
        # has already been measured and fits inside the requested window.
        result = subprocess.run([ffmpeg, '-v', 'error', '-y', '-i', str(compressed),
            '-af', 'apad', '-t', f'{window_ms / 1000:.3f}', '-ar', str(sample_rate),
            '-ac', str(CHANNELS), '-c:a', 'pcm_s16le', str(dst)], capture_output=True)
        if result.returncode:
            raise RuntimeError('配音补齐时间窗失败')
    if speed > 1.5:
        logger.warning('配音需要 %.3fx 加速，可懂度需人工核对；source=%dms window=%dms', speed, source_ms, window_ms)
    Path(dst).with_suffix('.speed.json').write_text(json.dumps({'tempo':speed,'source_ms':source_ms,
        'window_ms':window_ms,'min_speed':min_speed,'measured_stretched_audio_ms':actual,
        'trailing_padding_ms':max(0,window_ms-actual),**pause_receipt,'method':'ffmpeg_atempo_complete_audio_measured'}),encoding='utf-8')
    return False

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

def connect_tts_socket(url, headers, *, read_timeout):
    import websocket

    for attempt in range(1, 4):
        try:
            connection = websocket.create_connection(url, header=headers, timeout=10)
        except (TimeoutError, ConnectionResetError, websocket.WebSocketTimeoutException) as error:
            if attempt == 3:
                raise RuntimeError("连接 DashScope 配音服务失败，3 次 WebSocket 建连均未成功。") from error
            logger.warning("DashScope 配音 WebSocket 第 %s 次建连失败，正在重试。", attempt)
            time.sleep(0.5 * attempt)
        else:
            connection.settimeout(read_timeout)
            return connection


def synthesize_clip(
    text: str, voice_id: str, model: str, sample_rate: int, out_path: Path, *, conditioning=None
) -> None:
    """调用 DashScope CosyVoice 合成一段中文口播，写成目标规格的 WAV。

    使用官方推荐的 v2 SDK 接口 `Client(...).audio.tts.synthesize(...)`；
    旧版 `dashscope.audio.tts_v2.SpeechSynthesizer` 在 SDK 中已归入 `legacy_1x`。

    环境变量：
    - `DASHSCOPE_API_KEY`：必需，从本机环境变量或 `.env` 加载
    - `DASHSCOPE_WORKSPACE`：业务空间 ID，仅子业务空间或使用专属域名时需要
    - `DASHSCOPE_REGION`：默认 `cn-beijing`；API Key 与地域绑定，不可跨地域混用

    合成请求要 wav 24kHz 单声道：CosyVoice 原生 24kHz，直接拿无损音频，
    避免默认 mp3 的编解码损耗；后续仍由 ffmpeg 统一转成目标规格。
    """
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parents[2] / ".env")
    api_key = os.getenv("DASHSCOPE_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("缺少 DASHSCOPE_API_KEY，无法合成中文配音")

    import dashscope

    from .usage_budget import reserve
    reserve('tts_characters',len(text),f'{model}:{len(text)}chars')

    client = dashscope.Client(
        api_key=api_key,
        workspace=os.getenv("DASHSCOPE_WORKSPACE") or None,
        region=os.getenv("DASHSCOPE_REGION", "cn-beijing"),
    )
    chunks=[];sentences={};started=time.perf_counter()
    parameters={'word_timestamp_enabled':True}
    if conditioning:parameters.update({k:conditioning[k] for k in ['instruction','language_hints','rate'] if k in conditioning})
    with client.audio.tts.connect(model=model,voice=voice_id,format='wav',sample_rate=sample_rate,
                                  parameters=parameters,
                                  connector=partial(connect_tts_socket, read_timeout=client.config.timeout)) as session:
        session.send_text(text)
        session.stop()
        for event in session.events():
            if isinstance(event,bytes):chunks.append(event)
            else:
                output=(event.get('payload') or {}).get('output') or {}
                sentence=output.get('sentence') or {}
                if sentence.get('words'):
                    sentences[sentence['index']]={'text':output.get('original_text','') or sentences.get(sentence['index'],{}).get('text',''),
                                                   'words':sentence['words']}
        usage=getattr(session,'usage',None)
        first_package_delay_ms=getattr(session,'first_package_delay',None)
    elapsed_sec=time.perf_counter()-started
    audio=b''.join(chunks)
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
    Path(out_path).with_suffix('.timing.json').write_text(
        json.dumps({'sentences':[sentences[k] for k in sorted(sentences)],'usage':usage,
                    'elapsed_sec':elapsed_sec,'first_package_delay_ms':first_package_delay_ms,
                    'submitted_characters':len(text),'model':model,'conditioning':conditioning,
                    'region':os.getenv('DASHSCOPE_REGION','cn-beijing')},ensure_ascii=False,indent=2),encoding='utf-8')


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
    # Optional incremental repair: preserve the base path when repair returned {}.
    if state.repaired_blocks:
        state=state.model_copy(update={'reviewed_blocks':state.repaired_blocks})
    reviewed = state.reviewed_blocks
    if not reviewed:
        logger.info("tts_align：reviewed_blocks 为空，跳过")
        return {}

    segments = state.segments
    if not segments:
        raise ValueError("tts_align：缺少 segments，无法确定时间窗")

    by_id = {segment.segment_id: segment for segment in segments}
    from .dubbing_timing import forward_windows
    duration_ms = state.media_info.duration_ms if state.media_info else max(s.end_ms for s in segments)
    windows = forward_windows(segments, duration_ms)
    speaker_order: list[str] = []
    for item in reviewed:
        segment = by_id.get(item.segment_id)
        if segment is None:
            raise KeyError(f"审校片段 {item.segment_id} 在 segments 中不存在")
        if segment.speaker_id not in speaker_order:
            speaker_order.append(segment.speaker_id)

    plan = load_voice_plan()
    from .dubbing_timing import DubbingPolicy, reserve_end_limits, schedule_segment
    policy=DubbingPolicy.from_plan(plan)
    if plan.natural_groups:
        from .natural_dubbing import make_groups
        reserve_end_limits(make_groups(state),duration_ms,policy)
    if plan.voice_mode=='cloned':
        from .auto_voice_profiles import ensure_profiles
        from dotenv import load_dotenv
        load_dotenv(_REPO_ROOT/'.env')
        audio=Path(artifact_path('source_audio'))
        voices=ensure_profiles(audio.with_name('voice_profiles.json'),audio,segments,speaker_order,
                               model=plan.model,region=os.getenv('DASHSCOPE_REGION','cn-beijing'),
                               authorized=os.getenv('LOCALIZER_AUTHORIZE_VOICE_CLONE')=='1')
    else:
        voices = assign_voices(plan, speaker_order)

    if plan.natural_groups:
        from .natural_dubbing import synthesize_groups
        return synthesize_groups(state,plan,voices,synthesize_clip,fit_to_window,wav_duration_ms,assemble_dub)

    clips: list[TTSClip] = []
    placed: list[tuple[int, Path]] = []
    alignment_records = []

    with tempfile.TemporaryDirectory(prefix="tts_align_", ignore_cleanup_errors=True) as tmp:
        for item in reviewed:
            segment = by_id[item.segment_id]
            window_ms = segment.end_ms - segment.start_ms
            voice_id = voices[segment.speaker_id]

            from .duration_repair import measure_with_repair
            # Consume only the following gap needed by this utterance. Never
            # move its start or borrow time from before it / the next sentence.
            available_ms = windows[segment.segment_id][1] - segment.start_ms
            group={'group_id':item.segment_id,'text':item.zh_subtitle,'start_ms':segment.start_ms,
                   'original_end_ms':segment.end_ms,'available_duration_ms':available_ms,
                   'source':[{'segment_id':segment.segment_id,'text_en':segment.text_en,'zh_subtitle':item.zh_subtitle}]}
            def prepare(text):
                tag=hashlib.sha256(text.encode()).hexdigest()[:16]
                raw=Path(tmp)/f'{item.segment_id}_{tag}.raw.wav'
                if not raw.exists():synthesize_clip(text,voice_id,plan.model,plan.sample_rate,raw)
                return raw,wav_duration_ms(raw)
            def schedule(ms):
                return schedule_segment(group,ms,policy)
            audio_path=Path(artifact_path('tts_audio',f'{item.segment_id}.wav'))
            def finalize(raw,position):
                fit_to_window(raw,audio_path,position[1],plan.sample_rate,max_speedup=policy.speed_cap(group),min_speed=policy.min_speed)
                return json.loads(audio_path.with_suffix('.speed.json').read_text(encoding='utf-8'))
            raw,raw_ms,(_,window_ms)=measure_with_repair(group,plan,prepare,schedule,
                {'voice':voice_id,'model':plan.model,'sample_rate':plan.sample_rate},finalize)
            alignment_records.append({'segment_id':segment.segment_id,
                'start_ms':segment.start_ms,'original_end_ms':segment.end_ms,
                'display_end_ms':segment.start_ms+window_ms,'available_end_ms':windows[segment.segment_id][1],
                'raw_duration_ms':raw_ms,'window_ms':window_ms,
                'nominal_speed_ratio':raw_ms/window_ms,'speech_trimmed':False})


            clips.append(
                TTSClip(
                    segment_id=item.segment_id,
                    audio_path=audio_path.name,
                    duration_ms=wav_duration_ms(audio_path),
                    text=group['text'],
                    voice_id=voice_id,
                    model=plan.model,
                )
            )
            placed.append((segment.start_ms, audio_path))

    write_artifact("tts_clips", clips)
    Path(artifact_path('tts_audio', 'alignment_report.json')).write_text(
        json.dumps(alignment_records,ensure_ascii=False,indent=2),encoding='utf-8')

    total_ms = max(
        by_id[clip.segment_id].start_ms + clip.duration_ms for clip in clips
    )
    assemble_dub(placed, Path(artifact_path("dub_audio")), total_ms, plan.sample_rate)

    return {"tts_clips": clips}
