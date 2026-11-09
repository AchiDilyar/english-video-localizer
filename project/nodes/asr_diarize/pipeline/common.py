from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
import hashlib
import json
import os
from pathlib import Path
import tempfile


class BError(ValueError):
    def __init__(self, code, message):
        self.code = code
        super().__init__(message)


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Only workflow-owned artifacts are atomically replaced; raw predictions are immutable per job.
    fd, name = tempfile.mkstemp(prefix=path.stem+'-', suffix='.tmp', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(value, f, ensure_ascii=False, indent=2, allow_nan=False)
            f.write('\n')
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        while block := f.read(1024*1024):
            h.update(block)
    return h.hexdigest()


def object_hash(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False,allow_nan=False).encode()).hexdigest()


def milliseconds(value):
    return int((Decimal(str(value))*1000).quantize(Decimal('1'),rounding=ROUND_HALF_UP))


def artifact(job, relative):
    root = Path(job).resolve()
    path = (root / relative).resolve()
    if not path.is_relative_to(root):
        raise BError('PATH_ESCAPE', 'Artifact must stay inside its job')
    return path


def event(job, stage, status, **details):
    record = {'utc':datetime.now(timezone.utc).isoformat(),'stage':stage,'status':status,**details}
    with artifact(job,'events.jsonl').open('a',encoding='utf-8') as f:
        f.write(json.dumps(record,ensure_ascii=False,allow_nan=False)+'\n')
