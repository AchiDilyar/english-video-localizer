"""Compare final sentence-only long-video artifacts without re-running ASR."""
import argparse
import json
import re
from pathlib import Path


def metrics(table):
    rows=table['sentences']
    return {'sentence_count':len(rows),'duration_ms':table['duration_ms'],
            'maximum_unit_words':max(len(s['en'].split()) for s in rows),
            'maximum_unit_duration_ms':max(s['end_ms']-s['start_ms'] for s in rows),
            'over_32_words':sum(len(s['en'].split())>32 for s in rows),
            'over_10_seconds':sum(s['end_ms']-s['start_ms']>10000 for s in rows),
            'human_review_count':table['review']['sentences_needing_human_review'],
            'untimed_count':len(table['review'].get('untimed_utterances',[])),
            'structural_errors':table['review']['structural_errors'],
            'semantic_review':table['review'].get('semantic_review',{'not_available_in_historical_version':True}),
            'execution':table['execution']}


def main():
    p=argparse.ArgumentParser();p.add_argument('job');p.add_argument('--previous',required=True);a=p.parse_args()
    job=Path(a.job);previous=Path(a.previous)
    current=json.loads((job/'timetable.json').read_text(encoding='utf-8'))
    old=json.loads((previous/'timetable.json').read_text(encoding='utf-8'))
    def lexical_sequence(table):
        after={}
        for item in table['review'].get('untimed_utterances',[]):after.setdefault(item['after_sentence_id'],[]).append(item['en'])
        text=list(after.get(None,[]))
        for row in table['sentences']:
            text.append(row['en']);text.extend(after.get(row['sentence_id'],[]))
        return re.findall(r"[\w']+",' '.join(text).lower())
    report={'scope':'43-minute real local LangGraph validation, no paid semantic calls',
            'current':metrics(current),'previous':metrics(old),
            'spoken_word_sequence_equal_to_previous':lexical_sequence(current)==lexical_sequence(old),
            'not_verified':['human transcript accuracy','all semantic boundaries','two-hour real inference','live DeepSeek HTTP integration']}
    (job/'long-validation.json').write_text(json.dumps(report,indent=2,ensure_ascii=False),encoding='utf-8')
    oversized=[{'sentence_id':s['sentence_id'],'word_count':len(s['en'].split()),
                'duration_ms':s['end_ms']-s['start_ms'],'en':s['en'],'issues':s['review_issues']}
               for s in current['sentences'] if len(s['en'].split())>32 or s['end_ms']-s['start_ms']>10000]
    (job/'long-units-to-review.json').write_text(json.dumps(oversized,indent=2,ensure_ascii=False),encoding='utf-8')
    print(json.dumps({'current':report['current'],'spoken_word_sequence_equal_to_previous':report['spoken_word_sequence_equal_to_previous'],
                      'previous_summary':{k:v for k,v in report['previous'].items() if k not in ['execution','semantic_review']}},indent=2))


if __name__=='__main__':main()
