# Windows adaptation

The Windows audit on 2026-09-24 found that the original release was not yet a
reliable Windows application. The requested outcome is a working local Windows
installation, including checking projects, copying repair commands, checking
again, saving sessions, and exporting reports.

Implementation decisions:

- Windows copyable commands target PowerShell, with explicit UI labels.
- Keep project interpreters independent of the application's virtual environment.
  Do not overwrite an existing environment with a different Python ABI.
- Decode BOM-marked PowerShell logs and requirements correctly. Keep JSON valid
  on legacy code pages and preserve the tested project's subprocess encoding.
- Own check subprocess trees from launch until completion. Windows uses a job
  object assigned before a suspended child starts; closing the owner kills the
  tree. Web shutdown cancels the scope and refuses subsequent launches.
- Retry transient Windows file sharing conflicts without weakening atomic saves.
- Redact Windows path spellings and path-derived identifiers consistently.
- Preserve POSIX quoting and process groups. Do not change system settings or
  install packages globally.

## 已完成（2026-09-24）

Windows 适配已进入本项目源码，原 Windows 开发机已用 `scripts/setup.ps1`
完成安装验证。组员测试包不含 `.venv`，请先运行安装脚本，再双击
`start-fixfirst.bat`；复制的修复命令应在 PowerShell 中执行。安装不修改全局
Python 或系统编码设置。组员测试包在 `RELEASE_INFO.txt` 里写明基础提交和修订号；r1 至 r4 的修复已在 v0.6.1 合入仓库。

- 修复 Windows 会话删除时的锁文件占用，以及保存/读取的短暂共享冲突。
- 修复中文、空格、单引号路径与依赖版本比较符的 PowerShell 命令引用；CLI
  提示使用实际 Python，不依赖全局 `fixfirst` 命令。界面标明 PowerShell。
- 接受省略 `.exe` 的 Python 路径；识别 Windows Conda 布局并提供相应 DLL/脚本
  搜索路径；文件浏览器可从盘符根目录切换到其他盘。
- 支持 PowerShell 5.1 UTF-16 日志/requirements、BOM 与本地编码；保持 JSON
  在 GBK 控制台有效；不再改变被测项目所启动子进程的原有编码语义。
- 修复路径别名的 requirements 引用、大小写重复声明及 Windows 路径证据处理。
- Windows 检查进程在启动前归属 Job Object。超时、Ctrl+C、关闭控制台和服务
  被强制结束时清理整个检查树；服务停止后禁止请求线程再启动下一项检查。
- 修复服务地址重定向输出缓冲、重复端口绑定；校验端口范围。
- 导出清理反斜杠转义、斜杠和大小写变体路径；行动 ID 使用独立散列并同步引用，
  避免路径派生 ID 泄露用户名或被替换成重复 ID。嵌套 JSON 仍保持可解析。
- 安装复用兼容环境，拒绝混用 Python ABI。显式 `-Recreate` 会保留旧环境备份。

## 原 Windows 包的验证记录

以下是基础提交 `ec87d05b38b186700f63c196024d90f5bbbc1696` 所附的历史记录，
不表示后文的本地修订已经在 Windows 重跑。完整原始证据保存在原开发机的
`workbench/windows-audit-20260924/`，不随组员测试包分发。

| 验证 | 结果 | 日志 |
|---|---|---|
| Windows 11 / Python 3.12 全套，含新增 8 项回归 | **149 passed** | `adaptation-pytest.log` |
| 最后路径证据改动后的相关回归 | **28 passed** | `adaptation-targeted-final.log` |
| Ubuntu WSL / Python 3.12 全套 | **148 passed, 1 skipped**（PowerShell 专项） | `adaptation-linux-pytest.log` |
| 真正 ACP 936 的独立 Python，全套 | **147 passed, 2 failed**，原因见下 | `adaptation-cp936-pytest.log` |
| Ruff、pip check、CLI help | 通过 | 主目录实际安装执行 |
| GBK JSON、中文/UTF-16 导入、requirements、导出 | 通过 | `fresh-adapted-cp936-functional.json` |
| GBK 下直接 pytest 与 FixFirst 检查结果对照 | 一致 | `fresh-adapted-cp936-parity.json` |
| 实际 PowerShell 参数往返，包括中文空格解释器 | 完全一致 | `fresh-adapted-candidate.json` |
| 父进程退出、子进程仍持有输出管道 | 0.203 秒结束；原来约 9 秒 | `fresh-adapted-pipe.json` |
| 版本探测超时及子树清理 | 1 秒期限，1.078 秒返回 | `fresh-adapted-sandbox.json` |
| 3 个并发读取者与写入者 | 4254 次读、221 次写，0 错误 | `fresh-adapted-race.json` |
| Ctrl+C / 强制结束 / 关闭控制台 | 均无存活检查进程、无新检查启动 | `adaptation-web-*.json` |
| 指定不同 Python 版本重装 | 拒绝覆盖，原 `pyvenv.cfg` 哈希不变 | `adaptation-setup-mismatch.log` |

