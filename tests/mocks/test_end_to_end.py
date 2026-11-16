"""全 mock 端到端测试：patch 开启全部 mock 节点，经 CLI 跑完整链路。

运行：
    uv run pytest tests/mocks/test_end_to_end.py -q

与 tests/smoke/test_full_pipeline.py 的区别：那条是「前 5 真实 + D 真实 + 后 2 mock」，
本测试是「9 个节点全部 mock」，因此不需要 patch 任何外部模型或 SDK。

工作目录固定为 tests/tmp/mocks/end_to_end/all_mock/，每次用例前清空。
"""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
import wave
from pathlib import Path

import pytest

import cli
import utils.paths
from graph import registry
from utils.io import read_artifact
from utils.paths import artifact_path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEMO_VIDEO = _REPO_ROOT / "tests" / "data" / "asr_diarize" / "real_dialogue" / "input.mp4"
_PROBE_SNAPSHOT = _REPO_ROOT / "project" / "mocks" / "data" / "probe_input.json"
_WORK_DIR = _REPO_ROOT / "tests" / "tmp" / "mocks" / "end_to_end" / "all_mock"

# 演示视频走完整 mock 链路时不应触发的告警标记。
_FORBIDDEN_MARKERS = (
    "[指纹不符]",
    "[覆盖不符]",
    "[未覆盖]",
    "[单块过大]",
    "[丢弃",
    "[空结果]",
    "[译文缺失]",
    "[blocks 为空]",
    "[segments 为空]",
    "[translated_blocks 为空]",
    "[reviewed_blocks 为空]",
)


@pytest.fixture(autouse=True)
def _restore_logging():
    """抵消 setup_logging 对 root logger 的修改，避免污染其他用例。"""
    root = logging.getLogger()
    saved_handlers = root.handlers[:]
    saved_level = root.level
    try:
        yield
    finally:
        root.handlers[:] = saved_handlers
        root.setLevel(saved_level)


def _find_tool(name: str) -> str | None:
    """按 architecture.md 第 11 节：.tools 优先，PATH 其次。"""
    candidate = _REPO_ROOT / ".tools" / "ffmpeg" / "bin" / f"{name}.exe"
    if candidate.is_file():
        return str(candidate)
    return shutil.which(name)


