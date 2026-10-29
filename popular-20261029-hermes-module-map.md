# Hermes 的模块地图：四个入口，一层能力，一颗心脏

> hermes 科普系列·第二篇。上篇讲"一个大脑四种皮肤"，这篇往下挖一层：这套代码到底由哪些零件拼起来、每个零件归谁管。
>
> 素材来源：本机源码 `/usr/local/lib/hermes-agent`，v0.21.5，commit `46bab6f5e4`（2026-10-17）。所有数字都是实测的，不是估的。

## 开场：为什么模块图值得单独讲一篇

很多人读开源项目的方式是"打开 IDE，从 main 顺着 import 往下看"。对 Hermes 这种体量的仓库，这条路会死在第二个小时——因为它的根目录躺着 48 个 `.py`、3 万行代码，一眼望过去像一堆零件摊在工作台上，而不是一个能跑的程序。

但它其实有非常清晰的分层。问题只是：**这个分层不在目录名里，在"职责边界"里。**

这篇我把源码翻了一遍，拆出四层。顺便说一句，这套分类不是我发明的——是我和一位朋友在飞书里边翻源码边吵出来的版本，他（我）提了一句"入口 / 能力扩展 / 长期运行"，我补了底座那一层。

## 顶层：四层地图

先看全景。后面逐层展开。

| 层 | 模块 | 一句话 |
|---|---|---|
| **① 入口层** | `cli` · `tui` · `tui_gateway` · `web` · `gateway` · `apps/desktop` · `acp_adapter` | 人怎么接触它 |
| **② 能力扩展层** | `tools` · `plugins` · `skills` · `optional-skills` · `optional-mcps` · `plugin-catalog` | 它怎么变强 |
| **③ 长期运行层** | `gateway`（常驻形态）· `cron` | 它怎么一直在那儿 |
| **④ 底座** | 根目录 48 个 .py + `agent/` + `hermes_state*` + `providers/` + `hermes_platform/` | 撑住上面三层的代码 |

注意 `gateway` 出现了两次——这不是笔误，下一节专门说。

## ① 入口层：七张脸，但不是七个进程

| 入口 | 目录 | 技术栈 | 干什么 |
|---|---|---|---|
| CLI | `hermes_cli/` | Python | 主控台，70+ 子命令（setup/model/cron/skills/mcp/doctor…）+ slash 分发 + config.yaml + 皮肤 + profile |
| TUI | `ui-tui/` | TypeScript + Ink | 终端富界面客户端 |
| TUI 后端 | `tui_gateway/` | Python | JSON-RPC 传输、MCP 发现、事件重放、hosted room |
| Web | `web/` | React + Vite | 仪表盘 + 内嵌真 TUI |
| Gateway | `gateway/` | Python | 消息网关 + 投递 + hooks |
| Desktop | `apps/desktop/` | Electron | 桌面端 + 桌面插件宿主 |
| ACP | `acp_adapter/` | Python | 接进 VS Code / Zed / JetBrains |

实测规模：`hermes_cli/` 递归 557 个 `.py`（顶层就 417 个），`gateway/` 174 个，`tui_gateway/` 97 个，`acp_adapter/` 14 个。

有个反直觉的点：**入口层不是"每个入口一套完整逻辑"**。CLI 里的 `cli.py` 只有 1876 行，因为它自己什么都不干，只做一件事——把 16 个 mixin 类拼起来（另有若干 helper 模块一并 import）：

```python
from hermes_cli.cli_agent_setup_mixin import CLIAgentSetupMixin
from hermes_cli.cli_commands_mixin import CLICommandsMixin
from hermes_cli.cli_stream_mixin import CLIStreamMixin
...
```

真正的逻辑在 `hermes_cli/` 的各个 mixin 文件里。这是 AGENTS.md 里说的"把 god file 拆成干净模块"——机械拆分，但保持 `cli.<name>` 这个缝合点不变，外部调用方一行都不用改。

### Gateway 为什么既是入口又是长期运行层

这是最容易分类错的一个。

看 `gateway/platforms/` 的文件结构就明白了：里面有 `bluebubbles.py`、`signal.py`、`weixin.py`、`whatsapp_cloud.py`、`yuanbao/`、`qqbot/`——这些是**接入面**（入口）。但 `gateway/` 外面还有 `run_startup.py`、`run_turn.py`、`run_shutdown.py`、`run_watchers.py`、`run_idle_gates.py`、`run_heartbeat_*`——这些是**进程形态**（长期运行）。

一个进程，两个身份。不是两套东西。

## ② 能力扩展层：Hermes 的"外接器官"

这一层是 Hermes 最被误解的地方。很多人以为"给 agent 加能力 = 改核心代码"，其实恰恰相反。

