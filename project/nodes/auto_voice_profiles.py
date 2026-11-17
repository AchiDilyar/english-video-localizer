"""D-private automatic reference preparation; enrollment requires per-task authorization."""

from __future__ import annotations

import hashlib
import json
import logging
import math
import os
import shutil
import tempfile
import wave
from array import array
from pathlib import Path

from .voice_profiles import digest, enroll_profiles, load_profiles

logger = logging.getLogger(__name__)


def _timeline_digest(segments):
    rows = [(s.speaker_id, s.start_ms, s.end_ms) for s in segments]
    return hashlib.sha256(json.dumps(rows, separators=(",", ":")).encode()).hexdigest()


def _reuse_matching_job(path, source_audio, model, region, speakers, account, timeline):
    """Reuse a prior private job record only with exact audio/account/model/region identity."""
    jobs = path.parent.parent.parent
    if path.parent.name != "audio" or jobs.name not in {"jobs", "webui"} or not account:
        return False
    source_hash = digest(source_audio)
    for candidate in jobs.glob("*/audio/voice_profiles.json"):
        if candidate.resolve() == path.resolve():
            continue
        try:
            data = json.loads(candidate.read_text(encoding="utf-8"))
            if (
                data.get("source_sha256"),
                data.get("model"),
                data.get("region"),
                data.get("account_fingerprint"),
                data.get("speaker_timeline_sha256"),
            ) != (source_hash, model, region, account, timeline):
                continue
            if not set(speakers) <= data.get("voices", {}).keys():
                continue
            load_profiles(candidate, source_audio, model, region, speakers)
            shutil.copyfile(candidate, path)
            logger.info("复用当前音频、账号、模型及地域一致的本地音色记录，无需重新创建")
            return True
        except (OSError, ValueError, TypeError, KeyError, AttributeError):
            continue
    return False


def reference_intervals(segments, speakers, *, min_ms=10000, target_ms=15000):
    """Select time-ordered same-speaker intervals, excluding cross-speaker overlaps.

    Sentence-level speaker labels are approximate; no claim of perfect speech isolation.
    Short turns may be joined for one speaker, never padded/repeated to meet minimum length.
    """
    result = {}
    for speaker in speakers:
        if speaker == "spk_unknown":
            raise ValueError("VOICE_REFERENCE_UNCERTAIN: 未确定说话人不能自动复刻")
        spans = []
        for segment in sorted(segments, key=lambda s: s.start_ms):
            if segment.speaker_id != speaker:
                continue
            start, end = segment.start_ms, segment.end_ms
            if end - start < 500:
                continue
            if any(
                other.speaker_id != speaker and other.start_ms < end and other.end_ms > start
                for other in segments
            ):
                continue
            if spans and start <= spans[-1][1]:
                spans[-1][1] = max(end, spans[-1][1])
            else:
                spans.append([start, end])
        # Prefer a continuous sample; otherwise use a deterministic same-speaker compilation.
        continuous = next((span for span in spans if span[1] - span[0] >= min_ms), None)
        candidates = [continuous] if continuous else spans
        selected, total = [], 0
        for start, end in candidates:
            take = min(end - start, target_ms - total)
            if take <= 0:
                break
            selected.append((start, start + take))
            total += take
        if total < min_ms:
            raise ValueError(
                f"VOICE_REFERENCE_TOO_SHORT: {speaker} 可用原声不足10秒，请换较长素材或提供单人参考音频"
            )
        result[speaker] = selected
    return result


def prepare_references(source_audio, segments, speakers, folder):
    intervals = reference_intervals(segments, speakers)
    references = {}
    with wave.open(str(source_audio), "rb") as audio:
        if audio.getnchannels() != 1 or audio.getsampwidth() != 2:
            raise ValueError("原声参考需使用 B 提供的单声道 PCM16 音频")
        rate = audio.getframerate()
        duration_ms = audio.getnframes() * 1000 / rate
        for index, speaker in enumerate(speakers):
            pcm = bytearray()
            for start, end in intervals[speaker]:
                if not 0 <= start < end <= duration_ms + 1:
                    raise ValueError("音色参考时间超出原声范围")
                audio.setpos(round(start * rate / 1000))
                pcm.extend(audio.readframes(round((end - start) * rate / 1000)))
            samples = array("h", pcm)
            rms = math.sqrt(sum(value * value for value in samples) / max(1, len(samples))) / 32768
            clipped = sum(abs(value) >= 32760 for value in samples) / max(1, len(samples))
            if rms < 0.003 or clipped > 0.01:
                raise ValueError(
                    f"VOICE_REFERENCE_QUALITY: {speaker} 原声过静或严重削波，请提供更清晰的单人原声"
                )
            reference = Path(folder) / f"reference-{index:03d}.wav"
            with wave.open(str(reference), "wb") as output:
                output.setnchannels(1)
                output.setsampwidth(2)
                output.setframerate(rate)
                output.writeframes(pcm)
            references[speaker] = reference
    return references


def ensure_profiles(
    path, source_audio, segments, speakers, *, model, region, authorized=False, client_factory=None
):
    path = Path(path)
    key = os.getenv("DASHSCOPE_API_KEY", "").strip()
    account = hashlib.sha256(key.encode()).hexdigest() if key else ""
    timeline = _timeline_digest(segments)
    if not path.exists() and authorized:
        _reuse_matching_job(path, source_audio, model, region, speakers, account, timeline)
    missing = list(speakers)
    if path.is_file():
        # Validate existing voices/source before considering any additional enrollment.
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("account_fingerprint") and data["account_fingerprint"] != account:
            raise ValueError("音色记录所属配音账号已变化，请使用匹配账号或新任务")
        if data.get("speaker_timeline_sha256") and data["speaker_timeline_sha256"] != timeline:
            raise ValueError("说话人时间轴已变化，请勿沿用旧人物映射的音色记录")
        if (data.get("source_sha256"), data.get("model"), data.get("region")) != (
            digest(source_audio),
            model,
            region,
        ):
            raise ValueError("复刻音色与本视频、模型或地域不匹配，请勿复制其他任务的音色记录")
        missing = [speaker for speaker in speakers if speaker not in data.get("voices", {})]
        if not missing:
            return load_profiles(path, source_audio, model, region, speakers)
    if not authorized:
        raise PermissionError(
            "VOICE_CLONE_AUTHORIZATION_REQUIRED: 当前任务缺少音色记录。请在 WebUI 勾选已获说话人授权并允许上传参考原声、创建音色，或使用系统音色。"
        )
    # All samples are checked before entering the paid enrollment helper. No auto retries.
    with tempfile.TemporaryDirectory(prefix=".voice-reference-", dir=path.parent) as temporary:
        references = prepare_references(source_audio, segments, missing, temporary)
        logger.info(
            "正在为 %d 位说话人自动准备复刻音色；仅上传本任务已授权的参考原声", len(missing)
        )
        enroll_profiles(
            source_audio,
            references,
            path,
            model=model,
            region=region,
            authorized=True,
            allow_network=True,
            client_factory=client_factory,
        )
    data = json.loads(path.read_text(encoding="utf-8"))
    data["account_fingerprint"] = account
    data["speaker_timeline_sha256"] = timeline
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return load_profiles(path, source_audio, model, region, speakers)
