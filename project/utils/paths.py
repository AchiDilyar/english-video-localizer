"""名称映射与绝对路径生成。

对应 architecture.md §6.1 与 dataflow.md §5.1。
路径规则从 utils/artifacts.py 的产物规格表获取，事实源为 dataflow.md 第 3 节产物表。
"""

from __future__ import annotations

from pathlib import Path

from .artifacts import ARTIFACT_SPECS, ArtifactSpec


_work_dir: Path | None = None


def set_work_dir(work_dir: str) -> None:
    """由 CLI 在启动时调用一次，设置本次任务的全局工作目录。"""
    global _work_dir
    _work_dir = Path(work_dir).resolve()


def get_work_dir() -> str:
    """返回当前工作目录；未设置时抛出异常。"""
    if _work_dir is None:
        raise RuntimeError("工作目录未设置，请先调用 set_work_dir()")
    return str(_work_dir)


def _get_spec(name: str) -> ArtifactSpec:
    spec = ARTIFACT_SPECS.get(name)
    if spec is None:
        raise KeyError(f"未知的产物名称: {name!r}")
    return spec


def _resolve(name: str, filename: str | None) -> Path:
    if _work_dir is None:
        raise RuntimeError("工作目录未设置，请先调用 set_work_dir()")
    spec = _get_spec(name)

    if spec.path_kind == "fixed":
        if filename is not None:
            raise ValueError(f"产物 {name!r} 路径已确定，不应提供 filename")
        return (_work_dir / spec.path).resolve()

    if spec.path_kind == "dir":
        if filename is None:
            raise ValueError(f"产物 {name!r} 路径不确定，必须提供 filename")
        return (_work_dir / spec.path / filename).resolve()

    raise ValueError(f"未知的路径类型: {spec.path_kind!r}")


def artifact_path(name: str, filename: str | None = None) -> str:
    """根据名称返回产物的绝对路径。

    - 路径确定的产物：filename 为 None，返回完整绝对路径。
    - 路径不确定的产物：filename 必须提供，返回名称对应文件夹下的文件绝对路径。
    - 路径规则从产物规格表（utils/artifacts.py）按名称获取，事实源为 dataflow.md 第 3 节产物表。
    - 名称必须存在于产物规格表中，否则抛出异常。
    """
    return str(_resolve(name, filename))