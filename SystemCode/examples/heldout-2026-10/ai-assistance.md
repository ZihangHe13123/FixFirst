# AI 辅助排查记录（A1）

只记录 A1/C1 的辅助排查；不把具体项目、报错或对话发给 B 及其开发助手。
C 提交独立初判前，不打开 A 的记录和 AI 回答。

**披露结论（A1 定稿）：评测是人工的——所有标签判断栏由 A 本人逐行写定；AI 只用于"为什么报错"的排查线索，从未产出任何标签栏目的结论。**
具体分工：`root_cause`、`first_step`、`also_acceptable`、`partial_if`、`wrong_if` 五个判断栏由 A1 本人逐行写定；
AI 的输出只用于「为什么报错」这一步的排查，且每一条都被要求给出可打开核对的一手来源，采纳或拒绝均由人决定。
每条线索都经人工打开来源核对、并在 twin 副本里实际验证之后，才可能进入标签（逐案例记录见下文）。
`pytest_shows`、`checked_by_trying`、`later_layers` 是运行记录（`pytest/`、`twins/` 的原始输出），不是判断栏。
C 的独立初判全程人工、未用 AI；定稿环节的核对与措辞合并也由 C 本人完成。

## 使用概况

- A：使用过。这一批用的是两个助手，分别披露：
  - 主会话助手：模型 **GPT-5.6 Sol**（A 确认）
  - 后台执行 agent（跑候选扫描、建环境、跑 `pytest` 和 twin 的子 agent）：模型 **未知**——它的界面没有明确显示模型版本，按模板要求记未知，没有根据名称、运行速度或其他迹象推断
- C：独立初判阶段未使用 AI、未打开 A 的记录；提交初判（`b34263a`）后，用本机终端 AI 助手会话（可见模型标识 deepseek-v4-pro，以客户端实际显示为准）执行 `heldout.py agree`/`check`、生成 `review.md` 的 Decisions 节与最终 `labels.csv`——均为脚本运行与文件生成，未让 AI 诊断案例；定稿判断（措辞合并、层次确认）由 C 本人作出
- 是否曾使用正式基线计划中的同一模型：没有（held-out 的这批项目没有用 FixFirst 基线计划里的同一个模型跑过初判）

## 每个用过 AI 的案例、每位使用人一条

以下 12 条是同一种用法，逐条记的是该案例里 AI 提过什么、哪些被采纳、哪些被否决。
「人工核查来源」栏写的文件/提交都由 A 本人打开核对过，`projects.toml` 的 `scenario`/`layout` 里有对应行号。

### click

- 使用人、日期、阶段：A 排查，2026-09-29 ~ 2026-09-30
- 助手及可见的模型版本：主会话助手 GPT-5.6 Sol；后台执行 agent 未知（界面未明确显示模型版本）
- 用途、询问了什么：`AttributeError: __spec__` 为什么让 pytest 起不来；是 pytest 版本还是别的依赖
- AI 提出的候选原因或修法；采纳/拒绝哪些：AI 先答「升级 pytest 到兼容 3.12 的版本」→ **拒绝**，对照实验 A（只换 pytest 9.1.1）同一个 `AttributeError: __spec__` 原样复现；改答「pinned `py==1.10.0` 在 3.12 下不可 import」→ **采纳**（对照实验 B/C 验证）
- 人工实际打开核对的文档或源码链接（含适用版本）：pallets/click 8.0.3 的 `requirements/tests.txt`（`py` 的 pin）、`setup.py`、`tox.ini`；`py` 1.10.0 与 1.11.0 的源码差异
- 副本验证记录位置：`twins/click.txt`、`twins/click.raw*.txt`；结论在 `labels-A.csv` 的 `checked_by_trying`
- 本地保存的对话位置：`%USERPROFILE%\.claude\projects\<会话目录>\7bb2b1bf-4e8c-40c5-9f5e-a9ceac94c915.jsonl`（A 本机）

### pytest

- 使用人、日期、阶段：A 排查，2026-09-29 ~ 2026-09-30
- 助手及可见的模型版本：主会话助手 GPT-5.6 Sol；后台执行 agent 未知（界面未明确显示模型版本）
- 用途、询问了什么：conftest 收集期的 `ast.Str` DeprecationWarning 被 `filterwarnings = error` 升级成错误，是项目缺陷还是解释器版本问题
- 采纳/拒绝：AI 给的「换成 Python 3.10」→ 采纳，并在 3.10.21 上实跑验证（2849 passed）；AI 一度把 `pkg_resources` 缺失当成第二层缺陷 → **拒绝**，那是 uv 建的 venv 没有 setuptools 的环境产物，只写进 `later_layers`
- 人工核查来源：pytest-dev/pytest 6.2.5 的 `pyproject.toml`（`filterwarnings`）、`src/_pytest/assertion/rewrite.py:823`
- 验证记录位置：`twins/pytest.txt`、`twins/pytest.raw.txt`

