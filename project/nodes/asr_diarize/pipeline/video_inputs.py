"""V2 direct local-video / YouTube input; no transcript or source-time persistence."""
from pathlib import Path
import re
import shutil
import time
from urllib.parse import urlparse,parse_qs

from .common import BError,digest,write_json
from nodes.probe_input import media as b_media


def youtube_url(value):
    u=urlparse(str(value));host=(u.hostname or '').lower()
    if u.scheme not in ['http','https'] or u.username or u.password:
        raise BError('INPUT_URL','Use a local file or a normal YouTube video URL')
    if host in ['youtu.be','www.youtu.be']:video_id=u.path.strip('/').split('/')[0]
    elif host in ['youtube.com','www.youtube.com','m.youtube.com','music.youtube.com']:
        if u.path=='/watch':video_id=parse_qs(u.query).get('v',[''])[0]
        elif u.path.startswith(('/shorts/','/embed/','/live/')):video_id=u.path.strip('/').split('/')[1]
        else:video_id=''
    else:raise BError('INPUT_URL','Only YouTube URLs are accepted directly')
    if not re.fullmatch(r'[A-Za-z0-9_-]{11}',video_id):raise BError('INPUT_URL','A single YouTube video ID is required')
    return 'https://www.youtube.com/watch?v='+video_id


def resolve_input(value):
    p=Path(str(value)).expanduser()
    if p.is_file():return {'kind':'local','path':str(p.resolve()),'title':p.stem,'rights':'user_provided_not_automatically_licensed'}
    return {'kind':'youtube','url':youtube_url(value),'rights':'user_selected_public_video_not_automatically_licensed'}


def english_format(context):
    formats=[f for f in context.get('formats',[]) if not f.get('has_drm')]
    def audio_rank(f):
        language=(f.get('language') or '').lower();note=(f.get('format_note') or '').lower()
        if language=='en-orig' or ('original' in note and (language.startswith('en') or 'english' in note)):return 4
        if language=='en' or language.startswith('en-'):return 3
        if not language:return 1
        return 0
    mux=[f for f in formats if f.get('vcodec') not in [None,'none'] and f.get('acodec') not in [None,'none']
         and f.get('ext')=='mp4' and (f.get('height') or 0)<=480 and audio_rank(f)>0]
    if mux and max(audio_rank(f) for f in mux)>=3:
        yield max(mux,key=lambda f:(audio_rank(f),f.get('height') or 0,f.get('tbr') or 0));return
    videos=[f for f in formats if f.get('vcodec') not in [None,'none'] and f.get('acodec')=='none'
            and f.get('ext')=='mp4' and (f.get('height') or 0)<=480]
    audios=[f for f in formats if f.get('vcodec')=='none' and f.get('acodec') not in [None,'none'] and audio_rank(f)>0]
    if mux and (not videos or not audios or max(audio_rank(f) for f in audios)<3):
        yield max(mux,key=lambda f:(audio_rank(f),f.get('height') or 0,f.get('tbr') or 0));return
    if not videos or not audios:raise BError('YOUTUBE_FORMAT','No accessible English/original-compatible video and audio formats')
    v=max(videos,key=lambda f:(f.get('height') or 0,f.get('tbr') or 0))
    a=max(audios,key=lambda f:(audio_rank(f),f.get('ext')=='m4a',f.get('abr') or 0))
    yield {'format_id':v['format_id']+'+'+a['format_id'],'ext':'mp4',
           'requested_formats':[v,a],'protocol':v['protocol']+'+'+a['protocol']}


class QuietLogger:
    def debug(self,message):pass
    def info(self,message):pass
    def warning(self,message):pass
    def error(self,message):pass  # Do not echo signed URLs or giant extraction metadata.


def download_input(value,output_dir,*,allow_network=False,max_duration_sec=7200,max_bytes=2*1024**3,
                   download_timeout_sec=600,node_path=None):
    """Public material interface. No login/cookies/DRM bypass or playlist downloads."""
    source=resolve_input(value);folder=Path(output_dir);folder.mkdir(parents=True,exist_ok=True)
    target=folder/'video.mp4';receipt=folder/'download.json';start=time.perf_counter()
    if target.exists() or receipt.exists():raise BError('OUTPUT_EXISTS','Use a new material directory')
    if source['kind']=='local':
        src=Path(source['path'])
        if src.stat().st_size>max_bytes:raise BError('SOURCE_SIZE','Video exceeds configured file size limit')
        # Keep original container extension so local playback is not mislabeled.
        target=folder/('video'+src.suffix.lower());shutil.copy2(src,target)
        meta={'kind':'local','title':source['title'],'input_path':str(src),'rights':source['rights']}
    else:
        if not allow_network:raise BError('NETWORK_DISABLED','Enable networking for YouTube input')
        from yt_dlp import YoutubeDL
        started=time.perf_counter()
        selected_formats=[]
        def select_format(context):
            for chosen in english_format(context):
                audio=next((f for f in chosen.get('requested_formats',[]) if f.get('vcodec')=='none'),chosen)
                selected_formats.append({k:audio.get(k) for k in ['format_id','language','format_note','acodec']})
                yield chosen
        def progress(data):
            if time.perf_counter()-started>download_timeout_sec:raise BError('DOWNLOAD_TIMEOUT','YouTube download time budget reached')
            if (data.get('downloaded_bytes') or 0)>max_bytes:raise BError('SOURCE_SIZE','YouTube download exceeded file limit')
        def check(info,*,incomplete=False):
            if info.get('is_live'):return 'Live streams are not accepted'
            duration=info.get('duration')
            if duration is not None and duration>max_duration_sec+.1:return 'Video exceeds two-hour limit'
            if not incomplete and duration is None:return 'Video duration is unavailable'
        options={'quiet':True,'no_warnings':True,'logger':QuietLogger(),'noplaylist':True,
                 'format':select_format,'outtmpl':str(folder/'video.%(ext)s'),'merge_output_format':'mp4',
                 'ffmpeg_location':str(Path(b_media.tool_path('ffmpeg')).parent),
                 'socket_timeout':15,'retries':1,'extractor_retries':1,'fragment_retries':1,
                 'max_filesize':max_bytes,'progress_hooks':[progress],'match_filter':check,
                 'writesubtitles':False,'writeautomaticsub':False,'writeinfojson':False,
                 'writethumbnail':False,'cachedir':False,'overwrites':False}
        if node_path:options['js_runtimes']={'node':{'path':str(node_path)}}
        try:
            with YoutubeDL(options) as ydl:
                info=ydl.extract_info(source['url'],download=True)
            if not info or not target.is_file():raise BError('YOUTUBE_DOWNLOAD','No complete MP4 was downloaded')
            meta={k:info.get(k) for k in ['id','title','uploader','duration','language','license']}
            meta.update({'kind':'youtube','url':source['url'],'rights':source['rights'],
                         'selected_audio':selected_formats[-1] if selected_formats else None,
                         'audio_selection':'prefer English/original, never intentionally choose another language'})
        except BError:raise
        except Exception as exc:raise BError('YOUTUBE_DOWNLOAD',f'YouTube download failed ({type(exc).__name__}); check network/access and yt-dlp version') from exc
    if target.stat().st_size>max_bytes:raise BError('SOURCE_SIZE','Downloaded video exceeds file limit')
    meta.update({'file':target.name,'bytes':target.stat().st_size,'sha256':digest(target),'elapsed_sec':time.perf_counter()-start})
    write_json(receipt,meta)
    return target,meta
