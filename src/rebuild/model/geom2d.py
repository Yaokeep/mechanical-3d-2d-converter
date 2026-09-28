# -*- coding: utf-8 -*-
"""2D 几何基元（图纸坐标系）。

与 geom.py 同理：纯数据、不依赖 ezdxf/OCC，便于独立测试与序列化。
"""
from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class Point2:
    x: float
    y: float

    def distance_to(self, o: "Point2") -> float:
        return math.hypot(self.x - o.x, self.y - o.y)


@dataclass(frozen=True)
class Line2:
    start: Point2
    end: Point2

    @property
    def length(self) -> float:
        return self.start.distance_to(self.end)

    @property
    def midpoint(self) -> Point2:
        return Point2((self.start.x + self.end.x) / 2, (self.start.y + self.end.y) / 2)

    @property
    def direction(self) -> tuple[float, float]:
        """单位方向向量；零长线段返回 (0, 0)。"""
        n = self.length
        if n == 0.0:
            return (0.0, 0.0)
        return ((self.end.x - self.start.x) / n, (self.end.y - self.start.y) / n)

    def distance_to_point(self, p: Point2) -> float:
        """点到**线段**的距离（非到直线）。"""
        dx, dy = self.end.x - self.start.x, self.end.y - self.start.y
        seg2 = dx * dx + dy * dy
        if seg2 == 0.0:
            return self.start.distance_to(p)
        t = max(0.0, min(1.0, ((p.x - self.start.x) * dx + (p.y - self.start.y) * dy) / seg2))
        proj = Point2(self.start.x + t * dx, self.start.y + t * dy)
        return proj.distance_to(p)


@dataclass(frozen=True)
class Circle2:
    center: Point2
    radius: float


@dataclass(frozen=True)
class Arc2:
    center: Point2
    radius: float
    start_angle: float   # 弧度
    end_angle: float

    @property
    def is_full_circle(self) -> bool:
        return abs(abs(self.end_angle - self.start_angle) - 2 * math.pi) < 1e-9


@dataclass(frozen=True)
class BBox2:
    xmin: float
    ymin: float
    xmax: float
    ymax: float

    @property
    def width(self) -> float:
        return self.xmax - self.xmin

    @property
    def height(self) -> float:
        return self.ymax - self.ymin

    @property
    def center(self) -> Point2:
        return Point2((self.xmin + self.xmax) / 2, (self.ymin + self.ymax) / 2)

    @classmethod
    def of_points(cls, pts: list[Point2]) -> "BBox2":
        if not pts:
            raise ValueError("空点集无法求包围盒")
        xs = [p.x for p in pts]
        ys = [p.y for p in pts]
        return cls(min(xs), min(ys), max(xs), max(ys))

    def union(self, o: "BBox2") -> "BBox2":
        return BBox2(
            min(self.xmin, o.xmin), min(self.ymin, o.ymin),
            max(self.xmax, o.xmax), max(self.ymax, o.ymax),
        )

    def expanded(self, m: float) -> "BBox2":
        return BBox2(self.xmin - m, self.ymin - m, self.xmax + m, self.ymax + m)

    def overlaps(self, o: "BBox2", margin: float = 0.0) -> bool:
        return not (
            self.xmax + margin < o.xmin or o.xmax + margin < self.xmin
            or self.ymax + margin < o.ymin or o.ymax + margin < self.ymin
        )
