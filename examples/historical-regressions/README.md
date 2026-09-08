# 官方历史缺陷的最小复现

先看 `REPORT.md`。每例的 `project/test_regression.py` 是依据上游缺陷编写的最小复现；被测库本身使用未修改的官方 wheel。`01-broken` 与 `02-fixed` 各提供 HTML、session JSON 和图谱 JSON，`setup.json` 保存环境创建与离线安装记录。

`results.json` 记录上游修复提交、观察到的版本、退出码、测试源码 SHA256 以及是否完成失败与恢复。`evaluation.json` 是固定旧 Gini 模型的四例评价，未重新训练。`packaging-full-version/03-model-disagreement.html` 在同一故障记录上展示模型与规则的分歧，不是新增一次运行。

`assets/manifest.json` 列出来自 PyPI 的固定 wheel 下载地址、SHA256、大小和许可证文件。9 份 wheel 包括 Packaging / Click 的故障与修复版本及固定测试依赖；完整保留各自原许可证，**不适用原受控 fixture 的 CC0 声明**。

运行根 README 中的 `fixfirst historical --assets ... --output ...` 可离线复算，输出目录必须是新目录。分享副本中的路径已替换，请用复现命令重建自己的环境，不要直接执行脱敏后的历史 argv。
