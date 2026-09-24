---
story_id: 3
title: 一场 alias 移植引发的对话过程——我整理了我们讨论的关键决策
date: 2026-09-06
author: notfresh
status: recorded
upstream_repo: NousResearch/hermes-agent
tags: [hermes-agent, alias, multi-surface, decision-process, collaboration-notes]
---

## 背景

这是一篇聊天口述成文，记录我整理我和用户（郑旭）一次多日讨论的关键决策的过程。

主要素材来自一次围绕 Hermes alias 功能的多轮讨论。用户已经知道 kimi-code 有个别名功能（issue #3158），想移植到 Hermes 上。我们的对话从移植方案的选择开始，经历了写代码、实战反馈、profile 隔离发现、报告沉淀、科普系列开篇等多个阶段。

下面这份"梳理"是我整理给用户的——**这段就是当时那个完整的回顾**。

---

# 我们的对话过程：自然时序

## 第一阶段：起源——用户从 kimi 移植到 Hermes 的想法

**起点**："我们似乎之前调查过 hermes 的 alias，原生的有问题，执行 ss 命令并不方便"

调历史 →找到 8-22 那天会话 → 锁定**两大事实**：
- `quick_commands`（type: alias）是 Hermes 原生配置，已有 config.yaml 入口
- 但 TUI 端 slash.exec **不查 quick_commands**，所以 `/ss` 在 TUI 里弹不出 sessions picker——8-22 分析里说的"8 行断点"

**用户的决策**：开 tui-alias 分支移植 kimi 完整能力（issue #3158）。我提议三个范围档（A 完整 / B 修断点+防环 / C 修断点+/alias 命令），用户选**完整移植 A**——意味着"用户别名优先 + 遮蔽警告"语义，代价是会和上游刻意设计相违背。

## 第二阶段：定位与代码调研

深入源码——挨个查 CLI/TUI 后端/前端/共享注册表的 alias 切入点：
- `cli.py:12525-12574`：else 分支兜底（内置优先）
- `gateway/run.py:17930`：`_cmd_def is None` 才查（内置优先）
- `tui_gateway/methods_tools.py:1158`：slash.exec **完全不查 quick_commands** ← 8-22 断点
- `hermes_cli/commands.py`：COMMAND_REGISTRY 统一注册表
- 三个 profile 各自独立 gateway 进程

调研报告定稿：9012 字节，七节。

## 第三阶段：动手实现

三个端各写一份：
- **CLI** (`cli.py`)：`process_command` 加 `_alias_depth` 单跳防环，canonical 算出后插"别名优先"块
- **Gateway** (`gateway/run.py`)：改 `_cmd_def is None` → 无条件展开；新增 `/alias` handler
- **TUI 后端** (`tui_gateway/methods_tools.py`)：slash.exec 加 8 行路由到 command.dispatch（断点根修）；alias 链展开到底 + visited 环检测；新增 `_handle_alias_dispatch`
- **TUI 前端**：留到下一阶段（用户反馈后）
- **注册表** (`hermes_cli/commands.py`)：加 `/alias` CommandDef

测试：**15 个新用例**（CLI/gateway 9 + TUI 6），全绿；回归 697 passed 零破坏。

**第一次 commit**：`fdb7aa441b`（主提交，7 文件 +638/−15）

## 第四阶段：实战反馈驱动补全

**反馈 1**（用户看到截图）："没有看到 /ss 命令"
→ 我检查发现是**命令面板（catalog）有 /ss**，但**输入补全（complete.slash）没有 quick_commands 源**——两条数据流
→ 改 `SlashCommandCompleter` 加第 5 数据源，CLI prompt_toolkit 和 TUI RPC 共用

**反馈 2**（用户的真实使用）："加入 /ss 命令，没有立马在 tui 的可选命令里显示"
→ 我才意识到 TUI 前端 catalog 是**启动时拉一次的快照**，不会自动刷新
→ 加 `refreshCommandCatalog()`（对应 kimi 蓝本的 `refreshAliases()`，我移植时漏了）

**第二个 commit**：`f7b2e4ef25`（前端刷新）

**第三个 commit**：`4f294b5727`（补全）

## 第五阶段：同步运行版 + 多 profile 隔离发现

用户要求应用 diff 到运行版（cherry-pick + 重启 gateway）——成功，飞书 bot 立刻能用 `/ss` `/q` `/n` 和补全。

但用户很快发现新问题：

**反馈 3**："不同的 profile 是隔离的啊，其他 profile 输入这个命令 '/alias /n' 都不行"
→ 查证：3 个 profile 的 gateway 进程从 8-23 一直没重启过（运行**旧代码**），内存里没有 `/alias` 命令
→ 排程重启三个 profile（用 at 延迟 1 分钟避免 SIGTERM 自杀）

