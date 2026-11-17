"""mocks 共享的视频指纹与输入路径辅助。

**这是内部模块，不是节点 mock**：文件名以下划线开头，test_mock_skeleton 的
_mock_module_names() 会排除 `_*` 模块，因此不会产生「未登记的 mock 模块」告警。

集中实现的原因：probe_input、asr_diarize、translate_blocks 三个 mock 都需要
「定位工作目录下的输入视频」与「取前 64KB 的 SHA-256 指纹」，重复三份容易漏改。
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from contracts import GraphState
from utils.paths import artifact_path

HEAD_BYTES = 64 * 1024


def head_sha256(path: Path) -> str:
    """返回文件前 HEAD_BYTES 字节的 SHA-256。"""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        digest.update(handle.read(HEAD_BYTES))
    return digest.hexdigest()


def input_path(state: GraphState) -> Path:
    """定位工作目录根目录下的输入视频；不合法或不存在时抛出。"""
    filename = state.input_video
    if not filename:
        raise ValueError("mocks: state.input_video 为空")
    if not Path(filename).is_absolute() and ("/" in filename or "\\" in filename):
        raise ValueError("mocks: input_video 必须是文件名或原视频绝对路径")
    if Path(filename).suffix.lower() != ".mp4":
        raise ValueError("mocks: 基础版只接受本地 MP4")

    path = Path(artifact_path("input_video", filename))
    if not path.is_file():
        raise FileNotFoundError(f"mocks: 输入视频不存在: {path}")
    return path


def matches_source(path: Path, source: dict) -> bool:
    """字节数与前 64KB 指纹都与 source 一致时返回 True。"""
    if path.stat().st_size != source["size_bytes"]:
        return False
    return head_sha256(path) == source["head_sha256"]


def describe_mismatch(path: Path, source: dict) -> str:
    """生成指纹不一致的可读原因，供 warning 使用。"""
    actual_size = path.stat().st_size
    if actual_size != source["size_bytes"]:
        return f"字节数不符（记录 {source['size_bytes']}，实际 {actual_size}）"
    if head_sha256(path) != source["head_sha256"]:
        return "前 64KB 哈希不符"
    return "指纹一致"
