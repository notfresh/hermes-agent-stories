---
story_id: 11
title: Hermes 一周 2000 commit——我的私有特性怎么活下来
date: 2026-10-06
author: notfresh
status: recorded
tags: [git, rebase, patch, fork, hermes-agent, three-way-merge, weekly-sync]
---

## 起点

我给 Hermes 加了一个特性，写在 `feature-zx` 分支里，但作者不会合。

主仓不管不顾地狂奔——一周不见，commit 数就奔 2000。

我有两个困境：
- 不能合掉上游，担心**错过**作者后面要做的事
- 不能扔掉我的特性，这是我自己用的核心

"fork + 长期跟随 + 私有特性不被冲掉"——怎么破？

## 答案骨架

主仓房东，我的家具墙绘。每周房东重装一次，我每次得把自己的家具再搬进去一遍。

**两种搬家具的方式**：

| 方案 | 动作 | 适用 |
|---|---|---|
| **rebase** | 把特性整段历史**重放**到新主仓之上 | 低频维护 / 特性深入主仓 |
| **patch + 3-way merge** | 把特性导成 patch，**每次重打**到新主仓之上 | 高频更新 / 特性小且边界清晰 |

## 为什么 Hermes 优先 patch

**三条护城河**：

1. **特性小，主仓大**——你改的几十行最小覆盖范围，主仓一周 2000 commit 不必然撞你那些改的那几处
2. **冲突面是特性大小**，不是主仓大小——三路合并只在"你特性改的文件**且**主仓也动过"的地方报冲突，通常就那么几行
4. **rebase 是反过来的"大驱动小"**——重放整个特性历史，主仓动多少你就重装多少

一句话：**"特性小、主仓大"是常态，不是侥幸**——patch 方案能扛。

## diff、rebase、patch 三件套

**这三件是不同物种，别混。**

```
diff    A B    →  问"从 A 到 B 要做多少增量"（只读，不动分支）
rebase  A onto B →  把 A 自分叉后的全部提交，重放到 B 之上（改写历史）
patch + 3-way   →  拿 patch 当意图，祖宗 B + 主仓 A + 你 C 三路合并
```

**diff 的三个默认：** 

```
git diff         → 工作区 vs HEAD（改了啥但没暂存）
git diff --staged  → 暂存区 vs HEAD（暂存了啥，待发）
git diff HEAD     → 工作区+暂存区 合 vs HEAD（所有未提交）
```

**rebase 的本意：** re-base，重新定基。把 A 这棵树枝嫁接到 B 这棵新干上。提交内容不变，但所有提交的 hash 全部变了。

**patch 的本意：** 一份 patch = 一组"坐标 + 期望内容"指令。`@@ -10,7 +10,7 @@` 告诉 git "在原文件第 10 行起，找上下文对得上的 7 行，把 `print('old')` 换成 `print('new')`"。

## 三路合并怎么工作

```
上游 A        我的 C（fork 现在）
  │              │
  └───┬──────────┘
      ▼ 找共同祖先 B
  上次成功 sync 时的快照
```

三个人开会：

| 角色 | 代表 | 立场 |
|---|---|---|
| 祖宗 B | 上次 sync 成功的版本 | 中立裁判 |
| 上游 A | 主仓现在变成啥了 | "我要这样变" |
| 你 C | 你 fork 现在变成啥 | "我要那样变" |

四种结局：

- A 和 C 都没动 → ✅ 自动过
- 只 A 动了 → ✅ 取 A（你 patch 让位）
- 只 C 动了 → ✅ 取 C（你特性保留）
- **A 和 C 都动了同一处** → ⚠️ **停下来让你选**

**为什么不是两路：** 两路 patch（`git apply` 严格匹配）只对比"patch 上下文 vs 当前文件"，文件一动就废。三路多了祖宗 B 当锚点，**抗主仓暴动**就靠这一手。

## 一周一次的 sync 脚本

```bash
# 1. 一次性：把特性导成 patch
git diff upstream/main..feat/my-xxx > ~/feat-my-xxx.patch

# 2. 每周跑一次：
git checkout main && git pull upstream main
git checkout feat/my-xxx && git merge main # 先 merge 别 rebase
git apply --3way ~/feat-my-xxx.patch         # 三路合并
git add -A && git commit -m "sync: reapply feat-my-xxx"
```

**为什么 merge 不用 rebase：** 主仓更新太快，rebase 累计冲突爆雷；merge 主仓后只重打你**这份 patch**（特性体积可控），3-way merge 还能自动解掉一部分。

## 什么时候该换姿势

- 特性改了主仓核心文件（agent 主循环 / model 层）→ patch 每周撞墙，该用 rebase 或干脆上不赶
- 特性提交被上游合了 → patch 优雅过期，走退场
- 特性越叠越大、文件越改越绕 → patch 拆成多个小 patch，边界最小化

## 收尾

Fork + 长期特性分支 + 每周 patch 重打 = 我跟上慢主仓的姿势。特性是你的，冲突面可控，作者合了你优雅退场，不合你永久持有。

**一句话总结：** patch 在 Hermes 这种"一周2000 commit 主仓"下能扛，靠的是"特性小、主仓大"是常态；特性深入主仓内核才是 rebase 的主场。