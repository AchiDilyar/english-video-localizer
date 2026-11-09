"""Exercise the B file boundary and actual E media rendering without model calls."""

import subprocess
from pathlib import Path
from zipfile import ZipFile

import pytest
from imageio_ffmpeg import get_ffmpeg_exe

import e_handoff
from e_handoff import read_json, write_json
from nodes.probe_input import media as b_media


def test_b_export_to_e_review_bundle(tmp_path: Path):
    ffmpeg = get_ffmpeg_exe()
    ffprobe = b_media.tool_path("ffprobe")
    video = tmp_path / "input.mp4"
    subprocess.run([
        ffmpeg, "-v", "error", "-f", "lavfi", "-i", "color=c=navy:s=320x180:r=25:d=2",
        "-f", "lavfi", "-i", "sine=frequency=440:duration=2",
        "-c:v", "libx264", "-c:a", "aac", str(video),
    ], check=True)
    b_job = tmp_path / "b"
    (b_job / "source").mkdir(parents=True)
    video = video.rename(b_job / "source/video.mp4")
    source_hash = b_media.sha256(video)
    write_json(b_job / "request.json", {"video_stream": 0, "audio_stream": 1})
    write_json(b_job / "media.json", {"duration_ms": 2000, "video_sha256": source_hash})
    write_json(b_job / "timetable.json", {
        "schema_version": "b-sentences-2",
        "status": "ready_for_human_review",
        "source": {"file": "video.mp4", "sha256": source_hash},
        "duration_ms": 2000,
        "review": {"untimed_utterances": []},
        "sentences": [
            {"sentence_id": "sentence_000001", "speaker_id": "speaker_001",
             "start_ms": 125, "end_ms": 875, "en": "Keep the original timeline.",
             "review_status": "automatic_checks_passed", "review_issues": []},
            {"sentence_id": "sentence_000002", "speaker_id": None,
             "start_ms": 1000, "end_ms": 1750, "en": "Do not change it.",
             "review_status": "needs_human_review", "review_issues": ["unknown speaker"]},
        ],
    })

    work = tmp_path / "e"
    original = (b_job / "timetable.json").read_bytes()
    shared = read_json(e_handoff.prepare(b_job, work, ffprobe))
    assert [row["speaker_id"] for row in shared] == ["spk_001", "spk_unknown"]
    assert [(row["start_ms"], row["end_ms"]) for row in shared] == [(125, 875), (1000, 1750)]

    reviewed = work / "translated/reviewed_blocks.json"
    copy = work / "editor.json"
    write_json(copy, {"title": "时间轴", "description": "联调样例", "cover_text": "保留原片时间轴"})
    translated = [
        {"segment_id": row["segment_id"], "block_id": "blk_0001", "zh_subtitle": subtitle,
         "zh_dub": subtitle}
        for row, subtitle in zip(shared, ["保留原片时间轴。", "不要改动。"], strict=True)
    ]
    write_json(reviewed, translated[:1])
    with pytest.raises(ValueError, match="一一对应"):
        e_handoff.render(b_job, work, copy, ffmpeg, ffprobe)
    assert not (work / "e-preview").exists()

    write_json(reviewed, translated[::-1])
    subprocess.run([
        ffmpeg, "-v", "error", "-f", "lavfi", "-i", "sine=frequency=660:duration=2",
        str(work / "audio/dub.wav"),
    ], check=True)
    package = e_handoff.render(b_job, work, copy, ffmpeg, ffprobe)
    with ZipFile(package) as archive:
        assert archive.testzip() is None
        assert set(archive.namelist()) == {
            "video/final.mp4", "subtitles/bilingual.srt", "subtitles/burnin.ass",
            "cover/cover.jpg", "edit_assets.json", "review-report.json", "manifest.json",
        }
        srt = archive.read("subtitles/bilingual.srt").decode().replace("\r\n", "\n")
        assert "00:00:00,125 --> 00:00:00,875\n保留原片时间轴。\nKeep the original timeline." in srt
        assert "00:00:01,000 --> 00:00:01,750\n不要改动。\nDo not change it." in srt
        assert b"needs_human_review" in archive.read("review-report.json")
    assert (b_job / "timetable.json").read_bytes() == original

    with (b_job / "source/video.mp4").open("ab") as source:
        source.write(b"changed")
    with pytest.raises(ValueError, match="哈希不一致"):
        e_handoff.prepare(b_job, tmp_path / "bad-handoff", ffprobe)
