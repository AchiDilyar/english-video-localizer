"""utils/log.py 的最小验证。"""

from __future__ import annotations

import logging
from pathlib import Path

from utils.log import setup_logging


def test_setup_logging_writes_file(tmp_dir: Path) -> None:
    log_file = tmp_dir / "logs" / "run.log"
    setup_logging(str(log_file))

    logging.getLogger("demo.alpha").info("hello")
    logging.getLogger("demo.beta").warning("warn")

    text = log_file.read_text(encoding="utf-8")
    assert "demo.alpha" in text and "hello" in text
    assert "[WARNING]" in text and "demo.beta" in text