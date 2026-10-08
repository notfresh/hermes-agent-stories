# Letta Code：让 agent 自己改自己的记忆（Stateful Agent Harness）

> 2026-08-26 · 上下文专题 · 业界项目剖析（第二篇）
> 剖析对象：[letta-ai/letta](https://github.com/letta-ai/letta) → 当前实现 [letta-ai/letta-code](https://github.com/letta-ai/letta-code)（Apache-2.0）
> 本地源码：`/root/projects/letta-code/`（浅克隆，所有行号实测自该副本）
> 与专题主线的连接：**"agent 自我编辑记忆"路线的代表**——记忆是文件，agent 用工具直接改，全程 git 版本化。

---

## 〇、先说一个仓库事实（不搞清楚会看错项目）

`letta-ai/letta`（24.4k stars）主分支现在**只是落地页**：

- **V1 已退役**：旧的 Python server 实现归档在 `archive` 分支，官方明令"仅供历史参考，禁止用于任何新应用/基准/对比"
- **当前实现在 `letta-ai/letta-code`**（3.1k stars，2025-10 起）：TypeScript/Bun 项目，Node 22.19+，npm 包 `@letta-ai/letta-code`
- 历史渊源：Letta 前身是 **MemGPT**（"把 LLM 上下文当操作系统内存，分页换页"的论文项目，2023）；V1 是那条思想的产品化；letta-code 是 2025 年重写后的版本——**"分页"思路淡出，取而代之的是"记忆块 + 自我编辑 + git 版本化"**

一句话定位：**Stateful agent harness（有状态的 agent 运行框架）——agent 有记忆、有身份、有随时间累积的经验，能通过改写自己的记忆/技能/提示词来进化。**

## 一、记忆形态：Memory Blocks（记忆块）——可编辑的系统提示词

Letta 的记忆不是数据库里的事实条目，是**一组常驻上下文的文本块**：

```ts
// src/agent/memory.ts:32 —— 每个标准 agent 的默认块
export const MEMORY_BLOCK_LABELS = ["persona", "human"] as const;
```

- `persona`：agent 的自我认知（我是谁、我擅长什么、我的行为准则）
- `human`：agent 对用户的了解（用户偏好、事实、关系）
- 每个块是 `{label, value, description?, read_only?}`（`CreateBlock`），初始内容从 `src/agent/prompts/*.mdx` 加载（`memory.ts:57`）
- **关键**：这些块直接拼进系统提示词——记忆不是"查的时候才想起来"，是**每轮都在上下文里**（记忆 = 提示词的一部分，这也是"上下文工程"字面意义的实现）

## 二、写路径：5 个记忆工具——agent 自己在对话里改记忆

`src/tools/toolset.ts:65-71` 定义了全部记忆编辑工具：

```ts
export const MEMORY_TOOL_NAMES = new Set([
  "memory",               // 通用记忆读写
  "memory_apply_patch",   // 对记忆文件打 patch（add/update/delete hunks）
  "memory_insert",        // 插入新记忆（MemGPT 遗产）
  "memory_replace",       // 替换旧记忆（MemGPT 遗产）
  "memory_rethink",       // 反思重写记忆
]);
```

**和 Mem0 的本质区别**：Mem0 是系统在 `add()` 时让 LLM 提取事实；Letta 是 **agent 在对话中主动调用工具编辑自己的记忆**——改不改、怎么改，是 agent 的决策，不是后台管道。

主力工具 `memory_apply_patch`（`src/tools/impl/memory-apply-patch.ts`）：对记忆文件做三类操作（`add` / `update` / `delete`，git patch 风格的 hunks），每次写入都走 `commitMemoryWrite`——**每次记忆修改就是一次 git commit**。

## 三、MemFS：记忆即代码，全部上下文 git 跟踪

```
MEMORY_FS_ROOT = ".letta"            // src/agent/memory-filesystem.ts:26
  ├── agents/                        // 每个 agent 一个目录
  ├── memory/                        // 记忆块文件
  └── system/                        // 系统级配置
```

- 所有上下文（记忆块、技能、提示词、agent 配置）都是**文件**，整个目录是 git 仓库
- `/memory-repository set git@github.com:...` 可把记忆同步到**私人 GitHub 仓库**——记忆跟代码一样可版本回滚、可异地同步
- 记忆树可视化（`/memory/` 目录树，`memory-filesystem.ts:344`）+ `/palace` 查看记忆、`/doctor` 审计记忆质量

## 四、读路径：记忆常驻 + 跨会话搜索

- **常驻**：persona/human 块每轮在上下文（记忆 ≈ 提示词，天然"想起"）
- **`/search`**：跨所有消息和 agent 全文搜索历史（`/search` slash 命令）
- **recall 子代理**：内置子代理之一，专门回忆历史对话（`src/agent/subagents/builtin/`）
- 另有 history-analyzer 子代理做长历史分析

## 五、Dreaming（做梦）：定期反思机制

`/sleeptime` 命令配置 periodic dreaming（`src/cli/app/use-configuration-handlers.ts:1014-1056`，事件类型 `set_sleeptime`）：

- 配置 reflection settings（`src/reflection-settings.ts`），agent **定期在后台"做梦"反思**自己的记忆/技能是否需要更新
- 反思由内置 reflection 子代理执行（`src/agent/subagents/builtin/reflection.md`）
- 与 Hermes 的 background review（每 10 轮 fork 反思 agent）**同构**——"定期后台自我审查"是 agent 自我改进的标准形态

## 六、三个关键设计决策（为什么）

**① 为什么记忆是文件 + git，而不是数据库？**
版本化白送：每次记忆修改可 diff、可回滚、可审计（git log 就是记忆变更史）；可同步 GitHub（记忆跟着仓库走）；天然可移植（换机器 = clone 仓库）。代价：不是为检索设计的存储，跨海量记忆检索弱。

**② 为什么 agent 自我编辑，而不是系统提取？**
Mem0 的问题是"系统猜什么重要"；Letta 让 **agent 自己判断什么值得记**——记忆决策发生在对话内（agent 说"这个值得记"然后调工具），可被用户看到、纠正。这是"主体性"的业界极致：记忆不是被动的产物，是 agent 主动行为。

**③ 为什么记忆常驻上下文，而不是 RAG 按需检索？**
persona/human 块小（几十行），常驻成本低，换来"身份和用户偏好永远在线"；体量大、不常用的才走搜索/子代理。这是"舞台角色"的工程实现——主角常驻，配角检索（对应总纲的仿生调度）。

## 七、与专题主线的对照

**Letta 的自我编辑 = 你四维模型的第④维（Agent 主动探测/标记）的业界极致**。你在 8-20 的框架讨论里设想过"agent 主动发现任务是否重要"——Letta 把它做成了产品核心：agent 不仅探测，还直接动手改。

| 维度 | Mem0（LLM 主判） | Letta（agent 自我编辑） |
|---|---|---|
| 谁决定记什么 | 系统 add() 时 LLM 提取 | agent 对话中主动调工具 |
| 记忆形态 | 事实条目（向量库） | 文本块（文件 + git） |
| 审计 | ❌ 无 | ✅ 文件级 git 历史 |
| 可解释 | ❌ 黑盒 | ⚠️ git 有"改了什么"，无"为什么改" |
| 生命周期 | 无分层 | ⚠️ 靠 dreaming 定期反思（后验），无 TTL 先验 |

**对照结论**：Letta 补上了 Mem0 缺的"审计"（git）和"主体性"（agent 自己改），但"为什么改"仍是 LLM 隐式判断——它没有规则引擎那层"宪法"；生命周期靠 dreaming 事后反思，没有先验 TTL。你的设计 = 规则主判（可解释）+ 提取/编辑能力（吸收两家的主体性）。

## 八、源码导航

```
src/agent/memory.ts                  记忆块加载（persona/human 默认块）
src/agent/memory-filesystem.ts       MemFS（.letta 目录 + 记忆树）
src/agent/memory-git.ts              git 提交/同步（commitMemoryWrite）
src/tools/toolset.ts:65-71           5 个记忆工具名
src/tools/impl/memory-apply-patch.ts 记忆 patch 工具实现（add/update/delete）
src/agent/context.ts                 上下文组装（记忆块注入）
src/reflection-settings.ts           dreaming 配置
src/agent/subagents/builtin/reflection.md 反思子代理
src/agent/subagents/builtin/         内置子代理（recall / history-analyzer 等）
```

阅读顺序：memory.ts（记忆形态）→ toolset.ts 记忆工具 → memory-apply-patch.ts（编辑机制）→ memory-filesystem.ts（MemFS）→ context.ts（怎么进上下文）。

---

*本文行号基线：`/root/projects/letta-code/` 浅克隆副本（2026-08-26）。仓库演进后行号可能漂移。*
