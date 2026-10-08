# Skill vs Plugin：内容与机制的分界线

> 2026-09-01 · agent 原理系列 · 第一篇
> 整理自一次问答讨论：Hermes 的 skill 和 plugin 到底有什么区别，为什么简单分"skill 是文档、plugin 是代码"不成立。

---

## 核心结论

skill 和 plugin 的界限不在文件形态（markdown 还是代码），在**加载机制**：skill 是内容，模型按需读取；plugin 是代码，进程启动时执行注册。

一句话判据：**有没有被 Hermes 进程 import 并执行**。

| | skill | plugin |
|---|---|---|
| 核心文件 | SKILL.md | plugin.yaml + `__init__.py` 的 `register()` |
| 加载时机 | 模型按需读取（渐进式披露：先索引 → 需要才看全文） | 进程启动时 import 并执行 `register()` |
| 附属内容 | 可带 `scripts/*.py`、references/、templates/ | 可带 skills/、commands/、tools/、hooks/、平台适配器 |
| 是否登记进系统 | 否 | 是 |

## 问题 1：skill 和 plugin 各是什么

- **skill**：一段给模型看的方法文档。加载后进入模型上下文，告诉模型"这类任务按什么流程做"。不新增能力，只改变行为方式。
- **plugin**：一段给进程执行的代码。启动时 `register()` 把新命令、新工具、新钩子挂进运行时，模型之后才能调用这些新东西。

## 问题 2：为什么"文档 vs 代码"的二分不成立

两个反例：

1. **plugin 可以带 skill**。著名例子 superpowers——以 plugin 形式分发，里面是一百多个 SKILL.md。plugin 是打包容器，skill 是其中一种内容。
2. **skill 可以带 py 脚本**。本机 35 个 skill 带 `scripts/` 目录，8 个带 py 文件（如 quote-poster-wallpaper 的 `gen_quote_wallpaper.py`）。这些脚本从未被注册，模型读 SKILL.md 后用 terminal 工具手动运行它们。

所以"skill=文档、plugin=代码"不成立，二者都可以带对方形态的文件。

## 问题 3：真正的分界线——加载机制

同一个"py 文件"出现在两种位置，命运完全不同：

| 位置 | 谁主动 | 何时执行 | 效果 |
|---|---|---|---|
| `skill/scripts/*.py` | 模型读文档后决定 | 模型用 terminal 工具手动调起 | 一次性脚本，进程不知道它存在 |
| `plugin/__init__.py` | Hermes 进程 | 启动时 import | `register()` 把能力挂进运行时，模型之后用现成的 |

- skill 的 py：模型读文档后按指示运行，Hermes 进程对它的存在一无所知。
- plugin 的 py：启动即执行注册，不进注册表就不生效。

## 问题 4：怎么判定一个东西是 skill 还是 plugin

问三个问题：

1. **谁加载它**？—— 模型读 vs 进程 import
2. **加载时执行什么**？—— 文本进上下文 vs 代码执行注册
3. **不加载会怎样**？—— 模型不知道这方法 vs 新命令/新工具不存在

## 实例

- **superpowers（plugin 带 skill）**：它的 skill 能活，靠 plugin 里的 bootstrap 注入器。官方文档（`docs/porting-to-a-new-harness.md`）原话：没有注入，技能文件是"死文件"——在磁盘上，从不被调用。这印证了 plugin 的"激活"作用。
- **quote-poster-wallpaper（skill 带 py）**：`gen_quote_wallpaper.py` 躺在 `scripts/` 里，只有模型读了 SKILL.md 并按指示用 terminal 运行它才生效。

## 一句话

**skill 是内容（模型消费，脚本是附带的工具），plugin 是代码（进程执行，skill 可以是它打包的内容）**。分界线不是"有没有代码"，是"代码有没有被进程主动执行注册"。
