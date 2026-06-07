# 机械三维二维图互转 — 2D 工程图场景管理

from PyQt6.QtWidgets import QGraphicsScene, QGraphicsRectItem, QGraphicsTextItem
from PyQt6.QtCore import Qt, QRectF
from PyQt6.QtGui import QPen, QFont, QColor, QPainter


class View2DScene(QGraphicsScene):
    """2D 工程图场景

    管理 QGraphicsScene 坐标系，负责：
    - 各工程视图的框架绘制（标题、边框）
    - 网格背景
    - 投影图和标注图元的管理
    """

    # 默认颜色方案
    COLOR_BACKGROUND = QColor(255, 255, 255)
    COLOR_GRID_MAJOR = QColor(220, 220, 220)
    COLOR_GRID_MINOR = QColor(240, 240, 240)
    COLOR_VIEW_BORDER = QColor(100, 100, 100)
    COLOR_TITLE_TEXT = QColor(50, 50, 50)

    # 网格间距
    GRID_SPACING = 10  # mm（场景坐标）

    def __init__(self, parent=None):
        super().__init__(parent)
        self._view_frames: dict[str, QRectF] = {}
        self._grid_visible = True

    def add_view_frame(self, view_name: str, rect: QRectF) -> QGraphicsRectItem:
        """添加一个视图框架（带名称标题和边框）

        Args:
            view_name: 视图名称（如 "正视图", "俯视图" 等）
            rect: 视图在场景中的矩形区域

        Returns:
            创建的矩形图元
        """
        # 边框
        pen = QPen(self.COLOR_VIEW_BORDER, 1.0)
        frame = self.addRect(rect, pen)

        # 标题文字（放在视图框架上方）
        title = QGraphicsTextItem(view_name)
        title.setDefaultTextColor(self.COLOR_TITLE_TEXT)
        title_font = QFont("Microsoft YaHei", 10)
        title_font.setBold(True)
        title.setFont(title_font)
        title.setPos(rect.left() + 5, rect.top() + 3)
        self.addItem(title)

        self._view_frames[view_name] = rect
        return frame

    def add_projection_edges(self, edges: list, parent_item=None) -> list:
        """添加投影边图元列表

        Args:
            edges: Edge2D 列表
            parent_item: 父图元组（用于批量管理）

        Returns:
            创建的 QGraphicsItem 列表
        """
        # TODO: 根据 Edge2D 数据创建 QGraphicsPathItem
        return []

    def add_dimension_line(self, p1, p2, value: str) -> object:
        """添加尺寸标注线

        Args:
            p1: 起点 (QPointF)
            p2: 终点 (QPointF)
            value: 标注数值字符串

        Returns:
            DimensionItem 实例
        """
        # TODO: 创建 DimensionItem
        return None

    def add_center_line(self, p1, p2) -> None:
        """添加中心线（点划线样式）"""
        # TODO: 创建中心线 QGraphicsLineItem
        pass

    def drawBackground(self, painter: QPainter, rect: QRectF) -> None:
        """绘制背景网格"""
        super().drawBackground(painter, rect)

        if not self._grid_visible:
            return

        # 绘制细网格
        painter.setPen(QPen(self.COLOR_GRID_MINOR, 0.3))
        left = int(rect.left()) - (int(rect.left()) % self.GRID_SPACING)
        top = int(rect.top()) - (int(rect.top()) % self.GRID_SPACING)

        lines = []
        for x in range(int(left), int(rect.right()), self.GRID_SPACING):
            lines.append((x, rect.top(), x, rect.bottom()))
        for y in range(int(top), int(rect.bottom()), self.GRID_SPACING):
            lines.append((rect.left(), y, rect.right(), y))

        for x1, y1, x2, y2 in lines:
            painter.drawLine(int(x1), int(y1), int(x2), int(y2))

    def set_grid_visible(self, visible: bool) -> None:
        """设置网格是否可见"""
        self._grid_visible = visible
        self.update()

    def get_view_frame(self, name: str) -> QRectF | None:
        """根据名称获取视图框架矩形"""
        return self._view_frames.get(name)
