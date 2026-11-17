"""Bounded HTTPS file download with validated Range resumption and retained failures."""
from __future__ import annotations

import hashlib
from http.client import IncompleteRead
from pathlib import Path
import re
import time
import urllib.error
import urllib.request
from urllib.parse import urlparse
import uuid

from .common import BError, digest, read_json, write_json


class HTTPSRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if urlparse(newurl).scheme != 'https':
            raise BError('DOWNLOAD_REDIRECT', 'Refusing an HTTPS downgrade')
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def download_file(url, target, *, max_bytes=256*1024*1024, timeout_sec=180,
                  max_attempts=2, pause_once_bytes=None, expected_sha256=None, opener=None):
    """Return a verified local file; partial bytes/validators remain after failure.

    No authentication or video-site extraction. Servers without validators cannot
    safely resume: their partial response is archived and restarted, never appended.
    """
    u=urlparse(url)
    if u.scheme!='https' or not u.hostname or u.username or u.password:
        raise BError('SOURCE_URL','A public HTTPS URL without credentials is required')
    if type(max_bytes) is not int or not 0<max_bytes<=1024**3:
        raise BError('DOWNLOAD_LIMIT','max_bytes must be in (0,1 GiB]')
    if not 0<timeout_sec<=600 or max_attempts not in [1,2,3]:
        raise BError('DOWNLOAD_LIMIT','Use <=600 seconds and 1–3 attempts')
    target=Path(target);target.parent.mkdir(parents=True,exist_ok=True)
    part=target.with_suffix(target.suffix+'.part');meta_path=target.with_suffix(target.suffix+'.download.json')
    key=hashlib.sha256(url.encode()).hexdigest()
    meta=read_json(meta_path) if meta_path.exists() else {'url_sha256':key,'attempts':[],'pause_used':False}
    if meta.get('url_sha256')!=key:raise BError('DOWNLOAD_SOURCE_CHANGED','Partial download belongs to another URL')
    if target.exists():
        if meta.get('complete') and digest(target)==meta.get('file_sha256'):
            if expected_sha256 and meta['file_sha256']!=expected_sha256:raise BError('HASH_MISMATCH','Downloaded source differs from registered hash')
            return {**meta,'reused_complete_file':True}
        raise BError('OUTPUT_EXISTS','Do not overwrite an unverified existing media file')
    open_url=opener or urllib.request.build_opener(HTTPSRedirect()).open
    started=time.perf_counter();invocation_bytes=0

    def save_partial():
        meta['saved_bytes']=part.stat().st_size if part.exists() else 0
        meta['prefix_sha256']=digest(part) if part.exists() else None
        meta['complete']=False;write_json(meta_path,meta)

    def archive_partial(reason):
        if part.exists():part.rename(part.with_name(part.name+'.discarded-'+uuid.uuid4().hex[:8]))
        meta['attempts'].append({'event':'restart','reason':reason})
        for k in ['saved_bytes','prefix_sha256','etag','last_modified','expected_total']:meta.pop(k,None)

    for attempt in range(max_attempts):
        offset=0
        if part.exists():
            if meta.get('saved_bytes')!=part.stat().st_size or meta.get('prefix_sha256')!=digest(part):
                raise BError('DOWNLOAD_PARTIAL_CHANGED','Partial bytes changed; inspect them instead of combining data')
            validator=meta.get('etag') or meta.get('last_modified')
            if validator:offset=part.stat().st_size
            else:archive_partial('No stable HTTP validator available')
        if time.perf_counter()-started>=timeout_sec:
            save_partial();raise BError('DOWNLOAD_TIMEOUT','Download time budget exhausted; partial saved')
        headers={'Accept-Encoding':'identity','User-Agent':'B-English-Localizer/1.0'}
        if offset:headers.update({'Range':f'bytes={offset}-','If-Range':meta.get('etag') or meta['last_modified']})
        entry={'attempt':len(meta['attempts'])+1,'requested_offset':offset,'status':'started'}
        meta['attempts'].append(entry)
        try:
            with open_url(urllib.request.Request(url,headers=headers),timeout=min(15,timeout_sec)) as response:
                status=response.status;entry['http_status']=status
                if response.headers.get('Content-Encoding','identity')!='identity':
                    raise BError('DOWNLOAD_ENCODING','Unexpected content encoding; cannot verify byte ranges')
                if offset and status==200:
                    archive_partial('Server ignored Range or representation changed');offset=0
                if status==206:
                    match=re.fullmatch(r'bytes (\d+)-(\d+)/(\d+)',response.headers.get('Content-Range',''))
                    if not match or int(match[1])!=offset:raise BError('DOWNLOAD_RANGE','Content-Range does not match requested offset')
                    start,end,total=map(int,match.groups())
                    if not 0<=start<=end<total:raise BError('DOWNLOAD_RANGE','Invalid byte interval')
                    if offset and meta.get('expected_total') not in [None,total]:raise BError('DOWNLOAD_CHANGED','Source length changed during resume')
                elif status==200:
                    value=response.headers.get('Content-Length');total=int(value) if value is not None else None
                else:raise BError('DOWNLOAD_HTTP',f'Unexpected HTTP status {status}')
                if total is not None and total>max_bytes:raise BError('DOWNLOAD_SIZE','Full source exceeds configured download limit')
                etag=response.headers.get('ETag');etag=etag if etag and not etag.startswith('W/') else None
                modified=response.headers.get('Last-Modified')
                if offset and meta.get('etag') and etag!=meta['etag']:raise BError('DOWNLOAD_CHANGED','Source ETag changed during resume')
                if offset and not meta.get('etag') and meta.get('last_modified')!=modified:raise BError('DOWNLOAD_CHANGED','Source Last-Modified changed during resume')
                meta.update({'etag':etag,'last_modified':modified,'expected_total':total})
                with part.open('ab' if offset else 'wb') as f:
                    while True:
                        if time.perf_counter()-started>=timeout_sec:raise BError('DOWNLOAD_TIMEOUT','Download time budget exhausted')
                        data=response.read(64*1024)
                        if not data:break
                        if f.tell()+len(data)>max_bytes:raise BError('DOWNLOAD_SIZE','Download exceeded byte limit')
                        f.write(data);invocation_bytes+=len(data)
                        if pause_once_bytes and not meta.get('pause_used') and f.tell()>=pause_once_bytes and (total is None or f.tell()<total):
                            meta['pause_used']=True
                            raise BError('DOWNLOAD_PAUSED','Requested one-time download checkpoint reached')
                if total is not None and part.stat().st_size!=total:
                    raise IncompleteRead(b'',total-part.stat().st_size)
            save_partial()
            sha=digest(part)
            if expected_sha256 and sha!=expected_sha256:raise BError('HASH_MISMATCH','Full source SHA-256 mismatch')
            part.replace(target)
            entry['status']='completed';meta.update({'complete':True,'file_sha256':sha,'file_bytes':target.stat().st_size,
                'last_invocation_bytes':invocation_bytes,'last_invocation_elapsed_sec':time.perf_counter()-started})
            write_json(meta_path,meta);return meta
        except Exception as exc:
            entry['status']='paused' if getattr(exc,'code',None)=='DOWNLOAD_PAUSED' else 'failed'
            entry['error_type']=type(exc).__name__;entry['error_code']=getattr(exc,'code',None)
            if isinstance(exc,urllib.error.HTTPError):entry['http_status']=exc.code
            save_partial()
            transient=(isinstance(exc,(urllib.error.URLError,TimeoutError,IncompleteRead,ConnectionError))
                       and (not isinstance(exc,urllib.error.HTTPError) or exc.code in [429,500,502,503,504]))
            if not transient or attempt==max_attempts-1 or time.perf_counter()-started>=timeout_sec:raise
            time.sleep(.5)
    raise BError('DOWNLOAD_FAILED','No complete response')
