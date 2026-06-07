# 机械三维二维图互转 — 旋转实体构建器

from typing import Any, Optional
import math


class RevolveBuilder:
    """旋转（Revolve）实体构建器

    将 2D 截面（闭合线框）绕指定轴旋转生成 3D 实体。
    主要流程：
    1. WireMaker → 闭合线框
    2. FaceBuilder → 平面面
    3. BRepPrimAPI_MakeRevolve → 旋转实体

    典型应用：轴类零件、法兰盘、旋转对称体。
    """

    def __init__(self):
        pass

    def build(
        self,
        wire,
        axis_origin: tuple[float, float, float],
        axis_direction: tuple[float, float, float],
        angle: float = 360.0,
    ) -> Any:
        """旋转构建实体

        Args:
            wire: 截面轮廓 TopoDS_Wire
            axis_origin: 旋转轴上一点 (x, y, z)
            axis_direction: 旋转轴方向 (dx, dy, dz)
            angle: 旋转角度（度），默认 360° 全周旋转

        Returns:
            TopoDS_Solid
        """
        # TODO: 集成 PythonOCC
        # from OCC.Core.BRepPrimAPI import BRepPrimAPI_MakeRevolve
        # from OCC.Core.GP import gp_Pnt, gp_Dir, gp_Ax1
        #
        # face = FaceBuilder().build_face(wire)
        # axis = gp_Ax1(gp_Pnt(*axis_origin), gp_Dir(*axis_direction))
        #
        # angle_rad = math.radians(angle)
        # revolve = BRepPrimAPI_MakeRevolve(face, axis, angle_rad)
        # revolve.Build()
        #
        # if not revolve.IsDone():
        #     raise RuntimeError("旋转建模失败，请检查截面和轴线")
        #
        # return revolve.Shape()
        return None

    def build_full_revolve(
        self,
        wire,
        axis_origin: tuple[float, float, float],
        axis_direction: tuple[float, float, float],
    ) -> Any:
        """全周旋转（360°）快捷方法"""
        return self.build(wire, axis_origin, axis_direction, 360.0)

    def build_partial_revolve(
        self,
        wire,
        axis_origin: tuple[float, float, float],
        axis_direction: tuple[float, float, float],
        angle: float,
    ) -> Any:
        """部分角度旋转"""
        if angle <= 0 or angle > 360:
            raise ValueError("旋转角度必须在 (0, 360] 度范围内")
        return self.build(wire, axis_origin, axis_direction, angle)
