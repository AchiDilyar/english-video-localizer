# graph 测试

从仓库根运行：

```bash
uv run pytest tests/graph
```

基础环境即可，不需要任何 `--extra`、不需要 FFmpeg/ffprobe、不发起外部调用。

## 文件与覆盖

| 文件 | 覆盖内容 |
| --- | --- |
| `test_registry.py` | `graph.registry.resolve_nodes` 的切换规则与配置校验：未列出或显式 `false` 的节点走真实；每个节点独立开关；`mock.toml` 未知键、非布尔值、`load_config` 返回非 dict、节点模块缺函数、节点属性非 callable 全部直接失败；`INCREMENTAL_NODE_NAMES` 含未知节点时启动即失败；增量节点经代理包装后异常返回 `{}` 并记录 `warning`；非增量节点异常继续上抛 |
| `test_incremental.py` | `graph.incremental` 的代理行为：正常透传、`Exception` 吞掉并记录带栈 `warning`、`BaseException` 继续上抛、只包装增量集合内节点、空集合保持函数同一性、元数据保留、`OSError` 模拟写盘失败仍返回空增量；图级别测试通过 patch 常量走真实 `build_graph()`，验证增量节点异常时基础版链与 `compose_video` 继续执行、增量正常返回时合并进 State |
| `test_builder.py` | `graph.build_graph` 的拓扑与执行语义：8 个节点注册；边集合与 `workflow.md` 第 4 节逐条一致；线性前缀顺序；`subtitle_cover` 等待 `review_blocks`；`compose_video` 等待 `tts_align` 与 `subtitle_cover`；`compose_video` 为最后执行的业务节点，完成后进入 `END`；每个节点执行一次；节点入参为 `GraphState` 且增量合并进 State；节点失败后下游不执行；`resolve_nodes` 缺节点或含多余节点时 `build_graph` 拒绝 |
| `test_builder_integration.py` | 不 monkeypatch，真实走 `resolve_nodes → import_module(mocks.*) → StateGraph` 编译链路，验证当前 `mock.toml` 配置下 8 个节点全部进入图 |

`test_registry.py` 与 `test_builder.py` 只在 `load_config`、`import_module`、`resolve_nodes` 三个边界注入，**不导入任何 `nodes/*` 或 `mocks/*` 真实模块**，也不依赖 `tests/data/` 下任何样例。`test_builder_integration.py` 依赖 `mocks/*` 存在且导出同名主函数，那是 `architecture.md` 4.3 的 graph 契约。

`test_incremental.py` 的单元测试直接调用 `graph.incremental`，不依赖真实节点；图级别测试通过 fixture 集中 patch `registry.NODE_NAMES`、`builder.NODE_NAMES`、`builder.WORKFLOW_EDGES`、`registry.INCREMENTAL_NODE_NAMES`、`graph.incremental.INCREMENTAL_NODE_NAMES`，并 mock `registry.load_config` 与 `registry.import_module`，**不修改 `builder.py`**，不影响现有基础版节点。

## 失败排查

+   **`test_registry.py` 失败**：先看断言消息里的“实际导入顺序”或“实际值”。常见原因：`mock.toml` 拼写、值写成字符串、`NODE_NAMES` 改名后 `mock.toml` 未同步、节点模块未导出同名函数、`INCREMENTAL_NODE_NAMES` 拼写错误。
    
+   **`test_edges_match_workflow` 失败**：断言会列出“缺少边”和“多余边”。先查 `workflow.md` 第 4 节与 `graph/builder.py` 的边定义，再看是否是 LangGraph 版本升级导致多前驱等待边展开表示变化。
    
+   **`test_each_node_runs_exactly_once` 失败**：断言会列出完整执行序列与重复节点名。常见原因：新增边导致某节点被多个前驱触发、等待边被写成条件边。
    
+   **`test_*_waits_*` 失败**：断言消息含实际执行序列。先确认前驱节点的执行顺序，再查对应边是否为列表多前驱形式。
    
