from pathlib import Path
import json
import pytest

from nodes.probe_input import youtube
from nodes.asr_diarize.pipeline.common import BError
from nodes.asr_diarize.pipeline.video_inputs import youtube_url


def fake_download(url,folder,**kwargs):
    target=Path(folder)/'video.mp4';target.write_bytes(b'download-adapter-test')
    return target,{'url':url,'file':target.name,'rights':'not_automatically_licensed'}


def test_youtube_download_promotes_to_standard_input_and_records_origin(tmp_path,monkeypatch):
    monkeypatch.setattr(youtube,'download_input',fake_download)
    assert youtube.prepare_youtube_input('https://youtu.be/BaW_jenozKc',tmp_path)=='input.mp4'
    assert (tmp_path/'input.mp4').read_bytes()==b'download-adapter-test'
    receipt=json.loads((tmp_path/'logs/input-download.json').read_text())
    assert receipt['url']=='https://www.youtube.com/watch?v=BaW_jenozKc'
    assert receipt['file']=='input.mp4'
    assert not list(tmp_path.glob('.youtube-*'))


def test_existing_input_is_never_replaced_or_downloaded(tmp_path,monkeypatch):
    target=tmp_path/'input.mp4';target.write_bytes(b'keep')
    monkeypatch.setattr(youtube,'download_input',lambda *a,**kw:pytest.fail('must not download'))
    with pytest.raises(FileExistsError):youtube.prepare_youtube_input('https://youtu.be/BaW_jenozKc',tmp_path)
    assert target.read_bytes()==b'keep'


def test_file_created_during_download_is_preserved(tmp_path,monkeypatch):
    def race(*args,**kwargs):
        (tmp_path/'input.mp4').write_bytes(b'other-writer')
        return fake_download(*args,**kwargs)
    monkeypatch.setattr(youtube,'download_input',race)
    with pytest.raises(FileExistsError):youtube.prepare_youtube_input('https://youtu.be/BaW_jenozKc',tmp_path)
    assert (tmp_path/'input.mp4').read_bytes()==b'other-writer'


@pytest.mark.parametrize('url',['https://www.youtube.com/shorts/','https://example.org/video','https://youtube.com/playlist?list=x'])
def test_invalid_url_rejected_before_network(tmp_path,monkeypatch,url):
    monkeypatch.setattr(youtube,'download_input',lambda *a,**kw:pytest.fail('must not download'))
    with pytest.raises(BError):youtube.prepare_youtube_input(url,tmp_path)


def test_cli_download_only_does_not_call_graph(tmp_path,monkeypatch,capsys):
    monkeypatch.setattr(youtube,'download_input',fake_download)
    assert youtube.main(['https://youtu.be/BaW_jenozKc','--output-dir',str(tmp_path/'job')])==0
    assert (tmp_path/'job/input.mp4').is_file()
    assert '视频已下载' in capsys.readouterr().out
