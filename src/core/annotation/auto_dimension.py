# 机械三维二维图互转 — 自动尺寸标注引擎

from src.core.model.projection_data import Dimension2D, DimensionType


class AutoDimension:
    """自动尺寸标注引擎

    分析投影结果中的 2D 边，自动生成线性尺寸标注。
    算法：贪心放置原则，检测极值点并生成水平/垂直标注线，
    避免标注线重叠。
    """

    def __init__(self, offset: float = 15.0):
        """
        Args:
            offset: 标注线距图形的偏移距离 (mm)
        """
        self._offset = offset

    def generate(self, edges: list, view_frame) -> list[Dimension2D]:
        """根据边列表生成自动标注

        Args:
            edges: Edge2D 列表
            view_frame: 视图框架矩形（用于确定标注位置范围）

        Returns:
            Dimension2D 列表
        """
        dimensions = []

        # TODO: 实现自动标注算法
        # 1. 找到所有边的极值点（最左、最右、最上、最下）
        # 2. 生成宽度和高度标注
        # 3. 检测圆形特征生成直径/半径标注
        # 4. 贪心放置避免重叠

        return dimensions

    def generate_linear_dimensions(self, edges: list) -> list[Dimension2D]:
        """仅生成线性标注"""
        return []

    def generate_radial_dimensions(self, edges: list) -> list[Dimension2D]:
        """仅生成半径/直径标注"""
        return []
