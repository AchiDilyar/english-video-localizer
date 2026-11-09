# 项目代码架构设计

版本：v1.2.1
最后更新：2026-11-09

---

## 1. 文档定位与事实源范围

### 1.1 本文档负责什么

本文档描述基本版项目代码架构，包括：

- 代码目录结构；
- 节点函数签名与注册；
- 模拟与真实节点切换；
- 配置加载机制；
- 通用函数接口；
- CLI 入口与出口；
- 节点失败基本行为；
- 测试代码的组织与存放规范。
- 日志的存放与格式规范。

### 1.2 本文档是以下内容的唯一事实源

> 唯一事实源指：以下概念**只在该文档定义**，其它文档可以引用这些概念，但**不可重新定义**。如果出现名称不一致，以该文档的名称为准，引用该概念的文档应尽快同步修改。

| 事实 | 对应章节 | 说明 |
|---|---|---|
| 代码目录结构 | 第 2 节 代码目录结构 | 仓库和 `project/` 下的模块划分 |
| 节点函数签名 | 第 3 节 节点函数签名与注册 | 统一为 `state: GraphState -> dict` |
| 节点注册方式 | 第 3 节 节点函数签名与注册 | F 在 `graph/` 中导入并注册 |
| 模拟与真实节点切换机制 | 第 4 节 模拟与真实节点切换 | 切换位置、模拟实现位置、函数签名一致性、`config/mock.toml` 的键与含义 |
| 配置加载机制 | 第 5 节 配置加载机制 | 配置文件位置、`load_config()` 入口、配置格式、F 与模块的边界 |
| 通用函数接口 | 第 6 节 通用函数接口 | 路径函数、读写函数、配置加载函数的签名与职责；产物规格表 |
| CLI 入口与出口 | 第 7 节 CLI 入口与出口 | 命令形式、参数、默认值、工作目录与输入视频必须存在、输出格式、退出码 |
| 节点失败基本行为 | 第 8 节 节点失败基本行为 | 异常抛出、图终止、CLI 非零退出 |
| 测试组织规范 | 第 2.5 节 测试组织 | 测试代码位置、命名、数据存放与归属 |
| 日志组织规范 | 第 2.6 节 日志组织 | 日志文件位置、格式、logger 命名、异常记录方式 |

### 1.3 文档引用约定

- 本文档引用的节点名与节点职责以 `workflow.md` 为准；
- 本文档引用的产物名、磁盘路径、数据类名以 `dataflow.md` 为准；
- 本文档引用的字段名、类型、必填性以 `contracts/` 与自动生成的 `interfaces.md` 为准；
- 本文档只引用名字，不重复定义节点职责、产物定义和字段。

---

## 2. 代码目录结构

### 2.1 仓库顶层

```text
english-video-localizer/
  project/          # 主代码
  tests/            # 测试代码，结构镜像 project/
  docs/
    design/         # 设计文档、协作约定与 CHANGELOG
      workflow.md
      dataflow.md
      architecture.md
      collaboration.md
      CHANGELOG.md
    contracts/      # interfaces.md，从 Pydantic 自动生成
    nodes/          # 各节点模块的补充文档，子目录以节点名命名
    graph/          # 图构建模块的补充文档
    cli/            # CLI 模块的补充文档
    utils/          # utils 模块的补充文档
  config/           # 配置文件
  pyproject.toml    # 依赖与项目元信息
```

### 2.2 `project/` 内部

```text
project/
  cli.py                    # CLI 入口
  graph/                    # 图构建模块
  contracts/                # Pydantic 模型
  nodes/                    # 节点模块
  mocks/                    # 模拟节点
  utils/                    # 通用函数
    artifacts.py
    paths.py
    io.py
    config.py
    log.py
```

### 2.3 各目录职责

| 路径 | 职责 |
|---|---|
| `cli.py` | 参数解析、检查工作目录与输入视频存在、创建子目录、构造初始 State、调用 `build_graph()`、执行图、输出结果 |
| `graph/` | 图构建：导入节点函数、注册节点、添加边、编译；对外只暴露 `build_graph()` |
| `contracts/` | Pydantic 模型，字段、类型、必填性与约束的唯一事实源 |
| `nodes/` | 节点模块，每个节点一个模块，模块名与节点名一致，导出主函数 |
| `mocks/` | 模拟节点，每个节点一个模块，模块名与节点名一致，导出主函数 |
| `utils/artifacts.py` | 产物规格表：名称到路径规则与校验类型的唯一代码实现；事实源为 `dataflow.md` 第 3 节产物表 |
| `utils/paths.py` | 绝对路径生成；路径规则从 `utils/artifacts.py` 的产物规格表获取 |
| `utils/io.py` | 结构化数据读写与 Pydantic 校验；校验类型从 `utils/artifacts.py` 的产物规格表获取 |
| `utils/config.py` | 配置加载入口 |
| `config/` | 配置文件存放位置，具体文件由各模块自行定义和解析；`config/mock.toml` 由 F 维护 |
| `utils/log.py` | 日志初始化入口；CLI 调用一次，配置 root logger 写文件与 stderr |

