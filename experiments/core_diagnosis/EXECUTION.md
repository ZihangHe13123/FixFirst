# 核心诊断与运行模式整合：2026-09-30

实现提交：`ba32dba8126bc3389430515c293119590f34f85e`。
它将 #42 的 `5e240ef` 与 main 的 `9fdf48d`（已合并 #43）整合，保留两侧历史。

本轮提高的是完整诊断和具体建议的适用范围，**没有重训分类器，也没有替换内置模型**。
pytest 之外的模式继续不使用未经这些模式评估的决策树预测。

## 1. 合并中发现并修复的问题

Git 报出的冲突位于异常来源处理。此外，两侧都新增了 G12/G13，自动合并后的规则库
不能加载。第一次组合测试因此有 51 项失败。保留已进入 main 的运行目标规则编号，
将 #42 的两条行为推导改为 G14/G15，诊断和动作编号保持不变。

解决加载问题后，原有相关测试 67 项通过。额外运行的跨模式探针发现了下面的问题：

| 情况 | 整合后、运行证据修复前 | 修复后 |
|---|---|---|
| 脚本或模块中的 Pydantic 多行错误 | 将字段名 `code` 当成异常类型，丢失异常正文 | 保留 `ValidationError`、真实限定名和多行正文 |
| 给字符串字段传入字典 | 因上述误读，给出不合适的版本回退建议 | 不再归为版本变化，不推荐降级 |
| 普通 Pydantic 字符串字段接收数字 | 脚本/模块只有宽泛版本建议，unittest 没有具体建议 | 三种模式均给出有证据支持的显式字符串转换建议 |
| notebook 调用 Python 模块里的 `yaml.load` | 文件调用位置丢失，无法匹配具体接口变化 | 保留 notebook 单元格位置和实际调用文件/行，给出安全 loader 建议 |
| notebook 调用模块里的 NumPy 混合运算后 JSON 序列化 | IPython 的 `~/…` 标准库路径被当成项目路径 | 在采集端展开路径，正确保留标准库来源，给出转为 Python float 的建议 |

四个开发问题/反例分别用脚本、模块、unittest、notebook 实际执行一次，共 16 个模式与
案例组合。它们不是 16 个独立故障，也不是正式实验。[前后对照记录](execution-development-2026-09-30/diagnosis-comparison.json)
包含输入代码、诊断、第一建议和相关源码哈希。修前状态是解决合并和规则编号冲突后的
未提交组合代码，已在记录中明确标注。

## 2. 修法验证和反例

新增 `tests/test_execution_diagnosis.py` 的 18 项检查：

- Pydantic 正例在脚本、模块、unittest 下实际执行转换建议；对应的错误字典输入不归为版本变化。
- PyYAML 正例在四种模式下实际使用 `safe_load`，保持入口或测试文件原样。
- notebook 的 NumPy 混合运算正例实际转成 Python float；直接序列化 NumPy 标量的旧有问题不归为这次版本变化。
- notebook 中名字相似的本地函数不会继承 PyYAML 历史。
- 多行异常正文、类似异常名的正文行、无消息异常、异常链保持正确类型和来源。
- notebook 只报告未限定的异常名时，不凭库路径补造 `exception_module`。

其中 8 项实际修法检查验证了原目标失败消失、相同入口/测试完成、入口或测试文件哈希未变。
这些都使用新建开发 fixture。普通会话全面的测试完整性保护仍由 Claude 的独立 PR 负责；
不能将这里的回归检查写成所有普通会话已经具备该保护。

## 3. 已有开发数据未退步

固定第三轮的 61 特征候选，重放已有观察快照，不执行第三方项目、不重新训练。

| 已有开发材料 | 完整系统根因结果 |
|---|---:|
| 新观察的生成案例 | 215/215 |
| 新观察的难例 | 30/30 |
| 保留的普通错误反例 | 14/14 |
| 真实开发故障 | 6/6 |
| 旧生成观察 | 215/215 |
| 旧难例观察 | 30/30 |

[重放记录](execution-development-2026-09-30/development-replay.json)同时保留纯树结果和漏判。
其中生成案例包含模型拟合数据，纯树 210/215 是固定模型重放结果，**不能替代此前
190/215 的按故障分组验证成绩**。这些数据都已参与开发，不能当成独立泛化证据。

## 4. 实际验证与协作接口

- 最终 Mac 主测试：**474 passed、1 skipped，82.76 秒**。
- Mac B7 harness：**51 passed，64.89 秒**。
- 运行模式与新增诊断回归：**50 passed，15.48 秒**，包含真实 notebook 内核。
- Ruff、`git diff --check` 通过。未做 Windows 实机验收。

`issue_evidence()` 保留原有键及含义，新增 `source_location` 保存实际 Python 调用位置；
notebook 的 `where` 继续显示文件与单元格。unittest 异常记录增加 `exception_module`。
没有为 Claude 的事实模式修改 Session/Run/Issue 定义，也没有在本轮扩展模型特征布局。

notebook 仍有明确边界：IPython 未报告异常所属模块时，Pydantic 数字转字符串变化暂不
给出确定的具体迁移判断；直接写在单元格里的静态调用/类定义也没有在本轮建立完整索引。
保持不确定结论比凭相似文本补齐来源更可靠。

复现运行回归需要本树自己的环境和 notebooks extra：

```bash
.venv/bin/python -m pip install -e '.[dev,notebooks]' httpx
.venv/bin/python -m pytest tests/test_execution_diagnosis.py tests/test_program_execution.py -q
.venv/bin/python -m pytest -q
.venv/bin/python -m pytest experiments/agent_baseline/test_harness.py -q
```

Claude 在独立分支推进三组框架/事实模式及普通会话验证完整性。这些 PR 的结果不计入
上面的数字。未启动真实语言模型或付费 API，未读取 A1/C1 留出，未启动正式实验或冻结。
