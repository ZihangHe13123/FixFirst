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

## 最终门禁

实现 `5117e56`，收据 `0a3e057`。本机 CPython 3.12.13 / macOS arm64：全套 1974 passed / 75 skipped，知识三文件 170 passed，Ruff/diff check 通过。跳过是未提供可选的独立 Django/pkg_resources 测试解释器、未启用场景生成，以及 Windows 专用项；本轮的配置修法另由上面的真实解释器案例验证。

owners 原验证器真实重生成：155/155 个键、23/23 个 merged 键通过，存档自审0问题，762秒。明细与原收据逐值一致，新增绑定 persistent_configuration.py 并更新改变的模块摘要；没有手工更改绑定摘要。

git archive 构建的 wheel 包含新模块，所有运行时文件逐字节相同；装进干净环境后仍给出相同持久步骤。内置81特征模型摘要仍为 `189f712ea75bcb117f96aae879fd0c9bdab9ee6531475d1a95faf01ec2738d30`。
