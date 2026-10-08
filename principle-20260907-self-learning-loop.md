# Agent 如何记住用户教的纠正：Self-Learning 闭环

> agent 原理系列·第三篇（机制讲解，不做源码逐行分析）。
> 案例 = `minimal-agent-v2-self-learning` 分支（仓库：`mini-hermes-v2`，`self-learning` 分支于 2026-08-21 从 main 开）。

## 一句话

**自学习的本质 = 把临时内存里的"用户纠正"转存进持久化的操作手册（SKILL.md），下次同类任务自动可用。**

不转存，每条纠正只在当时那一次会话有效；会话关掉就清零。

## 为什么需要这个机制

先看一个事实：用户在对话里教过 agent 的事，下次同类任务会不会重复犯错，取决于 agent 有没有把纠正"留下来"。

| 不留（默认行为） | 留（自学习） |
|---|---|
| 用户纠正一次"以后别用 markdown 表格" | 同上 |
| 该次会话立即生效 | 该次会话立即生效 |
| 关掉会话 = 纠正跟着对话历史一起清零 | 纠正被写到 `~/.minimal-agent-v2/skills/<name>/SKILL.md` |
| 下次同类任务又用 markdown 表格 → 再被纠正一次 | 下次启动技能索引自动包含它 → 模型按需加载 → 不再犯 |

"自学习"在这条对比里只多做了一步：把临时态转成持久态。这一步是整个机制的杠杆点。

## 闭环四要素（用真实代码位置标注）

下面四个齿轮每一步都在 `minimal-agent-v2-self-learning` 里有具体代码，不是抽象描述。

```
对话 → 触发 → 取样 → 蒸馏 → 落盘 → 下次可用
```

### 1. 触发器（计数触发）

**位置**：`session_manager.py:317-320`

```python
if learner is not None:
    turn_count += 1
    learned = learner.maybe_learn(turn_count, session.messages)
    if learned:
        print(f"🧠 已学习到技能 [{learned['name']}] → {learned['path']}")
```

**具体是什么**：每轮用户对话结束后计数；累计到 `interval`（默认 3 轮，Hermes 是 10 轮）调一次 `maybe_learn`。

**为什么不是每轮触发**：每轮问一次"刚才学到了啥"会浪费 token，且单次纠正不一定代表规律；触发太密会写出"如何查天气"这种没用的 skill。经验值：教学版 3 轮，Hermes 生产版 10 轮。

### 2. 取样器（只取 user/assistant）

**位置**：`self_learning.py:103-115`

```python
for m in (messages or [])[-_RECENT_TURNS * 2:]:
    role = m.get("role")
    if role not in ("user", "assistant"):
        continue
```

**具体是什么**：取最近 8 条消息（4 轮对话），只保留 user 和 assistant，跳过 system 和 tool。

**为什么跳过 system/tool**：system 是机器配置、tool 是工具输出。学习信号 = 用户的纠正 + 助手的承认，这是经验所在；工具执行结果是数据不是经验。

### 3. 蒸馏器（反思提示词）

**位置**：`self_learning.py:26-41`

```python
回顾下面的对话。如果其中出现了【对未来同类任务有用的经验】——
例如：用户纠正了你的风格/流程、你发现了某个工具的使用技巧、踩坑后的修复方法——
就把这条经验整理成一个技能……
如果对话里没有值得沉淀的经验，只输出一行：NOTHING
```

**具体是什么**：把最近几轮对话拼成一段文本，发给 LLM，要求返回标准 `SKILL.md`（含 `name`/`description` frontmatter）；如果没值得沉淀的内容，返回一行 `NOTHING`。

**关键 trick**：`NOTHING` 这个显式放弃退路重要。没有它，LLM 会硬挤出没用的 skill；有它，模型可以诚实说"这段对话没东西可学"。

**为什么提示词能管用**：提示词就是程序。这段话在结构上是一个分支：有经验 → 输出 SKILL.md 格式；没经验 → 输出 NOTHING。`self_learning.py:89` 用 `content.strip().upper()[:20]` 检测 NOTHING 字符串。

### 4. 落盘器（标准 SKILL.md）

**位置**：`self_learning.py:143-149`

```python
skill_dir = self.skills_dir / name
skill_dir.mkdir(parents=True, exist_ok=True)
path = skill_dir / "SKILL.md"
path.write_text(content, encoding="utf-8")
```

**具体是什么**：解析 LLM 返回的 frontmatter 拿到 `name`，规范化成小写连字符，写入 `<skills_dir>/<name>/SKILL.md`。

**为什么是 `name/SKILL.md` 这种目录结构**：因为 V2 已有 `SkillRegistry.scan()` 的扫描契约就是这种结构（`skill_registry.py` 早就写好了）。**本分支零改动就对接上**——这就是"加法扩展"的威力：前人定好接口，新人只管往里填。

### 闭环的最后一步（不用新代码）

下次会话启动 → `SkillRegistry.scan()` 扫到新文件 → `reg.index_text()` 把新 skill 的 name+description 拼进 system prompt（`<available_skills>` 索引）→ 模型知道"我有个叫 xxx 的技能" → 模型用 `load_skill` 工具按需加载全文 → 经验复活。