### 2.4 节点模块结构约定

- 每个节点在 `nodes/` 下对应一个模块，模块名与 `workflow.md` 中的节点名完全一致。
- 节点模块可以是单文件，也可以是目录，由负责该节点的角色决定。
  - 单文件示例：`nodes/probe_input.py`；
  - 目录示例：`nodes/asr_diarize/__init__.py` 导出主函数，内部文件放适配器和辅助实现。
- 无论文件还是目录，节点模块必须导出与节点名一致的主函数。
- 适配器、辅助函数、内部数据结构放在节点模块内部，由负责角色自行组织，不规定节点内部结构。

---

## 3. 节点函数签名与注册

所有节点主函数统一为：

```python
def node_name(state: GraphState) -> dict:
    """从 state 读取输入，返回需要合并进 state 的增量。"""
```

- `node_name` 是模板占位符，应替换为节点名称，必须与 `workflow.md` 中定义的节点名称一致；
- `GraphState` 是 Pydantic `BaseModel` 类型，其定义见 `contracts/`；
- 输入参数是 `GraphState`；
- 返回值是增量字典，只包含本次修改的字段，未返回的字段保持不变；键必须在 `GraphState` 中已定义；
- 对于列表字段的修改，增量的含义是丢弃该列表的原有数据并修改为指定数据，不是保留原有内容并追加；  
- 节点内部可调用任意适配器、辅助函数；  
- 节点返回增量后，由 LangGraph 合并进 `GraphState`；
- 合并规则：LangGraph 以 `GraphState.model_copy(update=increment)` 做浅合并，节点函数返回的增量只需包含本次修改的键，未出现的键保持原值
- 合并过程不保证是否触发 Pydantic 校验。落盘时（见 dataflow.md 5.2节；`workflow.md v1.0`的设计`GraphState`不落盘，不会触发）或显式调用 `GraphState.model_validate` 时会触发校验。节点函数应保证增量完成后，调用方在任何时刻调用校验函数都可通过校验。
- 结构化落盘对象的写磁盘在节点函数内部完成，且发生在返回增量之前，约定见 `dataflow.md` 第 5.2 节；写磁盘失败时按节点失败处理，约定见第 8 节；
- `graph` 模块会从 `nodes/` 导入各节点主函数，并进行注册。

---

## 4. 模拟与真实节点切换

### 4.1 模拟节点与真实节点说明

为了方便验证完整流程以及节点的单元测试，角色 F 后续会实现模拟节点。模拟节点内部没有任何程序逻辑，仅读取并返回模拟数据。真实节点即正常代码实现的各个节点。

每个节点可以独立选择使用真实实现还是模拟实现，由 `config/mock.toml` 中对应节点的开关决定。

### 4.2 切换位置

- 切换在 `graph/registry.py` 中完成；
- `registry.py` 读取 `config/mock.toml`，按每个节点的开关决定导入真实节点函数还是模拟节点函数；
- `builder.py` 和 `cli.py` 不感知当前是真实还是模拟。

### 4.3 模拟实现位置

- 模拟实现放在 `mocks/` 下；
- 每个模拟节点一个模块，模块名与节点名一致；
- 模拟模块导出与真实节点同名的主函数，签名完全一致：`state -> dict`；
- 模拟数据由模拟实现自行管理，可放在 `mocks/data/` 或直接写在模拟函数中。

### 4.4 mock 配置

`config/mock.toml` 由 F 维护，列出各节点的模拟开关。格式约定：

- 键为节点名，值为布尔；
- 未列出的节点默认为真实实现；
- 新增节点时若未在 `config/mock.toml` 中配置，默认真实。

### 4.5 切换机制

```text
读取 config/mock.toml
→ 对每个节点：
    若 use_mock 为 true：从 mocks/ 导入该节点主函数
    否则或未配置：从 nodes/ 导入该节点主函数
→ 在 builder 中按节点名注册
```

### 4.6 约束

