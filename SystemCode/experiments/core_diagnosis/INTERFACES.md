# 核心诊断：2026-09-30 第四轮接口证据与实际建议验证

本轮完成了两项可复现的诊断修复，并实际执行系统给出的第一步。模型方面做了五组对照及有限深度检查，**没有选出同时满足误报和难例要求的新候选**；第三轮的 61 特征候选继续保留。

起点：`6edc1501fc99ddcbf57062d9adb88e267d06dbbd`。实现：`5bcb13d4358d26987238af4971fa33dbc4a60861`。所有数据均为开发材料，A1/C1 独立留出没有参与。

## 1. 修复了哪些实际问题

### 错误参数必须匹配实际调用对象

旧 D04 看到 `squared` 就可能套用 scikit-learn 的删除记录。即使调用的是 NumPy 或 scikit-learn 中完全不同的类，也会给出错误迁移建议。

| 实际执行的程序 | 旧代码 | 当前代码 |
|---|---|---|
| `numpy.array([1], squared=False)` | 确认版本问题，建议替换 scikit-learn 的参数 | 参数使用错误假设，检查 `numpy.array` 的调用 |
| `StandardScaler(squared=False)` | 同样套用参数删除记录 | 参数使用错误假设，检查 `StandardScaler` 的调用 |
| 为 `mean_squared_error` 起别名后传入 `squared=False` | 判断为已删除参数 | 仍正确判断为已删除参数 |

两套代码分别从真实失败采集结果，关闭分类器以隔离规则贡献。[旧代码结果](interface-development-2026-09-30/call-scope-before.json)、[当前结果](interface-development-2026-09-30/call-scope-after.json)和 [probe](call_scope_probe.py)均保存。

历史记录现在绑定具体 callable，再核对版本和失败参数。静态索引同时保存调用处写下的别名与解析后的目标，修复了别名和原函数名称不同导致来源丢失的问题。类的相近属性名只与该类自己的成员比较，不借用其他类里的同名方法。

