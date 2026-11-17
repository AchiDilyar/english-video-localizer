"""YouTube acquisition before graph execution; no model or TTS calls."""
import argparse
import json
import shutil
from pathlib import Path
from tempfile import TemporaryDirectory

from nodes.asr_diarize.pipeline.video_inputs import download_input, youtube_url


def prepare_youtube_input(url, work_dir, *, filename='input.mp4', max_height=720):
    """Return the local filename expected by F's unchanged GraphState contract."""
    url=youtube_url(url)
    work=Path(work_dir).resolve()
    if not work.is_dir():raise FileNotFoundError(f'工作目录不存在: {work}')
    if Path(filename).name!=filename or Path(filename).suffix.lower()!='.mp4':
        raise ValueError('YouTube target must be a plain MP4 filename')
    target=work/filename
    if target.exists():raise FileExistsError(f'输入文件已存在，请使用新任务目录: {target}')
    with TemporaryDirectory(prefix='.youtube-',dir=work) as temporary:
        downloaded,metadata=download_input(url,temporary,allow_network=True,max_height=max_height)
        if not downloaded.is_file() or not downloaded.stat().st_size:
            raise ValueError('YouTube download did not produce a nonempty video')
        # Exclusive creation also prevents replacing a file created mid-download.
        created=False
        try:
            with target.open('xb') as output:
                created=True
                with downloaded.open('rb') as source:shutil.copyfileobj(source,output)
            logs=work/'logs';logs.mkdir(exist_ok=True)
            (logs/'input-download.json').write_text(json.dumps({**metadata,'file':filename},ensure_ascii=False,indent=2),encoding='utf-8')
        except Exception:
            if created:target.unlink(missing_ok=True)
            raise
    return filename


def main(argv=None):
    parser=argparse.ArgumentParser(description='只下载单条公开YouTube视频，不调用翻译或配音API')
    parser.add_argument('url',help='YouTube视频链接（不是播放列表）')
    parser.add_argument('--output-dir',required=True,type=Path)
    parser.add_argument('--max-height',type=int,default=720)
    args=parser.parse_args(argv)
    if not 144<=args.max_height<=2160:parser.error('--max-height must be between 144 and 2160')
    args.output_dir.mkdir(parents=True,exist_ok=True)
    name=prepare_youtube_input(args.url,args.output_dir,max_height=args.max_height)
    print(f'视频已下载: {(args.output_dir/name).resolve()}')
    return 0


if __name__=='__main__':raise SystemExit(main())