@pytest.mark.slow
def test_all_mock_pipeline_via_cli(monkeypatch, capsys):
    if _find_tool("ffmpeg") is None or _find_tool("ffprobe") is None:
        pytest.skip("缺少 ffmpeg/ffprobe，无法跑全 mock 端到端")

    assert _DEMO_VIDEO.is_file(), f"演示视频不存在: {_DEMO_VIDEO}"
    if _WORK_DIR.exists():
        shutil.rmtree(_WORK_DIR)
    _WORK_DIR.mkdir(parents=True)
    shutil.copyfile(_DEMO_VIDEO, _WORK_DIR / "input.mp4")

    monkeypatch.setattr(utils.paths, "_work_dir", None)
    monkeypatch.setattr(
        registry,
        "load_config",
        lambda filename: {name: True for name in registry.NODE_NAMES},
    )

    exit_code = cli.main(["--work-dir", str(_WORK_DIR), "--input", "input.mp4"])

    assert exit_code == 0
    assert "成片已生成" in capsys.readouterr().out

    # 1. 结构化 JSON 产物可反读（read_artifact 内部做 Pydantic 校验）
    segments = read_artifact("segments")
    blocks = read_artifact("blocks")
    translated = read_artifact("translated_blocks")
    reviewed = read_artifact("reviewed_blocks")
    tts_clips = read_artifact("tts_clips")

    # 2. 数量与 ID 一致性
    assert segments, "segments 为空"
    assert len(blocks) == 1, f"build_blocks mock 应输出单块，实际 {len(blocks)}"
    assert len(translated) == len(segments)
    assert len(reviewed) == len(segments)
    assert len(tts_clips) == len(reviewed)

    segment_ids = {segment.segment_id for segment in segments}
    assert {item.segment_id for item in translated} == segment_ids
    assert {item.segment_id for item in reviewed} == segment_ids
    assert [clip.segment_id for clip in tts_clips] == [
        item.segment_id for item in reviewed
    ]

    block_ids = [sid for block in blocks for sid in block.segment_ids]
    assert len(block_ids) == len(segments), "翻译块必须恰好覆盖每个分段一次"
    assert set(block_ids) == segment_ids

    # 3. 二进制/文本产物存在且非空
    for name in (
        "source_audio",
        "dub_audio",
        "bilingual_srt",
        "burnin_subtitle",
        "final_video",
    ):
        path = Path(artifact_path(name))
        assert path.is_file(), f"缺少产物 {name}: {path}"
        assert path.stat().st_size > 0, f"产物为空 {name}: {path}"

    for clip in tts_clips:
        path = Path(artifact_path("tts_audio", clip.audio_path))
        assert path.is_file(), f"缺少分段音频: {path}"
        assert path.stat().st_size > 0, f"分段音频为空: {path}"

    # 4. mock 写出的 WAV 规格
    #    source_audio：asr_diarize mock，16kHz，帧数 = duration_ms × 16
    #    dub_audio   ：tts_align mock，24kHz，帧数 = 已覆盖分段 max(end_ms) × 24
    duration_ms = json.loads(_PROBE_SNAPSHOT.read_text(encoding="utf-8"))["duration_ms"]
    with wave.open(artifact_path("source_audio"), "rb") as handle:
        assert (
            handle.getframerate(),
            handle.getnchannels(),
            handle.getsampwidth(),
        ) == (16000, 1, 2), "source_audio WAV 规格不符"
        assert handle.getnframes() == duration_ms * 16, (
            f"source_audio 帧数 {handle.getnframes()} 应为 duration_ms×16 = {duration_ms * 16}"
        )

    max_end_ms = max(segment.end_ms for segment in segments)
    with wave.open(artifact_path("dub_audio"), "rb") as handle:
        assert (
            handle.getframerate(),
            handle.getnchannels(),
            handle.getsampwidth(),
        ) == (24000, 1, 2), "dub_audio WAV 规格不符"
        assert handle.getnframes() == max_end_ms * 24, (
            f"dub_audio 帧数 {handle.getnframes()} 应为 max(end_ms)×24 = {max_end_ms * 24}"
        )

    segments_by_id = {segment.segment_id: segment for segment in segments}
    for clip in tts_clips:
        window_ms = (
            segments_by_id[clip.segment_id].end_ms
            - segments_by_id[clip.segment_id].start_ms
        )
        assert clip.duration_ms == window_ms, (
            f"{clip.segment_id} duration_ms={clip.duration_ms} 应为时间窗 {window_ms}ms"
        )
        with wave.open(artifact_path("tts_audio", clip.audio_path), "rb") as handle:
            assert (
                handle.getframerate(),
                handle.getnchannels(),
                handle.getsampwidth(),
            ) == (24000, 1, 2), f"{clip.segment_id} 分段音频规格不符"
            assert handle.getnframes() == window_ms * 24, (
                f"{clip.segment_id} 帧数 {handle.getnframes()} 应为时间窗×24 = {window_ms * 24}"
            )

    # 5. final_video 可被 ffprobe 解析出 h264 视频流
    ffprobe = _find_tool("ffprobe")
    completed = subprocess.run(
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
    assert completed.returncode == 0, f"ffprobe 失败: {completed.stderr}"
    assert "codec_name=h264" in completed.stdout

    # 6. repair_blocks 为增量空实现，不产生 repaired_blocks.json
    assert not Path(artifact_path("repaired_blocks")).exists()

    # 7. 日志：非空、无 traceback、无任何 mock 告警
    log_text = (_WORK_DIR / "logs" / "run.log").read_text(
        encoding="utf-8", errors="replace"
    )
    assert log_text.strip(), "run.log 为空"
    assert "Traceback" not in log_text, "成功路径不应出现 traceback"
    for marker in _FORBIDDEN_MARKERS:
        assert marker not in log_text, f"全 mock 链路不应出现告警标记 {marker}"
