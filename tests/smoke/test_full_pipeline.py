"""端到端冒烟测试：前 5 个真实节点 + 后 3 个 mock 节点。

- 进程内调用 CLI（方案 B），覆盖目录创建、set_work_dir、日志初始化与 invoke；
- monkeypatch nodes.translate_blocks._text_model.request_json，禁止真实外部模型调用；
- 断言 final_video 可播放、全部中间产物齐全且合法、mock.toml 配置未漂移。
"""

from __future__ import annotations

import shutil
import subprocess
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
    "asr_diarize": False,
    "build_blocks": False,
    "translate_blocks": False,
    "review_blocks": False,
    "tts_align": True,
    "subtitle_cover": True,
    "compose_video": True,
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


@pytest.mark.slow
def test_full_pipeline_with_mocks(monkeypatch):
    # 1. 准备 work_dir 与输入视频
    assert _INPUT_VIDEO.is_file(), f"测试输入视频不存在: {_INPUT_VIDEO}"
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    work_dir = _TMP_ROOT / f"test_full_pipeline_{timestamp}"
    work_dir.mkdir(parents=True, exist_ok=False)
    shutil.copy2(_INPUT_VIDEO, work_dir / "input.mp4")

    # 2. 断言 mock.toml 未漂移（前 5 真实 + 后 3 mock）
    flags = load_config("mock.toml")
    assert flags == _EXPECTED_MOCK_FLAGS, (
        f"mock.toml 与预期不一致：实际={flags!r}，预期={_EXPECTED_MOCK_FLAGS!r}"
    )

    # 3. patch 外部模型：items 走固定译文，issues 走空列表
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

    # 7. final_video 可播放
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