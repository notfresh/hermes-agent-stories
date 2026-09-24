# 被放弃的融入终端的特性

关于 `feature-zx` 分支上那 21 个提交，以及它们为什么没进主干

---

## 一、仓库里有一块化石

`git branch` 会告诉你，这个仓库里躺着一条叫 `feature-zx` 的分支，最后提交 2026-07-29，信息是「zx功能完结」。

往上数 21 个提交，是完整的实现轨迹：设计规格、实现计划、解析器改动、核心函数、分发接线、测试、daemon、锁、socket、bug 修复。

不是被废弃的实验。它有完结收尾、有配套文档、有测试、有 bug 修正记录。它是**做完了但没被合并**的特性，只存在于这一台机器上——`origin` 只有 `main` 和 `source-code-read`。

这篇文章讲的是：这个特性在技术上到底想做什么，它的判断是哪来的，以及**它为什么会被放弃**。

---

## 二、它瞄准的是终端本身的空档

Hermes 有两种调用姿态：

- **交互态**（`hermes`、`hermes -c`、`hermes --resume`）：工作台，记得上次聊了什么，有心跳、有提示符。
- **失忆的一次性调用**（`hermes -z "..."`）：给脚本用，没有 banner/spinner，把最终文本吐 stdout。代价是**每次从零开始**。

中间那个空档是：

> 在 shell 里，带着上一轮的上下文，问一个问题，拿一段干净输出，然后走人。

不是"恢复会话"（那是 `-c`，要进 REPL），也不是"无状态提问"（那是 `-z`，要失忆）。这是第三种东西：**有记忆的一次性调用**。

作者为此造了 `-xz` 和 `-zx` 两个同义词——行为完全一致，唯一的差别是"手指从键盘滑过去的时候不该被工具的语法打断"。纯粹的终端美学，没有功能增益。**而恰恰是这种美学，在评审中是负债。**

---

## 三、技术上真正讲究的三件事

抛开产品直觉，`-xz` 的实现里有三处判断值得单独拿出来说。

### 1. 没有新造"恢复会话"的路径

最省事的做法是"读数据库、拼消息、喂给 agent"。作者没有。

他逐字对齐交互式 CLI 的既有契约——`cli_agent_setup_mixin.py:455` 里 `_preload_resumed_session()` 的那套：同一个调用 `get_messages_as_conversation(session_id, ...)`、同一个标志 `repair_alternation=True`、同一份消息格式。

`repair_alternation` 修的是"上次崩溃留下的角色交替损坏"——比如数据库里躺着两条连续 `user`。不修的话，这条损坏会在会话余生的每一次请求里反复触发防御性修复。作者在注释里写得很清楚：**一次性修掉，而不是每次都去打补丁**。

### 2. 写回，而不是只读

`-xz` 打完一轮，通过标准的 `_flush_messages_to_session_db` 路径**持久化这一轮**。`session_db` 用的是完整 `SessionDB()`，而不是 `-z` 那条轻量句柄 `_create_session_db_for_oneshot()`——**这里要的是真持久化**。

你在脚本里续的那一轮，等下打开 TUI 是能看到的。它不是"历史查询工具"，是"对话的又一次呼吸"。

### 3. 把"脚本友好"当成硬契约

退出码被契约化：

| 情形 | 退出码 |
|---|---|
| 正常完成 | 0 |
| 没有可续的会话 / `--provider` 没给 `--model` / `--toolsets` 非法 | 2 |
| agent 抛异常 / 没有产出最终响应 | 1 |

错误信息带前缀写 stderr（`hermes -xz: ...`），管道能精确区分"stdout 的内容"和"stderr 的抱怨"。`--usage-file` 失败也写——批处理最怕的不是某次失败，而是**不知道失败那次花了多少钱**。

还有一个挖得极深的坑，作者用一行声明修掉了：

```python
# One-shot prints a single final response and exits: there is no later turn
# for a detached subagent's completion to re-enter, and nothing here drains
# process_registry.completion_queue (only cli.py's interactive process_loop
# and the gateway watchers do). Left unbound, async_delivery_supported()
# defaults True, delegate_task is forced background, and every subagent
# result is discarded.
declare_stateless_channel()
```

one-shot 进程**没有任何东西会去消费子代理的完成队列**。如果不显式声明这是无状态通道，`delegate_task` 会被强制走后台，**每一个子代理的结果都会被静默丢弃**——不报错、不崩、不留日志，只是让"委托给子代理"安静失效。

---

## 四、一个关于 fork 与锁的正确性练习

同一个分支上的 `shell_context.py` 想砍掉每次 one-shot 的启动成本——起一个常驻 daemon 预热 `discover_plugins()` 和 `discover_mcp_tools()`，通过 UDS 暴露状态；后续 one-shot 进程先问"暖好了吗"，暖了就跳过重复发现。

