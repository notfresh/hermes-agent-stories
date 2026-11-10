#!/usr/bin/env python3
"""
store.py — 给 Agent 长记性：消息仓库 + 上下文压缩
==================================================

配套教程：tutorial-20261109-03-context-compression.md

Agent 的对话历史每次都全量发给模型：10 轮后请求里带着 20 条旧消息，
token 线性上涨，最终撑爆上下文窗口。本文件解决它：

  - MessageStore：消息列表的唯一入口，循环不直接碰列表
  - compress_if_needed()：超长时按"块"丢中间历史，保住头尾

取自 mini-hermes-v2 的 message_store.py，可对照真实框架源码。
"""

from __future__ import annotations

import copy
from typing import Any, Optional


class MessageStore:
    """消息列表的唯一入口。循环通过它读写消息。"""

    def __init__(self, messages: Optional[list[dict]] = None):
        self._messages: list[dict] = list(messages) if messages else []

    # ── 读 ──────────────────────────────────────────────────────────────

    def all(self) -> list[dict]:
        """返回当前全部消息（浅拷贝，防止外部误改）。"""
        return list(self._messages)

    def snapshot(self) -> list[dict]:
        """深快照，用于持久化/调试。"""
        return copy.deepcopy(self._messages)

    def count(self) -> int:
        return len(self._messages)

    # ── 写 ──────────────────────────────────────────────────────────────

    def append(self, message: dict) -> None:
        """追加一条消息。"""
        self._messages.append(message)

    # ── 压缩 ────────────────────────────────────────────────────────────

    def approximate_tokens(self) -> int:
        """粗略估算当前消息总 token 数（教学版用字符数/2 近似）。

        真实估算要考虑 tools 定义、图片、缓存命中——教学版够用即可。
        """
        total = 0
        for m in self._messages:
            content = m.get("content", "")
            if isinstance(content, str):
                total += len(content)
            for tc in m.get("tool_calls", []) or []:
                total += len(tc.get("function", {}).get("arguments", ""))
        return max(1, total // 2)

    def compress_if_needed(self, max_tokens: int, keep_tail_blocks: int = 3) -> bool:
        """如果超长，按"块"丢中间历史（保留 system + 最近 K 个完整块）。

        关键约束：tool 消息必须随其 assistant 一起丢或留，绝不能产生孤儿
        ——OpenAI/DeepSeek 都拒绝"role=tool 但前面没有带 tool_calls 的
        assistant"的消息序列。

        块的定义：一个 assistant（带 tool_calls 或纯文本）+ 它后面的
        所有 tool 消息 + 收尾的 user/assistant，是一个原子单元。
        压缩按块丢，不会拆散配对。

        Returns: 是否发生了压缩。
        """
        if self.approximate_tokens() <= max_tokens:
            return False

        head = self._messages[:1]  # system
        body = self._messages[1:]

        # 1. 把消息流切成原子块
        atomic_blocks: list[list[dict]] = []
        current: list[dict] = []
        for msg in body:
            role = msg.get("role")
            if role == "assistant":
                # 新 assistant 开新块（上一个块到此为止）
                if current:
                    atomic_blocks.append(current)
                current = [msg]
            elif role == "tool":
                # tool 跟当前块（它属于最近的 assistant）
                if current:
                    current.append(msg)
                else:
                    atomic_blocks.append([msg])  # 孤儿 tool 包成伪块，不丢
            else:
                # user / 其他 → 挂在当前块尾
                if current:
                    current.append(msg)
                else:
                    atomic_blocks.append([msg])
        if current:
            atomic_blocks.append(current)

        # 2. 块不够多就别丢（丢了头部对话就没意义了）
        if len(atomic_blocks) <= keep_tail_blocks:
            return False

        # 3. 保尾部 K 个完整块
        kept = atomic_blocks[-keep_tail_blocks:]
        dropped = sum(len(b) for b in atomic_blocks[:-keep_tail_blocks])

        # 4. 重组：system + 提示 + 尾部块
        new_messages = list(head)
        if dropped > 0:
            new_messages.append({
                "role": "system",
                "content": f"[历史压缩：已丢弃中间 {dropped} 条消息]",
            })
        for block in kept:
            new_messages.extend(block)

        self._messages = new_messages
        return True


if __name__ == "__main__":
    # 演示：超长对话压缩前后
    m = MessageStore([{"role": "system", "content": "你是助手。"}])
    for i in range(8):
        m.append({"role": "user", "content": f"问题{i}。" + "细节" * 200})
        m.append({"role": "assistant", "content": f"回答{i}。" + "内容" * 200})

    print(f"压缩前: {m.count()} 条消息, ~{m.approximate_tokens()} tokens")
    did = m.compress_if_needed(max_tokens=1000)
    print(f"压缩后: {m.count()} 条消息, ~{m.approximate_tokens()} tokens (压缩={did})")
    for i, msg in enumerate(m.all()):
        c = (msg.get("content") or "")[:24]
        print(f"  [{i}] {msg['role']:9} {c!r}")
