"""File exchange for an operator-mediated school model tool, not a network API."""
import hashlib
import json
import os
from pathlib import Path


class SchoolModelPending(RuntimeError):
    pass


def request_json(*, instruction, payload, output_format):
    directory = os.getenv('DEEPSEEK_BRIDGE_DIR', '').strip()
    if not directory:
        raise ValueError('学校工具模式需设置 DEEPSEEK_BRIDGE_DIR，使用本机不上传的工作目录。')
    folder = Path(directory).resolve()
    folder.mkdir(parents=True, exist_ok=True)
    request = {'instruction': instruction, 'payload': payload, 'output_format': output_format}
    encoded = json.dumps(request, ensure_ascii=False, sort_keys=True).encode('utf-8')
    key = hashlib.sha256(encoded).hexdigest()
    path = folder / f'{key}.request.json'
    # The digest covers the exact instructions/data; a response is never reused
    # for a changed request. No model invocation or credential is embedded here.
    if not path.exists():
        with path.open('x', encoding='utf-8') as handle:
            handle.write(encoded.decode('utf-8'))
    response = folder / f'{key}.response.json'
    if not response.is_file():
        raise SchoolModelPending(f'SCHOOL_MODEL_PENDING: 学校工具待处理请求 {path}')
    if response.stat().st_size > 1024 * 1024:
        raise ValueError('学校工具响应过大。')
    result = json.loads(response.read_text(encoding='utf-8'))
    if not isinstance(result, dict):
        raise ValueError('学校工具响应必须是 JSON 对象。')
    return result
