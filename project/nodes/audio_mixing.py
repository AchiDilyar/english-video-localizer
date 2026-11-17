"""Mix an already separated background bed with final Chinese speech."""
import json
import subprocess
from pathlib import Path
from .background_audio import digest


def mix_background(background,dub,output,*,ffmpeg,duration_sec,background_gain=.7,source_video=None):
    if not 0<=background_gain<=1:raise ValueError('Background gain must be 0–1')
    for path in [background,dub]:
        if not Path(path).is_file():raise FileNotFoundError(path)
    filters=(f'[0:a]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo,volume={background_gain}[bg];'
             f'[1:a]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo,apad,atrim=duration={duration_sec},asplit=2[voice][key];'
             '[bg][key]sidechaincompress=threshold=0.03:ratio=3:attack=30:release=250:makeup=1[bed];'
             '[voice][bed]amix=inputs=2:normalize=0:duration=longest:dropout_transition=0,'
             f'alimiter=limit=0.95:level=false:latency=1,apad,atrim=duration={duration_sec}[mixed]')
    subprocess.run([str(ffmpeg),'-v','error','-y','-i',str(background),'-i',str(dub),'-filter_complex',filters,
                    '-map','[mixed]','-c:a','pcm_f32le',str(output)],check=True)
    result={'background_file':str(Path(background).resolve()),'dub_file':str(Path(dub).resolve()),'output':str(Path(output).resolve()),'duration_sec':duration_sec,
            'dub_sha256':digest(dub),'background_sha256':digest(background),'mixed_sha256':digest(output),
            'source_video_sha256':digest(source_video) if source_video else None,
            'background_gain':background_gain,'voice_gain':1.0,'sample_rate':48000,'channels':2,
            'sidechain_ducking':{'threshold':.03,'ratio':3,'attack_ms':30,'release_ms':250},
            'limiter_ceiling':.95,'automatic_mix_normalization':False,'latency_compensated':True}
    Path(output).with_suffix('.mix.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    return result


def select_prepared_mix(dub,source_video):
    """A prepared bed is optional, but a stale mix must never silently replace speech."""
    mixed=Path(dub).with_name('mixed.wav')
    if not mixed.exists():return Path(dub)
    receipt=mixed.with_suffix('.mix.json')
    if not receipt.is_file():raise ValueError('Prepared background mix has no provenance receipt')
    data=json.loads(receipt.read_text(encoding='utf-8'))
    if (data.get('dub_sha256'),data.get('source_video_sha256'),data.get('mixed_sha256'))!=(digest(dub),digest(source_video),digest(mixed)):
        raise ValueError('Prepared background mix does not match current video or dub')
    return mixed
