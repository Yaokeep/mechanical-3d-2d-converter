# 机械三维二维图互转 — 拉伸建模参数对话框

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QFormLayout,
    QDoubleSpinBox, QComboBox, QDialogButtonBox,
    QGroupBox, QLabel,
)
from PyQt6.QtCore import Qt
from enum import Enum


class ExtrudeDirection(Enum):
    """拉伸方向"""
    POSITIVE_X = ("+X", (1, 0, 0))
    NEGATIVE_X = ("-X", (-1, 0, 0))
    POSITIVE_Y = ("+Y", (0, 1, 0))
    NEGATIVE_Y = ("-Y", (0, -1, 0))
    POSITIVE_Z = ("+Z", (0, 0, 1))
    NEGATIVE_Z = ("-Z", (0, 0, -1))


class ExtrudeDialog(QDialog):
    """拉伸建模参数设置对话框

    用户从 DXF 导入 2D 草图后，通过此对话框设置：
    - 拉伸方向
    - 拉伸深度
    - 拔模角度
    - 是否双向拉伸
    """

    def __init__(self, sketch_name: str = "", parent=None):
        super().__init__(parent)
        self.setWindowTitle("拉伸建模")
        self.setMinimumWidth(380)
        self._sketch_name = sketch_name

        self._setup_ui()

    def _setup_ui(self) -> None:
        """构建对话框 UI"""
        layout = QVBoxLayout(self)

        # 草图信息
        if self._sketch_name:
            info_label = QLabel(f"草图: {self._sketch_name}")
            info_label.setStyleSheet("font-weight: bold;")
            layout.addWidget(info_label)

        # 拉伸参数
        params_group = QGroupBox("拉伸参数")
        params_form = QFormLayout()

        # 方向
        self._dir_combo = QComboBox()
        for direction in ExtrudeDirection:
            self._dir_combo.addItem(direction.value[0], direction)
        params_form.addRow("方向:", self._dir_combo)

        # 深度
        self._depth_spin = QDoubleSpinBox()
        self._depth_spin.setRange(0.01, 10000.0)
        self._depth_spin.setValue(10.0)
        self._depth_spin.setSingleStep(1.0)
        self._depth_spin.setSuffix(" mm")
        params_form.addRow("深度:", self._depth_spin)

        # 拔模角度
        self._taper_spin = QDoubleSpinBox()
        self._taper_spin.setRange(-30.0, 30.0)
        self._taper_spin.setValue(0.0)
        self._taper_spin.setSingleStep(0.5)
        self._taper_spin.setSuffix(" °")
        params_form.addRow("拔模角度:", self._taper_spin)

        params_group.setLayout(params_form)
        layout.addWidget(params_group)

        # 按钮
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok |
            QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    # ------------------------- 公共接口 -------------------------

    def get_direction(self) -> ExtrudeDirection:
        """获取拉伸方向"""
        return self._dir_combo.currentData()

    def get_depth(self) -> float:
        """获取拉伸深度 (mm)"""
        return self._depth_spin.value()

    def get_taper_angle(self) -> float:
        """获取拔模角度 (度)"""
        return self._taper_spin.value()
