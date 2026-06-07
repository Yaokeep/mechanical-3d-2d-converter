# 机械三维二维图互转 — 尺寸计算器

import math
from typing import Optional


class DimensionCalculator:
    """尺寸计算器

    提供几何测量功能：
    - 两点间距
    - 点到线距离
    - 圆弧半径
    - 角度

    所有输入和输出均以毫米 (mm) 为单位。
    """

    @staticmethod
    def distance_2d(p1: tuple[float, float], p2: tuple[float, float]) -> float:
        """计算两点之间的 2D 距离"""
        return math.sqrt((p2[0] - p1[0]) ** 2 + (p2[1] - p1[1]) ** 2)

    @staticmethod
    def distance_3d(p1: tuple[float, float, float], p2: tuple[float, float, float]) -> float:
        """计算两点之间的 3D 距离"""
        return math.sqrt(
            (p2[0] - p1[0]) ** 2 +
            (p2[1] - p1[1]) ** 2 +
            (p2[2] - p1[2]) ** 2
        )

    @staticmethod
    def point_to_line_distance(
        point: tuple[float, float],
        line_p1: tuple[float, float],
        line_p2: tuple[float, float],
    ) -> float:
        """计算点到直线的垂直距离"""
        x0, y0 = point
        x1, y1 = line_p1
        x2, y2 = line_p2
        numerator = abs((y2 - y1) * x0 - (x2 - x1) * y0 + x2 * y1 - y2 * x1)
        denominator = math.sqrt((y2 - y1) ** 2 + (x2 - x1) ** 2)
        if denominator == 0:
            return 0.0
        return numerator / denominator

    @staticmethod
    def angle_between_vectors(
        v1: tuple[float, float, float],
        v2: tuple[float, float, float],
    ) -> float:
        """计算两个 3D 向量之间的夹角（度）"""
        dot = v1[0] * v2[0] + v1[1] * v2[1] + v1[2] * v2[2]
        mag1 = math.sqrt(v1[0] ** 2 + v1[1] ** 2 + v1[2] ** 2)
        mag2 = math.sqrt(v2[0] ** 2 + v2[1] ** 2 + v2[2] ** 2)
        if mag1 == 0 or mag2 == 0:
            return 0.0
        cos_theta = max(-1.0, min(1.0, dot / (mag1 * mag2)))
        return math.degrees(math.acos(cos_theta))

    @staticmethod
    def circle_radius_from_three_points(
        p1: tuple[float, float],
        p2: tuple[float, float],
        p3: tuple[float, float],
    ) -> Optional[float]:
        """通过三点计算圆弧半径"""
        x1, y1 = p1
        x2, y2 = p2
        x3, y3 = p3

        d = 2 * (x1 * (y2 - y3) + x2 * (y3 - y1) + x3 * (y1 - y2))
        if abs(d) < 1e-10:
            return None  # 三点共线

        ux = ((x1 ** 2 + y1 ** 2) * (y2 - y3) +
              (x2 ** 2 + y2 ** 2) * (y3 - y1) +
              (x3 ** 2 + y3 ** 2) * (y1 - y2)) / d
        uy = ((x1 ** 2 + y1 ** 2) * (x3 - x2) +
              (x2 ** 2 + y2 ** 2) * (x1 - x3) +
              (x3 ** 2 + y3 ** 2) * (x2 - x1)) / d

        radius = math.sqrt((x1 - ux) ** 2 + (y1 - uy) ** 2)
        return radius
