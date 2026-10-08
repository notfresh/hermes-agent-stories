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
- [story-10: yolo 模式是怎么把危险命令审批的"否决权"夺走的——我又怎样把它放回来](./story-10-yolo-mode-原理与代码分布.md)
  yolo = 审批门可旁路开关,3 源任一为真即开;但 floors 是审批链最底下的硬地板,yolo 也踩不破。容器里跑,dangerous 检测会被跳过,deny 是唯一剩下的拦截手段——必须写。
- [story-11: Hermes 一周 2000 commit——我的私有特性怎么活下来](./story-11-keep-a-private-feature-on-top-of-fast-moving-upstream.md)
  主仓狂奔特性留不下:rebase 累计冲突爆雷,patch + 3-way merge 拿祖宗 B 当锚点重打——"特性小、主仓大"是常态不是侥幸。一周一次脚本化,冲突只在特性改的那几行。

## 调研与原理文章

> 从 [mini-hermes](https://github.com/notfresh/mini-hermes) 迁入：那边只做项目总览（v1/v2 最小 Agent），文章沉淀统一在这里。

### agent 原理系列

讲清 Agent 的基本概念与机制。上下文专题已并入本系列。

- [principle-20260901-skill-vs-plugin: Skill vs Plugin——内容与机制的分界线](./principle-20260901-skill-vs-plugin.md)
  skill 与 plugin 的界限不在文件形态，在**加载机制**：skill 是内容（模型按需读取，渐进式披露），plugin 是代码（进程启动时 import 并执行 `register()`）。一句话判据：有没有被 Hermes 进程 import 并执行。
- [principle-20260901-hermes-cwd-mechanism: Hermes 如何记住"当前工作目录"——一个状态，三层存储](./principle-20260901-hermes-cwd-mechanism.md)
  cwd 是"会漂移的工具级状态"，Hermes 用三层存储投影同一值：**内存字典** / **SQLite 列** / **环境变量 `TERMINAL_CWD`**。易变状态分三层：活体 / 档案 / 广播。
- [principle-20260907-self-learning-loop: Agent 如何记住用户教的纠正——Self-Learning 闭环](./principle-20260907-self-learning-loop.md)
  用户的纠正默认是 session 级临时态，关掉就清零；自学习 = 把临时态转成持久态。闭环四要素：触发器 + 取样器 + 蒸馏器 + 落盘器，零记忆模块——靠文件系统做持久化。

### 元认知系列

关于"怎么看代码"，不是"代码做了什么"。

- [什么是架构](./什么是架构.md)
  调研前必读——先问三件事（边界 / 责任分配 / 不变），再谈架构图怎么画。

### 上下文专题（agent 原理系列·子专题）

深攻方向：搜索 / RAG / agent 记忆——上下文工程是 Agent 更加高效的方向。**总纲先行，落地设计随后**。

- [thinking-20260826-lifecycle-based-memory-management: 基于生命周期识别的记忆管理](./thinking-20260826-lifecycle-based-memory-management.md) — 上下文专题·总纲
  核心结论：**频率 + 属性 + 有效期**三个维度决定一条信息放哪、留多久。
- [design-20260826-memory-rule-engine-decision: 记忆分层规则引擎——决策思路复盘](./design-20260826-memory-rule-engine-decision.md) — 总纲的第一块落地
  判断器用规则引擎不用 LLM 黑盒（可审计）；12 条规则 = 45 行代码，YAGNI。
- [analysis-20260826-mem0-core-principles: Mem0 核心原理——把 LLM 当记忆秘书的"写时增改删"](./analysis-20260826-mem0-core-principles.md) — 业界项目剖析第一篇
  对话不存原文，LLM 提取成事实条目，写时对已有记忆做 **ADD/UPDATE/DELETE**。四个可抄的防幻觉细节：UUID→整数映射、hash 去重、原始消息落 SQLite、OSS 版时间能力关闭。
- [analysis-20260826-letta-core-principles: Letta Code——让 agent 自己改自己的记忆](./analysis-20260826-letta-core-principles.md) — 业界项目剖析第二篇
  ⚠️ 仓库事实：`letta-ai/letta` 主分支已只是落地页，**当前实现在 [letta-ai/letta-code](https://github.com/letta-ai/letta-code)**。记忆 = Memory Blocks + 5 个记忆工具，全部 git 跟踪（MemFS）。
- [analysis-20260826-graphiti-core-principles: Graphiti——给知识图谱装上时间轴（Zep 的开源核心）](./analysis-20260826-graphiti-core-principles.md) — 业界项目剖析第三篇
  ⚠️ 仓库事实：Zep 产品 = 托管平台，**开源核心 = [getzep/graphiti](https://github.com/getzep/graphiti)**。EntityEdge 带双时间轴（valid_at / invalid_at / expired_at / reference_time），可"时间旅行"查询。
- [review-20260826-hermes-memory-system: Hermes 记忆系统综述——内置双文件 vs 可插拔外部记忆](./review-20260826-hermes-memory-system.md) — Hermes 自身机制综述
  内置 MemoryStore（MEMORY.md + USER.md，2200+1375 字符上限）+ MemoryProvider ABC（19 钩子）+ **8 个外部记忆插件**。内置对个人助手级够用，升级判据 = 量大上向量检索、要历史上时间轴、要主动进化上自我编辑。
- [analysis-20260826-agent-memory-survey-2026: Agent 记忆 2026 综述导读——三维度框架与六个开放挑战](./analysis-20260826-agent-memory-survey-2026.md) — 学术综述导读
  原文《Rethinking Memory Mechanisms of Foundation Agents in the Second Half: A Survey》（[arXiv:2602.06052](https://arxiv.org/abs/2602.06052)），**三维度框架** × **六开放挑战**。

### hermes 科普系列

把 Hermes 的机制讲成大白话。

- [popular-20260902-hermes-multi-surface: Hermes 的多张脸——一个大脑，四种皮肤](./popular-20260902-hermes-multi-surface.md)
  同一个 `/ss` 在 CLI 打印、TUI 弹窗、飞书回话之谜：大脑（agent core，无界面）与四张脸（CLI/TUI/Desktop/Gateway）分离；会话按 source 盖章隔离。
