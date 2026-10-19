# -*- coding: utf-8 -*-
"""原神圣遗物强化模拟器 —— 启动入口。

用法：  python main.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from gasim.ui import main  # noqa: E402

if __name__ == "__main__":
    main()
