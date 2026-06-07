# 机械三维二维图互转 — Mechanical 3D-2D CAD Converter
# 应用入口

import sys
import os

# 将 src 目录加入 Python 路径
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
SRC_PATH = os.path.join(PROJECT_ROOT, "src")
if SRC_PATH not in sys.path:
    sys.path.insert(0, SRC_PATH)

from src.app import Application


def main():
    """应用程序主入口"""
    app = Application(sys.argv)
    sys.exit(app.run())


if __name__ == "__main__":
    main()
