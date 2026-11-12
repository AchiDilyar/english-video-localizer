"""compose_video 的 mock 实现：结构验证用，不做真实合成。

按 architecture.md 第 11 节查找 FFmpeg：先仓库根 .tools/ffmpeg/bin/ffmpeg，再系统 PATH；
两处都找不到抛 FileNotFoundError，不静默降级。
找到后生成 1 秒黑屏 MP4 占位；FFmpeg 执行失败时原样抛出。
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from utils.paths import artifact_path


def _find_ffmpeg() -> str:
    repo_root = Path(__file__).resolve().parents[2]
    candidate = repo_root / ".tools" / "ffmpeg" / "bin" / "ffmpeg.exe"
    if candidate.is_file():
        return str(candidate)
    found = shutil.which("ffmpeg")
    if found:
        return found
    raise FileNotFoundError(
        "compose_video: 未找到 FFmpeg；请放到仓库根 .tools/ffmpeg/bin/ffmpeg.exe 或加入 PATH"
    )


def compose_video(state) -> dict:
    ffmpeg = _find_ffmpeg()
    output = artifact_path("final_video")
    subprocess.run(
        [
            ffmpeg,
            "-y",
            "-f", "lavfi",
            "-i", "color=black:s=320x240:d=1",
            "-c:v", "libx264",
            "-pix_fmt", "yuv420p",
            "-an",
            output,
        ],
        check=True,
    )
    return {}