| 模块 | 规模 | 装什么 |
|---|---|---|
| `tools/` | 336 个 .py | 工具注册表与 toolsets：审批、浏览器、computer_use、委派子 agent、connectors |
| `plugins/` | 241 个 .py | 18 个插件族：memory（7 个后端）/ model-providers（37 个）/ platforms（22 个）/ kanban / image_gen / video_gen / observability / context_engine / spotify… |
| `skills/` | 14 个目录 | 内置技能库，curator 自动维护 |
| `optional-skills/` | 24 个目录 | 可选技能包（blockchain / gaming / health / mlops / payments / finance…） |
| `optional-mcps/` | 65 个 | MCP 服务目录（notion / stripe / sentry / vercel / airtable / twilio…） |
| `plugin-catalog/` | 294 个 YAML | 第三方插件注册表 |

写代码的判断链条是：**新能力默认不进核心**，按 AGENTS.md 里那张"Footprint Ladder"（足迹阶梯）从最轻的往上找：

1. 扩展已有代码（零新表面）
2. CLI 命令 + skill（订阅、定时任务、服务配置都走这条）
3. 服务门控工具（`check_fn`，需要配了前置条件才出现）
4. 插件（第三方 / 冷门 / 用户特有）
5. 目录里的 MCP server（是真工具但不该占核心 schema）
6. 新核心工具（最后手段：只有当它足够基础、人人需要、且 terminal+file+MCP 都够不着）

为什么要这么克制？因为核心工具 schema **每次 API 调用都要全量发过去**。加一个核心工具 = 每次请求多付一份 token。这是 Hermes 最硬的经济学约束。

顺带一个反过来的例子：根目录的 `mcp_serve.py` 让 Hermes **自己变成 MCP server**，被 Claude Code / Cursor / Codex 当工具调用。能力扩展是双向的——Hermes 既消费外部能力，也对外输出。

## ③ 长期运行层：让它一直在那儿

| 模块 | 规模 | 职责 |
|---|---|---|
| `gateway/` | 174 个 .py | 常驻进程：接消息 → 跑 turn → 投递回复 |
| `cron/` | 33 个 .py | 调度器：job 定义、投递队列、失败诊断、occurrences |

`cron/` 的文件命名很说明问题——`scheduler_delivery.py`、`scheduler_detached_worker.py`、`scheduler_preflight.py`、`scheduler_diagnostics.py`、`lifecycle_guard.py`、`quota_hold.py`。一个定时任务要管的东西，比"到点执行"多得多：投递去哪、执行超时怎么办、失败怎么诊断、进程重启后 job 还在不在、谁持有这个 job。

`cron/` 还带一个 `bot_chat_delivery.py`——定时任务的产出可以投回聊天窗口。这就是你能在飞书里收到"每日盘后提醒"的技术路径。

## ④ 底座：根目录那 48 个文件

这部分最容易被漏看，因为它们不在任何"有名字"的目录里。

**根目录 48 个 `.py`，合计 31,572 行。** 按职责分四类：

**执行核心**
- `run_agent.py`（1623 行）——AIAgent 主循环，对话轮次、工具执行、会话生命周期
- `model_tools.py`（992 行）——工具注册表之上的薄编排层，暴露 `get_tool_definitions()` / `handle_function_call()`
- `toolsets.py` —— 工具组定义与解析（CLI 和所有消息平台共用一份工具清单，改一次全平台生效）
- `toolset_distributions.py` —— 批量数据生成时"每个工具组以多少概率开启"的采样分布

**会话存储（`hermes_state*.py`，30 个模块）**
- `hermes_state.py`（1735 行）——SQLite 状态库的入口，WAL 模式（多读单写）
- `hermes_state_sessions.py`（1716）/ `_messages.py`（1585）/ `_search.py`（1346）/ `_schema.py`（1311）/ `_common.py`（1251）/ `_repair.py`（1160）…
- `_fts.py` —— FTS5 全文检索；`native/fts5_cjk/` 是配套的 CJK 分词原生扩展

30 个模块说明一件事：**会话存储不是"一张表"，是一套子系统。** 压缩、检索、修复、WAL、reindex、时间轴、标题、用量统计，各占一个模块。

**公共基建**
- `hermes_constants.py`（1648 行）——共享常量，纯 stdlib、任何地方都能 import、零循环依赖风险
- `utils.py`（745）/ `hermes_logging.py`（776）/ `hermes_time.py`（时区感知时钟）
- `hermes_bootstrap.py` —— **进程引导**。必须是每个入口的第一个 import：Windows 绑定 cp1252 控制台代码页，`print("café")` 会炸；这个模块处理 UTF-8 stdio、import 路径加固（防止启动目录的 `utils/` 目录覆盖 Hermes 自己的同名模块）、双栈连接
- `hermes_startup_watchdog.py` —— 启动存活看门狗。注释里写得很直白：其他所有存活兜底（循环看门狗、关停看门狗、心跳文件）都假设启动成功了；如果进程在事件循环起来之前就死锁，它们一个都响不了。这个看门狗在进程入口起一个守护线程，循环确认活着后才解除武装
- `registration_lifecycle.py` —— 可替换运行时注册项的所有权租约（provider 单例可以注册-卸载-再注册，认的是"注册代次"不是值身份）

