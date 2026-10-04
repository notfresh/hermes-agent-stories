---
story_id: 10
title: yolo 模式是怎么把危险命令审批的"否决权"夺走的——我又怎样把它放回来
date: 2026-10-04
author: notfresh
status: recorded
tags: [hermes-agent, approval, security, yolo, container, command-allowlist]
---

## 起点

我有个反复用的容器,想让 agent 在里面帮我跑命令,又不想让它过度自由。一开始我以为是 yolo 模式的问题,后来顺着仓库扒了 `tools/approval.py`、`approval_floors.py`、`approval_detection.py` 一圈,才搞清楚 yolo 不是单点开关,是一组**三源旁路**——而且在 docker 里它的边界跟我以为的不一样。

这篇文章把这次捋清楚的东西写下来:**yolo 是什么、它在审批链哪一层、容器里它到底放了多少、又怎么收回来**。

## 抽象到一句:yolo 是什么

**yolo = "危险命令审批门" 的可旁路开关**。打开后,除不可逆的硬伤之外,所有危险命令自动放行,不再问人。

三道硬伤(yolo 也救不了):
1. **硬线黑名单**:`rm -rf /`、关机、磁盘原始写
2. **用户自定义 `approvals.deny`**:`config.yaml` 里写的 glob 列表
3. **`sudo -S` 密码管道**:暴力破解向量

其他一切:**放**。包括 `git push --force`、`dd`、`chmod -R 777`、`curl|sh` 这种"危险但有救"的——yolo 通通不问。

一句话总结:**yolo = "除了不可逆的硬伤,其余全放"。**

## 三个独立来源,任一为真即开

代码在 `tools/approval.py:355-364`:

```python
def is_approval_bypass_active_for_session(session_key):
    """三源旁路检查:进程级 --yolo、会话级 /yolo、config 级 mode=off"""
    return (_YOLO_MODE_FROZEN or is_session_yolo_enabled(session_key)
            or approval_context._get_approval_mode() == "off")
```

三个来源,任一为真就激活:

| 来源 | 怎么触发 | 作用范围 | 持久? |
|---|---|---|---|
| 进程级 | `hermes --yolo` 或 `HERMES_YOLO_MODE=1` | 整个进程 | 仅本次 |
| 会话级 | `/yolo` 斜杠命令 | 当前 session_key | 仅本次会话 |
| config 级 | `config.yaml` 里 `approvals.mode: off` | 所有会话、CLI/TUI/cron | ✅ 持久 |

`HERMES_YOLO_MODE` 是**模块加载时一次性冻结**的(`approval.py:45`)——这设计很关键:防止运行中的 skill 通过 `os.environ` 临时覆写绕过审批门(防 prompt injection 升级路径)。

## 审批链的真实顺序

我原以为是"先检测危险模式,后查白名单",但顺着代码读下来发现不是。**完整顺序(从最先到最晚)**(`tools/approval.py:977-1038` 的 `check_all_command_guards`):

```
┌─────────────────────────────────┐  ← yolo? mode=off? cron approve? → 直接放
│      可恢复的审批层              │
├─────────────────────────────────┤
│   permanent allowlist 匹配?     │  ← 命令在你的白名单里? → 放
├─────────────────────────────────┤
│  dangerous pattern 检测          │  ← 是危险模式? → 弹 prompt 问人
├─────────────────────────────────┤
│ ★ FLOORS (硬地板,无条件拒绝) ★ │  ← 硬线/deny/sudo? → 直接拒,谁也救不了
└─────────────────────────────────┘
```

也就是说:**floors 永远在审批层底下跑**。上层放开(floors 之外)→ agent 自由跑;但 floors 命中 → **无条件拒绝**,yolo / mode=off / cron approve-mode **全都救不了**。

具体看 `approval.py:871-885` 的 `_floor_block` 函数,里面按这个顺序查:

1. 硬线黑名单(`HARDLINE_PATTERNS`):`rm -rf /`、关机、磁盘原始写
2. `sudo -S` 密码管道
3. `approvals.deny`(用户的 glob)

三个里任何一个命中,都直接拒。

## 我的真实场景:docker 容器里反复用

我一直在 docker 里跑反复使用的容器。一开始我以为 docker 里 yolo 是"沙箱所以默认安全",读代码才搞清楚边界。`_should_skip_container_guards` 函数(`approval.py:852-857`):

```python
def _should_skip_container_guards(env_type, has_host_access=False):
    """True when the backend is isolated enough to skip dangerous-command prompts."""
    if env_type == "docker":
        return not has_host_access                # ★ docker 例外
    return env_type in ("singularity", "modal", "daytona", "vercel_sandbox")
```

如果是 docker 且**没有 host bind mount**,跳过危险检测。整个流程变成:

```python
return _user_deny_block(command) or _approved()
```

**只查 deny,不查 dangerous pattern、不查白名单、不查 yolo、不弹 prompt。**

我一开始以为这是好事——"沙箱嘛,随便跑"。但仔细一想:**deny 是唯一剩下的拦截手段**。如果不写 deny,容器里 agent 就**完全自由**——比不开沙箱还松。

docker 有 host bind mount 是例外(`has_host_access=True`)——`rm -rf /workspace` 会扫到宿主文件,这时候不跳过危险检测。

## 我的解决方案

不写 `approvals.mode: off`,也不开 `--yolo`。默认 manual 模式,然后在 `~/.hermes/config.yaml` 加 `approvals.deny`:

