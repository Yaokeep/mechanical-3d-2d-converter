# -*- coding: utf-8 -*-
"""YZYX 式**塔腔**：端部搭在圆柱塔上的「冠—拱壳」切除（沿塔的横向挤出）。

图纸画法（塔轴 ∥ x 的剖面帧，即 p_axis = y 的全剖视图）：

    塔顶之下一条**冠线**（∥x 的长水平可见线），两端各接一对**同心弧**：
    小弧 = 冠角（半径 r_s、顶点落在冠线端点上），大弧 = 塔端部外形圆角
    （半径 r_b > r_s，弧顶 = 塔顶母线；两弧同心是因为腔冠与塔顶壳呈等厚）。
    自小弧的自由端起，轮廓以「端点相接 + 切向连续」向下延续成一条链
    （竖墙 → R 弧 → 横段 → R 弧 → … → 口袋台阶墙），直到 z ≈ 0 结合面；
    东西两链 + 底边 + 冠线合成闭合腔轮廓，斜度全由链上的弧段给出。

读数与推论（不写死任何数值）：

- 塔外半径 R 取自**塔特征母线**（REVOLVE，axis_revolve 所读）的最大 r；
- 冠高 h_c 取自冠线（= 小弧顶点）的 z；冠角半径 r_s = 小弧半径；
- **挤出半宽 W = √(R² − (h_c − 塔轴 z)²)**：腔侧壁落在「冠面与塔柱面的
  相贯线」上的几何推论（制图侧这条线在俯视图用细实线过渡线画出）；
- 轮廓链由端点/切向连续在段池上追踪；T 型接点先对段做拆分预处理。

**拒发**（只记账、不猜）：没有回转塔 / 塔轴非水平 / 找不到 p_axis = 横向
的剖面帧 / 冠线两端凑不出对称同心弧对 / 大弧顶点 ≠ 塔顶（塔母线）/
W² ≤ 0（冠面高于柱面，画法不成立）/ 链追踪断（无切向延续的下一段）或
两链尾不落在结合面。

发射：POCKET，axis = 横向轴，`axial_at` = 塔轴横向坐标 − W、depth = 2W
（契约：axial_at = 腔底，沿 +轴 挖）。profile 平面 ⊥ 挤出轴，其 (a, b)
轴序与 `occ_builder.basis_of` 一致（挤出轴 y ⇒ (a, b) = (z, x)）。
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING

from ..model.claim import Claim, Tier
from ..model.feature_tree import Feature, FeatureType
from ..model.geom import Axis3, Point3
from ..model.geom2d import Arc2, Line2, Point2, Profile2, ProfileSeg2
from ..model.ids import FeatureId
from .height_zones import _dir_vec
from .library import mk_claim
# HATCH 材料判据（工具箱已中立化，`axis_revolve.axis_bore_scan` 共用同一份；
# 私有名导入保持本模块旧调用点逐字不动）
from .material import (chain_loops as _chain_loops,
                       material_map as _material_map,
                       pt_in_poly as _pt_in_poly)
from .side_channels import _as_ccw, _axis_letter

if TYPE_CHECKING:
    from ..evidence.dxf_reader import Drawing
    from ..views.correspondence import CorrespondenceResult, ViewFrame
    from .recognizer import RecognizeReport

_TAU = 2.0 * math.pi

JOIN_TOL = 0.5        # 端点相接容差（图纸离散）
CONT_TOL = -0.2      # 切向延续下限：直角（cos 0）放行、回折（≈ −1）拒绝
FLOOR_TOL = 0.6       # 到达视图下边界（结合面）的停车容差
MIN_R_RATIO = 1.5     # 大弧 / 小弧半径比下限（塔壳必有厚度）
SYM_TOL = 0.5         # 左右弧对对称容差
VERTEX_TOL = 0.5      # 「弧端点 = 弧顶点」判据容差
PROBE_MM = 1.5        # 材料侧探针距离
TURN_MIN = 0.35       # 换段切向下限（dot ≥ 0.35 ≈ ≤69° 转折）才考虑偏离最优切向的段



def _uv(fr: "ViewFrame", p) -> Point2:
    """视图内坐标 → 图纸模型系 (u, v)。"""
    return Point2(fr.u_to_model(p.x), fr.v_to_model(p.y))


@dataclass
class _Seg:
    """追踪用段（图纸模型系 (u, v)）：直线或 Arc2 弧（恒 ccw sa→ea）。"""

    kind: str                       # "line" | "arc"
    p1: Point2
    p2: Point2
    center: Point2 | None = None    # 弧
    radius: float = 0.0
    ccw: bool = True
    sa: float = 0.0                 # 弧：p1 端角
    ea: float = 0.0                 # 弧：p2 端角
    handle: str = ""


def _seg_pool(d: "Drawing", fr: "ViewFrame", vid: str) -> list[_Seg]:
    """视图可见线段/圆弧池（滤零长退化段；整圆无端点不参与）。"""
    view = next((v for v in d.views if v.id == vid), None)
    if view is None:
        return []
    pool: list[_Seg] = []
    for h in view.evidence:
        e = d.by_handle(h)
        if e.role.value != "visible":
            continue
        g = e.geom
        if isinstance(g, Line2):
            a, b = _uv(fr, g.start), _uv(fr, g.end)
            if a.distance_to(b) < 0.1:
                continue
            pool.append(_Seg("line", a, b, handle=h))
        elif isinstance(g, Arc2):
            c = _uv(fr, g.center)
            a = Point2(c.x + g.radius * math.cos(g.start_angle),
                       c.y + g.radius * math.sin(g.start_angle))
            b = Point2(c.x + g.radius * math.cos(g.end_angle),
                       c.y + g.radius * math.sin(g.end_angle))
            if a.distance_to(b) < 0.1:
                continue
            pool.append(_Seg("arc", a, b, c, g.radius, True,
                             g.start_angle, g.end_angle, h))
    return pool


def _ang(c: Point2, p: Point2) -> float:
    return math.atan2(p.y - c.y, p.x - c.x)


def _vertex_of(sg: _Seg) -> Point2 | None:
    """弧顶点 (c.x, c.y + r) 若落在弧跨度内 ⇒ 返回之（即"向上凸"判据）。"""
    if sg.kind != "arc" or sg.center is None:
        return None
    if not ((math.pi / 2.0 - sg.sa) % _TAU) <= (sg.ea - sg.sa) % _TAU:
        return None
    return Point2(sg.center.x, sg.center.y + sg.radius)


def _tangent(sg: _Seg, end_p1: bool, enter_p1: bool) -> tuple[float, float]:
    """段在指定端处的**行进切向**（enter_p1 = 从 p1 端进入、走向 p2）。

    弧的切向沿弧变化：到达处取离开端、出发处取进入端——两端取对的切向
    才在同一接点上比较（拿两段的同名端比会在拐角处错判）。
    """
    if sg.kind == "line":
        a = sg.p1 if enter_p1 else sg.p2
        b = sg.p2 if enter_p1 else sg.p1
        dx, dy = b.x - a.x, b.y - a.y
        n = math.hypot(dx, dy)
        return (dx / n, dy / n) if n > 1e-12 else (0.0, 0.0)
    th = _ang(sg.center, sg.p1 if end_p1 else sg.p2)
    fw = ((-math.sin(th), math.cos(th)) if sg.ccw
          else (math.sin(th), -math.cos(th)))
    return fw if enter_p1 else (-fw[0], -fw[1])


def _arrive_tangent(sg: _Seg, enter_p1: bool) -> tuple[float, float]:
    """按「从 enter 端进入」的行进方向，到达**离开端**处的切向。"""
    return _tangent(sg, not enter_p1, enter_p1)


def _depart_tangent(sg: _Seg, enter_p1: bool) -> tuple[float, float]:
    """按「从 enter 端进入」的行进方向，在 **enter 端**（接点）处的切向。"""
    return _tangent(sg, enter_p1, enter_p1)


def _on_arc(sg: _Seg, p: Point2) -> float | None:
    """点落在弧跨度内的参数 s = (θ − sa) % 2π（严格内部返回），否则 None。"""
    if sg.kind != "arc" or sg.center is None:
        return None
    if abs(math.hypot(p.x - sg.center.x, p.y - sg.center.y) - sg.radius) > 0.1:
        return None
    s = (_ang(sg.center, p) - sg.sa) % _TAU
    span = (sg.ea - sg.sa) % _TAU
    if 0.02 < s < span - 0.02:
        return s
    return None


def _split_at_joints(pool: list[_Seg]) -> list[_Seg]:
    """T 型接点预处理：段内部的其它段端点处将段拆开。

    追踪按"端点相接"走，若某段中段挂着别的段的端点（如东墙竖线在口袋
    台阶高度被斜线搭上），不拆就会整段走过头/漏掉转角。
    """
    ends = [p for s in pool for p in (s.p1, s.p2)]
    out: list[_Seg] = []
    for sg in pool:
        cuts: list[tuple[float, float]] = []      # (参数, 1D 长度坐标)
        if sg.kind == "line":
            dx, dy = sg.p2.x - sg.p1.x, sg.p2.y - sg.p1.y
            L2 = dx * dx + dy * dy
            L = math.sqrt(L2)
            for p in ends:
                t = ((p.x - sg.p1.x) * dx + (p.y - sg.p1.y) * dy) / L2
                if not (0.03 < t < 0.97):
                    continue
                qx, qy = sg.p1.x + t * dx, sg.p1.y + t * dy
                if math.hypot(p.x - qx, p.y - qy) <= 0.1:
                    cuts.append((t, t * L))
        else:
            for p in ends:
                s_ = _on_arc(sg, p)
                if s_ is not None:
                    cuts.append((s_, s_ * sg.radius))
        if not cuts:
            out.append(sg)
            continue
        cuts.sort()
        merged: list[float] = []
        for t, _ in cuts:
            if not merged or t - merged[-1] > 1e-6:
                merged.append(t)
        if sg.kind == "line":
            pts = [sg.p1] + [Point2(sg.p1.x + t * (sg.p2.x - sg.p1.x),
                                    sg.p1.y + t * (sg.p2.y - sg.p1.y))
                             for t in merged] + [sg.p2]
            for a, b in zip(pts, pts[1:]):
                out.append(_Seg("line", a, b, handle=sg.handle))
        else:
            ss = [0.0] + merged + [(sg.ea - sg.sa) % _TAU]
            for s0, s1 in zip(ss, ss[1:]):
                a = Point2(sg.center.x + sg.radius * math.cos(sg.sa + s0),
                           sg.center.y + sg.radius * math.sin(sg.sa + s0))
                b = Point2(sg.center.x + sg.radius * math.cos(sg.sa + s1),
                           sg.center.y + sg.radius * math.sin(sg.sa + s1))
                out.append(_Seg("arc", a, b, sg.center, sg.radius, True,
                                sg.sa + s0, sg.sa + s1, sg.handle))
    return out


@dataclass
class _Pair:
    rs: _Seg          # 小弧（冠角）
    rb: _Seg          # 大弧（塔端部外形圆角）
    cs: Point2        # 公共圆心
    crown_end: Point2  # 冠线在该侧的端点（= 小弧顶点）


def _arc_pair(pool: list[_Seg], crown_end: Point2,
              r_ratio_min: float) -> _Pair | None:
    """在冠线端点处找「端点即顶点的小弧 + 同圆心更大弧」的弧对。"""
    smalls = [s for s in pool if s.kind == "arc"
              and (_vertex_of(s) is not None)
              and (_vertex_of(s).distance_to(crown_end) <= VERTEX_TOL)]
    for rs in smalls:
        for rb in pool:
            if rb is rs or rb.kind != "arc" or rb.center is None:
                continue
            if rb.center.distance_to(rs.center) > SYM_TOL:
                continue
            if rb.radius < rs.radius * r_ratio_min:
                continue
            if _vertex_of(rb) is None:
                continue
            return _Pair(rs, rb, rs.center, crown_end)
    return None


def _find_crown(pool: list[_Seg], tower_top_v: float
                ) -> tuple[_Seg, _Pair, _Pair] | None:
    """找冠线（水平可见长线）与其两端对称的同心弧对。"""
    for crown in pool:
        if crown.kind != "line":
            continue
        dy = abs(crown.p2.y - crown.p1.y)
        if dy > 0.05 or crown.p1.distance_to(crown.p2) < 0.5:
            continue
        wp, ep = sorted((crown.p1, crown.p2), key=lambda p: p.x)
        pw = _arc_pair(pool, wp, MIN_R_RATIO)
        pe = _arc_pair(pool, ep, MIN_R_RATIO)
        if pw is None or pe is None:
            continue
        # 左右对称 + 大弧顶点 = 塔顶母线（塔特征读数）
        if (abs(pw.cs.y - pe.cs.y) > SYM_TOL
                or abs(pw.rs.radius - pe.rs.radius) > SYM_TOL
                or abs(pw.rb.radius - pe.rb.radius) > SYM_TOL):
            continue
        top_w = pw.cs.y + pw.rb.radius
        if abs(top_w - tower_top_v) > SYM_TOL:
            continue
        return crown, pw, pe
    return None


def _enter_end(sg: _Seg, at: Point2) -> bool | None:
    """段从哪个端进入：True = p1 端，False = p2 端，不匹配返回 None。"""
    if sg.p1.distance_to(at) <= JOIN_TOL:
        return True
    if sg.p2.distance_to(at) <= JOIN_TOL:
        return False
    return None


# ---- HATCH 材料判据（接点分叉的仲裁） --------------------------------------
#
# 剖面视图里「材料」的地面真值是 HATCH 填充：腔体边界的正确延续，应在与
# 来段同侧的材料侧命中填充；而「过线」（同一实体被 T 型接点拆开的直落段、
# 邻件背棱）两侧都落在空腔里，材料侧探针打空。
# ⚠️ 该判据只在 HATCH 覆盖处有信号 —— 打不出材料侧时退回纯切向（旧行为）。
# 工具箱（edge_points / chain_loops / near / pt_in_poly / material_map）已搬
# 到 `features/material.py`（axis_revolve.axis_bore_scan 共用同一份）。


def _material_side(material, out: Point2, tang: tuple[float, float]) -> int:
    """来段到达端的材料侧：+1 = 左 / −1 = 右 / 0 = 判不出。"""
    qx, qy = out.x - PROBE_MM * tang[0], out.y - PROBE_MM * tang[1]
    lx, ly = -tang[1], tang[0]
    left = material(Point2(qx + PROBE_MM * lx, qy + PROBE_MM * ly))
    right = material(Point2(qx - PROBE_MM * lx, qy - PROBE_MM * ly))
    if left == right:
        return 0
    return 1 if left else -1


def _walk(pool: list[_Seg], first: _Seg, enter_p1: bool, z_floor: float,
          material=None) -> list[tuple[_Seg, bool]] | None:
    """端点/切向连续追踪：从 first 的进入端出发，走到视图下边界（结合面）。

    接点分叉（T 型接点，段池已按端点拆开）处的选择：
    1. 候选按切向点积排序——先看「换段」候选（dot ≥ TURN_MIN 且**材料侧
       探针命中 HATCH**），它优先于同实体的直落过线（YZYX 实测：西链在
       (20.5,81.47) 该走 7DF 斜段而不是沿 7DB 直落到底——后者是东壁带的
       背面棱，材料侧探针落空）；
    2. 没有合格换段候选时取点积最大者（直角横穿如 7C8 孔顶线 dot=0，
       自然回到直落——YZYX 实测东链在 (124.5,80) 继续 7C9 到结合面）。
    """
    used = {id(first)}
    path: list[tuple[_Seg, bool]] = [(first, enter_p1)]
    cur, ep1 = first, enter_p1
    for _ in range(40):
        out = cur.p2 if ep1 else cur.p1
        if out.y <= z_floor + FLOOR_TOL:
            return path
        tang = _arrive_tangent(cur, ep1)
        cands: list[tuple[float, _Seg, bool, tuple[float, float]]] = []
        for s in pool:
            if id(s) in used:
                continue
            for s_ep1 in (True, False):
                p = s.p1 if s_ep1 else s.p2
                if p.distance_to(out) > JOIN_TOL:
                    continue
                t2 = _depart_tangent(s, s_ep1)
                cands.append((tang[0] * t2[0] + tang[1] * t2[1], s, s_ep1, t2))
        if not cands:
            return None
        cands.sort(key=lambda t: -t[0])
        pick: tuple[_Seg, bool, float] | None = None
        if material is not None:
            side = _material_side(material, out, tang)
            if side:
                for dot, s, s_ep1, (tx, ty) in cands:
                    if dot < TURN_MIN:
                        break
                    qx, qy = out.x + PROBE_MM * tx, out.y + PROBE_MM * ty
                    probe = Point2(qx + side * PROBE_MM * -ty,
                                   qy + side * PROBE_MM * tx)
                    if material(probe):
                        pick = (s, s_ep1, dot)
                        break
        if pick is None:
            pick = (cands[0][1], cands[0][2], cands[0][0])
        if pick[2] < CONT_TOL:
            return None
        cur, ep1 = pick[0], pick[1]
        used.add(id(cur))
        path.append((cur, ep1))
    return None


def _snap_ends(segs: list[ProfileSeg2]) -> list[ProfileSeg2]:
    """链端焊接：把每段 p2 改写成下一段 p1（弧重取终角），使遍历序逐位闭合。

    追踪按 JOIN_TOL=0.5 相接，而 ``chain_break`` 要求 1e-6 —— 图纸离散的
    残余接头（实测 7DF→7E0 差 0.06）必须在此消掉。线段方向与弧心半径不动，
    只动端点（≤ JOIN_TOL，与图纸离散同量级）。
    """
    n = len(segs)
    out: list[ProfileSeg2] = []
    for i, s in enumerate(segs):
        p2 = segs[(i + 1) % n].p1
        if not s.is_arc:
            out.append(ProfileSeg2("line", s.p1, p2))
        else:
            out.append(ProfileSeg2("arc", s.p1, p2, center=s.center,
                                   radius=s.radius, ccw=s.ccw,
                                   sa=s.sa, ea=_ang(s.center, p2)))
    return out


def _to_seg2(sg: _Seg, enter_p1: bool) -> ProfileSeg2:
    p1 = sg.p1 if enter_p1 else sg.p2
    p2 = sg.p2 if enter_p1 else sg.p1
    if sg.kind == "line":
        return ProfileSeg2("line", p1, p2)
    ccw = sg.ccw if enter_p1 else not sg.ccw
    sa = sg.sa if enter_p1 else sg.ea
    ea = sg.ea if enter_p1 else sg.sa
    return ProfileSeg2("arc", p1, p2, center=sg.center, radius=sg.radius,
                       ccw=ccw, sa=sa, ea=ea)


def _reversed_seg2(s: ProfileSeg2) -> ProfileSeg2:
    if not s.is_arc:
        return ProfileSeg2("line", s.p2, s.p1)
    return ProfileSeg2("arc", s.p2, s.p1, center=s.center, radius=s.radius,
                       ccw=not s.ccw, sa=s.ea, ea=s.sa)


def _to_ab(s: ProfileSeg2, b1: str, b2: str, coords_axes: tuple[str, str]
           ) -> ProfileSeg2:
    """(u, v) 平面段 → 挤出轴的面内 (a, b) 段（轴序按 basis_of）。

    (u, v) = (coords_axes) 是视图两轴在图纸系里的字母。映射 (x,z)→(z,x)
    是镜像：弧端角按 a 轴/ b 轴重取、ccw 翻转。
    """
    def P(p: Point2) -> Point2:
        d = {coords_axes[0]: p.x, coords_axes[1]: p.y}
        return Point2(d[b1], d[b2])
    p1, p2 = P(s.p1), P(s.p2)
    if not s.is_arc:
        return ProfileSeg2("line", p1, p2)
    c = P(s.center)
    sa = _ang(c, p1)
    ea = _ang(c, p2)
    # 镜像映射翻转环向：p1→p2 的跨角大小不变，方向取反
    return ProfileSeg2("arc", p1, p2, center=c, radius=s.radius,
                       ccw=not s.ccw, sa=sa, ea=ea)


_BASIS_AB = {"x": ("y", "z"), "y": ("z", "x"), "z": ("x", "y")}


def _find_tower(part) -> Feature | None:
    """特征树里母线最大 r 最大的 REVOLVE（YZYX 的塔）。"""
    best: tuple[float, Feature] | None = None
    for f in part.features:
        if f.type.value != "revolve":
            continue
        pr = f.params.get("radius_profile")
        prof = getattr(pr, "value", pr)
        if not prof:
            continue
        r = max(float(rr) for _, rr in prof)
        if best is None or r > best[0]:
            best = (r, f)
    return None if best is None else best[1]


def tower_cavity(d: "Drawing", corr: "CorrespondenceResult", part,
                 rep: "RecognizeReport") -> int:
    """塔腔读数与发射。返回新特征数；读不到只记账（notes），不猜。"""
    tower = _find_tower(part)
    if tower is None:
        rep.notes.append("塔腔：特征树里没有回转塔（REVOLVE 母线最大 r）⇒ 不建")
        return 0
    al = _axis_letter(tower)
    ex = {"x": "y", "y": "x"}.get(al)
    if ex is None:
        rep.notes.append(f"塔腔：塔轴 {al or '?'} 非水平（或读不出）⇒ 本画法不适用")
        return 0
    ax = tower.axis.value
    pr = tower.params["radius_profile"]
    profile = getattr(pr, "value", pr)
    R_tower = max(float(rr) for _, rr in profile)
    tower_top_v = ax.origin.z + R_tower
    b1, b2 = _BASIS_AB[ex]

    hit: tuple[str, "ViewFrame", _Seg, _Pair, _Pair,
                list[tuple[_Seg, bool]], list[tuple[_Seg, bool]]] | None = None
    for vid, fr in sorted(corr.frames.items()):
        if fr.p_axis != ex:
            continue
        view = next((v for v in d.views if v.id == vid), None)
        if view is None or view.bbox is None:
            continue
        pool = _split_at_joints(_seg_pool(d, fr, vid))
        found = _find_crown(pool, tower_top_v)
        if found is None:
            continue
        crown, pw, pe = found
        wp, ep = sorted((crown.p1, crown.p2), key=lambda p: p.x)
        ew = _enter_end(pw.rs, wp)
        ee = _enter_end(pe.rs, ep)
        if ew is None or ee is None:
            continue
        # 停车地板 = 本视图下边界，映射到与段池同一坐标系（model 系）
        z_floor = fr.v_to_model(view.bbox.ymin)
        material = _material_map(d, fr, view.bbox)
        wpath = _walk(pool, pw.rs, ew, z_floor, material)
        epath = _walk(pool, pe.rs, ee, z_floor, material)
        if wpath is None or epath is None:
            rep.notes.append(
                f"塔腔：视图 {vid} 链追踪断（西 {'OK' if wpath else '断'} / "
                f"东 {'OK' if epath else '断'}）⇒ 不建")
            continue
        hit = (vid, fr, crown, pw, pe, wpath, epath)
        break
    if hit is None:
        rep.notes.append(
            "塔腔：没有 p_axis = 横向轴的剖面帧读得出「冠线 + 两端对称"
            "同心弧对（小弧冠角 / 大弧塔外形圆角，弧顶 = 塔顶母线）」⇒ 不建")
        return 0

    vid, fr, crown, pw, pe, wpath, epath = hit
    # 挤出半宽：冠面与塔柱面相交（腔壁落在相贯线上）
    # 冠高取冠线 v；塔轴 v 取「塔顶（大弧顶点，种子已核 ≡ 塔顶母线）− R」
    # —— 两者都是图纸读数。不用 ax.origin.z：revolve 识别的轴位置带
    # 0.0485 误差（实测 1541.2 vs 图纸 1541.2485 = 塔顶 1728.7485 − 187.5）
    h_c = crown.p1.y                        # 冠线 v 坐标（model 系）
    axis_v = pw.rb.center.y + pw.rb.radius - R_tower   # 塔轴 v（model 系）
    h = h_c - axis_v
    W2 = R_tower * R_tower - h * h
    if W2 <= 1.0:
        rep.notes.append(
            f"塔腔：冠高 {h:.2f} 不低于塔柱面半径 {R_tower:.2f} —— 腔侧壁"
            "落不到相贯线上（画法不成立）⇒ 不建")
        return 0
    W = math.sqrt(W2)
    if W < 2.0:
        rep.notes.append(f"塔腔：挤出半宽 {W:.2f} 过小 ⇒ 不建")
        return 0
    coords_axes = (fr.u_axis, fr.v_axis)

    # 组装闭合链：西链 → 底边 → 东链反向 → 冠线反向
    segs2: list[ProfileSeg2] = [_to_seg2(sg, ep1) for sg, ep1 in wpath]
    w_out = wpath[-1][0].p2 if wpath[-1][1] else wpath[-1][0].p1
    e_out = epath[-1][0].p2 if epath[-1][1] else epath[-1][0].p1
    segs2.append(ProfileSeg2("line", w_out, e_out))
    segs2.extend(_reversed_seg2(_to_seg2(sg, ep1))
                 for sg, ep1 in reversed(epath))
    ec = _enter_end(crown, ep)
    # 自东端进入冠线、走到西端 —— 正好接回西链首段的起点
    segs2.append(_to_seg2(crown, ec if ec is not None else True))
    segs2 = _snap_ends(segs2)
    prof_ab = Profile2(tuple(_to_ab(s, b1, b2, coords_axes) for s in segs2))
    brk = prof_ab.chain_break()
    if brk is not None:
        rep.notes.append(f"塔腔：轮廓链在段 {brk} 断开 ⇒ 不建")
        return 0
    prof_ab = _as_ccw(list(prof_ab.segments))

    ev = tuple(dict.fromkeys(
        [crown.handle] + [pw.rs.handle, pw.rb.handle, pe.rs.handle, pe.rb.handle]
        + [sg.handle for sg, _ in wpath] + [sg.handle for sg, _ in epath]))
    method = "tower:crown_prism"
    ay = ax.origin.y
    f = Feature(
        id=FeatureId(-1),
        type=Claim(FeatureType.POCKET, method, Tier.PROJECTION, ev),
        params={"profile": Claim(prof_ab, method, Tier.PROJECTION, ev),
                "depth": mk_claim(2.0 * W, method, Tier.PROJECTION, ev),
                # POCKET 契约：axial_at = 腔底（沿 +轴 挖 depth）
                "axial_at": mk_claim(ay - W, method, Tier.PROJECTION, ev)},
        placement=Claim(Point3(0.0, 0.0, 0.0), method, Tier.PROJECTION, ev),
        axis=Claim(Axis3(Point3(0.0, 0.0, 0.0), _dir_vec(ex)), method,
                   Tier.PROJECTION, ev),
        source_view=vid, evidence=list(ev))
    f.id = part.next_id()
    part.add(f)
    rep.notes.append(
        f"塔腔：POCKET {ex}∈[{ay - W:.2f},{ay + W:.2f}]（半宽 {W:.2f} = "
        f"√({R_tower:.2f}²−{h:.2f}²)），轮廓 {len(prof_ab.segments)} 段 "
        f"（含弧 {sum(1 for s in prof_ab.segments if s.is_arc)}），"
        f"冠高 {h:.2f}、冠角 R{pw.rs.radius:.2f}、塔圆角 R{pw.rb.radius:.2f}")
    return 1
