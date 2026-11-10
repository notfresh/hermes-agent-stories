#!/usr/bin/env python3
"""
test_agent.py — agent.py 的离线测试
====================================

跑法（不需要 API key，不花钱）：
    python test_agent.py

为什么需要这个文件
------------------
agent.py 里真正和模型打交道的是这一行：

    resp = client.chat.completions.create(...)

要测"模型看到了什么"，就必须能看见发给模型的 messages。
真 API 看不见（你只能等它返回结果），所以这里用一个假客户端顶上——
它照抄 OpenAI 的返回形状，并把每次收到的 messages 记下来。

这就是 FakeClient 的全部职责：**替代真客户端，当记录器用。**

agent.run(client=...) 这个参数就是为它留的口子。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from agent import TOOLS, run


# ────────────────────────────────────────────────────────────────────
# 假客户端
# ────────────────────────────────────────────────────────────────────

class FakeClient:
    """假模型客户端。

    照抄 OpenAI SDK 的形状：client.chat.completions.create(...)
    返回 response.choices[0].message，message 上有 .content 和 .tool_calls。

    行为按脚本走：脚本是一串 (content, tool_calls) 回应，
    每次调用取一个；取完就重复最后一个。

    .calls 是它的"抓包记录"：每次调用收到的 messages 都存了一份。
    """

    def __init__(self, script: list[tuple[str | None, list | None]]):
        """
        Args:
            script: 每次调用的回应。元素是 (content, tool_calls)：
                    content  = 模型的文字
                    tool_calls = 工具调用列表，None 表示这轮不调工具
        """
        self.script = script
        self.calls: list[list[dict]] = []   # 抓包记录
        self.chat = type("Chat", (), {"completions": self})()
        self.completions = self

    def create(self, model=None, messages=None, tools=None, temperature=None):
        # 抓包：把这次收到的 messages 记下来
        self.calls.append([dict(m) for m in messages])

        index = min(len(self.calls) - 1, len(self.script) - 1)
        content, tool_calls = self.script[index]

        message = type("M", (), {"content": content, "tool_calls": tool_calls})()
        return type("R", (), {"choices": [type("C", (), {"message": message})()]})()


def make_tool_call(name: str, args: dict, call_id: str = "call_1"):
    """造一个工具调用对象，形状跟 OpenAI SDK 返回的一致。"""
    import json
    return type("T", (), {
        "id": call_id,
        "type": "function",
        "function": type("F", (), {"name": name, "arguments": json.dumps(args)})(),
    })()


def roles_of(calls: list[list[dict]], index: int) -> list[str]:
    """取第 index 次请求里，模型看到的角色序列。"""
    return [m.get("role") for m in calls[index]]


def contents_of(calls: list[list[dict]], index: int) -> list[str]:
    """取第 index 次请求里，模型看到的全部文字内容。"""
    return [str(m.get("content")) for m in calls[index]]


# ────────────────────────────────────────────────────────────────────
# 测试 1：单轮 —— 模型要工具 → 执行 → 回填 → 模型收工
# ────────────────────────────────────────────────────────────────────

def test_single_turn() -> None:
    print("【测试 1】单轮对话：模型要工具，执行后回填，模型收工")

    client = FakeClient([
        (None, [make_tool_call("get_weather", {"city": "北京"})]),  # 第 1 次：我要调工具
        ("北京今天晴，25℃。", None),                              # 第 2 次：我说完了
    ])

    answer, messages = run("北京天气怎么样？", client=client)

    assert answer == "北京今天晴，25℃。", f"最终回答不对：{answer}"

    # 第 2 次请求里，模型应该看到了：system → user → assistant(要工具) → tool(结果)
    assert roles_of(client.calls, 1) == ["system", "user", "assistant", "tool"], \
        f"消息序列不对：{roles_of(client.calls, 1)}"

    # 工具结果确实被回填了，且和请求配对
    tool_msg = client.calls[1][3]
    assert tool_msg["role"] == "tool"
    assert tool_msg["tool_call_id"] == "call_1"
    assert tool_msg["content"] == "北京：晴，25℃"

    print(f"  ✓ 最终回答：{answer}")
    print(f"  ✓ 第 2 次请求角色序列：{roles_of(client.calls, 1)}")
    print()


# ────────────────────────────────────────────────────────────────────
# 测试 2：多轮 —— 历史带没带回去（这节对应教程的"坑"）
# ────────────────────────────────────────────────────────────────────

def test_multi_turn_keeps_history() -> None:
    print("【测试 2】多轮对话：第 2 轮请求里，第 1 轮的问和答都要在")

    client = FakeClient([
        (None, [make_tool_call("get_weather", {"city": "北京"})]),  # 第 1 次：要工具
        ("北京今天晴，25℃。", None),                              # 第 2 次：收工
        (None, [make_tool_call("get_weather", {"city": "北京"})]),  # 第 3 次：第 2 轮又要工具
        ("建议穿短袖。", None),                                   # 第 4 次：收工
    ])

    # 第 1 轮
    answer1, history = run("北京天气怎么样？", client=client)
    assert answer1 == "北京今天晴，25℃。"

    # 第 2 轮：把第 1 轮的历史接回去
    answer2, history2 = run("那我该穿什么？", initial_messages=history, client=client)

    assert answer2 == "建议穿短袖。"

    # 第 3 次请求 = 第 2 轮的首个请求
    second_round = client.calls[2]
    second_roles = roles_of(client.calls, 2)

    # 第 1 轮的用户提问必须在
    assert any("北京天气怎么样？" in c for c in contents_of(client.calls, 2)), \
        "第 1 轮的用户提问丢了"

    # 第 1 轮 Agent 的最终回答也必须在 ← 这条就是那个 bug 的守门断言
    assert any("北京今天晴" in c for c in contents_of(client.calls, 2)), \
        "第 1 轮的 Agent 回答丢了（多轮上下文丢失的 bug）"

    # 顺序也该对：system → user → assistant(工具请求) → tool(结果) → assistant(回答) → user
    assert second_roles == [
        "system", "user", "assistant", "tool", "assistant", "user"
    ], f"第 2 轮消息序列不对：{second_roles}"

    print(f"  ✓ 第 2 轮请求角色序列：{second_roles}")
    print(f"  ✓ 第 1 轮的回答在里面：{[c for c in contents_of(client.calls, 2) if '北京今天晴' in c]}")
    print()


# ────────────────────────────────────────────────────────────────────
# 测试 3：相邻 user —— 另一种接线错误
# ────────────────────────────────────────────────────────────────────

def test_no_adjacent_user() -> None:
    print("【测试 3】相邻 user 检查：模型不能看到两条挨着的 user")

    client = FakeClient([
        (None, [make_tool_call("get_weather", {"city": "北京"})]),
        ("北京今天晴，25℃。", None),
    ])

    answer, history = run("北京天气怎么样？", client=client)
    answer2, history2 = run("那我该穿什么？", initial_messages=history, client=client)

    for index in range(len(client.calls)):
        roles = roles_of(client.calls, index)
        for a, b in zip(roles, roles[1:]):
            assert not (a == "user" and b == "user"), \
                f"第 {index} 次请求里有两条挨着的 user：{roles}"

    print(f"  ✓ {len(client.calls)} 次请求都没有相邻 user")
    print()


# ────────────────────────────────────────────────────────────────────
# 测试 4：工具出错不当异常处理，而是回填给模型
# ────────────────────────────────────────────────────────────────────

def test_tool_error_is_fed_back() -> None:
    print("【测试 4】工具报错：结果回填给模型，不是抛异常")

    client = FakeClient([
        # 模型传了一个 get_weather 不认识的参数 → 调用时抛 TypeError
        (None, [make_tool_call("get_weather", {"city": "北京", "unit": "celsius"})]),
        ("我查不到这个城市的天气。", None),
    ])

    answer, messages = run("北京天气怎么样？", client=client)

    # 第 2 次请求里的 tool 结果应该是一条错误信息
    tool_msgs = [m for m in client.calls[1] if m.get("role") == "tool"]
    assert tool_msgs, "没有 tool 结果消息"
    assert tool_msgs[0]["content"].startswith("错误："), \
        f"工具错误没有回填给模型：{tool_msgs[0]['content']}"

    print(f"  ✓ 工具错误回填内容：{tool_msgs[0]['content'][:60]}")
    print()


# ────────────────────────────────────────────────────────────────────
# 测试 5：工具不存在也要回填，不能崩
# ────────────────────────────────────────────────────────────────────

def test_unknown_tool_is_fed_back() -> None:
    print("【测试 5】模型点了不存在的工具：回填错误，不能崩")

    client = FakeClient([
        (None, [make_tool_call("get_stock", {"code": "AAPL"})]),
        ("我没有这个工具。", None),
    ])

    answer, messages = run("查一下 AAPL", client=client)

    tool_msgs = [m for m in client.calls[1] if m.get("role") == "tool"]
    assert tool_msgs, "没有 tool 结果消息"
    assert "没有叫 get_stock 的工具" in tool_msgs[0]["content"], \
        tool_msgs[0]["content"]

    print(f"  ✓ 回填内容：{tool_msgs[0]['content']}")
    print()


# ────────────────────────────────────────────────────────────────────
# 跑全部
# ────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 60)
    print("agent.py 离线测试（不需要 API key）")
    print("=" * 60)
    print()

    test_single_turn()
    test_multi_turn_keeps_history()
    test_no_adjacent_user()
    test_tool_error_is_fed_back()
    test_unknown_tool_is_fed_back()

    print("=" * 60)
    print("全部测试通过 ✓")
    print("=" * 60)
