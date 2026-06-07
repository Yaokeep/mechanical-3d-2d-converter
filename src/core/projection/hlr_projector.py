# 机械三维二维图互转 — HLR 隐藏线消除投影引擎

from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class ProjectionResult:
    """HLR 投影原始结果"""
    visible_sharp: Any = None       # 可见锐边 (TopoDS_Compound)
    hidden_sharp: Any = None        # 隐藏锐边 (TopoDS_Compound)
    visible_outline: Any = None     # 可见轮廓 (TopoDS_Compound)
    hidden_outline: Any = None      # 隐藏轮廓 (TopoDS_Compound)
    visible_smooth: Any = None      # 可见光滑边 (TopoDS_Compound)


class HLRProjector:
    """HLR（Hidden Line Removal）隐藏线消除投影引擎

    核心 3D→2D 转换算法。使用 OpenCASCADE 的 HLRBRep_Algo：
    1. 加载 TopoDS_Shape
    2. 设置观察方向（投影方向）
    3. 运行隐藏线消除算法
    4. 提取可见边和隐藏边分别输出

    参考文献：OpenCASCADE HLR Algorithm User Guide
    """

    def __init__(self):
        self._shape: Any = None
        self._projection_direction: tuple[float, float, float] = (0, 0, 1)

    def set_shape(self, shape) -> None:
        """设置要投影的 3D 形状

        Args:
            shape: TopoDS_Shape 实例
        """
        self._shape = shape

    def set_direction(self, direction: tuple[float, float, float]) -> None:
        """设置投影方向（即观察方向）

        Args:
            direction: 3D 方向向量，例如 (0, 0, 1) 表示从 Z 轴正向观察
        """
        self._projection_direction = direction

    def compute(self) -> ProjectionResult:
        """执行 HLR 计算

        Returns:
            ProjectionResult 包含所有可见/隐藏边的分类结果

        Raises:
            RuntimeError: 形状未设置或 HLR 计算失败
        """
        if self._shape is None:
            raise RuntimeError("HLR 投影前需要先调用 set_shape() 设置形状")

        result = ProjectionResult()

        # TODO: 集成 PythonOCC HLR 引擎
        # from OCC.Core.HLRBRep import HLRBRep_Algo, HLRBRep_HLRToShape
        # from OCC.Core.GP import gp_Dir, gp_Ax2, gp_Pnt
        #
        # hlr = HLRBRep_Algo()
        # hlr.Add(self._shape)
        #
        # projector = hlr.Projector()
        # dir_vec = gp_Dir(*self._projection_direction)
        # origin = gp_Pnt(0, 0, 0)
        # projector.SetDirection(dir_vec)
        #
        # hlr.Update()
        # hlr.Hide()
        #
        # shapes = HLRBRep_HLRToShape(hlr)
        # result.visible_sharp = shapes.VCompound()
        # result.hidden_sharp = shapes.HCompound()
        # result.visible_outline = shapes.OutLineVCompound()
        # result.hidden_outline = shapes.OutLineHCompound()

        return result

    def extract_edges(self, result: ProjectionResult) -> list:
        """从 ProjectionResult 提取 Edge2D 列表

        将 OpenCASCADE 的边数据转换为应用程序内部的 Edge2D 结构。
        """
        edges = []
        # TODO: 遍历 result 中的边，转换为 Edge2D
        return edges
