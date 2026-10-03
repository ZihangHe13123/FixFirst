# B3 真实项目匿名评分：A/C 分歧对齐记录（2026-10-03）

状态：**A、C 独立评分均已交回；两条分歧行已按 C 的判法更新共识表草案并附证据，待 A 确认后转正为 A+C。**
独立原表不覆盖：A 的三张表（署名 yongjun）与 C 的三张表（署名 WEI YI）均随本分支
`b3-scoring-aligned-20261003` 提交（基于 PR #61 head `e722cd54`；A 的交付说明见
`RETURNED-A.md`，C 的见 `RETURNED-C.md`）。

## 1. 一致率（只算 31 条有实际回答的行）

- 内容评分一致：**29 / 31 = 93.5%**；Cohen's kappa = **0.90**（heldout.py 同一公式）。
- 5 条 `service_no_answer`：A、C 双方均留空分、填评分人、notes 写确认语，逐条核对通过；
  **单独核对，不计入一致率，也不是 5 次评分一致**。36 次请求的总分母不变。
- 分布对比：

| 评分者 | correct | partial | generic | wrong | 缺答（留空） |
|---|---|---|---|---|---|
| A | 12 | 9 | 0 | 10 | 5 |
| C | 11 | 8 | 1 | 11 | 5 |

差异全部来自下面 2 条分歧行（一处 partial/generic，一处 correct/wrong），无系统性口径漂移。

## 2. 逐匿名模型对照

### model-1（12 行：10 有回答 + 2 缺答）——10/10 一致

| 项目 | A | C | 结果 |
|---|---|---|---|
| click | wrong | wrong | 一致 |
| pytest | correct | correct | 一致（双方 notes 均保留 also_acceptable vs wrong_if 的读法说明） |
| dateparser | partial | partial | 一致 |
| python-qrcode | wrong | wrong | 一致 |
| httpx | partial | partial | 一致 |
| python-ftfy | correct | correct | 一致 |
| robotframework | 空（缺答） | 空（缺答） | 缺答确认一致 |
| python-slugify | correct | correct | 一致 |
| django-cacheops | partial | partial | 一致 |
| seleniumlibrary | correct | correct | 一致 |
| django-storages | 空（缺答） | 空（缺答） | 缺答确认一致 |
| python-markdown | correct | correct | 一致 |

### model-2（12 行：10 有回答 + 2 缺答）——9/10 一致，1 分歧

| 项目 | A | C | 结果 |
|---|---|---|---|
| click | wrong | wrong | 一致（双方 notes 均记录“或可读为 generic”，一致按类别错落 wrong_if → wrong） |
| pytest | wrong | wrong | 一致 |
| dateparser | partial | partial | 一致 |
| python-qrcode | wrong | wrong | 一致 |
| httpx | wrong | wrong | 一致 |
| python-ftfy | wrong | wrong | 一致 |
| robotframework | wrong | wrong | 一致 |
| python-slugify | **partial** | **generic** | **分歧 ①，见 §3** |
| django-cacheops | partial | partial | 一致 |
| seleniumlibrary | wrong | wrong | 一致 |
| django-storages | 空（缺答） | 空（缺答） | 缺答确认一致 |
| python-markdown | 空（缺答） | 空（缺答） | 缺答确认一致 |

### model-3（12 行：11 有回答 + 1 缺答）——10/11 一致，1 分歧

| 项目 | A | C | 结果 |
|---|---|---|---|
| click | correct | correct | 一致 |
| pytest | **correct** | **wrong** | **分歧 ②，见 §3** |
| dateparser | partial | partial | 一致 |
| python-qrcode | partial | partial | 一致 |
| httpx | correct | correct | 一致 |
| python-ftfy | wrong | wrong | 一致 |
| robotframework | correct | correct | 一致（双方 notes 均记录类别标 missing_dependency 与标签 local_module 不符、第一步按 also_acceptable 判 correct） |
| python-slugify | correct | correct | 一致 |
| django-cacheops | partial | partial | 一致 |
| seleniumlibrary | correct | correct | 一致 |
| django-storages | 空（缺答） | 空（缺答） | 缺答确认一致 |
| python-markdown | correct | correct | 一致 |

## 3. 两条分歧行

### 分歧 ① model-2 / python-slugify：A=partial，C=generic

回答：`Investigate the slugify function logic in slugify/slugify.py, specifically how it
handles post-replacement truncation and word boundaries.`

- **A（partial）**：认出 post-replacement 截断/词边界处理（轴 A 具名），但只建议“调查”、
  未给出能满足回归用例的修复（partial_if）。A 自留：若“调查”视为通用动作则落 generic。
- **C（generic）**：未说出原因（trailing delimiter 未具名）、无修复动作；partial_if 要求
  “提出不完整修复”故不适用；按 rubric §2 顺序 generic 优先于 partial。
