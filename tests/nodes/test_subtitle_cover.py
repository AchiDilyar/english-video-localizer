"""Regression coverage for the synchronized SRT and ASS tracks."""

import pytest
from contracts import GraphState, Segment, TranslatedSegment
from nodes.subtitle_cover import subtitle_cover
from subtitle_templates import APPEARANCE, GEOMETRY, LAYOUTS, RESOLUTIONS, STYLES
from utils import paths


@pytest.fixture
def subtitle_job(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "_work_dir", tmp_path)
    monkeypatch.setattr('nodes.subtitle_cover.load_config',lambda _: {'timing_source':'source'})
    output = tmp_path / "subtitles"
    output.mkdir()
    return output


def test_speech_mode_uses_actual_speech_text_and_times(subtitle_job,subtitle_state,monkeypatch):
    monkeypatch.setattr('nodes.subtitle_cover.load_config',lambda _: {'timing_source':'speech'})
    monkeypatch.setattr('nodes.speech_subtitles.create_bilingual_cues',lambda *args:[
        {'start_ms':2220,'end_ms':2600,'zh':'实际配音。','en':'Hello, world. Later.'}])
    subtitle_cover(subtitle_state)
    result=(subtitle_job/'bilingual.srt').read_text(encoding='utf-8')
    assert '00:00:02,220 --> 00:00:02,600' in result
    assert '实际配音。\nHello, world. Later.' in result
    assert '00:00:00,000' not in result


def test_speech_mode_does_not_fall_back_to_old_times_if_audio_missing(subtitle_job,subtitle_state,monkeypatch):
    monkeypatch.setattr('nodes.subtitle_cover.load_config',lambda _: {'timing_source':'speech'})
    with pytest.raises(FileNotFoundError,match='先生成'):
        subtitle_cover(subtitle_state)


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
    assert r"Dialogue: 2,0:00:00.00,0:00:01.23,ZH,,0,0,185,,你好 世界" in ass
    assert r"Dialogue: 1,0:00:00.00,0:00:01.23,EN,,0,0,0,,Hello,\Nworld." in ass
    assert actual == {
        "english_segmented.srt": f"{first}Hello,\nworld.\n\n{second}Later.\n",
        "chinese.srt": f"{first}你好 世界\n\n{second}再见\n",
        "bilingual.srt": f"{first}你好 世界\nHello,\nworld.\n\n{second}再见\nLater.\n",
    }


@pytest.mark.parametrize('height',[480,1080,2160])
def test_multiline_english_keeps_chinese_above_and_both_centered(height):
    from subtitle_templates import ass_dialogue,ass_header
    header=ass_header(None,round(height*16/9),height,'clean','zh_top')
    styles={line.split(',')[0].split(': ')[1]:line.split(',') for line in header.splitlines() if line.startswith('Style: ')}
    assert int(styles['ZH'][18])==int(styles['EN'][18])==2
    result=ass_dialogue('0:00:00.00','0:00:02.00','中文在上',
                        'Original English first sentence.\nOriginal English second sentence.',
                        'zh_top',render_height=height)
    upper=result.splitlines()[0].split(',')
    assert int(upper[7])>=int(styles['EN'][21])+2*int(styles['EN'][2])+5
    assert r'Original English first sentence.\NOriginal English second sentence.' in result


def test_speech_english_wrap_is_display_only_and_preserves_words():
    from subtitle_templates import ass_dialogue
    english=' '.join(['A complete original English sentence, with punctuation.']*4)
    result=ass_dialogue('0:00:00.00','0:00:10.00','中文在上',english,'zh_top',
                        render_height=720,wrap_english=True)
    rendered=result.splitlines()[1].split(',',9)[9]
    assert rendered.replace(r'\N',' ')==english
    assert max(map(len,rendered.split(r'\N')))<=64
    assert int(result.splitlines()[0].split(',')[7])>78


def test_speech_long_chinese_wrap_keeps_every_character():
    from subtitle_templates import ass_dialogue
    chinese='这是用于检查长句中文字幕完整显示且不会超出画面宽度的测试文字'*3
    result=ass_dialogue('0:00:00.00','0:00:10.00',chinese,'Original English.',
                        'zh_top',render_height=720,wrap_chinese=True)
    rendered=result.splitlines()[0].split(',',9)[9]
    assert rendered.replace(r'\N','')==chinese
    assert max(map(len,rendered.split(r'\N')))<=24


def test_display_end_follows_dubbing_but_not_past_next_start(subtitle_job, subtitle_state, monkeypatch):
    from contracts import TTSClip
    monkeypatch.setattr('nodes.subtitle_cover.load_config', lambda _: {})
    subtitle_state.tts_clips=[TTSClip(segment_id='seg_0001',audio_path='seg_0001.wav',
        duration_ms=2000,text='你好',voice_id='local',model='test')]
    subtitle_cover(subtitle_state)
    assert '00:00:00,000 --> 00:00:02,000' in (subtitle_job/'bilingual.srt').read_text(encoding='utf-8')
    assert subtitle_state.segments[1].end_ms==1234


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
