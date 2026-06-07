# 机械三维二维图互转 — QApplication 初始化与全局配置

import sys
import os
from pathlib import Path
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt, QLocale, QTranslator
from PyQt6.QtGui import QIcon, QFont


class Application:
    """应用程序主类，负责 QApplication 初始化、主题加载和主窗口启动"""

    APP_NAME = "机械三维二维图互转"
    APP_VERSION = "0.3.0"
    APP_ORG = "CADConverter"

    def __init__(self, argv: list[str]):
        # 高 DPI 缩放支持
        QApplication.setHighDpiScaleFactorRoundingPolicy(
            Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
        )
        self._app = QApplication(argv)
        self._app.setApplicationName(self.APP_NAME)
        self._app.setApplicationVersion(self.APP_VERSION)
        self._app.setOrganizationName(self.APP_ORG)

        # 设置默认字体
        font = QFont("Microsoft YaHei", 9)
        self._app.setFont(font)

        # 加载样式表
        self._load_stylesheet()

    @property
    def project_root(self) -> Path:
        """项目根目录"""
        return Path(__file__).parent.parent

    @property
    def resources_dir(self) -> Path:
        """资源文件目录"""
        return self.project_root / "resources"

    def _load_stylesheet(self) -> None:
        """加载 QSS 样式表"""
        qss_path = self.resources_dir / "styles" / "light_theme.qss"
        if qss_path.exists():
            with open(qss_path, "r", encoding="utf-8") as f:
                self._app.setStyleSheet(f.read())

    def run(self) -> int:
        """启动应用程序主循环"""
        # 延迟导入，避免循环依赖
        from src.gui.main_window import MainWindow

        self._main_window = MainWindow()
        self._main_window.show()

        return self._app.exec()