骨架不难。难的是 **fork 和锁的关系**——这是极容易写出隐蔽 bug 的地方。作者踩了四个坑：

**坑一：父进程预持锁 → daemon 静默消失**

最初父进程先 `acquire` 再 fork。子进程 `LOCK_NB` 失败、直接 `os._exit(1)`。表面什么都没发生——daemon 从来没活过。最终版留下注释：*Do not hold the lock in the parent before forking. If the parent acquires it first, the child can fail to re-acquire and exit, leaving no daemon.*

**坑二：`flock` 不跨 fork 继承**

子进程必须自己重新取一次锁——反过来变成好事：**锁本身成了选主机制**。抢不到锁的子进程优雅退出，天然防重复 daemon，不需要额外心跳或 PID 检查。

**坑三：`fcntl.fcntl` 写成了 `fcntl.flock`**

`2926d79e3d` 提交只有一个作用：把 `fcntl.fcntl(fd, LOCK_EX | LOCK_NB)` 改成 `fcntl.flock(...)`。POSIX 咨询锁的教科书陷阱——两个都能编译、能跑、返回值都像那么回事，但 `fcntl()` 用 `struct flock` 记录锁、`flock()` 用 BSD 文件锁，混用通常导致"锁看起来生效，某些路径下神秘失效"。作者自己复查出来并修掉了。

**坑四：PID 文件从"创建"改成"替换"**

收尾提交把 `O_CREAT | O_EXCL` 改成 tmp 文件 + `replace()`（原子替换陈旧的）。`O_EXCL` 的语义：如果上次异常退出留下 pid 文件，**以后永远起不来 daemon**——一次崩溃放大成永久失效。

---

## 五、它为什么会被放弃

工程上看，这个特性没有明显硬伤。有设计文档、有实现计划、有测试、有 bug 修正、有收尾提交。走的是 Superpowers 的 spec → plan → task 流程。

但从《贡献准则》看，它踩在了几条线上：

### 1. `-zx` 同义词是纯粹的 surface

准则"扩展，不要重复"以及"最多余的表面是有代价的"。`-zx` 和 `-xz` 行为完全一致，`help=argparse.SUPPRESS`，唯一理由是"敲着顺手"。功能上零收益，终端美学是全部意义——**而终端美学不在评审准则的评分表里**。

务实做法：只做 `-xz`，让需要的人 `alias`。这不是技术分歧，是"谁的成本"的分歧——alias 成本在用户（一行配置），`-zx` 成本在项目（永久核心表面）。

### 2. daemon 是"投机性基础设施"的灰色地带

准则："投机性基础设施——没有具体消费方的钩子/回调/扩展点，加容易、删难。"

`shell_context.py` 里的 UDS 端点有两个**没有消费方**：`GET /prewarmed_plugins` 和 `GET /prewarmed_mcp`。除了 `shell_context.py` 自己，全仓库没有第二处读取它们。`main.py` 只读 `/health` 里的 `status` 和 `prewarmed` 布尔位，然后用这个布尔**跳过 inline discovery**；预暖的**实际内容**（插件名、MCP 工具清单）从未被送回父进程。

获益是真实的——确实跳过了重复发现。但"回传实际内容"那段，接口搭好了、线没接。从字面看是负债，从作者看是 plan 里 Task 2 的交付物。**双方都不算错的判断分歧，准则给的是保守答案。**

### 3. 最根本的：它挑战的是"什么算核心"的定义

准则："核心是一条细腰；能力长在边缘。每一个 model tool 都要在每一次 API 调用里被发送。"

`-xz` 挑战的不是文本，是**边界**。它是一个 CLI flag——按"足迹阶梯"，CLI 命令 + 技能属于第二级，是推荐做法。作者甚至做得很干净：`cli.py`、`run_agent.py`、`SessionDB` 一行未动，纯边缘扩展。

但顶层 flag 是这个项目最敏感的地带。和"缓存神圣"同源——**顶层解析器决定每一次调用要付多少启动成本**。一个 flag 不是加一行 argparse——牵动 `main()` 的分发顺序、`_prepare_agent_startup` 的时机、one-shot 路径的整条生命周期。这正是为什么这批改动最终横跨 `_parser.py` / `main.py` / `oneshot.py` / 新增一个 daemon 模块。**一个 flag 从来不是一个 flag。**

### 4. 时机

最朴素的原因：**这条分支落后主干很久**。`main..feature-zx` 有 16395 个提交。要合，得先 rebase 到 `main`、处理冲突、重新验证。而 `main.py` 恰恰是这八周里被改得最勤的文件之一。合并代价很可能已超过特性本身价值。准则里专门警告过这个场景："从陈旧分支做 squash 合并会静默回滚近期的修复。"

---

## 六、一个更有意思的角度

如果只讲成"一个没被合并的特性"，就浪费了它。

真正值得记下来的是：**这是一个被放弃的、但做对了的特性。** 它的每一处"被放弃"的理由，都可追溯到这个项目的某条硬约束：

