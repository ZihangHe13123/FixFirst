# 官方历史回归复现

每例在新建独立环境中切换官方 wheel；测试源码保持不变。安装全程离线，来源及 SHA256 见配套 assets/manifest.json。

| 案例 | 版本变化 | 失败 → 恢复退出码 | 结果 |
|---|---|---|---|
| [预发布版本被错误排除](https://github.com/pypa/packaging/issues/788) | 24.1 → 24.2 | 1 → 0 | reproduced |
| [未打标签的 Python 版本令条件判断异常](https://github.com/pypa/packaging/issues/678) | 24.1 → 24.2 | 1 → 0 | reproduced |
| [命令帮助漏掉空字符串默认值](https://github.com/pallets/click/issues/2500) | 8.1.7 → 8.1.8 | 1 → 0 | reproduced |
| [命令帮助展示错误的配置默认值](https://github.com/pallets/click/issues/2632) | 8.1.7 → 8.1.8 | 1 → 0 | reproduced |

这些是指定第三方库历史缺陷的最小复现，不代表独立完整项目数量、故障分布或开发者耗时。该复现知道修复版本；日常产品不会据此猜测其他错误的正确版本。没有用这些案例训练模型。
