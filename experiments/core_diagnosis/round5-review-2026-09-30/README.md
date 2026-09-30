# 核心诊断第五轮：Claude 的开发复现与交叉复核（2026-09-30）

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
