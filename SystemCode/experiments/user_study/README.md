# 用户研究的任务项目（任务 B8）

给 [C2 用户研究](../../docs/tasks/C2-user-study-sessions.md)用的 4 个故障项目，以及重建和判分用的脚本。研究方案见 [B13](../../docs/tasks/B13-user-study-design.md)。**这个文件夹里有答案，不要给参与者看。**

## 里面有什么

| 文件 | 做什么 |
|---|---|
| `tasks/` | 4 个任务项目的原始版本 |
| `prepare.py` | 把 4 个任务复制到一个新文件夹，每个都带好自己的 `.venv`；`--self-test` 顺便检查任务和判分是否正常 |
| `open_task.py` | 在当前任务目录打开干净终端，绑定该任务的 `.venv`；两种实验条件都使用 |
| `grade.py` | 给一个任务判分：打印 PASS 或 FAIL，以及原因 |
| `solutions.py` | 参考答案，自检时用 |

## 4 个任务

每组一个"版本问题"，一个"配置或路径问题"，两组难度相当。故障都和 FixFirst 样例项目里的 4 个不同。

| 组 | 任务 | 参与者看到的错误 | 原因 | FixFirst 的第一步（9/29 核对） | 参考修法 | 也算对的修法 |
|---|---|---|---|---|---|---|
| A | T1 `T1-report` | `cannot import name 'Markup' from 'jinja2'` | Jinja2 3.1 删掉了 `jinja2.Markup` | Replace jinja2.Markup: removed in jinja2 3.1（规则 D02） | 改成 `from markupsafe import Markup` | 装旧版 `pip install "jinja2<3.1"` |
| A | T2 `T2-inventory` | `No module named 'inventory'` | src 布局，项目没有安装（README 里写了 `pip install -e .`） | Make the project module inventory importable（D13） | `pip install -e .` | 在 `pyproject.toml` 里给 pytest 加 `pythonpath = ["src"]` |
| B | T3 `T3-versions` | `No module named 'distutils'` | Python 3.12 删掉了 `distutils` | Replace distutils: removed in Python 3.12（D01） | 改用 `packaging.version.Version`（环境里已有） | `pip install setuptools`（它会补回 `distutils`） |
| B | T4 `T4-booking` | `FileNotFoundError: ... settings.toml` | 没按 README 把示例配置复制成 `settings.toml` | Create or point to the configuration file settings.toml（D32） | 复制 `settings.example.toml` 为 `settings.toml` | 自己写一个内容相同的 `settings.toml` |

判分只看结果：测试文件没改、预期的测试全部通过就算 PASS，用哪种修法都行。

## 用法

需要 Python 3.12 或更新的版本（T3 依赖 Python 3.12 删掉的模块），第一次运行要联网下载包。下面的命令都在 FixFirst 主仓库里运行，任务副本放在 `C:\study`（macOS 上是 `~/study`）。

**准备电脑时先自检一次：**

```powershell
.venv\Scripts\python experiments\user_study\prepare.py C:\study --self-test
```

应该看到 4 行 `as expected`，最后一行是 `Self-test passed`。自检会用参考答案把任务改好，所以**自检之后、第一个参与者之前，要再重建一次**。

**每个参与者开始前，重建全部任务：**

```powershell
.venv\Scripts\python experiments\user_study\prepare.py C:\study
```

只重建一个任务，就加上 `--only T3`。

**每个任务开始前，由实验员打开任务终端（不计时）：**

在 FixFirst 主仓库的终端中运行，`T1` 换成当前任务编号：

```powershell
.venv\Scripts\python experiments\user_study\open_task.py C:\study T1
```

macOS / Linux：

```bash
.venv/bin/python experiments/user_study/open_task.py ~/study T1
```

脚本会打开一个子 shell：Windows 用不加载配置文件的 PowerShell，macOS / Linux 用不加载配置文件的 bash。
它已进入任务目录，`python`、`pip` 和 `pytest` 都来自该任务的 `.venv`，无需运行激活脚本。
它会清掉临时 Python、pytest、pip 和应用设置，只保留系统、语言、终端及网络所需的环境变量。
开始前用以下命令核对解释器；不要提前运行测试或展示报错：

```bash
python -c "import sys; print(sys.executable)"
```

路径应位于当前任务目录，例如 `C:\study\T1-report\.venv\Scripts\python.exe`。
两种条件都从这个终端开始，参与者运行 `python -m pytest`、`python -m pip …`。
有 FixFirst 的条件中，选择同一个任务目录，并确认 FixFirst 使用的解释器也是上面这个路径。
任务结束后输入 `exit`，下一题重新运行 `open_task.py`。判分在实验员的另一个终端里进行。

**判分**（参与者说"好了"的时候）：

```powershell
.venv\Scripts\python experiments\user_study\grade.py C:\study T1
```

- `PASS T1: 4 passed ...`：完成，记下用时；
- `FAIL T1: ...`：还没完成，冒号后面是原因，但不要告诉参与者。加 `--show` 可以看到 pytest 的完整输出。

macOS 上把 `.venv\Scripts\python` 换成 `.venv/bin/python`，路径换成 `~/study`。

## 判分规则

- 测试在任务自己的 `.venv` 里运行，与 `open_task.py` 打开的干净终端一致。临时 Python、pytest、pip 和应用变量不计入修复；例如 `PYTHONPATH`、`PYTEST_ADDOPTS` 不能使未修好的任务通过。项目文件和该任务环境内的包修改可以计入。
- `tests/` 里的文件和刚建好时不一样（改了、加了、删了），直接 FAIL。
- 预期的测试必须全部通过：T1、T3、T4 各 4 个，T2 5 个。有测试失败、报错、被跳过或数量不对，都判 FAIL。

## 给参与者的说明（每个任务开始时念）

> 这个项目的测试跑不通。请在准备好的任务终端里让 `python -m pytest` 全部通过。不要修改或删除 `tests/` 里的文件；项目代码可以改，包可以装或卸。修好的标准是：重新用同一任务环境打开干净终端，测试也能全部通过，临时设置的变量不算。觉得完成了就告诉我。

环境核对和 FixFirst 教学不计时。说明结束、实验员说“开始”并允许参与者操作时开始计时；判分通过时停止。

## 版本

这些材料包含在冻结版 v0.7.0 里。试用之后如果要改任务项目，只改这个文件夹，B 会打 v0.7.1，并在 B8 的 Issue 里告诉 C 用哪个标签。FixFirst 本身不变。
