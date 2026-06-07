# 机械三维二维图互转 — 轴测图投影引擎

import math
from src.core.projection.hlr_projector import HLRProjector, ProjectionResult
from src.core.model.projection_data import ProjectionData, ProjectionType


class AxonometricProjector:
    """轴测图投影引擎

    产生等轴测（Isometric）和自定义轴测投影。
    默认等轴测方向为 (1, 1, 1) 归一化后的向量。
    """

    # 标准轴测方向
    ISOMETRIC = (1.0, 1.0, 1.0)              # 等轴测（三个轴各缩约 0.816）
    DIMETRIC = (1.0, 1.0, 0.5)               # 二等轴测
    TRIMETRIC = (1.0, 0.6, 0.3)              # 三轴测

    def __init__(self):
        self._hlr = HLRProjector()

    def project_isometric(self, shape) -> ProjectionData:
        """等轴测投影

        Args:
            shape: TopoDS_Shape

        Returns:
            ProjectionData
        """
        return self._project(shape, self.ISOMETRIC, "等轴测图")

    def project_custom(self, shape, direction: tuple[float, float, float], label: str = "轴测图") -> ProjectionData:
        """自定义方向的轴测投影"""
        return self._project(shape, direction, label)

    def _project(self, shape, direction: tuple[float, float, float], label: str) -> ProjectionData:
        """内部投影方法"""
        self._hlr.set_shape(shape)
        self._hlr.set_direction(direction)

        raw_result = self._hlr.compute()

        data = ProjectionData(
            source_shape_name="unknown",
            view_type=ProjectionType.ISOMETRIC,
            view_label=label,
            view_direction=direction,
        )

        # TODO: 从 raw_result 提取 Edge2D
        return data

    @staticmethod
    def normalize_direction(dx: float, dy: float, dz: float) -> tuple[float, float, float]:
        """归一化方向向量"""
        length = math.sqrt(dx * dx + dy * dy + dz * dz)
        if length == 0:
            return (0, 0, 1)
        return (dx / length, dy / length, dz / length)
