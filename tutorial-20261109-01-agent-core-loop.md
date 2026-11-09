# 手写一个 Agent（第一篇）：三十行核心循环

> 教程系列 · 第一篇。一篇笔记，三句话：Agent = LLM + Tools + Loop；这三十行代码是所有 Agent 的共同起点；跑通它，你就能拆任何 Agent 框架。

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
- 循环**不是**模型的内部机制，它是你写的 `while`，模型每次都是" stateless 地重新回答一次"

---

## 三十行，就是全部

先把完整的东西放这儿，再逐段拆。代码可以直接跑（放在 `agent.py`）：

```python
import json

from openai import OpenAI

client = OpenAI(base_url="https://api.deepseek.com/v1", api_key="你的key")

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
        msg = resp.choices[0].message

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
```

跑起来：

```bash
pip install openai
export DEEPSEEK_API_KEY=sk-xxx
python agent.py
```

（`json` 那行别忘了 `import json`。）

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

模型看到一条孤零零的 `tool` 消息，前面没有对应的请求记录。它不知道这个结果是哪来的——API 层面会直接报：

```
tool must be a response to a preceding message with tool_calls
```

或者更糟：API 接受了，但模型开始胡言乱语，说些"根据刚才的查询结果"之类的废话，因为它真的不知道刚才发生了什么。

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

上面代码看着多轮没问题。但真接进一个带会话的系统（记得住历史），有一个 bug 极隐蔽：

**症状**：界面上完全看不出异常。只是模型显得健忘——你问它刚才说过什么，它说没说过。

**根因**：循环跑完一轮时，返回给宿主的消息列表**漏了最后那条 assistant 回答**。宿主把它存回会话，下一轮再接回去时，模型只看得见自己之前的提问，看不见自己的答案。

**怎么发现的**：不能只看返回值，要**抓请求内容**。用一个假模型记录每次收到的 messages：

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

断言抓到的第二轮消息里，问和答都在：

```python
roles = [m.get("role") for m in fake_llm.calls[1]]
assert "user" in roles and "assistant" in roles
```

这条断言救过我一次。它也顺便说明了**为什么断言要抓"发给 LLM 的请求内容"，而不是返回值**——返回值看不出"上下文静默丢失"这种 bug。

（这个坑的完整复盘见 [story-7](https://github.com/notfresh/hermes-agent-stories/blob/main/story-7-how-i-built-my-own-coding-agent.md)，MinimalAgentV2 里对应的回归测试是 `tests/test_multiturn_context.py`，5 条断言全绿。）

---

## 一句话总结

Agent 的全部秘密就是三十行：**问模型 → 模型要工具就执行并回填 → 不要工具就收工**。三十万行的生产框架，做的全部是同一件事——把这段代码在真实世界里不崩的那层壳，一层层补上去。读懂这三十行，你就读懂了一切 Agent 框架的地基。
