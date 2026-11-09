# 数据字段修订记录

## v1.0 2026-11-09
### 修改内容
所有数据模型的定义、接口文档生成脚本
### 修改原因
项目初始化

## v1.0.1 2026-11-09
### 修改内容
- `state.py` 中 `GraphState` 由 `TypedDict(total=False)` 改为 Pydantic `BaseModel`，字段均为可选默认 `None`，`extra="forbid"`
### 修改原因
- 统一 `contracts/` 与 `utils/io.py` 的类型体系，使 `GraphState` 可被 Pydantic 校验、可被 `read_artifact`/`write_artifact` 直接处理，消除未来落盘/检查点时的嵌套模型退化风险。
### 修改影响
- 节点内 State 访问由下标改属性、缺失判断由 `in` 改 `is not None`

## v1.0.2 2026-11-09

### 修改内容

- `tts.py` 中`TTSClip`类的文档说明。不修改其实际字段。

### 修改原因

- 修正`tts_clips`承载了两种磁盘形态的问题。

### 修改影响

- 重新生成`interface.md`，对`TTSClip`类本身没有影响。