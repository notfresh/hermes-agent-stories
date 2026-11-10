#!/usr/bin/env python3
"""
check_refs.py — 第二篇教程的行号引用校验（配置版）

通用逻辑在 examples/check_refs.py，这里只指定教程名和源文件。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from check_refs import run

HERE = Path(__file__).resolve().parent

TUTORIALS = [
    ("tutorial-20261109-02-tool-system.md", {
        "tools.py": HERE / "tools.py",
        "runner.py": HERE / "runner.py",
        "test_tools.py": HERE / "test_tools.py",
    }),
]

if __name__ == "__main__":
    sys.exit(run(TUTORIALS))
