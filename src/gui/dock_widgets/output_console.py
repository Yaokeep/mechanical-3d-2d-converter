# 机械三维二维图互转 — 输出控制台 Dock 面板

from PyQt6.QtWidgets import (
    QDockWidget, QTextEdit, QVBoxLayout, QWidget,
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QTextCursor, QColor, QFont


class OutputConsoleDock(QDockWidget):
    """输出控制台面板

    显示应用程序日志、导入/导出信息、错误消息等。
    支持不同级别的消息着色：
    - 信息 (Info)：默认黑色
    - 警告 (Warning)：橙色
    - 错误 (Error)：红色
    - 成功 (Success)：绿色
    """

    # 信号
    message_logged = pyqtSignal(str)  # 每条消息

    def __init__(self, title: str, parent=None):
        super().__init__(title, parent)
        self.setObjectName("OutputConsoleDock")
        self.setFeatures(
            QDockWidget.DockWidgetFeature.DockWidgetMovable |
            QDockWidget.DockWidgetFeature.DockWidgetClosable
        )
        self._setup_ui()

    def _setup_ui(self) -> None:
        """构建文本编辑区域"""
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(2, 2, 2, 2)

        self._text_edit = QTextEdit()
        self._text_edit.setReadOnly(True)
        self._text_edit.setFont(QFont("Consolas", 9))
        self._text_edit.setStyleSheet(
            "QTextEdit { background-color: #1e1e1e; color: #d4d4d4; }"
        )
        self._text_edit.setMinimumHeight(80)

        layout.addWidget(self._text_edit)
        self.setWidget(container)

    # ------------------------- 公共接口 -------------------------

    def info(self, message: str) -> None:
        """输出信息级别日志"""
        self._append(message, QColor(212, 212, 212))
        self.message_logged.emit(message)

    def success(self, message: str) -> None:
        """输出成功信息"""
        self._append(message, QColor(78, 201, 176))
        self.message_logged.emit(message)

    def warning(self, message: str) -> None:
        """输出警告信息"""
        self._append(message, QColor(206, 145, 120))
        self.message_logged.emit(message)

    def error(self, message: str) -> None:
        """输出错误信息"""
        self._append(message, QColor(244, 71, 71))
        self.message_logged.emit(message)

    def clear(self) -> None:
        """清空控制台"""
        self._text_edit.clear()

    # ------------------------- 内部方法 -------------------------

    def _append(self, message: str, color: QColor) -> None:
        """向控制台追加带颜色文本"""
        cursor = self._text_edit.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)

        fmt = cursor.charFormat()
        fmt.setForeground(color)
        cursor.setCharFormat(fmt)
        cursor.insertText(message + "\n")

        # 自动滚动到底部
        self._text_edit.setTextCursor(cursor)
        self._text_edit.ensureCursorVisible()