- 模拟函数与真实函数签名一致，返回增量结构一致；
- 模拟实现不得被真实节点模块导入或依赖；
- 真实节点模块不得包含模拟分支；模拟与真实的区分只在 `graph/registry.py` 中完成。

---

## 5. 配置加载机制

### 5.1 配置文件位置

- 配置文件放在 `config/` 目录下；
- 配置格式统一为 TOML；
- 具体文件名和内容由各模块自行决定，可以用节点名作为配置文件名的前缀；
- 模块可以读取自己需要的配置文件，也可以共享配置；
- `config/mock.toml` 是 F 维护的跨模块配置，与各模块自己的配置文件并列。`config/mock.toml` 由 F 维护，其它角色不可修改。

### 5.2 F 的职责边界

- 提供 `utils/config.py` 中的 `load_config(filename: str) -> dict` 入口，输入配置文件文件名，返回原始配置 dict，不做 schema 校验；
- 不规定配置内容的键、类型和校验方式；
- 各模块自行决定读取哪些配置、如何解析、如何校验。

### 5.3 模块的职责

- 模块通过 `load_config(filename)` 获取原始配置；
- 模块自行解析自己需要的部分；
- 模块自行处理配置缺失或无效的情况，失败时按节点失败处理。

---

## 6. 通用函数接口

### 6.1 `utils/paths.py`

```python
def set_work_dir(work_dir: str) -> None:
    """由 CLI 在启动时调用一次，设置本次任务的全局工作目录。"""

def get_work_dir() -> str:
    """返回当前工作目录；未设置时抛出异常。"""

def artifact_path(
    name: str,
    filename: str | None = None,
) -> str:
    """根据名称返回产物的绝对路径。

    - 路径确定的产物：filename 为 None，返回完整绝对路径。
    - 路径不确定的产物：filename 必须提供，返回名称对应文件夹下的文件绝对路径。
    - 路径规则从产物规格表（`utils/artifacts.py`）按名称获取，事实源为 `dataflow.md` 第 3 节产物表。
    - 名称必须存在于产物规格表中，否则抛出异常。
    """
```

### 6.2 `utils/io.py`

```python
def read_artifact(
    name: str,
    filename: str | None = None,
):
    """按名称读取 JSON 产物，按产物规格表登记的校验类型做 Pydantic 校验后返回。

    - 校验类型从产物规格表（`utils/artifacts.py`）按名称获取，事实源为 `dataflow.md` 第 3 节产物表。
    - 返回类型由名称决定
    - 名称未登记，或该产物的校验类型为 None（二进制产物）时抛出异常。
    """


def write_artifact(
    name: str,
    obj,
    filename: str | None = None,
) -> None:
    """按名称写入 JSON 产物，写入前按产物规格表登记的校验类型做 Pydantic 校验。

    - `obj` 可以是模型实例，也可以是裸 dict / list；校验后统一转化为模型实例再序列化。
    - 写入磁盘 JSON 必须为通过校验的合法结构。
    - 名称未登记，或该产物的校验类型为 None（二进制产物）时抛出异常。
    """
```

### 6.3 `utils/config.py`

```python
def load_config(filename: str) -> dict:
    """从 config/ 目录加载指定 TOML 配置文件，返回 dict，不做 schema 校验。"""
```

### 6.4 产物规格表

- `utils/artifacts.py` 内部维护产物规格表，内容与 `dataflow.md` 第 3 节产物表一致；规格表是 `utils/paths.py` 与 `utils/io.py` 的共同数据源，两者不各自维护映射表，也不接收调用方传入的类型参数；
- 每个名称映射到路径规则与校验类型：路径规则分三种（完整相对路径 / 文件夹 + filename / 根目录 + filename）；校验类型为落盘 JSON 的 Pydantic 类型，落盘为二进制文件的产物为 None。校验类型描述磁盘 JSON 的类型，与 `GraphState` 字段类型无关；
- 名称与磁盘格式一一对应的约束见 `dataflow.md`的`5.1`节；`dataflow.md` 第 3 节产物表是名称、路径与校验类型的事实源，`utils/artifacts.py` 是代码实现，两者不一致时以 `dataflow.md` 为准。

### 6.5 使用约束

- 节点通过 `artifact_path` 获取路径，不直接拼接路径字符串；
- 落盘为单个 JSON 文件的结构化产物，必须通过 `read_artifact` / `write_artifact` 读写，函数内部按产物规格表完成 Pydantic 校验；节点不自行 JSON 序列化，也不接收或传入校验类型参数；
- 落盘为二进制文件的产物，不可调用 `read_artifact` / `write_artifact`（函数会因校验类型为 None 抛异常），必须通过 `artifact_path` 获取绝对路径，交给对应第三方工具（FFmpeg、TTS 工具等）处理。

