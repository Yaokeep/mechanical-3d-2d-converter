# 机械三维二维图互转 — 2D 工程图图元项

from PyQt6.QtWidgets import QGraphicsItem, QGraphicsPathItem, QGraphicsLineItem
from PyQt6.QtCore import Qt, QPointF, QRectF
from PyQt6.QtGui import (
    QPen, QPainterPath, QPainter, QColor, QFont, QPolygonF,
)
from enum import Enum, auto


# ------------------------- 线条样式枚举 -------------------------

class LineStyle(Enum):
    """工程图线条样式"""
    CONTINUOUS = auto()         # 实线（可见轮廓）
    DASHED = auto()             # 虚线（隐藏轮廓）
    DASH_DOT = auto()           # 点划线（中心线）
    DASH_DOT_DOT = auto()       # 双点划线
    PHANTOM = auto()            # 假想线


class DimensionType(Enum):
    """标注类型"""
    LINEAR = auto()             # 线性标注
    ANGULAR = auto()            # 角度标注
    RADIUS = auto()             # 半径标注
    DIAMETER = auto()           # 直径标注
    ORDINATE = auto()           # 坐标标注


# ------------------------- 边图元 -------------------------

class EdgeItem(QGraphicsPathItem):
    """工程图边线图元

    表示投影结果中的一条边，支持实线（可见边）和虚线（隐藏边）。
    """

    # 默认画笔
    PEN_VISIBLE = QPen(QColor(0, 0, 0), 1.2)
    PEN_HIDDEN = QPen(QColor(100, 100, 100), 0.8, Qt.PenStyle.DashLine)
    PEN_CENTER = QPen(QColor(180, 0, 180), 0.6, Qt.PenStyle.DashDotLine)

    def __init__(self, start: QPointF, end: QPointF, style: LineStyle = LineStyle.CONTINUOUS, parent=None):
        """
        Args:
            start: 起点
            end: 终点
            style: 线条样式
            parent: 父图元
        """
        super().__init__(parent)
        self._start = start
        self._end = end
        self._style = style

        # 构建路径
        path = QPainterPath()
        path.moveTo(start)
        path.lineTo(end)
        self.setPath(path)

        # 设置画笔
        self._apply_pen()

    def _apply_pen(self) -> None:
        """根据样式设置画笔"""
        pen_map = {
            LineStyle.CONTINUOUS: self.PEN_VISIBLE,
            LineStyle.DASHED: self.PEN_HIDDEN,
            LineStyle.DASH_DOT: self.PEN_CENTER,
            LineStyle.DASH_DOT_DOT: QPen(QColor(50, 50, 200), 0.6, Qt.PenStyle.DashDotDotLine),
        }
        self.setPen(pen_map.get(self._style, self.PEN_VISIBLE))

    def set_style(self, style: LineStyle) -> None:
        """修改线条样式"""
        self._style = style
        self._apply_pen()

    def boundingRect(self) -> QRectF:
        """返回边界矩形"""
        extra = 2.0
        return QRectF(self._start, self._end).normalized().adjusted(
            -extra, -extra, extra, extra
        )


# ------------------------- 标注图元 -------------------------

class DimensionItem(QGraphicsItem):
    """工程图尺寸标注图元

    绘制尺寸标注线：两条引出线 + 一条标注线 + 箭头 + 数值文本
    """

    ARROW_SIZE = 6.0       # 箭头大小
    EXTENSION_OFFSET = 8.0  # 引出线偏移

    def __init__(self, p1: QPointF, p2: QPointF, dim_type: DimensionType, value: str, parent=None):
        """
        Args:
            p1: 第一测量点
            p2: 第二测量点
            dim_type: 标注类型
            value: 标注数值文本
            parent: 父图元
        """
        super().__init__(parent)
        self._p1 = p1
        self._p2 = p2
        self._dim_type = dim_type
        self._value = value

        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)

    def boundingRect(self) -> QRectF:
        """返回边界矩形"""
        return QRectF(self._p1, self._p2).normalized().adjusted(-20, -20, 20, 20)

    def paint(self, painter: QPainter, option, widget=None) -> None:
        """绘制标注"""
        # 简化实现：绘制测量点和标注线
        pen = QPen(QColor(0, 0, 200), 0.6)
        painter.setPen(pen)

        # 引出线
        offset = QPointF(0, -self.EXTENSION_OFFSET)
        p1_ext = self._p1 + offset
        p2_ext = self._p2 + offset

        painter.drawLine(self._p1, p1_ext)
        painter.drawLine(self._p2, p2_ext)
        painter.drawLine(p1_ext, p2_ext)

        # 箭头（简化为小线段）
        # TODO: 绘制实心箭头三角形

        # 文本
        font = QFont("Microsoft YaHei", 8)
        painter.setFont(font)
        painter.setPen(QColor(0, 0, 0))
        text_rect = QRectF(
            (p1_ext.x() + p2_ext.x()) / 2 - 30,
            p1_ext.y() - 16,
            60, 14,
        )
        painter.drawText(text_rect, Qt.AlignmentFlag.AlignCenter, self._value)


# ------------------------- 剖面填充图元 -------------------------

class SectionHatchItem(QGraphicsPathItem):
    """剖面填充（截面线）图元

    表示剖面视图中被切割区域的填充图案。
    """

    HATCH_SPACING = 3.0       # 剖面线间距 (mm)
    HATCH_ANGLE = 45.0        # 剖面线角度（度）

    def __init__(self, boundary_path: QPainterPath, parent=None):
        super().__init__(parent)
        self._boundary = boundary_path
        self._generate_hatch()

    def _generate_hatch(self) -> None:
        """生成剖面线路径"""
        # TODO: 在 boundary_path 内生成 45° 平行线
        self.setPath(self._boundary)
        self.setPen(QPen(QColor(0, 0, 0), 0.4))
        self.setBrush(Qt.BrushStyle.NoBrush)
