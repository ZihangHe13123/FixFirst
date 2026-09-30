# 第五轮：减少错误降级，补具体迁移建议

基线：main `39244136ec06ff1d3a714cdb9a3a11c213b189ea`。最终生产源码 `18f2875`。主要实现及交叉复核经过 `35c9246`、`4bded78`、`ba52e22`、`a56a621`；各原始记录保留自己的实际提交与源码哈希。

本轮由 Claude 准备案例与参考修法、执行反例和交叉复核，Codex 修改核心诊断、执行建议并检查回归。Claude 在 `ba52e22` 上确认 D1–D4 已关闭；SQLAlchemy 的后续消费误报经过 `a56a621`、`18f2875` 两次收紧后，也已在 Claude 的 12 项新旧版本对照中复查关闭。最后一次生产差异未发现新的可复现缺陷，记录于 Claude 的 `ff2d9f0`。**交叉复核已完成，PR 可进入合并评审；尚未合并。**

## 结果如何理解

这批是 **9 个受控开发案例：8 个故障、1 个健康对照**。标签、预期第一步与参考修法在运行 FixFirst 之前固定于 Claude 的 `fa4d7f7`；实现随后看到了这些案例并据此改进。它们不是独立留出，也不是人工金标准，不能据此宣称真实项目准确率为 100%。

- 默认完整系统根因正确：**4/8 → 8/8**。健康案例两次均通过，没有必做修复步骤。
- 旧系统给出的三个降级命令中：NumPy solve 的降级实际有效；reshape 降级后仍失败；PyYAML 降级安装本身失败。
- 新系统给出七项有针对性的建议。**Codex 阅读建议与项目后，把它们转成具体编辑，再执行原测试：7 项均通过，测试未改。** 这证明这些解释过的修法可行，不是自动修复率。
- Claude 的独立评级：**3 项完全满足、4 项部分指导、1 项通用建议**。Pydantic 拼写问题现在会提醒比较实际传入的键；Click 选项拼写仍通用，未计入七项有效解释后的修法。
- **模型权重和特征布局未改。** 在这 9 例的旧系统中，换成 61 特征候选后最终判断、第一步均无变化。收益来自新增观察、具体知识和规则选择。

| 开发案例 | 旧系统 | 新系统 | 实际验证与剩余缺口 |
|---|---|---|---|
| NumPy `copy=False` | code_defect，通用检查 | 版本假设；保留 dtype，改用 `asarray` | 按建议修改后通过 |
| Pydantic Optional 无默认值 | code_defect，通用检查 | 版本假设；声明中补 `= None` | 修改后通过；界面位置仍是构造调用，需自行找到字段声明 |
| NumPy 批量 `solve` | 版本假设；降级有效 | 版本假设；根据实际 a/b 形状明确列向量 | 按给出的表达式修改后通过 |
| Python 3.12 `SafeConfigParser` | 版本可能；通用导入检查 | 已知删除；替换成 `ConfigParser` | 修改导入和构造调用后通过 |
| YAML 制表符缩进 | 错误建议降级 PyYAML | 输入语法问题；检查报错行列和缩进 | 根据错误信息改为空格后通过；非自动生成补丁 |
| NumPy reshape 多加一列 | 错误建议降级 NumPy | 输入形状问题；尺寸必须匹配 | 结合预期矩阵去掉 `+1` 后通过；非自动生成补丁 |
| Click 选项拼写 | code_defect，断言检查 | 保持原判断与通用建议 | 缺少选项声明定位，不计有效修法 |
| Pydantic 普通字段拼写 | code_defect，通用检查 | code_defect；比较缺失字段与实际传入键 | 按此检查修正拼写后通过；具体拼写仍需阅读调用处 |
| 健康项目带弃用警告 | 通过，无必做步骤 | 相同 | 健康对照保留 |

## 改动依据与范围

