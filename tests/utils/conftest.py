"""tests/utils 的共享 fixture。

按 architecture.md §9.1：测试运行时临时创建的目录放在 tests/tmp/。
- 每次 session 仅分配自己的 utils 子目录，不清空其他角色的临时文件；
- 每个测试得到该目录下的独立子目录；
- session 结束后保留内容，便于排查。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from utils.paths import set_work_dir


@pytest.fixture(scope="session")
def _tmp_root(tmp_path_factory) -> Path:
    return tmp_path_factory.mktemp("utils")


@pytest.fixture
def tmp_dir(_tmp_root: Path, request) -> Path:
    """每个测试独立的目录：tests/tmp/<test_id>/。"""
    safe = request.node.nodeid.replace("::", "__").replace("/", "_")
    d = _tmp_root / safe
    d.mkdir(parents=True, exist_ok=True)
    return d


@pytest.fixture
def work_dir(tmp_dir: Path) -> Path:
    """在 tmp_dir 下创建全部子目录，并设为当前工作目录。"""
    for sub in ("audio", "segments", "translated", "tts",
                "subtitles", "cover", "video", "package"):
        (tmp_dir / sub).mkdir(exist_ok=True)
    set_work_dir(str(tmp_dir))
    return tmp_dir
