# 手写一个 Agent（第三篇）：上下文压缩——给 Agent 长记性

> 教程系列 · 第三篇。前两篇给了 Agent 大脑和手脚，但它有个致命弱点：**金鱼记忆**。每轮对话都把全部历史重发一遍，聊得越久请求越大，token 费用线性上涨，最终撑爆上下文窗口——长任务跑到一半，Agent 就"失忆"了。这一篇给它装上记忆管理：**记住重要的，忘掉琐碎的**。
>
> 配套代码在 [`examples/tutorial-03/`](https://github.com/notfresh/hermes-agent-stories/tree/main/examples/tutorial-03)，跑 `python test_store.py` 就能验证（10 个离线测试，不需要 API key）。本文所有片段都标了行号，可对着源文件看。

---

## 一、先看问题有多严重

Agent 的对话历史是个列表，每次调模型都**全量**发过去：

```python
response = client.chat.completions.create(
    model="deepseek-chat",
    messages=messages,   # ← 全部历史，一条不少
)
```

第一篇就是这么写的，当时没问题——对话只有两三轮。但 Agent 的本职是长任务：读 20 个文件、跑 10 次工具、来回确认。每轮追加两条消息，请求体积线性上涨：

```python
m = MessageStore([{"role": "system", "content": "S"}])
sizes = []
for i in range(6):
    m.append({"role": "user", "content": "U" * 300})
    m.append({"role": "assistant", "content": "A" * 300})
    sizes.append(m.approximate_tokens())

assert all(sizes[i] < sizes[i + 1] for i in range(len(sizes) - 1)), sizes
assert sizes[-1] > sizes[0] * 3, f"6 轮后应涨 3 倍以上: {sizes[0]} → {sizes[-1]}"
print(f"  每轮请求体积: {sizes}")
ok("不压缩时请求体积线性上涨")
assert m.count() == 13  # system + 6*2
ok("消息数也线性上涨（13 条）")
```

实测曲线（`test_store.py` 的 A 组）：每轮 300 token，6 轮后 1800——**涨了 6 倍，而"新信息"只占最后 1/6**。前 5/6 都是重复发送的旧历史，每轮都在为它们付钱。

涨到头是什么？上下文窗口。模型能一次吃进的 token 有上限（128K、200K……），超了 API 直接拒绝。也就是说：**不管理的对话，长度是硬死刑，不是慢性问题。**

还有个隐藏成本：窗口被旧历史占满后，模型"看不到"最早的关键约定（"这次任务的输出格式是……"），行为开始漂移。

所以压缩要同时解决三件事：**省钱、不撑爆、不忘约定。**

---

## 二、压缩的最小正确做法

真实框架的压缩是让 LLM 给旧历史写摘要。但那引入新问题：摘要要再调一次模型（花钱、慢、摘要本身可能丢关键信息）。

教学版用最朴素的一招近似：**丢中间，保头尾**。

- **保头**：system 消息（人设 + 任务约定）绝对不动
- **保尾**：最近的几轮对话（模型正在处理的上下文）
- **丢中间**：最早的那段历史——它们的信息大概率已经被后续对话消化了

这跟人类记忆很像：你记得刚才在干什么、记得任务目标，忘了中间翻过的第 7 个文件。

### 但有一个不能碰的地方

消息不是平等的。对话里有个**原子结构**：

```
assistant（带 tool_calls："我要调 get_weather"）
  └─ tool（"结果：北京晴，25℃"）      ← 必须跟它上面的 assistant 在一起
```

API 规定：`role=tool` 的消息前面**必须**是带 `tool_calls` 的 assistant。拆散了——比如压缩时只丢了 assistant、留下 tool——API 直接报错：

```
tool must be a response to a preceding message with tool_calls
```

这是本篇的核心约束：**压缩按"块"丢，块内配对，绝不拆散。** 第一篇埋下的"assistant/tool 成对"伏笔，在这里兑现。

---

## 三、实现：仓库 + 压缩

### 3.1 消息仓库：循环不直接碰列表

第一篇的 `messages` 是个裸列表，循环里到处 `messages.append(...)`。消息一多，这些散落的操作就成了 bug 温床。收拢成一个类（`store.py:16-17`，节选）：

```python
class MessageStore:
    """消息列表的唯一入口。循环通过它读写消息。"""
```

循环只剩两个动作：`append`（写）和 `compress_if_needed`（压缩）。列表的访问收敛到一处，配对约束才有地方统一执行。

### 3.2 先估体积（`store.py:50-62`）

```python
    def approximate_tokens(self) -> int:
        """粗略估算当前消息总 token 数（教学版用字符数/2 近似）。

        真实估算要考虑 tools 定义、图片、缓存命中——教学版够用即可。
        """
        total = 0
        for m in self._messages:
            content = m.get("content", "")
            if isinstance(content, str):
                total += len(content)
            for tc in m.get("tool_calls", []) or []:
                total += len(tc.get("function", {}).get("arguments", ""))
        return max(1, total // 2)

```

**注意这是"估算"不是"精确计数"。** 真实 token 数要用 tokenizer 算，还要算上 tools 定义、图片——但压缩决策不需要那么精确：阈值设 8000，估算误差 ±20%，无非是早点压晚点压。教学版用"字符数 ÷ 2"近似（中文约 1.5-2 字符一个 token）。

**估算准错了会怎样？** 压早了浪费（历史其实放得下），压晚了 API 报错。所以生产框架会在估算上加安全余量，或者干脆用 tokenizer 精确数。这是个精度换简单度的权衡，教学版选简单。

### 3.3 压缩入口（`store.py:64-78`）

```python
    def compress_if_needed(self, max_tokens: int, keep_tail_blocks: int = 3) -> bool:
        """如果超长，按"块"丢中间历史（保留 system + 最近 K 个完整块）。

        关键约束：tool 消息必须随其 assistant 一起丢或留，绝不能产生孤儿
        ——OpenAI/DeepSeek 都拒绝"role=tool 但前面没有带 tool_calls 的
        assistant"的消息序列。

        块的定义：一个 assistant（带 tool_calls 或纯文本）+ 它后面的
        所有 tool 消息 + 收尾的 user/assistant，是一个原子单元。
        压缩按块丢，不会拆散配对。

        Returns: 是否发生了压缩。
        """
        if self.approximate_tokens() <= max_tokens:
            return False
```

返回值是"是否发生了压缩"——循环拿它做统计。两个参数：`max_tokens` 触发线，`keep_tail_blocks` 保尾块数。

### 3.4 核心：按块切分（`store.py:83-103`）

```python
        # 1. 把消息流切成原子块
        atomic_blocks: list[list[dict]] = []
        current: list[dict] = []
        for msg in body:
            role = msg.get("role")
            if role == "assistant":
                # 新 assistant 开新块（上一个块到此为止）
                if current:
                    atomic_blocks.append(current)
                current = [msg]
            elif role == "tool":
                # tool 跟当前块（它属于最近的 assistant）
                if current:
                    current.append(msg)
                else:
                    atomic_blocks.append([msg])  # 孤儿 tool 包成伪块，不丢
            else:
                # user / 其他 → 挂在当前块尾
                if current:
                    current.append(msg)
                else:
```

切块规则一句话：**遇到 assistant 就开新块，tool 和 user 挂到当前块尾。**

这样每条 tool 天然跟它所属的 assistant 在同一块里——按块丢，配对永远不会拆散。这就是把"原子结构"直接编码进数据结构，而不是靠小心翼翼的边界检查。

### 3.5 保留尾部（`store.py:105-126`）

```python
        if current:
            atomic_blocks.append(current)

        # 2. 块不够多就别丢（丢了头部对话就没意义了）
        if len(atomic_blocks) <= keep_tail_blocks:
            return False

        # 3. 保尾部 K 个完整块
        kept = atomic_blocks[-keep_tail_blocks:]
        dropped = sum(len(b) for b in atomic_blocks[:-keep_tail_blocks])

        # 4. 重组：system + 提示 + 尾部块
        new_messages = list(head)
        if dropped > 0:
            new_messages.append({
                "role": "system",
                "content": f"[历史压缩：已丢弃中间 {dropped} 条消息]",
            })
        for block in kept:
            new_messages.extend(block)

        self._messages = new_messages
```

三处细节：

- **块不够 K 个就不丢**（`store.py:109-111`）：只剩 2 块还硬压，等于把对话的开头都丢了——模型连"用户最初要什么"都不知道。宁可这轮超限，也不做破坏性压缩。
- **压缩要留痕迹**（`store.py:115-119`）：插入一条 system 提示"[已丢弃 N 条]"。模型知道历史被截断，回答时不会假装记得。
- **丢的是"信息密度最低"的中间段**——头尾保留，这是保头尾算法的全部。

跑一下（`store.py:129-135` 的演示）：

```python

if __name__ == "__main__":
    # 演示：超长对话压缩前后
    m = MessageStore([{"role": "system", "content": "你是助手。"}])
    for i in range(8):
        m.append({"role": "user", "content": f"问题{i}。" + "细节" * 200})
        m.append({"role": "assistant", "content": f"回答{i}。" + "内容" * 200})
```

```
压缩前: 17 条消息, ~3234 tokens
压缩后: 7 条消息, ~1022 tokens (压缩=True)
  [0] system    '你是助手。'
  [1] system    '[历史压缩：已丢弃中间 11 条消息]'
  [2] assistant '回答5。……'
  ...
```

3234 → 1022 token，**省 68%**，而最近三轮对话完整保留。

---

## 四、验证：压缩没拆散配对

压缩最大的风险就是拆散 assistant/tool 配对——平时单元测试根本测不到（对话短不触发压缩），一上长任务就炸 API。所以这部分测试是本篇的重点（`test_store.py:104-121`）：

```python
# 无孤儿 tool：每条 tool 前面必须是带 tool_calls 的 assistant
orphans = []
for i, msg in enumerate(msgs):
    if msg["role"] == "tool":
        prev = msgs[i - 1] if i > 0 else None
        if not (prev and prev["role"] == "assistant" and prev.get("tool_calls")):
            orphans.append(i)
assert not orphans, f"孤儿 tool: {orphans}"
ok("压缩后无孤儿 tool 消息")

# 保留的 tool_call_id 与 tool 消息一一对应
assistant_ids = set()
for msg in msgs:
    for tc in msg.get("tool_calls", []) or []:
        assistant_ids.add(tc["id"])
tool_ids = {msg["tool_call_id"] for msg in msgs if msg["role"] == "tool"}
assert tool_ids <= assistant_ids, f"tool 引用了不存在的 id: {tool_ids - assistant_ids}"
ok("tool_call_id 与 assistant 的 tool_calls 对得上")
```

两个断言各守一边：

- **无孤儿**：每条 tool 前面必须是带 tool_calls 的 assistant——防"拆散"
- **id 对得上**：tool 的 `tool_call_id` 必须能在某个 assistant 的 `tool_calls` 里找到——防"配错对"

跑全部测试：

```bash
cd hermes-agent-stories/examples/tutorial-03
python test_store.py    # 10 个测试，不用 API key
python store.py         # 看压缩前后的消息列表
```

```
【A】成本曲线：不压缩时请求体积 [300, 600, 900, 1200, 1500, 1800] ✓
【B】压缩触发：未超阈值 noop / 块不够不丢 / 超了才压 ✓
【C】配对完整：压缩后无孤儿 tool / id 对得上 / system 保留 ✓
【D】边界：all() 浅拷贝 / snapshot() 深拷贝 ✓
全部测试通过 ✓ (10 项)
```

---

## 五、教学版和真实框架差在哪

| 教学版 | 真实框架（Hermes / mini-hermes-v2） |
|---|---|
| 丢中间，直接删 | 让 LLM 给旧块写**摘要**，摘要替换原文——信息保住了，只是变粗了 |
| 字符数 ÷ 2 估算 | tokenizer 精确计数 + tools/图片开销 |
| 超限才压 | 有预判：接近阈值就先压，避免一轮爆掉 |
| 保尾部 K 块 | 摘要 + 保留最近 N 轮原文（混合策略） |

值得注意：**真实框架的"摘要压缩"也必须按块操作**——你没法对半个工具调用写摘要。本篇的块结构不是教学简化，是这个问题域的本质结构。

---

## 六、收尾

至此 Agent 有了大脑、手脚和记性。三篇走下来：

1. **核心循环**：问模型 → 有工具就执行回填 → 没工具就收工
2. **工具系统**：名片（Schema）+ 手（执行器），一切错误喂回给模型
3. **上下文压缩**：按块丢中间、保头尾，配对绝不拆散

还有一个绕不开的话题：模型会调错工具、传错参数，工具会做**危险的事**（删文件、跑 shell）。下一篇给手脚装**刹车**——权限系统。

---

*代码取自 [mini-hermes-v2](https://github.com/notfresh/mini-hermes-v2) 的 message_store.py，可对照真实框架源码。*
