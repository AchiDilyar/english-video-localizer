"""Run a credential-free check of the shared development tools."""

import json
import os
import shutil
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory

import imageio_ffmpeg
from dotenv import load_dotenv
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph
from PIL import Image, ImageDraw, ImageFont

CHINESE_FONTS = (
    Path("/System/Library/Fonts/Supplemental/Arial Unicode.ttf"),
    Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
    Path("C:/Windows/Fonts/msyh.ttc"),
)


def check_workflow() -> None:
    builder = StateGraph(dict)
    builder.add_node("check", lambda _state: {"ready": True})
    builder.add_edge(START, "check")
    builder.add_edge("check", END)
    config = {"configurable": {"thread_id": "environment-check"}}
    with SqliteSaver.from_conn_string(":memory:") as saver:
        graph = builder.compile(checkpointer=saver)
        graph.invoke({}, config)
        if graph.get_state(config).values != {"ready": True}:
            raise RuntimeError("Could not read the workflow state from SQLite.")


def check_media(directory: Path) -> None:
    ffmpeg = os.getenv("LOCALIZER_FFMPEG") or imageio_ffmpeg.get_ffmpeg_exe()
    ffprobe = os.getenv("LOCALIZER_FFPROBE") or "ffprobe"
    if not shutil.which(ffprobe):
        raise RuntimeError("Install ffprobe or set LOCALIZER_FFPROBE.")
    configured_font = os.getenv("LOCALIZER_FONT_PATH")
    candidates = (Path(configured_font).expanduser(),) if configured_font else CHINESE_FONTS
    font_path = next((path for path in candidates if path.is_file()), None)
    if font_path is None:
        raise RuntimeError("Set LOCALIZER_FONT_PATH to a Chinese font file.")
    font = ImageFont.truetype(str(font_path), 28)

    cover = Image.new("RGB", (320, 180), "#112537")
    ImageDraw.Draw(cover).text((24, 48), "中文封面", font=font, fill="white")
    cover.save(directory / "cover.jpg")
    with Image.open(directory / "cover.jpg") as saved:
        saved.verify()

    (directory / "sample.srt").write_text(
        "1\n00:00:00,000 --> 00:00:01,000\n中英双语字幕\nBilingual subtitles\n",
        encoding="utf-8",
    )
    fonts = directory / "fonts"
    fonts.mkdir()
    shutil.copyfile(font_path, fonts / font_path.name)
    subprocess.run(
        [
            ffmpeg,
            "-v",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=c=navy:s=320x180:r=24:d=1",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=1",
            "-vf",
            f"subtitles=sample.srt:fontsdir=fonts:force_style='FontName={font.getname()[0]}'",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-shortest",
            "sample.mp4",
        ],
        cwd=directory,
        check=True,
    )
    probe = subprocess.check_output(
        [
            ffprobe,
            "-v",
            "error",
            "-show_entries",
            "stream=codec_type,codec_name",
            "-of",
            "json",
            str(directory / "sample.mp4"),
        ],
        text=True,
    )
    codecs = {stream["codec_type"]: stream["codec_name"] for stream in json.loads(probe)["streams"]}
    if codecs != {"video": "h264", "audio": "aac"}:
        raise RuntimeError(f"Unexpected codecs in the rendered sample: {codecs}")


def main() -> None:
    load_dotenv()
    check_workflow()
    print("OK: LangGraph SQLite checkpoint")
    with TemporaryDirectory() as directory:
        check_media(Path(directory))
    print("OK: Chinese cover, bilingual subtitles, and H.264/AAC export")


if __name__ == "__main__":
    main()
