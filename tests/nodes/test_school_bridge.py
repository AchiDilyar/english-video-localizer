import json

import pytest

from nodes.translate_blocks import _text_model
from nodes.translate_blocks._school_bridge import SchoolModelPending


def test_school_bridge_needs_no_api_key_and_binds_response_to_request(tmp_path, monkeypatch):
    monkeypatch.setenv('DEEPSEEK_TRANSPORT', 'school_bridge')
    monkeypatch.setenv('DEEPSEEK_BRIDGE_DIR', str(tmp_path))
    monkeypatch.delenv('DEEPSEEK_API_KEY', raising=False)
    monkeypatch.setattr(_text_model, 'load_dotenv', lambda *args: None)
    monkeypatch.setattr(_text_model.httpx, 'Client', lambda **kwargs: pytest.fail('No HTTP permitted'))
    request={'instruction':'Translate public text','payload':{'text':'Hello'},'output_format':'JSON'}
    with pytest.raises(SchoolModelPending):
        _text_model.request_json(**request)
    exported=list(tmp_path.glob('*.request.json'))
    assert len(exported)==1
    assert json.loads(exported[0].read_text(encoding='utf-8'))==request
    response=exported[0].with_name(exported[0].name.replace('.request.json','.response.json'))
    response.write_text('{"items": []}',encoding='utf-8')
    assert _text_model.request_json(**request)=={'items':[]}
    with pytest.raises(SchoolModelPending):
        _text_model.request_json(**{**request,'payload':{'text':'Changed'}})
    response.write_text('[]',encoding='utf-8')
    with pytest.raises(ValueError,match='JSON'):
        _text_model.request_json(**request)


def test_unknown_transport_does_not_silently_call_api(monkeypatch):
    monkeypatch.setenv('DEEPSEEK_TRANSPORT','typo')
    monkeypatch.setattr(_text_model, 'load_dotenv', lambda *args: None)
    with pytest.raises(ValueError,match='DEEPSEEK_TRANSPORT'):
        _text_model.request_json(instruction='x',payload={})
