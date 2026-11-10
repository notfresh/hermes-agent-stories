# 手写一个 Agent（第一篇）：三十行核心循环

> 教程系列 · 第一篇。一篇笔记，三句话：Agent = LLM + Tools + Loop；这三十行代码是所有 Agent 的共同起点；跑通它，你就能拆任何 Agent 框架。
>
> 这份代码单轮能跑，多轮会丢上下文——最后一节把这个坑完整复现并修掉。**先看懂主链，再看它怎么坏。**

---

## 先把名词固定

| 名字 | 是什么 |
|---|---|
| **LLM** | 大语言模型。你把一段文字和一份"工具清单"发给它，它回你一段文字，或者回"我要调用某个工具" |
| **Tool（工具）** | 一个普通函数。但它有 JSON Schema 描述，模型看得懂，于是能点名调用 |
| **Loop（循环）** | 模型要工具 → 你执行 → 结果塞回对话 → 再问模型。直到模型不再要工具 |
| **Agent** | 就是上面三样东西拼起来。没有第四样 |

一句话关系：**模型只负责"决定下一步做什么"，执行和循环都是你的代码干的。**

这个划分很关键，因为它决定了后面所有事的边界：
- 模型**不能**自己执行工具，它只能"说"它想调哪个工具
- 工具**不是**模型的一部分，它是你进程里的普通函数，能读文件、能跑 shell
- 循环**不是**模型的内部机制，它是你写的 `while`，模型每次都是"无状态地重新回答一次"

---

## 三十行，就是全部

先把完整的东西放这儿，再逐段拆。代码可以直接跑（放在 `agent.py`）：

> ⚠️ 这份代码**单轮能跑，多轮会有 bug**（Agent 记不住自己上一句说了什么）。原因和修复在最后一节讲，先看懂主链。

```python
import json
import os

from openai import OpenAI

client = OpenAI(
    base_url="https://api.deepseek.com/v1",
    api_key=os.environ.get("DEEPSEEK_API_KEY", ""),
)

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_weather",
            "description": "查询某个城市的天气",
            "parameters": {
                "type": "object",
                "properties": {"city": {"type": "string", "description": "城市名"}},
                "required": ["city"],
            },
        },
    }
]

def get_weather(city: str) -> str:
    """真的去查天气。"""
    return f"{city}：晴，25℃"

def run(user_message: str) -> str:
    messages = [
        {"role": "system", "content": "你是一个助手，需要信息时用工具查。"},
        {"role": "user", "content": user_message},
    ]

    for _ in range(10):                      # ① 最多 10 轮
        resp = client.chat.completions.create(
            model="deepseek-chat",
            messages=messages,
            tools=TOOLS,
        )
        msg = resp.choices[0].message          # 这是OpenAI封装的api请求响应结构体定义的，目前照着写就行

        if not msg.tool_calls:                # ② 模型不要工具 → 结束
            return msg.content

        messages.append({                     # ③ 记下"模型要调工具"这件事
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments,
                    },
                }
                for tc in msg.tool_calls
            ],
        })

        for tc in msg.tool_calls:             # ④ 真执行
            args = json.loads(tc.function.arguments)
            result = get_weather(**args)
            messages.append({                 # ⑤ 结果回填
                "role": "tool",
                "tool_call_id": tc.id,
                "content": str(result),
            })

    return "(达到最大轮次，未获得最终回复)"


if __name__ == "__main__":
    print(run("北京今天天气怎么样？"))
```

跑起来：

```bash
pip install openai
export DEEPSEEK_API_KEY=sk-xxx
python agent.py
```

换一家模型只改两处：`base_url` 和 `model`（OpenAI 兼容的接口都能用）。

---

## 逐段拆：五个动作

上面这段代码，拆开只有五个动作：