整个闭环没有额外的"记忆模块"——复用 V2 已有的 SkillRegistry，靠文件系统做持久化。

## 完整闭环图

```
用户对话（轮次累加）
  │
  ▼ 第 N 轮结束（session_manager.py:317）
maybe_learn(turn_count, messages)
  │
  ├─ 距上次 < interval → 跳过（self_learning.py:81）
  │
  ├─ 取最近 8 条 user/assistant（self_learning.py:103-115）
  │
  ├─ LLM 反思（SKILL_REVIEW_PROMPT，self_learning.py:26-41）
  │    │
  │    ├─ 返回 NOTHING → 记录轮次、return None
  │    │
  │    └─ 返回 SKILL.md 文本
  │         │
  │         ├─ 解析 name → 小写连字符（self_learning.py:132-141）
  │         │
  │         └─ 写入 <skills_dir>/<name>/SKILL.md（self_learning.py:143-149）
  │
  ▼ REPL 打印 "🧠 已学习到技能 xxx"

下次会话启动：
  SkillRegistry.scan() → 索引含新技能 → system prompt 注入 name+description
  模型用 load_skill 加载全文 → 经验复活
```

## 对比：教学版 vs Hermes 生产版

教学版只做"能不能跑通"那一条主线，生产版还做一堆防御。下表是真实差距，不是缺陷清单——是教学版应有的克制。

| 维度 | Hermes 生产版 | 教学版（minimal-agent-v2-self-learning） |
|---|---|---|
| 触发 | 每 10 轮，后台 fork 独立 AIAgent（不挡对话） | 每 3 轮，前台同步跑（REPL 立即可见反馈） |
| 总结范围 | 记忆（MEMORY.md）+ Skill 双通道 | 只做 Skill |
| 防御 | 防注入扫描、合并去重 | 信任本地模型 |
| 生命周期 | 30 天 stale、90 天归档（`tools/skill_usage.py` + `agent/curator.py`） | 无 |
| 提示词 | `_SKILL_REVIEW_PROMPT` 完整版（170-284 行） | 裁剪到 15 行 |

为什么前台同步跑反而是教学版的优点：反馈可见性 > 吞吐。学员能看到 `🧠 已学习到技能 xxx` 立即打印，比后台跑更容易理解"这一刻发生了什么"。

## 三个判断题

1. **为什么 interval=3 而不是 1？** 每轮都学的话，LLM 会反复抽到"用户随手问个问题"这种没纠正的对话，写出一堆没用的 skill。学习信号是有密度的，触发太密 = 噪声淹没信号。
2. **为什么不直接复用对话历史当记忆？** 因为对话历史是 session 级临时态，关掉就清零；SKILL.md 是文件系统级持久态，跨 session 存活。要让纠正跨 session，必须落到文件系统。
3. **为什么不存记忆（MEMORY.md）只存技能？** 教学版只演示"纠正→沉淀"这一条主路径。Hermes 实际是双通道：MEMORY.md 是事实性记忆（用户的名字/偏好），SKILL.md 是程序性记忆（怎么做事的流程）。两条性质不同，机制也不同——本篇只讲后者的最小实现。

## 启示

写给做 agent 框架的人：

**让用户教的纠正"留下来"是 agent 的最低成本增量**。一个 `SkillLearner` 类 + 一个计数触发点 + 一段反思提示词 + 复用已有 SkillRegistry——4 个文件改动（`self_learning.py` 新增、`session_manager.py` 加 7 行、`cli.py` 加 25 行、`skill_registry.py` 零改动）就能跑通。这比加一个向量数据库做语义检索便宜得多。

什么时候升级到向量检索 / 时间轴 / 自我编辑？见 `review-20260826-hermes-memory-system.md` 末的"升级判据"——量大上向量检索，要历史上时间轴，要主动进化上自我编辑。本分支演示的最小闭环是起点不是终局。

## 源码导航

- 案例实现：`/root/projects/minimal-agent-v2-self-learning/`
  - `self_learning.py`（SkillLearner 类，149 行）——本机制全部逻辑
  - `session_manager.py:317-320` —— REPL 主循环触发点
  - `docs/design-20260821-self-learning.md` —— 设计文档（YAGNI 清单 + Hermes 对照表）
  - `demo_self_learning.py` —— 3 轮对话演示（无 API key 也可读懂）
- Hermes 生产版：
  - `agent/background_review.py:170-284`（`_SKILL_REVIEW_PROMPT` 完整版）
  - `agent/turn_context.py:494-501`（计数触发）
  - `tools/skill_manager_tool.py`（写入 SKILL.md）
  - `tools/skill_usage.py` + `agent/curator.py`（生命周期管理）
- 相关阅读：
  - `principle-20260901-skill-vs-plugin.md` —— skill 的加载机制（理解本篇前提）
  - `review-20260826-hermes-memory-system.md` —— Hermes 记忆系统综述 + 升级判据
