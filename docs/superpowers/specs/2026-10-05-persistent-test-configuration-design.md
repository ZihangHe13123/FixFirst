# 持久保存测试配置

## 已确认范围

用户批准继续：Codex 改产品，Claude 定实验并独立验收。本次覆盖 pytest 的本地导入 P12 和 Django P86，不改树、不启动 LLM、不选择正式任务、不读取新留出。程序/unittest/notebook 目标保留原有入口与打包提示，不能套用 pytest 文件。

## 方案取舍

仅补“export 不持久”仍需用户推断修法；按文件存在猜配置会写到没生效的地方。采用实际 pytest 启动记录：复用现有 pytest_config/config_file，补一份有界的持久配置快照，两个建议入口共用选择与格式化模块。

## 配置快照与选择

probe 在项目 conftest 执行前记录原配置的段名、语法、已有 pythonpath/DJANGO_SETTINGS_MODULE、文件安全性、pytest 版本、rootdir 和 Django 插件/覆盖状态。只读实际选中的文件，不重新搜优先级，不执行项目模块，不记录其它环境变量。限常规文件 128 KB、字段 16 KB、路径项50个；失败只使这份快照不完整，不能改变原检查结果。

规划只用当前已执行、完整的失败运行和同环境快照。实际配置必须在项目里、非链接且格式明确；原 addopts/PYTEST_ADDOPTS 只含显示选项。旧记录、重复/畸形快照、项目外配置、未知格式、已覆盖的设置保持审查。无配置且 rootdir 正好为项目根时，才建议创建 pytest.ini；不得新建高优先级文件覆盖已有有效配置。

支持 pytest.ini/.pytest.ini/tox.ini 的 [pytest]、setup.cfg 的 [tool:pytest]、pyproject 的两种段以及 pytest.toml/.pytest.toml 的 [pytest]。以实际段名为准，兼容原有空配置或空 pyproject 的明确新段。

## 两个建议入口

- P12：pytest>=7 且唯一导入根时，在选中的配置保存 pythonpath，按配置文件目录计算相对路径、保留已有条目和空格。既有设置已经包含根时不重复给无效修法。有真实打包入口时保留同解释器 editable 安装及元数据说明。
- P86：仅唯一无冲突的 settings 候选时保存 DJANGO_SETTINGS_MODULE。先说明 pytest-django 的需求；插件未加载/被禁用、--ds/环境覆盖或候选冲突时不把一行配置当成修复。
- 插件缺失时，提供有来源的固定候选，保留已装 Django/pytest 版本：4.11.1 用于 Django 4.2/5.0/5.1/5.2、Python<=3.13；4.14.0 用于 Django 6.0 和 Django5.2/Python3.14。Python/Django 的支持边界、pytest>=7且<10 均检查，非稳定/未来未知版本不猜。
- 候选不是“最早支持版本”，也不是项目已验证成功。安装命令经过已有项目/反向依赖约束处理；可选测试组的相关声明也保守保留。冲突时点名来源、不给矛盾命令，沿用依赖试解/协调审查。

行动句、具体文件/段/选项放在解释开头，只改该键、保留其它设置与测试。修复后用新 shell、相同解释器、原参数和完整节点复核，再 pip check。产品不自动改项目文件。

## 验收

实现前冻结合成产品用例与参考修改：各 INI/TOML、无配置、已有路径/空格、Django 已有/缺失插件、设置/应用初始化、禁用插件、约束冲突、多候选、项目外配置、旧记录、纯代码缺陷、非 pytest 目标。先跑参考修改确认新 shell 原命令通过，再按候选建议执行。保留所有测试与受保护选测设置的摘要。

补 collector/选择器/约束的边界探针；重放旧开发记录只检查回归，不当新收益。三个知识测试、完整测试、Ruff、owners 原验证器重生成后交草稿 PR；独立实验由 Claude 负责。

## 来源与自审

来源：[pytest 配置](https://docs.pytest.org/en/stable/reference/customize.html)、[pytest-django 配置](https://pytest-django.readthedocs.io/en/latest/configuring_django.html)、[4.11.1 元数据](https://pypi.org/pypi/pytest-django/4.11.1/json)、[更新记录](https://pytest-django.readthedocs.io/en/latest/changelog.html)、[Django/Python 支持](https://docs.djangoproject.com/en/5.2/faq/install/)。

所有写文件步骤均为建议；只有来源、原检查及依赖约束同时明确时给具体操作。无自动写入、无新的正式实验，模块身份与模型不因建议更具体而放宽。没有实现占位项。

## 独立验收后的默认入口修复

验收发现默认 pytest 批次在测试后才检查项目，与本方案的证据时序要求冲突。采用先 environment、project，再 pip_check、pytest、ruff 的默认顺序；显式指定顺序保持原样。相比放宽时序校验或额外重复检查，这样能让 CLI、Web、MCP 共用正确入口，同时继续拒绝测试后的项目记录及旧快照。

补默认 service.scan、CLI scan/打印的 Check again、MCP diagnose/check_again 的真实进程测试。B3 已封存记录保持原样；B7 修复判分按原完整测试及保护摘要，不依赖问题列表的首项，首因指标仍来自排序后的行动。

标准 -ra/-r a 只改变 pytest 汇总显示，接受官方列出的报告字符，未知字符和影响选测的选项继续保持未核对或不同。pytest-django 的依赖试装也固定当前已装 Django、pytest；项目声明冲突则拒绝候选，不能借试装升级这两个包。旧试装缓存用新的协议身份失效。补真实离线 resolver 对照，证明有新版可选时也保留已装版本、与固定版本不兼容的候选不产出安装命令。

持久导入建议提醒保留项目仍依赖的外部 PYTHONPATH 条目。没有配置时创建 pytest.ini 与 B7 保护规则冲突，属于实验方案 H5，正式冻结前另定；本次不放宽原判分或重写旧结果。

验收补充的发现6：仅重跑pytest时，早于失败的旧声明可能已经被用户修改。规划继续只读记录，不在规划阶段读取现场文件；scan在pytest/pytest_run前补齐本批次缺少的environment/project检查。默认批次已有这些前置检查，不重复；保留原测试目标与命令参数。节点校验仍在所有执行前完成，非法节点不触发这些检查。补声明改变后的真实入口回归，不沿用矛盾的旧安装范围。
