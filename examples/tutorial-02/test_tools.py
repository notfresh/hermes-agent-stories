#!/usr/bin/env python3
"""
test_tools.py — 工具系统离线测试
=================================

跑法（不需要 API key）：
    python test_tools.py

覆盖三块：
  A. Schema 自动生成（类型映射、required、参数描述）
  B. 执行器的四种错误路径
  C. 注册的幂等性
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import runner
import tools


def schema_of(name: str) -> dict:
    """取某个工具的 schema。"""
    return next(s for s in tools.schemas() if s["function"]["name"] == name)


def params_of(name: str) -> dict:
    """取某个工具的 parameters 部分。"""
    return schema_of(name)["function"]["parameters"]


# ── A. Schema 自动生成 ─────────────────────────────────────────────

def test_schema_generation() -> None:
    print("【A1】Schema 自动生成：类型、required、参数描述")

    props = params_of("get_weather")["properties"]
    req = params_of("get_weather")["required"]

    # 类型注解 → JSON Schema type
    assert props["city"]["type"] == "string", props
    assert props["days"]["type"] == "number", props

    # docstring 的 Args: 区域 → 参数描述
    assert props["city"]["description"] == "城市名，例如：北京", props
    assert props["days"]["description"] == "预报天数，默认 1", props

    # 没有默认值的参数 = required
    assert req == ["city"], req
    assert "days" not in req

    # 工具描述来自装饰器参数
    assert schema_of("get_weather")["function"]["description"] == "查询某个城市的当前天气"

    print(f"  ✓ 类型：city={props['city']['type']}, days={props['days']['type']}")
    print(f"  ✓ 描述：{props['city']['description']!r}")
    print(f"  ✓ required：{req}")
    print()


def test_default_value_makes_optional() -> None:
    print("【A2】有默认值的参数不算 required")

    params = params_of("ls")
    assert params["required"] == [], params
    assert params["properties"]["path"]["type"] == "string"

    print(f"  ✓ ls() 无 required 参数（path 有默认值 '.'）")
    print()


def test_missing_docstring_is_degraded_not_broken() -> None:
    print("【A3】没写 docstring：退化但不崩")

    @tools.tool(description="没写 docstring 的工具")
    def no_doc(x: str) -> str:
        return ""

    params = params_of("no_doc")
    assert params["properties"]["x"]["description"] == "Parameter x", params
    assert params["required"] == ["x"]

    print(f"  ✓ 参数描述退化为 'Parameter x'（模型看不懂这个参数是干嘛的）")
    print()


# ── B. 执行器的四种错误路径 ─────────────────────────────────────────

def test_execute_normal() -> None:
    print("【B1】正常执行")

    tc = runner.build_tool_call("get_weather", {"city": "北京", "days": 3})
    result = runner.execute(tc)

    assert result["role"] == "tool"
    assert result["tool_call_id"] == "call_1"
    assert "北京" in result["content"] and "3" in result["content"]

    print(f"  ✓ {result['content']}")
    print()


def test_unknown_tool_is_fed_back() -> None:
    print("【B2】工具不存在：回填错误，不崩")

    tc = runner.build_tool_call("get_stock", {"code": "AAPL"})
    result = runner.execute(tc)

    assert result["role"] == "tool"
    assert "没有叫 get_stock 的工具" in result["content"]
    # 还要告诉模型有哪些工具可选
    assert "get_weather" in result["content"]

    print(f"  ✓ {result['content']}")
    print()


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

    print(f"  ✓ {result['content'][:70]}")
    print()


def test_wrong_params_is_fed_back() -> None:
    print("【B4】参数不匹配签名：回填错误，不崩")

    # 传了一个 get_weather 不认识的参数
    tc = runner.build_tool_call("get_weather", {"city": "北京", "unit": "celsius"})
    result = runner.execute(tc)

    assert result["role"] == "tool"
    assert "参数不匹配" in result["content"]

    # 少了必填参数
    tc2 = runner.build_tool_call("get_weather", {})
    result2 = runner.execute(tc2)
    assert "参数不匹配" in result2["content"]

    print(f"  ✓ 多传参数：{result['content'][:60]}")
    print(f"  ✓ 少传参数：{result2['content'][:60]}")
    print()


def test_tool_internal_error_is_fed_back() -> None:
    print("【B5】工具内部抛异常：回填错误，不崩")

    @tools.tool(description="会崩的工具")
    def boom(x: str) -> str:
        raise RuntimeError("内部炸了")

    tc = runner.build_tool_call("boom", {"x": "1"})
    result = runner.execute(tc)

    assert result["role"] == "tool"
    assert "内部炸了" in result["content"]

    print(f"  ✓ {result['content']}")
    print()


def test_execute_all_keeps_order() -> None:
    print("【B6】一次调多个工具：结果按顺序回填")

    calls = [
        runner.build_tool_call("get_weather", {"city": "北京"}, "call_1"),
        runner.build_tool_call("calculator", {"expression": "(3+5)*2"}, "call_2"),
        runner.build_tool_call("get_stock", {"code": "AAPL"}, "call_3"),
    ]
    results = runner.execute_all(calls)

    assert len(results) == 3
    assert [r["tool_call_id"] for r in results] == ["call_1", "call_2", "call_3"]
    assert "北京" in results[0]["content"]
    assert "16" in results[1]["content"]
    assert "没有叫 get_stock 的工具" in results[2]["content"]

    print(f"  ✓ 三个结果顺序和 id 都对上了")
    print()


# ── C. 注册的幂等性 ─────────────────────────────────────────────────

def test_register_is_idempotent() -> None:
    print("【C1】重复注册同名工具：不产生重名")

    before = [s["function"]["name"] for s in tools.schemas()]
    before_count = len(before)

    # 模拟宿主每轮重新注册一遍
    for _ in range(3):
        tools.register_external(
            "dup_tool",
            "重复注册的工具",
            {"type": "object", "properties": {}, "required": []},
            lambda x="": x,
        )

    after = [s["function"]["name"] for s in tools.schemas()]
    dup_count = after.count("dup_tool")

    assert dup_count == 1, f"重名了 {dup_count} 次：{after}"
    assert len(after) == before_count + 1

    print(f"  ✓ 注册 3 次，schemas 里只有 1 份：{after.count('dup_tool')} 份")
    print(f"  ✓ 全部工具名无重复：{len(after) == len(set(after))}")
    print()


def test_no_duplicate_function_names() -> None:
    print("【C2】发给模型的 tools 数组里不能有重名")

    names = [s["function"]["name"] for s in tools.schemas()]
    assert len(names) == len(set(names)), f"有重名：{names}"

    print(f"  ✓ {len(names)} 个工具，名字全不重复")
    print()


# ── D. 一个真实的坑：模型可能传字符串 ──────────────────────────────

def test_model_may_pass_string_for_int() -> None:
    print("【D1】模型可能给 int 参数传字符串——Python 不拦你")

    tc = runner.build_tool_call("get_weather", {"city": "北京", "days": "3"})
    result = runner.execute(tc)

    # 不报错，但函数里拿到的是 str
    assert "错误" not in result["content"], result
    assert "3 天预报" in result["content"], result

    print(f"  ✓ {result['content']}")
    print(f"  ⚠️ 但 days 实际是 str 不是 int——schema 说的是 number，模型没遵守")
    print(f"     这个类型漂移只能靠工具内部自己兜（比如 int(days)）")
    print()


# ── 跑全部 ──────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 62)
    print("工具系统离线测试（不需要 API key）")
    print("=" * 62)
    print()

    test_schema_generation()
    test_default_value_makes_optional()
    test_missing_docstring_is_degraded_not_broken()

    test_execute_normal()
    test_unknown_tool_is_fed_back()
    test_bad_json_is_fed_back()
    test_wrong_params_is_fed_back()
    test_tool_internal_error_is_fed_back()
    test_execute_all_keeps_order()

    test_register_is_idempotent()
    test_no_duplicate_function_names()

    test_model_may_pass_string_for_int()

    print("=" * 62)
    print("全部测试通过 ✓")
    print("=" * 62)
