#!/usr/bin/env python3
"""
check_refs.py — 校验教程里引用的代码和行号（通用版）
===================================================

教程正文会贴 `tools.py:44-46` 这样的行号引用。代码一改，行号就漂，
读者一对照就发现对不上——这个脚本专门防这件事。

用法（在某个教程目录里）：
    python ../check_refs.py

检查两件事：
1. 引用的行号区间，在源文件里必须存在
2. 教程里贴的代码，必须逐字等于源文件对应行（允许片段标注"节选"）

各教程目录下的 check_refs.py 只是本脚本的一份配置（指定教程名和源文件）。
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent   # hermes-agent-stories/
HERE = Path(__file__).resolve().parent          # examples/

# 匹配：标题里的（`file.py:A-B`）后面紧跟的 ```python 块
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
                f"{tutorial}: {fname}:{lo}-{hi} 越界（文件只有 {max_line} 行）"
            )
            continue

        actual_lines = [src.get(i, "").rstrip() for i in range(lo, hi + 1)]
        claimed_lines = [l.rstrip() for l in code.strip("\n").split("\n")]

        # 2. 标了"节选"的允许片段不一致，但每行必须在源区间里
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
            for i in range(len(actual_lines)):
                if actual_lines[i] != claimed_lines[i]:
                    problems.append(
                        f"{tutorial}: {fname}:{lo}-{hi} 第 {i + 1} 行不一致\n"
                        f"      源  : {actual_lines[i]}\n"
                        f"      教程: {claimed_lines[i]}"
                    )
                    break

    return problems


def run(tutorials: list[tuple[str, dict[str, Path]]]) -> int:
    all_problems: list[str] = []
    for tutorial, sources in tutorials:
        all_problems.extend(check(tutorial, sources))

    if all_problems:
        print("✗ 发现问题：\n")
        for p in all_problems:
            print(f"  {p}\n")
        return 1

    print("✓ 教程里的行号引用和代码全部对得上")
    return 0


def discover() -> list[tuple[str, dict[str, Path]]]:
    """扫描 examples/ 下的所有 tutorial-* 目录，收集校验配置。

    约定：每个教程目录下的 check_refs.py 里定义了 TUTORIALS。
    这里直接 import 它们，避免配置分散在两处。
    """
    import importlib.util

    found = []
    for d in sorted(HERE.glob("tutorial-*")):
        cfg = d / "check_refs.py"
        if not cfg.exists():
            continue
        spec = importlib.util.spec_from_file_location(f"cfg_{d.name}", cfg)
        mod = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = mod
        spec.loader.exec_module(mod)
        found.extend(mod.TUTORIALS)
    return found


if __name__ == "__main__":
    sys.exit(run(discover()))
