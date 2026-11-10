#!/usr/bin/env python3
"""
agent.py — 手写一个 Agent（教程系列 · 第一篇）
================================================

Agent = LLM + Tools + Loop。这个文件就是那三样东西的最小组装。

怎么跑：
    pip install openai
    export DEEPSEEK_API_KEY=sk-xxx
    python agent.py

配套测试（不需要 key，不花钱）：
    python test_agent.py

文件里标了五个编号动作（①～⑤），教程正文逐段对应：

    ① 问模型          ② 判有没有工具请求      ③ 记录请求
    ④ 执行工具        ⑤ 结果回填
"""

from __future__ import annotations

import json
import os
from typing import Any, Optional

from openai import OpenAI


# ────────────────────────────────────────────────────────────────────
# 工具清单 —— 这是"模型能看见的部分"
#
# 关键：模型看不见你的 Python 函数，它只能看见这份 JSON 描述。
# 描述写不清，模型就调不对 —— 工具系统大部分的问题出在这里。
# ────────────────────────────────────────────────────────────────────

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


# ────────────────────────────────────────────────────────────────────
# 工具实现 —— 这是"你进程里真正干活的函数"
#
# 模型只会"点名"要 get_weather，真正跑它的是下面这段代码。
# ────────────────────────────────────────────────────────────────────

def get_weather(city: str) -> str:
    """查询天气。教程里写死返回值，接真实接口时换成 HTTP 请求。"""
    return f"{city}：晴，25℃"


# 工具名 → 函数 的对照表。模型报名字，你按名字找函数。
TOOL_IMPLS = {
    "get_weather": get_weather,
}


def build_system_prompt() -> str:
    """系统提示词：告诉模型它是谁、有哪些工具可用。"""
    tool_lines = "\n".join(
        f"- {t['function']['name']}: {t['function']['description']}"
        for t in TOOLS
    )
    return (
        "你是一个助手，需要信息时用工具查。\n"
        f"你有以下工具可用：\n{tool_lines}\n"
        "用中文回复用户。"
    )


# ────────────────────────────────────────────────────────────────────
# 核心循环 —— 这就是全部
# ────────────────────────────────────────────────────────────────────

def run(
    user_message: str,
    initial_messages: Optional[list[dict]] = None,
    client: Any = None,
    max_turns: int = 10,
) -> tuple[str, list[dict]]:
    """跑一轮完整对话。

    Args:
        user_message: 本轮用户输入
        initial_messages: 上一轮留下的消息历史（接会话时传进来）
        client: 模型客户端。默认连真实 API；测试时传假客户端（见 test_agent.py）
        max_turns: 最多几轮「问模型 → 调工具」，防死循环

    Returns:
        (最终回答, 完整消息历史)
    """
    if client is None:
        client = OpenAI(
            base_url=os.environ.get(
                "DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1"
            ),
            api_key=os.environ.get("DEEPSEEK_API_KEY", ""),
        )

    # ── 回合准备：拼出这次要发给模型的消息列表 ────────────────────
    if initial_messages is None:
        messages = [
            {"role": "system", "content": build_system_prompt()},
            {"role": "user", "content": user_message},
        ]
    else:
        # 接历史：把上一轮的消息整个接上，再追加本轮提问
        messages = list(initial_messages)
        messages.append({"role": "user", "content": user_message})

    # ── 核心循环 ────────────────────────────────────────────────────
    for _ in range(max_turns):
        # ① 问模型：把全部历史 + 工具清单一起发过去
        resp = client.chat.completions.create(
            model="deepseek-chat",
            messages=messages,
            tools=TOOLS,
        )
        msg = resp.choices[0].message

        # ② 判有没有工具请求：没有 = 模型要收工了
        if not msg.tool_calls:
            # 收工前先记下这条回答 —— 多轮能用的关键，漏了会丢上下文
            messages.append({"role": "assistant", "content": msg.content})
            return msg.content, messages

        # ③ 记录请求：把「模型要调工具」这件事写进历史
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

        # ④ 执行工具 + ⑤ 结果回填
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

    # 跑满轮数还没收工：把失败也记进历史，否则这段历史接回去是残的
    messages.append({
        "role": "assistant",
        "content": "(达到最大轮次，未获得最终回复)",
    })
    return "(达到最大轮次，未获得最终回复)", messages


if __name__ == "__main__":
    answer, _ = run("北京今天天气怎么样？")
    print(answer)