| 动作 | 在代码哪 | 干什么 |
|---|---|---|
| ① 问模型 | `client.chat.completions.create(...)` | 把**全部历史**发过去，附带工具清单 |
| ② 判有没有工具请求 | `if not msg.tool_calls` | 没有 → 收工；有 → 继续 |
| ③ 记录请求 | `messages.append({"role": "assistant", ...})` | **必须记**，否则下一轮模型不知道自己刚要过工具 |
| ④ 执行工具 | `get_weather(**args)` | 你的代码真的跑起来了 |
| ⑤ 结果回填 | `messages.append({"role": "tool", ...})` | 把结果塞回对话，模型才能基于结果接着想 |

三件事必须一起理解：

### 一、"发全部历史"是这个架构的代价和力量

每次调模型，**整个 messages 列表原封不动重发一遍**。没有服务端会话状态，模型也不记得上一次调用。上下文 = 你维护的那个列表。

这带来两个后果：
- **好处**：模型能看到自己前几轮说过什么、做过什么，推理链条连贯
- **代价**：上下文会越滚越长，成本线性上涨，最后撑爆窗口

Agent 框架长大，几乎全是在处理这个代价。上下文压缩（把老消息压成一段摘要）、记忆系统（把该记的东西挪到上下文外面存着）是两代框架的主战场。

### 二、第③步漏了会怎样

`messages.append({"role": "assistant", "content": None, "tool_calls": [...]})` 这一步看着像多余——结果不都回填了吗？

漏了它，第二次请求发给模型的消息序列是：

```
system → user("北京天气?") → tool("北京：晴，25℃")
```

模型看到一条孤零零的 `tool` 消息，前面没有对应的请求记录。它不知道这个结果是哪来的——API 层面会直接拒绝：

```
Messages with role 'tool' must be a response to a preceding message with 'tool_calls'
```

这不是我猜的，是踩过的真实事故：上下文超长触发压缩后，压缩逻辑把 `assistant[tool_calls]` 和它的 `tool` 结果拆散了，DeepSeek 立刻报这句话。修法是压缩时**按"原子块"切分**——一个 `assistant[tool_calls]` 加它的 N 个 `tool` 结果，要么全留要么全丢，绝不拆散。

**规则**：assistant 的 tool_calls 消息和 tool 结果消息**必须成对出现**，要么一起留，要么一起丢。

### 三、第⑤步的工具结果为什么要带 `tool_call_id`

`tool_call_id` 是模型给每个工具请求发的编号。你回填结果时带上这个编号，模型才能把"哪个请求"和"哪个结果"对上。

一次要调三个工具时，模型会发三个带不同 id 的 tool_calls，你回填三条 tool 消息，id 一一对应。顺序错了模型就会把结果搞混。

---

## 这三十行怎么变成三十万行

上面这段代码能跑，但拿去干真活会立刻崩。生产级框架（Hermes 15 万行）做的事，就是把每个薄弱点都补上：

| 薄弱点 | 生产框架的解法 | 涉及模块 |
|---|---|---|
| API 超时/限流 | 重试 + 指数退避 + 错误分类（timeout / rate_limit / auth 分开处理） | `LLMClient` |
| key 过期 | 凭证自动轮换 + provider fallback（这家挂了换那家） | `LLMClient` |
| 上下文撑爆 | 超长检测 + 压缩（把老消息换成摘要） | `MessageStore` |
| 工具不存在/参数错 | 错误回填给模型，让它自己改（而不是抛异常崩掉） | `ToolRunner` |
| 工具要写危险文件 | 权限校验（路径白名单、只读/读写权限码） | `ToolRunner` |
| 模型跑飞，死循环 | 轮数上限 + 迭代预算 + 中断 + grace call | `LoopController` |
| 任务复杂，一次搞不定 | 规划模式（先出计划、等人批准再执行） | `PlanMode` + 守卫 |
| 模型不按规矩来 | 守卫函数：工具执行前检查，违规直接拒 | `ToolRunner` |

把这些都塞进循环体，循环就撑爆了。生产的做法是**拆出去**：

```
ConversationLoop.run()   ← 只剩编排：问 → 要工具吗 → 执行 → 回填 → 再来
    ├── LoopController    还继续吗？（轮数/预算/中断）
    ├── LLMClient        模型说什么？（重试/退避/错误分类）
    ├── ToolRunner       工具结果是什么？（查找/解析/守卫/回填）
    ├── MessageStore     消息放哪、太长怎么办？
    └── TurnContext      回合开始前准备什么？（系统提示词/清洗/凭证）
```

