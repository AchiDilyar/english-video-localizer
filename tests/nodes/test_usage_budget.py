import json
import pytest
from nodes.usage_budget import reserve


def test_ceiling_is_checked_before_external_call_and_failures_stay_counted(tmp_path,monkeypatch):
    path=tmp_path/'budget.json'
    path.write_text(json.dumps({'limits':{'tts_characters':5},'used':{}}))
    monkeypatch.setenv('LOCALIZER_BUDGET_FILE',str(path))
    reserve('tts_characters',4,'attempt')
    with pytest.raises(RuntimeError,match='BUDGET_LIMIT'):reserve('tts_characters',2)
    assert json.loads(path.read_text())['used']['tts_characters']==4