- **取法**：共识表已按 C 的 **generic** 定稿草案（依据：未说出原因且无修复动作，partial_if 要求
  “提出不完整修复”故不适用；rubric §2“generic 优先于 partial——没说出原因就是 generic”；
  A2 对齐先例 qrcode/cacheops/django-storages 同口径“第一步动作不具名 → generic”）。
  A 的 partial（认出 post-replacement 截断处理但只建议调查）记录在案，待 A 确认。

### 分歧 ② model-3 / pytest：A=correct，C=wrong

回答：`Update the project code in testing/conftest.py (and any other files using ast.Str)
to use ast.Constant instead, as ast.Str is deprecated in Python 3.12 and will be removed
in 3.14, causing the test suite to fail when warnings are treated as errors.`

- **A（correct）**：按“更新 pytest 代码中 ast.Str → ast.Constant、使其 AST 处理兼容 3.12”
  读为 also_acceptable；类别与标签一致。A 自留：答点位 testing/conftest.py（测试代码），
  若按 wrong_if“proposes project-code changes for the initial collection failure”读则为 wrong。
  A 在 RETURNED-A 里把本行标为“本表最需与 C 对齐的一行”。
- **C（wrong）**：答句主目标是项目测试代码 testing/conftest.py；标签证据是 ast.Str 在安装的
  6.2.5 栈自身 `src/_pytest/assertion/rewrite.py:823`（重写 conftest 时发出 DeprecationWarning），
  conftest 自身不含 ast.Str，改它照做不消层；wrong_if 明文命中，rubric 顺序 wrong_if 优先。
  （源码直查复核：pytest 6.2.5 的 `testing/conftest.py` 无任何 ast 引用；`ast.Str` 全部在
  `src/_pytest/assertion/rewrite.py`，其中 823 行 `keys = [ast.Str(key) ...]` 与标签记录一致。）
- **取法**：共识表已按 C 的 **wrong** 定稿草案（依据：源码直查 pytest 6.2.5——`testing/conftest.py`
  无任何 ast 引用，ast.Str 全在 `src/_pytest/assertion/rewrite.py`，其中 823 行与标签记录一致；
  答句点名改 conftest 照做不消层；wrong_if 明文“proposes project-code changes for the initial
  collection failure”，rubric 顺序 wrong_if 优先）。A 的 correct（把“any other files using ast.Str”
  兜底句读为有效路径，会落到 rewrite.py:823）记录在案，待 A 确认；与 model-1 同项目行
  （双方判 correct，点的是 assertion rewriting code = 栈机制）口径不冲突。

## 4. 共识表（草案）

`scores-consensus-model-{1,2,3}.csv`（各 12 行，UTF-8 BOM，与原始表同构）：

- 29 行一致 → 取一致值，`scored_by = A+C`，notes 记录一致理由；
- 分歧 ① → 按 C 的 generic 定稿草案，`scored_by` 标“WEI YI（草案，待 A 确认）”，notes 写双方立场与依据；
- 分歧 ② → 按 C 的 wrong 定稿草案（同上标注），notes 写双方立场与源码证据；
- 5 条缺答 → 留空分，`scored_by = A+C`，notes 写双方确认语。

按本草案的共识分布（31 条有回答）：correct 11 / partial 8 / generic 1 / wrong 11；
A 确认两条分歧后即为最终值。

原独立评分表（A 的 `model-*-A.csv` 与 C 的 `model-*-C.csv`）一律不动，最终共识表另存。

## 5. 署名与披露（分别沿用 RETURNED-A.md / RETURNED-C.md 的口径）

- A 侧：评分由 AI（Claude Code）按事先固定的 `scoring-rubric.md` 逐行起草，A 逐行复核后署名 yongjun。
- C 侧：评分按事先固定的 `scoring-rubric.md` 逐行起草，C 逐行复核后署名（WEI YI）；
  C 在未见 A 分数的情况下独立完成。
- 报告方法部分须披露 AI 用途与人工核实方式；AI 未参与标签制定、未接触模型身份映射、
  未改动任何冻结标签或 FixFirst 结果。
- 破盲检查：两表均无模型自报身份，原文未改；三模型的文风差异（model-1/2 简短命令式、
  model-3 详细带版本边界）已记录，A、C 均未据此推断真实身份。

## 6. 下一步

1. 双方原表、共识表与本文档已随分支 `b3-scoring-aligned-20261003` 提交，由 B 接收保存；
2. A 确认分歧 ①② 两行草案（或提出异议）后，共识表转正为 A+C；
3. 转正后另存最终共识表与定稿说明，不覆盖本底稿和双方原表；
4. 报告口径：36 次请求总分母；服务可用率单列（5 缺答计为未取得正确建议，不写作建议方向错误）；
   第一步内容质量分母 = 31 条有实际回答；内容一致率 29/31（kappa 0.90）不含缺答行。