1. **退休 H08/P62 的宽泛降级推断。** `numpy>=1.21` 只声明版本下限，不能证明项目曾在 1.x 测试通过。H06 只在导入、属性或签名这类 API 证据存在时考虑锁版本差异，不能对奇异矩阵等数值失败推断降级；锁定版本也不再被说成“已测试通过”。H10 匹配具体历史变化。[PyPA 版本说明](https://packaging.python.org/en/latest/specifications/version-specifiers/)
2. **输入错误优先给相应检查。** 实际库来源与异常类型匹配后，针对 reshape、轴越界、YAML 语法、Click 参数值和非法版本字符串提供检查要点；不用降低版本掩盖错误。[NumPy reshape](https://numpy.org/doc/stable/reference/generated/numpy.reshape.html)、[AxisError](https://numpy.org/doc/stable/reference/generated/numpy.exceptions.AxisError.html)、[PyYAML](https://pyyaml.org/wiki/PyYAMLDocumentation#yamlerror)、[Click](https://click.palletsprojects.com/en/stable/parameter-types/)、[packaging Version](https://packaging.pypa.io/en/stable/version.html)
3. **补具体历史变化。** 增加 NumPy 的严格 `copy=False`、`ndarray.ptp/newbyteorder` 删除、`solve` 批量向量含义变化；Pydantic Optional 必填变化；packaging 22 删除 LegacyVersion；Python 3.12 删除 SafeConfigParser。各条都有官方出处，实际调用对象、版本上下文及反例约束。[NumPy 迁移](https://numpy.org/doc/2.0/numpy_2_0_migration_guide.html)、[solve](https://numpy.org/doc/stable/reference/generated/numpy.linalg.solve.html)、[Pydantic 迁移](https://docs.pydantic.dev/latest/migration/#required-optional-and-nullable-fields)、[packaging 历史](https://packaging.pypa.io/en/stable/changelog.html)、[Python 3.12](https://docs.python.org/3/whatsnew/3.12.html)
4. **补 pytest/unittest 的实际运行证据。** 有界采集 AttributeError 的真实对象类型、solve 的 a/b 形状、Pydantic 缺失字段及传入键名。这些新增结构字段不保存数组或输入值；原有异常文字仍按原逻辑保存。仅文字伪装、同名本地对象、普通必填字段、未知键、错误矩阵尺寸不直接触发迁移。
5. **兼容旧 NumPy 的无上下文异常。** NumPy 2.2/2.3 的删除提示不带 `name/obj`。仅从实际失败的属性加载指令及直接名称接收者恢复类型，覆盖 Python 3.12–3.14 的普通、借用和合并加载；分支汇合、属性链等无法确定的情况不猜。21 个直接名称接收者对照通过。[Python 指令文档](https://docs.python.org/3.14/library/dis.html)
6. **收紧 Pydantic 假设。** 有另一个传入的可空字段或相近字段名时，先检查值是否传错位置，不建议直接补默认值。对精确匹配的 NumPy/Pydantic 症状，没有依赖声明也可给假设；明确从新版开始的声明仍不套旧行为。
7. **SQLAlchemy 的具体变化。** 源码和 SQLite 对照确认：1.3 的迭代器惰性创建，1.4 起立即读取结果元数据；不是“1.4 能迭代出空行、2.0 才不行”。已采集的同一函数上下文里若有后续消费，不归为升级；缺少上下文、未知调用、包装器或嵌套捕获也不套用版本解释，仍保留 `returns_rows` 输入检查建议。只有直接别名和裸返回等简单惰性用途支持这条假设。这个静态检查不证明其他函数不会消费已返回的生成器。[1.3 源码](https://github.com/sqlalchemy/sqlalchemy/blob/rel_1_3_24/lib/sqlalchemy/engine/result.py)、[1.4 源码](https://github.com/sqlalchemy/sqlalchemy/blob/rel_1_4_54/lib/sqlalchemy/engine/result.py)

最后 12 项 SQL 对照中，解包、`join` 与嵌套函数消费的三个误报已消除，简单惰性正例保留。**包装类正例由版本标签降为 H12/code_defect，是新增的保守漏判；lambda 正例也仍漏判。** 原预期没有改写。这两个案例按 H12 建议补 `returns_rows` 判断后，在 SQLAlchemy 2.0.44 和 1.3.24 下都通过，测试文件未改。这只证明这两项解释后的修法有效，不说明根因标签正确。

新增元数据目前只在 pytest/unittest 的探针采集。脚本、模块和 notebook 仍可使用已有的文本与静态证据，但不能宣称上述依赖新元数据的匹配已全部适用于它们。没有添加新的运行适配层。

后续三组实验还需核对事实视图：当前 `facts.py` 的白名单没有导出新的形状及校验键名。正式比较前应补齐中性观察，或明确报告两组拿到的事实差异；本轮不据此声称已经隔离测出了诊断建议的增益。

## 原有开发记录回放

在完全相同的记录和模型上，用旧/新源码回放；不执行原项目，不重训。**有一项明确退步**：旧 `real-records` 快照没有新采集的生成器消费上下文，因此不再凭那一行代码推断升级，按原标签从 6/6 变成 5/6；建议仍是 `returns_rows` 检查。最终 `18f2875` 回放与 `a56a621` 的全部预测相同。重新采集也不能保证恢复版本标签：包装器用途未知时，系统仍给保守的 H12 建议。不能把缺失的上下文假定为安全，也不能宣称这一项准确率已经恢复。

| 记录集 | 默认 44 特征：前 → 后 | 候选 61 特征：前 → 后 |
|---|---:|---:|
| 重采集生成案例 | 215/215 | 215/215 |
| 重采集难例 | 30/30 | 30/30 |
| 保留开发反例 | 14/14 | 14/14 |
| 已有真实项目观察 | 6/6 → 5/6 | 6/6 → 5/6 |
| 旧生成快照 | 210/215 | 215/215 |
| 旧难例快照 | 30/30 | 30/30 |

上述集合有重叠，包含训练材料；不能相加作为独立样本数。旧记录缺少新增运行元数据。本轮不把“在旧记录上无回退”当作所有真实项目都不退步的证明。

## 检查与证据

- 新增输入/迁移检查 **56 个通过**，含实际库执行、同名/伪造文本、版本边界、旧锁文件、生成器上下文及原测试不变。
- 最终生产源码 `18f2875`：主测试集 **558 passed、1 skipped**；macOS harness **58 passed**；Ruff 与 diff check 通过。没有新增 Windows 实机结论。
- [固定案例与环境构建脚本](round5_cases.py)，保留原先固定的标签与参考修法。
- [建议解释与执行脚本](round5_advice.py)：逐条保留 Codex 阅读建议后所作的解释，不读取参考补丁，不处理 Click 的通用建议。
- [环境清单](round5-development-2026-09-30/environments.json)、[参考修法结果](round5-development-2026-09-30/reference.json)。
- [旧系统输出](round5-development-2026-09-30/before.json)、[旧候选输出](round5-development-2026-09-30/before-candidate61.json)、[旧降级命令实际结果](round5-development-2026-09-30/before-command-execution.json)。
- [同一宿主解释器上的旧系统复查](round5-development-2026-09-30/before-same-host.json)：Codex 用相同案例环境、宿主 Python 3.12.14，导入 main `3924413`，再次得到与 Claude 相同的九项判断和第一步。Claude 原记录的 `8e58b0e` 只多了案例脚本，`src` 与该 main 完全相同。
- [新系统输出](round5-development-2026-09-30/after.json)、[新建议解释后执行结果](round5-development-2026-09-30/after-manual-execution.json)。
- [旧记录回放比较及来源哈希](round5-development-2026-09-30/replay-comparison.json)、[原始/去路径记录的哈希](round5-development-2026-09-30/provenance.json)。
- [Claude 分轮复核及原始结果](round5-review-2026-09-30/README.md)，保留修复前的失败，不改写历史结果。
- [a56a621 阶段五项 SQLAlchemy 复查](round5-development-2026-09-30/final-sqlalchemy-probes.json)：懒创建正例与后续消费、list、fetchall、显式 close 反例。
- [最终十二项 SQLAlchemy 复查](round5-development-2026-09-30/final-consumption-probes.json)，以及 [Claude 同提交的独立执行记录](round5-review-2026-09-30/results/review-codex-18f2875.json)；[两个保守漏判的建议执行记录](round5-review-2026-09-30/results/interpreted-codex-18f2875-sqla.json)。

仍然未覆盖：NumPy solve 不抛异常而只改变结果形状、Pydantic 别名/部分自定义校验、ndarray 子类，以及缺少异常对象上下文时的复杂接收者。以上开发结果不代替独立评估。

## 复现

需要独立开发环境、uv 及网络下载公开测试依赖；`build` 的目标目录必须不存在。脚本只在各案例副本里操作：

```bash
.venv/bin/python experiments/core_diagnosis/round5_cases.py build --out /tmp/fixfirst-round5-new
.venv/bin/python experiments/core_diagnosis/round5_cases.py reference --out /tmp/fixfirst-round5-new
PYTHONPATH=src .venv/bin/python experiments/core_diagnosis/round5_cases.py diagnose \
  --out /tmp/fixfirst-round5-new --tag after
.venv/bin/python experiments/core_diagnosis/round5_advice.py \
  --out /tmp/fixfirst-round5-new --tag after
```

旧系统用同一脚本、环境与案例，把 `PYTHONPATH` 指向 `3924413` 的 `src`，换一个 tag；`first-step` 子命令执行记录里的降级命令，使用另建的环境副本。固定快照回放：

```bash
PYTHONPATH=src .venv/bin/python experiments/core_diagnosis/round5_replay.py \
  --repo . --code-head REVIEWED_COMMIT --output /tmp/round5-replay-after.json
```

本轮没有启动语言模型服务或付费 API，没有使用 A1/C1 留出、BugsInPy 或正式实验数据。模型训练和泛化验证仍需单独的数据与实验。