```yaml
approvals:
  deny:
    - "rm -rf *"
    - "git push --force*"
    - "git reset --hard*"
    - "curl * | sh"
    - "wget * | sh"
    - "dd *"
    - "mkfs*"
    - "shutdown*"
    - "reboot*"
    - ":(){:|:&};:"             # fork 炸弹
```

这样我的反复使用容器里:

- 普通命令:agent 自由跑
- 危险命令:每次弹 prompt 问我(`once / session / always`);如果我觉得烦就 `[a]lways` 加白名单
- 我担心的几类:**完全不会跑**(deny 直接拒)
- 即使误开 yolo / mode=off → deny **仍生效**(floors 跑在最底下)

## smart 模式不是 yolo 的替代

顺便看了一下 `approvals.mode: smart`(`approval_smart.py` + `approval.py:1036`)。它是 manual 模式的**升级**:多一道 guardian LLM 预审,APPROVE 直放,DENY 弹 prompt 给人(附 guardian 的拒绝理由,人可 ESCALATE 强制放)。

但代码里 `approval.py:993` 写得明白:

```python
if _yolo_active() or approval_mode == "off":
    return _approved()
```

**yolo / off 直接 short-circuit 在 smart 之前**——smart 模式只在你没开 yolo、mode 又不是 off 时才生效。换句话说:**smart 是 manual 的升级,不是 yolo 的替代品**。

## 代码分布全景

```
核心(共 5 文件, 3000+ 行相关)
├─ tools/approval.py            1168 行 — 状态、三源、4 个 gate(最重)
├─ tools/approval_detection.py  1165 行 — 危险模式/hardline 模式表(yolo 不改)
├─ tools/approval_floors.py      204 行 — floors(yolo 之前的最后一道)
├─ tools/approval_context.py     — contextvars, _get_approval_mode()
└─ tools/approval_prompt.py      — CLI/gateway 提问实现(yolo 跳过它)

CLI 入口
├─ hermes_cli/main.py           4 个 chokepoint(L3377/2720/2983/1672)
├─ hermes_cli/_parser.py        argparse --yolo(L159/257)
├─ hermes_cli/cli_status_bar_mixin.py  ⚠ YOLO 徽章(L1047)
├─ hermes_cli/cli_tui_mixin.py  状态条主题(L2173)
├─ hermes_cli/cli_chat_turn_mixin.py  每 turn 绑定 session key(L278/339/451)
└─ hermes_cli/approvals_suggest.py  历史挖掘(L8 注释提到 yolo)

Gateway/Messaging
├─ gateway/slash_commands.py     /yolo 翻转实现(L889-897)
└─ gateway/hosted_room_*.py     房间内的执行策略

Desktop
└─ apps/desktop/src/lib/yolo-session.ts   76 行 — 会话/全局两种 toggle

配置 + 文档
├─ website/docs/user-guide/security.md  §65 "YOLO Mode" 章节
├─ website/docs/user-guide/cli.md       状态条说明
├─ website/docs/user-guide/tui.md       TUI 中的视觉
├─ website/docs/reference/cli-commands.md    --yolo
├─ website/docs/reference/environment-variables.md  HERMES_YOLO_MODE
└─ website/docs/reference/cli-symbols.md ⚠ YOLO 图例
```

## 关键设计取舍

| 取舍 | 体现位置 | 理由 |
|---|---|---|
| **freeze at import** | `approval.py:45` | 防 skill 临时改 env 绕过审批 |
| **4 处 chokepoint 重复设 env** | `main.py:3377/2720/2983/1672` | 不同入口(Termux fast-CLI / 默认 chat / subcommand dispatch)都跑一遍,防漏 |
| **floors 永远先于 yolo** | `approval_floors.py` docstring + `approval.py:871-885` | 用户可在 yolo 下用 deny glob 留例外 |
| **permanent allowlist 跑在 yolo 之后** | `approval.py:901/995` | yolo 不光放行危险命令,也跳过 allowlist check——但 allowlist 仍会被尊重 |
| **yolo 不影响 hardline** | `approval_detection.py:52` 注释直说 | "no recovery path" 的操作不能误开 |
| **会话级 vs 全局级两套 toggle** | `yolo-session.ts:11/36` | Session 临时 vs 持久改 config——影响范围差几个数量级 |
| **`release_permission_mode_dependents`** | `approval.py:235` | 打开 yolo 替换 computer-use 后端,关闭立刻杀掉——bypass 关闭不留后门进程 |

## 一句话总结

> yolo 让 agent 自由,但永远不能让它自由到删系统。**floors 是审批链最底下的硬地板,yolo 也踩不破**;容器里跑,dangerous 检测会被跳过,deny 是唯一剩下的拦截手段——必须写。

## 复盘

- 一开始我只想搞清楚"yolo 怎么关",顺着扒下来才发现它根本不是单点开关——是三源任一为真的旁路。
- 我之前有个错误印象:docker 容器 = 沙箱 = 安全 = 可以随便开 yolo。实际上 docker 没 host bind mount 时 dangerous 检测被跳过,**deny 是唯一的拦截**——不开 deny 等于完全自由。
- smart 模式是 manual 的**升级**(不是 yolo 的替代),这点容易混淆。
- 反复使用的容器最稳的配置是:**manual 模式 + 写好 deny**——既不烦,又不会被 agent 误操作整垮。
