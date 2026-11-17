from array import array
import sys
from types import SimpleNamespace
import wave
import pytest
from nodes.speech_alignment import waveform_cue,refine_groups,restore_script_text,normalize
from utils import paths


@pytest.fixture
def audio_job(tmp_path,monkeypatch):
    monkeypatch.setattr(paths,'_work_dir',tmp_path)
    for name in ['tts','audio','subtitles']:(tmp_path/name).mkdir()
    return tmp_path


def write_wave(path,samples):
    with wave.open(str(path),'wb') as f:
        f.setnchannels(1);f.setsampwidth(2);f.setframerate(1000)
        f.writeframes(array('h',samples).tobytes())


def prepare(root,voice=2000,dub_voice=None):
    samples=[0]*100+[voice]*100+[0]*100
    write_wave(root/'tts/dub_0001.wav',samples)
    other=samples if dub_voice is None else [0]*100+[dub_voice]*100+[0]*100
    write_wave(root/'audio/dub.wav',[0]*1000+other+[0]*100)
    return {'group_id':'dub_0001','start_ms':1000,'end_ms':1300}


def test_recovery_bounds_come_from_final_pcm_not_old_source_time(audio_job):
    report=prepare(audio_job)
    cue=waveform_cue(report,'嗯。')
    assert (cue['start_ms'],cue['end_ms'])==(1080,1220)
    assert 'not independent word ASR' in cue['warnings'][0]


def test_known_narration_restores_numbers_negation_and_asr_typos_without_new_times():
    script='他们仍会缺少什么？不是40年，而是14年。'
    spoken=[{'start_ms':100,'end_ms':800,'zh':'他们人会缺少什么'},
            {'start_ms':900,'end_ms':1800,'zh':'是四十年而不是十年'}]
    result=restore_script_text(spoken,script)
    assert ''.join(c['zh'] for c in result)==script
    assert [(c['start_ms'],c['end_ms']) for c in result]==[(100,800),(900,1800)]
    assert result[0]['asr_original_text']==spoken[0]['zh']


def test_leading_book_title_punctuation_is_preserved():
    text='《蒙娜丽莎》，40年后依然很酷。'
    result=restore_script_text([{'start_ms':100,'end_ms':900,'zh':'蒙娜丽莎四十年后依然很酷'}],text)
    assert ''.join(c['zh'] for c in result)==text


def test_unmatched_asr_hallucination_is_not_added_to_known_narration():
    spoken=[{'start_ms':0,'end_ms':100,'zh':'嗯'},
            {'start_ms':100,'end_ms':200,'zh':'感谢观看'},
            {'start_ms':200,'end_ms':300,'zh':'对'}]
    result=restore_script_text(spoken,'嗯。对。')
    assert ''.join(c['zh'] for c in result)=='嗯。对。'
    assert '感谢' not in ''.join(c['zh'] for c in result)


def test_silent_or_mismatched_audio_cannot_create_fake_cue(audio_job):
    report=prepare(audio_job,voice=0)
    with pytest.raises(ValueError,match='有效音频信号'):waveform_cue(report,'嗯。')
    report=prepare(audio_job,voice=2000,dub_voice=1000)
    with pytest.raises(ValueError,match='内容不一致'):waveform_cue(report,'嗯。')


@pytest.mark.parametrize('recognized,accepted',[('嗯。',True),('感谢观看。',False)])
def test_targeted_asr_is_cached_and_hallucinations_use_marked_pcm_recovery(audio_job,monkeypatch,recognized,accepted):
    report=prepare(audio_job);calls=[]
    class Model:
        def __init__(self,*args,**kwargs):pass
        def transcribe(self,*args,**kwargs):
            calls.append(1)
            return iter([SimpleNamespace(words=[SimpleNamespace(word=recognized,start=.1,end=.2)])]),None
    monkeypatch.setitem(sys.modules,'faster_whisper',SimpleNamespace(WhisperModel=Model))
    args=([report],{'dub_0001':'嗯。'},'audio-hash','local-model')
    first=refine_groups(*args);second=refine_groups(*args)
    assert len(calls)==1 and first==second
    cue=first['dub_0001'][0]
    assert ('local_ASR' in cue['alignment_method']) is accepted
    assert cue['zh']=='嗯。'
