# B7 小规模 A2 开发对照：登记材料

2026-10-04。**材料已整理，等待最终登记文稿绑定；本次整理未启动模型、提交、推送或合并。**

## 范围

- 两个任务：`django-storages`、`python-slugify`。
- 三组：`baseline`、`facts`、`mcp`。
- 三模型每个任务、每组分别 5 / 5 / 3 次，共 **78 次计划运行**。
- 不带 6 个生成难例，不使用新的留出任务。
- 固定产品/框架：`804cc3c455061517cbc5edb21a9fe4b66626b453`（`v0.8.0rc2`）。
- 这是 **A2 在 macOS arm64 上的开发重建对照**，不是 Windows 原环境复现，也不是未见任务的泛化评估。两项完整参考通过才纳入；78 次重复不能当成 78 个独立任务。

## 文件

| 文件 | 用途 |
|---|---|
| `projects.toml` | 两项项目清单，与已通过的无模型预检逐字节相同；原文件的“not final selection”注释保留，最终状态由登记正文决定 |
| `environments/*.txt` | 项目环境快照；两项实际使用 Python 3.12.7，原 pins 未改 |
| `reference_repairs.toml` | 已通过完整套件的参考命令，供独立判分器使用 |
| `source-identities.public.json` | 固定源码 commit/tree、slugify 的测试 overlay 来源及摘要、参考计数 |
| `patches/python-slugify-tests-overlay.patch` | 只构造起点的上游回归测试 overlay |
| `patches/python-slugify-reference-production.patch` | 参考答案，只改上游 `slugify/slugify.py` |
| `inclusion-ledger.public.json` | 12 项完整纳入总账：2 项纳入、6 项待补参考、3 项按当前协议排除、1 项 healthy 对照 |
| `run-scope.public.json` | 78 次范围和统计证据发布待办；不替代最终协议 |
| `model-identity-current.public.json` | 三模型的 44 个已登记文件摘要及服务环境身份；原记录未启动推理，其限制原样保留 |
| `environment-current.public.json` | 固定 FixFirst 控制环境身份；文件中的 hard environment 是原准备记录，**不表示本批包含难例** |
| `controller-lock.txt` | 与环境记录相同的控制环境包清单 |
| `MATERIALS_MANIFEST.json`、`SHA256SUMS` | 本材料包的文件摘要 |

JSON、两份项目快照和命令均无本机绝对路径。原始 stdout、JUnit、沙箱 profile、主机名和本机目录没有复制进来。总账保留本地原始记录的相对编号与摘要用于追溯，但不包含那些原始文件。

## 参考与起点的隔离

**本目录包含答案。** `reference_repairs.toml`、参考 production patch、选择总账及 source identity 应保存在运行沙箱不能读取的位置，不能放进运行项目、模型可读源码克隆、输出目录或 harness 的可读位置。测试 overlay 只在受保护源码克隆中形成起点，再按该起点提交导出；参考 production patch 只能由判分器在独立参考副本中应用。

不要将本目录整体复制到固定产品的运行检出。材料将来能公开，不等于实验进行中可以让 agent 读取答案。

## 源码复现要点

### django-storages

上游 `jschneier/django-storages` 的 `1.14.6` 在本次取回时解析为 `3658c3d2353b778a45b09dd7a55cbabc66d22381`，tree 为 `3a1ced0cb0b672a3d29ff9089677f3f675a3ee53`。这里只保证本次固定了该源码，不宣称独立核验过原 A2 Windows 检出的完整 HEAD。

参考只安装 `pytest-django==4.11.1` 并在既有 tox.ini 的 pytest 配置中设置 `DJANGO_SETTINGS_MODULE = tests.settings`。完整参考 253 个节点通过，保护文件/测试选择设置未变。

### python-slugify

不能直接拿 `v9.1.0` 最新 tag 树代替起点。起点生产源码必须为 A2 清单明确给出的 `c442cd4cb61763c85b078d6ea83b5959c3ff364a`，再从 `8f9a550a906701412c8fc93e731582098f2caee2` 取唯一文件 `tests/test_release.py`。测试文件 SHA-256：

`40533c17177a6cbabbc3e549817b29baf3b7ee954e5ca73475ea6aa159eb8273`

本地仅测试 overlay 提交为 `025da8e577fd21c37f1794bd5cc2acb954e4c0e0`，未推送；其固定内容树为 `8461312530696a7daf79de90b68ae21e017d759f`。别人可从上游父提交应用本包测试 patch 重建相同内容树；新建 commit 的作者和时间会改变提交号，因此不要求另一次重建的提交号相同，也不能把本地提交当作可从上游 fetch 的对象。

起点 freeze 后，参考仅应用 production patch，不改测试。完整参考为 125 个通过的方法节点；pytest 另外报告 115 个通过的 subtests。起点的原始 pytest 汇总是 7 failed、124 passed、109 subtests passed；B7 按方法节点归一为 123 passed / 2 failed。这些是计数口径不同，不是缩小测试范围。

## 总账和未完成事项

完整 12 项保留在总账中，未因只跑两项而消失：

- **纳入 2 项**：django-storages、python-slugify。
- **待补参考 6 项**：click、pytest、dateparser、httpx、robotframework、python-markdown。它们仍有后续故障或当前投入内没有得到完整参考，不是永久排除。
- **按当前协议排除 3 项**：python-qrcode 的 Windows 故障机制在 macOS 上改变；django-cacheops 需要外部 Redis；seleniumlibrary 的完整套件与当前沙箱的本地 socket 限制冲突。
- **healthy 1 项**：python-ftfy，起点已通过，不进入修复率分母。

另外，方案 A 的两个统计证据发布校验器仍停在 `67e1077`，**结果路径链接逃出本包**和**悬空 `.git` 被当作无历史**两项返修尚未完成、尚未集成。本材料没有把它们标成已通过。两项只需补校验器和定向检查，不需为此重跑 24 组模拟；是否可引用其统计结果仍按最终登记与报告明确的边界处理。

在收到最终登记文稿、冻结必要设置和运行身份以前，这些材料只是可审查的登记输入，不是已开始或已完成的实验。
