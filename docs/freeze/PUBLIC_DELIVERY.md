# v0.7.0冻结与交付

正式冻结以远端`v0.7.0`标签和[B5 #19冻结记录](https://github.com/ZihangHe13123/FixFirst/issues/19)为准。本文随冻结PR提交；标签尚未建立或任务记录尚未完成时，不得只凭本文或版本字符串判定冻结完成。

## 正式标签的固定源码与安装包

`v0.7.0`应指向干净public历史正常合入main后的提交，保留`4a7c470`等已验公开祖先。最终main/tag完整提交号、正式207文件安装包SHA256和CI链接写入B5任务；注释标签也记录该包摘要。**正式包由最终标签所指提交重新构建，下表392736…仅是合并前候选包的历史摘要。**

取得正式版本及重建安装包（Python 3.11或更新版本）：

```bash
git clone https://github.com/ZihangHe13123/FixFirst.git
cd FixFirst
git checkout --detach v0.7.0
python3 scripts/build_source_zip.py --revision "$(git rev-parse HEAD)" --output output/FixFirst-v0.7.0.zip
git show --no-patch v0.7.0
```

Windows PowerShell可将Python命令换成`py -3.12`，并以`$FreezeRevision = git rev-parse HEAD`后传入`--revision $FreezeRevision`。保留生成的`.zip.receipt.json`，核对其source_commit与标签指向的commit相同，以及包SHA256与注释标签/B5记录相同。构建器只创建本地文件，不宣布冻结状态；正式状态由远端tag及B5记录决定。

最终源码的生产代码、默认模型和回归测试应与已验候选逐字节一致；正式冻结只增加交付说明、CI触发和合并元数据。如不一致，必须重新说明和验证，不能套用候选收据。实际main与tag CI均应运行同一完整pytest/Ruff，结果以各自Checks为准。

Windows真人签收仍按C3计划进行。R11的位置专用参数机制只有5个公开机制任务验证，没有该机制的独立保留验证，不能称为泛化提升。A2仍需A/C确认C1已冻结；本次不读取C1标签或保留输出，也不启动A2。B7准备与分析分支未合入，正式B7还需A2第1–6步结果PR合并。

## 合并前候选的历史验证

本分支为`codex/release-0.7.0-public`，从已公开main独立导入获准交付文件，不包含旧发布准备分支的未公开历史。原分支及旧ZIP在本地保留。

## 候选身份与取得方法

这是发布准备分支，尚未正式冻结或发布tag。以下固定源码与包已经本地验证；后续文档提交不改此包，不能用可变HEAD代替固定源码。

| 项目 | 已验证值 |
|---|---|
| 固定源码提交 | `4a7c470633bd087cc0bc3d899db190fb4bd07bba` |
| 应用版本 | `0.7.0` |
| 安装源码ZIP | `FixFirst-0.7.0-public-4a7c470.zip` |
| ZIP SHA256 | `392736ba461d1979d110515400806a74ac985d3c74ebd0ad37783cd385b9baa4` |
| 大小 / 文件数 | 809,988字节 / 207文件 |

[本次收据](public-validation-20261001/RECEIPT.json)与[完整包成员收据](public-validation-20261001/source-zip.receipt.json)分别记录验证结果及文件摘要。旧d7ca505包的7452a000…摘要属于旧本地包，不是本次公开候选。

源码可以从[公开候选分支](https://github.com/ZihangHe13123/FixFirst/tree/codex/release-0.7.0-public)取得。要重建上述精确安装包，用Git克隆仓库（构建器需要Git对象），然后用Python 3.11或更新版本运行：

```bash
git clone --branch codex/release-0.7.0-public https://github.com/ZihangHe13123/FixFirst.git
cd FixFirst
python3 scripts/build_source_zip.py --revision 4a7c470633bd087cc0bc3d899db190fb4bd07bba --output output/FixFirst-0.7.0-public-4a7c470.zip
```

Windows可将`python3`替换为`py -3.12`或实际Python完整路径。核对上述完整SHA256，并同时保留相邻`.zip.receipt.json`。输出路径已存在时请换新目录，不覆盖旧包。GitHub的“Download ZIP”是分支开发树快照，不能拿它的摘要与这个207文件安装包比较。

安装与实际使用见[快速指南](CANDIDATE_QUICKSTART.md)，Windows执行及签收见[Windows交接](WINDOWS_HANDOFF.md)。首次安装需要联网。

## 实现与验证边界

生产实现沿用已验第十一轮候选，不新增诊断行为；默认44特征模型保持SHA256 `4479864358595024a121b57fdb49f66f6d184c096c5a243a11fb5f1efdfb41e3`。位置专用参数精确建议默认开启，仅经5个公开机制任务验证，没有该机制的独立保留验证。

旧版的安装和主回归见[历史本地交付记录](LOCAL_DELIVERY_20261001.md)。本次在新公开树的独立环境重新执行：**776 passed、1 skipped**，唯一跳过项为Windows PowerShell quoting；同一完整范围Ruff通过。62个生产文件、37个测试按摘要绑定到本次固定源码；三份历史复现helper的机械格式修正保留原件和[前后摘要](evidence/PUBLIC_HELPER_STYLE_RECEIPT.json)，没有重跑私有复现或改动原结果。

本次新ZIP连续构建两次逐字节一致；中文及空格路径下原样setup安装成功，CLI、无测试脚本、按文档修复的既有样例4个原测试、导出、Web HTTP与停止/重开均通过。26个共有依赖版本与完整回归环境一致。新包207个原文件在验证后全部未变。样例流程不是新模型收益，HTTP检查也不是浏览器视觉或Windows验收。详见[回归记录](public-validation-20261001/development-report.md)和[安装记录](public-validation-20261001/installation-report.md)。

GitHub Actions会在公开分支push后运行源码回归；实际结果以对应提交的Checks为准，本地收据不冒称远端CI已完成。

参考源码ZIP仍是白名单安装包，不含全部开发测试fixture；Git分支保留完整开发测试和必要已公开支持材料。公开源码CI跑完整pytest与Ruff，不启动模型、用户研究或正式评估。CI通过不代表Windows真人验收。

## 后续验收与独立评估

正式源码采用、标签及冻结记录的实际状态见本页首段所指远端tag与B5任务。Windows真实验收待C完成；A2必须等B5与C1标签冻结均明确确认，正式B7还要等A2第1–6步结果PR合并。不能将B5技术冻结记成Windows签收、A2评分或B7实验已经完成。

公开聚合说明保留其条件复现限制；12个私有起点会话没有导入。独立B7框架和分析方法分支也没有合并进本分支。
