# 机械三维二维图互转 — 投影数据结构

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, Optional


# ------------------------- 枚举 -------------------------

class ProjectionType(Enum):
    """投影类型"""
    FRONT = auto()              # 正视图
    TOP = auto()                # 俯视图
    RIGHT = auto()              # 右侧视图
    LEFT = auto()               # 左侧视图
    BOTTOM = auto()             # 仰视图
    BACK = auto()               # 后视图
    ISOMETRIC = auto()          # 等轴测图
    SECTION = auto()            # 剖面图
    DETAIL = auto()             # 局部放大图


class CurveType(Enum):
    """曲线类型"""
    LINE = auto()               # 直线段
    ARC = auto()                # 圆弧
    CIRCLE = auto()             # 整圆
    ELLIPSE = auto()            # 椭圆
    SPLINE = auto()             # B样条曲线
    BEZIER = auto()             # 贝塞尔曲线


class DimensionType(Enum):
    """标注类型"""
    LINEAR = auto()             # 线性标注
    ANGULAR = auto()            # 角度标注
    RADIUS = auto()             # 半径标注
    DIAMETER = auto()           # 直径标注
    ORDINATE = auto()           # 坐标标注


# ------------------------- 数据结构 -------------------------

@dataclass
class Edge2D:
    """2D 边数据——投影结果中的一条边

    包含可见边和隐藏边，由 HLR 投影引擎生成。
    """

    start: tuple[float, float]      # 起点 (x, y)
    end: tuple[float, float]        # 终点 (x, y)
    curve_type: CurveType = CurveType.LINE
    curve_data: Any = None          # 曲线参数（圆弧的圆心半径等）
    is_hidden: bool = False         # 是否为隐藏边
    is_center: bool = False         # 是否为中心线
    extra: dict = field(default_factory=dict)  # 扩展字段


@dataclass
class Dimension2D:
    """2D 尺寸标注数据"""

    dim_type: DimensionType
    points: list[tuple[float, float]]   # 标注点序列
    value: float                        # 测量数值 (mm)
    tolerance_upper: float = 0.0        # 上公差
    tolerance_lower: float = 0.0        # 下公差
    text_override: Optional[str] = None # 自定义文本覆盖


@dataclass
class ProjectionData:
    """投影结果数据——一次投影操作的完整输出

    由投影引擎生成，传递给 2D 视图进行渲染。
    """

    source_shape_name: str                      # 源形状名称
    view_type: ProjectionType                   # 视图类型
    view_label: str = ""                        # 视图标签（如 "正视图"）

    # 投影方向（3D 世界坐标）
    view_direction: tuple[float, float, float] = (0, 0, 0)

    # 边数据
    visible_edges: list[Edge2D] = field(default_factory=list)
    hidden_edges: list[Edge2D] = field(default_factory=list)
    center_lines: list[Edge2D] = field(default_factory=list)

    # 标注数据
    dimensions: list[Dimension2D] = field(default_factory=list)

    # 变换和比例
    scale: float = 1.0
    offset_2d: tuple[float, float] = (0, 0)     # 在图纸上的偏移

    # 剖面图专用
    section_plane: Optional[Any] = None          # 剖面定义
    hatch_pattern: Optional[Any] = None          # 剖面填充图案

    @property
    def total_edges(self) -> int:
        """总边数"""
        return len(self.visible_edges) + len(self.hidden_edges) + len(self.center_lines)

    @property
    def is_empty(self) -> bool:
        """投影结果是否为空"""
        return self.total_edges == 0
