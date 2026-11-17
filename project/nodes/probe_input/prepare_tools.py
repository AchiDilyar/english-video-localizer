"""Download a project-local portable build; never changes PATH or system settings."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
import urllib.request


def main() -> None:
    root = Path(__file__).resolve().parents[3] / '.tools' / 'ffmpeg'
    root.mkdir(parents=True, exist_ok=True)
    if (root / 'bin' / 'ffmpeg.exe').exists():
        raise SystemExit('FFmpeg already exists; not overwriting it.')
    # Windows bsdtar supports 7z; the release 7z archive is much smaller than ZIP.
    tar = shutil.which('tar')
    if not tar:
        raise SystemExit('tar is required to read the portable 7z archive.')
    url = 'https://github.com/GyanD/codexffmpeg/releases/download/9.0.2/ffmpeg-9.0.2-essentials_build.7z'
    started = time.perf_counter()
    # Published digest from the build publisher's official release assets page.
    checksum = '4705843ccaaf54257c16ad90f3e952ece33c17df964ecf7bfdbb0f49c7171077'
    if len(checksum) != 64 or any(c not in '0123456789abcdef' for c in checksum):
        raise ValueError('Invalid published SHA-256')
    archive = root / 'download-mirror.7z.part'
    digest = hashlib.sha256()
    size = 0
    try:
        with urllib.request.urlopen(url, timeout=30) as response, archive.open('wb') as target:
            while block := response.read(1024 * 1024):
                size += len(block)
                if size > 60 * 1024 * 1024 or time.perf_counter() - started > 180:
                    raise RuntimeError('Download exceeded 60 MiB or 180 seconds')
                digest.update(block)
                target.write(block)
        if digest.hexdigest() != checksum:
            raise ValueError('Archive does not match published SHA-256; nothing executed')
        extracted = []
        listing = subprocess.run([tar, '-tf', str(archive)], capture_output=True, text=True, check=True, timeout=30)
        with tempfile.TemporaryDirectory(prefix='unpack-', dir=root) as temporary:
            for name in listing.stdout.splitlines():
                # Select only known files and generate destination paths ourselves.
                basename = name.rsplit('/', 1)[-1]
                if basename not in {'ffmpeg.exe', 'ffprobe.exe', 'LICENSE', 'LICENSE.txt', 'README.txt'}:
                    continue
                if name.startswith(('/', '\\')) or '..' in name.replace('\\', '/').split('/') or ':' in name:
                    raise ValueError('Unsafe archive member')
                subprocess.run([tar, '-xf', str(archive.resolve()), '-C', temporary, '--', name], check=True, timeout=30)
                source = Path(temporary) / name
                if source.is_symlink() or not source.is_file() or not source.resolve().is_relative_to(Path(temporary).resolve()):
                    raise ValueError('Unsafe extracted file')
                dest = root / ('bin' if basename.endswith('.exe') else 'licenses') / basename
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, dest)
                extracted.append(str(dest.relative_to(root)))
        for name in ['ffmpeg.exe', 'ffprobe.exe']:
            if not (root / 'bin' / name).is_file():
                raise RuntimeError(f'Archive missing {name}')
        record = {'source_url': url, 'archive_sha256': checksum, 'download_bytes': size,
                  'checksum_source': 'https://github.com/GyanD/codexffmpeg/releases/expanded_assets/9.0.2',
                  'elapsed_sec': time.perf_counter() - started, 'files': extracted,
                  'executables_sha256': {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                                         for p in (root / 'bin').glob('*.exe')}}
        (root / 'provenance.json').write_text(json.dumps(record, indent=2) + '\n', encoding='utf-8')
        print(json.dumps(record, indent=2))
    finally:
        archive.unlink(missing_ok=True)


if __name__ == '__main__':
    main()
