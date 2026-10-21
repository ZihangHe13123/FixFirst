# B5 公开分支独立环境验证

2026-10-01，分支 `codex/release-0.7.0-public`。结论：完整 pytest 通过，归档 helper 的机械格式修复后，同一完整 Ruff 命令也通过。验证者没有修改源码、测试或复制 fixture，没有推送。

## 环境

在新公开分支 checkout 中新建独立 `.venv`，以批准的 Python 3.12.14 创建，通过官方 `https://pypi.org/simple` 使用 pip `--isolated` 安装 `-e .[dev,notebooks] uv`。未借用另一源码树的 editable 环境；`fixfirst.__file__` 和 `direct_url.json` 均确认指向本树。应用版本 **0.7.0**。

实际依赖：pytest 9.1.1、Ruff 0.16.9、uv 0.12.21、nbclient 0.11.0、nbformat 5.11.1、ipykernel 7.4.0、pydantic 2.13.5、scikit-learn 1.9.1、NumPy 2.5.3、pip 25.0.1。完整冻结列表、解释器路径及安装命令/原始输出保存在本地证据中。

## 测试和检查

- 完整命令 `python -m pytest -q -ra --junitxml ...`：**776 passed，1 skipped**，0 错误、0 失败，终端统计 173.82 秒，进程耗时 174.213 秒。
- 唯一跳过：`tests/test_windows_adaptation.py:265::test_powershell_exact_native_arguments`，理由 **Windows PowerShell quoting**。没有因 notebook、uv 或缺少 fixture 增加跳过。
- 首次原样运行 `ruff check src tests scripts experiments`：exit 1，13 项问题；完整原日志保留为 `ruff.log`。
- 首次 13 项分布为 `experiments/field_trial/round9/harness/ml_replay9.py` 3 项、`structure-check/failure_mix.py` 1 项、`structure-check/structure_check.py` 9 项；规则为 E401×4、F401×1、E731×4、E402×2、E702×2。没有 `src` 或 `tests` 报错。
- root 随后对这三个归档 helper 做机械格式修复，并保存 `docs/freeze/evidence/PUBLIC_HELPER_STYLE_RECEIPT.json`。验证者重新运行完全相同的 Ruff 命令，得到 **All checks passed!**；保存在 `ruff-final.log`。没有缩小 lint 范围、删测试或改断言。

修复仅涉及归档 helper，生产源码与测试摘要未变，按指示没有重跑 pytest。本次没有读取或补入未批准的 R8/R9/R10 数据；测试引用的开发 fixture 在新树中均存在，没有发生缺 fixture 失败。

## 字节完整性与版本绑定

验证开始、结束时，新树 **62** 个生产源码/模板/知识/模型文件均与旧树当前生产字节相同；全部 **37** 个测试文件在运行前后摘要一致。默认模型 SHA256 始终为：

`4479864358595024a121b57fdb49f66f6d184c096c5a243a11fb5f1efdfb41e3`

验证期间 root 继续处理公开分支的交付文件，HEAD 从起始 `8136da46396a9d7c532a741052a51d908c3a1991` 变为记录中的后续提交，因此本报告使用逐文件源码/测试摘要绑定本次执行；不把起始提交号冒充最终推送版本。提交状态及最终 lint 时 HEAD 见 `environment.json` / `validation-summary.json`。

本次是该公开分支新环境的 macOS 全量测试与 lint 记录，不代表 Windows 真人验收、正式模型实验或 CI 已执行。没有启动模型服务、付费或正式数据流程；推送和 CI 由根任务负责。

## 原始证据

- `setup-commands.json`、`setup-01.log`、`setup-02.log`：独立环境创建及官方索引安装。
- `environment.json`、`environment-freeze.txt`：版本、editable 来源及解释器。
- `initial-source-hashes.json`：62 个源文件、37 个测试和模型的开始摘要及跨树比较。
- `pytest-command.json`、`pytest.log`、`pytest-junit.xml`：完整测试精确命令、时间、退出码、全部原结果及实际跳过。
- `ruff-command.json`、`ruff.log`、`ruff-summary.json`：首次 13 项原始失败。
- `ruff-final-command.json`、`ruff-final.log`：root 格式修复后的同命令复验。
- `fixture-existence.json`：仅存在性核对，未读取或复制 fixture 内容。
- `validation-summary.json`：结果、跳过详情、源码/测试/模型未变以及格式修复收据摘要。

所有证据写在指定旧树的 workbench 目录；报告正文不包含本机绝对路径。
