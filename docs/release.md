# 发布与验收

版本：0.1.0。源码与安装包发布以[GitHub仓库](https://github.com/aryuu-git/astrbot_plugin_anime_party_33989)为准；AstrBot官方插件市场尚未提交。

## 已验证（2026-10-26，Asia/Shanghai）

- 32项领域与适配行为测试通过；Python 3.12和3.14均已运行。
- Ruff代码检查通过。
- AstrBot 4.29.3真实模块导入与所需API检查通过。
- 使用真实AstrBot事件对象和插件处理阶段验证：游戏产生一份结果并阻止后续聊天处理器，普通聊天放行。验证不发送真实QQ消息。
- 已在AstrBot4.29.3云端加载：启动日志确认30道题与实例允许会话。智谱真实主持引子生成通过，QQ实际游戏送达仍待体验。
- 当前还需真实群体验验收；平台发送、跨版本与长期运行表现不由模拟测试保证。

## 发布前检查

1. 运行领域与适配测试；目标AstrBot真实导入/加载、QQ连接和实际群玩法验证分开记录。
2. 检查普通聊天放行、已消费事件无双回复、两个会话独立、重启续局、模型关闭/超时降级。
3. 检查ZIP只包含允许文件，大小小于16MiB，没有真实账号配置、数据库、日志、环境和运行时。
4. 核对metadata版本、仓库地址、支持平台与Python版本；无测试证据的平台不宣称已适配。
5. 创建公开仓库并推送经审查源码；确认仓库URL实际可用后按[官方发布流程](https://docs.astrbot.app/dev/star/plugin-publish.html)提交AstrBot Cloud。

```powershell
python -m unittest discover -s tests -v
python scripts/build_release.py
```

## 云端试用

仅把发布包解压到插件目录，为Owner已有私聊/测试群写入单独的allowed_sessions；不要把这些ID写进公开包。备份新增配置与相关联动插件，然后重启/重载AstrBot并检查日志。

固定文案和AI主持分别验证；自动测试不向真实群发虚构消息、答案或重启续局请求。真实群体验由明确的游戏请求开始。

本页随实际验收补充结果，不能把测试用假框架称为完整AstrBot端到端验收。
