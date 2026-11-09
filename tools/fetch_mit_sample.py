"""Prepare the licensed 45-second MIT OCW English test excerpt requested by user."""
from pathlib import Path
import hashlib
import json
import subprocess
import time

ROOT = Path(__file__).resolve().parents[1]
PAGE = 'https://ocw.mit.edu/courses/6-0001-introduction-to-computer-science-and-programming-in-python-fall-2016/resources/lecture-1-what-is-computation/'
URL = 'https://archive.org/download/MIT6.0001F16/MIT6_0001F16_Lecture_01_300k.mp4'


def main():
    folder = ROOT / 'media' / 'mit_ocw_6_0001_lecture1'
    folder.mkdir(parents=True, exist_ok=True)
    output = folder / 'mit_lecture1_0060_0105.mp4'
    if output.exists():
        raise SystemExit('Sample exists; refusing to replace it.')
    ffmpeg = ROOT / '.tools' / 'ffmpeg' / 'bin' / 'ffmpeg.exe'
    command = [str(ffmpeg), '-hide_banner', '-loglevel', 'error', '-nostdin', '-n',
               '-rw_timeout', '15000000', '-ss', '60', '-i', URL,
               '-t', '45', '-map', '0:v:0', '-map', '0:a:0',
               '-c:v', 'libx264', '-preset', 'fast', '-crf', '23',
               '-c:a', 'aac', '-b:a', '96k', '-movflags', '+faststart', str(output)]
    start = time.perf_counter()
    try:
        result = subprocess.run(command, capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=180)
        record = {'ok': result.returncode == 0, 'returncode': result.returncode,
                  'stderr': result.stderr, 'elapsed_sec': time.perf_counter() - start,
                  'source_page': PAGE, 'source_media_url': URL, 'command': command,
                  'source_start_sec': 60, 'requested_duration_sec': 45,
                  'license': 'CC BY-NC-SA 4.0',
                  'license_url': 'https://creativecommons.org/licenses/by-nc-sa/4.0/',
                  'license_evidence': PAGE,
                  'changes': 'Excerpt 00:01:00–00:01:45; video/audio transcoded; full original not downloaded.',
                  'attribution': 'Ana Bell. 6.0001 Introduction to Computer Science and Programming in Python. Fall 2016. Massachusetts Institute of Technology: MIT OpenCourseWare.',
                  'sha256': hashlib.sha256(output.read_bytes()).hexdigest() if result.returncode == 0 else None}
    except subprocess.TimeoutExpired:
        record = {'ok': False, 'reason': '180-second timeout', 'elapsed_sec': time.perf_counter() - start,
                  'source_page': PAGE, 'source_media_url': URL, 'command': command}
    (folder / 'acquisition.json').write_text(json.dumps(record, indent=2) + '\n', encoding='utf-8')
    (folder / 'ATTRIBUTION.txt').write_text(
        'Ana Bell. 6.0001 Introduction to Computer Science and Programming in Python. Fall 2016.\n'
        'Massachusetts Institute of Technology: MIT OpenCourseWare.\n' + PAGE + '\n'
        'License: CC BY-NC-SA 4.0. https://creativecommons.org/licenses/by-nc-sa/4.0/\n'
        'Changes: excerpt 00:01:00–00:01:45, transcoded to MP4/AAC for non-commercial coursework testing.\n'
        'Not TED. No endorsement by MIT or the instructor. Preserve this attribution with shared excerpts.\n', encoding='utf-8')
    print(json.dumps(record, indent=2))
    if not record['ok']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
