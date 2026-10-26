# 0.2.0 发布与验收

这是移除固定题库的动态模式升级，仍作为预发布。代码和ZIP均不包含旧默认题库，旧缓存不能用于补题。

测试覆盖Unicode组合Emoji、5/7/5行列数、错误数量、相邻两个Emoji、片名泄露、失败重试、来源核对、缓存恢复、无缓存回退、消息重复与普通聊天放行。实际模型调用、Bangumi网络和QQ连接应另作现场验证，不把假网络测试称为端到端。

升级前备份原game.db；新版本使用独立dynamic-game.db，不加载旧局。allowed_sessions和现有聊天模型配置保留；question_source旧设置不再生效。生成器需要模型额度和可用的Bangumi公开API网络。

发布包由scripts/build_release.py显式允许列表构建，检查无默认题库、数据库、凭据、测试样例和运行时。源码中的tests/fixtures只有虚构测试数据，不会进入发布ZIP或运行时加载。

AstrBot官方市场尚未提交，用户可通过GitHub仓库或Release ZIP安装。
