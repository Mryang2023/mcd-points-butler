#!/usr/bin/env python3
"""麦麦积分管家一键入口（等价于 python -m mcd_butler）。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from mcd_butler.cli import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