**批量与评测**
- `batch_runner.py`（1011 行）——批量跑 agent over JSONL 数据集，多进程池、断点续跑、工具使用统计
- `trajectory_compressor.py`（868 行）——把 agent 轨迹压进 token 预算：保护头部（system/human/首个 assistant/首个 tool）和最后 N 轮，中间按需摘要，但**绝不拆开 `<tool_call>/<tool_response>` 配对**
- `mini_swe_runner.py` —— SWE 基准跑批

**另外还有** `setup.py`（安装脚本）、`cli.py`（CLI 入口）、`mcp_serve.py`（728 行，MCP server 输出侧）。

## 一张表收尾

| 层 | 目录 | 规模 |
|---|---|---|
| 入口 | `hermes_cli/` | 557 py |
| 入口 | `gateway/` | 174 py |
| 入口 | `tui_gateway/` | 97 py |
| 入口 | `acp_adapter/` | 14 py |
| 入口 | `web/` `ui-tui/` `apps/desktop/` | TS/TSX/Electron |
| 扩展 | `tools/` | 336 py |
| 扩展 | `plugins/` | 241 py |
| 扩展 | `skills/` + `optional-skills/` | 155 py |
| 扩展 | `optional-mcps/` + `plugin-catalog/` | 65 + 294 项 |
| 长跑 | `cron/` | 33 py |
| 底座 | 根目录 | 48 py / 31,572 行 |
| 底座 | `agent/` | 306 py |
| 底座 | `hermes_state*.py` | 30 模块 |
| 底座 | `providers/` `hermes_platform/` `native/` | 16 py + C 扩展 |
| 保障 | `evals/` + `tests/` | 146 py + 4886 py |

（`tests/` 的 4886 个 `.py` 里大部分是 fixtures，按文件数统计会失真，仅作规模参考。）

## 三条我读完的判断

**1. 目录名不重要，边界才重要。**
`gateway/platforms/` 里一半是核心适配器，一半是 webhook 公共设施，真正的主力平台（Telegram、Discord、Slack、飞书、Teams、WhatsApp…）反而住在 `plugins/platforms/`。所以"某平台在哪个目录"这个问题本身就没意义——有意义的问题是"它属于核心还是扩展"。

**2. 30 个状态模块 > 1 个大状态模块。**
会话存储能长成这样，是因为它要面对的不是一个功能而是十几个：压缩、检索、修复、迁移、并发、时间轴……每个都是能独立演进的领域。这就是"Refactor god-files into clean modules"那条贡献准则的落地形态。

**3. `hermes_bootstrap.py` 这种文件最能说明工程成熟度。**
它解决的不是功能问题，是"每个入口都得记得正确初始化"这种横切关注点。把这类东西收进一个必须第一个 import 的模块，比在文档里写"记得先设置 PYTHONUTF8"可靠一百倍。

## 思考题（每层一个）

1. 如果让你把 `tui_gateway/` 的职责并进 `web/`，会省掉多少文件、又会多出哪些耦合？
2. AGENTS.md 说插件"不该改核心文件"。用本文四层地图解释：为什么这条规则在结构上是自洽的？
3. 根目录那 48 个文件里，哪几个其实应该搬进 `agent/`？搬进去的收益和代价分别是什么？

## 源码导航

- 四层地图的总纲：`AGENTS.md`（根目录）——贡献准则 + Footprint Ladder + 分区路由表
- 入口装配：`cli.py`（mixin 拼装）
- 主循环：`run_agent.py`
- 工具编排：`model_tools.py` / `toolsets.py`
- 会话存储：`hermes_state.py` + 30 个 `hermes_state_*.py`
- 进程引导：`hermes_bootstrap.py`
- 存活兜底：`hermes_startup_watchdog.py`
- 平台接入：`gateway/platforms/`（核心）+ `plugins/platforms/`（22 个插件平台）
- 扩展目录：`optional-mcps/`（65）、`plugin-catalog/`（294）、`optional-skills/`（24）

---

**下篇预告**：`skills/` 和 `plugins/` 到底怎么协同——同一个能力，什么时候写成技能、什么时候写成插件，判据是什么？（这个问题仓库里有一篇 `principle-20260901-skill-vs-plugin` 讲了一半，但它没覆盖 MCP 这一档。）
