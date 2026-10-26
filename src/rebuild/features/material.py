# -*- coding: utf-8 -*-
"""HATCH 材料判据 —— 剖面视图里"某点是材料吗"的可复用工具箱。

地面真值是 HATCH 填充：剖面图中打了剖面线的区域就是材料。边界边在 IR 里
以「原 handle#序号」散挂（Role.HATCH_BOUNDARY），按原 handle 重新分组，
一组 = 一个 HATCH 的全部边界环；点判定按**奇偶**（外环 + 内环天然 XOR）。

判据的消费者：
- `tower_cavity` —— 接点分叉仲裁（腔体边界的正确延续应在材料侧命中填充）；
- `axis_revolve.axis_bore_scan` —— 子午段两侧 ±1.5mm 探材料定"内/外侧"，把
  「内侧材料 ⇒ 凸（add）/ 外侧材料 ⇒ 凹（cut）」这一对极性直接读成特征。

只在 HATCH 覆盖处有信号 —— 打不出材料（两侧同态）的段是标注/中心线残留，
调用方自行区分"非边界"与"腔内部"（后者在 HATCH 里表现为两侧皆材料）。
"""
from __future__ import annotations

import math
from typing import TYPE_CHECKING

from ..model.geom2d import Arc2, Line2, Point2

if TYPE_CHECKING:
    from ..evidence.model import Drawing
    from ..views.correspondence import ViewFrame

_TAU = 2.0 * math.pi


def edge_points(g, step: float = 0.15) -> list[tuple[float, float]]:
    """边界边 → 折线点列（弧按弦长 step 采样）。"""
    if isinstance(g, Line2):
        return [(g.start.x, g.start.y), (g.end.x, g.end.y)]
    if isinstance(g, Arc2):
        span = (g.end_angle - g.start_angle) % _TAU
        n = max(2, int(g.radius * span / step))
        return [(g.center.x + g.radius * math.cos(g.start_angle + span * k / n),
                 g.center.y + g.radius * math.sin(g.start_angle + span * k / n))
                for k in range(n + 1)]
    return []


def near(a, b, tol: float) -> bool:
    return math.hypot(a[0] - b[0], a[1] - b[1]) <= tol


def chain_loops(segs, tol: float = 0.05) -> list[list[tuple[float, float]]]:
    """把边界边按端点相接串成环（每环一条点列）。"""
    chains: list[list[tuple[float, float]]] = []
    for g in segs:
        pts = edge_points(g)
        if len(pts) < 2:
            continue
        head, tail = pts[0], pts[-1]
        for ch in chains:
            if near(ch[-1], head, tol):
                ch.extend(pts[1:])
                break
            if near(ch[-1], tail, tol):
                ch.extend(reversed(pts[:-1]))
                break
        else:
            chains.append(list(pts))
    return [c for c in chains if len(c) >= 3]


def pt_in_poly(poly: list[tuple[float, float]], p: Point2) -> bool:
    """奇偶射线法。"""
    cnt = False
    n = len(poly)
    for i in range(n):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % n]
        if (y1 > p.y) != (y2 > p.y):
            xx = x1 + (p.y - y1) * (x2 - x1) / (y2 - y1)
            if p.x < xx:
                cnt = not cnt
    return cnt


def hatch_lines(d: "Drawing", fr: "ViewFrame", view_bbox) -> list[Line2]:
    """本视图 HATCH 边界里的**直线段**（已映射到 model 系）。

    用途：栅格采样只能给出量化后的面位（GRID=0.3 ⇒ ±0.3 的错位），而端面
    台阶的精确高度就在 HATCH 边界线上。消费方按「线段方向垂直于某轴」取该
    轴的精确坐标（如 y=69.83 / 70.83），把采样值吸附回图纸真值。
    """
    from ..evidence.model import Role
    out: list[Line2] = []
    for ev in d.evidence:
        if ev.role.value is not Role.HATCH_BOUNDARY:
            continue
        g = ev.geom
        if not isinstance(g, Line2):
            continue
        xs = [g.start.x, g.end.x]
        ys = [g.start.y, g.end.y]
        if (max(xs) < view_bbox.xmin or min(xs) > view_bbox.xmax
                or max(ys) < view_bbox.ymin or min(ys) > view_bbox.ymax):
            continue
        out.append(Line2(
            Point2(fr.u_to_model(g.start.x), fr.v_to_model(g.start.y)),
            Point2(fr.u_to_model(g.end.x), fr.v_to_model(g.end.y))))
    return out


def material_map(d: "Drawing", fr: "ViewFrame", view_bbox):
    """本视图 HATCH 填充的材料判据（点取 model 系的 Point2 → bool）。

    HATCH 的边界边在 IR 里以「原 handle#序号」散挂（Role.HATCH_BOUNDARY）——
    按原 handle 重新分组，一组 = 一个 HATCH 的全部边界环；点判定按**奇偶**
    （外环 + 内环天然 XOR）。只收与本视图 bbox 相交的 HATCH——别的视图的
    填充不该给本视图的点作证。环点借 fr 映射到 model 系（与段池同系）。
    """
    from ..evidence.model import Role
    groups: dict[str, list] = {}
    for ev in d.evidence:
        if ev.role.value is not Role.HATCH_BOUNDARY:
            continue
        base = str(ev.role.evidence[0]) if ev.role.evidence else "?"
        groups.setdefault(base, []).append(ev.geom)
    hatches: list[list[list[tuple[float, float]]]] = []
    for segs in groups.values():
        xs: list[float] = []
        ys: list[float] = []
        for g in segs:
            if isinstance(g, Line2):
                xs += [g.start.x, g.end.x]
                ys += [g.start.y, g.end.y]
            elif isinstance(g, Arc2):
                xs += [g.center.x - g.radius, g.center.x + g.radius]
                ys += [g.center.y - g.radius, g.center.y + g.radius]
        if not xs:
            continue
        if (max(xs) < view_bbox.xmin or min(xs) > view_bbox.xmax
                or max(ys) < view_bbox.ymin or min(ys) > view_bbox.ymax):
            continue
        loops = [[(fr.u_to_model(x), fr.v_to_model(y)) for x, y in ch]
                 for ch in chain_loops(segs)]
        if loops:
            hatches.append(loops)

    def material(p: Point2) -> bool:
        for loops in hatches:
            cnt = sum(1 for poly in loops if pt_in_poly(poly, p))
            if cnt % 2 == 1:
                return True
        return False

    # 材料图是否有效（本视图有 HATCH 且与本视图相交）——无 HATCH 的视图
    # （俯视/向视图）恒返回 False，消费方据此跳过而不是把"两侧空"当边界。
    material.has_hatch = bool(hatches)     # type: ignore[attr-defined]
    return material
