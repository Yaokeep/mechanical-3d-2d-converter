# 机械三维二维图互转 — 项目结构树 Dock 面板

from PyQt6.QtWidgets import (
    QDockWidget, QTreeView, QVBoxLayout, QWidget,
    QHeaderView, QMenu,
)
from PyQt6.QtCore import Qt, pyqtSignal, QModelIndex
from PyQt6.QtGui import QStandardItemModel, QStandardItem, QAction


class ProjectTreeDock(QDockWidget):
    """项目结构树面板

    以树形结构显示导入的模型层级：
    - 根节点：项目名称
    - 子节点：各导入形状（可展开为面/边子级）
    - 支持右键菜单（重命名、删除、导出、可见性切换）
    """

    # 信号
    item_selected = pyqtSignal(str)          # 选中项的名称路径
    visibility_changed = pyqtSignal(str, bool)  # 名称, 是否可见

    def __init__(self, title: str, parent=None):
        super().__init__(title, parent)
        self.setObjectName("ProjectTreeDock")
        self.setFeatures(
            QDockWidget.DockWidgetFeature.DockWidgetMovable |
            QDockWidget.DockWidgetFeature.DockWidgetClosable
        )
        self.setMinimumWidth(200)

        self._setup_ui()

    def _setup_ui(self) -> None:
        """构建树形视图"""
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(2, 2, 2, 2)

        # 树模型
        self._model = QStandardItemModel()
        self._model.setHorizontalHeaderLabels(["名称"])

        # 树视图
        self._tree_view = QTreeView()
        self._tree_view.setModel(self._model)
        self._tree_view.setHeaderHidden(False)
        self._tree_view.header().setStretchLastSection(True)
        self._tree_view.setEditTriggers(
            QTreeView.EditTrigger.NoEditTriggers
        )
        self._tree_view.setContextMenuPolicy(
            Qt.ContextMenuPolicy.CustomContextMenu
        )
        self._tree_view.setSelectionMode(
            QTreeView.SelectionMode.SingleSelection
        )

        # 根节点
        self._root_item = QStandardItem("项目")
        self._root_item.setSelectable(False)
        self._model.appendRow(self._root_item)

        # 连接信号
        self._tree_view.clicked.connect(self._on_item_clicked)
        self._tree_view.customContextMenuRequested.connect(
            self._on_context_menu
        )

        layout.addWidget(self._tree_view)
        self.setWidget(container)

    # ------------------------- 公共接口 -------------------------

    def add_shape(self, name: str, shape_type: str = "Solid") -> None:
        """添加形状节点到项目树

        Args:
            name: 形状名称
            shape_type: 类型标签（Solid / Face / Edge / Compound）
        """
        item = QStandardItem(f"{name} [{shape_type}]")
        item.setData(name, Qt.ItemDataRole.UserRole)
        item.setCheckable(True)
        item.setCheckState(Qt.CheckState.Checked)
        self._root_item.appendRow(item)
        self._tree_view.expand(self._model.indexFromItem(self._root_item))

    def remove_shape(self, name: str) -> None:
        """从项目树中移除形状节点"""
        for row in range(self._root_item.rowCount()):
            child = self._root_item.child(row)
            if child and child.data(Qt.ItemDataRole.UserRole) == name:
                self._root_item.removeRow(row)
                break

    def clear_all(self) -> None:
        """清除所有形状节点"""
        self._root_item.removeRows(0, self._root_item.rowCount())

    def get_tree_view(self) -> QTreeView:
        """获取底层 QTreeView"""
        return self._tree_view

    # ------------------------- 槽函数 -------------------------

    def _on_item_clicked(self, index: QModelIndex) -> None:
        """树节点点击处理"""
        item = self._model.itemFromIndex(index)
        if item and item is not self._root_item:
            name = item.data(Qt.ItemDataRole.UserRole)
            if name:
                self.item_selected.emit(name)

    def _on_context_menu(self, pos) -> None:
        """右键上下文菜单"""
        index = self._tree_view.indexAt(pos)
        if not index.isValid():
            return

        item = self._model.itemFromIndex(index)
        if item is None or item is self._root_item:
            return

        menu = QMenu(self)

        # 可见性切换
        act_toggle = QAction("显示/隐藏", self)
        act_toggle.triggered.connect(
            lambda: self._toggle_visibility(item)
        )
        menu.addAction(act_toggle)

        menu.addSeparator()

        # 删除
        act_delete = QAction("删除", self)
        act_delete.triggered.connect(
            lambda: self._delete_item(item)
        )
        menu.addAction(act_delete)

        menu.exec(self._tree_view.viewport().mapToGlobal(pos))

    def _toggle_visibility(self, item: QStandardItem) -> None:
        """切换可见性"""
        current = item.checkState()
        new_state = (
            Qt.CheckState.Unchecked
            if current == Qt.CheckState.Checked
            else Qt.CheckState.Checked
        )
        item.setCheckState(new_state)
        name = item.data(Qt.ItemDataRole.UserRole)
        self.visibility_changed.emit(name, new_state == Qt.CheckState.Checked)

    def _delete_item(self, item: QStandardItem) -> None:
        """删除节点"""
        name = item.data(Qt.ItemDataRole.UserRole)
        parent = item.parent() or self._root_item
        parent.removeRow(item.row())
