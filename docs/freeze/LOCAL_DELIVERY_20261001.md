# B5本地候选交付与验收：2026-10-01

**本地源码ZIP、干净安装和必要入口已验证；B5尚未正式冻结，A2没有启动。**

本页保留旧本地候选d7ca505的历史验收，不能作为当前公开分支的源码身份或CI结果。新的干净交付分支及其验证见[公开交付记录](PUBLIC_DELIVERY.md)；旧提交不随新分支推送，公众不能假定能从新分支检出本页的旧源码SHA。

## 候选身份

| 项目 | 实际值 |
|---|---|
| 发布准备分支 | `codex/release-0.7.0-prep` |
| 本包固定源码提交 | `d7ca5052805410a74b5dda8bc02c0a30125c90f2` |
| 包内及安装后版本 | `0.7.0`（本地候选，未发布正式tag） |
| 源码ZIP | `output/FixFirst-0.7.0-candidate-d7ca505.zip` |
| ZIP SHA256 | `7452a000893d7bd6d78463dc6d828085822a9142b167df25343318bf70390748` |
| 大小 / 文件数 | 675,274字节 / 169文件 |
| 模型SHA256 | `4479864358595024a121b57fdb49f66f6d184c096c5a243a11fb5f1efdfb41e3` |
| 出厂模型政策 | 44特征、43训练场景215记录；保留已验模型，冻结不重训 |

ZIP保存在本地output（不提交Git、不上传）。相邻`.zip.receipt.json`记录全部成员的归档摘要、Git blob摘要及仅限声明的换行转换。
[收据归档](validation-20261001/source-zip.receipt.json)提供相同记录；[总体收据](validation-20261001/RECEIPT.json)区分原日志与脱敏副本摘要。
后续报告提交不改这份已验证ZIP；构建时应使用上面的固定源码提交，而不是可变HEAD。

## 实际完成了什么

| 核验 | 结果 / 边界 |
|---|---|
| 构建和独立成员核验 | 169项恰等于白名单；无额外/重复/越界/符号链接成员。源码与ZIP字节逐项核对。仅setup.ps1、start-fixfirst.bat按仓库声明转CRLF，分列前后摘要。 |
| 重复构建 | 同一固定提交再次构建，ZIP逐字节一致。 |
| 干净安装 | 解压到新的中文及空格目录，无预存venv；用现有setup.sh和官方PyPI创建新环境，退出0。安装后module及distribution版本均0.7.0，加载路径在新解压目录中。 |
| CLI、现有样例 | help正常；依现有playground的FIXES.md修改样例，原测试未改，完整4 passed、goal achieved。仅说明操作流程，不计诊断或自主修复收益。 |
| 无测试脚本 | 新的最小入口检查执行成功，保存的目标为achieved；不计模型评估任务。 |
| 保存及导出 | CLI HTML/JSON报告与脱敏导出生成；Web实际HTTP主页、会话、Details、导出均200。 |
| 服务退出/重开 | 两次真实CLI服务进程以Ctrl+C对应SIGINT正常退出0；重启后原会话仍可读取。没有声称浏览器视觉或Windows验收。 |
| 可选notebook依赖 | 从官方PyPI安装声明的notebooks extras，退出0；随主回归验证现有notebook相关用例。 |
| 新环境主回归 | **776 passed、1 skipped**，使用新安装候选及同提交完整开发测试/公开fixtures。未将不含全量fixtures的ZIP称为全量回归包。 |
| Mac harness | 既有99c8086的**58 passed**保留，未重跑；隔离/进程实现未改变。 |

补跑主回归的原因：新环境解析得到scikit-learn1.9.1，既有回归为1.9.0。诊断源码与测试没有变化（仅应用/包版本变为0.7.0），仍不能将不同依赖环境的旧全量结果冒充本次结果。
测试中的临时学习器fixture不替换出厂模型。安装/回归结束后再次核对模型摘要未变。

原系统`unzip`在本机C.UTF-8环境解压中文文件名时退出50；磁盘仍有177GiB，ZIP中文项UTF-8标志正确。
同包使用macOS系统`ditto -x -k`完整解压并核对成功，安装采用新的ditto目录，失败副本未使用。这记录实际工具兼容现象，不将其夸大成所有平台的根因结论。

## 怎样复现本地交付

完整Git仓库具备上述提交后，按[SOURCE_ZIP_PLAN](SOURCE_ZIP_PLAN.md)执行：

