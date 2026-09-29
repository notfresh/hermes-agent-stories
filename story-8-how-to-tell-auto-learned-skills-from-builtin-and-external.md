story_id: 8
title: 一行命令分清 skill 三种出身——我以为很简单，结果卡了我三轮
date: 2026-09-29
author: notfresh
status: recorded
tags: [skill, curator, hermes-agent, introspection]
---

# 一行命令分清 skill 三种出身——我以为很简单，结果卡了我三轮

> 起因：我列了 `~/.hermes/skills/` 的目录，以为数数就能分清。结果错了三轮。

## 第一轮：天真版本

我有个朴素的需求：自动学习出来的 skill 有哪些？不要内置的，也不要我从外部下载/手动装的。

打开 `~/.hermes/skills/`，扫一眼，42 个分类文件夹。心想：76 个内置的减掉……等下，76 这个数字哪来的？我都不知道哪 76 个是内置。

## 第二轮：找「出处标记」

直觉告诉我，Hermes 一定记了「谁建的」。这种记账的工作它肯定干过，不然 7 万多行的 agent 怎么会知道哪个 skill 是自己带的、哪个是后加的。

扫了一遍 `~/.hermes/skills/`，看见两个「长得像账本」的隐藏文件：

| 文件 | 大小 | 一开始我以为它是 |
|---|---|---|
| `.bundled_manifest` | 3.6 KB | 不知道 |
| `.curator_ledger.jsonl` | 209 KB | 某种日志 |

先读 `.bundled_manifest`，76 行，每行 `名字:哈希`，**白名单**——名字在里面就是内置的，不在就不是。✓ 第一个判定器到手。

再读 `.curator_ledger.jsonl`，每行一条 JSON 记录：

```json
{"id": "...", "ts": "...", "actor": "curator",
 "action": "create", "skill": "hermes-source-modification", ...}
```

`actor` 字段：要么 `curator`，要么 `agent`。**这就够了**。

```
curator = Hermes 后台那个每周跑的程序，从历史会话里抽取可复用流程
agent   = 你或 AI 主动调用 skill_manage create 命令建的
```

## 第三轮：交叉验证，把三类彻底分开

跑了个 Python 脚本：

| 来源 | 数量 | 判定条件 |
|---|---|---|
| 内置 | 76 | 名字在 `.bundled_manifest` 里 |
| 外部安装 | 4 | ledger 里 `actor=agent` 的 `create` 记录 |
| **自动学习** | **20** | **ledger 里 `actor=curator` 的 `create` 记录** |

三个判定器**两两不重叠**：内置的不会出现在 ledger 里（manifest 是只读白名单）；外部安装和自动学习都写 ledger，但 `actor` 字段二选一，互斥。

那行「一行命令」就是：

```python
import json
from pathlib import Path
seen = {}
for line in Path('/root/.hermes/skills/.curator_ledger.jsonl').read_text().splitlines():
    r = json.loads(line)
    if r.get('action') == 'create' and r.get('actor') == 'curator':
        seen.setdefault(r['skill'], r['ts'][:10])
for s, ts in sorted(seen.items(), key=lambda x: x[1]):
    print(f'{ts}  {s}')
```

## 我现在知道的 20 个自动学习 skill

```
2026-09-02  hermes-source-modification
2026-09-02  historical-claim-verification
2026-09-02  image-ocr
2026-09-03  personal-knowledge-base
2026-09-03  graphiti-mcp-ops
2026-09-03  technical-training-material
2026-09-04  shell-command-hygiene
2026-09-07  flask-quiz-site-operations
2026-09-08  headless-cdp-visual-verification
2026-09-08  chrome-cdp-screenshot
2026-09-10  java-spring-scheduled-task
2026-09-10  spring-feature-addition
2026-09-18  cosyvoice-300m-cpu-clone
2026-09-20  internet-cognitive-scope-archiver
2026-09-23  podcast-audio-production
2026-09-23  podcast-production
2026-09-23  podcast-audio-pipeline
2026-09-24  essay-to-stories-repo
2026-09-26  disk-space-triage
2026-09-28  pr-analysis
```

## 教训：两个账本，一个偏置

`actor` 字段只有两个值是**有意为之**——把「自动 vs 手动」的二元区分**内化进数据**，而不是事后去推断。推断容易错，比如「看 SKILL.md 里的 metadata」会被同名 skill 复用搞混，「看修改时间」会被你手改一个老 skill 骗到。

`bundled_manifest` 用纯文本 `名字:哈希` 而不是 YAML/JSON——也是为了让「白名单」一眼可读、AI 不会去 parse 失败。这俩文件都不是「配置」，是**断言**：内置就是内置，不会因为你改了它就变成非内置。

附带一个边角发现：ledger 是 2026-09-02 才开始的，所以 102 个「孤儿」skill 在磁盘上有、ledger 里没记录——这些是 ledger 上线前就存在的，**靠 ledger 反推不出来源**，只能看 `ls -lt` 或读 frontmatter 猜。这是另一个故事了。

## 一句话总结

> **自动学习 = 不在 `.bundled_manifest` 里 + `.curator_ledger.jsonl` 里有 `actor=curator` 的 `create` 记录。**
>
> 两个账本：`~/.hermes/skills/.bundled_manifest`（内置白名单）+ `~/.hermes/skills/.curator_ledger.jsonl`（创建流水）。
