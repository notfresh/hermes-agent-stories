#!/usr/bin/env python3
"""
check_refs.py — 第一篇教程的行号引用校验（配置版）

通用逻辑在 examples/check_refs.py，这里只指定教程名和源文件。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from check_refs import run

HERE = Path(__file__).resolve().parent

TUTORIALS = [
    ("tutorial-20261109-01-agent-core-loop.md", {
        "agent.py": HERE / "agent.py",
        "test_agent.py": HERE / "test_agent.py",
    }),
]

if __name__ == "__main__":
    sys.exit(run(TUTORIALS))