### dateparser

- 使用人、日期、阶段：A 排查，2026-09-30
- 助手及可见的模型版本：主会话助手 GPT-5.6 Sol；后台执行 agent 未知（界面未明确显示模型版本）
- 用途、询问了什么：3 个收集错误全是 `No module named 'fasttext'`，fasttext 是漏声明还是要装而装不上
- 采纳/拒绝：AI 结论「项目声明过 fasttext，缺的是装不上」→ 采纳；AI 原先写的 twin「failed」→ **拒绝**，改为 twin 记录里的 "Twin verification: unresolved / intervention unavailable in the current environment"（两者含义不同）；`partial_if` 也按 A 的意见放松（只答「缺 fasttext，先装 fasttext」给 partial，不判 wrong）
- 人工核查来源：scrapinghub/dateparser v1.1.0 的 `setup.py`（`extras_require={'fasttext': ['fasttext']}`）、`tests/requirements.txt`、`tox.ini`、`pytest.ini`（`--doctest-modules`）；本机安装失败信息 `Microsoft Visual C++ 14.0 or greater is required`
- 验证记录位置：`twins/dateparser.txt`、`twins/dateparser.raw.txt`（原始与 twin 输出一致，环境里没有快轮）

### python-qrcode

- 使用人、日期、阶段：A 排查，2026-09-30
- 助手及可见的模型版本：主会话助手 GPT-5.6 Sol；后台执行 agent 未知（界面未明确显示模型版本）
- 用途、询问了什么：`ValueError: Invalid format string` 出在哪、第一层到底是哪一个失败
- 采纳/拒绝：AI 第一版把 first step 只写在 `qrcode/release.py:34` → **拒绝**，只改这一处后同一个 `ValueError` 从 `tests/test_release.py:37` 照样抛出，说明这一层有两个位置，first_step 要覆盖两处；AI 把 `pkg_resources` 当第二层缺陷 → **拒绝**，改标为环境产物（uv venv 无 setuptools）
- 人工核查来源：lincolnloop/python-qrcode v7.3.1 的 `qrcode/release.py:34`、`tests/test_release.py:37,39`、`qrcode/console_scripts.py:36`、`tox.ini`
- 验证记录位置：`twins/python-qrcode.txt`、`twins/python-qrcode.raw*.txt`

### httpx

- 使用人、日期、阶段：A 排查，2026-09-30
- 助手及可见的模型版本：主会话助手 GPT-5.6 Sol；后台执行 agent 未知（界面未明确显示模型版本）
- 用途、询问了什么：`tests/conftest.py` 收集失败是不是 httpx 自己的问题
- 采纳/拒绝：AI 的「先升级 pinned pytest 6.2.4」→ 采纳（twin 里 `ast.Str` 归零）；AI 顺带提出的「httpx 用 `cgi` 也要一起改」→ **拒绝**，那是升级后才露出的下一层，写进 `later_layers` 不进 first_step
- 人工核查来源：encode/httpx 0.21.1 的 `requirements.txt:29`（pytest pin）、`setup.cfg:19-21`（`filterwarnings = error`）、`httpx/_models.py:1`
- 验证记录位置：`twins/httpx.txt`、`twins/httpx.raw.txt`

### python-ftfy

- 使用人、日期、阶段：A 排查，2026-09-30
- 助手及可见的模型版本：主会话助手 GPT-5.6 Sol；后台执行 agent 未知（界面未明确显示模型版本）
- 用途、询问了什么：318 passed / exit 0 是不是真的没有第一层失败
- 采纳/拒绝：AI 提过「顺手清理一下废弃 API」之类的无关建议 → **拒绝**，healthy 案例的 first_step 就是「不需要动作」；无因果 twin（没有失败可移除）
- 人工核查来源：rspeer/python-ftfy v6.0.3 的 `pytest.ini`（`--doctest-modules`）、`tox.ini`
- 验证记录位置：`pytest/python-ftfy.txt`、`environments/python-ftfy.txt`、`twins/python-ftfy.txt`

### robotframework

