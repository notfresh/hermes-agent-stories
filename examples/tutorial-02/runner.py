#!/usr/bin/env python3
"""
runner.py — 工具执行器：按名字找函数、执行、错误回填
======================================================

第一篇里执行工具的逻辑是内联在 run() 里的，只认一个函数。
这一篇抽出来：工具多了以后（3 个 → 30 个），内联就撑不住了。

配套教程：tutorial-20261109-02-tool-system.md
配套测试：python test_runner.py（不需要 API key）
"""

from __future__ import annotations

import json
from typing import Any

import tools


def execute(tool_call: dict) -> dict:
    """执行一个 tool_call，返回 role=tool 的结果消息。

    四种情况，**全部返回消息，没有一种抛异常**：
      1. 工具不存在        → 回填"没有这个工具"
      2. 参数不是合法 JSON  → 回填"参数格式错误"
      3. 参数不匹配签名      → 回填"参数不匹配"
      4. 工具内部抛异常      → 回填"错误：xxx"

    为什么要这样：对模型来说，工具结果和工具报错**格式上没区别**——
    都是一条 role=tool 的消息。它看到"错误：..."就能自己改主意。
    而如果你抛异常，整个进程崩了，模型连重试的机会都没有。

    Args:
        tool_call: {"id", "type", "function": {"name", "arguments"}}

    Returns:
        {"role": "tool", "tool_call_id": ..., "content": ...}
    """
    fn_name = tool_call["function"]["name"]
    tool_call_id = tool_call.get("id", "")
    raw_args = tool_call["function"].get("arguments", "") or "{}"

    # ── 情况 1：工具不存在 ────────────────────────────────────────
    fn = tools.get_fn(fn_name)
    if fn is None:
        content = f"错误：没有叫 {fn_name} 的工具。可用工具：{', '.join(tools.names())}"
        return {"role": "tool", "tool_call_id": tool_call_id, "content": content}

    # ── 情况 2：参数不是合法 JSON ─────────────────────────────────
    try:
        fn_args = json.loads(raw_args)
    except json.JSONDecodeError as e:
        content = f"错误：工具 {fn_name} 的参数不是合法 JSON（{e}）。请检查参数格式。"
        return {"role": "tool", "tool_call_id": tool_call_id, "content": content}

    # ── 情况 3、4：调用失败 ───────────────────────────────────────
    try:
        result = str(fn(**fn_args))
    except TypeError as e:
        # 参数不匹配签名（少了必填参数 / 传了不认识的参数）
        result = f"错误：参数不匹配（{e}）。请参考工具描述调整参数。"
    except Exception as e:
        # 工具内部出错
        result = f"错误：{e}"

    return {"role": "tool", "tool_call_id": tool_call_id, "content": result}


def execute_all(tool_calls: list[dict]) -> list[dict]:
    """执行一批 tool_calls，按顺序返回结果消息。

    教学版串行执行。生产框架会并发跑（工具之间无依赖时），
    但并发会引入"结果顺序"问题——这里先保证顺序和直觉一致。
    """
    return [execute(tc) for tc in tool_calls]


def build_tool_call(name: str, args: dict, call_id: str = "call_1") -> dict:
    """造一个 tool_call（形状跟 OpenAI SDK 返回的一致）。测试里用。"""
    return {
        "id": call_id,
        "type": "function",
        "function": {
            "name": name,
            "arguments": json.dumps(args, ensure_ascii=False),
        },
    }


if __name__ == "__main__":
    tc = build_tool_call("get_weather", {"city": "北京", "days": 3})
    print("执行：", tc["function"]["name"], tc["function"]["arguments"])
    print("结果：", execute(tc)["content"])
