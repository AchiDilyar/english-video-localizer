import json
from pathlib import Path

import pytest
from nodes.asr_diarize.pipeline.common import BError
from nodes.probe_input import source_store, youtube


def fake_download(url, folder, **kwargs):
    target = Path(folder) / "video.mp4"
    target.write_bytes(b"download-adapter-test")
    return target, {"url": url, "file": target.name, "rights": "not_automatically_licensed"}


def test_youtube_keeps_original_in_shared_source_and_reuses_it(tmp_path, monkeypatch):
    calls = []

    def download(*args, **kwargs):
        calls.append(args[0])
        return fake_download(*args, **kwargs)

    monkeypatch.setattr(source_store, "download_input", download)
    cache = tmp_path / "sources"
    first = tmp_path / "job1"
    first.mkdir()
    second = tmp_path / "job2"
    second.mkdir()
    one = youtube.prepare_youtube_input("https://youtu.be/BaW_jenozKc", first, source_dir=cache)
    two = youtube.prepare_youtube_input(
        "https://www.youtube.com/watch?v=BaW_jenozKc", second, source_dir=cache
    )
    assert one == two == str((cache / "BaW_jenozKc/video.mp4").resolve())
    assert len(calls) == 1 and Path(one).read_bytes() == b"download-adapter-test"
    assert not (first / "input.mp4").exists() and not (second / "input.mp4").exists()
    receipt = json.loads((first / "logs/input-download.json").read_text())
    assert receipt["source_video"] == one


def test_existing_task_input_is_never_replaced(tmp_path, monkeypatch):
    target = tmp_path / "input.mp4"
    target.write_bytes(b"keep")
    monkeypatch.setattr(source_store, "download_input", fake_download)
    source = youtube.prepare_youtube_input(
        "https://youtu.be/BaW_jenozKc", tmp_path, source_dir=tmp_path / "sources"
    )
    assert Path(source) != target and target.read_bytes() == b"keep"


def test_changed_source_is_not_silently_replaced_or_redownloaded(tmp_path, monkeypatch):
    monkeypatch.setattr(source_store, "download_input", fake_download)
    source, _ = source_store.acquire_youtube("https://youtu.be/BaW_jenozKc", tmp_path)
    source.write_bytes(b"changed")
    monkeypatch.setattr(
        source_store, "download_input", lambda *args, **kwargs: pytest.fail("No silent redownload")
    )
    with pytest.raises(ValueError, match="改变"):
        source_store.acquire_youtube("https://youtu.be/BaW_jenozKc", tmp_path)


@pytest.mark.parametrize(
    "url",
    [
        "https://www.youtube.com/shorts/",
        "https://example.org/video",
        "https://youtube.com/playlist?list=x",
    ],
)
def test_invalid_url_rejected_before_network(tmp_path, monkeypatch, url):
    monkeypatch.setattr(
        source_store, "download_input", lambda *a, **kw: pytest.fail("must not download")
    )
    with pytest.raises(BError):
        youtube.prepare_youtube_input(url, tmp_path, source_dir=tmp_path / "sources")


def test_cli_download_only_writes_source_directory(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(source_store, "download_input", fake_download)
    assert (
        youtube.main(["https://youtu.be/BaW_jenozKc", "--output-dir", str(tmp_path / "sources")])
        == 0
    )
    assert (tmp_path / "sources/BaW_jenozKc/video.mp4").is_file()
    assert "视频已下载" in capsys.readouterr().out
