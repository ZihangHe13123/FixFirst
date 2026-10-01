# 第七轮：安装失败进入下一步计划

生产候选：`eec1c5c686a010cb215f9fb70b550163d3692814`。初版：`9b74c2a`。基线：`5d661e6`。
这是已知公开开发案例上的修复。没有使用私有留出或正式冻结数据，也没有改变内置决策树权重。

## 改动

- 手动 pip 命令记录会话日志，下次扫描读取新输出；导入日志和实际检查结果分开，日志不验证项目通过。
- 只取追加日志的最后一次调用，拒绝非普通文件、符号链接和可识别的其他解释器日志；读取与保存均有上限。
  对大索引日志保留最终失败的需求对应的源码链接，避免把它误判为不存在的包。
- 区分源码包被 wheel 限制排除、找不到发行版、版本冲突、缺 pg_config 等构建工具、旧构建配置。
  pip 详细栈中的内部 ResolutionImpossible 不再单独当作版本冲突。
- 显式手动 pip wheel 只准备被点名的包。名称、版本、元数据、标签和内容哈希经过检查后，
  wheel 可进入临时解析试验及用户安装命令。自动扫描不运行源码构建、不安装到项目环境。
- 解释器、声明或 wheel 内容改变后旧结果失效；按工具精确改过声明后，随后安装失败仍可回到会话。
- 目标缺 pytest 时，唯一含 pytest 的 requirements/dev.txt 可随测试目标选中并读入 prod.txt。
  多个候选不自动混合；其他可选组保留。哈希锁文件不生成丢掉原哈希的命令。
- 解释 psycopg2-binary 与 psycopg2 声明的区别；真实冲突、旧构建配置仍有需要人决定的情形。
- 在本会话绑定的 pip 输出中，间接依赖的源码阻塞也能成为下一步，保留日志里的版本范围。
  其他来源的未绑定日志不会为未声明的包生成构建命令。间接包构建失败后也不能原样重试安装。
- 排除旧版搜索不再自动变成升级到最新版的试验；旧使用方没有声明版本上限不等于运行时兼容。
- CLI 和详细报告将安装输出标为 Installation record，不计入“仍失败/已验证修复”统计；原记录不篡改。

## 验证状态

### 初版 9b74c2a

- 主测试 613 passed、1 skipped；Mac harness 58 passed。
- Codex 在 Claude 预登记的 11 个流程用例上复查：6 PASS、5 REVIEW、0 FAIL；
  Claude 完成含 C1 的全部 12 例：7 PASS、5 REVIEW、0 FAIL。
  PASS 包括“正确拒绝错误建议”等检查，不能当作项目完成率；REVIEW 不计成功。
- Codex 在固定提交的新副本、Claude 在独立检出与环境里，分别按 C1 原始起点照做：
  8 个工具建议的动作后通过原 4 个测试，pip check 0，测试哈希不变。
  只按精确建议把 multidict==6.0.4 改成 7.0.0；Flask-Mail==0.9.1 和 langdetect==1.0.9 保持。
  操作者没有自行选择版本或补充修法。C1 在这轮为 M1；它已是开发案例，不能外推整体成功率。
- 独立旧例复核发现 **C 回退**：源码 wheel 放行后，试验推荐 Django 1.10.5 → 6.1.1，
  pip check 虽通过，原程序随后因 providing_args 报错。另发现 docopt 间接依赖会重复安装，
  成功后旧安装日志仍显示 Still failing。三个问题均在同一输入上先复现，再修改。

### 返修 eec1c5c

- 主测试 **617 passed、1 skipped**（112.21 秒），Mac harness **58 passed**（85.06 秒）。
- 新反例在 9b 上得到 3 failed、1 passed；修改后相关扩展测试 177 passed、1 skipped，
  再补一个间接构建失败测试通过。Ruff 与 diff 检查通过。
- num2words==0.5.13 → docopt>=0.6.2 的真实开发探针：3 个建议动作后原脚本通过，
  声明和脚本不变，pip check 0。该探针在提交返修前运行，与固定提交后的独立复测分开。
- Claude 对固定提交完成窄复核，**没有发现阻塞**：同一预登记验收仍为 7 PASS、5 REVIEW、0 FAIL。
  C1 仍是 8 个动作、4 个原测试通过，测试哈希不变，pip check 0，无操作者版本选择。
- 旧 C 从真实原始起点停止在声明/解释器的审阅步骤，没有试验、安装命令或声明改动，
  不再推荐无依据的跨大版本升级。A2 与 D2b 的试验、精确修改和原测试通过没有回退。
- Claude 独立重跑间接 docopt：3 步通过，pip check 0，声明与测试不变。
  显式导入的未绑定日志，以及本会话目录里无对应命令的合法文件名，均不触发 docopt 构建。
  其中一次文件放错位置的探针已标为设置错误，不用作证据；正确位置另行重做。
- CLI 的旧安装输出全部改标 Installation record；最终报告仍失败组为 0。
  修改前那条 multidict 声明仍显示 Not checked this round，保留为历史而不冒充已验证。

## 证据入口

- [Codex 开发记录和测试输出](round7-development/README.md)。
- [Claude 预登记验收脚本](../field_trial/acceptance_r7.py)。
- [Claude 的原基线和初版结果](../field_trial/results/round7-acceptance/)：
  `baseline-5d661e6*.json`、`r7-9b74c2a.json`、`C1-strict-9b74c2a.jsonl`、`old-cases-9b74c2a.json`、`probes-9b74c2a.json`。
  初版证据保留，不用返修后的结果覆盖。提交来源与人工核对事项见 [证据索引](../field_trial/EVIDENCE.md)。
- Claude 的最终证据：同目录下 `r7-eec1c5c.json`、`C1-strict-eec1c5c.jsonl`、
  `old-cases-eec1c5c.json`、`probes-eec1c5c.json`，原证据提交 `4633ba2`（父 `f894430`）。

## 限制

源码构建仍需用户明确执行；未识别的发行版/索引问题、系统依赖安装和旧构建配置可能需人工处理。
每轮通常只处理当前暴露的阻塞，因此 C1 仍需 8 个动作。日志与 wheel 会留在项目内的
`.fixfirst/installation/`，本次约 27 MB，不代表源码改动；README 已说明保存位置和用途。
wheel 成功生成或安装元数据一致，不保证应用行为正确。C2 的使用方迁移和 notebook 相关覆盖仍需后续工作。
本轮没有重训或部署新模型，不能把一个已知开发项目的完成外推成整体准确率提升。

数据扩增的后续安排已补充到 [人工与生成数据计划](../../docs/HUMAN_DATA_TRAINING_PLAN.md)，
使用可执行变体、同源分组和固定配置的学习曲线；不在本次固定候选上边测边改。
