# 机械三维二维图互转 — 导出文件对话框

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QFormLayout, QLabel,
    QComboBox, QCheckBox, QDialogButtonBox,
    QGroupBox, QSpinBox, QDoubleSpinBox,
)
from PyQt6.QtCore import Qt


class ExportDialog(QDialog):
    """模型/工程图导出选项对话框

    允许用户设置导出参数：
    - 导出格式（STEP / IGES / STL / DXF）
    - 精度设置
    - DXF 图层映射
    """

    FORMATS = [
        ("STEP (.step/.stp)", "step"),
        ("IGES (.iges/.igs)", "iges"),
        ("STL (.stl)", "stl"),
        ("BREP (.brep)", "brep"),
        ("DXF 工程图 (.dxf)", "dxf"),
    ]

    def __init__(self, is_2d: bool = False, parent=None):
        """
        Args:
            is_2d: True 表示导出 2D 工程图，False 表示导出 3D 模型
        """
        super().__init__(parent)
        self.setWindowTitle("导出" + ("工程图" if is_2d else "模型"))
        self.setMinimumWidth(400)
        self._is_2d = is_2d

        self._setup_ui()

    def _setup_ui(self) -> None:
        """构建对话框 UI"""
        layout = QVBoxLayout(self)

        # 格式选择
        format_group = QGroupBox("导出格式")
        format_form = QFormLayout()

        self._format_combo = QComboBox()
        if self._is_2d:
            self._format_combo.addItem("DXF 工程图 (.dxf)", "dxf")
        else:
            for label, key in self.FORMATS[:-1]:  # 排除 DXF
                self._format_combo.addItem(label, key)
        format_form.addRow("格式:", self._format_combo)

        format_group.setLayout(format_form)
        layout.addWidget(format_group)

        # 精度设置
        precision_group = QGroupBox("精度设置")
        precision_form = QFormLayout()

        self._precision_spin = QDoubleSpinBox()
        self._precision_spin.setRange(0.001, 10.0)
        self._precision_spin.setValue(0.01)
        self._precision_spin.setSingleStep(0.01)
        self._precision_spin.setSuffix(" mm")
        precision_form.addRow("公差:", self._precision_spin)

        precision_group.setLayout(precision_form)
        layout.addWidget(precision_group)

        # 选项
        self._binary_check = QCheckBox("二进制格式（仅 STL）")
        layout.addWidget(self._binary_check)

        # 按钮
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok |
            QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    # ------------------------- 公共接口 -------------------------

    def get_format(self) -> str:
        """获取选择的导出格式"""
        return self._format_combo.currentData()

    def get_precision(self) -> float:
        """获取精度值"""
        return self._precision_spin.value()

    def is_binary(self) -> bool:
        """是否使用二进制格式"""
        return self._binary_check.isChecked()
