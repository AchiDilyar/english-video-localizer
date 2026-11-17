"""In-memory recognition/review kernels; consume resolved paths, never write artifacts."""
import copy
import logging
import time

from .common import BError
from .sentence_rules import sentences_from_words, sentence_audit, validate_sentence_table
from utils.local_models import require_whisper_model

logger = logging.getLogger(__name__)


def recognize_audio(audio_path, model_dir, duration_ms, source_meta=None, semantic_config=None):
    model_dir = require_whisper_model(model_dir)
    from faster_whisper import WhisperModel
    import spacy
    started=time.perf_counter()
    model=WhisperModel(model_dir,device='cpu',compute_type='int8',cpu_threads=4,local_files_only=True)
    load=time.perf_counter()-started;t=time.perf_counter()
    # Exactly one transcribe call for the complete audio; no external splitting.
    stream,info=model.transcribe(str(audio_path),language='en',beam_size=5,
                                 temperature=0,word_timestamps=True,vad_filter=False,condition_on_previous_text=True)
    words=[];count=0
    for segment in stream:
        if not segment.words and segment.text.strip():raise BError('WORD_ALIGNMENT_MISSING','Cannot time sentence text without alignment')
        words.extend({'word':w.word,'start':w.start,'end':w.end} for w in segment.words or [])
        count+=1
        if count%100==0:logger.info('ASR internal decoder results processed (not saved): %d',count)
    inference=time.perf_counter()-t
    nlp=spacy.load('en_core_web_sm',disable=['ner']);nlp.max_length=3000000
    semantic=semantic_config or {'provider':'none'}
    reviewer=None
    if semantic['provider']=='deepseek':
        from .semantic_review import DeepSeekHTTP
        reviewer=DeepSeekHTTP(allow_network=semantic['allow_network'],max_calls=semantic['max_calls'])
        if reviewer.model!=semantic.get('model') or reviewer.base_url!=semantic.get('base_url'):
            raise BError('SEMANTIC_CONFIG_CHANGED','Semantic model/endpoint changed; create a new task')
    sentences,review=sentences_from_words(words,nlp,semantic_reviewer=reviewer)
    # Discard alignment before any durable output/checkpoint update.
    word_count=len(words);del words,stream,model
    table={'schema_version':'b-sentences-2','duration_ms':duration_ms,
           'source':source_meta or {},'sentences':sentences,'review':review,
           'verification':{'human_confirmed':False,'automatic_diarization_executed':False,
                           'sentence_semantics_guaranteed':False},
           'execution':{'engine':'faster-whisper','language':'en','device':'cpu','compute_type':'int8',
                        'model_load_sec':load,'inference_sec':inference,'transcribe_calls':1,
                        'external_audio_chunks':0,'internal_decoder_results_not_persisted':count,
                        'aligned_word_count_used_in_memory':word_count,'raw_asr_timestamps_persisted':False,
                        'paid_api_calls':getattr(reviewer,'calls',0),'deepseek_used':bool(getattr(reviewer,'calls',0))}}
    return table


def review_table(table):
    import spacy
    table=copy.deepcopy(table);nlp=spacy.load('en_core_web_sm',disable=['ner'])
    # Second check uses sentence text only; no original ASR alignment is available here.
    for sentence in table['sentences']:
        extra=sentence_audit(sentence['en'],nlp)
        sentence['review_issues']=sorted(set(sentence['review_issues']+extra))
        sentence['review_status']='needs_human_review' if sentence['review_issues'] else 'automatic_checks_passed'
    errors=validate_sentence_table(table)
    table['review']['structural_errors']=errors
    table['review']['sentences_needing_human_review']=sum(bool(s['review_issues']) for s in table['sentences'])
    table['status']='blocked_validation' if errors else 'ready_for_human_review'
    return table
