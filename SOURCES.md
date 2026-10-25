# 来源与许可

## 原始自有项目

本插件经Owner授权从 aryuu-git/Apeiria 的动画游戏能力独立整理，原项目基线commit：`dde3f6d0f1b0928134ad424d2115369879529829`。提取时原工作区可能包含未提交变更，此hash只标识仓库基线，不宣称每个工作文件均与该commit一致。

- game/engine.py、models.py、catalog.py、presentation.py：由原 `packages/anime-party/src/anime_party` 提取并修改。
- game/types.py：提取必要消息与状态接口，消除apeiria-core工作区依赖。
- 其余适配、事务服务、AI引子约束、测试和独立打包为本次整理实现。
- 不包含AstrBot/NapCat运行时、Apeiria人格资产、私有配置或数据库。

代码与本仓库自编题面使用仓库MIT许可。保留作品名称、别名及外部标识的事实引用，不主张对动画作品本身的权利。

## 题库

30道初始题面来自同一Owner维护的Apeiria题包；subject_id是Bangumi条目标识，既有记录注明已对照2026-09-08快照核对。本次未下载或再分发Bangumi Archive，不包含原始简介、封面或音视频文件。

维护者应人工检查提示准确度、别名和内容范围。历史核对不是持续在线验证；用户自行导入的题包应自行说明来源与许可。

## 外部运行框架

AstrBot通过公开插件接口作为外部运行时使用，不在此发布包内分发或修改其核心。AstrBot自身许可、商标和生态发布要求由其项目维护。
