# 项目设计相关文档修订记录

## workflow.md v1.0  2026-11-08
### 修改内容
- 第一版完整内容
### 修改原因
- 初始化项目设计文档

## dataflow.md v1.0  2026-11-08
### 修改内容
- 第一版完整内容
### 修改原因
- 初始化项目设计文档

## architecture.md v1.0  2026-11-08
### 修改内容
- 第一版完整内容
### 修改原因
- 初始化项目设计文档

## collaboration.md v1.0  2026-11-08
### 修改内容
- 第一版完整内容
### 修改原因
- 初始化项目设计文档

## dataflow.md v1.0.1 2026-11-09
### 修改内容
- `GraphState` 从 `TypedDict` 改为 Pydantic `BaseModel`
### 修改原因
- 统一 `contracts/` 与 `utils/io.py` 的类型体系，使 `GraphState` 可被 Pydantic 校验、可被 `read_artifact`/`write_artifact` 直接处理，消除未来落盘/检查点时的嵌套模型退化风险。

## architecture.md v1.0.1 2026-11-09
### 修改内容
- `GraphState` 从 `TypedDict` 改为 Pydantic `BaseModel`
### 修改原因
- 统一 `contracts/` 与 `utils/io.py` 的类型体系，使 `GraphState` 可被 Pydantic 校验、可被 `read_artifact`/`write_artifact` 直接处理，消除未来落盘/检查点时的嵌套模型退化风险。