上述 GBK 记录中的两个失败分别为 `test_export_redacts_and_html_escapes` 和
`test_pip_pass_can_miss_project_dependency_and_advice_has_provenance`：当时使用无
`encoding` 参数的 `read_text()`，将 UTF-8 HTML 当作 GBK 读取。本次已将两处改成
`read_text(encoding="utf-8")`，保留原断言和产品的 UTF-8 输出；原来的失败记录保留，
首次修订的后续 Windows／GBK 反馈见下。

## 首次追加修复与 Mac 复核（2026-09-24，历史记录）

修订号：`windows-review-fixes-20260924`。这是上述基础提交导出包上的本地修改，
没有对应的新 Git 提交；`RELEASE_MANIFEST.json` 已更新为当前文件的校验值。

- 网页与 CLI 问答将问题中完整的原始行动 ID 映射到公开 ID，避免误答排第一的行动；
  兼容公开 ID，并区分互为前缀的行动 ID。
- 补充带单引号用户名的脱敏，覆盖 Windows 反斜杠／斜杠路径、POSIX 路径、
  pytest 临时路径、引号包围的主目录及嵌套 JSON；后续发现的文本边界问题见下。
- 两处旧测试显式按 UTF-8 读取 HTML，避免依赖机器默认编码。
- 新增 10 个回归用例，覆盖指定行动问答、路径脱敏及保留路径之间的诊断文字，全部通过。

本次使用 macOS arm64、Python 3.12.14，明确加载本包 `src/`：

| 检查 | 本次结果 |
|---|---|
| 全套 pytest | **158 passed, 1 skipped**，34.29 秒；共 159 个用例 |
| 跳过项 | Windows PowerShell 参数往返测试 |
| Ruff：`src tests scripts` | 通过 |
| CLI：`python -m fixfirst --help` | 通过 |

该次 Mac 复核没有执行 Windows、WSL、GBK 或真实 Conda 检查，也未覆盖双击启动器与
GUI 的完整人工验收。

### 首次修订的 Windows 后续反馈

用户转发的 Windows Codex 复核报告称：Windows 和真正 GBK 环境均 **159 passed**，
Ruff 通过，包内文件校验全部匹配；此前两个 GBK 测试失败已消除。原始记录在 Windows
开发机的 `workbench/mac-review-20260924/REVIEW.md`，未随本包提供；此处记录的是转发
结果，非本机复跑结果。

该次复核另发现两个测试未覆盖的问题：

1. `Home 'C:\Users\Alice' is not inside /tmp/project` 脱敏后丢失了中间诊断文字。
2. `为什么inspect-beta？` 因中文与 ID 紧邻而未识别指定行动，转而解释首个行动。

## 第二次追加修复与 Mac 复核（2026-09-24，历史记录）

修订号：`windows-review-fixes-20260924-r2`。基础提交不变，没有新 Git 提交；
`RELEASE_MANIFEST.json` 描述当前修订的实际文件。

- 先确定引号包围的路径范围，再替换用户名，防止后文的斜杠被当作用户名之后的目录
  分隔符。上述输入现在保留为 `Home '<home>' is not inside /tmp/project`。
- 行动 ID 按 ASCII 标识符字符判断边界；中文紧贴 ID 的前后两侧都能识别。
  保留完整 ID 匹配、公开 ID 以及互为前缀 ID 的行为。
- 在修改前复现了两个报告问题及相关变体；扩展后的相关回归全部通过。
  这些用例覆盖 Web 和 CLI、中文无空格提问、ID 片段、单双引号、带单引号和空格的
  用户名、Windows／POSIX／pytest 临时路径、后续路径有无引号及嵌套 JSON。
- 保留已知项目／解释器路径优先替换的行为，新增用例覆盖同时包含单引号和空格的
  用户名，确保引号解析不会破坏 `<project>`／`<python>` 别名。
