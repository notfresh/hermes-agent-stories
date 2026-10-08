# Graphiti：给知识图谱装上时间轴（Zep 的开源核心）

> 2026-08-26 · 上下文专题 · 业界项目剖析（第三篇）
> 剖析对象：[getzep/graphiti](https://github.com/getzep/graphiti)（30.3k stars，Apache-2.0，Zep 的开源核心）＋ 宿主产品 [getzep/zep](https://github.com/getzep/zep)
> 本地源码：`/root/projects/graphiti/`（浅克隆，所有行号实测自该副本）
> 与专题主线的连接：**"时间感知记忆"路线的代表**——每条事实带双时间轴，能回答"当时的事实是什么"。

---

## 〇、先说仓库事实（Zep 的形态）

- **Zep 产品** = Zep Cloud（托管 agent 记忆平台），SDK：`zep-cloud`（Python）/ `@getzep/zep-cloud`（TS）
- **开源核心 = Graphiti**：`getzep/zep` 仓库 README 明说"这不是 Zep 的产品或服务，是示例/集成"，并指路 Graphiti——**Zep 的开源价值 100% 在 Graphiti**（30.3k stars vs zep 4.9k）
- 图数据库驱动：Neo4j / FalkorDB / Neptune（Kuzu 已废弃）

一句话定位：**实时增量构建的知识图谱引擎——从对话/文档中提取实体和关系，每条关系带"何时成立、何时失效"的时间轴，支持按时间查询"当时的事实"。**

## 一、记忆形态：三层节点 + 带时间轴的边

```
Episodic 层（情景）：原始 episode 原文（"用户 8 月 20 日说……"）
   │  HAS_EPISODE 边（episode 提到哪些实体）
   ▼
Entity 层（语义）：去重后的实体（人物/公司/概念）——带周边摘要
   │  RELATES_TO 边 = 事实陈述（"A 收购了 B"）——带双时间轴
   ▼
Community 层（社区）：label propagation 聚类出的社区 + LLM 摘要
```

**EntityEdge 是灵魂**（`graphiti_core/edges.py:263`）：

```python
class EntityEdge(Edge):
    fact: str                      # 事实陈述（"X 于 2024 年收购了 Y"）
    fact_embedding: list[float]    # 事实的向量（检索按边检，不是按节点！）
    valid_at: datetime | None      # 事实开始为真的时间
    invalid_at: datetime | None    # 事实停止为真的时间
    expired_at: datetime | None    # 系统发现并失效这条边的时间
    reference_time: datetime | None  # 产生这条边的 episode 的时间戳
    episodes: list[str]            # 引用这条边的来源 episode id（可追溯）
```

## 二、写路径：add_episode 增量流水线（graphiti.py:980）

```
Phase 1 取前情        retrieve_episodes：拿这个 group 的最近 episode 做上下文
Phase 2 提取节点      extract_nodes：LLM 从新 episode 提取实体
Phase 3 对齐节点      resolve_extracted_nodes：与已有实体合并（uuid_map 去重）
Phase 4 提取+解析边   _extract_and_resolve_edges（与属性提取并行）：
                     返回 (resolved_edges, invalidated_edges, new_edges)
                     ——新信息发现旧事实过期 → 旧边被失效
Phase 5 属性提取      extract_attributes_from_nodes：节点属性 + 摘要
Phase 6 保存 episode  _process_episode_data：存原文，建 HAS_EPISODE /
                     NEXT_EPISODE 边（连续 episode 串成时间线）
Phase 7 更新社区      可选 update_communities：每个新节点增量更新所属社区
```

**两个区别于普通 GraphRAG 的关键**：

1. **增量，不重建**：每来一段对话只做局部提取 + 对齐，图随对话实时长大——GraphRAG 是批处理建图，Graphiti 是流式建图
2. **边失效（edge invalidation）**：新信息与旧事实冲突时，LLM 判定旧边 `invalid_at`/`expired_at`——图自己会"遗忘"，不留矛盾事实

## 三、双时间轴：记忆的"时间旅行"能力

EntityEdge 有四个时间字段，构成**双时间轴**：

| 轴 | 字段 | 回答的问题 |
|---|---|---|
| 事实时间 | `valid_at` → `invalid_at` | 这条事实**在现实中**什么时候成立/失效（"用户 2024 年住北京"） |
| 知识时间 | `created_at` / `expired_at` | 图库**什么时候知道** / 什么时候失效（摄入时间） |
| 来源时间 | `reference_time` | 哪段对话产生了它 |

- `EpisodicNode.valid_at`（`nodes.py:322`）= 原文创建时间——双时间轴的"事件时间"地基
- 检索时可指定 `reference_date`：**只返回那个时间点成立的事实**——"查 2024 年用户说过什么"不会混入 2025 年的信息
- 对比：Mem0 的 OSS 版时间能力是关闭的；Graphiti 的时间轴是核心卖点

## 四、读路径：四 scope × 三手段的混合检索

`search()`（`search.py:98`）按 `SearchConfig`（`search_config.py:112`）配置四个检索范围：

```
edge / node / episode / community  四个 scope（可组合）
  ×  fulltext（BM25 关键词）
  ×  similarity（向量）
  ×  bfs（图遍历：从中心节点沿关系扩展）
  +  MMR 重排（cross_encoder）
  +  时间过滤（只取当时成立的事实）
```

- `hybrid_node_search`（`search_utils.py:1163`）把多手段结果融合
- **社区检索**（`community_search`，`search.py:764`）：全局性问题走社区摘要——GraphRAG 同源思路
- 检索的单位是**边（事实）**不是节点——"A 和 B 有什么关系"直接命中

## 五、社区：label propagation + LLM 摘要

- `get_community_clusters` → **label propagation（标签传播）**聚类（`community_operations.py:93`，不是 Leiden）
- `build_community`（`:174`）：每个社区生成一个 CommunityNode + LLM 写的摘要
- `update_community`（`:340`）：新节点增量归入社区，不整图重算
- 用途：全局检索（"这些实体间整体什么关系"）+ 规模化（社区摘要代替逐边遍历）

## 六、三个关键设计决策（为什么）

**① 为什么把时间轴放在边上，而不是节点上？**
事实（关系）才是会变的：关系有成立/失效，实体本身只是存在。`valid_at/invalid_at` 在边上，才能精确表达"这段关系只在这段时间成立"；节点时间只记录原文创建。

**② 为什么检索按边（事实）不按节点？**
问题通常是"关系"导向的："A 影响谁"、"B 的供应商是谁"。事实向量化（`fact_embedding`）让"语义相似的事实"可检索——这是图 + 向量融合的关键设计。

**③ 为什么增量 + 失效，而不是重建？**
对话是流式的，图必须实时可用；重建成本随图大小爆炸。失效机制保证图里不留矛盾——这解决了向量记忆的"事实堆叠冲突"问题（Mem0 靠 UPDATE/DELETE，Graphiti 靠时间轴 + 失效）。

## 七、与专题主线的对照

**Graphiti 的时间轴 = 你的"TTL + provenance"的图增强版**。你设计里的 `time`（何时记住）和 `context`（来源），Graphiti 用 `valid_at/invalid_at/expired_at/reference_time` 四字段做成了查询能力——不只是"可追溯"，是"可回放当时的世界"。

| 维度 | 你的设计 | Graphiti 对应 |
|---|---|---|
| 来源可追溯 | context（session/message） | `episodes` 引用链（episode id） |
| 生命周期 | TTL（先验）+ 后验修正 | 时间轴（valid/invalid）+ 边失效 |
| 情景/语义分层 | 情景记忆 vs 语义记忆（Tulving） | Episodic 层 vs Entity 层（同源） |
| 冲突处理 | 用户纠正 P3 覆盖 | 边失效（LLM 判定，无用户参与） |
| 全局视角 | （未设计） | 社区摘要（GraphRAG 同源） |

**对照结论**：Graphiti 验证了"记忆必须带时间 + 来源"的判断，且把时间做成了**一等查询维度**（这是它超越 Mem0/Letta 的地方）。但它仍是 LLM 主判（提取/失效都靠模型），且依赖图数据库（Neo4j/FalkorDB）——部署重，不适合教学级项目。你的规则引擎路线（轻、可审计）+ 时间轴思想（抄它的四字段模型）是合理组合。

## 八、源码导航

```
graphiti_core/graphiti.py            主入口：add_episode(:980) / search(:1527)
graphiti_core/nodes.py               EpisodicNode(:318) / EntityNode(:499)
graphiti_core/edges.py               EntityEdge(:263) —— 双时间轴字段
graphiti_core/search/search.py       edge/node/episode/community 四检索
graphiti_core/search/search_utils.py fulltext/similarity/bfs 实现 + hybrid(:1163)
graphiti_core/utils/maintenance/community_operations.py  label propagation(:93)
graphiti_core/driver/                Neo4j / FalkorDB / Neptune 驱动
graphiti_core/prompts/               LLM 提取提示词（实体/关系/失效判定）
```

阅读顺序：edges.py 的 EntityEdge（时间轴模型）→ graphiti.py 的 add_episode（写路径）→ search/（读路径）→ community_operations（社区）。

---

*本文行号基线：`/root/projects/graphiti/` 浅克隆副本（2026-08-26）。仓库演进后行号可能漂移。*
