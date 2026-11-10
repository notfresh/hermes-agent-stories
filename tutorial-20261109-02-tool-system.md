# 手写一个 Agent（第二篇）：工具系统——给 Agent 长出手脚

> 教程系列 · 第二篇。上一篇给了 Agent 一个**大脑**（LLM + 循环），但那个大脑被关在房间里：它能思考，却碰不到外面的世界。这一篇给它装上**手脚**——让它能查天气、读写文件、真正做事。
>
> 配套代码在 [`examples/tutorial-02/`](https://github.com/notfresh/hermes-agent-stories/tree/main/examples/tutorial-02)，跑 `python test_tools.py` 就能验证（12 个离线测试，不需要 API key）。本文所有片段都标了行号，可对着源文件看。

---

## 一、大脑没有手脚是什么样

上一篇的 Agent 循环是这样的：

```
用户：北京明天适合穿外套吗？
模型：（心想：我需要天气数据……但我只能输出文字）
模型：作为 AI 语言模型，我无法查询实时天气。
```

这不是模型"不想"答，是它**够不着**。LLM 是个纯文本进、纯文本出的函数——你把世界的信息喂给它，它才能推理；够不着，就只能坦白或者瞎编。

**工具就是喂给它世界的那条通道。** OpenAI 的接口里，你发请求时带上一份工具清单：

```python
response = client.chat.completions.create(
    model="deepseek-chat",
    messages=messages,
    tools=[...],   # ← 每个工具：叫什么、干什么、要什么参数
)
```

模型看到清单后，如果觉得"这事我自己答不了，得用工具"，它不输出普通文字，而是输出一个结构化请求：

```json
{"name": "get_weather", "arguments": "{\"city\": \"北京\"}"}
```

**注意：模型没有执行任何东西。** 它只是说"我想调 get_weather"。真正执行的是你的代码——你在循环里拿到这个名字，找到对应函数，跑了，把结果塞回对话，再问模型一次。

所以工具系统的全部职责就两件事：

1. **告诉模型有哪些工具**（Schema——工具的名片）
2. **替模型执行工具**（执行器——真正干活的手）

---

## 二、一个工具 = 一张名片 + 一双手

模型看不到你的 Python 函数，它只看到名片。名片上写三样：

```json
{
  "name": "get_weather",
  "description": "查询某个城市的当前天气",
  "parameters": {
    "type": "object",
    "properties": {
      "city": {"type": "string", "description": "城市名，例如：北京"},
      "days": {"type": "number", "description": "预报天数，默认 1"}
    },
    "required": ["city"]
  }
}
```

名片决定模型怎么调：`description` 让它知道"这是查天气的"；参数描述让它知道 `city` 该填城市名；`required` 让它知道不填 `city` 不行。**名片写错，模型就调错**——它照着名片行事，名片是错的它没有别的信息来源。

而函数是名片背后真实的手：

```python
def get_weather(city: str, days: int = 1) -> str:
    return f"{city}：晴，25℃（{days} 天预报）"
```

上一篇就是这么手写的：一份 Schema、一个函数、一个注册表，三处要保持同步。工具只有一两个时无所谓；到 30 个（读文件、跑 shell、查库……）就是灾难。

---

## 三、自动生成名片

解决思路不是"少写 Schema"，而是**让名片从函数身上长出来**——函数签名里本来就有全部信息：

| 函数里已有的 | 变成名片的什么 |
|---|---|
| 参数名 + 类型注解 | `properties` 的 key 和 `type` |
| 有没有默认值 | `required` 列表 |
| docstring | `description` |

于是工具的定义收敛回一处——一个装饰器：

```python
def tool(name: str = "", description: str = ""):
    """把一个函数注册成模型可调用的工具。

    用法：

```

用法（`tools.py:101-108`，节选）：

```python
@tool(description="查询某个城市的当前天气")
def get_weather(city: str, days: int = 1) -> str:
    """查询某个城市的当前天气。

    Args:
        city: 城市名，例如：北京
        days: 预报天数，默认 1
    """
    return f"{city}：晴，25℃（{days} 天预报）"
```

生成出的名片和上一篇手写的那份**一字不差**。但现在改名、加参数、删参数，只动函数一处。

### 类型映射（`tools.py:34-46`）

```python
_PY_TO_JSON = {
    str: "string",
    int: "number",
    float: "number",
    bool: "boolean",
    list: "array",
    dict: "object",
}


def _pytype_to_jsontype(py_type: Any) -> str:
    """类型映射。认不出来的一律当 string——宁可宽，不可错。"""
    return _PY_TO_JSON.get(py_type, "string")
```

两个容易踩的点：

- **必须按"声明的类型"取，不能按值的运行时类型判断。** 因为 Python 里 `bool` 是 `int` 的子类，按值判断会把 `True` 误判成 `number`。
- **认不出来的类型一律当 `string`**——宁可宽不可错。真坑是 `Optional[int]`：映射表里没有它，会退化成 `string`，于是模型传 `"5"`（字符串），Python 不拦，你的算术代码才炸。对策：工具内部自己 `int(x)` 兜底，或者别用 `Optional`。

### 注册表要幂等（`tools.py:159-176`）

```python
def register(name: str, schema: dict, fn: Callable) -> dict:
    """把一个工具登记进注册中心。**同名替换，不重复追加。**

    为什么要幂等：注册表是模块级全局的。宿主每轮启动 agent 内核都会重新
    注册一遍，不幂等的话跑第 3 轮时，发给 LLM 的 tools 数组里会有 3 份
    同名工具，OpenAI SDK 直接报 "Duplicate function names"。

    Args:
        name: 工具名
        schema: JSON Schema
        fn: 实际执行体

    Returns:
        登记的 schema
    """
    _TOOL_REGISTRY[name] = {"fn": fn, "schema": schema}

    for i, existing in enumerate(_TOOL_SCHEMAS):
```

这看着是小事，实际是注册表能不能在真实宿主里活下来的关键：宿主每轮启动都会重新注册一遍，不幂等的话第 3 轮时工具清单里有 3 份同名工具，API 直接报 `Duplicate function names`——而且这个错要到第 3 轮才炸，最隐蔽的那种 bug。

---

## 四、语言窄化：这只是 Python 的做法

必须坦白：**装饰器 + docstring 自动生成 Schema，是 Python 生态独有的语法红利。** 换个语言，这套代码一个字都搬不过去。但"思路"是通的——每个主流生态都有自己的做法，思想全是同一个：**类型定义只有一份，Schema 从它生成，绝不手抄两遍**：

| 生态 | 做法 | 思想 |
|---|---|---|
| Python | 装饰器 + 类型注解 + docstring（本文） | 从函数签名生成 |
| TypeScript | Zod 定义 schema，`zodToJsonSchema()` 转换 | 从类型定义生成 |
| Go | struct + `json`/`jsonschema` tag，Google 2026 年还出了官方 `jsonschema-go` | 从结构体生成 |
| Java | Spring AI 的 `@Tool` 注解，或 Jackson 从 POJO 生成 | 从注解/类生成 |

所以读本文别学"装饰器怎么写"，学那条**对所有语言都成立的原则**：

> 工具的参数结构是模型和你之间的契约。契约只能有一个事实来源（source of truth），其余全部自动生成——凡是手抄两遍的东西，迟早改错一处。

Go / TS / Java 读者把本文的 `tools.py` 当伪代码读即可，你们生态里有对应物。

---

## 五、手：把每个错误都喂回给模型

名片管"告诉模型"，执行器管"替模型干活"。上一篇它内联在循环里只认一个函数，现在抽出来（`runner.py`）。

核心原则只有一条：**四种情况，全部返回消息，没有一种抛异常**（`runner.py:21-30`）：

```python
def execute(tool_call: dict) -> dict:
    """执行一个 tool_call，返回 role=tool 的结果消息。

    四种情况，**全部返回消息，没有一种抛异常**：
      1. 工具不存在        → 回填"没有这个工具"
      2. 参数不是合法 JSON  → 回填"参数格式错误"
      3. 参数不匹配签名      → 回填"参数不匹配"
      4. 工具内部抛异常      → 回填"错误：xxx"

    为什么要这样：对模型来说，工具结果和工具报错**格式上没区别**——
```

为什么？因为对模型来说，工具结果和工具报错格式上没区别——都是一条 `role=tool` 消息。把错误当消息喂回去，模型下一轮就会改主意；抛异常则进程崩了，模型连重试的机会都没有。

看两种最有代表性的（`runner.py:45-48`）：

```python
    fn = tools.get_fn(fn_name)
    if fn is None:
        content = f"错误：没有叫 {fn_name} 的工具。可用工具：{', '.join(tools.names())}"
        return {"role": "tool", "tool_call_id": tool_call_id, "content": content}
```

注意错误信息里带了"可用工具：..."——**把可选项告诉模型**，它能自己换一个，而不是放弃。这就是"喂回去"的价值：错误不是终点，是下一轮的输入。

参数和内部错误分开处理（`runner.py:58-67`）：

```python
    try:
        result = str(fn(**fn_args))
    except TypeError as e:
        # 参数不匹配签名（少了必填参数 / 传了不认识的参数）
        result = f"错误：参数不匹配（{e}）。请参考工具描述调整参数。"
    except Exception as e:
        # 工具内部出错
        result = f"错误：{e}"

    return {"role": "tool", "tool_call_id": tool_call_id, "content": result}
```

- `TypeError` = **模型的错**（参数不匹配），提示它"参考工具描述调整参数"——它能改
- 其他异常 = **工具自己的错**（内部炸了），如实转告——它知道这次失败了，换个思路

还有一个反直觉的实测结论：**Python 不强制类型，类型错不会当场报错。** Schema 里 `days` 是 `number`，模型传了字符串 `"3"`，`fn(**{"days": "3"})` 照样跑通——错误埋在你后面的算术代码里才炸。所以：**名片说的类型是给模型的建议，不是保证，工具内部该自己转就转。**

---

## 六、怎么验证这套东西没坏

12 个离线测试（`test_tools.py`），挑最有代表性的一种（`test_tools.py:123-135`）：

```python
def test_bad_json_is_fed_back() -> None:
    print("【B3】参数不是合法 JSON：回填错误，不崩")

    tc = {
        "id": "call_x",
        "type": "function",
        "function": {"name": "get_weather", "arguments": "{city: 北京}"},  # 少了引号
    }
    result = runner.execute(tc)

    assert result["role"] == "tool"
    assert "不是合法 JSON" in result["content"]
    assert result["tool_call_id"] == "call_x"

```

关键在断言的是**回填的消息内容**，而不是"没抛异常"。上一篇讲过这个原则：断言要抓真正要保证的东西——这里要保证的是"错误变成了模型能看到的消息"，所以断言 `role` 和 `content`。

跑法：

```bash
cd hermes-agent-stories/examples/tutorial-02
python test_tools.py    # 12 个测试，不用 API key
python tools.py         # 看自动生成的名片长什么样
```

---

## 七、收尾

这一篇做完，Agent 长出了手脚：

- **名片**：从函数签名自动生成，契约只有一份事实来源（这条跨语言成立）
- **手**：执行器把一切错误喂回给模型，让失败成为下一轮的输入而非进程的终点

但它现在只有一双裸手——下一篇给手戴上**手套**：让模型能记住超过上下文窗口的对话（上下文压缩）。

---

*代码取自 [mini-hermes-v2](https://github.com/notfresh/mini-hermes-v2) 的工具层，可对照真实框架源码。*
