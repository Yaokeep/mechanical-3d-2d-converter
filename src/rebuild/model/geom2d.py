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
class Polyline2:
    """折线（样条/椭圆的采样结果也用它承载）。

    存在的理由有两件，都属"不许静默丢信息"：

    1. **断裂视图的波浪线**通常画成 SPLINE —— "这个视图被缩短了"这个信号
       只能从它读出来。旧管线完全不读 SPLINE（本项目 `CAD/reducer.dxf`
       就有 4 条），断裂视图因此被当成完整视图，尺寸直接搞错
    2. 采样的多边形比原曲线低一档精度，但**方向与跨度**这类判据只用到
       bbox，足够；真正的精确曲线留给 OCC 侧（emit）从原文件重读
    """

    points: tuple[Point2, ...]
    closed: bool = False

    def bbox(self) -> BBox2:
        return BBox2.of_points(list(self.points))

    @property
    def length(self) -> float:
        return sum(p.distance_to(q) for p, q in zip(self.points, self.points[1:]))


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


@dataclass(frozen=True)
class ProfileSeg2:
    """有向轮廓段：``p1 → p2``，直线或弧（弧带走向）。

    纸面 CCW 的闭合轮廓要按遍历方向还原每段走向；``Arc2`` 是 DXF
    语义（恒为 CCW 从 start 到 end），表达不了被反向走过的弧，故另立
    本类型。它是**跨层轮廓契约**：views 层（ring.py）提取、本模块承载、
    emit 层（OCC / SW）消费——发射器只依赖 model，不依赖 views。
    """

    kind: str                              # "line" | "arc"
    p1: Point2
    p2: Point2
    center: Point2 | None = None           # 弧：圆心
    radius: float = 0.0                    # 弧：半径
    ccw: bool = True                       # 弧：p1→p2 是否逆时针
    sa: float = 0.0                        # 弧：p1 源角度（弧度，原值）
    ea: float = 0.0                        # 弧：p2 源角度（弧度，原值）

    @property
    def is_arc(self) -> bool:
        return self.kind == "arc"


def _angle_in_span(q: float, sa: float, ea: float, ccw: bool) -> bool:
    """角度 ``q`` 是否落在弧 ``sa→ea``（按 ``ccw``）的跨度内（自 ring.py 提升）。"""
    tau = 2.0 * math.pi
    if ccw:
        span = (ea - sa) % tau
        return ((q - sa) % tau) <= span + 1e-12
    span = (sa - ea) % tau
    return ((sa - q) % tau) <= span + 1e-12


@dataclass(frozen=True)
class Profile2:
    """闭合有向轮廓（外环；纸面 CCW 正面积）——**发射器的统一 2D 契约**。

    ``Feature`` 的 ``profile`` 参数既可为原始 ``[(a, b), ...]`` 点列
    （多边形路径，历史兼容），也可为本类型（允许圆弧段）。面积取
    **顶点折线鞋带**口径——与 ``ring.Ring.area`` 一致（旧管线即如此，
    保证两遍提取与下游门控可比）。
    """

    segments: tuple[ProfileSeg2, ...]

    @property
    def is_polygonal(self) -> bool:
        return all(s.kind != "arc" for s in self.segments)

    def chain_break(self, tol: float = 1e-6) -> int | None:
        """段序检查：返回第一个断点段号，闭合链返回 None。

        发射器建 wire 的前提是**段序即遍历序**（每段 ``p2`` 接下一段
        ``p1``，末段接首段）。乱序输入不能让 ``BRepBuilderAPI_MakeWire``
        自己兜——它会自动重排"看起来能连"的边，产出面面积对、拉伸体积
        错的怪形状（实测 D 形乱序：面积 957.08 vs 正确 557.08）。故
        进门先验，把上游顺序错误变成显式报错。段数 <2 视为断在 0
        （单段闭不了口；两段弧的双弧整圆是合法下限）。
        """
        n = len(self.segments)
        if n < 2:
            return 0
        for i in range(n):
            a = self.segments[i].p2
            b = self.segments[(i + 1) % n].p1
            if a.distance_to(b) > tol:
                return i
        return None

    def signed_area(self) -> float:
        """有符号面积（顶点鞋带；CCW 为正）。"""
        a = 0.0
        n = len(self.segments)
        for i in range(n):
            p, q = self.segments[i].p1, self.segments[(i + 1) % n].p1
            a += p.x * q.y - q.x * p.y
        return a / 2.0

    def bbox(self) -> BBox2:
        """几何 bbox，含弧的四象限极值点（不只是端点）。"""
        xs: list[float] = []
        ys: list[float] = []
        for s in self.segments:
            xs += [s.p1.x, s.p2.x]
            ys += [s.p1.y, s.p2.y]
            if s.kind == "arc" and s.center is not None and s.radius > 0:
                for base in (0.0, math.pi / 2, math.pi, 3 * math.pi / 2):
                    if _angle_in_span(base, s.sa, s.ea, s.ccw):
                        xs.append(s.center.x + s.radius * math.cos(base))
                        ys.append(s.center.y + s.radius * math.sin(base))
        return BBox2(min(xs), min(ys), max(xs), max(ys))

    def corner_points(self) -> tuple[Point2, ...]:
        """段起点序列（弧退化为弦端——给点列消费方的近似视图）。"""
        return tuple(s.p1 for s in self.segments)

    def to_point_tuples(self) -> list[tuple[float, float]]:
        return [(p.x, p.y) for p in self.corner_points()]

    def reversed(self) -> "Profile2":
        """反向遍历（段序倒转，每段 ``p1 ↔ p2``；弧同步换向）。

        用途：坐标映射时轴对调（行列式 −1）会把环翻成 CW —— 用它把
        轮廓统一回"纸面 CCW 正面积"的契约（``Ring`` 层同理，
        view frame 的 u/v 与轮廓平面 (b1, b2) 未必同序）。
        """
        out = []
        for s in reversed(self.segments):
            if s.kind == "line":
                out.append(ProfileSeg2("line", s.p2, s.p1))
            else:
                out.append(ProfileSeg2("arc", s.p2, s.p1, s.center,
                                       s.radius, not s.ccw, s.ea, s.sa))
        return Profile2(tuple(out))


def profile_span(profile: "Profile2 | list[tuple[float, float]]"
                 ) -> tuple[float, float]:
    """轮廓在 (a, b) 两轴上的跨度 —— 两种表示的统一口径。

    点列（历史路径）：取 ``max`` 口径（多项式轮廓锚定在原点角，
    ``max`` 即宽度，与 v0.5 起的既有语义一致）；Profile2：取几何
    bbox 宽高（含弧的四象限极值，不是弦端——臂端圆头算直径）。
    """
    if isinstance(profile, Profile2):
        bb = profile.bbox()
        return bb.width, bb.height
    return (max(float(p[0]) for p in profile),
            max(float(p[1]) for p in profile))
