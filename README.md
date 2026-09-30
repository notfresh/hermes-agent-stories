# Hermes-Agent-Stories

关于 Hermes Agent 的故事与思考。

## story 列表

- [story-1: 智能体记忆——一场以自身为样本的逆向工程](./story-1-agent-memory-reverse-engineering-from-self.md)
  从"自己怎么记住一个项目"出发，反推智能体记忆系统的设计原则。
- [story-2: 被放弃的融入终端的特性](./story-2-被放弃的融入终端的特性.md)
  关于 `feature-zx` 分支 21 个提交的事后复盘：从"逐字对齐既有契约"的设计野心，到"低频特性不该为融入而融入"的领悟。
- [story-3: 一场 alias 移植引发的对话过程——我整理了我们讨论的关键决策](./story-3-alias-port-decision-process.md)
  九阶段自然时序回顾：起源 → 代码调研 → 动手实现 → 实战反馈 → 同步运行版 → profile 隔离 → 上游 PR 讨论与放弃 → 报告沉淀 → 科普系列开篇；末尾附决策风格表。
- [story-4: Hermes 简史——一个开源项目如何从 7 个文件长成一座城](./story-4-hermes-history.md)
  从 `NousResearch/hermes-agent` 的 21,384 次提交里读出的项目成长史。
- [story-5: 一条原则打破了我对「ABC + orchestrator」的想象](./story-5-abc-orchestrator-extension-mode.md)
  跳进源码看一条图谱原则，发现「ABC + orchestrator + 内置 provider」不是铁三角——它只是 MemoryProvider 这一家的做法。
- [story-7: How do I build an agent？——我为什么做、又怎么做自己的 coding agent](./story-7-how-i-built-my-own-coding-agent.md)
  从"读不懂 Hermes 的防御机制"出发，决定自己写一个——把 Hermes 蒸馏一遍，剥掉枝蔓，只留骨架。
- [story-8: 一行命令分清 skill 三种出身——我以为很简单，结果卡了我三轮](./story-8-how-to-tell-auto-learned-skills-from-builtin-and-external.md)
  两个账本交叉判定：`.bundled_manifest` 白名单 = 内置，`.curator_ledger.jsonl` 里 `actor=agent` = 外部装、`actor=curator` = 自动学习。
- [story-9: 一个软链接加 8 行 SKILL.md——我怎么用最小的代价记住一个项目](./story-9-softlink-short-skill-pattern.md)
  把"指代成本"和"触发语义"拆开：软链接给人记路径，短 skill 给 Hermes 路由，详细约定按需查项目自带文档——每次上下文只花该花的 token。