"""cli.py 冒烟测试。

仅验证 project/cli.py 自身行为，不联调 nodes/、mocks/、graph/。
运行：uv run pytest tests/smoke/test_cli.py
"""
from __future__ import annotations

import logging
import shutil
from pathlib import Path
import subprocess

import pytest

import cli
import utils.paths


_REPO_ROOT = Path(__file__).resolve().parents[2]
_TMP_ROOT = _REPO_ROOT / "tests" / "tmp" / "cli"

_EXPECTED_SUBDIRS = {
    "audio",
    "segments",
    "translated",
    "tts",
    "subtitles",
    "video",
    "logs",
}


class _FakeGraph:
    """记录 invoke 收到的 State；可注入异常。"""

    def __init__(self) -> None:
        self.calls: list = []
        self.error: Exception | None = None

    def invoke(self, state):
        self.calls.append(state)
        if self.error is not None:
            raise self.error
        return {}


@pytest.fixture(autouse=True)
def _restore_logging():
    """抵消 setup_logging 对 root logger 的修改，避免污染 pytest。"""
    root = logging.getLogger()
    saved_handlers = root.handlers[:]
    saved_level = root.level
    try:
        yield
    finally:
        root.handlers[:] = saved_handlers
        root.setLevel(saved_level)


@pytest.fixture(autouse=True)
def _reset_work_dir(monkeypatch):
    """避免用例间 _work_dir 残留。"""
    monkeypatch.setattr(utils.paths, "_work_dir", None)


@pytest.fixture
def work_dir(request) -> Path:
    """tests/tmp/cli/<用例名>/，先清空再创建。"""
    path = _TMP_ROOT / request.node.name
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True)
    return path


@pytest.fixture
def fake_graph(monkeypatch) -> _FakeGraph:
    """替换 cli.build_graph，返回记录型 fake 图。"""
    fake = _FakeGraph()
    monkeypatch.setattr(cli, "build_graph", lambda: fake)
    return fake


def test_work_dir_missing(work_dir, fake_graph, capsys):
    missing = work_dir / "nope"
    with pytest.raises(FileNotFoundError):
        cli.main(["--work-dir", str(missing)])
    assert "运行失败" in capsys.readouterr().err
    assert fake_graph.calls == []


def test_work_dir_is_file(work_dir, fake_graph, capsys):
    target = work_dir / "afile"
    target.write_text("x", encoding="utf-8")
    with pytest.raises(NotADirectoryError):
        cli.main(["--work-dir", str(target)])
    assert "运行失败" in capsys.readouterr().err


def test_input_missing(work_dir, fake_graph, capsys):
    with pytest.raises(FileNotFoundError) as excinfo:
        cli.main(["--work-dir", str(work_dir)])
    assert "输入视频不存在" in str(excinfo.value)
    assert "运行失败" in capsys.readouterr().err


def test_input_is_directory(work_dir, fake_graph):
    (work_dir / "input.mp4").mkdir()
    with pytest.raises(IsADirectoryError):
        cli.main(["--work-dir", str(work_dir)])


def test_input_missing_has_no_side_effects(work_dir, fake_graph):
    with pytest.raises(FileNotFoundError):
        cli.main(["--work-dir", str(work_dir)])
    assert list(work_dir.iterdir()) == []
    assert not (work_dir / "logs").exists()


def test_workflow_without_final_video(work_dir, fake_graph, capsys):
    (work_dir / "input.mp4").touch()
    rc = cli.main(["--work-dir", str(work_dir)])
    assert rc == 0
    out = capsys.readouterr().out
    assert out.strip() == "工作流已结束，未生成成片。"
    actual_dirs = {p.name for p in work_dir.iterdir() if p.is_dir()}
    assert _EXPECTED_SUBDIRS <= actual_dirs
    assert (work_dir / "logs" / "run.log").exists()
    assert len(fake_graph.calls) == 1
    assert fake_graph.calls[0].input_video == "input.mp4"


def test_reports_existing_final_video(work_dir, fake_graph, capsys, monkeypatch):
    (work_dir / "input.mp4").touch()

    def compose(_state):
        (work_dir / "video" / "final.mp4").write_bytes(b"sample video")

    monkeypatch.setattr(fake_graph, "invoke", compose)
    assert cli.main(["--work-dir", str(work_dir)]) == 0
    assert capsys.readouterr().out.strip() == f"成片已生成: {work_dir / 'video' / 'final.mp4'}"


def test_custom_input(work_dir, fake_graph):
    (work_dir / "custom.mp4").touch()
    rc = cli.main(["--work-dir", str(work_dir), "--input", "custom.mp4"])
    assert rc == 0
    assert fake_graph.calls[0].input_video == "custom.mp4"


def test_default_work_dir_is_cwd(work_dir, fake_graph, monkeypatch):
    (work_dir / "input.mp4").touch()
    monkeypatch.chdir(work_dir)
    rc = cli.main([])
    assert rc == 0
    assert (work_dir / "logs" / "run.log").exists()


def test_graph_exception_logged(work_dir, fake_graph, capsys):
    (work_dir / "input.mp4").touch()
    fake_graph.error = RuntimeError("boom")
    with pytest.raises(RuntimeError) as excinfo:
        cli.main(["--work-dir", str(work_dir)])
    assert "boom" in str(excinfo.value)

    log_text = (work_dir / "logs" / "run.log").read_text(encoding="utf-8")
    assert "RuntimeError" in log_text
    assert "boom" in log_text
    assert "Traceback" in log_text
    assert "运行失败" in capsys.readouterr().err


def test_default_input_missing_in_cwd(work_dir, fake_graph, monkeypatch):
    monkeypatch.chdir(work_dir)
    with pytest.raises(FileNotFoundError) as excinfo:
        cli.main([])
    assert "输入视频不存在" in str(excinfo.value)

def test_run_input_command_default_input(work_dir):
    """在项目根目录通过 run-input 命令行调用，验证默认 --input=input.mp4。

    等效于在项目根目录执行 `uv run run-input --work-dir <tmp>`。
    --work-dir 显式指向 tests/tmp 下的临时目录（默认 `.` 已由进程内用例覆盖）。
    临时目录无 input.mp4，命令应在启动前检查阶段失败，不触发 build_graph，
    因此不联调任何节点。
    """
    result = subprocess.run(
        ["uv", "run", "run-input", "--work-dir", str(work_dir)],
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert result.returncode != 0
    # 默认 --input=input.mp4 拼出 work_dir 下的绝对路径
    assert str(work_dir / "input.mp4") in result.stderr
    assert "运行失败" in result.stderr
    # 检查在创建子目录之前，失败时不应产生任何副作用
    assert list(work_dir.iterdir()) == []