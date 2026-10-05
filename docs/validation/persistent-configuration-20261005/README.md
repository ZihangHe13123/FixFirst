# 持久配置建议验收

本轮改的是产品建议：实际选择的 pytest 配置文件、段名、既有路径及 Django 插件需求。没有模型请求，不是三组实验或泛化结果。

## 真实修法

- 14 个已有配置文件的案例，照建议保存选项后，新 shell 原完整测试通过。
- 最初“无配置”的两个夹具实际选中了父目录配置，候选正确拒绝覆盖；发现这一点后，在独立目录补了两例，创建 pytest.ini 后通过。这两例单列为补充诊断性用例。
- 原冻结的已有路径案例通过；另外补测了项目目录及已有路径含空格，条目保留，测试文件没改。
- 缺插件时执行产品生成的有界安装命令并保存设置后通过；普通/可选测试组的版本冲突都不给矛盾命令，禁用 autoload 时先审查加载政策。
- 交叉验证：Python 3.10.20 / pytest 7.3.2 / Django 4.2.26；Python 3.13.14 / pytest 9.1.1 / Django 5.2.1；Python 3.14.6 / pytest 9.1.1 / Django 6.0.1，三个最小项目均照建议通过。验证了这些实例，不宣称所有组合或所有项目都验证过。

`FROZEN_CASES.json` 和生成器在实现前固定；`ACCEPTANCE.json` 单列原案例、父配置控制和补充案例。所有实际配置修复均保持原测试与受保护选测选项，不通过换测试目标宣布成功。

## 范围

明确支持 pytest 的 INI 和两种 TOML 写法。程序/unittest/notebook 目标仍需自己的入口或安装方式，不能套用 pytest 配置。旧记录、实际配置在项目外、版本/快照不完整、覆盖来源有冲突时保守审查。

插件版本是依据官方支持关系选出的固定候选，不是最早支持版本。安装规划保留已装 Django/pytest，并核对声明及反向依赖约束；没有把候选的可安装性当作项目已修好。

来源：[pytest 配置](https://docs.pytest.org/en/stable/reference/customize.html)、[pytest-django 配置](https://pytest-django.readthedocs.io/en/latest/configuring_django.html)、[插件兼容更新](https://pytest-django.readthedocs.io/en/latest/changelog.html)、[Django/Python 支持表](https://docs.djangoproject.com/en/6.0/faq/install/)。

## 初版门禁（显式检查顺序）

实现 `5117e56`，收据 `0a3e057`。本机 CPython 3.12.13 / macOS arm64：全套 1974 passed / 75 skipped，知识三文件 170 passed，Ruff/diff check 通过。跳过是未提供可选的独立 Django/pkg_resources 测试解释器、未启用场景生成，以及 Windows 专用项；本轮的配置修法另由上面的真实解释器案例验证。

owners 原验证器真实重生成：155/155 个键、23/23 个 merged 键通过，存档自审0问题，762秒。明细与原收据逐值一致，新增绑定 persistent_configuration.py 并更新改变的模块摘要；没有手工更改绑定摘要。

git archive 构建的 wheel 包含新模块，所有运行时文件逐字节相同；装进干净环境后仍给出相同持久步骤。内置81特征模型摘要仍为 `189f712ea75bcb117f96aae879fd0c9bdab9ee6531475d1a95faf01ec2738d30`。

## 独立验收后的默认入口修复

Claude 发现初版默认顺序在 pytest 后才读项目，规划的时序守卫因此拒绝所有持久写法。上面的初版真实修法用了显式顺序，不能证明默认 CLI/MCP 入口交付成功。

源码 `3321b550b09392ef0bb9e384180e166022fc4e94` 将默认顺序改为 environment、project、pip_check、pytest、ruff；显式选择保持原样，时序和旧快照守卫保留。另支持标准 `-ra -q` 汇总选项，pytest-django 试装也固定已装 Django/pytest；与这些版本不兼容时无安装候选。旧协议的试装缓存失效。

默认 service.scan 的24个实例（本地导入的运行/收集目标、Django运行目标、各配置格式与真正无配置）照实际打印的字面写法保存后，新进程完整测试24/24通过，测试文件未改。`DEFAULT_ACCEPTANCE.json` 是本次记录，`default_acceptance.py` 用已有夹具复现。Django夹具只在测试函数内访问配置，收集不触发该故障，故没有把收集目标算入Django修法。

仓库测试另走真实 CLI 默认 scan 与打印的 Check again、MCP stdio 的 diagnose/check_again，分别覆盖已有/无配置；两个入口的初次与再次检查都出现持久步骤。真实离线 resolver 在新 Django/pytest 可选时仍保留已装版本，并拒绝必须升级 Django 的候选。新增回归在修前失败16项，修后定向210 passed / 10 skipped；随后补了4个收集目标实例。

B3 当前结果读取封存显示字段。B7 修复判分读取完整测试、参考节点及完整性摘要，不读取首个问题；首因来自明确排序后的行动，排序包含行动id，不依赖问题的插入顺序。本次未改这些脚本或历史记录。新建pytest.ini仍会被现有B7判分拒绝，属于实验方案H5；正式冻结前需解决该差异，本PR未放宽保护规则。

`-r` 的字符范围依据 [pytest 输出说明](https://docs.pytest.org/en/stable/how-to/output.html#producing-a-detailed-summary-report) 和目标pytest的终端选项源码；未知字符和改变执行范围的选项仍不能证明等价。

### 验收补充：测试单独重跑的旧声明

最终源码 `ea03f56874686c8f6e4d3777ef8e4ffcf6b8d26a` 在pytest检查前补齐本批次缺少的环境、项目快照；默认批次已有快照，不重复。仍保留原测试目标/参数、先校验节点再执行。规划没有改为读取现场文件。

真实CLI：先默认扫描 `pytest-django>=4.5`，再把文件改为 `pytest-django<4`，仅运行 `--checks pytest_run`。修前仍给旧范围的安装命令；修后点名冲突、无安装命令，文件保持用户修改后的内容，测试未改。见 `STALE_DECLARATION_ACCEPTANCE.json`。本次新回归在修前失败，修后定向243 passed / 10 skipped；额外54项上下文兼容回归通过。

最终源码又重跑默认24例，24/24通过。重新从git archive构建、替换干净wheel安装后，78个运行时文件仍逐字节相同，默认CLI/MCP初次与再次检查通过；记录 `WHEEL_DEFAULT_SMOKE.json` 绑定最终源码。旧收据重生成曾因这项补充而中断，该次输出不作验收依据。

### 修复后的最终门禁

源码 `ea03f56`，收据提交 `31b0155`。macOS / CPython 3.12.13：完整测试1993 passed / 75 skipped，知识三文件170 passed，B7运行器107 passed，额外隔离Django的10项机制回归通过；Ruff与diff check通过。跳过项仍为没有在完整测试中提供的独立解释器、需主动启用的环境生成，以及Windows项。

owners原验证器重跑707秒：155/155键、23/23 merged键通过，自审0问题。与初版收据相比，results、merged、summary逐值一致，变化仅在tool段的代码绑定；没有手工改绑定摘要。模型摘要仍为189f712e…，没有启动LLM或读取新的留出数据。以上为产品回归，Claude的同批独立复验尚待完成。
