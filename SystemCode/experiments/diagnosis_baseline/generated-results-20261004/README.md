# B3：250 个生成案例的类别对照

750 条本地模型回答已封存；两版 FixFirst 对同一批保存的会话完成了 500 次离线重放。
完整结果见 [REPORT.md](REPORT.md)，逐例答案见 [case-matrix.csv](case-matrix.csv)。

| 系统 | 普通案例 / 220 | 困难案例 / 30 |
|---|---:|---:|
| FixFirst v0.7.0 | 220 | 30 |
| v0.8 候选 `ff92446` | 215 | 30 |
| Qwen3.6 35B A3B | 203 | 15 |
| Gemma 4 26B A4B | 213 | 15 |
| Qwen3.8 27B | 216 | 18 |

## 怎么读

- 这里评的是**根因类别**。首步是否正确、能否修好，没有评分。
- 普通集参与过模型训练，困难集参与过规则开发；不能证明未见真实项目上的泛化能力。
- FixFirst 使用完整结构化会话，模型使用事前固定的白名单文本；来自同一采集记录，表示和部分派生字段不同。
- v0.8 的 5 个未答是旧 unittest 记录缺对象归属，仍按全分母计错。没有补采、挑备选答案或替换成新回归成绩。
- Qwen3.8 的 1 条无效 JSON 原样保留并计错，没有宽松解析、修补或重发。
- 两版内置 44 特征树相同。此处不训练树，也不启动 B7 的修复 agent。

## 离线核对

在安装了项目依赖的 Python 3.12 环境中，从仓库根执行：

```sh
python experiments/diagnosis_baseline/generated-results-20261004/verify.py
```

它核对文件清单、回答封存、标签、输入快照和逐例来源；从原始回答重新解析及计分，独立重算 FixFirst 的计数/F1，并在临时目录重建报告。无需模型、网络或测试项目运行。历史 Git 对象在场时还逐个核对产品源码；浅克隆缺对象时会明确写 `NOT CHECKED`，不把内容核对冒充源码绑定核对。

`python experiments/diagnosis_baseline/generated-results-20261004/build_report.py` 可直接重建三份派生文件。科学数值和矩阵必须与 `original-report/` 完全相同；只改公开文件路径和交付说明。

## 可选：重放产品诊断

`fixfirst/replay_portable.py` 来自实际运行的脚本，只将本机目录改成参数并要求新输出目录。原始脚本摘要保留在 `PACKAGING.json` 和 `fixfirst/SOURCE_INPUT_IDENTITY.json`；这份便携副本不是原执行脚本的逐字节副本。

先准备两个干净检出，分别停在 `c8151af7bd6c19d71605dd3add38ea2dcda98ec2` 和 `ff92446c5d0de26564f1cbf50e45036c90b87713`。然后指定其路径：

```sh
B3_V070_CHECKOUT=/path/to/v070 B3_V08_CHECKOUT=/path/to/v08 \
B3_REPLAY_OUTPUT=/path/to/new-output PYTHONDONTWRITEBYTECODE=1 \
python experiments/diagnosis_baseline/generated-results-20261004/fixfirst/replay_portable.py
```

这只重放固定观察，不启动 LLM、运行项目测试或安装依赖。代码包含拒绝外部 I/O 的守卫；它不是针对恶意代码的系统沙箱。

## 保存范围

- `run/answers/`：6 份原始封存文件，逐字节不变。
- `inputs/`：标签、模型文件身份、6 份原始会话快照，逐字节不变。
- `fixfirst/`：两版逐例预测、计数、输入/源码绑定、补充计时。
- `recorded-audit/`：独立复核回执；LLM 回执的一处本机解释器前缀替换为 `<LOCAL_MODEL_ENV>`，另命名为 `.sanitized.json`。公开包的复算以 `verify.py` 为准。
- `PACKAGING.json`：34 份原件的来源/摘要和脚本路径改写说明。`SHA256SUMS.json` 覆盖本包其他文件。

本机解释器路径、启动配置和 1500 份重复请求日志留在本地。登记文件里对这些本地材料的摘要仍保留，但本包不能重查缺席的材料。第一次产品重放因漏预载模块失败，原尝试留在本地；后来只修评估器预载，再完整重跑。摘要能发现内容变化，不能证明运行时间顺序或抵御整套文件和摘要一起伪造。

本提交叠在 #66 的真实项目结果分支之上，并带入与 #53 逐字节相同的接入和评分工具，作为生成批次发送/计分的共同依赖；#61 的匿名评分材料已在 #66 基线里。生成案例与真实项目成绩分开报告；没有修改 v0.7.0、v0.8 候选或已有封存回答。
