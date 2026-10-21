# B5 新源码 ZIP 干净安装与入口验证

2026-10-01。固定源码 `4a7c470633bd087cc0bc3d899db190fb4bd07bba`。结论：新 ZIP 原样安装成功，指定入口检查通过；与先前 development 环境的共有依赖没有版本漂移。

## 包和独立安装

- ZIP：809988 字节、207 个文件，SHA256 `392736ba461d1979d110515400806a74ac985d3c74ebd0ad37783cd385b9baa4`。
- 使用 package-context 指定的新解压目录（含空格和中文）。安装前 `.venv`、`.git` 均不存在，207 个原文件与 ZIP 逐字节一致。
- 使用批准的 Python 3.12.14 执行原样 `bash scripts/setup.sh <approved-python>`，exit 0，8.049 秒。只在此安装进程设置 `PIP_CONFIG_FILE=/dev/null`、官方 `PIP_INDEX_URL=https://pypi.org/simple`，清除继承的其它 PIP 配置变量；没有更改全局配置。
- 应用模块和已安装发行版均为 **0.7.0**；editable 来源指向新解压项目自己的源码，新 `.venv` 没有借用 development 环境。
- 模型 SHA256 为 `4479864358595024a121b57fdb49f66f6d184c096c5a243a11fb5f1efdfb41e3`。

与此前 `.[dev,notebooks] + uv` 完整回归环境比较，**26 个共有包版本全部一致**。此次原安装脚本安装 `.[dev]`，没有安装 notebook/uv 及其可选依赖，属于预期安装范围差异；没有发现需要进一步风险判断的共有包版本变化。完整包版本在 `environment.json` / `environment-freeze.txt`，逐项差异在 `dependency-comparison.json`。

## 指定入口检查

用新包自身的 Python 执行包内 `docs/freeze/validation-20261001/check_install.py`，指定此项目与全新 entries 输出目录，exit 0，20.852 秒。helper SHA256 为 `5e3c87de79ddbe3a3ab203f2727af18aa6506dd698d743876dd2c8074a0cc8d8`。

- CLI 帮助、创建/列出/查看会话均成功。
- 既有 playground 示例按原 `FIXES.md` 操作，从 blocked 变为 achieved；最终实际 pytest 退出 0、verified_pass=true、4 passed。独立重新计算的 4 个原测试摘要均与包内样例模板一致。
- 无测试 hello 脚本入口实际执行成功，保存参数并记录 `entry-ok`，目标 achieved。
- 生成本地报告并导出 HTML 与 JSON；helper 的导出脱敏断言通过。
- 本地 Web 服务实际启动、停止、再次启动；两次启动各访问主页、会话页、详情和导出，共 **8 次 HTTP 200**。
- 从同一 store 重开原会话，仍为 achieved。

这些是源码安装和既有入口检查。示例使用已文档化参考修改，不能计为新增诊断/模型收益或产品自主修复。没有使用外部用户项目。

## 完整性和限制

安装及入口检查结束后，ZIP 内 **207 个原文件全部保持原字节**，包含生产源码、测试、helper 和模型。新增环境、会话、导出与样例运行材料不属于原包文件。

本次没有重复 776 项开发回归，没有训练、模型服务、付费、正式评估、推送或源码修改。没有宣称浏览器视觉检查、Windows 真人验收或 notebook 可选安装已完成；helper 明确将这些项记录为 false。

精确安装/入口命令、进程环境、起止时间与原始输出见 `install-command.json` / `install.log`、`entry-command.json` / `entry-check.log`；安装前全文件摘要见 `package-before-install.json`。入口逐步原日志和原始收据位于相邻 `../entries/`；机器汇总为 `package-validation-summary.json`。本报告与此前 development 环境的 pytest/Ruff 验证分开保存。
