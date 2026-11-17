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

## v1.0.3 2026-11-17

### 修改内容
- 新增 EnvironmentAudio、MixedAudio；GraphState 新增 environment_audio、mixed_audio，可选、默认 None。
- 同步 contracts 导出、生成脚本并重新生成 interfaces.md。
- dataflow.md 及 utils/artifacts.py 登记 environment_bed、environment_audio、mixed_track、mixed_audio。
### 修改原因及影响
- 按 F 最新主图让 b_environment 与翻译链并行，mix_background 汇合后合成；不再以独立 BCDE 图绕开主图。
- 固定路径不入 State，回执在 State 传递并经公共工具写盘；只新增增量产物，不覆盖 dub.wav/source.wav。
- 下游 None 安全，增量异常返回空增量后基础链继续；测试包含正常、缺失、分离失败、混音失败及陈旧混音拒用。
