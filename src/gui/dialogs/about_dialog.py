# 机械三维二维图互转 — 关于对话框

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QLabel, QPushButton,
    QTextEdit,
)
from PyQt6.QtCore import Qt


class AboutDialog(QDialog):
    """关于对话框

    显示应用程序信息、版本号、技术栈、开源许可等。
    """

    ABOUT_TEXT = """
<h2 style="text-align:center;">机械三维二维图互转</h2>
<p style="text-align:center; font-size:14px;">Mechanical 3D-2D CAD Converter</p>
<p style="text-align:center; color:#888;">版本 0.1.0 (Alpha)</p>

<hr>

<h4>功能特性</h4>
<ul>
  <li>3D 模型 → 2D 工程图：标准三视图、轴测图、剖面图</li>
  <li>2D 草图 → 3D 实体：拉伸建模、旋转建模</li>
  <li>支持格式：STEP / IGES / STL / DXF / BREP</li>
  <li>交互式 3D 预览和 2D 工程图渲染</li>
  <li>自动尺寸标注</li>
</ul>

<h4>技术栈</h4>
<ul>
  <li>GUI 框架：PyQt6</li>
  <li>CAD 内核：OpenCASCADE (PythonOCC)</li>
  <li>DXF 支持：ezdxf</li>
</ul>

<h4>开源许可</h4>
<p>本项目基于 MIT 许可证开源。</p>
<p>OpenCASCADE Technology 版权所有 © Open CASCADE SAS.</p>
"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("关于 机械三维二维图互转")
        self.setFixedSize(480, 460)

        self._setup_ui()

    def _setup_ui(self) -> None:
        """构建对话框 UI"""
        layout = QVBoxLayout(self)

        # 内容区域
        text = QTextEdit()
        text.setReadOnly(True)
        text.setHtml(self.ABOUT_TEXT)
        text.setStyleSheet(
            "QTextEdit { border: none; background: transparent; }"
        )
        layout.addWidget(text)

        # 关闭按钮
        btn_close = QPushButton("关闭")
        btn_close.clicked.connect(self.close)
        layout.addWidget(btn_close, alignment=Qt.AlignmentFlag.AlignCenter)