- 使用人、日期、阶段：A 排查，2026-09-30
- 助手及可见的模型版本：主会话助手 GPT-5.6 Sol；后台执行 agent 未知（界面未明确显示模型版本）
- 用途、询问了什么：98 个 `No module named 'robot'` 是缺依赖还是路径问题
- 采纳/拒绝：AI 的「项目文档让用 `utest/requirements.txt` + PYTHONPATH，`src/` 没进路径」→ 采纳，用只插 `src/` 的 `conftest.py` 做 twin 验证；AI 一度把 `resources`/`classes` 和 GBK 报错一起算进第一层 → **拒绝**，那是 runner 另外两条路径和本机 cp936 控制台代码页，进 `later_layers`
- 人工核查来源：robotframework/robotframework v4.1.3 的 `utest/README.rst`、`utest/run.py:28-33`、`utest/utils/test_encoding.py:9`
- 验证记录位置：`twins/robotframework.txt`、`twins/robotframework.raw.txt`

### python-slugify

- 使用人、日期、阶段：A 排查，2026-09-30
- 助手及可见的模型版本：主会话助手 GPT-5.6 Sol；后台执行 agent 未知（界面未明确显示模型版本）
- 用途、询问了什么：上游修复提交 8f9a550 之前的状态里，失败到底是改动预期还是代码缺陷
- 采纳/拒绝：采纳「父提交 c442cd4 的 `slugify/slugify.py` 里 `_modern_truncate` 是真缺陷」；AI 给的标签措辞「hard cut 后留下一个 delimiter」采纳为 first_step，用它跑 twin（只换入修复提交的 `slugify.py`，125 passed）
- 人工核查来源：un33k/python-slugify 的修复提交 8f9a550（PR #200）及父提交 `c442cd4cb61763c85b078d6ea83b5959c3ff364a`，`git rev-parse` 亲自核过
- 验证记录位置：`twins/python-slugify.txt`、`twins/python-slugify.raw.txt`

### django-cacheops

- 使用人、日期、阶段：A 排查，2026-09-30
- 助手及可见的模型版本：主会话助手 GPT-5.6 Sol；后台执行 agent 未知（界面未明确显示模型版本）
- 用途、询问了什么：`ImproperlyConfigured` 是配置缺失还是别的
- 采纳/拒绝：AI 先给一步（设 `DJANGO_SETTINGS_MODULE`）→ 只算半个，twin 第一步跑出 `AppRegistryNotReady`；A 据此把 first_step 升级成**两步**（`DJANGO_SETTINGS_MODULE=tests.settings` 加 `django.setup()`）；AI 把后面的建表/Redis 失败列作后续层 → 采纳，`partial_if` 明确写「只设变量」给 partial
- 人工核查来源：Suor/django-cacheops 6.0 的 `run_tests.py:3,20`、`manage.py:6`、`tox.ini`、`tests/settings.py`
- 验证记录位置：`twins/django-cacheops.txt`、`twins/django-cacheops.raw*.txt`

### seleniumlibrary

- 使用人、日期、阶段：A 排查，2026-09-30
- 助手及可见的模型版本：主会话助手 GPT-5.6 Sol；后台执行 agent 未知（界面未明确显示模型版本）
- 用途、询问了什么：这一类的第二个自然案例（`local_module`）；以及「上游什么时候把这个路径问题掩盖掉」
- 采纳/拒绝：AI 用 GitHub API 逐 tag 核过 v6.3.0/v6.4.0/v6.5.0/v6.6.0/v6.7.0 的 `pyproject.toml`（v6.5.0 起才有 `pythonpath = ["src"]`）→ 采纳为版本结论的一手证据；AI 建议的 id 写成 `django-storages-cm` 那类带类别缩写的命名 → **拒绝**（id 会泄题），全部改用仓库名
- 人工核查来源：robotframework/SeleniumLibrary v6.3.0 的 `utest/README.rst`、`utest/run.py:13,20`、`requirements-dev.txt`、各 tag 的 `pyproject.toml`
- 验证记录位置：`twins/seleniumlibrary.txt`、`twins/seleniumlibrary.raw.txt`、`pytest/seleniumlibrary.txt`

### django-storages

- 使用人、日期、阶段：A 排查，2026-09-30
- 助手及可见的模型版本：主会话助手 GPT-5.6 Sol；后台执行 agent 未知（界面未明确显示模型版本）
- 用途、询问了什么：`config_missing` 的第二个自然案例，配置到底写在哪
- 采纳/拒绝：AI 找出「`DJANGO_SETTINGS_MODULE` 只出现在 `tox.ini:14` 的 `setenv`，仓库根和 `tests/` 下都没有 `conftest.py`」→ 采纳；并用 `DJANGO_SETTINGS_MODULE=tests.settings` 一个环境变量做 twin（`ImproperlyConfigured` 归零）
- 人工核查来源：jschneier/django-storages 1.14.6 的 `tox.ini:14,20,50`、`tests/settings.py`；仓库根和 `tests/` 下无 conftest 用 GitHub contents API 按 ref 核过
- 验证记录位置：`twins/django-storages.txt`、`twins/django-storages.raw.txt`

