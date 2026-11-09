"""Audit the recorded public boundary response locally; never call an API."""
import json
from pathlib import Path
from nodes.asr_diarize.pipeline.semantic_review import validate_response, check_semantic_boundaries
from nodes.asr_diarize.pipeline.common import BError

ROOT=Path(__file__).resolve().parents[4]

def audit_fixture(output):
    output=Path(output).resolve()
    if not output.is_relative_to((ROOT/'tests/tmp').resolve()):
        raise ValueError('Test audit output must stay in tests/tmp')
    data=json.loads((ROOT/'tests/data/asr_diarize/semantic-boundary.json').read_text(encoding='utf-8'))
    validated=validate_response(data['response'],data['tokens'])
    verdict={'new_api_calls':0,'structural_validation':'passed','semantic_decision':'accepted'}
    try:
        check_semantic_boundaries(validated,data['tokens'])
    except BError as exc:
        verdict.update(semantic_decision='rejected',reason=exc.code)
    output.mkdir(parents=True,exist_ok=False)
    (output/'verification.json').write_text(json.dumps(verdict,indent=2),encoding='utf-8')
    return verdict
