"""Run bounded synthetic checks, retain raw evidence in a new local jobs directory."""
from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import time

import b_media as m


def main() -> None:
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
    started = time.perf_counter()
    root = Path(__file__).resolve().parents[1]
    output = root / 'jobs' / ('B-media-' + datetime.now().strftime('%Y%m%d-%H%M%S'))
    output.mkdir(parents=True, exist_ok=False)
    env = m.environment(None, None)
    (output / 'environment.json').write_text(json.dumps(env, indent=2) + '\n', encoding='utf-8')
    ffmpeg = m.tool_path('ffmpeg')
    ffprobe = m.tool_path('ffprobe')
    fixture = output / 'synthetic-offset.mov'
    command = [ffmpeg, '-hide_banner', '-loglevel', 'error', '-nostdin', '-n',
               '-f', 'lavfi', '-i', 'color=c=black:s=160x120:r=25:d=2',
               '-itsoffset', '0.25', '-f', 'lavfi', '-i', 'sine=frequency=880:sample_rate=48000:duration=1',
               '-c:v', 'mpeg4', '-c:a', 'pcm_s16le', str(fixture)]
    m.run(command)
    prepared = m.extract(fixture, output / 'prepared', ffprobe, ffmpeg, None, None, 30)
    test_command = [sys.executable, '-m', 'unittest', 'discover', '-s', 'tests', '-p', 'test_b_media.py', '-v']
    child_env = dict(os.environ, PYTHONIOENCODING='utf-8',
                     B_MEDIA_TEST_ARTIFACT_DIR=str(output / 'integration'))
    result = subprocess.run(test_command, cwd=root, env=child_env, capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=120)
    (output / 'tests.stdout.txt').write_text(result.stdout, encoding='utf-8')
    (output / 'tests.stderr.txt').write_text(result.stderr, encoding='utf-8')
    skipped = 'skipped' in result.stderr.lower()
    record = {
        'created_at_utc': datetime.now(timezone.utc).isoformat(),
        'scope': 'synthetic media preparation; no speech recognition or agent execution',
        'python': sys.version, 'platform': platform.platform(),
        'commands': {'fixture': command, 'tests': test_command},
        'source_sha256': prepared['source_sha256'], 'audio_sha256': prepared['audio_sha256'],
        'test_exit_code': result.returncode, 'skipped_detected': skipped,
        'tests_passed_without_skips': result.returncode == 0 and not skipped,
        'elapsed_sec': time.perf_counter() - started,
        'peak_gpu_memory': None, 'api_calls': 0, 'api_cost': 0,
        'speech_accuracy_evaluated': False, 'langgraph_executed': False,
        'deepseek_used': False, 'run_directory': str(output),
    }
    provenance = root / '.tools/ffmpeg/provenance.json'
    if provenance.exists():
        record['ffmpeg_download'] = json.loads(provenance.read_text(encoding='utf-8'))
    (output / 'verification.json').write_text(json.dumps(record, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(record, indent=2))
    print(result.stderr)
    if not record['tests_passed_without_skips']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
