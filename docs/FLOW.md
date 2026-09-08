# FixFirst 实现流程与接口

本文件描述已经落地的代码；产品定位和使用方式见根目录 README。修改模块前，以 `models.py` 的 Pydantic 数据结构为共同约定。

## 一次排查的完整流程

1. **创建记录**：CLI / 菜单收集项目路径、解释器、目标及算法选项。`service.create_session` 验证路径，`storage.Store` 保存排查记录。
2. **主动采集**：`runner.collect` 用选定解释器运行环境快照、pip check、pytest 收集或 Ruff。参数列表直接传给子进程，不拼接 shell。记录输出、退出码、环境、范围、完成状态与耗时；每次检查默认 30 秒、总输出最多 1 MB。
3. **解析证据**：`parsers.parse` 把运行结果转成 Event。pytest 使用临时采集插件补充结构化事件；Ruff 使用 JSON。未知和不完整输出保留，不能被解释成成功。
4. **归并问题**：`grouping.group_events` 先按工具、阶段、组件、版本等信息限制候选，再进行精确 / TF-IDF / SBERT 比较。complete-link 分组要求组内相互满足阈值，避免 A 像 B、B 像 C 就把不同的 A/C 强行合并。原始证据与出现位置仍可查看。
5. **候选分类**：`classification.rule_classify` 给出基线类别；选用训练模型时，`predict_tree` 读取 JSON 决策树给出独立候选。预测不能覆盖真实错误信息。
6. **更新状态**：`service.ingest` 比较新旧问题。只有同一解释器身份、同一检查范围的完整成功检查，才可关闭该范围旧问题。失败、超时、缺少完成证据或局部检查不能关闭其他问题。手动“已修改”只进入待验证状态。
7. **推理与排序**：`reasoning.infer_and_plan` 从当前有效问题产生观察事实；`forward_chain` 反复应用显式规则，直到没有新事实。规则输出保留规则号、输入事实与证据引用。再根据前置条件、目标影响、证据和估计检查成本生成有序行动。
8. **输出与迭代**：存储层原子写入 session；Jinja 生成 HTML / JSON。用户执行建议检查或手动修复后重新采集。每次重新推理，避免旧结论在证据消失后继续影响排序。

## 核心对象

| 对象 | 内容 | 谁生成 / 谁使用 |
|---|---|---|
| Run | 工具、命令、环境 ID、范围、输出、退出码、完成状态 | runner → parser / 状态比较 |
| Event | 错误种类、组件、位置、原始信息、证据引用 | parser → grouping |
| Issue | 稳定标识、成员事件、状态、分类与独立预测 | grouping / service → reasoning / report |
| Fact | 观察 / 推导 / 假设、规则、输入与证据 | reasoning → 行动解释 |
| Action | 下一步、关联问题、前置条件、排序、可选检查 | reasoning → CLI / report |
| Session | 项目、解释器、目标、以上对象及历史 | service / storage 统一保存 |

当前“环境 ID”区分解释器路径，不是整个环境内容的不可变快照。用户在同一路径更新依赖后，应重新运行环境与相关检查。报告中的“已验证”对应记录中的检查时刻，不代表后台持续监控。

## 三类课程技术怎样落地

| 技术 | 实际输入与输出 | 已实现的可比较项 |
|---|---|---|
| 文本向量、相似度 | 错误文本 → 向量 → 受结构约束的问题组 | 精确匹配 / TF-IDF / MiniLM SBERT；成对 precision / recall |
| Gini 决策树 | 从日志得到的 8 个二值信号 → 候选类别 | 规则基线 vs 决策树；按模板项目划分；Macro F1 |
| 前向推理 | 当前问题事实 + 用户目标 → 派生事实和行动 | 多跳推理、循环终止、证据链、撤回旧事实、目标切换检查 |

排序是有明确顺序的启发式，不保证全局最优修复路径。规则边表达行动所需条件，不把文本相似度直接当成故障因果关系。当前行动顺序的小实验是模拟，不是完整修复调度基准。

## 数据与模型生命周期

`cases.create_project` → 健康基线通过 → `inject` 注入已知故障 → 实际运行检查 → 保存输入 → 按注入类型生成 truth → `repair_fixture` 恢复自建案例 → 重跑验证 → 保存 manifest 和标签。

`evaluation.evaluate` 读取标签 → 固定按项目划分 → 训练 Gini 树 → 在验证/测试数据报告成绩 → 输出可读 JSON 模型及树结构 → 用户通过 `init --model` 接入产品。

`scripts/download_model.py` 负责公开 SBERT 下载并记录版本；运行时仅使用本地模型。训练只针对分类器；本项目未微调 SBERT。模型缺失会报错，不能假装跑过。

生成数据中的故障恢复函数只供 demo/dataset 调用。面向用户项目的扫描与行动入口没有自动修改源码或安装依赖的路径。

## 三人协作的接口边界

- A 的新增解析器输出合法 Event 和真实 Run 覆盖信息，不自行把未识别输出标为成功。
- B 的新模型输出候选类别或相似分数，不能改写 Run 的执行事实；算法结果和基线使用相同划分。
- C 从 Session 构建界面与状态流程，不把页面按钮成功、人工声明或日志缺失当作修复成功。

每个人可先沿现有测试添加自己遇到的真实边界案例。集成时共同验证：多处重复导入错误、仅重跑 Ruff、切换解释器、超时、不完整日志，以及恢复后的目标状态。

## 依赖文档

- [pytest hooks](https://docs.pytest.org/en/stable/reference/reference.html#hooks)：采集阶段与完成信息。
- [Ruff configuration](https://docs.astral.sh/ruff/configuration/)：检查配置与命令行覆盖。
- [pip check](https://pip.pypa.io/en/stable/cli/pip_check/)：已安装依赖的一致性检查。
