# 核心诊断第五轮：Claude 的开发复现与交叉复核（2026-09-30）

**当前收尾状态**：D1–D4 已在 `ba52e22` 复查关闭；SQLAlchemy 的后续消费误报经过 `a56a621`、`18f2875` 修正后，已完成 12 项 SQL 对照和最后差异复核。包装器与 lambda 正例仍是明确记录的漏判，修复建议已实际验证。交叉复核记录提交于 `ff2d9f0`；最新汇总见 [ROUND5.md](../ROUND5.md)。下方保留各次原始发现，不是当前未修清单。

分工：Codex 修改核心证据、诊断和建议；Claude 负责复现、反例、实际执行建议和交叉复核，不改生产代码。

以下全部是**开发材料**：不是独立留出，不是人工金标准，也不是自动修复率。没有启动语言模型或付费 API，没有碰 A1/C1、BugsInPy、正式实验和冻结。

## 做了什么

- **九个开发案例**：`../round5_cases.py`。
  - 4 个版本变化正例、4 个普通错误反例、1 个健康对照。
  - 每例都是新建的小项目，依赖固定，并有一个旧版本对照环境：正例在旧版本上能通过；反例在旧版本上同样失败。
  - 标签、目标错误和参考修法在运行 FixFirst 之前已提交（`fa4d7f7`），之后没有改过。
- **复核探针**：`../round5_review_probes.py`，共 17 个。预期先提交再运行（`857927a`、`623bb6f`）。覆盖类型来源、Pydantic 的动态输入/别名/校验器、`solve` 的尺寸、锁文件与固定版本的优先级，以及没有声明依赖的真实正例。
- **按第一步执行**：`../round5_review_steps.py`。编辑依据 FixFirst 实际给出的第一步推出，并写明每条信息来自哪里，然后在副本里执行原测试。

## 结果

| 实现 | 9 例中根因正确 | 第一步 |
|---|---|---|
| main `3924413`（默认内置树） | 4/8 个故障 + 对照正常 | 只有 P3 能执行且有效，靠的是宽泛的 H08。N1 的 `pip install 'pyyaml<6'` 在 3.12 上构建失败；N2 降级后错误照旧 |
| 同上，改用 61 特征候选 | 与内置树完全相同 | 与内置树完全相同 |
| Codex `35c9246` | 8/8 + 对照正常 | 完全满足 3（P1、P3、P4），部分指导 3（P2、N1、N2），通用建议 2（N3、N4）。8 个编辑执行后全部通过，测试不改 |

P4 的位置只列了导入行；如果只改那一行，第 5 行会报 NameError。

**复核中确认的缺陷**（最小复现在 `results/review-codex-35c9246.json`）：

1. **NumPy 2.0–2.2 的 `a.ptp()` / `a.newbyteorder()` 漏判。** 方法调用时，NumPy 的自定义删除错误不带 `AttributeError.name/obj`，运行时元数据因此记不到。探针 `newbyteorder_real`。
2. **Pydantic Optional 规则误报：值传给了另一个合法字段。** 系统建议加 `= None`，照做后测试仍失败。探针 `optional_swapped_valid_key`。
3. **输入错误不在已知清单里时，H06 仍按旧锁文件建议回退。** 奇异矩阵加上 uv.lock，执行 `pip install 'numpy<1.27'` 后仍然失败。探针 `lockfile_singular_matrix`。
4. **没有 requirements 或锁文件的新手项目，拿不到新增的迁移建议。** 因为 H10 需要 G14/G15 推出的版本上下文。探针 `undeclared_copy_false` 和 `undeclared_optional_required`。

**边界，漏判但没有误报**：
- `solve` 的方程组个数等于阶数时，NumPy 2 不报错，只返回不同形状；
- Pydantic 传入的是别名；
- 项目里任何一处用了 validator；
- 子类继承的 ptp。

**通过，没有误报**：
- `solve` 维度本来就不匹配；
- 字段写成 `Field(...)`；
- 锁文件或固定版本同时存在时，reshape 的输入错误仍然优先；
- 项目自己的 `class ndarray` 没有 ptp；
- packaging 的 `parse("nightly")` 被判为版本变化（H10），`Version("nightly")` 被判为输入错误（H12）。

## D1 修法复核（`4bded78`）

- **3.12 + numpy 2.2.6**：参数、局部变量、全局变量、闭包、前面还有另一个局部变量等所有直接名字接收者都判为 D03；属性链按设计不推断；没有误报。
- **3.13 + numpy 2.2.6**：只有同一行连读两个局部变量（`LOAD_FAST_LOAD_FAST`）时漏判。
- **3.14 + numpy 2.3.5**：凡是局部变量接收者都漏判（`LOAD_FAST_BORROW` 及其合并形式），全局变量和闭包仍能判出。numpy 2.3.5 的删除错误同样不带 `name`，所以这种组合会实际遇到。
- 第一步给出了具体替换，按它编辑后测试都通过。
- 建议：把 `LOAD_FAST_BORROW` 当作 `LOAD_FAST` 处理；对以元组为参数的合并指令，取最后一个名字作为接收者。
- 结果文件：`results/review-codex-4bded78*.json`。

## SQLAlchemy 历史核实