```bash
.venv/bin/python scripts/build_source_zip.py --revision d7ca5052805410a74b5dda8bc02c0a30125c90f2 --output output/new-candidate.zip
```

不要覆盖已验产物。Mac可用`ditto -x -k new-candidate.zip 新空目录`解压，再按[快速指南](CANDIDATE_QUICKSTART.md)执行setup.sh；Windows仍使用setup.ps1，实际验收待C。
本次安装是Python3.12.14/macOS，完整依赖清单见[环境记录](validation-20261001/final-clean-environment.json)。首次安装需联网，不要求wheel/sdist或离线镜像交付。

可在新解压的安装目录上重放必要入口脚本（会新建输出，不触及用户项目）：

```bash
python3 docs/freeze/validation-20261001/check_install.py --project "/path/to/extracted/FixFirst" --output "/new/entry-evidence"
```

此入口脚本只覆盖本次Mac/POSIX操作检查。主回归还需同提交完整开发工作区：用新安装venv的Python运行该工作区的`tests/`；日志和[回归范围说明](validation-20261001/regression-reuse.json)保留。
消融12个私有起点会话没有读取或打包，完整oracle回放仍是[条件复现](evidence/README.md)。

## B5及下游还差什么

1. **正式源码整合与版本确认**：B2/B8的PR32、B4的PR33已合并；本发布准备分支的后续工作尚未推送/合并。正式采用哪个提交须明确，不能仅靠本地版本字符串。
2. **正式tag、推送和Issue公告**：B5卡的完成标准仍包括v0.7.0标签推送和公告；本次无这些授权，未执行。只读查询远端v0.7.0引用返回404，不能说已发布。
3. **Windows实际执行**：任务终端尽量冻结前、最迟10/11，研究前必须通过；冻结版Windows验收明确依赖B5，不能反设为B5前置。两者均不能用Mac结果代替，见[门槛核查](validation-20261001/gates-audit.md)。
4. **A2门槛**：B5指定版本冻结和C1标签冻结均获确认后，再按原计划由A/C独立评分；本次没有读取C1标签、正式保留材料或运行A2。

B14完整图文指南仍为10/19初稿、10/22定稿；B15约10/20开始，不额外加作冻结前硬门槛。尚未获准的发布动作不会自动执行。

## 发布复核收尾与覆盖限制

- **F1：派生日志脱敏。**本地提交`4e24915`修正了两份公开安装日志各一处`/private/var/folders/...`路径，替换为`<tmp>`。原始本地日志未改；[总体收据](validation-20261001/RECEIPT.json)保留原日志摘要，并记录脱敏前后派生摘要及来源`3fe6501`；[文件摘要清单](validation-20261001/FILE-SHA256.json)同步更新。已验ZIP完整SHA-256与上表相同，未重建或替换。
- **F2：默认模型与产品机制分开。**默认44模型文件保持不变；第十一轮positional-only精确建议机制在普通管线中默认开启，不依赖第十轮的默认关闭实验开关。它仅经5个公开机制任务验证，**没有该机制的独立保留任务验证**。不能把第8–11轮各候选对照统称为默认配置验收，也不能用早期验收覆盖后来新增的机制。[模型政策](B5_MODEL_POLICY_20261001.md)已修正，C3增加[W13待验项](WINDOWS_HANDOFF.md#位置专用参数机制的windows待验项w13)。
- **F3：既有导出限制。**当前导出替换home、项目和精确解释器路径；位于home/项目之外的解释器环境前缀、purelib或traceback路径仍可能保留。分享前须预览导出，不承诺任意本机路径全部脱敏。这里只记录现有边界，未改导出实现。
- **F4：既有身份限制。**断言问题的`issue_id`不保证跨会话稳定。跨次记录配对应结合nodeid、稳定标题及检查范围，不能只比较issue_id。这里只记录，不修改生产行为。

Claude报告在固定d7ca505上再次运行Mac harness，公开日志为**58 passed，97.22秒**；本次只读核对了该聚合日志。这与上表99c8086历史结果分列，不冒称根助手新执行。其MCP两模式、Web等其它独立复核结论来自交接报告；根助手已有的实际干净安装、主回归和入口记录仍以上表及原收据为准。未读取其R8/R9保留逐例对照材料。

这些变更属于本地文档和派生证据收尾；固定ZIP、生产代码、出厂模型及正式实验权限均未改变。
