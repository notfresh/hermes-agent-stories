---
story_id: 5
title: 一条原则打破了我对「ABC + orchestrator」的想象
date: 2026-09-28
author: notfresh
status: recorded
tags: [hermes, design-pattern, abcs, orchestrator, reading-source]
---

# 一条原则打破了我对「ABC + orchestrator」的想象

## 起点：一个看上去很整齐的词

我最近在啃 Hermes 的源码图谱。图谱里有这么一条原则，名字很长，叫 `principle.hermes-abc-orchestrator-extension-pattern`。

我第一次看到它，脑子里立刻冒出一个标准的图景：抽象基类（abstract base class，下面我都叫 ABC）+ 一个编排器（orchestrator，负责决定走哪条路）+ 一个内置 provider（provider 就是"实际干活的那一档"）。三件套，齐了。

这是我熟悉的"可扩展架构"模板——第三个 PR 进来之前写好 ABC，第三个 PR 进来之后写一个 orchestrator 把它路由过去，再给一个开箱即用的内置 provider 让别人抄。这是教科书答案，我以为可以照着抄一段就完事。

但事情没这么简单。

## 第一跳：图谱里的原则描述

我顺着原则描述往下读。desc 一句话总结讲的是：当有"3 个以上的 provider 实现"这种场景时，应该用 ABC + orchestrator 的模式来扩展。

这句话本身没毛病。我同意——超过三个分支，确实需要个调度层来管。但我还是想知道：Hermes 自己是不是真的这么做的？原则写出来是一回事，源码做不做得到位是另一回事。

于是我跳进源码看。

## 第二跳：MemoryProvider 这块是齐的

第一个看的是 `MemoryProvider`——也就是 Hermes 里负责记忆的 provider。

打开一看，心里踏实了：

- 有个抽象基类（Provider）——ABC 在；
- 上面挂了一个 `MemoryManager`，专门做调度——orchestrator 在；
- 默认实现是 `MemoryStore`，是个内置 provider——内置 provider 也在。

三件套，齐了。我甚至有点想关掉文件走人——你看，原则和实现对得上，没什么可说的。

但转念一想：Hermes 不止一个 provider 吧？我先去把其他几个 provider 也扫一眼。

## 第三跳：另外两个 ABC 不太一样

这一扫，问题来了。

`ProviderTransport` 是处理 provider 跟外部世界怎么连的。我跳进去一看：没有 orchestrator。它是按一个叫 `api_mode` 的开关做单选——要么走这条线，要么走那条线，本质上就是个开关。ABC 是有的，内置 provider 是有的，但中间没有调度层。

`ContextEngine` 是管上下文的组装方式的。结果更直接：默认情况下，整个系统就一个 ContextEngine 实例——单实例，连"选哪条路"的问题都没有，更谈不上需要 orchestrator 了。

所以真实情况是这样的：

- MemoryProvider：ABC + orchestrator + 内置 provider，齐全；
- ProviderTransport：ABC + 内置 provider，但用开关选路；
- ContextEngine：ABC + 内置 provider，单实例。

「ABC + orchestrator + 内置 provider」这三件套，根本不是铁三角。它只是 MemoryProvider 这一家特殊的做法。

我之前以为它是"通用模板"，结果它只是一个具体案例的描述。

## 第四跳：内置 provider 也不简单

但这一跳还顺手发现了一件小事，让故事多了一层。

`MemoryStore` 这个内置 provider 不只是"第一个普通 provider"——它还背了一个特殊的责任：兜底防合并失控。具体来说，是有一个阈值（`MAX_CONSOLIDATION_FAILURES_PER_TURN` 等于 3）——一轮里合并失败三次就停手，不再继续。

这是什么？这是工程里的安全阀。一个 provider 同时是默认实现，又兼带"防失控"的护栏——这不是简单的"先有个内置的让人抄"，这是"内置 provider 天然背了其他 provider 不背的责任"。

这意味着什么？意味着**内置 provider 不是普通 provider 的样板，它是一个特殊的角色**。我之前完全没意识到这一点——以为"内置"就是个"先有一个能跑的"。

## 第五跳：原则的 note 都写错了

再回到那条原则本身。我顺手翻了一下它的 note——也就是附在原则下面的解释文字。

note 里给了一个文件名做引用：`memory_tool.py` 的某一行。我按图索骥去找——找不到。然后我换个角度搜了一下"防合并失控"相关的逻辑，定位到了 `memory_tool_store.py` 的另一个位置。

也就是说：原则自己的注解引用的位置，和实际代码的位置，已经对不上了。

这是个小事。但小事背后是大事：**这条原则还在演化**。如果它已经稳定，作者会顺手把 note 也更新；如果 note 还引用着旧路径，说明原则本身可能还要继续改。也可能作者和我一样，懒得动那行 note——但无论哪种，都说明这不是一条"已经定型"的结论。

## 重述这条原则

把这一路的发现串起来，那条原则其实应该这样说：

> 当一种 provider 有"多份实现需要被路由"这种业务形态时，给它配一个 orchestrator；当它只有几种固定模式或单实例时，开关或单例就够了；内置 provider 还会天然背一些额外的护栏责任，不只是"先有个能抄的"。

翻译成大白话：

- **MemoryProvider 为什么有 orchestrator**：因为它真的有很多种实现需要被挑着用；
- **ProviderTransport 为什么不需要**：因为它的"路由"本质上是个单选开关；
- **ContextEngine 为什么不需要**：因为它默认就一个，没什么好挑的；
- **MemoryStore 这个内置 provider 为什么特殊**：因为它还要在后台守一道安全阀。

三件套从来不是"三个一组齐刷刷地摆出来"。它是一组**按业务形态来裁剪的零件**——多 provider 路由就加 orchestrator；模式少就开关；只有一个就单例；内置 provider 还可能顺手背一个兜底。哪里需要装哪里，不需要的就别硬装。

## 我带走的

我读 Hermes 一直有一个冲动：把读到的模式抽象成一句通用的金句，写到图谱的 desc 里。这次最大的教训是——**原则要简单，但简单不是僵化**。金句写出来越整齐，离真实代码就越远。

真正的"原则"，应该长成一句"什么时候需要、什么时候不需要"的话，而不是一个"三个零件摆齐"的图景。

下次再看到"ABC + orchestrator"这种整齐的词，我先别急着抄，先去源码里数数：到底有几个 provider？它们之间是不是真的需要被路由？还是只是看起来需要？

整齐，是给读者看的；按形态裁剪，是给代码活的。
