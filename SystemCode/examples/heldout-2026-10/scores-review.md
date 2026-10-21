# Agreement on score: scores-A.csv vs scores-C.csv

- Projects in both files: 12
- Same score: 9 of 12 (75%)
- Cohen's kappa: 0.66

| Project | score (first) | score (second) | notes (first) | notes (second) |
|---|---|---|---|---|
| click | wrong | wrong | wrong_if 命中（将首个阻塞归为 project code/tests 缺陷）；第一步也只是手动查看原输出；F01，无规则支撑的统计猜测；hedged | 归因"项目代码或测试的缺陷"，命中 wrong_if（把首次失败归到 click 源码），第一步为通用调查；hedged=yes（只说"可能"） |
| pytest | generic | generic | 轴 A 不成立：第一步仅要求检查工具是否可用/是否跑完，未具名 Python 3.12 与 pinned pytest 6.2.5 的版本兼容问题 | 未给出原因，第一步"确认工具可用并跑完"为通用检查 |
| dateparser | partial | partial | partial_if 命中：已具名缺失依赖 fasttext，但 FixFirst 给的第一步不可执行 —— twin 实测 pip install --only-binary=:all: fasttext 报 'No matching distribution found'（pip 日志：'No sources permitted for fasttext' 丢弃了唯一可用的 sdist），3 个 No module named fasttext 错误不变；证据 twins/dateparser.a2-first-step.txt | 原因正确（缺 fasttext）且给了安装命令，但未处理 Windows/Python 3.12 下的原生编译要求，命中 partial_if |
| python-qrcode **differs** | generic | partial | 轴 A 不成立：虽归类为 version incompatibility，但第一步仅检查 import path/dependency declarations，未具名 Windows 的 %-d strftime 平台兼容问题；F01；hedged | 原因类别正确（版本不兼容），命中 partial_if（认出问题但未修 %-d）；hedged=yes（只说"可能"）；第一步为通用调查，与原因脱节 |
| httpx | generic | generic | 轴 A 不成立：第一步仅检查工具是否可用/是否跑完，未具名 pinned pytest/tooling 与 Python 3.12 的兼容问题 | 未给出原因，第一步"确认工具可用并跑完"为通用检查 |
| python-ftfy | correct | correct | healthy 项目且 FixFirst 第一步为 (no must-fix step)，命中 healthy 的 correct 条件 | 健康项目，正确标记 (no must-fix step) |
| robotframework | correct | correct | 轴 A/B 均成立：具名 repository local module robot，并要求使其 importable，与标签 first_step/also_acceptable 语义一致 | 原因（本地模块/路径）与第一步（让 robot 可导入）均命中标签 |
| python-slugify | generic | generic | 轴 A 不成立：只要求比较 failed assertion 的 expected/actual，未具名 _modern_truncate 或 repeated-delimiter truncation 根因 | 未识别 _modern_truncate（未达 partial_if 的识别要求），第一步"比较断言期望值与实际值"为通用诊断 |
| django-cacheops **differs** | generic | partial | 轴 A 不成立：仅给 Missing configuration 类别且第一步是手动查看输出，未具名 DJANGO_SETTINGS_MODULE=tests.settings / Django initialization；F01；hedged | 认出缺配置（hedged=yes，只说"可能"），但第一步未解决 Django 初始化问题，命中 partial_if |
| seleniumlibrary | correct | correct | 轴 A/B 均成立：具名 repository local module SeleniumLibrary，并要求使其 importable，与标签 first_step/also_acceptable 语义一致 | 原因（本地模块/路径）与第一步（让 SeleniumLibrary 可导入）均命中标签 |
| django-storages **differs** | generic | partial | 轴 A 不成立：仅给 Missing configuration 类别且第一步是检查异常，未具名 DJANGO_SETTINGS_MODULE=tests.settings；F01；hedged | 认出缺 Django 配置（hedged=yes，只说"可能"）但未指出 tests.settings，命中 partial_if |
| python-markdown | correct | correct | 轴 A/B 均成立：具名 PyYAML/yaml，并直接建议安装 pyyaml；标签 also_acceptable 明确允许直接安装 PyYAML | "Install pyyaml" 与标签 also_acceptable（直接安装 PyYAML）一致 |

## Reconciliation (第 5 步对齐记录)

Independent agreement was **9 / 12 (75%), Cohen's kappa 0.66**. Three rows differed —
`python-qrcode`, `django-cacheops`, `django-storages` — all with A scoring `generic` and C
scoring `partial`.

A interpreted a cause category alone ("Version incompatibility" / "Missing configuration")
as insufficient to satisfy Axis A, because the first step did not name the concrete
dependency, setting, module, function, or other specific cause. C initially treated the
correct cause category as sufficient for Axis A and therefore scored these rows partial.

The reviewers resolved the disagreement by applying the rubric's named-cause requirement
consistently with the already-agreed `python-slugify` case (its cause category matched the
label, but the first step did not name the specific defect, and both reviewers scored it
`generic`). The three rows were therefore reconciled to `generic`.

Basis in the rubric that was fixed **before** either reviewer filled a sheet
(`scoring-rubric.md`, committed 2026-10-02 15:38; C's sheet committed 17:03):

- §1 Axis A — a step is *not* named if it is "read the raw output and investigate by hand",
  "check this exception", or "check the dependency declarations";
- §2 — **generic outranks partial**: "no cause stated" is `generic`; partial requires the
  cause to be right and only the action lacking;
- §3 — **hedged + not named = generic**.

The independent scores are unchanged. `scores-A.csv` and `scores-C.csv` each keep their own
original calls, so 9/12, 75% and kappa = 0.66 remain the true independent-scoring result.
Only the agreed/final `scores.csv` records the consensus.

| Project | A (independent) | C (independent) | Agreed | Decision and reason |
|---|---|---|---|---|
| python-qrcode | generic | partial | **generic** | First step "Check the import path and dependency declarations" names neither the `%-d` strftime issue nor any concrete dependency; the only cause signal is the hedged category "Version incompatibility". Not named (rubric §1), hedged (rubric §3) → generic. |
| django-cacheops | generic | partial | **generic** | First step "Read the original output and investigate by hand" names nothing; cause is the hedged category "Missing configuration" only. Rubric §1 / §2 / §3 → generic. |
| django-storages | generic | partial | **generic** | First step "Inspect the exception raised while running the test" names nothing; cause is the hedged category "Missing configuration" only. Rubric §1 / §2 / §3 → generic. |

Final distribution (see `scores-summary.md`): correct 4 / partial 1 / generic 6 / wrong 1.