### python-markdown

- 使用人、日期、阶段：A 排查，2026-09-30
- 助手及可见的模型版本：主会话助手 GPT-5.6 Sol；后台执行 agent 未知（界面未明确显示模型版本）
- 用途、询问了什么：找第 12 个自然 `missing_dependency` 候选（这一类的第 2 个）。**候选发现本身是 AI 做的**：后台执行 agent 用 GitHub API 批量扫了约 170 个仓库，判据是「测试套件顶层 import 的第三方包，不在任何 requirements 类文件里」，并把「只在 setup.py/setup.cfg/pyproject.toml 的 extras 里」单独分出来
- AI 提出的候选原因或修法；采纳/拒绝哪些：agent 提出 Python-Markdown 3.4.3 → **采纳**。它还一度自我否决（认为 twin 之后仍剩 1 个 collection error 就该淘汰）→ **否决它的自我否决**：按 twin 标准，干预后出现一个明确不同的下一层失败不算 twin 失败。它扫出的其他 HIT 全部 **拒绝**：webargs 的 werkzeug 和 flask-sqlalchemy 的 werkzeug（Flask 传递依赖）、flask-restx 的 faker（只在 benchmarks/）、jsonpickle 的 pytz（requirements-dev.txt 经 pandas 带上）、html5lib 的 pkg_resources（环境自带 setuptools，且 1.1 是 2020 年、在年份窗口外）、soupsieve/webargs/cattrs 等（extras 与文档的 tox 路径都会装）；另外淘汰了 omegaconf（文档安装本身在 Win/3.12 就坏掉）
- 人工实际打开核对的文档或源码链接（含适用版本）：Python-Markdown/markdown **3.4.3** 的 `docs/contributing.md:283`（`pip install --editable .`）与 `:298`（`python -m unittest discover tests`）、`tests/test_apis.py:34`（顶层 `import yaml`）、`pyproject.toml`（`dependencies` 带 `python_version<'3.10'` 条件，`[project.optional-dependencies] testing = ['coverage','pyyaml']`）、`tox.ini` 的 `[testenv]`（`extras = testing`，`commands` 用 unittest）；以及 **3.4.4** 的 `docs/contributing.md:360`（`pip install -e .[testing]`），证明上游是 3.4.4 才补上这一步
- 副本验证记录位置：`pytest/python-markdown.txt`（原始 `--repeat 2`）、`twins/python-markdown.txt`、`twins/python-markdown.raw.txt`（twin）、`twins/python-markdown.docpath.txt`（项目自己文档里的 unittest 命令在同一环境下的原始输出）；结论在 `labels-A.csv` 的 `checked_by_trying`
- 本地保存的对话位置：同一 jsonl；后台执行 agent 自身的输出另存在 `%TEMP%\claude\...\tasks\ae85f1a517bf7eeef.output`

## 开发侧暴露记录（如有）

无。（待 A 最终确认：没有把 held-out 的项目名、报错或 AI 对话发给 B 及其开发助手；公开 Issue 里的提交号留言不含项目名。）

## 报告披露摘要（C1 定稿时填写）

- 正式案例总数 N；其中经 AI 辅助排查的案例数、涉及的模型：N = 12；A 侧 12 个案例均经 AI 辅助排查（主会话助手 GPT-5.6 Sol；后台执行 agent 模型未知）；C 侧初判 0 个，定稿阶段仅用 AI 助手执行脚本与生成文件，未用 AI 诊断案例
- C 能在未看 A/AI 结论时独立给出初判的案例数 m：m = 12
- 一致率/kappa 比较的是哪两份初始记录、共同案例数 m/N：`labels-A.csv` 与 `labels-C.csv` 两份初始记录；m/N = 12/12；根因一致 12/12（100%），Cohen's kappa = 1.00
- 后续共同裁决或补充查证的案例数及依据：12 个项目的 `first_step`/`also_acceptable` 措辞经 A/C 会议合并（见 `review.md` Decisions）；其中 click、python-qrcode、python-markdown 3 项明确了层次关系；依据为原始 pytest 输出与 environments 记录，未重新搭环境

`heldout.py check` 不自动核验本记录；由 A、C 按卡片检查。A2 发布结果时公开脱敏的辅助方式、数量、来源和验证摘要；原始聊天无需整份公开。
