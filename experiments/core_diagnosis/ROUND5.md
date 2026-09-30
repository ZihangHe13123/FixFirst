# 第五轮：减少错误降级，补具体迁移建议

基线：main `39244136ec06ff1d3a714cdb9a3a11c213b189ea`。生产改动 `4b0baae`，建议措辞修正 `057dce3`，锁文件边界修复 `35c9246`；最终新执行记录来自 `35c9246`，源码干净。

本轮由 Claude 准备案例与参考修法、记录旧系统结果，Codex 修改核心诊断并执行新系统建议。**Claude 对最终实现的交叉复核尚未完成。** 以下区分两者各自已经执行的检查。

## 结果如何理解

这批是 **9 个受控开发案例：8 个故障、1 个健康对照**。标签、预期第一步与参考修法在运行 FixFirst 之前固定于 Claude 的 `fa4d7f7`；实现随后看到了这些案例并据此改进。它们不是独立留出，也不是人工金标准，不能据此宣称真实项目准确率为 100%。

- 默认完整系统根因正确：**4/8 → 8/8**。健康案例两次均通过，没有必做修复步骤。
- 旧系统给出的三个降级命令中：NumPy solve 的降级实际有效；reshape 降级后仍失败；PyYAML 降级安装本身失败。
- 新系统给出六项有针对性的建议。**Codex 阅读建议与项目后，把它们转成具体编辑，再执行原测试：6 项均通过，测试未改。** 这证明这些解释过的修法可行，不是自动修复率，也不是六项都完全满足预登记的位置要求。
- Click 选项拼写、普通 Pydantic 字段拼写仍是通用建议，未按“系统建议修好”计入。
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
| Pydantic 普通字段拼写 | code_defect，通用检查 | 保持原判断与通用建议 | 缺少拼写修正，不计有效修法 |
| 健康项目带弃用警告 | 通过，无必做步骤 | 相同 | 健康对照保留 |

## 改动依据与范围

1. **退休 H08/P62 的宽泛降级推断。** `numpy>=1.21` 只声明版本下限，不能证明项目曾在 1.x 测试通过。H06 保留锁文件差异这一线索，但有明确的输入错误时优先处理输入；提示也不再把锁定版本说成“已测试通过”。H10 匹配具体历史变化。[PyPA 版本说明](https://packaging.python.org/en/latest/specifications/version-specifiers/)
2. **输入错误优先给相应检查。** 实际库来源与异常类型匹配后，针对 reshape、轴越界、YAML 语法、Click 参数值和非法版本字符串提供检查要点；不用降低版本掩盖错误。[NumPy reshape](https://numpy.org/doc/stable/reference/generated/numpy.reshape.html)、[AxisError](https://numpy.org/doc/stable/reference/generated/numpy.exceptions.AxisError.html)、[PyYAML](https://pyyaml.org/wiki/PyYAMLDocumentation#yamlerror)、[Click](https://click.palletsprojects.com/en/stable/parameter-types/)、[packaging Version](https://packaging.pypa.io/en/stable/version.html)
3. **补具体历史变化。** 增加 NumPy 的严格 `copy=False`、`ndarray.ptp/newbyteorder` 删除、`solve` 批量向量含义变化；Pydantic Optional 必填变化；packaging 22 删除 LegacyVersion；Python 3.12 删除 SafeConfigParser。各条都有官方出处，实际调用对象、版本上下文及反例约束。[NumPy 迁移](https://numpy.org/doc/2.0/numpy_2_0_migration_guide.html)、[solve](https://numpy.org/doc/stable/reference/generated/numpy.linalg.solve.html)、[Pydantic 迁移](https://docs.pydantic.dev/latest/migration/#required-optional-and-nullable-fields)、[packaging 历史](https://packaging.pypa.io/en/stable/changelog.html)、[Python 3.12](https://docs.python.org/3/whatsnew/3.12.html)
4. **补 pytest/unittest 的实际运行证据。** 有界采集 AttributeError 的真实对象类型、solve 的 a/b 形状、Pydantic 缺失字段及传入键名。不保存数组或字段值。仅文字伪装、同名本地对象、普通必填字段、未知键、错误矩阵尺寸不直接触发迁移。

新增元数据目前只在 pytest/unittest 的探针采集。脚本、模块和 notebook 仍可使用已有的文本与静态证据，但不能宣称上述依赖新元数据的匹配已全部适用于它们。没有添加新的运行适配层。

## 原有开发记录回放

在完全相同的记录和模型上，用旧/新源码回放；不执行原项目，不重训。**两种固定模型的完整系统结果均无变化**，逐行预测变化列表为空：

| 记录集 | 默认 44 特征：前后相同 | 候选 61 特征：前后相同 |
|---|---:|---:|
| 重采集生成案例 | 215/215 | 215/215 |
| 重采集难例 | 30/30 | 30/30 |
| 保留开发反例 | 14/14 | 14/14 |
| 已有真实项目观察 | 6/6 | 6/6 |
| 旧生成快照 | 210/215 | 215/215 |
| 旧难例快照 | 30/30 | 30/30 |

上述集合有重叠，包含训练材料；不能相加作为独立样本数。旧记录缺少新增运行元数据。本轮不把“在旧记录上无回退”当作所有真实项目都不退步的证明。

## 检查与证据

- 针对性测试 74 passed；其中新增真实输入/迁移测试 29 个，含 pytest/unittest、同名与伪造文本反例、版本边界、有/无旧锁文件、原测试不变。
- 最终生产源码 `35c9246`：主测试集 **531 passed、1 skipped**；前一版核心源码的 macOS harness **58 passed**（之后只改输入/锁文件规则和说明，未改 harness）；Ruff 与 diff check 通过。没有新增 Windows 实机结论。
- [固定案例与环境构建脚本](round5_cases.py)，保留原先固定的标签与参考修法。
- [建议解释与执行脚本](round5_advice.py)：逐条保留 Codex 阅读建议后所作的解释，不读取参考补丁，不处理两个通用建议。
- [环境清单](round5-development-2026-09-30/environments.json)、[参考修法结果](round5-development-2026-09-30/reference.json)。
- [旧系统输出](round5-development-2026-09-30/before.json)、[旧候选输出](round5-development-2026-09-30/before-candidate61.json)、[旧降级命令实际结果](round5-development-2026-09-30/before-command-execution.json)。
- [同一宿主解释器上的旧系统复查](round5-development-2026-09-30/before-same-host.json)：Codex 用相同案例环境、宿主 Python 3.12.14，导入 main `3924413`，再次得到与 Claude 相同的九项判断和第一步。Claude 原记录的 `8e58b0e` 只多了案例脚本，`src` 与该 main 完全相同。
- [新系统输出](round5-development-2026-09-30/after.json)、[新建议解释后执行结果](round5-development-2026-09-30/after-manual-execution.json)。
- [旧记录回放比较及来源哈希](round5-development-2026-09-30/replay-comparison.json)、[原始/去路径记录的哈希](round5-development-2026-09-30/provenance.json)。

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
