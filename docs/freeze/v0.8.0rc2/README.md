# v0.8.0rc2 产品冻结

本记录固定用于后续对照的产品候选。冻结在以下两项都满足后生效：远端注释标签 `v0.8.0rc2` 指向下面的产品提交，且该提交的 [main CI](https://github.com/ZihangHe13123/FixFirst/actions/runs/37196927268) 成功。以远端标签和检查结果为准，不能仅凭本文判定已完成。

## 固定对象

| 项目 | 值 |
|---|---|
| 产品提交 | `804cc3c455061517cbc5edb21a9fe4b66626b453` |
| 产品树 | `14f6efadbfc6681f6d8887a05b994abc8f5c76f6` |
| 独立验收候选 | `b1edf8dc66c97361191dd43edf9404771f48b658`，与产品提交的整个文件树一致 |
| 软件版本 | `0.8.0rc2` |
| 默认树 | 81 特征，schema 8，`189f712ea75bcb117f96aae879fd0c9bdab9ee6531475d1a95faf01ec2738d30` |
| 合并顺序 | [#68](https://github.com/ZihangHe13123/FixFirst/pull/68) → [#70](https://github.com/ZihangHe13123/FixFirst/pull/70) → [#71](https://github.com/ZihangHe13123/FixFirst/pull/71) |

机器记录 [freeze.json](freeze.json) 包含 77 个运行文件、规则、知识库、两份验证收据和旧 44 特征模型的摘要。后续 main 可以增加文档；对照运行应使用上述完整提交或该标签。

```sh
git fetch origin tag v0.8.0rc2
git switch --detach v0.8.0rc2
git rev-parse HEAD
git show --no-patch v0.8.0rc2
```

## 配置与验证

默认启用分类器，未指定 `--model` 时加载内置 81 特征树；最低采纳置信度为 0.6。`structured_evidence` 和 `bounded_actions` 的默认值都是 false。默认分组为 tfidf、阈值 0.82。显式选择模型或打开实验开关时应另行记录配置。

CLI 的 `init --goal` 默认是 `auto`，会根据项目选择目标；Session/API 的默认目标是 `collect_tests`。对照实验必须明确目标、入口、参数、输入和解释器。

- PR71 的 130 项定向测试、391 份记录回放及完整分段回归通过；独立验收对 255 个旧用例和 21 个新增用例没有发现挡合并问题。
- owners 在同一生产源码上重生成：155 个键与 23 个 merged 键通过，收据审计为 0；本次合并未改变被绑定的文件。
- 从产品提交的干净 Git archive 构建 wheel、sdist。两包及独立安装后的 77 个运行文件逐字节匹配提交；程序和嵌套 src 的实际修复通过，旧 44 特征模型可以加载。
- 原始运行环境和跳过原因见 [开发验证](../../validation/2026-10-04-pr70-followups.md)。[控制器清单](controller-inventory.json) 是 macOS 打包/离线校验环境，不是 B7 的正式运行环境；额外测试解释器另配。

## 安装包身份

| 文件 | SHA-256 |
|---|---|
| `fixfirst_local-0.8.0rc2-py3-none-any.whl` | `88c39e3194b047e1b11aabdb8a2fcd7e6d4ebe8c0707f3a3e5b7276a6eb5bad5` |
| `fixfirst_local-0.8.0rc2.tar.gz` | `b7d4397dd51ea64d536edcba5752870d24f9ce6bf03a1251c100cf26e5fe55f4` |

构建使用 CPython 3.12.13、build 1.6.1、setuptools 81.0.0 和 `python -m build --no-isolation`。上表绑定本次验收的包；重新构建的归档时间等元数据可能不同，不能承诺整个包摘要逐字节重现，应同时核对运行文件清单。包保存在交付工作区，本记录不表示已经上传到 PyPI 或 GitHub Release。旧 v0.7.0 源码 ZIP 白名单不作为新版安装包。

## 下一阶段边界

这是产品候选冻结；B7 正式登记仍未完成。真实项目/难例清单、运行环境、模型与聊天模板身份、协议编号、比较族和预算应在运行前单独登记；原先写 v0.7.0 的草稿不能自动视为 v0.8 登记。

A2 和本轮验收用例已参与 v0.8 开发，只能用于开发回归。新版本在未见项目上的表现需要独立材料和协议。历史 v0.7.0 标签与已封存 B3 结果保持原身份；本次没有启动新的语言模型运行或正式实验。

已知限制 R1–R4、O3–O5 见 [独立验收与已知限制](../../validation/2026-10-04-pr70-followups.md#独立验收与已知限制2026-10-04)。Windows/PowerShell 尚无本轮实机验收；冻结不等于所有平台或所有项目均可修复。