- 相对首次修订新增 19 个测试用例，当前总数为 178。

本次仍使用 macOS arm64、Python 3.12.14，明确加载本包 `src/`：

| 检查 | 本次结果 |
|---|---|
| 全套 pytest | **177 passed, 1 skipped**，34.13 秒；共 178 个用例 |
| 跳过项 | Windows PowerShell 参数往返测试 |
| Ruff：`src tests scripts` | 通过 |
| CLI：`python -m fixfirst --help` | 通过 |

### r2 的 Windows 后续复核

用户提供的 `workbench/mac-review-r2-20260924/REVIEW.md` 已在本机读取。记录报告：
Windows 11 / Python 3.12 **178 passed，97.81 秒**，真正 ACP 936 / cp936 环境
**178 passed，96.70 秒**；Ruff 通过，842 个文件校验全部匹配。此处引用 Windows
复核记录，未在本机重复执行 Windows 测试。原始复现 JSON 和运行日志未随记录提供。

复核确认了 r2 的两处具体修复，同时发现：未知路径中单引号包围的 `O' Brien` 用户名
仍会泄露后半段；缺少结束引号的重复路径日志会触发明显的扫描性能回归。

## 第三次追加修复与 Mac 复核（2026-09-25，历史记录）

修订号：`windows-review-fixes-20260925-r3`。基础提交不变，没有新 Git 提交；
`RELEASE_MANIFEST.json` 描述当前文件。修复内容：

- 用顺序扫描取代整段后缀上的结束引号正则搜索；已扫描的片段即使没有结束引号也会
  被消费，不再从每个路径开头重复扫描同一尾部。
- 遇到单引号加空格时延后判定路径边界，结合后续路径、新的绝对路径、独立引用的
  文本和换行来确定范围。未知路径的 `'C:\Users\O' Brien\OtherProject\data.csv'`
  现在得到 `'<home>\OtherProject\data.csv'`，保留后面的诊断文字。
- Windows 盘符路径先于 POSIX 路径替换，避免 `C:/Users/Alice` 留下 `C:<home>`。
- 增加 18 个测试用例：未知路径的单引号加空格用户名、主目录和完整路径、
  Windows／POSIX／pytest 临时路径、嵌套 JSON、不同诊断后缀，以及两个接近 1 MB
  的未闭合路径日志回归。性能测试在独立子进程中校验完整输出，处理期限 4 秒，
  子进程超时 10 秒；超时会终止并回收测试子进程。

本次使用 macOS 26.6.2 arm64、Python 3.12.14，明确加载本包 `src/`：

| 检查 | 本次结果 |
|---|---|
| 修改前运行新增场景 | 复现用户名泄露；两个长日志子进程均超过 10 秒被终止 |
| 修复后的相关回归 | **37 passed** |
| 全套 pytest | **195 passed, 1 skipped**，35.41 秒；共 196 个用例 |
| 跳过项 | Windows PowerShell 参数往返测试 |
| Ruff：`src tests scripts` | 通过 |
| CLI：`python -m fixfirst --help` | 通过 |

性能对比在同一 Mac、相同解释器的独立子进程中进行，r2 代码从已交付压缩包读取。
输入为 `"'C:/Users/Alice"` 的重复文本，字节数按实际字符串长度计算：

| 输入字节数 | 重复次数 | r2 | r3 | r3 输出 |
|---|---|---|---|---|
| 168,000 | 11,200 | 5 秒超时，子进程已回收 | **0.021604 秒** | 与预期逐字一致 |
| 999,990 | 66,666 | 未另行计时 | **0.123245 秒** | 与预期逐字一致 |

以上为本机单次耗时，用于复核已知性能回归，不是跨机器耗时保证。该次 Mac 复核
未执行 Windows／GBK／WSL 测试；后续 Windows 结果见下。

### r3 的 Windows 后续复核

用户提供的 `workbench/mac-review-r3-20260925/REVIEW.md` 已在本机读取，记录报告：
Windows 11 / Python 3.12 **196 passed，98.82 秒**；真正 ACP 936 / cp936 环境
**196 passed，112.75 秒**；Ruff 及 842 个文件校验通过。近 1 MB 的未闭合路径日志
分别耗时 0.2728 秒（正斜杠）、0.2594 秒（反斜杠），输出逐字一致。

