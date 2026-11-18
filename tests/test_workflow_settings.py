"""The workbench edits the same TOML shape and schema consumed by the CLI."""

import sys
import tomllib
from pathlib import Path

import pytest
from graph.builder import WORKFLOW_EDGES
from graph.registry import NODE_NAMES
from nodes.asr_diarize.node import ASROptions
from nodes.probe_input.node import ProbeOptions
from pydantic import ValidationError

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from workflow_settings import ConfigChanged, save_settings, settings_snapshot, workflow_schema  # noqa: E402


def test_canvas_topology_matches_main_graph():
    schema = workflow_schema()
    assert schema["nodes"] == NODE_NAMES
    assert set(map(tuple, schema["edges"])) == {
        (node, target)
        for sources, target in WORKFLOW_EDGES
        for node in (sources if isinstance(sources, tuple) else (sources,))
    }
    assert set(schema['incremental_nodes']) == {'repair_blocks','b_environment','mix_background'}


def test_background_settings_use_node_models(tmp_path):
    path=tmp_path/'mix_background.toml'
    path.write_text('background_gain = 0.7\n')
    snapshot=settings_snapshot('mix_background',path.read_bytes())
    saved=save_settings(path,'mix_background',{'revision':snapshot['revision'],'values':{'background_gain':0.4}})
    assert saved['fields'][0]['value']==0.4
    with pytest.raises(ValidationError):
        save_settings(path,'mix_background',{'revision':saved['revision'],'values':{'background_gain':1.1}})


def test_mock_incremental_does_not_block_real_basic_path(tmp_path):
    from workflow_modes import mode_snapshot, save_modes
    path=tmp_path/'mock.toml'
    path.write_text('b_environment = true\nmix_background = true\nrepair_blocks = true\n')
    snapshot=mode_snapshot(path.read_bytes())
    assert save_modes(path,{'revision':snapshot['revision'],'modes':snapshot['modes']})['modes']==snapshot['modes']


def test_write_and_clear_asr_overrides(tmp_path):
    path = tmp_path / "asr_diarize.toml"
    path.write_text('# Local models\nmodel_dir = "models/local"\n')
    original = settings_snapshot("asr_diarize", path.read_bytes())
    assert {field["key"] for field in original["fields"]} == ASROptions.model_fields.keys()
    saved = save_settings(path, "asr_diarize", {
        "revision": original["revision"],
        "values": {"num_speakers": 2, "max_duration_sec": 600.5, "audio_recheck": False},
    })
    options = ASROptions.model_validate(tomllib.loads(path.read_text()))
    assert (options.num_speakers, options.max_duration_sec, options.audio_recheck) == (2, 600.5, False)
    assert options.model_dir == "models/local"
    assert path.read_text().startswith("# Local models\n")
    with pytest.raises(ConfigChanged):
        save_settings(path, "asr_diarize", {"revision": original["revision"], "values": {}})
    save_settings(path, "asr_diarize", {"revision": saved["revision"], "values": {"num_speakers": None}})
    assert "num_speakers" not in tomllib.loads(path.read_text())


@pytest.mark.parametrize("values, error", [
    ({"num_speakers": 33}, ValidationError),
    ({"num_speakers": "2"}, ValidationError),
    ({"audio_recheck": 1}, ValidationError),
    ({"community1_python": "other"}, ValueError),
    ({"vad": True}, ValueError),
])
def test_reject_unsupported_asr_settings(tmp_path, values, error):
    path = tmp_path / "asr_diarize.toml"
    original = b"audio_recheck = true\n"
    path.write_bytes(original)
    snapshot = settings_snapshot("asr_diarize", original)
    with pytest.raises(error):
        save_settings(path, "asr_diarize", {"revision": snapshot["revision"], "values": values})
    assert path.read_bytes() == original


def test_probe_round_trip(tmp_path):
    path = tmp_path / "probe_input.toml"
    path.touch()
    snapshot = settings_snapshot("probe_input", b"")
    updated = save_settings(path, "probe_input", {
        "revision": snapshot["revision"],
        "values": {"ffprobe": '/tmp/media "tools"/ffprobe', "audio_stream": 2},
    })
    options = ProbeOptions.model_validate(tomllib.loads(path.read_text()))
    assert options.ffprobe == '/tmp/media "tools"/ffprobe'
    assert options.audio_stream == 2
    assert updated == settings_snapshot("probe_input", path.read_bytes())



def test_subtitle_style_and_layout_use_backend_catalog(tmp_path):
    path = tmp_path / "subtitle_cover.toml"
    path.touch()
    snapshot = settings_snapshot("subtitle_cover", b"")
    fields = {field["key"]: field for field in snapshot["fields"]}
    assert fields["style"]["choices"] == ["clean", "contrast", "serif", "refined"]
    assert fields["layout"]["choices"] == ["zh_only", "zh_top", "zh_bottom"]
    assert fields["layout"]["choice_labels"]["zh_bottom"] == "双语 · 译文在下"
    saved = save_settings(path, "subtitle_cover", {
        "revision": snapshot["revision"], "values": {"style": "contrast", "layout": "zh_bottom"},
    })
    assert tomllib.loads(path.read_text()) == {"style": "contrast", "layout": "zh_bottom"}
    with pytest.raises(ValidationError, match="未知的字幕风格"):
        save_settings(path, "subtitle_cover", {
            "revision": saved["revision"], "values": {"style": "unsupported"},
        })



def test_translation_dropdowns_preserve_nested_terminology(tmp_path, monkeypatch):
    from nodes.translate_blocks import _options

    path = tmp_path / 'translate_blocks.toml'
    path.write_text('style = "通用"\n\n[terminology]\nenabled = true\n'
                    '[terminology.entries]\n"style" = "风格"\n"sample size" = "样本量"\n')
    snapshot = settings_snapshot('translate_blocks', path.read_bytes())
    fields = {field['key']: field for field in snapshot['fields']}
    assert fields['style']['choices'] == ["通用", "音乐行业", "影视", "新闻", "科学与技术", "文化与历史"]
    assert fields['tone']['value'] == '遵循原文'
    assert '口语自然' in fields['tone']['choices']
    assert 'terminology' not in fields
    before = tomllib.loads(path.read_text())['terminology']
    saved = save_settings(path, 'translate_blocks', {
        'revision': snapshot['revision'],
        'values': {'style': '科学与技术', 'tone': '口语自然'},
    })
    data = tomllib.loads(path.read_text())
    assert data['terminology'] == before
    monkeypatch.setattr(_options, 'load_config', lambda name: data)
    prompt = _options.with_style('Translate.')
    assert '科学与技术' in prompt and '口语自然' in prompt
    assert '数字、单位' in prompt
    with pytest.raises(ValidationError):
        save_settings(path, 'translate_blocks', {
            'revision': saved['revision'], 'values': {'tone': '不存在'},
        })
