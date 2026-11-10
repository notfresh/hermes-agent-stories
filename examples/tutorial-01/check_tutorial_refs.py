#!/usr/bin/env python3
"""
check_tutorial_refs.py — 校验教程里引用的代码和行号
==================================================

教程正文会贴 `agent.py:143-157` 这样的行号引用。代码一改，行号就漂，
读者一对照就发现对不上——这个脚本专门防这件事。

用法：
    python check_tutorial_refs.py

检查两件事：
1. 引用的行号区间，在源文件里必须存在
2. 教程里贴的代码，必须逐字等于源文件对应行（允许片段标注"节选"）

新增教程时，把 TUTORIALS 加进来即可。
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent          # hermes-agent-stories/

TUTORIALS = [
    ("tutorial-20261109-01-agent-core-loop.md", {
        "agent.py": HERE / "agent.py",
        "test_agent.py": HERE / "test_agent.py",
    }),
]

# 匹配：标题里的（`file.py:A-B`）后面紧跟的 ```python 块
# 注意：代码块内容里可能含 ``` 之外的反引号，这里用非贪婪匹配，
# 并且要求 ```python 之后紧跟代码块结束标记，不允许跨越到下一个块。
BLOCK_RE = re.compile(
    r"（`([\w.]+\.py):(\d+)-(\d+)`）(?P<note>[^\n）]*)"
    r"\s*\n\n```python\n(.*?)\n```",
    re.S,
)


def load_lines(path: Path) -> dict[int, str]:
    """读文件，返回 {行号: 该行内容}（去掉行尾空白）。"""
    out: dict[int, str] = {}
    for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        out[i] = line.rstrip()
    return out


def check(tutorial: str, sources: dict[str, Path]) -> list[str]:
    """返回问题列表，空列表 = 全对。"""
    problems: list[str] = []
    md = (REPO / tutorial).read_text(encoding="utf-8")

    blocks = BLOCK_RE.findall(md)
    if not blocks:
        problems.append(f"{tutorial}: 没找到任何带行号引用的代码块")
        return problems

    for fname, lo_s, hi_s, note, code in blocks:
        lo, hi = int(lo_s), int(hi_s)
        src_path = sources.get(fname)
        if src_path is None:
            problems.append(f"{tutorial}: 引用了未知文件 {fname}")
            continue

        src = load_lines(src_path)

        # 1. 区间必须在文件范围内
        max_line = max(src)
        if lo < 1 or hi > max_line:
            problems.append(
                f"{tutorial}: {fname}:{lo}-{hi} 越界"
                f"（文件只有 {max_line} 行）"
            )
            continue

        # 用 splitlines 保留空行，行数必须严格相等
        actual_lines = [src.get(i, "").rstrip() for i in range(lo, hi + 1)]
        claimed_lines = [l.rstrip() for l in code.strip("\n").split("\n")]

        # 2. 标了"节选"的允许片段不一致，但区间必须合法
        if "节选" in note:
            src_set = set(actual_lines)
            missing = [l for l in claimed_lines if l.strip() and l not in src_set]
            if missing:
                problems.append(
                    f"{tutorial}: {fname}:{lo}-{hi}（节选）里有不在源文件的行："
                    f"{missing[0][:60]}"
                )
            continue

        # 3. 不标"节选"的必须逐字一致（含行数、空行都要对上）
        if len(actual_lines) != len(claimed_lines):
            problems.append(
                f"{tutorial}: {fname}:{lo}-{hi} 行数不对："
                f"源 {len(actual_lines)} 行，教程 {len(claimed_lines)} 行"
            )
            continue

        if actual_lines != claimed_lines:
            diff_at = None
            for i in range(len(actual_lines)):
                if actual_lines[i] != claimed_lines[i]:
                    diff_at = (i + 1, actual_lines[i], claimed_lines[i])
                    break
            if diff_at:
                n, x, y = diff_at
                problems.append(
                    f"{tutorial}: {fname}:{lo}-{hi} 第 {n} 行不一致\n"
                    f"      源  : {x}\n"
                    f"      教程: {y}"
                )

    return problems


def main() -> int:
    all_problems: list[str] = []
    for tutorial, sources in TUTORIALS:
        all_problems.extend(check(tutorial, sources))

    if all_problems:
        print("✗ 发现问题：\n")
        for p in all_problems:
            print(f"  {p}\n")
        return 1

    print("✓ 教程里的行号引用和代码全部对得上")
    return 0


if __name__ == "__main__":
    sys.exit(main())
