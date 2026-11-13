"""Regression coverage for the synchronized SRT and ASS tracks."""

import pytest
from contracts import GraphState, Segment, TranslatedSegment
from nodes.subtitle_cover import subtitle_cover
from subtitle_templates import APPEARANCE, GEOMETRY, LAYOUTS, RESOLUTIONS, STYLES
from utils import paths


@pytest.fixture
def subtitle_job(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "_work_dir", tmp_path)
    output = tmp_path / "subtitles"
    output.mkdir()
    return output


@pytest.fixture
def subtitle_state():
    return GraphState(
        media_info={
            "duration_ms": 3_603_000,
            "video_info": {"codec": "h264", "width": 1920, "height": 1080},
            "audio_info": {"codec": "aac", "sample_rate": 48000, "channels": 2},
            "ffprobe_raw": {},
        },
        segments=[
            Segment(
                segment_id="seg_0002", speaker_id="spk_1",
                start_ms=3_601_002, end_ms=3_602_003, text_en="Later.",
            ),
            Segment(
                segment_id="seg_0001", speaker_id="spk_1",
                start_ms=0, end_ms=1234, text_en="Hello,\r\n\r\nworld.",
            ),
        ],
        reviewed_blocks=[
            TranslatedSegment(
                segment_id="seg_0001", block_id="blk_0001",
                zh_subtitle="你好\n世界", zh_dub="口播稿",
            ),
            TranslatedSegment(
                segment_id="seg_0002", block_id="blk_0001",
                zh_subtitle="再见", zh_dub="口播稿",
            ),
        ],
    )


def test_exports_tracks_on_the_same_source_timeline(subtitle_job, subtitle_state, monkeypatch):
    monkeypatch.setattr("nodes.subtitle_cover.load_config", lambda _: {})
    first = "1\n00:00:00,000 --> 00:00:01,234\n"
    second = "2\n01:00:01,002 --> 01:00:02,003\n"

    assert subtitle_cover(subtitle_state) == {}
    actual = {file.name: file.read_bytes().decode("utf-8") for file in subtitle_job.iterdir()}
    ass = actual.pop("burnin.ass")
    assert r"Dialogue: 2,0:00:00.00,0:00:01.23,ZH,,0,0,0,,你好 世界" in ass
    assert r"Dialogue: 1,0:00:00.00,0:00:01.23,EN,,0,0,0,,Hello,\Nworld." in ass
    assert actual == {
        "english_segmented.srt": f"{first}Hello,\nworld.\n\n{second}Later.\n",
        "chinese.srt": f"{first}你好 世界\n\n{second}再见\n",
        "bilingual.srt": f"{first}你好 世界\nHello,\nworld.\n\n{second}再见\nLater.\n",
    }


def test_fade_is_opt_in(subtitle_job, subtitle_state, monkeypatch):
    monkeypatch.setattr("nodes.subtitle_cover.load_config", lambda _: {"fade_enabled": True})
    subtitle_cover(subtitle_state)
    ass = (subtitle_job / "burnin.ass").read_text(encoding="utf-8")
    events = [line for line in ass.splitlines() if line.startswith("Dialogue:")]
    assert len(events) == 4
    assert all(r"{\fad(120,120)}" in line for line in events)


def test_missing_reviewed_segment_keeps_previous_tracks(subtitle_job, subtitle_state):
    subtitle_cover(subtitle_state)
    original = {file.name: file.read_bytes() for file in subtitle_job.iterdir()}
    subtitle_state.reviewed_blocks.pop()

    with pytest.raises(ValueError, match="缺少译文.*seg_0002"):
        subtitle_cover(subtitle_state)

    assert {file.name: file.read_bytes() for file in subtitle_job.iterdir()} == original


def test_ass_uses_selected_export_resolution(subtitle_job, subtitle_state, monkeypatch):
    monkeypatch.setattr(
        "nodes.compose_settings.load_config", lambda _: {"resolution": "720p"}
    )
    subtitle_cover(subtitle_state)
    ass = (subtitle_job / "burnin.ass").read_text(encoding="utf-8")
    assert "PlayResX: 1280\nPlayResY: 720\n" in ass


@pytest.mark.parametrize("style", STYLES)
@pytest.mark.parametrize("layout", LAYOUTS)
@pytest.mark.parametrize("height", RESOLUTIONS)
def test_style_matrix_uses_video_size_and_saved_options(
    subtitle_job, subtitle_state, monkeypatch, style, layout, height
):
    monkeypatch.setattr("nodes.compose_settings.load_config", lambda _: {})
    monkeypatch.setattr(
        "nodes.subtitle_cover.load_config", lambda _: {"style": style, "layout": layout}
    )
    video = subtitle_state.media_info.video_info
    video.width, video.height = round(height * 16 / 9), height
    subtitle_cover(subtitle_state)

    lines = (subtitle_job / "burnin.ass").read_text(encoding="utf-8").splitlines()
    assert f"PlayResX: {video.width}" in lines
    assert f"PlayResY: {height}" in lines
    zh_style = next(line for line in lines if line.startswith("Style: ZH,")).split(",")
    preset = APPEARANCE | STYLES[style]
    scale = height / 2160
    assert int(zh_style[2]) == round(GEOMETRY["zh_size"] * scale)
    assert zh_style[16] == f"{preset['zh_outline'] * scale:.2f}"
    assert int(zh_style[18]) == 2
    assert int(zh_style[21]) == round(LAYOUTS[layout]["margin_y"]["zh"] * scale)
    events = [line for line in lines if line.startswith("Dialogue:")]
    assert len(events) == 2 * len(LAYOUTS[layout]["lines"])
    if layout != "zh_only":
        en_style = next(line for line in lines if line.startswith("Style: EN,")).split(",")
        assert int(en_style[21]) == round(LAYOUTS[layout]["margin_y"]["en"] * scale)
        assert events[-1].endswith(r"Later.")
    else:
        assert events[-1].endswith(r"再见")
