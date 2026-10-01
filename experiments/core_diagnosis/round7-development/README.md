# 第七轮开发证据（Codex）

这些是已经进入开发过程的公开案例，不是独立留出，也不能用于估计总体修复率。

- `summary.json`：提交、初始包、修改、检查结果、测试哈希及默认分类器哈希。
- `codex-C1-9b74c2a.jsonl`：固定初版的全新 C1 副本，逐步执行当时显示的命令和精确修改。
  8 个动作后原 4 测试通过；没有自行放宽版本或修改测试。原始依赖安装失败后只有 pip，
  Python 为 3.12.13，源码提交及差异见 summary。
- `codex-transitive-eec1c5c-development.jsonl`：num2words 0.5.13 的间接依赖 docopt 没有 wheel。
  先失败，再按显示步骤准备 wheel、重新安装，原脚本通过。它在提交 eec1c5c 前作为开发探针运行；
  固定提交的独立结果由 Claude 另存于 `../../field_trial/results/round7-acceptance/probes-eec1c5c.json`，
  同样 3 个动作后通过，声明和测试不变。
- `main-eec1c5c.txt`、`mac-harness-eec1c5c.txt`：最终生产代码的完整套件摘要。

`<C1>`、`<transitive>`、`<fixfirst>` 替换本机工作目录，日志里的随机会话标识仅作关联。
不把 pip 日志导入计作实际成功验证；验证依赖实际目标检查的退出状态、测试数量和原文件哈希。
Claude 的预登记基线、独立复核及发现的问题位于 `../../field_trial/results/round7-acceptance/`。
