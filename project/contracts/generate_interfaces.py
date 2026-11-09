# project/contracts/generate_interfaces.py
"""从 Pydantic 模型生成 docs/contracts/interfaces.md。

运行：
    python -m project.contracts.generate_interfaces

说明：
- BaseModel 使用 model_json_schema()；
- GraphState 是 TypedDict，使用 TypeAdapter(GraphState).json_schema()；
- JSON Schema 仅作为中间表示，不落盘为额外仓库文件；
- 最终产物为 docs/contracts/interfaces.md，路径由 architecture.md 2.1 登记。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, TypedDict, get_args, get_origin, get_type_hints

from pydantic import BaseModel, TypeAdapter

from . import (
    AudioStreamInfo,
    EditAssets,
    GraphState,
    ManifestEntry,
    MediaInfo,
    PackageManifest,
    Segment,
    TTSClip,
    TranslatedSegment,
    TranslationBlock,
    VideoStreamInfo,
)

BASE_MODELS: list[type[BaseModel]] = [
    MediaInfo,
    VideoStreamInfo,
    AudioStreamInfo,
    Segment,
    TranslationBlock,
    TranslatedSegment,
    TTSClip,
    EditAssets,
    ManifestEntry,
    PackageManifest,
]


def json_schema_for(model: type[BaseModel] | Any) -> dict[str, Any]:
    """返回单个模型的 JSON Schema。"""
    if isinstance(model, type) and issubclass(model, BaseModel):
        return model.model_json_schema()
    return TypeAdapter(model).json_schema()


def all_schemas() -> dict[str, dict[str, Any]]:
    """返回 {模型名: JSON Schema}，含 GraphState。"""
    schemas: dict[str, dict[str, Any]] = {
        model.__name__: json_schema_for(model) for model in BASE_MODELS
    }
    schemas["GraphState"] = json_schema_for(GraphState)
    return schemas


def _type_name(annotation: Any) -> str:
    """把 Python 类型注解渲染为可读字符串。"""
    if annotation is type(None):
        return "None"
    origin = get_origin(annotation)
    if origin is list:
        (item,) = get_args(annotation)
        return f"list[{_type_name(item)}]"
    if origin is dict:
        key, value = get_args(annotation)
        return f"dict[{_type_name(key)}, {_type_name(value)}]"
    if origin is not None:
        name = getattr(origin, "__name__", str(origin))
        args = ", ".join(_type_name(a) for a in get_args(annotation))
        return f"{name}[{args}]"
    if isinstance(annotation, type):
        return annotation.__name__
    return str(annotation)


def _base_model_rows(model: type[BaseModel]) -> list[tuple[str, str, str, str]]:
    """返回 BaseModel 的 (字段, 类型, 必填, 约束/说明) 行。"""
    rows: list[tuple[str, str, str, str]] = []
    hints = get_type_hints(model, include_extras=False)
    for name, field in model.model_fields.items():
        annotation = hints.get(name, field.annotation)
        required = "是" if field.is_required() else "否"
        constraints: list[str] = []
        if field.description:
            constraints.append(field.description)
        metadata = field.metadata
        for item in metadata:
            for attr, label in (
                ("pattern", "pattern"),
                ("min_length", "minLength"),
                ("max_length", "maxLength"),
                ("ge", "minimum"),
                ("gt", "exclusiveMinimum"),
                ("le", "maximum"),
                ("lt", "exclusiveMaximum"),
                ("min_items", "minItems"),
                ("max_items", "maxItems"),
            ):
                value = getattr(item, attr, None)
                if value is not None:
                    constraints.append(f"{label}={value}")
        if field.default is not None and not field.is_required():
            constraints.append(f"默认={field.default!r}")
        rows.append((name, _type_name(annotation), required, "；".join(constraints) or "—"))
    return rows


def _typed_dict_rows(model: type[Any]) -> list[tuple[str, str, str, str]]:
    """返回 TypedDict 的 (字段, 类型, 必填, 约束/说明) 行。"""
    rows: list[tuple[str, str, str, str]] = []
    hints = get_type_hints(model, include_extras=False)
    required_keys = getattr(model, "__required_keys__", frozenset())
    for name, annotation in hints.items():
        required = "是" if name in required_keys else "否"
        rows.append((name, _type_name(annotation), required, "—"))
    return rows


def render_markdown() -> str:
    """生成 interfaces.md 内容。"""
    lines: list[str] = [
        "# 接口定义",
        "",
        "> 本文件由 `project/contracts/generate_interfaces.py` 从 Pydantic 模型自动生成，请勿手工修改。",
        "> 字段名、类型、必填性以本文件与 `project/contracts/` 为准。",
        "",
    ]

    for model in BASE_MODELS:
        lines.append(f"## {model.__name__}")
        lines.append("")
        if model.__doc__:
            lines.append(model.__doc__.strip())
            lines.append("")
        lines.append("| 字段 | 类型 | 必填 | 约束/说明 |")
        lines.append("|---|---|---|---|")
        for name, type_name, required, note in _base_model_rows(model):
            lines.append(f"| `{name}` | `{type_name}` | {required} | {note} |")
        lines.append("")
        if model is Segment:
            lines.append("运行时校验（JSON Schema 不表达）：`end_ms > start_ms`。")
            lines.append("")

    lines.append("## GraphState")
    lines.append("")
    lines.append("流程顶层状态容器，`TypedDict`，`total=False`。")
    lines.append("")
    lines.append("| 字段 | 类型 | 必填 | 约束/说明 |")
    lines.append("|---|---|---|---|")
    for name, type_name, required, note in _typed_dict_rows(GraphState):
        lines.append(f"| `{name}` | `{type_name}` | {required} | {note} |")
    lines.append("")
    lines.append(
        "说明：`GraphState` 为 `TypedDict`，JSON Schema 不强制禁止额外键；"
        "节点返回增量的键必须在 `GraphState` 中已定义，该约束由 `graph/` 合并逻辑与测试保证。"
    )
    lines.append("")

    return "\n".join(lines)


def main() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    output = repo_root / "docs" / "contracts" / "interfaces.md"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(render_markdown(), encoding="utf-8")
    print(f"written: {output}")


if __name__ == "__main__":
    main()