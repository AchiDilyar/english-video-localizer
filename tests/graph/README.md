# graph 测试

从仓库根运行：

```bash
uv run pytest tests/graph
```
基础环境即可，不需要任何 `--extra`、不需要 FFmpeg/ffprobe、不发起外部调用。

## 文件与覆盖

| 文件 | 覆盖内容 |
| --- | --- |
| `test_registry.py` | `graph.registry.resolve_nodes` 的切换规则与配置校验：未列出或显式 `false` 的节点走真实；每个节点独立开关；`mock.toml` 未知键、非布尔值、`load_config` 返回非 dict、节点模块缺函数、节点属性非 callable 全部直接失败 |
| `test_builder.py` | `graph.build_graph` 的拓扑与执行语义：8 个节点注册；边集合与 `workflow.md` 第 4 节逐条一致；线性前缀顺序；`subtitle_cover` 等待 `review_blocks`；`compose_video` 等待 `tts_align` 与 `subtitle_cover`；`compose_video` 为最后执行的业务节点，完成后进入 `END`；每个节点执行一次；节点入参为 `GraphState` 且增量合并进 State；节点失败后下游不执行；`resolve_nodes` 缺节点或含多余节点时 `build_graph` 拒绝 |
| `test_builder_integration.py` | 不 monkeypatch，真实走 `resolve_nodes → import_module(mocks.*) → StateGraph` 编译链路，验证当前 `mock.toml` 配置下 8 个节点全部进入图 |

`test_registry.py` 与 `test_builder.py` 只在 `load_config`、`import_module`、`resolve_nodes` 三个边界注入，**不导入任何 `nodes/*` 或 `mocks/*` 真实模块**，也不依赖 `tests/data/` 下任何样例。`test_builder_integration.py` 依赖 `mocks/*` 存在且导出同名主函数，那是 `architecture.md` 4.3 的 graph 契约。

## 失败排查

+   **`test_registry.py` 失败**：先看断言消息里的“实际导入顺序”或“实际值”。常见原因：`mock.toml` 拼写、值写成字符串、`NODE_NAMES` 改名后 `mock.toml` 未同步、节点模块未导出同名函数。
    
+   **`test_edges_match_workflow` 失败**：断言会列出“缺少边”和“多余边”。先查 `workflow.md` 第 4 节与 `graph/builder.py` 的边定义，再看是否是 LangGraph 版本升级导致多前驱等待边展开表示变化。
    
+   **`test_each_node_runs_exactly_once` 失败**：断言会列出完整执行序列与重复节点名。常见原因：新增边导致某节点被多个前驱触发、等待边被写成条件边。
    
+   **`test_*_waits_*` 失败**：断言消息含实际执行序列。先确认前驱节点的执行顺序，再查对应边是否为列表多前驱形式。
    
+   **`test_compose_video_is_last_business_node` 失败**：断言消息含实际尾段。先确认 `compose_video → END` 边存在且无其他节点在 `compose_video` 之后执行。
    
+   **`test_node_failure_stops_downstream` 失败**：先确认节点抛出的异常类型与消息是否被包装；本测试要求异常原样传播。
    
+   **`test_builder_integration.py` 失败**：说明当前 `mock.toml` 与 `mocks/` 现状不能支撑编译。先跑 `uv run pytest tests/graph/test_registry.py` 定位是切换问题还是导入问题。
    

## 边界说明

B/C 联调测试已移至 `tests/nodes/`，由 B/C 维护，不在本目录，也不属于 graph 模块测试范围。graph 测试不校验业务产物、不读写 `tests/data/`、不涉及 `tests/tmp/`。
