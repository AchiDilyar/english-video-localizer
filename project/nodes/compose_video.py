"""Burn the prepared ASS onto the selected video stream and mux the audio."""

import logging
import os
import re
import shutil
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory

from contracts import GraphState
from utils.config import load_config
from utils.paths import artifact_path

from .compose_settings import load_compose_options
from .probe_input.media import choose_stream, probe, tool_path
from .probe_input.node import ProbeOptions, input_path

logger = logging.getLogger(__name__)


def _ffmpeg(override: str | None) -> str:
    candidates = [tool_path("ffmpeg", override)] if override else [
        str(Path(__file__).resolve().parents[2] / ".tools/ffmpeg/bin" /
            ("ffmpeg.exe" if os.name == "nt" else "ffmpeg")),
        shutil.which("ffmpeg"),
    ]
    if not override:
        try:
            from imageio_ffmpeg import get_ffmpeg_exe

            candidates.append(get_ffmpeg_exe())
        except (ImportError, RuntimeError):
            pass
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            filters = subprocess.check_output(
                [candidate, "-hide_banner", "-filters"], text=True, errors="replace"
            )
            if re.search(r"^\s*\S+\s+ass\s+V->V\b", filters, re.MULTILINE):
                return str(Path(candidate).resolve())
    raise RuntimeError("合成视频需要支持 ASS/libass 的 FFmpeg，请检查 FFmpeg 路径。")


def _encode(command: list[str], directory: Path) -> None:
    result = subprocess.run(command, cwd=directory, capture_output=True, text=True, errors="replace")
    if result.returncode:
        raise RuntimeError(f"FFmpeg 合成失败：{result.stderr.strip()[-1500:]}")
    if "failed to find any fallback" in result.stderr or "Glyph" in result.stderr:
        logger.warning("FFmpeg 字体回退信息：%s", result.stderr.strip()[-1500:])


def compose_video(state: GraphState) -> dict:
    source = input_path(state)
    ass = Path(artifact_path("burnin_subtitle"))
    if not ass.is_file() or not ass.stat().st_size:
        raise FileNotFoundError(f"缺少烧录字幕：{ass}")

    options = ProbeOptions.model_validate(load_config("probe_input.toml"))
    ffmpeg = _ffmpeg(options.ffmpeg)
    ffprobe = tool_path("ffprobe", options.ffprobe)
    raw = state.media_info.ffprobe_raw if state.media_info else probe(source, ffprobe)
    video = choose_stream(raw["streams"], "video", options.video_stream)
    audio = choose_stream(raw["streams"], "audio", options.audio_stream)
    dub = Path(artifact_path("dub_audio"))
    use_dub = not load_config("mock.toml").get("tts_align", False)
    if use_dub and (not dub.is_file() or dub.stat().st_size <= 44):
        raise FileNotFoundError(f"缺少真实配音音轨：{dub}")
    if use_dub:
        from .mix_background import select_mix_or_dub
        dub = select_mix_or_dub(state, dub, source)

    output = Path(artifact_path("final_video"))
    duration = state.media_info.duration_ms / 1000 if state.media_info else float(video["duration"])
    settings = load_compose_options()
    source_size = (video["width"], video["height"])
    width, height = settings.output_size(*source_size)
    pixel_format = "yuv420p" if width % 2 == height % 2 == 0 else "yuv444p"
    video_origin = float(video.get("start_time", 0))
    source_bitrate = int(video["bit_rate"]) if str(video.get("bit_rate")).isdigit() else 0
    bitrate = settings.target_bitrate(height, source_bitrate)
    filters = ["setpts=PTS-STARTPTS"]
    if (width, height) != source_size:
        filters.append(f"scale={width}:{height}")
    filters.append("ass=burnin.ass:fontsdir=fonts")
    with TemporaryDirectory(prefix=".compose-", dir=output.parent) as tmp:
        work = Path(tmp)
        shutil.copyfile(ass, work / "burnin.ass")
        fonts = work / "fonts"
        fonts.mkdir()
        for directory in (Path.home() / "Library/Fonts", Path("/Library/Fonts")):
            for font in directory.glob("MiSans-*.ttf"):
                target = fonts / font.name
                if not target.exists():
                    try:
                        os.link(font, target)
                    except OSError:
                        shutil.copyfile(font, target)

        common = [ffmpeg, "-nostdin", "-hide_banner", "-loglevel", "warning", "-y",
                  "-copyts", "-i", str(source)]
        video_args = [
            "-map", f"0:{video['index']}", "-vf", ",".join(filters),
            "-c:v", "libx264", "-preset", "medium", "-pix_fmt", pixel_format,
            "-fps_mode", "passthrough",
        ]
        rate = ["-b:v", str(bitrate), "-passlogfile", "video-pass"] if bitrate else ["-crf", "20"]
        if bitrate:
            _encode(common + video_args + rate + ["-pass", "1", "-an", "-f", "null", os.devnull], work)
            rate += ["-pass", "2"]
        if use_dub:
            common += ["-i", str(dub)]
            audio_map, audio_pts = "1:a:0", "PTS-STARTPTS"
        else:
            audio_map, audio_pts = f"0:{audio['index']}", f"PTS-({video_origin})/TB"
        _encode(
            common + video_args + rate + [
                "-map", audio_map, "-af",
                f"asetpts={audio_pts},aresample=async=1:first_pts=0,apad,atrim=duration={duration:.3f}",
                "-c:a", "aac", "-movflags", "+faststart", "final.mp4",
            ],
            work,
        )
        rendered = work / "final.mp4"
        result = probe(rendered, ffprobe)
        actual = choose_stream(result["streams"], "video").get("bit_rate", "未知")
        rendered.replace(output)
    logger.info("合成完成，分辨率=%dx%d，音轨=%s，源视频码率=%s，目标=%s，实测=%s",
                width, height, "中文配音" if use_dub else "原声",
                source_bitrate or "未知", bitrate or "CRF 20", actual)
    return {}