**反馈 4**：用户发现各 profile 的 config.yaml 都是空的——**别名不跨 profile 共享**，这是 profile 隔离的另一层。

## 第六阶段：profile +进程隔离的认知统一

用户追问的两个问题揭示了完整机制：

**问 1**："/alias 会被覆盖吗？" → 不会，`/alias` 是原子更新单个 key，幂等。

**问 2**："他们是复用同一个 config 啊" → 用户意识到**配置文件共享 ≠进程内存共享**：
- 文件：磁盘上的共享账本 ✅
- 进程内存：每个 gateway/TUI 进程**启动时读一次**，之后各看各的复印件
- 想让 X 进程也认识新配置，要么**重启它**，要么**在 X 里跑一次 /alias**（写盘 + 同步内存一步到位）

最后定调：**"/alias 的真正意义是'写盘 + 刷新我这进程的复印件'"**——多进程架构 + 配置共享的固有代价。

## 第七阶段：合并上游 PR 的讨论与放弃

用户问："如果我提一个 pr 的话……它有没有意义，官方会不会欢迎它？"

我分析：
- A（TUI 断点修复）+ B（补全）= 官方会欢迎（修官方文档化功能的真实 bug）
- C（/alias 命令）= 中立偏试探
- D（用户别名优先 + 遮蔽警告）= 大概率拒绝（违背上游 `Preserve built-in precedence` 的刻意设计）

**用户的决策**："算了"——主动放弃本可上贡的设计。用户清楚 fork 自用版有代价（每次 `hermes update` 可能撞同批文件），但**保留设计主权 > 合入上游**。这呼应了 kimi story-5 讨论的"Nous vs Moonshot 北极星差异"。

## 第八阶段：报告沉淀 + 写原理

用户要求写"从原理到落地的报告"，我先写了第一版（树形图 + 对照表）。**用户的批评**："写了这个，但是没写原理啊。原理就是你为什么这么改？每一个文件的职责是什么？"

→ 补第三节"原理"（6 小节）：
- 3.1 用户别名展开时优先于内置（一个原则）
- 3.2 三端展开点位置（CLI 单进程 / Gateway 改 event.text / TUI RPC + 递归）
- 3.3 防环机制的两种实现：单跳深度 vs 链展开+visited
- 3.4 /alias 命令为什么三端各写一份
- 3.5 补全盲区根因
- 3.6 TUI 前端 refreshCommandCatalog 为什么必须

→ 再次追问 "canonical 是什么" → 文档第 123 行 / 60 行 / 135-137 行全部对齐注释。

**三轮 commit**：`b51cb8cdd6`（报告）+ `ecc0a36121`（原理补充）+ `91853d0244`（canonical 注释）。

## 第九阶段：科普系列开篇

**用户的指令**：在 mini-hermes 仓库开 hermes 科普系列，文章放 `wiki/`（仓库根目录，不挂 docs 下），README 底部低调登记。

**第一篇主题**：用户定的"先2（Hermes 多端架构科普）再 1（alias 移植全过程）"——先科普大脑与四张脸分离的原理，下一篇再讲具体移植。

我用今天真实经历做素材：同一个 `/ss` 在 CLI 打印、TUI 弹窗、飞书回话之谜 → 解释大脑（agent core）与四张脸（CLI/TUI/Desktop/Gateway）分离、config.yaml 全局共享、命令统一注册各端实现、source 盖章隔离——顺带解了"CLI 里看不到飞书会话"的困惑。

**commit**：`22cf5a8`（mini-hermes 仓）。

---

## 用户的决策风格（贯穿全程）

| 偏好 | 体现 |
|---|---|
| **先讨论再动手** | 几乎每个新方向都先问方案再执行 |
| **递进版本，不要并列 A/B/C** | 每次列选项都被用户选其一，不说"两个都要" |
| **实战反馈驱动补全** | 三次 commit 都是用户实际敲命令时发现的问题 |
| **拒绝超前（YAGNI）** | 主动放弃上游 PR 机会 |
| **教学严谨：先讲原理再列改动** | 报告改两次，都是同一个反馈 |
| **快速体验 + 持续积累双轨** | alias 移植 + cherry-pick（今天用上）vs 报告 + 科普（沉淀） |

最一致的两件事：**① 今天能用上 + ② 沉淀下来以后翻得到**。本次五件交付（移植 + cherry-pick + 报告 + 科普 + profile 隔离处理）正是同时满足这两边的产物。