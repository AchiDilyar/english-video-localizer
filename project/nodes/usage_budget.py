"""Conservative local attempted-use ceilings, including failed requests."""
import json
import os
import threading
from pathlib import Path
from datetime import datetime,timezone

_lock=threading.Lock()


def reserve(kind,units=1,label=''):
    filename=os.getenv('LOCALIZER_BUDGET_FILE')
    if not filename:return
    if type(units) is not int or units<0:raise ValueError('Invalid budget units')
    with _lock:
        path=Path(filename)
        data=json.loads(path.read_text(encoding='utf-8'))
        if kind not in data['limits']:raise ValueError('Unregistered paid resource')
        used=data['used'].get(kind,0)
        if used+units>data['limits'][kind]:
            raise RuntimeError(f'BUDGET_LIMIT: {kind} {used}+{units}>{data["limits"][kind]}')
        data['used'][kind]=used+units
        data.setdefault('events',[]).append({'kind':kind,'units':units,'label':label,
            'time_utc':datetime.now(timezone.utc).isoformat(),'billing':'unknown; attempted usage reserved'})
        temporary=path.with_suffix('.tmp')
        temporary.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
        temporary.replace(path)
