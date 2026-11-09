# utils 模块

## 概览

| 文件 | 职责 | 依赖 |
|---|---|---|
| `artifacts.py` | 产物规格表：名称 → 路径规则 + 校验类型 | `contracts` |
| `paths.py` | 由名称生成绝对路径 | `artifacts` |
| `io.py` | 结构化 JSON 读写 + Pydantic 校验 | `artifacts`、`paths` |
| `config.py` | 加载 `config/` 下的 TOML | — |
| `log.py` | 初始化 root logger | — |

接口契约（签名、使用约束）见 `architecture.md` 第 6 节。

## 新增产物时的代码更改规则

1. 先改 `dataflow.md` 第 3 节 产物表；
2. 在 `artifacts.py` 的 `ARTIFACT_SPECS` 加一条 `ArtifactSpec`；
3. JSON 产物：`type_` 填 `contracts` 中的模型（单模型或 `list[X]`），`path_kind="fixed"`；
4. 二进制产物：`type_=None`。路径确定用 `"fixed"`；路径不确定用 `"dir"`，
   `path` 为文件夹相对路径，空字符串表示工作目录根；
5. 若为新的数据类，需在 `contracts/__init__.py` 顶层导出；
6. 更新 `tests/utils/test_artifacts.py` 中的 `EXPECTED` / `JSON_ARTIFACTS` /
   `BINARY_ARTIFACTS` 集合，跑测试。

## 各文件要点

### artifacts.py

- `ARTIFACT_SPECS` 是唯一代码来源；`paths.py` 与 `io.py` 都从它读，不各自维护表。
- `ArtifactSpec` 是 frozen Pydantic 模型。`path_kind="fixed"` 时 `path` 不能为空，
  由 `model_validator` 在构造时校验，规格写错在 `import` 阶段即失败。
- `type_` 标注为 `Any` 而非 `type`：`list[Segment]` 是 `types.GenericAlias`，
  `isinstance(list[Segment], type)` 为 False，标注 `type` 会被 Pydantic 拒绝。

### paths.py

- `_work_dir` 是模块级全局状态，由 CLI 在启动时通过 `set_work_dir` 设置一次。
- `fixed` 产物传了 `filename` 抛 `ValueError`（防御性检查）；`dir` 产物未传
  `filename` 也抛 `ValueError`。
- 返回 `.resolve()` 后的绝对路径，不依赖当前工作目录。

### io.py

- `_get_validator` 用 `lru_cache` 缓存 `TypeAdapter`，每个名称只构造一次。
- 用 `TypeAdapter` 而非 `BaseModel.model_validate`：`list[Segment]` 等列表产物
  无法用后者校验，`TypeAdapter(list[Segment])` 可以。
- `write_artifact` 的顺序是**先 `validate_python`、后 `open("w")`**。校验失败时
  磁盘上的旧文件保持原样，这是 `dataflow.md` 第 5.2 节 第 5 条“不存在 State 已更新
  但磁盘未写”的实现依据。
- 对 `type_=None` 的产物抛 `ValueError`，错误信息提示改用 `artifact_path`。
- 不创建目录。父目录缺失时 `FileNotFoundError`，依赖 CLI 在初始化时建好子目录。

### config.py

- `_CONFIG_DIR` 由 `Path(__file__).resolve().parent.parent.parent / "config"`
  计算，依赖仓库结构 `english-video-localizer/config/`。若目录结构调整，此处需同步。
- 不做 schema 校验，返回原始 dict。

### log.py

- `setup_logging` 会 `root.handlers.clear()`，重复调用会重置全局 logger 状态。
  CLI 只调用一次；测试中用 `tmp_dir` 隔离日志文件。
- 同时挂 `FileHandler`（`mode="w"`，每次运行覆盖）与 `StreamHandler`（stderr）。

## 排障

| 现象 | 原因 | 处理 |
|---|---|---|
| `KeyError: 未知的产物名称` | `ARTIFACT_SPECS` 无此名称 | 核对 `dataflow.md` §3 与规格表 |
| `ValueError: ... 路径已确定，不应提供 filename` | 对 `fixed` 产物传了 filename | 去掉 filename |
| `ValueError: ... 路径不确定，必须提供 filename` | 对 `dir` 产物未传 filename | 提供 filename |
| `ValueError: ... 不是结构化 JSON 产物` | 对二进制产物调用读写函数 | 改用 `artifact_path` |
| `ValidationError`（`write_artifact`） | 输入不符合 `contracts` 模型 | 看错误中的字段名与约束 |
| `FileNotFoundError`（`write_artifact`） | 父目录不存在 | 确认 CLI 已创建子目录、`set_work_dir` 正确 |
| `FileNotFoundError`（`read_artifact`） | 上游节点未写或路径错 | 确认上游已写、产物名称拼写一致 |
| `RuntimeError: 工作目录未设置` | 未调用 `set_work_dir` | CLI 应在启动时调用 |
| `ModuleNotFoundError: No module named 'utils'` | 模块导入不正确 | 确保正确导入`utils`模块 |