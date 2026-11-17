"""日志初始化。

对应 architecture.md §2.6。
"""

from __future__ import annotations

import logging
from pathlib import Path

_LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"

def setup_logging(log_file: str, level: int = logging.INFO) -> None:
    """配置 root logger：写文件 + 输出到 stderr。

    由 CLI 在 set_work_dir 后调用一次；创建日志文件所在目录。
    """
    path = Path(log_file).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)

    root = logging.getLogger()
    root.setLevel(level)
    root.handlers.clear()

    formatter = logging.Formatter(_LOG_FORMAT)

    file_handler = logging.FileHandler(path, mode="w", encoding="utf-8")
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)

    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    root.addHandler(stream_handler)