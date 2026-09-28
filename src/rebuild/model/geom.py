# -*- coding: utf-8 -*-
"""3D 几何基元（docs/ARCHITECTURE.md §4.4）。

刻意做成**纯数据**（frozen dataclass，不依赖 OCC）：
符号推理层跑在默认 python 上，几何构造才需要 cad-occt 环境
（ARCHITECTURE §5 解释器依赖分层）。
"""
from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class Vector3:
    x: float = 0.0
    y: float = 0.0
    z: float = 0.0

    def __add__(self, o: "Vector3") -> "Vector3":
        return Vector3(self.x + o.x, self.y + o.y, self.z + o.z)

    def __sub__(self, o: "Vector3") -> "Vector3":
        return Vector3(self.x - o.x, self.y - o.y, self.z - o.z)

    def __mul__(self, k: float) -> "Vector3":
        return Vector3(self.x * k, self.y * k, self.z * k)

    __rmul__ = __mul__

    @property
    def norm(self) -> float:
        return math.sqrt(self.x ** 2 + self.y ** 2 + self.z ** 2)

    def normalized(self) -> "Vector3":
        n = self.norm
        if n == 0.0:
            raise ValueError("零向量无法归一化")
        return Vector3(self.x / n, self.y / n, self.z / n)

    def cross(self, o: "Vector3") -> "Vector3":
        return Vector3(
            self.y * o.z - self.z * o.y,
            self.z * o.x - self.x * o.z,
            self.x * o.y - self.y * o.x,
        )

    def dot(self, o: "Vector3") -> float:
        return self.x * o.x + self.y * o.y + self.z * o.z


@dataclass(frozen=True)
class Point3:
    x: float
    y: float
    z: float

    def __add__(self, v: Vector3) -> "Point3":
        return Point3(self.x + v.x, self.y + v.y, self.z + v.z)

    def __sub__(self, o: "Point3") -> Vector3:
        return Vector3(self.x - o.x, self.y - o.y, self.z - o.z)

    def distance_to(self, o: "Point3") -> float:
        return (self - o).norm

    @property
    def as_vector(self) -> Vector3:
        return Vector3(self.x, self.y, self.z)


@dataclass(frozen=True)
class Axis3:
    """一条 3D 轴线。

    跨视图对应的主要产出物（ARCHITECTURE §4.3）：视图 A 里过圆的中心线
    + 视图 B 里共线的中心线 ⇒ 同一条 3D 轴。
    """

    origin: Point3
    direction: Vector3
    #: 图上若标了半径/直径（如 `B—B 横剖 x=121.89（穿 r25.5 孔轴）` 里的 r25.5），
    #: 由调用方填 Claim[float]；纯轴线上可能为 None
    radius: object | None = None

    def __post_init__(self) -> None:
        if self.direction.norm == 0.0:
            raise ValueError("轴线方向不能是零向量")

    def normalized(self) -> "Axis3":
        return Axis3(self.origin, self.direction.normalized(), self.radius)

    def point_at(self, t: float) -> Point3:
        return self.origin + self.direction.normalized() * t


# 常用轴向（图纸坐标系）：X 向右，Y 向内（俯视），Z 向上
AXIS_X = Vector3(1.0, 0.0, 0.0)
AXIS_Y = Vector3(0.0, 1.0, 0.0)
AXIS_Z = Vector3(0.0, 0.0, 1.0)

#: 轴向名 → 单位向量。图上文字 `x=121.89` 里的 x 即此表键
AXIS_BY_NAME: dict[str, Vector3] = {
    "x": AXIS_X,
    "y": AXIS_Y,
    "z": AXIS_Z,
}