GBK 首次运行曾有 2 项性能测试因测试子进程覆盖 `PYTHONPATH` 而无法加载依赖失败
（194 passed）；Windows 复核方补齐专用验证环境的依赖入口后完整重跑通过，没有
改动产品源码。以上引用用户提供的复核文档，原始运行日志仍在 Windows 开发机。

该轮另发现：扫描器把路径后 `mode='r'`、`error='permission denied'` 的结束引号
当成路径的新结束位置，导致这些诊断字段被一起脱敏。

## 第四次追加修复与复核（2026-09-25）

修订号：`windows-review-fixes-20260925-r4`，组员测试包的 `RELEASE_MANIFEST.json` 描述其文件。
这一版的修复已在 v0.6.1 合入仓库。

- 扫描器在已有候选路径结束引号后，遇到赋值、键值或容器语法引入的引号值时，
  结束当前路径范围，保留后面的诊断字段。识别两种引号、空值和带前导空格的值，
  不再只检查引号前是否有空白。
- 新增 21 个回归用例，覆盖 Windows／POSIX 主目录、单引号加空格用户名，
  `mode`／`error` 字段、有无冒号、多字段、嵌套字典、不同引号及字段中的另一条
  路径。每个用例均检查普通 `Run.stdout` 和嵌套 JSON 的完整输出。
- 性能测试改为将本包 `src` 前置到继承的 `PYTHONPATH`，保留验证解释器需要的
  第三方依赖路径，同时确保子进程加载当前源码。

本次使用 macOS arm64、Python 3.12.14，明确加载本包 `src/`：

| 检查 | 本次结果 |
|---|---|
| 修改前运行新增场景 | 21 项全部复现字段丢失 |
| 修复后的相关回归 | **58 passed**，包括之前的路径和性能回归 |
| 全套 pytest | **216 passed, 1 skipped**，35.18 秒；共 217 个用例 |
| 跳过项 | Windows PowerShell 参数往返测试 |
| Ruff：`src tests scripts` | 通过 |
| CLI：`python -m fixfirst --help` | 通过 |

本机单次性能复核（不含模块导入），所有输出均与预期逐字一致：

| 输入 | 实际字节数 | r4 耗时 |
|---|---|---|
| 原未闭合路径复现 | 168,000 | 0.021544 秒 |
| 原未闭合路径复现，接近输出上限 | 999,990 | 0.135953 秒 |
| 重复的主目录加 `mode`／`error` 字段日志 | 999,966 | 0.099248 秒 |

用户随后提供的 `r4` 复核记录：Windows 和真正 GBK 环境均 **217 项通过**；另外 320 组
脱敏检查全部通过，近 1 MB 日志约 0.26–0.33 秒处理完成；Ruff、压缩包和文件校验均通过；
没有发现新问题。原始记录在 Windows 开发机。WSL 未重跑。

合入仓库（v0.6.1）时没有改动产品代码，只放宽了两项计时测试的上限，避免较慢的电脑或
杀毒软件扫描导致误报：孤儿子进程测试从 1.8 秒放宽到 4 秒（子进程改为睡 6 秒，
仍能区分"没等它"和"等了它"），沙箱超时测试从 2 秒放宽到 5 秒（子进程改为睡 8 秒）。

## 已知边界

- 原包记录了 Windows 11 与 Linux 回归，r1 至 r4 均收到 Windows／GBK 全通过的反馈。
  Windows 10 与真实 Conda 仍待实机验收；r4 之后未在 WSL 重跑。
- Windows 显示的命令目标是 PowerShell，不能直接复制到 cmd.exe。
- 未在真正安装了 Conda 的环境做端到端验收；已实现其 Windows 布局处理。
- 超长工作目录仍受 Windows/Python 的启动限制；优先使用正常长度项目路径。
- 文件共享冲突有约 1 秒的有界重试；持续外部独占文件仍会报错。
- 分享前仍需预览报告；脱敏不承诺识别任意自由文本中的个人信息。
- 旧审查中的信息项和其他非阻塞产品改进不等于本次全部完成。当前交付是可实际
  安装和使用、已有上述实测覆盖的 Windows 版本。

Windows 进程管理依据微软的 [Job Objects](https://learn.microsoft.com/en-us/windows/win32/procthread/job-objects)
及 [Nested Jobs](https://learn.microsoft.com/en-us/windows/win32/procthread/nested-jobs)
机制。适配与复核回归在 `tests/test_windows_adaptation.py`；原有 141 项测试的
断言保留，仅修正了前述两处 HTML 读取编码。
