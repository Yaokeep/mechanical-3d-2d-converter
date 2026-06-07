# 机械三维二维图互转 — 属性面板 Dock

from PyQt6.QtWidgets import (
    QDockWidget, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget, QHeaderView, QLabel,
)
from PyQt6.QtCore import Qt


class PropertyPanelDock(QDockWidget):
    """属性查看/编辑面板

    当选中的形状变化时，显示其属性信息：
    - 名称、类型
    - 包围盒尺寸（长×宽×高）
    - 体积、表面积
    - 面数、边数、顶点数
    - 材质、颜色
    """

    # 属性字段定义
    PROPERTIES = [
        ("名称", "name"),
        ("类型", "shape_type"),
        ("长度 (mm)", "length"),
        ("宽度 (mm)", "width"),
        ("高度 (mm)", "height"),
        ("体积 (mm³)", "volume"),
        ("表面积 (mm²)", "area"),
        ("面数", "face_count"),
        ("边数", "edge_count"),
    ]

    def __init__(self, title: str, parent=None):
        super().__init__(title, parent)
        self.setObjectName("PropertyPanelDock")
        self.setFeatures(
            QDockWidget.DockWidgetFeature.DockWidgetMovable |
            QDockWidget.DockWidgetFeature.DockWidgetClosable
        )
        self.setMinimumWidth(220)

        self._setup_ui()

    def _setup_ui(self) -> None:
        """构建属性表格"""
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(2, 2, 2, 2)

        # 属性表格
        self._table = QTableWidget(len(self.PROPERTIES), 2)
        self._table.setHorizontalHeaderLabels(["属性", "值"])
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.verticalHeader().setVisible(False)
        self._table.setEditTriggers(
            QTableWidget.EditTrigger.NoEditTriggers
        )
        self._table.setAlternatingRowColors(True)

        # 填充属性名称列
        for row, (label, _) in enumerate(self.PROPERTIES):
            name_item = QTableWidgetItem(label)
            name_item.setFlags(name_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self._table.setItem(row, 0, name_item)
            self._table.setItem(row, 1, QTableWidgetItem("—"))

        layout.addWidget(self._table)

        # 提示标签
        self._hint_label = QLabel("选择模型元素以查看属性")
        self._hint_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._hint_label.setStyleSheet("color: #888; font-size: 11px;")
        layout.addWidget(self._hint_label)

        self.setWidget(container)

    # ------------------------- 公共接口 -------------------------

    def show_shape_properties(self, properties: dict) -> None:
        """显示形状属性

        Args:
            properties: 属性名 → 值的字典
        """
        for row, (_, key) in enumerate(self.PROPERTIES):
            value = properties.get(key, "—")
            self._table.item(row, 1).setText(str(value))

    def clear(self) -> None:
        """清空属性显示"""
        for row in range(len(self.PROPERTIES)):
            self._table.item(row, 1).setText("—")

    def get_table(self) -> QTableWidget:
        """获取底层 QTableWidget"""
        return self._table
