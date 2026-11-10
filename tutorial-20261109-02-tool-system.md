# 手写一个 Agent（第二篇）：工具系统

> 教程系列 · 第二篇。一篇笔记，三句话：工具 = 一份 Schema + 一个函数；Schema 可以从函数签名自动生成；执行器要把**所有**错误都变成消息回喂给模型。
>
> 配套代码在 [`examples/tutorial-02/`](https://github.com/notfresh/hermes-agent-stories/tree/main/examples/tutorial-02)：
> - [`tools.py`](https://github.com/notfresh/hermes-agent-stories/blob/main/examples/tutorial-02/tools.py) —— 装饰器注册 + Schema 自动生成
> - [`runner.py`](https://github.com/notfresh/hermes-agent-stories/blob/main/examples/tutorial-02/runner.py) —— 工具执行器
> - [`test_tools.py`](https://github.com/notfresh/hermes-agent-stories/blob/main/examples/tutorial-02/test_tools.py) —— 12 个离线测试，不需要 API key
>
> **先看代码再读本文**，本文所有片段都标了行号，可对着源文件看。

---

## 第一篇留下的问题

第一篇里，一个工具要写两遍：

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

def get_weather(city: str) -> str:
    """真的去查天气。"""
    return f"{city}：晴，25℃"

TOOL_IMPLS = {
    "get_weather": get_weather,
}
```

三处要同步：Schema 里的参数名、函数的参数名、`TOOL_IMPLS` 的键。**改错一个，模型就调不对**——而这个错误在代码里看不出来，只有模型调了才知道。

工具少的时候无所谓。工具到 30 个（读文件、写文件、跑 shell、搜索、查数据库……），这份重复就成了灾难。

**这一篇的目标：写一个函数，Schema 自动生成。**

---

## 文件长什么样

```
examples/tutorial-02/
├── tools.py       # 注册中心 + Schema 生成 + 内置工具
├── runner.py      # 执行器：按名字找函数、执行、错误回填
└── test_tools.py  # 12 个离线测试
```

跑起来：

```bash
cd hermes-agent-stories/examples/tutorial-02
python test_tools.py    # 12 个测试，不用 key，不花钱
python tools.py         # 看自动生成的 Schema 长什么样
```

---

## 第一步：Schema 自动生成

核心就一个问题：**函数签名怎么变成 JSON Schema？**

答案：三个信息源，各管一段。

| 信息 | 从哪来 | 变成什么 |
|---|---|---|
| 参数名 + 类型 | 函数签名和类型注解 | `properties` 的 key 和 `type` |
| 哪个参数必填 | 有没有默认值 | `required` 列表 |
| 每个参数是干嘛的 | docstring 的 `Args:` 区域 | `description` |

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

**为什么必须用 `get_type_hints` 而不是 `isinstance` 判断**：因为 `bool` 是 `int` 的子类——

```python
isinstance(True, int)   # True  ← 用 isinstance 会把 bool 判成 number
```

`get_type_hints` 按**声明的类型**取，不看值的运行时类型，所以 `bool` 正确映射成 `boolean`。

**认不出来的类型怎么办？** 映射表查不到 → 当 `string`。宁可宽不可错：把数组标成 string，模型传个字符串过来你还能处理；标错了类型模型传的东西你接不住。

⚠️ **这里有个真坑**：`Optional[int]` 不在映射表里，会退化成 `string`。因为 `get_type_hints` 拿到的是 `Optional[int]` 这个类型对象，不是 `int`。

```python
def opt_count(n: Optional[int] = None) -> str: ...
# → schema 里 n 的 type 是 "string"（不是 "number"）
```

模型看到 `string`，就会传 `"5"` 而不是 `5`。Python 不拦你，函数里拿到的是 str，后续算术就炸。

**对策**：工具内部自己兜（`int(n)`），或者干脆别用 `Optional[int]`，拆成两个参数。**Schema 说什么，模型就照着说什么**——Schema 错了，责任在写 Schema 的人。

### 参数描述从 docstring 提取（`tools.py:49-56`，节选）

```python
def _parse_docstring_params(docstring: str) -> dict[str, str]:
    """从 Google-style docstring 的 Args: 区域提取 {参数名: 描述}。

    格式要求（缩进很关键）：

        Args:
            path: 文件路径
            limit: 最多读取的行数
    """
```

只认 Google 那种 `Args:` 块，缩进必须比 `Args:` 多 4 格。解析规则：

- 遇到 `Args:` 开始收集
- 遇到 `Returns:` 或 `Raises:` 停止
- 缩进回到 `Args:` 级别 → 停止（说明出了 Args 区域）
- 匹配 `\s{8}(\w+):\s*(.*)` 提取 `参数名: 描述`

**这条规则很挑格式**——docstring 缩进不对，描述就提不出来。提不出来会怎样？

```python
@tool(description="没写 docstring 的工具")
def no_doc(x: str) -> str:
    return ""

# → properties.x.description = "Parameter x"
```

模型看到"Parameter x"，**完全不知道这个参数该填什么**。它可能瞎填一个。

**教训：装饰器省下的是机械活，但参数描述还得你手写**——而参数描述恰恰是模型判断"传什么"的主要依据。

### 装饰器本体（`tools.py:95-99`，节选）

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

这一个函数，生成出这样的 Schema：

```json
{
  "type": "function",
  "function": {
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
}
```

对比第一篇手写的那份——**一模一样**。但现在函数改名、参数改名、加参数，都不用动别的地方。

注意 `required` 的判定：

```python
            # 没有默认值 = 必填
            if param.default is inspect.Parameter.empty:
                required.append(pname)
```

`city` 没默认值 → 必填。`days` 有默认值 `1` → 不必填。**模型看到 `required` 里没有 `days`，就不传它**，你的函数用默认值。

---

## 第二步：注册中心

### 两个全局表（`tools.py:91-92`，节选）

```python
_TOOL_REGISTRY: dict[str, dict] = {}   # 名字 → {函数, schema}，执行时查
_TOOL_SCHEMAS: list[dict] = []          # 所有 schema 的列表，发给模型时用
```

为什么分开？两个用途不同：
- `_TOOL_SCHEMAS` → 直接当 `tools=[...]` 发给模型
- `_TOOL_REGISTRY` → 模型报了个名字，你查它拿到函数来执行

### 注册必须幂等（`tools.py:159-176`，节选）

```python
def register(name: str, schema: dict, fn: Callable) -> dict:
    """把一个工具登记进注册中心。**同名替换，不重复追加。**

    为什么要幂等：注册表是模块级全局的。宿主每轮启动 agent 内核都会重新
    注册一遍，不幂等的话跑第 3 轮时，发给 LLM 的 tools 数组里会有 3 份
    同名工具，OpenAI SDK 直接报 "Duplicate function names"。
    """
    _TOOL_REGISTRY[name] = {"fn": fn, "schema": schema}

    for i, existing in enumerate(_TOOL_SCHEMAS):
        if existing.get("function", {}).get("name") == name:
            _TOOL_SCHEMAS[i] = schema
            break
    else:
        _TOOL_SCHEMAS.append(schema)
    return schema
```

**"同名替换"和"直接追加"的区别，实测一下**：

```
--- 直接 append ---
  注册 3 次后 schemas 里的工具名: ['get_weather', 'get_weather', 'get_weather']
  重名: True  ← OpenAI SDK 会报 'Duplicate function names'

--- 同名替换 ---
  注册 3 次后 schemas 里的工具名: ['get_weather']
  重名: False
```

这个坑**编译期不报、运行早期也不报**，等你跑第 3 轮对话时 API 才炸。所以注册函数从一开始就得写成幂等的。

### 外部注册（`tools.py:185-193`，节选）

```python
def register_external(name, description, parameters, fn) -> dict:
    """注册一个**外部提供 schema** 的工具。

    什么时候用？当 schema 的唯一来源不在 Python 侧时——
    比如 Android 集成里工具定义在 Java 的注册表里（跟 DAO 同源），
    Python 侧启动时拉取后用这个函数注入，避免手抄两份。
    """
```

装饰器是"Python 函数 → Schema"，这个是"外部 Schema → Python 函数"。方向相反。

---

## 第三步：执行器

第一篇的执行逻辑内联在 `run()` 里，只认一个函数。现在工具多了，抽出来（`runner.py`）。

### 四种情况，全部返回消息（`runner.py:21-30`，节选）

```python
def execute(tool_call: dict) -> dict:
    """执行一个 tool_call，返回 role=tool 的结果消息。

    四种情况，**全部返回消息，没有一种抛异常**：
      1. 工具不存在        → 回填"没有这个工具"
      2. 参数不是合法 JSON  → 回填"参数格式错误"
      3. 参数不匹配签名      → 回填"参数不匹配"
      4. 工具内部抛异常      → 回填"错误：xxx"
    """
```

逐个看。

**情况 1：工具不存在**（`runner.py:45-48`，节选）

```python
    fn = tools.get_fn(fn_name)
    if fn is None:
        content = f"错误：没有叫 {fn_name} 的工具。可用工具：{', '.join(tools.names())}"
        return {"role": "tool", "tool_call_id": tool_call_id, "content": content}
```

注意后面那句"可用工具：..."。**把可选项告诉模型**，它能自己改主意换一个，而不是放弃。

**情况 2：参数不是合法 JSON**（`runner.py:51-55`，节选）

```python
    try:
        fn_args = json.loads(raw_args)
    except json.JSONDecodeError as e:
        content = f"错误：工具 {fn_name} 的参数不是合法 JSON（{e}）。请检查参数格式。"
        return {"role": "tool", "tool_call_id": tool_call_id, "content": content}
```

模型偶尔会吐出不合法的 JSON（少了引号、多了逗号）。这时候**别崩，把错误告诉它**，它下一轮会改对。

**情况 3、4：调用失败**（`runner.py:58-67`，节选）

```python
    try:
        result = str(fn(**fn_args))
    except TypeError as e:
        # 参数不匹配签名（少了必填参数 / 传了不认识的参数）
        result = f"错误：参数不匹配（{e}）。请参考工具描述调整参数。"
    except Exception as e:
        # 工具内部出错
        result = f"错误：{e}"
```

**`TypeError` 和其他异常要分开**。因为它们的含义不一样：

- `TypeError` = **模型的错**（参数不匹配），提示它"参考工具描述调整参数"
- 其他异常 = **工具自己的错**（内部炸了），告诉模型也没用，但它知道这次失败了

实测两种情况：

```
✓ 多传参数：错误：参数不匹配（get_weather() got an unexpected keyword argument 'unit'）。
✓ 少传参数：错误：参数不匹配（get_weather() missing 1 required positional argument: 'city'）
✓ 内部炸了：错误：内部炸了
```

### 为什么全部回填而不是抛异常

**因为对模型来说，工具结果和工具报错，格式上没区别**——都是一条 `role=tool` 的消息。

模型看到 `错误：没有叫 get_stock 的工具`，下一步就会改主意。而你抛异常，进程崩了，模型连重试的机会都没有。

这是 Agent 和普通程序最不一样的地方之一：**Agent 的错误处理不是"记日志然后继续"，是"把错误当消息喂回去"。**

---

## 一个真实的坑：模型不遵守类型

Schema 里 `days` 写的是 `number`，但模型可能传字符串。

实测：

```python
tc = runner.build_tool_call("get_weather", {"city": "北京", "days": "3"})
result = runner.execute(tc)

# → "北京：晴，25℃（3 天预报）"    不报错！
```

**Python 不强制类型**。`fn(**{"days": "3"})` 传进去的就是 str，函数里的 f-string 照样能打印。

不报错 ≠ 没问题。后面这行就炸了：

```python
@tool(description="计算")
def add(a: int, b: int) -> str:
    return str(a + b)     # "3" + "5" → TypeError: can only concatenate str
```

**Schema 说的类型是给模型的建议，不是保证。** 工具内部该 `int(x)` 就自己转。

---

## 测试怎么写

`test_tools.py` 有 12 个测试。挑三个最有意思的说。

### Schema 生成（`test_tools.py:39-52`，节选）

```python
def test_schema_generation() -> None:
    props = params_of("get_weather")["properties"]
    req = params_of("get_weather")["required"]

    assert props["city"]["type"] == "string"
    assert props["days"]["type"] == "number"
    assert props["city"]["description"] == "城市名，例如：北京"
    assert req == ["city"]
```

**断言的是 Schema 本身**——这就是"自动生成"的验收标准：类型对、描述对、required 对。

### 四种错误路径（`test_tools.py:123-136`，节选）

```python
def test_bad_json_is_fed_back() -> None:
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

**注意 `tool_call_id` 也要断言**。错误回填同样要跟原请求配对，否则模型收到的消息对不上号——这跟第一篇讲的 `tool_call_id` 是同一个道理。

### 幂等（`test_tools.py:200-213`，节选）

```python
def test_register_is_idempotent() -> None:
    before_count = len(tools.schemas())

    # 模拟宿主每轮重新注册一遍
    for _ in range(3):
        tools.register_external("dup_tool", "...", {...}, lambda x="": x)

    after = [s["function"]["name"] for s in tools.schemas()]
    assert after.count("dup_tool") == 1
```

这个测试的价值在于：**它模拟的是真实场景**（宿主反复注册），不是构造出来的假场景。

---

## 这套工具系统还差什么

| 缺什么 | 生产框架怎么做 | 章节 |
|---|---|---|
| 工具太多，Schema 占满上下文 | 按需加载：先给索引，模型要了才给全文 | 第六篇（技能） |
| 工具危险（写文件、跑 shell） | 权限校验：路径白名单、读/写/执行权限码 | 第五篇（权限） |
| 模型点的工具名不存在 | 回填错误 + 可用工具列表 | 本文已做 |
| 工具之间有依赖 | 并发执行 + 结果顺序保证 | 进阶话题 |
| 工具调了同一个参数反复 | 重复调用拦截 | 进阶话题 |

对照表：Hermes 的 `tools/registry.py`（注册 + Schema 生成）↔ 本文 `tools.py`；Hermes 的 `agent/tool_executor.py`（调度执行）↔ 本文 `runner.py`。

---

## 一总结

工具系统的全部秘密就三句：

1. **工具 = 一份 Schema + 一个函数**。Schema 是给模型看的，函数是你跑的。
2. **Schema 能从函数签名自动生成**——类型从注解来，必填从默认值来，描述从 docstring 来。但**参数描述还得手写**，那恰恰是模型最看重的部分。
3. **执行器要把所有错误变成消息回喂给模型**。工具不存在、参数非法、签名不匹配、内部崩溃——四种情况，一种都不许抛异常。

而"同名替换不重复追加"这条看着像小事，其实是注册表能不能在真实宿主里反复初始化的关键。