- **"1.4 legacy 直接迭代得到空列表、2.0 才报错"不成立。** 在 1.3.24、1.4.54、2.0.44 中，对不返回行的结果做迭代都会抛 `ResourceClosedError`。
- **真正的分界在 1.3 → 1.4。** 从 1.4 起，只是创建迭代器（例如 records 0.5.3 的 `query()` 构造生成器）就会立即抛错，1.3 则是懒执行。
  - 源码依据：1.4 与 2.0 的 `_iterator_getter` 会读取 `_row_getter`，进而读取 `_NoResultMetaData._keymap`；1.3 的 `ResultProxy.__iter__` 是生成器函数。
- **1.4 → 2.0 变化的是 `keys()`**：1.4 legacy 返回 `[]` 并发出 RemovedIn20Warning，2.0 改为抛错。
- **修法**：`returns_rows` 判断在所有版本都有效。records 上游 0.6.0 就是用 `returns_rows` 修的，`<2` 的版本上限不能修好这个问题。
- **反例**：`fetchall()` 和迭代已关闭的结果，在所有版本都失败。
- **文档出处未知**：抓取到的 1.4 changelog 和迁移指南里都没有找到相关条目。
- 结果文件：`results/sqlalchemy-*.json`、`results/records-*.json`；检查脚本：`../round5_sqlalchemy_history.py`。

## 最终复查（生产 head `ba52e22`）

- **9 例**：根因 8/8，健康对照正常。第一步中完全满足 3 个（P1、P3、P4），部分指导 4 个（P2、N1、N2、N4），通用建议 1 个（N3）。8 个编辑执行后都通过，测试未改。
- **46 个探针**：D1–D4 全部关闭。
  - D1：3 个 Python 版本上的 21 个直接名字接收者全部判为 D03。
  - D2：值传给另一个合法字段时判为 H12。
  - D3：奇异矩阵加锁文件时不再建议降级。
  - D4：没有声明依赖的项目也能给出迁移建议。
- **唯一确认的问题**：`sqla_generator_then_consumed`。同一函数里先构造生成器、随即消费，在 1.3 下同样失败，却被判为 1.4 的变化（H10）。不过它的 `returns_rows` 第一步在 2.0.44 和 1.3.24 下都能修好；错的只是标签和解释。
- **保留的边界**：solve 不报错只改形状、Pydantic 别名或 validator 正例、子类 ptp、属性链接收者。
- 结果文件：`results/*-codex-ba52e22*.json`。

## 最后有界复核（`a56a621`，与 PR #46 head `a0056b5` 的 src 相同）

- **上一轮的问题已关闭**：`sqla_generator_then_consumed` 现在是 H12 code_defect。原 5 个 SQLAlchemy 探针，以及别名后 `list`、`for` 循环、records 式包装的正例，结果都正确。
- **这次改动范围内仍有 3 个具体复现**：`[*rows]`、`sep.join(… for row in rows)`、在嵌套函数里消费。它们在 1.3 下同样失败，却仍被判为 H10 版本变化。影响只在标签和解释：`returns_rows` 这一步在 2.0.44 和 1.3.24 下都能修好。
  - 原因：`generator_consumption` 没有处理 Starred，没有处理派生生成器作为参数的情况，也没有看嵌套函数。
- **lambda 里构造的生成器**：缺少上下文，不作推断。这是预期中的漏判，不算误报。
- 结果文件：`results/review-codex-a56a621.json`、`results/interpreted-codex-a56a621-sqla.json`。

## 闭环复查（`18f2875`）

- **已消除**：3 个残余误报（`[*rows]`、`join`、嵌套函数消费）现在都判为 H12。12 个 SQL 探针里，凡是在 1.3 下同样失败的，都不再被判为 1.4 的变化。
- **保留**：构造后裸 `return` 的正例仍判为 H10。
- **wrapper 取舍**：`return Wrapper(rows)` 无法证明不会消费，所以不再推断版本。
  - `sqla_wrapped_not_consumed` 因此成为新的保守漏判，原预期不改；lambda 漏判同样保留。
  - 这两例按 H12 的 `returns_rows` 这一步修改后，在 2.0.44 和 1.3.24 下都能通过，所以只影响标签。
- **已知边界，不是本次差异引入的**：裸 `return` 之后调用方是否消费，看不到（docstring 已写明）。
- 结果文件：`results/review-codex-18f2875.json`、`results/interpreted-codex-18f2875-sqla.json`。

## 复现

先用 `round5_cases.py build` 建好环境。packaging 的两个探针还需要另建 `RUNS/packaging-old/venv`（packaging 21.3 + pytest）。`RUNS` 不能放在任何项目目录里。

```bash
cd experiments/core_diagnosis
python round5_cases.py build --out RUNS
python round5_cases.py reference --out RUNS
PYTHONPATH=/path/to/implementation/src python round5_cases.py diagnose --out RUNS --tag TAG
PYTHONPATH=/path/to/implementation/src python round5_review_probes.py --runs RUNS --tag TAG
python round5_review_steps.py --runs RUNS --tag TAG
```

结果都保存在 `results/`，本机路径已替换为 `<runs>`、`<home>`、`<tmp>`。
