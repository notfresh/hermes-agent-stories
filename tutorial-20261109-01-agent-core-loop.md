# 手写一个 Agent（第一篇）：三十行核心循环

> 教程系列 · 第一篇。一篇笔记，三句话：Agent = LLM + Tools + Loop；这三十行代码是所有 Agent 的共同起点；跑通它，你就能拆任何 Agent 框架。
>
> 配套代码在 [`examples/tutorial-01/`](https://github.com/notfresh/hermes-agent-stories/tree/main/examples/tutorial-01)：
> - [`agent.py`](https://github.com/notfresh/hermes-agent-stories/blob/main/examples/tutorial-01/agent.py) —— 完整可运行的 Agent
> - [`test_agent.py`](https://github.com/notfresh/hermes-agent-stories/blob/main/examples/tutorial-01/test_agent.py) —— 离线测试，不需要 API key
>
> **本文所有代码片段都是这两个文件里的原文，标了行号。**建议先 clone 下来对照着读。

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

## 文件长什么样

整个 Agent 就是两个文件。**先看全貌，再逐段拆。**

### `agent.py`（189 行）

```
agent.py
├── TOOLS              # 工具清单（模型看得见的 JSON 描述）
├── get_weather()      # 工具实现（你进程里真跑的函数）
├── TOOL_IMPLS         # 工具名 → 函数 的对照表
├── build_system_prompt()
└── run()              # ★ 核心循环，教程的主角
```

### `test_agent.py`（260 行，测试用，不需要 API key）

```
test_agent.py
├── FakeClient         # ★ 假模型客户端：替代真 API，并记录每次收到的消息
├── make_tool_call()   # 造一个工具调用对象
└── test_* × 5         # 五个测试
```

还有个 `check_tutorial_refs.py`——校验本文引用的行号和代码跟源文件对得上（防止代码改了、行号漂了，读者一对照就发现错位）。

跑起来：

```bash
git clone https://github.com/notfresh/hermes-agent-stories.git
cd hermes-agent-stories/examples/tutorial-01

python test_agent.py           # 离线测试，不用 key，不花钱
export DEEPSEEK_API_KEY=sk-xxx
python agent.py                # 连真实模型跑一次
python check_tutorial_refs.py  # 校验本文的行号引用
```

---

## 核心：`run()` 里发生了什么

`run()` 是全部。按顺序拆成五步，代码里标了编号 ①～⑤。

### 第 0 步：准备消息（`agent.py:116-124`）

```python
    if initial_messages is None:
        messages = [
            {"role": "system", "content": build_system_prompt()},
            {"role": "user", "content": user_message},
        ]
    else:
        # 接历史：把上一轮的消息整个接上，再追加本轮提问
        messages = list(initial_messages)
        messages.append({"role": "user", "content": user_message})
```

两种情况：
- **新会话**（`initial_messages` 是 None）：`system` + `user` 两条
- **接历史**（有历史）：把上一轮的消息**整个接上**，再追加本轮提问

`initial_messages` 这个参数是"多轮"和"单轮"唯一的区别。后面所有的坑都从这儿来。

### 第 ① 步：问模型（`agent.py:129-134`）

```python
        resp = client.chat.completions.create(
            model="deepseek-chat",
            messages=messages,
            tools=TOOLS,
        )
        msg = resp.choices[0].message
```

三件事：

1. `messages=messages` —— **把全部历史发过去**。没有服务端会话状态，模型不记得上一次调用。上下文 = 你维护的那个列表。
2. `tools=TOOLS` —— 工具清单也一起发。模型就是靠这份清单知道"我能调什么"。
3. `msg = resp.choices[0].message` —— **这是 OpenAI 封装的 API 请求响应结构体定义，目前照着写就行**。真实返回是个嵌套结构：`resp.choices` 是候选列表，取第 0 个，`.message` 才是有 `content` 和 `tool_calls` 的那层。

### 第 ② 步：判有没有工具请求（`agent.py:137-140`）

```python
        if not msg.tool_calls:
            # 收工前先记下这条回答 —— 多轮能用的关键，漏了会丢上下文
            messages.append({"role": "assistant", "content": msg.content})
            return msg.content, messages
```

**模型不要工具 = 它认为话说完了 = 循环结束。**

注意那句 `messages.append(...)`——**这一行是多轮能用的关键**，漏了会丢上下文。这是本文最后一个大坑，先记住。

### 第 ③ 步：记录请求（`agent.py:143-157`）

```python
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
```

模型说"我要调 get_weather，参数是 `{"city": "北京"}`"。你得把这句话**原样记进历史**。

为什么 `content` 是 `None` 而不是空字符串？因为这条消息的正文是工具请求，不是文字。

**漏了它会怎样**：第二次请求发给模型的消息是

```
system → user("北京天气?") → tool("北京：晴，25℃")
```

模型看到一条孤零零的 `tool` 消息，前面没有对应的请求记录。API 直接拒绝：

```
Messages with role 'tool' must be a response to a preceding message with 'tool_calls'
```

这不是我猜的，是踩过的真实事故：上下文超长触发压缩后，压缩逻辑把 `assistant[tool_calls]` 和它的 `tool` 结果拆散了，DeepSeek 立刻报这句话。修法是压缩时**按"原子块"切分**——一个 `assistant[tool_calls]` 加它的 N 个 `tool` 结果，要么全留要么全丢。

**规则**：assistant 的 tool_calls 消息和 tool 结果消息**必须成对出现**，要么一起留，要么一起丢。

### 第 ④⑤ 步：执行 + 回填（`agent.py:160-177`）

```python
        for tc in msg.tool_calls:
            fn = TOOL_IMPLS.get(tc.function.name)
            if fn is None:
                # 工具不存在：当成"结果"回填，让模型知道并改用别的
                result = f"错误：没有叫 {tc.function.name} 的工具"
            else:
                try:
                    args = json.loads(tc.function.arguments or "{}")
                    result = str(fn(**args))
                except Exception as e:
                    # 工具出错不当异常处理，而是当成"结果"回填给模型
                    result = f"错误：{e}"

            messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": result,
            })
```

三件事：

**一、模型报的参数是字符串 JSON，要自己解析。** `tc.function.arguments` 长得像 `'{"city": "北京"}'`，不是 dict。`json.loads` 之后才能 `**args` 展开调用。

**二、`tool_call_id` 必须带。** 这是模型给每个工具请求发的编号。你回填结果时带上它，模型才能把"哪个请求"和"哪个结果"对上。一次调三个工具时，模型发三个不同 id 的 tool_calls，你回填三条 tool 消息，id 一一对应。

**三、错误不当异常处理，而是当成"结果"回填。** 工具不存在、参数解析失败、函数内部抛异常——全部变成 `错误：xxx` 塞回对话，模型看见了能自己改。

**为什么？** 因为对模型来说，工具执行结果和工具报错，**格式上没区别**——都是"一条 role=tool 的消息"。它看到"错误：没有叫 get_stock 的工具"，下一步就会改主意。而如果你抛异常，整个进程崩了，模型连重试的机会都没有。

这是 Agent 和普通程序最不一样的地方之一：**Agent 的错误处理不是"记日志然后继续"，是"把错误当消息喂回去"。**

---

## 工具清单和工具实现，是两回事

看 `agent.py` 的开头：

```python
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_weather",
            "description": "查询某个城市的当前天气",
            "parameters": {
                "type": "object",
                "properties": {
                    "city": {"type": "string", "description": "城市名，例如：北京"},
                },
                "required": ["city"],
            },
        },
    },
]
```

这是**模型能看见的部分**。模型看不见你的 Python 函数，它只能看见这份 JSON 描述。

```python
def get_weather(city: str) -> str:
    """查询天气。教程里写死返回值，接真实接口时换成 HTTP 请求。"""
    return f"{city}：晴，25℃"


TOOL_IMPLS = {
    "get_weather": get_weather,
}
```

这是**你进程里真跑的函数**，加上名字到函数的对照表。

模型报"get_weather"，你查 `TOOL_IMPLS` 找到函数，调用它。**这就是工具系统的全部。**

写工具描述时的实操经验：
- `description` 说清楚**什么时候该调**（模型靠这个决定要不要调）
- 每个参数都要有 `description`（模型靠这个决定传什么）
- 参数名要具体（`city` 好过 `location`，`query` 好过 `q`）

---

## 怎么知道模型到底看到了什么

现在你有完整代码了。但有个问题：**代码是"跑起来"的，你看不见模型收到了什么。**

想看，就得抓包。做法是**换一个假的模型客户端顶上**——这就是 `test_agent.py` 里 `FakeClient` 的全部职责。

```python
class FakeClient:
    def __init__(self, script):
        self.script = script
        self.calls = []                    # ← 抓包记录
        self.chat = type("Chat", (), {"completions": self})()
        self.completions = self

    def create(self, model=None, messages=None, tools=None, temperature=None):
        self.calls.append([dict(m) for m in messages])    # ← 每次收到的消息都存一份
        index = min(len(self.calls) - 1, len(self.script) - 1)
        content, tool_calls = self.script[index]
        message = type("M", (), {"content": content, "tool_calls": tool_calls})()
        return type("R", (), {"choices": [type("C", (), {"message": message})()]})()
```

它照抄 OpenAI SDK 的形状（`client.chat.completions.create(...)` → `response.choices[0].message`），所以 `agent.py` 一行都不用改就能用上它。这就是 `run()` 那个 `client` 参数存在的意义。

**关键在 `.calls`**——每次调用收到的 messages 都存了一份。跑完一轮，`client.calls[0]` 就是模型第一次看到的全部内容。

### 用法：写一段脚本，让模型按你设计的顺序回应

```python
client = FakeClient([
    (None, [make_tool_call("get_weather", {"city": "北京"})]),  # 第 1 次：我要调工具
    ("北京今天晴，25℃。", None),                              # 第 2 次：我说完了
])

answer, messages = run("北京天气怎么样？", client=client)
```

`script` 是一串回应，按调用顺序取。所以：
- `client.calls[0]` = 模型**第 1 次**请求时看到的内容
- `client.calls[1]` = 模型**第 2 次**请求时看到的内容

### 最简单的例子：看它存了什么

不接 `agent.py`，单看 FakeClient 自己：

```python
fake = FakeClient([("第一轮回答", None), ("第二轮回答", None)])

r1 = fake.create(messages=[{"role": "user", "content": "你好"}])
print(r1.choices[0].message.content)   # 第一轮回答

r2 = fake.create(messages=[{"role": "user", "content": "再说一次"}])
print(r2.choices[0].message.content)   # 第二轮回答

print(fake.calls)   # [ [{'role':'user','content':'你好'}], [{'role':'user','content':'再说一次'}] ]
```

`.calls` 就是抓包结果：模型每次实际收到的内容，都在里面。

---

## 五个测试，逐个看

`test_agent.py` 的五个测试，每个验证一件事。跑 `python test_agent.py` 就能看到全部输出。

### 测试 1：单轮（`test_agent.py:98-121`，节选）

```python
client = FakeClient([
    (None, [make_tool_call("get_weather", {"city": "北京"})]),
    ("北京今天晴，25℃。", None),
])

answer, messages = run("北京天气怎么样？", client=client)

assert answer == "北京今天晴，25℃。"
assert roles_of(client.calls, 1) == ["system", "user", "assistant", "tool"]
```

第二条断言是关键：**模型第 2 次看到的是 `system → user → assistant(要工具) → tool(结果)`**。这四个动作一个不少。

### 测试 2：多轮（`test_agent.py:129-166`，节选）

这是最该看的测试。

```python
client = FakeClient([
    (None, [make_tool_call("get_weather", {"city": "北京"})]),  # 第 1 次
    ("北京今天晴，25℃。", None),                              # 第 2 次
    (None, [make_tool_call("get_weather", {"city": "北京"})]),  # 第 3 次 ← 第 2 轮开始
    ("建议穿短袖。", None),                                   # 第 4 次
])

answer1, history = run("北京天气怎么样？", client=client)
answer2, history2 = run("那我该穿什么？", initial_messages=history, client=client)

# 第 3 次请求 = 第 2 轮的首个请求
second_roles = roles_of(client.calls, 2)
assert second_roles == [
    "system", "user", "assistant", "tool", "assistant", "user"
]
```

**看清楚 `calls[2]` 为什么是"第 2 轮"**：因为一轮里模型可能要发 2 次请求（先要工具、再收工）。所以：

```
calls[0] = 第 1 轮：要工具
calls[1] = 第 1 轮：收工
calls[2] = 第 2 轮：要工具    ← 你要断言的是这个
calls[3] = 第 2 轮：收工
```

断言 `second_roles` 里有**两个** assistant 是对的：一个是工具请求，一个是最终回答。少一个就是丢上下文了。

### 那个坑：丢了就丢了

现在做个实验——**把 `agent.py` 里第 ② 步那句 `messages.append(...)` 删掉**，重跑测试 2：

```
AssertionError: 第 1 轮的 Agent 回答丢了（多轮上下文丢失的 bug）
```

删掉之后，模型第 2 轮看到的是：

```
system → user → assistant(要工具) → tool(结果) → user
```

中间那个 assistant（最终回答）没了。**模型看不见自己上一句说了什么。**

而**界面上完全看不出异常**——返回值 `answer` 完全正确，UI 显示的回答也完全正确。一切正常，直到第二轮对话时模型开始"失忆"。

这就是为什么测试必须**抓"发给 LLM 的请求内容"**，而不是看返回值。返回值看不出这类 bug。

### 一个反面教材：假绿断言

下面这条断言看起来在做同一件事，实际上**测不到任何东西**：

```python
roles = [m.get("role") for m in fake_llm.calls[1]]
assert "user" in roles and "assistant" in roles
```

两个毛病：

1. **`calls[1]` 是第 1 轮收工的请求**，不是第 2 轮。测的根本不是下一轮。
2. **它只检查"有没有 assistant"**，而第 1 轮那条 assistant 是**工具调用**那条，本来就带 `tool_calls`——它跟"最终回答"是两回事。

结果就是：**bug 在场，这条断言照样绿**。实测：

```
calls[1] roles = ['system', 'user', 'assistant', 'tool']
✓ 断言通过 —— 但 calls[1] 是【第 1 轮收工】的请求，不是第 2 轮！

calls[2] roles = ['system', 'user', 'assistant', 'tool', 'user']
第 2 轮请求里带着第 1 轮 agent 回答: 否 ← BUG 真实存在
```

**假绿测试比没测试更危险**——它给你一种"我测过了"的错觉。

怎么保证自己的断言不是假绿？**把修复临时撤掉，看这条断言会不会红**。会红的断言才有效。上面测试 2 就是这么设计的：删掉修复 → 测试红 → 恢复 → 测试绿。

### 测试 3：相邻 user（`test_agent.py:174-191`，节选）

另一种接线错误：**相邻 user**——上一轮的 user 和这一轮的 user 挨在一起，中间没有 assistant。OpenAI/DeepSeek 直接报错。

实测三种接线方式：

```
--- 正常接法 ---
  calls[2] roles = ['system', 'user', 'assistant', 'tool', 'assistant', 'user']

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

### 测试 4、5：错误要回喂给模型（`test_agent.py:199-239`，节选）

```python
# 测试 4：模型传了 get_weather 不认识的参数
(None, [make_tool_call("get_weather", {"city": "北京", "unit": "celsius"})]),

# 测试 5：模型点了不存在的工具
(None, [make_tool_call("get_stock", {"code": "AAPL"})]),
```

两次都断言：tool 结果消息的内容以 `错误：` 开头。

```
✓ 工具错误回填内容：错误：get_weather() got an unexpected keyword argument 'unit'
✓ 回填内容：错误：没有叫 get_stock 的工具
```

**不崩，能继续。** 这就是"把错误当消息喂回去"。

---

## 这三十行怎么变成三十万行

上面这个 Agent 能跑，但拿去干真活会立刻崩。生产级框架（Hermes 15 万行）做的事，就是把每个薄弱点都补上：

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

## 一总结

Agent 的全部秘密就是三十行：**问模型 → 模型要工具就执行并回填 → 不要工具就收工**。三十万行的生产框架，做的全部是同一件事——把这段代码在真实世界里不崩的那层壳，一层层补上去。读懂这三十行，你就读懂了一切 Agent 框架的地基。

而这个循环最难的地方不在代码，在**测试**：返回值永远是对的，bug 只在"模型实际看到了什么"里才显形。所以造一个假客户端当记录器，比什么都重要。
