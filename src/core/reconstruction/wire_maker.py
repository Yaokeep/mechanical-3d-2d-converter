# 机械三维二维图互转 — 2D 边→3D 线框组装器

from typing import Any


class WireMaker:
    """线框组装器

    将 DXF 导入的 2D 边（TopoDS_Edge 列表）组装为有效的 TopoDS_Wire。
    处理功能：
    - 边排序（按首尾连接顺序）
    - 闭口检测（判断是否形成闭合轮廓）
    - 间隙容忍（Tolerance 内的小间隙自动闭合）
    """

    # 默认连接公差 (mm)
    DEFAULT_TOLERANCE = 1e-3

    def __init__(self, tolerance: float = DEFAULT_TOLERANCE):
        self._tolerance = tolerance

    def build_wire(self, edges: list, close: bool = True) -> Any:
        """从边列表构建线框

        Args:
            edges: TopoDS_Edge 列表
            close: True 表示构建闭合线框

        Returns:
            TopoDS_Wire 实例

        Raises:
            ValueError: 边列表为空或无法连接
        """
        if not edges:
            raise ValueError("边列表为空，无法构建线框")

        # TODO: 集成 PythonOCC
        # from OCC.Core.BRepBuilderAPI import BRepBuilderAPI_MakeWire
        # from OCC.Core.ShapeAnalysis import ShapeAnalysis_Wire
        # from OCC.Core.BRep import BRep_Tool
        #
        # wire_builder = BRepBuilderAPI_MakeWire()
        #
        # ordered_edges = self.order_edges(edges)
        # for edge in ordered_edges:
        #     wire_builder.Add(edge)
        #
        # if close and not self.is_closed(wire):
        #     raise ValueError("边无法形成闭合轮廓，存在间隙大于容差的开口")

        return None  # wire_builder.Wire()

    def order_edges(self, edges: list) -> list:
        """按首尾连接顺序排序边列表

        贪心算法：从第一条边开始，每次找到与当前端点最近的边。

        Args:
            edges: 无序边列表

        Returns:
            排序后的边列表
        """
        # TODO: 实现边的连通排序
        return list(edges)

    def is_closed(self, wire) -> bool:
        """检查线框是否闭合"""
        # TODO: 使用 BRep_Tool 检查首尾点距离 < tolerance
        return True

    def analyze_gaps(self, edges: list) -> list[tuple[int, int, float]]:
        """分析边之间的间隙

        Returns:
            (边索引1, 边索引2, 间隙距离) 三元组列表
        """
        gaps = []
        # TODO: 计算相邻边端点间距
        return gaps
