"""Explicitly authorized voice enrollment, scoped to source audio/model/region."""
import base64
import hashlib
import json
import os
import wave
from pathlib import Path


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def inherit_verified_excerpt(parent_audio, child_audio, parent_registry, output, start_ms=0):
    """Reuse authorized voices only after exact PCM excerpt identity verification."""
    data=json.loads(Path(parent_registry).read_text(encoding='utf-8'))
    if data['source_sha256']!=digest(parent_audio):raise ValueError('Parent audio identity changed')
    with wave.open(str(parent_audio),'rb') as parent,wave.open(str(child_audio),'rb') as child:
        if (parent.getnchannels(),parent.getsampwidth(),parent.getframerate())!=(child.getnchannels(),child.getsampwidth(),child.getframerate()):raise ValueError('Excerpt PCM format differs')
        parent.setpos(round(start_ms*parent.getframerate()/1000))
        if parent.readframes(child.getnframes())!=child.readframes(child.getnframes()):raise ValueError('Excerpt PCM differs')
    data['parent_source_sha256']=data['source_sha256'];data['source_sha256']=digest(child_audio)
    data['excerpt_start_ms']=start_ms;data['lineage_verification']='exact_pcm_equality'
    Path(output).write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')


def load_profiles(path, source_audio, model, region, speakers):
    data=json.loads(Path(path).read_text(encoding='utf-8'))
    if (data['source_sha256'],data['model'],data['region'])!=(digest(source_audio),model,region):
        raise ValueError('复刻音色与本视频、模型或地域不匹配')
    voices=data['voices']
    if not set(speakers)<=voices.keys():
        raise ValueError('VOICE_CLONE_REQUIRED: 存在尚未复刻的说话人，不回退为系统音色')
    return {key:voices[key]['voice_id'] for key in speakers}


def enroll_profiles(source_audio, references, path, *, model, region,
                    authorized=False, allow_network=False, client_factory=None):
    if not authorized or not allow_network:
        raise PermissionError('复刻需要原声授权及明确的上传许可')
    # Validate every sample before any paid request.
    for reference in references.values():
        with wave.open(str(reference),'rb') as audio:
            seconds=audio.getnframes()/audio.getframerate()
            if audio.getnchannels()!=1 or audio.getsampwidth()!=2 or not 10<=seconds<=60:
                raise ValueError('复刻参考音频需为 10–60 秒单人单声道 PCM16 WAV')
    path=Path(path)
    header={'source_sha256':digest(source_audio),'model':model,'region':region}
    data=json.loads(path.read_text(encoding='utf-8')) if path.exists() else {**header,'voices':{}}
    if any(data.get(key)!=value for key,value in header.items()):
        raise ValueError('拒绝覆盖其他视频、模型或地域的音色记录')
    if client_factory is None:
        import dashscope
        client_factory=dashscope.Client
    key=os.environ.get('DASHSCOPE_API_KEY','').strip()
    if not key:raise ValueError('未配置 DASHSCOPE_API_KEY')
    with client_factory(api_key=key,region=region,workspace=os.environ.get('DASHSCOPE_WORKSPACE') or None,
                        max_retries=0,timeout=60) as client:
        for speaker,reference in references.items():
            sample_hash=digest(reference)
            if speaker in data['voices']:
                if data['voices'][speaker]['sample_sha256']!=sample_hash:
                    raise ValueError('已有音色的参考样本已改变，请使用新音色记录文件')
                continue
            audio='data:audio/wav;base64,'+base64.b64encode(Path(reference).read_bytes()).decode('ascii')
            from .usage_budget import reserve
            reserve('voice_enrollments',1,speaker)
            result=client.audio.voices.create(target_model=model,prefix='localizer',url=audio,language_hints=['en'])
            if not result.voice_id:raise ValueError('复刻接口未返回 voice_id')
            data['voices'][speaker]={'voice_id':result.voice_id,'sample_sha256':sample_hash,
                                     'authorization':'user_confirmed','similarity_human_verified':False}
            path.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
    return load_profiles(path,source_audio,model,region,references)
