#!/usr/bin/env python
"""主程序与运行入口。

用法:
    python run.py                 # 正常启动（自动选择采集方式）
    python run.py --demo          # 演示模式（合成数据，便于体验全部功能）
    python run.py --mode etw      # 强制精确模式（需管理员权限）
    python run.py --data-dir ./d  # 指定数据目录
"""
from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from app.main import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