参数历史依据：[OneHotEncoder 1.3 API 的 sparse 删除说明](https://scikit-learn.org/1.3/modules/generated/sklearn.preprocessing.OneHotEncoder.html)、[mean_squared_error 1.5 API 的 squared 删除说明](https://scikit-learn.org/1.5/modules/generated/sklearn.metrics.mean_squared_error.html)。缺失模块的历史来源沿用 [Python 3.12 删除记录](https://docs.python.org/3/whatsnew/3.12.html)。

### 版本搜索不能跳过可用区间后一直尝试更老版本

实际执行 flask-sqlalchemy 的第一步时发现：搜索先确认 Flask 3.x 缺少 `_app_ctx_stack`，随后跳到 2.0.3。2.0.3 及多个更老版本安装或导入失败，算法继续向更老版本走，最后用完 12 次预算，却没有尝试可用的 2.3.3。

现在遇到这种失败，会先检查跳跃过程中遗漏的较近版本。**同一项目第 5 次尝试找到 Flask 2.3.3**，随后系统自己生成安装命令；执行后目标导入错误消失，测试推进到 5 passed、68 failed。后续失败仍保留，不称为整个项目修复完成。

如果有限搜索仍没有结论，系统会显示“搜索未能确认兼容版本”的具体下一步，不再重复提供同一条搜索建议，也不会据此断言旧版从未提供该 API。已知安装版本改变后，旧搜索记录失效。对应成功、失败及缓存证据均有回归覆盖。

## 2. 这次执行的是系统建议

每个项目重新导出固定源码、建立独立环境并进入沙箱。先保存系统生成的 Action，再执行其命令；没有用第三轮参考修法替代它。只有 cachetools 使用建议文字明确列出的 `pip install -e .` 方案，并标为人工解释的执行。测试文件和选择设置未修改。

| 项目 | 实际系统动作 | 验证结果 |
|---|---|---|
| cachetools | 建议文字中的 editable install | 215 passed，目标导入问题解决 |
| typer | 系统命令安装 shellingham | 492 collected，验证范围为收集 |
| records | 系统命令 `sqlalchemy<1.3`，实际安装 1.2.19 | 目标 result 错误消失，23 passed/16 failed → 33 passed/6 failed；后续 SQLite 问题仍在 |
| django-model-utils | 先执行版本搜索，再执行系统生成的 Django 3.2.25 安装命令 | 300 collected，验证范围为收集 |
| flask-sqlalchemy | 修正搜索后，执行系统生成的 Flask 2.3.3 安装命令 | 原导入错误消失，5 passed/68 failed，存在后续问题 |
| parsel | 系统命令只安装 six | six 错误消失，随后暴露 lxml 缺失；仍未恢复收集，不算完成验证 |
| more-itertools | 健康对照，没有修复动作 | 670 passed、1 skipped |

因此，**6 个故障中有 5 个完成了表中声明范围的验证，1 个只推进到下一层依赖缺失**。这不是 5 个项目全套测试通过，也不是独立测试集的修复成功率。新的人工复核仍待完成。

records 上轮执行的是参考版本 1.3.24，本轮原样执行了系统的 `<1.3` 建议，两种执行证据现在已经区分并补齐。Flask 搜索未成功的首次尝试也保留。

[first-step-verification.json](interface-development-2026-09-30/first-step-verification.json)保存 8 条尝试记录：7 个项目（含健康对照）加 Flask 修后复验。包括第一动作、检查后动作、执行来源、命令、退出状态、测试摘要、后续错误、清理结果和原始记录哈希；不包含环境目录。`manual_action_requires_interpretation` 是旧审计脚本对 Flask 首次未能生成可执行后续动作的记录，检查其 `inspection` 可见实际原因为搜索未判定；当前脚本将其明确记为 `inspection_inconclusive`。

## 3. 模型训练对照

本轮增加作用域/成员证据，并把已有的接口历史元数据作为可关闭的实验特征。schema 6 共 65 个特征，保留 44、49、61 特征模型的前缀兼容。

**带接口历史的树使用了有出处的知识信息。** 相应收益不能全部解释为模型从训练样本中自主学到了版本知识。关闭知识的诊断和评估也关闭直接历史特征及其反向衍生特征，避免消融实验悄悄读取知识。未匹配历史记录仅表示未知，不证明调用正确或错误。

相同深度 6、叶大小 2、种子 42；同一故障的新旧观察始终在同一组。原 430 条配对观察仍是 215 个案例、43 类故障。加入的 15 个误用训练案例来自第三轮，分为 3 个相关故障族。14 个保留反例、30 个难例和真实项目不参与本轮训练。

| 训练方案，仅树 | 新观察留一故障 | 普通反例 | 新难例 | 旧难例 | 真实开发故障 |
|---|---:|---:|---:|---:|---:|
| 上轮 61 特征参照 | 190/215 | 11/14 | 15/30 | 10/30 | 5/6 |
| 新观察关系，关闭接口历史 | **195/215（90.70%）** | 11/14 | 15/30 | 10/30 | 5/6 |
| 新观察关系 + 接口历史 | 190/215 | 11/14 | 15/30 | 10/30 | 5/6 |
| 新观察关系 + 误用训练案例 | 190/215 | **14/14** | 5/30 | 10/30 | 5/6 |
| 再加入接口历史 | 195/215 | **14/14** | 5/30 | 5/30 | 4/6 |

在这些输入上，完整系统继续保持生成案例 215/215、难例 30/30、普通反例 14/14、真实根因 6/6。这些根因结果不能代替第 2 节的行动验证。

接受条件要求分组结果、两类快照难例和真实开发案例不退步，同时纯树反例至少恢复到 13/14。**五组中没有一组同时满足条件，因此没有替换第三轮候选。** 不能只报告 90.70%，或者只报告加入反例后 14/14。

另外检查了深度 4、6、8、10；加入误用数据的模型仍只有 5/30 个新难例正确。没有采用新深度，也没有用这次开发集选参数的最高分作为独立验证结果。[深度筛查记录](interface-development-2026-09-30/depth-screen.json)保存所有 16 种组合。

新观察来自保留的开发 fixture 源码：刷新静态调用与类成员信息，原先的调用和基类索引须逐例一致；错误输出使用已有采集记录，**没有把静态刷新写成重新执行全部测试**。源文件哈希和新增索引见 [static-metadata.json](interface-development-2026-09-30/static-metadata.json)。这些数据已参与开发判断，不能承担最终独立评测。

## 4. 校验与复现

- Mac 主测试：**424 passed、1 skipped，50.08 秒**；Ruff 和 `git diff --check` 通过。
- 新增 17 个检查：接口作用域、别名、同名参数反例、历史版本缺失/不适用、本地遮蔽、类成员归属、61 特征兼容、知识消融、搜索失败区间和未判定结果。
- 原始源码与环境未被审计脚本修改；未启动语言模型训练或服务，未做正式冻结，A/C 现有分工不变。
- 没有产生可替换上一轮的新候选。目录中的消融模型必须使用记录的特征变换回放，**不是可直接传给 CLI 的候选模型**；可直接使用的候选仍见[第三轮报告](OBSERVATIONS.md)。

离线重放训练与验证，不执行第三方项目，输出目录必须不存在：

```bash
.venv/bin/python experiments/core_diagnosis/round4_compare.py \
  --metadata experiments/core_diagnosis/interface-development-2026-09-30/static-metadata.json \
  --output workbench/interface-comparison-repeat
```

重新执行实际建议验证，需要 macOS、uv、联网安装依赖及旧公开项目的源码克隆。每次输出到新的独立目录：

```bash
.venv/bin/python experiments/core_diagnosis/verify_first_step.py \
  --sources /path/to/public-development-projects \
  --output /path/to/new-first-step-runs
```

下一步的主要模型缺口仍是普通代码/输入错误与未知库行为变化之间的迁移，当前简单加数据或加深树没有同时解决。应优先补均衡的、经过人工核实的开发故障，并在新增开发案例上检查误报和修法；保留独立最终评估。