+   **`test_compose_video_is_last_business_node` 失败**：断言消息含实际尾段。先确认 `compose_video → END` 边存在且无其他节点在 `compose_video` 之后执行。
    
+   **`test_node_failure_stops_downstream` 失败**：先确认节点抛出的异常类型与消息是否被包装；本测试要求异常原样传播。
    
+   **`test_incremental.py` 单元测试失败**：先确认异常类型是否为 `Exception` 子类；`BaseException` 子类不应被代理捕获。日志断言失败时检查 `caplog.at_level(logging.WARNING)` 是否生效。
    
+   **`test_incremental_failure_does_not_stop_graph` 失败**：断言消息含实际执行序列。先确认增量节点是否被 `apply_incremental_proxy` 包装、`INCREMENTAL_NODE_NAMES` 是否同时 patch 了 `registry` 与 `graph.incremental` 两处、`builder.WORKFLOW_EDGES` 是否包含增量节点到 `compose_video` 的边。
    
+   **`test_incremental_success_merges_increment` 失败**：先确认代理对正常返回不做修改，再检查增量键是否为 `GraphState` 已定义字段。
    
+   **`test_builder_integration.py` 失败**：说明当前 `mock.toml` 与 `mocks/` 现状不能支撑编译。先跑 `uv run pytest tests/graph/test_registry.py` 定位是切换问题还是导入问题。
    

## 边界说明

+   **增量代理位置**：代理位于 `graph/registry.py` 调用的 `graph/incremental.py`，`builder.py` 与 `cli.py` 不感知当前节点是基础版还是增量。`test_builder.py` 全部 monkeypatch `builder.resolve_nodes`，不经过代理，仍验证 `architecture.md` 8.1 的基础版行为。
    
+   **代理能力边界**：代理只保证异常不外抛并返回空增量，**不负责回滚增量节点在抛异常前对 `state` 的原地修改，也不负责回滚已写磁盘文件**。`architecture.md` 8.2 中“基础版字段保持执行前状态”依赖节点不原地修改 `state`、不提前写基础版产物名/路径。
    
+   **图级别增量测试约定**：增量节点分支从 `probe_input` 之后开始、在 `compose_video` 之前汇入，与基础版链并行；测试中选择 `review_blocks` 后分叉、汇入 `compose_video`。该约定是**测试范围限定**，不是生产代码的架构约束；生产代码中增量节点接入位置由 `workflow.md` 决定，且必须满足 8.2 第 4 条“增量节点不得成为基础版节点的必需前置”。
    
+   **图级别增量测试实现方式**：通过 patch 常量走真实 `build_graph()`，不修改 `builder.py`。新增或调整增量测试时，需同时 patch `registry.NODE_NAMES`、`builder.NODE_NAMES`、`builder.WORKFLOW_EDGES`、`registry.INCREMENTAL_NODE_NAMES`、`graph.incremental.INCREMENTAL_NODE_NAMES` 五处，并 mock `registry.load_config` 与 `registry.import_module`。
    
+   **registry 增量用例命名**：`test_registry.py` 的增量代理用例使用测试专用节点名 `incremental_probe`，不把真实基础版节点设为增量节点，也不构建图，避免与 8.2 第 4 条的图接入约束混淆。
    
+   **当前增量集合为空**：`graph.incremental.INCREMENTAL_NODE_NAMES` 当前为 `frozenset()`，现有 8 个基础版节点不经过代理，生产行为与改动前一致。后续新增增量节点时，需同步 `workflow.md` 第 3 节版本归属列、`NODE_NAMES`、`INCREMENTAL_NODE_NAMES`、`WORKFLOW_EDGES` 和 `mock.toml`。
    

B/C 联调测试已移至 `tests/nodes/`，由 B/C 维护，不在本目录，也不属于 graph 模块测试范围。graph 测试不校验业务产物、不读写 `tests/data/`、不涉及 `tests/tmp/`。
