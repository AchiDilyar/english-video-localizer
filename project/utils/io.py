"""结构化数据读写与 Pydantic 校验。

对应 architecture.md §6.2 与 dataflow.md §5.2。
校验类型从 utils/artifacts.py 的产物规格表获取，事实源为 dataflow.md 第 3 节产物表。
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from pydantic import TypeAdapter

from .artifacts import ARTIFACT_SPECS
from .paths import artifact_path


@lru_cache(maxsize=None)
def _get_validator(name: str) -> TypeAdapter:
    spec = ARTIFACT_SPECS.get(name)
    if spec is None:
        raise KeyError(f"未知的产物名称: {name!r}")
    if spec.type_ is None:
        raise ValueError(
            f"产物 {name!r} 不是结构化 JSON 产物，不能使用 read_artifact/write_artifact；"
            f"请用 artifact_path 获取路径后交给对应工具处理"
        )
    return TypeAdapter(spec.type_)


def read_artifact(
    name: str,
    filename: str | None = None,
):
    """按名称读取 JSON 产物，按产物规格表登记的校验类型做 Pydantic 校验后返回。

    - 校验类型从产物规格表（utils/artifacts.py）按名称获取，事实源为 dataflow.md 第 3 节产物表。
    - 返回类型由名称决定。
    - 名称未登记，或该产物的校验类型为 None（二进制产物）时抛出异常。
    """
    validator = _get_validator(name)
    path = Path(artifact_path(name, filename))
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    return validator.validate_python(data)


def write_artifact(
    name: str,
    obj,
    filename: str | None = None,
) -> None:
    """按名称写入 JSON 产物，写入前按产物规格表登记的校验类型做 Pydantic 校验。

    - obj 可以是模型实例，也可以是裸 dict / list；校验后统一转化为模型实例再序列化。
    - 写入磁盘 JSON 必须为通过校验的合法结构。
    - 名称未登记，或该产物的校验类型为 None（二进制产物）时抛出异常。
    """
    validator = _get_validator(name)
    validated = validator.validate_python(obj)
    path = Path(artifact_path(name, filename))
    with path.open("w", encoding="utf-8") as f:
        json.dump(
            validator.dump_python(validated, mode="json"),
            f,
            ensure_ascii=False,
            indent=2,
        )