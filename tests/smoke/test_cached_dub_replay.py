"""Opt-in F-main-graph replay from a failed local job; forbids paid generation.

LOCALIZER_REPLAY_JOB identifies an existing authorized job. B/C results and
existing Chinese voice clips are reused; D timing, E local ASR, pagination,
mixing and composition execute again. Exhaustion is simulated at zero rounds.
"""

import copy
import importlib
import json
import os
import shutil
from dataclasses import replace
from pathlib import Path
from time import perf_counter

import pytest
from contracts import EnvironmentAudio, GraphState, Segment, TranslatedSegment
from graph import builder, registry
from nodes.natural_dubbing import raw_cache_path, synthesize_groups
from nodes.probe_input.media import probe, tool_path
from nodes.translate_blocks._deepseek import DeepSeekError
from nodes.tts_align import assemble_dub, fit_to_window, load_voice_plan, wav_duration_ms
from utils.io import write_artifact
from utils.paths import artifact_path, set_work_dir


@pytest.mark.slow
def test_cached_job_through_f_main_graph(tmp_path, monkeypatch):
    original = os.getenv("LOCALIZER_REPLAY_JOB")
    if not original:
        pytest.skip("Set LOCALIZER_REPLAY_JOB to opt in; never starts a paid generation")
    job = Path(original).resolve()
    started = perf_counter()
    for name in ("audio", "segments", "translated", "tts", "subtitles", "video", "logs"):
        (tmp_path / name).mkdir()
    set_work_dir(str(tmp_path))
    metadata = json.loads((job / "web-run.json").read_text(encoding="utf-8"))
    source = Path(metadata.get("source_video") or job / "input.mp4")
    segments = [
        Segment.model_validate(x)
        for x in json.loads((job / "segments/segments.json").read_text(encoding="utf-8"))
    ]
    reviewed_file = job / "translated/repaired_blocks.json"
    if not reviewed_file.exists():
        reviewed_file = job / "translated/reviewed_blocks.json"
    reviewed = [
        TranslatedSegment.model_validate(x)
        for x in json.loads(reviewed_file.read_text(encoding="utf-8"))
    ]
    groups = json.loads((job / "tts/dubbing_script.json").read_text(encoding="utf-8"))
    ledger = json.loads((job / "tts/duration_repair_requests.json").read_text(encoding="utf-8"))
    profiles = json.loads((job / "audio/voice_profiles.json").read_text(encoding="utf-8"))
    voices = {k: v["voice_id"] for k, v in profiles["voices"].items()}
    plan = replace(
        load_voice_plan(),
        duration_repair_attempts=0,
        duration_exhaustion_policy="use_latest",
        source_expression=False,
        source_pacing=False,
    )
    cached = {}
    for group in groups:
        fitted = job / "tts" / f"{group['group_id']}.wav"
        if fitted.exists():
            records = [r for r in ledger.values() if r.get("group_id") == group["group_id"]]
            if len(records) > 1:
                raise ValueError("Ambiguous cached script lineage; do not guess spoken text")
            if records and records[0].get("revised_text"):
                group["text"] = records[0]["revised_text"]
            raw = fitted
        else:
            # The failed last group's synthesis may exist before scheduling failed.
            item = copy.deepcopy(group)
            item["conditioning"] = {**item.get("conditioning", {}), "rate": 1.0}
            prior = raw_cache_path(item, voices[group["speaker_id"]], plan)
            raw = job / "tts" / prior.name
        if not raw.is_file():
            raise FileNotFoundError("Missing cached audio; replay refuses paid synthesis")
        copied = tmp_path / "tts" / f"replay_{group['group_id']}.raw.wav"
        shutil.copyfile(raw, copied)
        cached[group["group_id"]] = copied

    natural = importlib.import_module("nodes.natural_dubbing")
    monkeypatch.setattr(natural, "prepare_script", lambda _: copy.deepcopy(groups))

    def cached_audio(group, text, *args):
        assert text == next(g["text"] for g in groups if g["group_id"] == group["group_id"])
        path = cached[group["group_id"]]
        return path, wav_duration_ms(path)

    monkeypatch.setattr("nodes.source_pacing.prepare_paced_audio", cached_audio)

    def no_paid_generation(*args, **kwargs):
        raise AssertionError("Paid generation is forbidden in offline replay")

    def semantic_unavailable(**kwargs):
        raise DeepSeekError("offline replay: use local display fallback")

    monkeypatch.setattr("nodes.translate_blocks._text_model.request_json", semantic_unavailable)
    nodes = registry.resolve_nodes()
    nodes["asr_diarize"] = lambda _: {"segments": segments}
    nodes["build_blocks"] = lambda _: {}
    nodes["translate_blocks"] = lambda _: {}
    nodes["review_blocks"] = lambda _: {"reviewed_blocks": reviewed}
    nodes["repair_blocks"] = lambda _: {}

    def cached_environment(_):
        shutil.copyfile(job / "audio/environment.wav", artifact_path("environment_bed"))
        receipt = EnvironmentAudio.model_validate_json(
            (job / "audio/environment.source.json").read_text(encoding="utf-8")
        )
        write_artifact("environment_audio", receipt)
        return {"environment_audio": receipt}

    nodes["b_environment"] = cached_environment
    nodes["tts_align"] = lambda state: synthesize_groups(
        state, plan, voices, no_paid_generation, fit_to_window, wav_duration_ms, assemble_dub
    )
    monkeypatch.setattr(builder, "resolve_nodes", lambda: nodes)
    final_state = GraphState.model_validate(
        builder.build_graph().invoke(GraphState(input_video=str(source)), {"recursion_limit": 100})
    )
    assert final_state.mixed_audio is not None
    final = Path(artifact_path("final_video"))
    assert final.stat().st_size > 1000
    actual = float(probe(final, tool_path("ffprobe", None))["format"]["duration"])
    assert abs(actual - final_state.media_info.duration_ms / 1000) < 0.1
    report = {
        "paid_api_calls": 0,
        "reused_source_groups": len(groups),
        "simulated_exhaustion_rounds": 0,
        "real_local_subtitle_asr": True,
        "real_ffmpeg_fit_mix_compose": True,
        "duration_sec": actual,
        "final_video": str(final),
        "elapsed_sec": perf_counter() - started,
        "human_audition_confirmed": False,
    }
    (tmp_path / "replay-validation.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
