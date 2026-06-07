# 机械三维二维图互转 — 导入文件对话框

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QComboBox, QCheckBox, QPushButton, QGroupBox,
    QFormLayout, QDialogButtonBox,
)
from PyQt6.QtCore import Qt


class ImportDialog(QDialog):
    """模型文件导入选项对话框

    允许用户在导入前设置：
    - 文件格式（自动检测 / 手动指定）
    - 单位（mm / inch / m）
    - 是否合并为单一实体
    """

    def __init__(self, file_path: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("导入模型")
        self.setMinimumWidth(400)
        self._file_path = file_path

        self._setup_ui()

    def _setup_ui(self) -> None:
        """构建对话框 UI"""
        layout = QVBoxLayout(self)

        # 文件信息
        info_group = QGroupBox("文件信息")
        info_form = QFormLayout()
        info_form.addRow("路径:", QLabel(self._file_path))
        info_form.addRow("检测格式:", QLabel("STEP (AP203/AP214)"))
        info_group.setLayout(info_form)
        layout.addWidget(info_group)

        # 导入选项
        options_group = QGroupBox("导入选项")
        options_layout = QFormLayout()

        self._unit_combo = QComboBox()
        self._unit_combo.addItems(["毫米 (mm)", "英寸 (inch)", "米 (m)"])
        options_layout.addRow("单位:", self._unit_combo)

        self._merge_check = QCheckBox("合并为单一实体")
        self._merge_check.setChecked(True)
        options_layout.addRow(self._merge_check)

        self._heal_check = QCheckBox("自动修复几何体")
        self._heal_check.setChecked(True)
        options_layout.addRow(self._heal_check)

        options_group.setLayout(options_layout)
        layout.addWidget(options_group)

        # 按钮
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok |
            QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    # ------------------------- 公共接口 -------------------------

    def get_unit(self) -> str:
        """获取选择的单位"""
        return self._unit_combo.currentText().split()[0]  # "mm"

    def is_merge_enabled(self) -> bool:
        """是否合并实体"""
        return self._merge_check.isChecked()

    def is_heal_enabled(self) -> bool:
        """是否自动修复"""
        return self._heal_check.isChecked()
