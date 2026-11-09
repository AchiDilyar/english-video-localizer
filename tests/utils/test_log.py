"""
utils/log.py 的最小验证。
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from utils.log import setup_logging


def test_setup_logging_writes_file(tmp_path: Path) -> None:
    log_file = tmp_path / "logs" / "run.log"
    setup_logging(str(log_file))

    # 仅用于验证utils.log模块，实际日志禁止自编logger名称，必须按 logging.getLogger(__name__) 规范
    logging.getLogger("demo.alpha").info("hello")
    logging.getLogger("demo.beta").warning("this is warning message")

    text = log_file.read_text(encoding="utf-8")
    assert "demo.alpha" in text and "hello" in text
    assert "[WARNING]" in text and "demo.beta" in text
