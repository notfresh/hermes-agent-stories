# Hermes 记忆系统综述：内置双文件 vs 可插拔外部记忆

> 2026-08-26 · 上下文专题 · Hermes 自身机制综述
> 源码：`/root/projects/hermes-agent-plus/`（研究副本，所有行号实测）
> 姊妹篇：业界剖析三篇（Mem0 / Letta / Graphiti）——本文回答"Hermes 自己是怎么做的"，文末对照
> 配套字典：《hermes-skill-memory-data-structures.md》（001study，数据结构级）

---

## 一、一句话定位

> **Hermes 的记忆系统 = 内置有界双文件（MEMORY.md + USER.md）+ 可插拔外部记忆插件**，通过 MemoryProvider 抽象接口连接，由 MemoryManager 统一编排——内置 provider 永远在，外部 provider 最多挂一个。

- 内置：`MemoryStore`（tools/memory_tool.py:113）——**有限长度文本文件**，就是你说的 memory.md + user.md
- 外部：8 个插件（plugins/memory/），通过 config.yaml 的 `memory.provider` 选一个激活
- 架构哲学：**核心窄腰，能力在边缘**——内置的永远是那个 2200 字符的小本子，要更强的记忆（向量/图/云服务）就插插件

## 二、内置记忆：MemoryStore —— 有界、双状态、防投毒

### 形态：两个有界文本文件

```
MEMORY.md   ← agent 自己的笔记（memory_entries）
USER.md     ← 用户画像（user_entries）
```

- 容量上限：**memory 2200 字符（≈800 tokens）+ user 1375 字符（≈500 tokens）**（memory_tool.py:130，config.py:2295 可配）
- 单个 `memory` 工具读写，action = `add` / `replace` / `remove` / `batch`，target = `memory` / `user`（memory_tool.py:20）
- 写满时提示合并（replace 合并重叠条目），合并失败计数，`_MAX_CONSOLIDATION_FAILURES_PER_TURN = 3` 后返回 TERMINAL——**记忆写不进不能阻塞回合回复**（:128）

### 双状态设计（关键中的关键）

```
_system_prompt_snapshot  ← 会话开始时冻结的快照 → 进系统提示词（永不中途改）
memory_entries / user_entries ← 实时状态 → 工具调用修改 → 落盘
```

- 系统提示词里的记忆是**冻结快照**，只在下次会话开始刷新——**prompt caching 神圣不可破**（AGENTS.md 第一铁律）
- 工具响应始终反映实时状态，模型看到"我改成了什么"，系统提示词里还是旧快照——两套并行的设计，互不干扰

### 防投毒（这个设计值得抄）

`load_from_disk` 构建快照时**逐条扫描注入模式**（promptware）：命中就把该条替换成占位符（memory_tool.py:168-198）。"记忆文件里被塞了'忽略以上指令'之类的恶意文本"——注入发生在文件层，快照层直接屏蔽，且模型还能通过 memory 工具看到原始内容自己判断。

## 三、记忆全生命周期（一个回合内）

```
回合开始
  → ① MemoryManager.prefetch_all(user_message)     同步预取（memory_manager.py:515）
  →    queue_prefetch_all()                         外部 provider 异步线程预取（:587）
  → ② build_memory_context_block() 注入：
       <memory-context>
       [System note: 这是召回的记忆上下文，NOT 新的用户输入……]
       （memory_manager.py:345）
  → ③ 流式输出时 StreamingContextScrubber 清洗跨 chunk 的标签（:173）
  → ④ 对话中模型调 memory 工具 → MemoryStore.handle_tool_call（add/replace/remove）
  → ⑤ 每 10 轮（_memory_nudge_interval，agent_init.py:1427，可配）：
       fork 后台审查 agent，_MEMORY_REVIEW_PROMPT（background_review.py:170）
       重放会话，判断"用户透露了什么值得记" → 调 memory 工具写入
  → ⑥ 会话切换/结束：on_turn_start / on_session_end / on_session_switch 钩子
```

注意 ⑤：**Hermes 的"记什么"是后台反思 agent 判的**（每 10 轮一次，回复送达后 fork，不挡对话）——这和 Mem0 的"add 时提取"是两种时机，但都是 LLM 主判、不可审计。你 8-26 的规则引擎设计正是要补这一层。

## 四、可插拔架构：MemoryProvider ABC + MemoryManager

### MemoryProvider（agent/memory_provider.py:43）——19 个钩子的契约

```
name / is_available / initialize       身份与生命周期
system_prompt_block / prefetch /       注入与检索
  queue_prefetch / sync_turn
get_tool_schemas / handle_tool_call    工具面（外部 provider 可暴露自己的工具）
on_turn_start / on_session_end /       会话钩子
  on_session_switch / on_pre_compress  压缩钩子（记忆在上下文压缩中的处理）
on_delegation                          子代理记忆
get_config_schema / save_config        配置（插件自带配置 UI）
on_memory_write                        感知内置记忆写入
backup_paths                           备份清单
```

### MemoryManager（agent/memory_manager.py:355）——编排规则

- **内置 provider 永远第一个**；外部 provider **最多一个**（再注册直接拒绝，:398-416）
- 失败隔离：一个 provider 出错不阻塞另一个（"Failures in one provider never block the other"）
- 外部预取走独立线程 + 超时（external_prefetch_timeout）

### 插件发现机制（plugins/memory/__init__.py）

