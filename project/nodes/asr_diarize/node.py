"""Full-video sentence transcription and speaker attribution for the team graph."""
import logging
from pathlib import Path
import wave

from contracts import GraphState, Segment
from pydantic import BaseModel, ConfigDict, Field

from nodes.probe_input import integration, media
from nodes.probe_input.node import inspect_input

logger = logging.getLogger(__name__)
ROOT = Path(__file__).resolve().parents[3]


class ASROptions(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model_dir: str = "models/faster-whisper-base.en"
    max_duration_sec: float = Field(default=7200, gt=0, le=7200)
    audio_recheck: bool = True
    community1_python: str = ""
    community1_cache: str = "models/community-1-hf-cache"
    community1_device: str = Field(default="cpu", pattern="^(cpu|cuda)$")
    num_speakers: int | None = Field(default=None, ge=1, le=32)
    worker_timeout_sec: float = Field(default=7200, gt=0)
    semantic_provider: str = Field(default="none", pattern="^(none|deepseek)$")
    allow_semantic_network: bool = False
    semantic_max_calls: int = Field(default=1, ge=1)


def repository_path(value: str) -> Path:
    path = Path(value).expanduser()
    return path.resolve() if path.is_absolute() else (ROOT / path).resolve()


def prepare_audio(video: Path, audio: Path, info: dict, ffmpeg: str) -> None:
    if not audio.parent.is_dir():
        raise FileNotFoundError("CLI must create audio/ before running the node")
    if audio.exists():
        raise FileExistsError("source_audio exists; use a new work directory")
    if info["video_origin_sec"] is None or info["audio_start_sec"] is None:
        raise ValueError("Cannot establish a reliable full-video audio timeline")
    duration = info["duration_ms"]
    media.run([
        ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin", "-n",
        "-copyts", "-protocol_whitelist", "file,pipe", "-i", str(video),
        "-map", f"0:{info['audio_stream_index']}", "-vn", "-af",
        f"asetpts=PTS-({info['video_origin_sec']})/TB,"
        f"aresample=16000:async=1:first_pts=0,apad,atrim=end_sample={duration * 16}",
        "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le", str(audio),
    ], timeout=600)
    with wave.open(str(audio), "rb") as wav:
        if (wav.getframerate(), wav.getnchannels(), wav.getsampwidth(), wav.getnframes()) != (
            16000, 1, 2, duration * 16
        ):
            raise ValueError("Normalized source_audio has unexpected format or length")


def recognize(audio: Path, duration_ms: int, options: ASROptions) -> dict:
    from .pipeline.sentence_mode import _recognize_sentence, _review

    semantic = {"provider": options.semantic_provider}
    if options.semantic_provider == "deepseek":
        from .pipeline.semantic_review import DeepSeekHTTP

        client = DeepSeekHTTP(
            allow_network=options.allow_semantic_network, max_calls=options.semantic_max_calls
        )
        semantic.update({"allow_network": options.allow_semantic_network,
                         "max_calls": options.semantic_max_calls,
                         "model": client.model, "base_url": client.base_url})
    state = {"job_dir": str(audio.parent), "audio_ref": audio.name,
             "duration_ms": duration_ms, "source_meta": {},
             "request": {"model_dir": str(repository_path(options.model_dir)),
                         "semantic_review": semantic}}
    table = _recognize_sentence(state)["table"]
    if options.audio_recheck:
        import spacy
        from faster_whisper import WhisperModel
        from .pipeline.audio_recheck import recheck_table

        model = WhisperModel(state["request"]["model_dir"], device="cpu", compute_type="int8",
                             cpu_threads=4, local_files_only=True)
        table = recheck_table(table, audio, model, spacy.load("en_core_web_sm", disable=["ner"]),
                              strict_errors=True)
    return _review({"table": table})["table"]


def run_diarization(audio: Path, duration_ms: int, options: ASROptions) -> dict:
    import json
    import subprocess
    import sys
    from .pipeline.common import digest

    worker = Path(__file__).with_name("community1_worker.py")
    python = str(repository_path(options.community1_python)) if options.community1_python else sys.executable
    command = [python, str(worker), "--audio", str(audio), "--result-stdout",
               "--cache-dir", str(repository_path(options.community1_cache)),
               "--device", options.community1_device]
    if options.num_speakers is not None:
        command += ["--num-speakers", str(options.num_speakers)]
    result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8",
                            errors="replace", timeout=options.worker_timeout_sec)
    if result.returncode:
        raise RuntimeError("Community-1 worker failed: " + result.stderr[-3000:])
    data = json.loads(result.stdout)
    if data["metadata"]["audio_sha256"] != digest(audio) or data["metadata"]["duration_ms"] != duration_ms:
        raise ValueError("Community-1 output does not match source_audio")
    previous = 0
    for turn in data["turns"]:
        if not (type(turn["start_ms"]) is int and type(turn["end_ms"]) is int
                and previous <= turn["start_ms"] < turn["end_ms"] <= duration_ms
                and turn["speaker_id"]):
            raise ValueError("Invalid or overlapping exclusive speaker turns")
        previous = turn["end_ms"]
    logger.info("Community-1 completed: groups=%d turns=%d", len(data["speaker_ids"]), len(data["turns"]))
    return data


def to_segments(table: dict) -> list[Segment]:
    from .pipeline.sentence_rules import validate_sentence_table

    errors = validate_sentence_table(table)
    if errors:
        raise ValueError("Invalid sentence timeline: " + "; ".join(errors))
    if table["review"].get("untimed_utterances"):
        raise ValueError("UNTIMED_UTTERANCES: resolve missing phrase timings before team handoff")
    if not table["sentences"]:
        raise ValueError("No usable English sentences detected")
    unresolved = [r["sentence_id"] for r in table["sentences"] if not r["speaker_id"]]
    if unresolved:
        raise ValueError(
            "UNRESOLVED_SPEAKER: shared Segment requires a speaker_id; "
            "confirm the unknown-speaker policy with F/D. Affected sentences: "
            + ", ".join(unresolved[:20])
        )
    mapping = {}
    segments = []
    for i, row in enumerate(table["sentences"], 1):
        speaker = mapping.setdefault(row["speaker_id"], f"spk_{len(mapping) + 1}")
        segments.append(Segment(segment_id=f"seg_{i:04d}", speaker_id=speaker,
                                start_ms=row["start_ms"], end_ms=row["end_ms"], text_en=row["en"]))
    return segments


def asr_diarize(state: GraphState) -> dict:
    options = ASROptions.model_validate(integration.load_config("asr_diarize.toml"))
    video, info, probe_options = inspect_input(state)
    if info["duration_ms"] > options.max_duration_sec * 1000:
        raise ValueError("Video exceeds configured duration limit")
    audio = Path(integration.artifact_path("source_audio"))
    segments_path = Path(integration.artifact_path("segments"))
    if not segments_path.parent.is_dir():
        raise FileNotFoundError("CLI must create segments/ before running the node")
    if segments_path.exists():
        raise FileExistsError("segments already exists; use a new work directory")
    prepare_audio(video, audio, info, media.tool_path("ffmpeg", probe_options.ffmpeg))
    table = recognize(audio, info["duration_ms"], options)
    from .pipeline.diarization import assign_speakers

    table = assign_speakers(table, run_diarization(audio, info["duration_ms"], options))
    segments = to_segments(table)
    integration.write_artifact("segments", segments)
    logger.info("English handoff completed: segments=%d review_items=%d", len(segments),
                sum(bool(r["review_issues"]) for r in table["sentences"]))
    return {"segments": segments}