| 它做了什么 | 为什么是对的 | 为什么被放弃 |
|---|---|---|
| `-xz` 补齐有记忆的一次性调用 | 填了终端管线的真空档 | 顶层 flag 边界太敏感 |
| 对齐 `_preload_resumed_session` 契约 | 零新增路径，复用既有秩序 | 完全符合准则 |
| 写回会话而非只读历史 | 对话能自然生长 | 完全符合准则 |
| 退出码 / stderr 前缀 / usage-file | 脚本友好是硬契约 | 完全符合准则 |
| `-zx` 同义词 | 终端美学 | 零收益 surface，准则不认 |
| UDS 预暖 daemon | 真实砍掉启动成本 | 端点无消费方 = 投机性 |
| fork + flock 的选主设计 | 优雅，无额外心跳 | 复杂度进主干后不可逆 |

有意思的是表中段：**三行"完全符合准则"的实现，没能救回这个特性。**

这说明评审不是逐条打分。当一件事在顶层表面是负债、在基础设施是投机、在合并成本是八周的债，那么它在实现上有多讲究，都不改变结论。

而恰恰是这一点，让这份代码有了文献价值。

---

## 七、所以它该被删掉吗

**不该。** 至少现在不该。

不是因为可惜。而是因为**它是这个仓库里唯一一份"这个空档存在过"的证据**。

`-z` 和 `-c` 之间那个空档是真实存在的，不会因为删掉分支就消失。区别在于：**下一次有人想的时候，是能看到这 21 个提交（设计、取舍、踩过的坑、修过的 bug），还是只能从零开始重走一遍。**

那 7 个坑里的每一个——`fcntl` 和 `flock` 的区别、父进程预持锁导致的静默死锁、`O_EXCL` 把单次崩溃放大成永久失效、one-shot 通道里子代理结果被静默丢弃——都是**有人付过时间成本才发现的**。删掉分支，这些知识归零。

处理的三条路：`git push origin feature-zx` 留异地副本；或 cherry-pick 到 `main` 验证；或至少归档成 issue + 设计说明。

至于作者——他给这条分支的最后一次提交起名「zx功能完结」。

功能确实完结了。只是没有被接纳。这两件事之间没有矛盾，但把它们放在一起看，就是一个挺典型的开源故事。

---

## 附：这批改动的基本事实

```
分支         feature-zx
最新提交     2626628ebc  "zx功能完结"
作者         notfresh <notfresh@foxmail.com>
时间         2026-07-25 ~ 2026-07-29
本人提交     14 个（committer 21 个，含 7 个上游同步）
独立提交     21 个（其他任何分支都没有）
远程副本     无
领先关系     落后 main 16395 个提交
```

涉及文件：

```
hermes_cli/_parser.py          -xz / -zx flag（与 -z 互斥）
hermes_cli/oneshot.py          run_oneshot_with_session / _run_agent_with_history
hermes_cli/main.py             分发 + 启动顺序调整
hermes_cli/shell_context.py    新增：prewarm daemon（lock/pid/socket/UDS）
tests/hermes_cli/test_xz_flag.py
tests/hermes_cli/test_shell_context.py
docs/superpowers/specs/2026-07-25-xz-design.md
docs/superpowers/plans/2026-07-25-xz-implementation.md
docs/superpowers/plans/2026-07-25-shell-context-implementation.md
```

一行未动：`cli.py`、`run_agent.py`、`SessionDB`。

---

## 八、给下一次做新特性时的判断：低成本试错

这篇文章从头到尾在讲"这个特性为什么被放弃"。但直到写完，我才发现**真正值得带走的东西不在这**。

它是事后才浮上来的：

> **新建特性时，先按"低频"对待——这是低成本试错的另一面。**

理由是**两种处置方式的成本曲线不对称**：

- **先融入 → 发现低频**：重构成本巨大。逐字对齐的契约、写回路径、退出码契约化……每一处"严谨"都是要拆、要重写、要重新走一遍 PR 流程的债。
- **先粗糙 → 发现高频**：再回头"融入"成本可控。因为高频带来的回报撑得住那次重构。

**反过来不成立。**

所以判断的默认值应该是反的：**默认粗糙、自起炉灶、最简单方式落地**。等它被反复用了、被证明值得，再去融合既有秩序。低频特性承受不起"先融入"的代价，只有高频才付得起——而高频是事后才看得清的。

而 `-xz` 那晚我做反了——**还没估计出频率，就先按"融入"姿态做**。`cli_agent_setup_mixin.py:455` 里 `_preload_resumed_session()` 的契约、`repair_alternation` 的一致性、写回走标准路径——这些"严谨"不是不必要，是**时机不对**。低频场景下，先严谨 = 先付债，收益却撑不起。

这些判断到现在还在用，但用反了的那一晚已经花出去了。

——事后追补于 2026-09-25。