```
扫描两个目录：
  ① bundled：plugins/memory/<name>/（随 Hermes 发布）
  ② 用户安装：$HERMES_HOME/plugins/<name>/
每个目录的 __init__.py 里必须有实现 MemoryProvider ABC 的类
同名冲突 → bundled 优先
接口：discover_memory_providers() → load_memory_provider(name)
```

## 五、外部插件生态：8 个记忆插件

| 插件 | 定位 | 来源 |
|---|---|---|
| **honcho** | Honcho AI-native memory（云服务，含 oauth_flow） | 内置 |
| **mem0** | 就是咱们剖析的 Mem0！走 HTTP 连 Mem0 server | PR #2933 kartik-mem0 |
| **holographic** | 结构化事实存储（holographic memory） | PR #2351 dusterbloom |
| **hindsight** | "后见之明"记忆（事后反思提取） | PR #1811 benfrank241 |
| **supermemory** | Supermemory 服务 | 内置 |
| **byterover** | ByteRover 记忆服务 | PR #3499 hieuntg81 |
| **openviking** | 全双向记忆（读+写都通） | 内置 |
| **retaindb** | RetainDB 记忆服务 | 内置 |

另有公共模块：query_rewrite.py（查询改写）、config_schema.py。

## 六、配置方式（config.yaml 的 memory 段）

```yaml
memory:
  memory_enabled: true        # 启用内置笔记（agent_init.py:1432）
  user_profile_enabled: true  # 启用用户画像
  memory_char_limit: 2200     # 笔记上限（≈800 tokens）
  user_char_limit: 1375       # 画像上限（≈500 tokens）
  nudge_interval: 10          # 后台反思间隔（每 N 轮）
  provider: ""                # 外部插件名，空 = 仅内置（config.py:2297）
```

## 七、与业界三项目的对照（本文增值点）

| 维度 | **Hermes 内置** | Mem0 | Letta | Graphiti |
|---|---|---|---|---|
| 记忆形态 | 两个有界文本文件 | 提取的事实条目 | 记忆块文件 + git | 实体-关系图（时间轴） |
| 容量 | 2200+1375 字符 | 向量库（大） | 文件 + git（大） | 图（大） |
| 判定主体 | 后台反思 LLM | add 时 LLM | agent 自我编辑 | LLM 增量提取 |
| 可审计 | ❌（有防投毒扫描） | ❌ | ✅ git 文件级 | ✅ episode 引用链 |
| 时间维度 | ❌ | ❌ | 弱 | ✅ 双时间轴 |
| 关系推理 | ❌ | 弱 | 弱 | ✅ 强 |
| 部署成本 | 零（俩文件） | 中（向量库+LLM） | 中（Node 运行时） | 重（Neo4j/FalkorDB） |

**Hermes 内置的三个独有优势**：
1. **有界 = 强制蒸馏**：写满必须合并——容量限制本身就是"什么值得留"的过滤器（变相 TTL）
2. **防投毒 + 冻结快照**：注入防护 + prompt caching 稳定，工程细节最扎实
3. **零依赖**：个人助手级记忆（一个人的偏好/身份），800+500 tokens 存骨架完全够

**内置的三个结构性短板**（对应升级路径）：
1. 无检索：记忆全量常驻，超过容量只能合并删除——量大时该上 Mem0 式向量检索
2. 无时间：记不住"什么时候说的"——需要历史时上 Graphiti 式时间轴
3. 被动：判定靠后台反思，agent 不能主动改——要"主体性"时上 Letta 式自我编辑

## 八、结论：你的判断对吗？

**对**——"内置双文件对个人用户助手级别够用"成立，理由：记忆量级小（个人偏好/身份骨架）、有界倒逼蒸馏、零成本零依赖、防投毒工程细节到位。

**升级判据**（任一出现再考虑外部插件，YAGNI）：
1. 记忆量到几千条、全量常驻塞不下 → mem0 / holographic（向量检索）
2. 需要"当时的事实"（时间查询）或关系推理 → graphiti（图 + 时间轴）
3. 需要 agent 主动进化、跨设备共享记忆 → letta / honcho（云服务）
4. 需要多 agent 共享记忆 → honcho（AI-native 会话记忆）

**架构评价**：19 钩子 ABC + 单外部 provider + 失败隔离 + 插件自带配置 schema——这是"核心窄腰、能力在边缘"的教科书实现。外部记忆不是二等公民，是走同一契约的插拔件。你以后给自己的框架加记忆系统，直接照这个 ABC 画接口就行。

---

## 附：源码导航

```
tools/memory_tool.py                内置 MemoryStore（:113）+ memory 工具 + 防投毒（:168）
agent/memory_provider.py            外部记忆 ABC，19 钩子（:43）
agent/memory_manager.py             编排：prefetch/注入/分发/失败隔离（:355）
plugins/memory/__init__.py          插件发现 + 加载
plugins/memory/<name>/              8 个外部插件（honcho/mem0/holographic/...）
agent/background_review.py          后台反思（_MEMORY_REVIEW_PROMPT :170）
agent/agent_init.py                 记忆初始化 + nudge 配置（:1427-1445）
hermes_cli/config.py                默认值（memory_char_limit 2200，:2295）
```

阅读顺序：memory_tool.py（内置怎么存）→ memory_manager.py（怎么编排）→ memory_provider.py（接口契约）→ plugins/memory/（外部怎么挂）→ background_review.py（怎么学）。

---

*本文行号基线：`/root/projects/hermes-agent-plus/` 研究副本（2026-08-26）。仓库演进后行号可能漂移。*
