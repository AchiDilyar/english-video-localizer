"""Recheck the single approved live text-only call; never calls any provider."""
import json
from pathlib import Path
from b_pipeline.semantic_review import validate_response,check_semantic_boundaries
from b_pipeline.common import BError


def main():
    root=Path('jobs/B-semantic-small-validation-20261107')
    request=json.loads((root/'request.json').read_text(encoding='utf-8'))
    receipt=json.loads((root/'response.json').read_text(encoding='utf-8'))
    result=validate_response(receipt['response'],request['tokens'])
    verdict={'calls':receipt['calls'],'elapsed_ms':receipt['elapsed_ms'],'cost':'unknown',
             'model':receipt['model'],'usage':receipt['usage'],'text_only':True,
             'structural_validation':'passed','semantic_decision':'accepted'}
    try:check_semantic_boundaries(result,request['tokens'])
    except BError as exc:verdict.update({'semantic_decision':'rejected','reason':exc.code})
    first=0;units=[]
    for end in result['ends']:
        units.append(' '.join(request['tokens'][first:end]));first=end
    verdict['proposed_text_units']=units
    verdict['applied_to_existing_timestamps']=False
    (root/'verification.json').write_text(json.dumps(verdict,indent=2),encoding='utf-8')
    old=json.loads(Path('jobs/B-sentence-v2-YouTube-full-20261107-01/timetable.json').read_text(encoding='utf-8'))
    oversized=[{'sentence_id':r['sentence_id'],'word_count':len(r['en'].split()),
                'duration_ms':r['end_ms']-r['start_ms']} for r in old['sentences']
               if len(r['en'].split())>32 or r['end_ms']-r['start_ms']>10000]
    (root/'historical-long-unit-audit.json').write_text(json.dumps(oversized,indent=2),encoding='utf-8')
    print(json.dumps({**verdict,'historical_oversized_unit_count':len(oversized)},indent=2))


if __name__=='__main__':main()
