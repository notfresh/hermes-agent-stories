#!/usr/bin/env python3
"""
tools.py — 工具系统：装饰器注册 + 自动生成 Schema
================================================

第一篇里工具是手写的：一半 JSON Schema，一半函数，加一个工具要改两个地方。
这一篇把它自动化——**写一个函数，Schema 自动生成**。

配套教程：tutorial-20261109-02-tool-system.md
配套测试：python test_tools.py（不需要 API key）
"""

from __future__ import annotations

import inspect
import json
import re
from typing import Any, Callable, Optional, get_type_hints


# ────────────────────────────────────────────────────────────────────
# 一、Schema 自动生成
#
# 三件事：
#   1. 类型注解   → JSON Schema 的 type
#   2. 参数名     → properties 的 key
#   3. docstring  → 参数描述（Google-style Args: 区域）
# ────────────────────────────────────────────────────────────────────

# Python 类型 → JSON Schema 类型
# 注意：只认精确类型，不做 isinstance 判断。
# 因为 bool 是 int 的子类，isinstance(True, int) 是 True，
# 用 isinstance 会把 bool 判成 number。
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


def _parse_docstring_params(docstring: str) -> dict[str, str]:
    """从 Google-style docstring 的 Args: 区域提取 {参数名: 描述}。

    格式要求（缩进很关键）：

        Args:
            path: 文件路径
            limit: 最多读取的行数
    """
    if not docstring:
        return {}

    params: dict[str, str] = {}
    in_args = False
    for line in docstring.split("\n"):
        stripped = line.strip()
        if stripped.startswith("Args:"):
            in_args = True
            continue
        if not in_args:
            continue
        if stripped.startswith("Returns:") or stripped.startswith("Raises:"):
            break
        # 参数行要比 "Args:" 多缩进 4 格
        m = re.match(r"\s{8}(\w+):\s*(.*)", line)
        if m:
            params[m.group(1)] = m.group(2).strip()
        elif stripped == "":
            continue
        elif not line.startswith("    "):
            break   # 缩进回来了 → 离开 Args 区域
    return params


# ────────────────────────────────────────────────────────────────────
# 二、注册中心
#
# 两个全局表：
#   _TOOL_REGISTRY  名字 → {函数, schema}   执行时查
#   _TOOL_SCHEMAS   所有 schema 的列表        发给模型时用
# ────────────────────────────────────────────────────────────────────

_TOOL_REGISTRY: dict[str, dict] = {}
_TOOL_SCHEMAS: list[dict] = []


def tool(name: str = "", description: str = ""):
    """把一个函数注册成模型可调用的工具。

    用法：

        @tool(description="查询天气")
        def get_weather(city: str, days: int = 1) -> str:
            '''查询天气。

            Args:
                city: 城市名，例如：北京
                days: 预报天数，默认 1
            '''
            ...

    Args:
        name: 工具名，默认用函数名
        description: 工具描述，默认用 docstring 第一行

    Returns:
        装饰器
    """
    def decorator(func: Callable) -> Callable:
        tool_name = name or func.__name__
        doc = func.__doc__ or ""

        # description 默认取 docstring 的第一段（Args: 之前）
        tool_desc = description or doc.split("\n\n")[0].strip()

        sig = inspect.signature(func)
        hints = get_type_hints(func)
        param_descs = _parse_docstring_params(doc)

        properties: dict[str, dict] = {}
        required: list[str] = []
        for pname, param in sig.parameters.items():
            if pname == "return":
                continue
            jtype = _pytype_to_jsontype(hints.get(pname, str))
            desc = param_descs.get(pname, f"Parameter {pname}")
            properties[pname] = {"type": jtype, "description": desc}
            # 没有默认值 = 必填
            if param.default is inspect.Parameter.empty:
                required.append(pname)

        schema = {
            "type": "function",
            "function": {
                "name": tool_name,
                "description": tool_desc,
                "parameters": {
                    "type": "object",
                    "properties": properties,
                    "required": required,
                },
            },
        }

        register(tool_name, schema, func)
        return func

    return decorator


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
        if existing.get("function", {}).get("name") == name:
            _TOOL_SCHEMAS[i] = schema
            break
    else:
        _TOOL_SCHEMAS.append(schema)
    return schema


def register_external(
    name: str,
    description: str,
    parameters: dict,
    fn: Callable,
) -> dict:
    """注册一个**外部提供 schema** 的工具。

    什么时候用？当 schema 的唯一来源不在 Python 侧时——
    比如 Android 集成里工具定义在 Java 的注册表里（跟 DAO 同源），
    Python 侧启动时拉取后用这个函数注入，避免手抄两份。

    Args:
        name: 工具名
        description: 工具描述
        parameters: JSON Schema 的 parameters 部分
        fn: 实际执行体，签名与 parameters 一致

    Returns:
        登记的 schema
    """
    schema = {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": parameters,
        },
    }
    return register(name, schema, fn)


def schemas() -> list[dict]:
    """全部工具的 JSON Schema（发给 LLM 的 tools 参数）。"""
    return list(_TOOL_SCHEMAS)


def names() -> list[str]:
    """全部工具名。"""
    return sorted(_TOOL_REGISTRY.keys())


def get_fn(name: str) -> Optional[Callable]:
    """按名字找函数。找不到返回 None。"""
    entry = _TOOL_REGISTRY.get(name)
    return entry["fn"] if entry else None


def summary() -> str:
    """生成工具清单文本（可注入 system prompt）。"""
    lines = []
    for schema in _TOOL_SCHEMAS:
        fn = schema["function"]
        args = ", ".join(
            f"{n}: {info['type']}"
            for n, info in fn["parameters"].get("properties", {}).items()
        )
        lines.append(f"  • {fn['name']}({args}) — {fn['description']}")
    return "\n".join(lines)


# ────────────────────────────────────────────────────────────────────
# 三、内置工具（用装饰器注册）
# ────────────────────────────────────────────────────────────────────

@tool(description="查询某个城市的当前天气")
def get_weather(city: str, days: int = 1) -> str:
    """查询某个城市的当前天气。

    Args:
        city: 城市名，例如：北京
        days: 预报天数，默认 1
    """
    return f"{city}：晴，25℃（{days} 天预报）"


@tool(description="列出目录下的文件")
def ls(path: str = ".") -> str:
    """列出目录下的文件。

    Args:
        path: 目录路径，默认当前目录
    """
    import pathlib
    try:
        entries = sorted(pathlib.Path(path).iterdir(), key=lambda p: p.name)
        if not entries:
            return f"(空目录: {path})"
        return "\n".join(
            f"{'📁' if e.is_dir() else '📄'} {e.name}" for e in entries
        )
    except Exception as e:
        return f"错误：{e}"


@tool(description="计算数学表达式，如 '(3+5)*2'")
def calculator(expression: str) -> str:
    """计算数学表达式。

    只支持 + - * / ( ) 和数字，不做变量替换。

    Args:
        expression: 数学表达式
    """
    try:
        # 安全起见：只允许数字和运算符
        if not re.fullmatch(r"[\d\s+\-*/().]+", expression):
            return "错误：表达式含不允许的字符"
        return str(eval(expression, {"__builtins__": {}}, {}))  # noqa: S307
    except Exception as e:
        return f"错误：{e}"


if __name__ == "__main__":
    print("已注册工具：")
    print(summary())
    print()
    print("Schema 示例（get_weather）：")
    print(json.dumps(
        next(s for s in schemas() if s["function"]["name"] == "get_weather"),
        ensure_ascii=False,
        indent=2,
    ))