---

## 7. CLI 入口与出口

### 7.1 命令形式

```bash
run-input [--work-dir PATH] [--input FILENAME]
```

启动前，工作目录和输入视频必须存在；CLI 不负责创建根目录，只创建子目录。

### 7.2 参数

| 参数 | 默认值 | 说明 |
|---|---|---|
| `--work-dir` | 当前目录 `.` | 工作目录，必须已存在 |
| `--input` | `input.mp4` | 工作目录根目录下的输入视频文件名，必须已存在 |

### 7.3 出口

- 成功：输出运行状态与最终 ZIP 路径；
- 失败：输出错误摘要；
- 退出码：成功 0，失败非 0。

### 7.4 CLI 职责边界

- CLI 不参与业务处理，不直接调用适配器、ASR、TTS、FFmpeg、LLM；
- CLI 负责调用 `utils/paths.py`的`set_work_dir`函数设置全局工作目录
- CLI 负责参数解析、目录检查与子目录创建、构造初始 State、调用图、输出结果。

---

## 8. 节点失败基本行为

1. 节点内部异常直接抛出，不做捕获和降级；
2. 图终止，不再执行后续节点；
3. CLI 捕获异常，打印错误摘要，返回非零退出码；
4. 节点不要求写重试、降级、退回、日志文件。

## 9. 测试与日志组织

### 9.1 测试组织

- 测试和日志的目标是保证模块可以正常运行、出问题能够快速排查，对格式和内容不做强制要求。基本版不建设完整测试体系（不强制覆盖率、不配 CI、不引入测试报告）。
- 不强制每个模块提供测试；若提供，按本节组织。
- 测试代码放在仓库顶层 `tests/`，结构镜像 `project/`：`tests/utils/` 对应 `project/utils/`，`tests/nodes/` 对应 `project/nodes/`，依此类推；
- 测试由对应模块的负责人维护：F 负责 `tests/utils/`、`tests/graph/`、`tests/smoke/`，B/C/D/E 负责 `tests/nodes/` 下各自节点的测试；
- 建议负责人在测试目录中放入`README.md`，简要说明各测试脚本的功能、测试数据获取方式等必要信息，此项不强制要求；
- 测试文件命名为 `test_<module_name>.py`，测试函数命名为 `test_<behavior>`
- 测试统一通过 `python -m pytest tests/[模块路径]` 运行；单个测试脚本用 `python -m pytest tests/.../test_xxx.py`。
- 仓库根 `pyproject.toml` 的 `[tool.pytest.ini_options]` 已配置 `pythonpath = ["project"]`，测试文件直接以`project`文件夹为根目录导入模块，如`import utils`，不需要修改 `sys.path`；
- 不支持直接 `python tests/.../test_xxx.py` 运行。直接运行会因找不到模块而失败，这是预期行为，请使用 pytest；
- 测试数据放在 `tests/data/<module>/`；小样例（< 1 MB）提交到仓库，大文件放在 `tests/data/_large/<module>/` 并通过 `.gitignore` 排除，由模块负责人本地提供，`tests/data/` 说明各目录用途与获取方式；
- 测试运行时临时创建的目录放在 `tests/tmp/`，`tests/tmp/` 不提交；
- `project/mocks/` 是项目代码（mock 模式下的节点替代实现），不属于测试代码；`tests/` 在测试时可导入 `mocks/`，反之不允许。

### 9.2 日志组织

- 所有日志写入同一个文件 `work_dir/logs/run.log`，由 CLI 在 `set_work_dir` 之后调用 `utils/log.py` 的 `setup_logging` 创建并初始化；日志是运行副产品，不进入产物表，不走 `read/write_artifact`；
- 日志格式由 `setup_logging` 统一配置，包含时间、级别、logger 名称与消息；默认有效级别为 `INFO`；
- 模块内统一使用 `logging.getLogger(__name__)` 获取 logger，禁止自编 logger 名称。
- 正常日志与异常日志不分文件，靠级别区分。节点内部不捕获异常、不记异常日志；异常直接抛出，由 CLI 顶层 `except` 用 `logger.exception` 记录一次完整栈后重新抛出；
- 不强制节点写日志；若写，建议使日志能反映智能体工作流程，不强制要求；
- 测试产生的临时日志放在 `tests/tmp/`，由 `.gitignore` 排除。