骨架只回答"下一步做什么"，每个模块各回答一个问题。这是 [MinimalAgentV2](https://github.com/notfresh/mini-hermes-v2) 的做法——它把 Hermes 的 5194 行主循环拆成上面五个模块，核心循环保持 30 行，全部防御下沉到模块里。

---

## 一个必须踩过的坑：多轮上下文静默丢失

上面这段代码单轮跑没问题。但你一旦给它加上"记得住历史"（会话系统），就会踩到一个**界面上完全看不出异常**的坑。

### 先看现象

用户第一轮问"北京天气怎么样"，Agent 答了"北京今天晴，25℃"。用户第二轮问"那我该穿什么？"

Agent 表现得像没听见——它看不见自己刚才那句回答。

### 根因在哪儿

看教程这段代码的收尾：

```python
        if not msg.tool_calls:                # ② 模型不要工具 → 结束
            return msg.content                # ← 直接返回，messages 里没有这条回答
```

`return` 之前**没有把这条 assistant 消息存进 `messages`**。宿主拿到返回值，把 `messages` 存回会话。下一轮接回去时，模型只看得见自己的提问，看不见自己的答案。

**实测一下**（把上面那段代码接上会话，跑两轮，抓每次发给模型的消息）：

```
=== 原版 ===
第 2 轮消息角色序列: ['system', 'user', 'assistant', 'tool', 'user']
第 2 轮是否带着第 1 轮的 agent 回答: 否 ← BUG！

=== 修好后 ===
第 2 轮消息角色序列: ['system', 'user', 'assistant', 'tool', 'assistant', 'user']
第 2 轮是否带着第 1 轮的 agent 回答: 是 ✓
```

看清楚差异：修好后多了一条 `assistant`。原版第 2 轮请求里，Agent 的最终回答**根本不存在**。

### 修复就一行

```python
        if not msg.tool_calls:
            messages.append({"role": "assistant", "content": msg.content})  # ← 补上
            return msg.content
```

改完之后，上面那份 `agent.py` 就能安全地接会话系统了。如果你不想回头改，完整修复版在这里（跟上面的差别只有这一行）：

```python
def run(user_message: str, initial_messages=None) -> tuple[str, list[dict]]:
    """initial_messages: 上一轮的消息历史（接会话时传进来）"""
    if initial_messages is None:
        messages = [
            {"role": "system", "content": "你是一个助手，需要信息时用工具查。"},
            {"role": "user", "content": user_message},
        ]
    else:
        messages = list(initial_messages)
        messages.append({"role": "user", "content": user_message})

    for _ in range(10):
        resp = client.chat.completions.create(
            model="deepseek-chat",
            messages=messages,
            tools=TOOLS,
        )
        msg = resp.choices[0].message

        if not msg.tool_calls:
            messages.append({"role": "assistant", "content": msg.content})   # ← 关键这行
            return msg.content, messages

        messages.append({
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments,
                    },
                }
                for tc in msg.tool_calls
            ],
        })

        for tc in msg.tool_calls:
            args = json.loads(tc.function.arguments)
            result = get_weather(**args)
            messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": str(result),
            })

    return "(达到最大轮次，未获得最终回复)", messages
```

会话怎么用它：

```python
history = None
while True:
    answer, history = run(input("你："), initial_messages=history)
    print("Agent：", answer)
```

### 为什么这个 bug 特别难发现

因为**返回值看不出问题**。函数返回的 `msg.content` 完全正确，UI 上显示的回答也完全正确——一切正常，直到第二轮对话时模型开始"失忆"。

所以测试必须**抓"发给 LLM 的请求内容"**，而不是看返回值。一个假模型就够用了——它把每次收到的 messages 记下来当"抓包"，测试不用花钱调真 API，也能看见模型实际看到了什么：

```python
class FakeLLM:
    def __init__(self):
        self.calls = []

    def complete(self, messages, tools=None):
        self.calls.append([dict(m) for m in messages])   # 抓包
        n = len(self.calls)
        msg = type("M", (), {"content": f"第{n}轮回答", "tool_calls": None})()
        return type("R", (), {"choices": [type("C", (), {"message": msg})()]})()
```

### 断言怎么写才算数

**先看清一件事**：教程代码每轮可能发 1 次或 2 次请求（先要工具、再收工），所以"第 2 轮"不是 `calls[1]`。跑两轮抓包：

```
calls[0] roles = ['system', 'user']                      ← 第 1 轮：要工具
calls[1] roles = ['system', 'user', 'assistant', 'tool']  ← 第 1 轮：收工
calls[2] roles = ['system', 'user', 'assistant', 'tool', 'user']  ← 第 2 轮：真正的目标
```

断言要落在 `calls[2]` 上，而且**断言的是"第 1 轮的回答在不在"**：

```python
second = fake_llm.calls[2]                                       # 第 2 轮的首个请求
assert any("第1轮回答" in str(m.get("content")) for m in second)   # 回答必须在
```

### 一个反面教材：假绿断言

下面这条断言看起来在做同一件事，实际上**测不到任何东西**：

```python
roles = [m.get("role") for m in fake_llm.calls[1]]
assert "user" in roles and "assistant" in roles
```

两个毛病：

1. **`calls[1]` 是第 1 轮收工的请求**，不是第 2 轮。测的根本不是下一轮。
2. **它只检查"有没有 assistant"**，而第 1 轮那条 assistant 是**工具调用**那条，本来就带 `tool_calls`——它跟"最终回答"是两回事。

结果就是：**bug 在场，这条断言照样绿**。实测结果：

```
calls[1] roles = ['system', 'user', 'assistant', 'tool']
✓ 断言通过 —— 但 calls[1] 是【第 1 轮收工】的请求，不是第 2 轮！

calls[2] roles = ['system', 'user', 'assistant', 'tool', 'user']
第 2 轮请求里带着第 1 轮 agent 回答: 否 ← BUG 真实存在
```

**假绿测试比没测试更危险**——它给你一种"我测过了"的错觉。

怎么保证自己的断言不是假绿？**把修复临时撤掉，看这条断言会不会红**。会红的断言才有效：

```python
# 撤掉 messages.append({"role": "assistant", "content": msg.content}) 这行
# → 上面的断言必须红
# 恢复这行
# → 断言转绿
```

### 另一个更早暴露问题的信号

还有一种接线错误：**相邻 user**——上一次请求的 user 和这一次的 user 挨在一起，中间没有 assistant。OpenAI/DeepSeek 直接报错。

实测三种接线方式：

```
--- 正常接法，丢 assistant 回答 ---
  calls[2] roles = ['system', 'user', 'assistant', 'tool', 'user']

--- 宿主多存了一条 user（重复 append）---
  calls[2] roles = ['system', 'user', 'assistant', 'tool', 'user', 'user']  ⚠️ 相邻 user

--- 完全不接历史 ---
  calls[2] roles = ['system', 'user']
```

注意第一行：**"丢 assistant 回答"并不会产生相邻 user**。相邻 user 来自另一个原因——宿主把 user 消息也存进了 session，循环里又 append 一次，同一条消息出现两遍。

两种症状、两套根因，别混：

| 症状 | 根因 |
|---|---|
| 模型看不见自己上一句回答 | 缺 `messages.append({"role": "assistant", ...})` |
| 两条 user 相邻，API 报错 | 宿主和循环重复 append 了 user 消息 |

**记住这一条**：测试 Agent 行为，要断言"你发给模型的东西"，而不是"你返回的东西"。

---

## 一总结

Agent 的全部秘密就是三十行：**问模型 → 模型要工具就执行并回填 → 不要工具就收工**。三十万行的生产框架，做的全部是同一件事——把这段代码在真实世界里不崩的那层壳，一层层补上去。读懂这三十行，你就读懂了一切 Agent 框架的地基。
