"""Public source registry API: selection is separate from acquisition."""
from __future__ import annotations

import math
from pathlib import Path
import shutil
from urllib.parse import urlparse

from nodes.probe_input import media as b_media
from .common import BError, artifact, digest, read_json


def list_sources(registry_path):
    data = read_json(registry_path)
    if data.get('schema_version') != 'b-sources-1':
        raise BError('REGISTRY_VERSION', 'Unsupported source registry version')
    entries = data.get('sources',[])
    ids = [e.get('source_id') for e in entries]
    if not entries or any(not isinstance(i,str) or not i for i in ids) or len(ids)!=len(set(ids)):
        raise BError('REGISTRY_INVALID', 'Source IDs must be unique nonempty strings')
    return entries


def select_source(input_ref, registry_path):
    """Resolve registered ID, registered URL or a registered local path; no web search."""
    base = Path(registry_path).resolve().parent
    matches = []
    for entry in list_sources(registry_path):
        e = dict(entry)
        if e.get('kind') == 'local':
            e['local_path'] = str((base / e['local_path']).resolve())
        names = [e['source_id'],e.get('page_url'),e.get('media_url'),e.get('local_path')]
        path_match = e.get('kind')=='local' and str(Path(input_ref).resolve())==e['local_path']
        if input_ref in names or path_match:
            matches.append(e)
    if len(matches)!=1:
        raise BError('SOURCE_NOT_REGISTERED' if not matches else 'SOURCE_AMBIGUOUS', 'Input must identify exactly one registered source')
    e = matches[0]
    if e.get('authorization_status')!='confirmed' or not all(e.get(k) for k in ['license','license_url','attribution','page_url']):
        raise BError('SOURCE_UNAUTHORIZED', 'Record confirmed permission, license, attribution and source first')
    if e.get('kind') not in ['local','https_excerpt','https_file']:
        raise BError('SOURCE_KIND', 'Supported kinds: local, https_excerpt, https_file')
    offset=e.get('original_offset_ms',0)
    if type(offset) is not int or offset<0:
        raise BError('SOURCE_OFFSET', 'original_offset_ms must be a nonnegative integer')
    if e['kind'] in ['https_excerpt','https_file']:
        u=urlparse(e.get('media_url',''))
        if u.scheme!='https' or not u.hostname or u.username or u.password:
            raise BError('SOURCE_URL', 'Use a registered public HTTPS media URL without credentials')
    if e['kind']=='https_excerpt':
        for key in ['excerpt_start_sec','excerpt_duration_sec']:
            n=e.get(key)
            if type(n) not in [int,float] or not math.isfinite(n) or n<0:
                raise BError('SOURCE_RANGE','Excerpt range must be finite and nonnegative')
        if not 0<e['excerpt_duration_sec']<=3600:
            raise BError('SOURCE_RANGE','Excerpt must be in (0,3600] seconds')
        from .common import milliseconds
        if milliseconds(e['excerpt_start_sec'])!=offset:
            raise BError('SOURCE_OFFSET','Original offset must match excerpt start')
    return e


def acquire(source, job, allow_network=False, limits=None):
    """Copy local media or read only the registered bounded remote excerpt."""
    limits=limits or {};max_bytes=limits.get('max_source_bytes',256*1024*1024)
    source_dir=artifact(job,'source');source_dir.mkdir(exist_ok=True)
    if source['kind']=='local':
        src=Path(source['local_path'])
        if not src.is_file():raise BError('INPUT_NOT_FOUND','Registered local video is missing')
        if src.stat().st_size>max_bytes:raise BError('SOURCE_SIZE','Local source exceeds configured file size limit')
        expected=source.get('expected_sha256')
        if expected and digest(src)!=expected:raise BError('HASH_MISMATCH','Registered local source changed')
        target=source_dir/('video'+src.suffix.lower())
        shutil.copyfile(src,target)
    elif source['kind']=='https_file':
        if not allow_network:raise BError('NETWORK_DISABLED','Enable networking for registered downloads')
        from .downloads import download_file
        target=source_dir/'video.mp4'
        download_file(source['media_url'],target,max_bytes=max_bytes,
                      timeout_sec=limits.get('download_timeout_sec',180),
                      pause_once_bytes=limits.get('pause_download_once_bytes'),
                      expected_sha256=source.get('expected_sha256'))
    else:
        if not allow_network:raise BError('NETWORK_DISABLED','Set allow_network=True for registered downloads')
        target=source_dir/'video.mp4'
        temp=source_dir/'download.partial.mp4'
        ffmpeg=b_media.tool_path('ffmpeg')
        command=[ffmpeg,'-hide_banner','-loglevel','error','-nostdin','-y',
                 '-rw_timeout','15000000','-ss',str(source['excerpt_start_sec']),'-i',source['media_url'],
                 '-t',str(source['excerpt_duration_sec']),'-map','0:v:0','-map','0:a:0',
                 '-c:v','libx264','-preset','fast','-crf','23','-c:a','aac','-b:a','96k',
                 '-fs',str(max_bytes),'-movflags','+faststart',str(temp)]
        b_media.run(command,timeout=limits.get('download_timeout_sec',180))
        info=b_media.inspect(temp,b_media.tool_path('ffprobe'),None,None)
        if not temp.stat().st_size or temp.stat().st_size>=max_bytes or abs(info['duration_ms']/1000-source['excerpt_duration_sec'])>.1:
            raise BError('DOWNLOAD_INCOMPLETE','Downloaded excerpt exceeds size bound or has unexpected duration')
        temp.replace(target)
    return {'media_ref':str(target.relative_to(Path(job))), 'media_sha256':digest(target),
            'acquisition_kind':source['kind'],'source_id':source['source_id']}
