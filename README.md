# 动画派对 · 动态Emoji猜动画

AstrBot插件 astrbot_plugin_anime_party_33989，版本0.2.0。

每次开局、下一题或切换难度都现场生成新题。题面固定三行，分别5、7、5个完整Emoji，以空格分隔。没有内置默认题库，不会在生成失败时拿旧题或固定题补位。

## 安装

1. 从 https://github.com/aryuu-git/astrbot_plugin_anime_party_33989 安装，或使用Release ZIP。Python>=3.11，AstrBot>=4.28.0,<5，当前支持声明为OneBot V11(aiocqhttp)。
2. 安装requirements.txt中的emoji依赖，在allowed_sessions填入 /sid 得到的会话标识；默认空列表不响应。
3. 配置支持工具外普通文本生成的聊天模型；留空provider_id时沿用当前会话模型。模型服务需要可用额度，动态生成会产生用量。
4. 确保能访问Bangumi公开API，必要时设置generation_proxy。此功能只读公开条目，不要求Bangumi账号或Token。
5. 发 /猜动画 开始。

## 怎么玩

- /猜动画 开始：编一道新题，默认普通难度。
- 活动题目中直接说“提示”“提示一下”“答案”“下一题”“暂停”。
- 作答用“我猜 动画名”；也可直接发送已核对的当前作品名称或原名。
- /猜动画 难度 简单（或普通、困难）：按难度重新生成。
- /猜动画 状态：显示题面和提示进度，不显示答案。
- /猜动画 清空：仅管理员可清空当前会话进度。

初次生成需要选题、作品身份核对和格式检查，会先发送一次等待说明。整轮默认超时120秒；出题失败会明确说明，普通聊天仍放行，不回退到固定题。

游戏开始后答案和三层提示固定，继续由状态机判题，不让聊天模型临时更改。生成器参考Bangumi名称与简介，但资料可能不完整，模型编写的图标线索和说明仍可能有歧义，欢迎反馈。

## 5／7／5校验

rows必须是三行数组，长度分别为5、7、5。每个元素用Unicode Emoji库校验为一个完整Emoji；家庭组合、肤色和旗帜可为一个格子，相邻两个独立Emoji不能塞进同一格。仅检查Python字符串长度或空格个数是不够的。

## 运行数据与升级

生成题仅保存在本实例plugin_data/astrbot_plugin_anime_party_33989/dynamic-game.db中，用于当前局恢复和近期避重；不会把历史生成题随机当作新题复用，不记录玩家聊天正文。旧版game.db和自定义固定题包不再加载。升级到0.2.0会开始独立动态游戏进度，旧活动局不继续使用；维护前备份旧数据。

近期12道生成作品会进入避重名单。不同会话的游戏状态隔离；生成失败不改写当前已生成的活动题。消息ID去重和状态变更由SQLite事务处理，平台发送仍可能受断线影响。

## AI表达与权限

独立出题调用使用模型生成并冻结谜题，可以接触来源资料；普通聊天及可选主持润色不会获得隐藏答案。可选ai_expression仍默认关闭，游戏本身的动态出题始终需要模型。群会话允许列表与AstrBot全局白名单分别生效。

## 开发与发布

```text
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
python scripts/build_release.py
```

[生成规则](docs/question-packs.md) · [架构](docs/architecture.md) · [发布验收](docs/release.md)。代码采用MIT许可。源码历史中可能保留旧版本题包，但当前运行与发布ZIP不包含它。
