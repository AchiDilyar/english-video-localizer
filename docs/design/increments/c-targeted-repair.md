# C 翻译配置与定向返工

## 翻译配置

在仓库的 config/translate_blocks.toml 中选择风格。默认是「通用」，另有「音乐行业」「影视」「新闻」「科学与技术」「文化与历史」。初译、审校与返工读取同一份配置，任务运行期间保持配置一致。各种风格都使用同一套中文字幕标点规则。

术语表增强默认关闭。开启后，配置术语覆盖同名的任务术语，并保留其他条目。任务未提供术语表时，从内置术语表开始合并。增强后的术语表由分块节点写入 GraphState，后续节点共享。术语来自配置文件，英文词条和中文译法都须为非空字符串。

~~~toml
style = "音乐行业"

[terminology]
enabled = true

[terminology.entries]
"sample size" = "样本量"
"audio mastering" = "母带制作"
~~~

## 定向返工

- project/nodes/repair_blocks.py 导出 repair_blocks(state: GraphState) -> dict。节点读取 reviewed_blocks、原文分段和术语表，先按块审计，再把有问题的片段交给模型重写一轮。
- 重写结果会在写盘前按中文字幕规范处理标点。小数、比例、网址和技术名称中的必要符号会保留。处理后为空的译文视为返工失败。
- 有实际修订时，按审校结果的原顺序写出完整 translated/repaired_blocks.json，并返回 repaired_blocks 状态增量。保持各片段 ID、块 ID 和未命中片段。原审校结果继续供基础版使用。
- 无审校结果、无问题或重写后译文相同时返回空增量。异常由主图已有的增量代理记录并隔离，下游可继续使用 reviewed_blocks。
- F 维护 config/mock.toml。当前主图默认使用 repair_blocks 的模拟节点。正式联调需由 F 切换真实节点，D 和 E 优先读取 repaired_blocks，缺失时使用 reviewed_blocks。

## 验证

uv run --locked --extra b-asr pytest tests/nodes/test_build_blocks.py tests/nodes/test_translate_blocks.py tests/nodes/test_review_blocks.py tests/nodes/test_repair_blocks.py tests/nodes/test_b_c_integration.py -q

测试覆盖术语增强开关、风格及标点复用、命中片段重写、审校产物保留和增量异常后的基础版路径。B/C 样片使用固定模型响应，下游使用模拟节点。
