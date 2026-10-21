# 六次开发复验结果

候选 `7c9a7fb`，协议 `f65d80fd`。6/6 已判分、没有重试，服务已关闭。
总耗时约 41.9 分钟。只覆盖两个已见开发项目、Qwen3.6 各组一次。

| 项目 | baseline | facts | mcp |
|---|---|---|---|
| django-storages | 253 errors；有选测配置违规 | 253 passed，合格成功 | 253 errors；仅临时设置 |
| python-slugify | 123 passed / 2 failed | 123 passed / 2 failed | 123 passed / 2 failed |

**成功 1/6，MCP 0/2。** 唯一成功的 facts 行没有调用 observe 或其它 FixFirst 工具：
agent 自行安装 pytest-env、修改 tox.ini，留下了持久修复。因此不能将其归因于事实报告，也不能据此宣称 FixFirst 收益提高。

79 份完整响应收据与逐行轮数、停止原因和 token 累计逐一一致。11 次长度截断触发 8 次续接；
三个 slugify 行均在已续接两次后再次截断，结束为 response_truncated，均未保存源码修改。
所有运行仍在 20 轮 / 900 秒预算内，空回复 0 次。两条 Django 截断续接后仍以普通无工具回复结束。

本批确认了截断的记录和有界续接机制；业务修复仍未完成。下一项优先把 Django 的具名设置建议
衔接到受约束的持久 pytest 配置，并改进代码缺陷的函数定位与从分析到修改的过程。
普通工具轮的独立 reasoning_content 字段回传另列为待验证问题；不能将它直接当成本批截断根因。

旧 78 行未改，不合并旧协议、B3 或新留出结果，不作整体效果或显著性结论。
数字与完整参数见 RESULTS.public.json；原始回复、命令、项目修改及判分收据留在本地脱敏前证据归档中。
