---
story_id: 9
title: 一个软链接加 8 行 SKILL.md——我怎么用最小的代价记住一个项目
date: 2026-10-01
author: notfresh
status: recorded
tags: [skill, symlink, hermes-agent, project-alias, context-budget]
---

## 起点

我有一个项目，目录叫 `his-pol-phy-think`，是历史·政治·哲学的思辨对话记录库。每次想引用它我都得在记忆里现拼：哪个目录来着？里面什么布局来着？

我想要一个名字——像 "hppt" 这种——说出来就知道指什么。

## 第一步：软链接

最初我想直接在 skill 里硬编码 `his-pol-phy-think`，但每次敲全名都嫌长。

```bash
cd /root/projects
ln -s his-pol-phy-think hppt
ls -la hppt
# lrwxrwxrwx 1 root root 17 Oct  1 05:11 hppt -> his-pol-phy-think
```

**软链接解决的是"指代成本"**——目录真实位置不变，给它一个我能脱口而出的别名。

## 第二步：建 skill

但软链接只能解决"路径"。我想要更多：以后说"加载 hppt"，Hermes 立刻知道这是"准备往里写"。

去建 skill：

```yaml
---
name: hppt
description: Loading hppt = about to write into the dialogue archive.
---

# hppt

- 项目真路径：`/root/projects/his-pol-phy-think/`
  （软链接 `/root/projects/hppt/` 别名）
- 加载 = **准备往里写文章**
- 对话稿落 `对话/YYYY-MM-DD_<主题>.md`
- 新文落档必须同步更新 `README.md`
- 详细约定按需展开
```

第一版我写了 4 KB，把文件骨架、README 写法、写作偏好都堆进去。

**被拒了：连续 3 次 YAML parse 失败**——description 字段超 60 字符硬限制。

我把整篇砍到 8 行。**反而更好。**

## 第三步：发现——这两个东西不是一回事

写到一半才意识到：软链接解决的是**指代**（"是什么"），短 skill 解决的是**触发语义**（"什么时候用、用来干嘛"）。它们解耦。

| 关注点 | 软链接 | 短 skill |
|---|---|---|
| 项目在哪 | ✓ | — |
| 叫什么名字好记 | ✓ | — |
| 触发条件（"加载 hppt"） | — | ✓ |
| 写到哪、命名规范 | — | ✓（写到 SKILL.md 里） |
| 详细写作约定 | — | ✗（**故意不写**，按需查项目自带的 README） |

**关键：详细约定不放在 skill 里**——让它留在项目自己的文档里。SKILL.md 只是"入口锚点"：路径 + 触发 + 一句话定位。

## 为什么短 skill 是对的

Hermes 的 skill 系统是**按需注入上下文**的。memory 是无差别注入每轮——同样花 token，给整个项目路径当背景就太重了。

```yaml
description: Loading hppt = about to write into the dialogue archive.
```

13 个英文单词。**永远只占这点位置**。剩下的内容（骨架怎么写、README 怎么更新）按需 `read_file` 到 `his-pol-phy-think/README.md` 自己查——那个仓库本来就有手维护的索引，**事实该在的地方就是那**。

## 这个模式可以推到哪

- **项目位置/入口语义** → 短 skill 锚定（每次加载都该有的）
- **项目内详细约定** → 留在自己文档里（按需查，不污染每轮上下文）
- **软链接 alias** → 给人用的（"hppt" 比 "his-pol-phy-think" 好记）
- **skill 名字** → 给 Hermes 用的（路由触发条件）

两者各管各的，别混。

## 一句话总结

> 软链接解决"指代"，短 skill 解决"触发"，详细约定留在项目里——三件事拆开，每次上下文只花该花的 token。

## 复盘

- 我自己一开始下意识把 skill 写得像 README——本能想让"加载了就能直接动手"。但忽略了 Hermes 上下文是有预算的。
- 软链接+短 skill 这个组合，本质是把"高频锚点"（路径+触发）放贵的地方（每轮上下文），把"低频详情"（写作骨架）放便宜的地方（按需读文件）。
- 跟 story-8（skill 三种出身判定）的味道有点像：都是用**最小命令/最小结构**把一个重复问题钉死。