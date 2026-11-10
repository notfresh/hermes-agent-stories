#!/usr/bin/env python3
"""
test_store.py — 上下文压缩离线测试
===================================

跑法（不需要 API key）：
    python test_store.py

覆盖四块：
  A. 成本曲线：不压缩时请求体积线性上涨
  B. 压缩触发：超阈值才动、块不够不丢
  C. 配对完整：压缩后 assistant+tool 不拆散、无孤儿
  D. 边界：system 保留、浅拷贝安全
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from store import MessageStore

PASS = 0


def ok(name: str) -> None:
    global PASS
    PASS += 1
    print(f"  ✓ {name}")


def section(title: str) -> None:
    print(f"\n【{title}】")


# ──────────────────────────────────────────────────────────────
section("A. 成本曲线：不压缩时每次请求都带全部历史")

m = MessageStore([{"role": "system", "content": "S"}])
sizes = []
for i in range(6):
    m.append({"role": "user", "content": "U" * 300})
    m.append({"role": "assistant", "content": "A" * 300})
    sizes.append(m.approximate_tokens())

assert all(sizes[i] < sizes[i + 1] for i in range(len(sizes) - 1)), sizes
assert sizes[-1] > sizes[0] * 3, f"6 轮后应涨 3 倍以上: {sizes[0]} → {sizes[-1]}"
print(f"  每轮请求体积: {sizes}")
ok("不压缩时请求体积线性上涨")
assert m.count() == 13  # system + 6*2
ok("消息数也线性上涨（13 条）")


# ──────────────────────────────────────────────────────────────
section("B. 压缩触发条件")

# 未超阈值 → 不动
m2 = MessageStore([{"role": "system", "content": "S"},
                   {"role": "user", "content": "hi"}])
assert m2.compress_if_needed(max_tokens=10000) is False
assert m2.count() == 2
ok("未超阈值：noop")

# 块不够 3 个 → 不丢
m3 = MessageStore([{"role": "system", "content": "S"}])
for i in range(2):
    m3.append({"role": "user", "content": "U" * 900})
    m3.append({"role": "assistant", "content": "A" * 900})
assert m3.approximate_tokens() > 1000  # 确实超了
assert m3.compress_if_needed(max_tokens=1000) is False
assert m3.count() == 5
ok("块不够 3 个：宁可超也不丢")

# 超阈值 + 块够 → 压缩
m4 = MessageStore([{"role": "system", "content": "S"}])
for i in range(8):
    m4.append({"role": "user", "content": "U" * 400})
    m4.append({"role": "assistant", "content": "A" * 400})
before = m4.count()
assert m4.compress_if_needed(max_tokens=1000) is True
assert m4.count() < before
# system + 提示 + 尾部 3 块（user 挂前块尾，实际 1+1+5 条）
assert m4.count() == 1 + 1 + 5
ok(f"压缩触发: {before} → {m4.count()} 条")


# ──────────────────────────────────────────────────────────────
section("C. 配对完整：压缩不拆散 assistant+tool")

m5 = MessageStore([{"role": "system", "content": "S"}])
for i in range(6):
    m5.append({"role": "user", "content": "U" * 300})
    m5.append({"role": "assistant", "tool_calls": [
        {"id": f"c{i}", "type": "function",
         "function": {"name": "f", "arguments": "{}"}}
    ]})
    m5.append({"role": "tool", "tool_call_id": f"c{i}", "content": "R" * 300})
    m5.append({"role": "assistant", "content": "done" * 25})

assert m5.compress_if_needed(600) is True
msgs = m5.all()

# 无孤儿 tool：每条 tool 前面必须是带 tool_calls 的 assistant
orphans = []
for i, msg in enumerate(msgs):
    if msg["role"] == "tool":
        prev = msgs[i - 1] if i > 0 else None
        if not (prev and prev["role"] == "assistant" and prev.get("tool_calls")):
            orphans.append(i)
assert not orphans, f"孤儿 tool: {orphans}"
ok("压缩后无孤儿 tool 消息")

# 保留的 tool_call_id 与 tool 消息一一对应
assistant_ids = set()
for msg in msgs:
    for tc in msg.get("tool_calls", []) or []:
        assistant_ids.add(tc["id"])
tool_ids = {msg["tool_call_id"] for msg in msgs if msg["role"] == "tool"}
assert tool_ids <= assistant_ids, f"tool 引用了不存在的 id: {tool_ids - assistant_ids}"
ok("tool_call_id 与 assistant 的 tool_calls 对得上")

# system 头必须在
assert msgs[0]["role"] == "system"
ok("system 头保留")


# ──────────────────────────────────────────────────────────────
section("D. 边界")

m6 = MessageStore([{"role": "system", "content": "S"},
                   {"role": "user", "content": "hi"}])
m6.all().append({"role": "user", "content": "injected"})
assert m6.count() == 2, "all() 是浅拷贝，外部 append 不应影响内部"
ok("all() 返回浅拷贝，外部误改不影响内部")

snap = m6.snapshot()
snap[0]["content"] = "hacked"
assert m6.all()[0]["content"] == "S"
ok("snapshot() 深拷贝")

print(f"\n{'=' * 46}")
print(f"全部测试通过 ✓ ({PASS} 项)")
print(f"{'=' * 46}")
