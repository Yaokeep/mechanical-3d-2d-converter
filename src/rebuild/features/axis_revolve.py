# -*- coding: utf-8 -*-
"""绕坐标轴的回转族识别——「画不全的圆弧」读成轮廓（YZYX 齿箱上盖首例）。

## 为什么单开一路

``revolve.detect_revolve`` 的入口是**圆柱提示**（圆边 ↔ 正交视图轮廓对的
对应），而 YZYX 的塔/盘/止口/侧裙在端视图里画的全是**短弧**：覆盖不足
``ARC_COVER_MIN``（170°）的 r145 59.5° / r110 90.5° / r95 27.5° 被
`_circle_edges_of` 直接丢弃；覆盖够了 170.5° 的 r187.5 又被 `_profile_arc`
判为轮廓弧（缺口 189.5° 且整条落在视图轮廓盒外）⇒ 圆柱提示只剩 r48.25
一条，`detect_revolve` 因 hints < 3 返回 None，整条绕 X 轴的回转栈被读成
竖直棱柱堆叠（TL 缺 200 的主体正是这些线）。

**短弧本身就是"这不是圆、是轮廓"的直接证据**——圆没画完的那截在视图轮廓
之外，按制图法不可能有材料（`_profile_arc` 的判据）；连 170° 都画不到的更
不必说（真孔的圆边一定画满，或画到剖分面为止——那是 180.5° 的半孔）。
同一圆心出 ≥3 条互异半径的短弧 ⇒ 圆心 + 视线方向 = 回转轴。

## 判据链

1. **端视短弧簇**：在 ``p_axis == 轴名`` 的视图里把 visible 弧按（圆心, 半径）
   归组、组内算角覆盖（与 `_circle_edges_of` 同一套 ``_arc_cover``/`_profile_arc``）；
   "短弧组" = 覆盖 < ``ARC_COVER_MIN`` 或被判轮廓弧。短弧组按圆心 ±``CENTER_TOL``
   再聚簇，簇内互异半径 ≥ ``MIN_RADII`` ⇒ 候选轴（轴心 = 簇内最大半径弧的
   **精确**圆心过 u/v_to_model 映射，轴向分量 0——母线 t 因此可用**绝对**图纸
   坐标，与 `_axial_lines` 同口径）。组键的 0.1mm 舍入只用于归组；2026-10-17 修
   过一处把它漏进轴心的 bug（YZYX 塔被整体读偏 (−0.037, −0.049)）。
2. **母线扫描**：对候选轴，在子午视图（轴 ∈ {u_axis, v_axis} 且 p_axis ≠ 轴）
   复用 `revolve._axial_lines` 收 ∥轴线段，按 |r − 半径表| ≤ ``RADIUS_TOL``
   匹配、同视图同半径合并（gap ≤ ``SEG_GAP``）。**只收 visible 线**——
   中心线/虚线会把 span 污染成伪长段（`_axial_lines` 自身不滤角色）。
3. **跨视图裁决**：同一半径在多视图的 span 取**交集**。同一条轮廓在不同视图
   的可见段不同：YZYX r145 在 V1 被共面面并成 [−166.5,−0.5]、在 V3 只画盘段
   [−166.5,−146.5]（三段碎段），交出来才是盘的真实跨度。交集为空 ⇒ 放弃该
   半径并记账（不猜哪一边对）。
4. **端部圆角**：段端点处找**图纸画出来的**过渡圆角弧——圆心轴向坐标 ≈ 端点
   且 |圆管半径 + 圆心径向 − 段半径| ≤ ``FILLET_RTOL``、两端点的（轴向, 径向）
   与 (端点上、段半径)/(外侧、段半径−R) 逐点吻合。YZYX 塔的 R15 环面转角
   V1/V3 都画了（c=(14.5/122.5,172.5) r15，象限 90°..180° / 0°..90°）；
   命中则母线外延到 (端点 ± R, 半径 − R) 并把圆弧离散 ``FILLET_SEGS`` 段。
   找不到圆角就按 span 端点当直角端面（盘/止口/侧裙都是这样画对的）。
5. **发射**：REVOLVE、``angle_deg = 180``——母线面在 +b1 侧（轴 +x 时
   ``basis_of`` 给 b1=+y），右手扫过 +b1 → +轴向 → −b1，恰好是**材料所在
   半側**（YZYX 全部在 z ≥ 轴高）。母线端点经轴自动闭合（`_build_revolve`）。

## 不建的东西（如实记账）

半剖简化的一半止口平顶（z=100 仅 y≤0 半）、塔腔（冠 177.5 + R5 角）、
Ø100 竖直腔 + U 碗槽、右端块 r107.5/填角/Ø160 孔——v1 只落四条回转母线
（塔/盘/止口/侧裙），其余按缺口留在表上。
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING

from ..evidence.model import Kind, Role
from ..model.claim import Claim, Tier
from ..model.feature_tree import Feature, FeatureType
from ..model.geom import Axis3, Point3, Vector3
from ..model.geom2d import Arc2, Circle2, Point2
from ..model.ids import FeatureId
from ..views.correspondence import ARC_COVER_MIN, _arc_cover, _profile_arc
from .library import mk_claim
from .material import material_map as _material_map
from .recognizer import AXIS_POS_TOL
from .revolve import AXIS_R_TOL, RADIUS_TOL, SEG_GAP, _axial_lines, _merge_spans

if TYPE_CHECKING:
    from ..evidence.dxf_reader import Drawing
    from ..views.correspondence import CorrespondenceResult, ViewFrame
    from .recognizer import RecognizeReport

#: 端视图弧簇的圆心归组容差（mm）。出图圆弧的圆心是精确值（YZYX 四条弧
#: 圆心逐位相同），0.5 只是浮点与舍入余量。
CENTER_TOL = 0.5
#: 成"族"的最少互异半径——两个同心短弧不构成回转体（大圆弧的常见结构）。
MIN_RADII = 3
#: 母线最短段（mm）——比这短的 span 是出图碎段，不进母线。
MIN_SEG = 0.8
#: 圆角弧圆心与段端点的轴向差容差（mm）。
FILLET_CX_TOL = 0.6
#: 「圆管半径 + 圆心径向 − 段半径」的容差（mm）。
FILLET_RTOL = 0.5
#: 过渡圆角的管半径范围——比 FILLET_R_MIN 小的（如 R5 根部圆角）不算端部
#: 过渡（YZYX 盘东端的 r5 弧正因此不吃掉 r140 台阶）；比 MAX 大的不是圆角。
FILLET_R_MIN = 8.0
FILLET_R_MAX = 40.0
#: 圆角离散段数（母线点数 = 段数 + 1）。
FILLET_SEGS = 5


@dataclass(frozen=True)
class _AxisCand:
    """候选回转轴：轴向名 + 轴心（轴向分量 0）+ 短弧半径表。"""

    dir_name: str
    centre: Point3
    radii: tuple[float, ...]
    views: tuple[str, ...]


@dataclass(frozen=True)
class _Cap:
    """段端部的过渡圆角：圆管半径 + 母线外延点列（含端点）。

    ``pts`` 按**母线行进方向**（西→东）排：(沿轴绝对坐标, 半径)。
    西端的末点 = (x0, rn)、东端的首点 = (x1, rn)，两端各自的最外点
    （远端）是 (x_end∓R, rn−R)——拼接时直角/圆角端点因此自动接上顶线直段。
    """

    radius: float
    pts: list[tuple[float, float]]
    handle: str


# ---------------------------------------------------------------------------
# 1) 端视短弧簇 ⇒ 候选轴
# ---------------------------------------------------------------------------

def _short_arc_groups(d: Drawing, fr: ViewFrame) -> dict[tuple, list[tuple]]:
    """一个视图里"短弧组"：{(圆心坐标, 半径): [(handle, Arc2)]}。

    与 `_circle_edges_of` 同一套判据的**补集**：覆盖 ≥ ``ARC_COVER_MIN``
    且不被 `_profile_arc` 判轮廓弧的组是圆边（不属于这里）。
    """
    view = next((v for v in d.views if v.id == fr.view_id), None)
    if view is None:
        return {}
    groups: dict[tuple, list[tuple]] = {}
    for h in view.evidence:
        e = d.by_handle(h)
        if e is None or e.kind != Kind.EDGE or e.role.value != Role.VISIBLE:
            continue
        g = e.geom
        if isinstance(g, Circle2):
            continue                        # 整圆 = 圆边（孔/凸台），不是短弧
        if not isinstance(g, Arc2):
            continue
        key = (round(g.center.x, 1), round(g.center.y, 1), round(g.radius, 3))
        groups.setdefault(key, []).append((h, g))
    out: dict[tuple, list[tuple]] = {}
    for key, items in groups.items():
        spans = [(a.start_angle, (a.end_angle - a.start_angle) % (2 * math.pi))
                 for _, a in items]
        if _arc_cover(spans) < ARC_COVER_MIN:
            out[key] = items                  # 画不全 ⇒ 轮廓弧
            continue
        c, r = items[0][1].center, items[0][1].radius
        if _profile_arc(c.x, c.y, r, spans, view.bbox):
            out[key] = items                  # 缺口在轮廓盒外 ⇒ 轮廓弧
    return out


def _axis_candidates(d: Drawing,
                     corr: CorrespondenceResult) -> list[_AxisCand]:
    """端视图里的短弧簇 ⇒ 候选轴（沿视线方向的回转轴）。"""
    cands: list[_AxisCand] = []
    for vid in sorted(corr.frames):
        fr = corr.frames[vid]
        name = fr.p_axis
        if name not in ("x", "y", "z"):
            continue
        groups = _short_arc_groups(d, fr)
        # 按圆心聚簇（圆心坐标 ±CENTER_TOL）
        clusters: list[dict] = []
        for (cx, cy, r), items in sorted(groups.items()):
            # 组键是**舍入值**（只用来归组）；轴心必须取弧自身的精确圆心 ——
            # 键的 0.1 舍入曾漏进轴心（YZYX 塔轴读成 3462.90/1541.20，图纸
            # 真值 3462.9371/1541.2485，整根塔偏 (−0.0371, −0.0485)，腔冠
            # 面随之穿出塔面 0.14mm）。取簇内**最大半径弧**的圆心为读数。
            gc = items[0][1].center
            for cl in clusters:
                if (abs(cx - cl["c"][0]) <= CENTER_TOL
                        and abs(cy - cl["c"][1]) <= CENTER_TOL):
                    cl["radii"].add(r)
                    cl["views"].add(vid)
                    if r > cl["rmax"]:
                        cl["rmax"] = r
                        cl["pc"] = gc
                    break
            else:
                clusters.append({"c": (cx, cy), "radii": {r}, "views": {vid},
                                 "rmax": r, "pc": gc})
        for cl in clusters:
            if len(cl["radii"]) < MIN_RADII:
                continue
            gc = cl["pc"]
            coords = {fr.u_axis: fr.u_to_model(gc.x),
                      fr.v_axis: fr.v_to_model(gc.y), fr.p_axis: 0.0}
            cands.append(_AxisCand(
                name, Point3(coords["x"], coords["y"], coords["z"]),
                tuple(sorted(cl["radii"])), tuple(sorted(cl["views"]))))
    # 同一轴的两张端视图（YZYX 的 V0/V4）合并：轴心距 ≤ AXIS_POS_TOL
    merged: list[_AxisCand] = []
    for c in cands:
        for m in merged:
            if m.dir_name == c.dir_name and \
                    m.centre.distance_to(c.centre) <= AXIS_POS_TOL:
                m2 = _AxisCand(m.dir_name, m.centre,
                               tuple(sorted(set(m.radii) | set(c.radii))),
                               tuple(sorted(set(m.views) | set(c.views))))
                merged[merged.index(m)] = m2
                break
        else:
            merged.append(c)
    return merged


# ---------------------------------------------------------------------------
# 2) 母线扫描（子午视图轴向线 × 跨视图 span 交集）
# ---------------------------------------------------------------------------

def _span_scan(d: Drawing, fr: ViewFrame, dir_name: str, centre: Point3,
               rn: float) -> tuple[list[tuple[float, float]], list[str]]:
    """一个子午视图里、半径 ``rn`` 的 visible 轴向线 span（合并）+ 证据句柄。"""
    lines = _axial_lines(d, fr, dir_name, centre)
    keep: list[tuple[float, float]] = []
    ev: list[str] = []
    for ln in lines:
        e = d.by_handle(ln.handle)
        if e is None or e.role.value != Role.VISIBLE:
            continue
        if ln.r < AXIS_R_TOL or abs(ln.r - rn) > RADIUS_TOL:
            continue
        keep.append((ln.t0, ln.t1))
        ev.append(ln.handle)
    if not keep:
        return [], []
    return _merge_spans(keep, SEG_GAP), ev


def _cross_view_spans(segs_by_view: dict[str, list[tuple[float, float]]]
                      ) -> list[tuple[float, float]]:
    """多视图 span 取交集（逐视图链式）。任一视图交空 ⇒ 返回空（放弃该半径）。"""
    order = list(segs_by_view)
    cur = segs_by_view[order[0]]
    for vid in order[1:]:
        nxt: list[tuple[float, float]] = []
        for a0, a1 in cur:
            for b0, b1 in segs_by_view[vid]:
                lo, hi = max(a0, b0), min(a1, b1)
                if hi - lo > 1e-6:
                    nxt.append((lo, hi))
        cur = _merge_spans(nxt, SEG_GAP) if nxt else []
        if not cur:
            return []
    return cur


# ---------------------------------------------------------------------------
# 3) 段端部的过渡圆角（图纸画出来的弧）
# ---------------------------------------------------------------------------

def _end_cap(d: Drawing, mframes: list[ViewFrame], dir_name: str,
             centre: Point3, x_end: float, rn: float, west: bool
             ) -> _Cap | None:
    """段端点处的过渡圆角弧；west=True 找西端（远端点 x_end−R），否则东端。

    校验三层：圆心轴向 ≈ 端点；「管半径 + 圆心径向 = 段半径」（径向取到轴的
    垂距，两侧同判）；弧的两端点逐点吻合 (端点上, rn) 与 (外侧, rn−R)。
    """
    ax_want = {"x": 0.0, "y": 0.0, "z": 0.0}
    for fr in mframes:
        view = next((v for v in d.views if v.id == fr.view_id), None)
        if view is None:
            continue
        u_is_ax = fr.u_axis == dir_name
        rad_axis = fr.v_axis if u_is_ax else fr.u_axis
        c_ax = {"x": centre.x, "y": centre.y, "z": centre.z}[rad_axis]
        for h in view.evidence:
            e = d.by_handle(h)
            if e is None or e.kind != Kind.EDGE:
                continue
            # 角色放宽到 VISIBLE ∪ AXIS：YZYX 端块的凹填角弧被绘图误设成
            # 粗实线层 + CENTER2 线型（role=axis），几何上却是真轮廓——
            # 三层校验（圆心轴向/径向/端点逐点吻合）足够严，伪弧（中心线弧）
            # 过不了；只认 VISIBLE 会让这类凹帽整条丢失。
            if e.role.value not in (Role.VISIBLE, Role.AXIS):
                continue
            g = e.geom
            if not isinstance(g, Arc2):
                continue
            R = g.radius
            if not (FILLET_R_MIN <= R <= FILLET_R_MAX):
                continue
            if u_is_ax:
                ax_c = fr.u_to_model(g.center.x)
                rad_c = fr.v_to_model(g.center.y)
            else:
                ax_c = fr.v_to_model(g.center.y)
                rad_c = fr.u_to_model(g.center.x)
            if abs(ax_c - x_end) > FILLET_CX_TOL:
                continue
            r_meas = abs(rad_c - c_ax)
            if abs(r_meas + R - rn) <= FILLET_RTOL:
                c_r = rn - R            # 凸：圆心在半径低侧（原行为）
            elif abs(r_meas - R - rn) <= FILLET_RTOL:
                c_r = rn + R            # 凹：圆心在半径高侧（YZYX 端块凹填角）
            else:
                continue
            # 两端点 (轴向, 到轴垂距)
            ok = False
            for ang in (g.start_angle, g.end_angle):
                if u_is_ax:
                    px = fr.u_to_model(g.center.x + R * math.cos(ang))
                    py = fr.v_to_model(g.center.y + R * math.sin(ang))
                else:
                    px = fr.v_to_model(g.center.y + R * math.sin(ang))
                    py = fr.u_to_model(g.center.x + R * math.cos(ang))
                dd_ax, dd_rad = px, abs(py - c_ax)
                far = ax_c - R if west else ax_c + R
                if (abs(dd_ax - x_end) <= FILLET_RTOL
                        and abs(dd_rad - rn) <= FILLET_RTOL):
                    ok = True
                elif (abs(dd_ax - far) <= FILLET_RTOL
                      and abs(dd_rad - c_r) <= FILLET_RTOL):
                    ok = True
            if not ok:
                continue
            # 母线外延点（两型同式，圆心半径位在 c_r）：**西端**从 (远端, c_r)
            # 沿圆弧到 (端点, rn)；**东端**从 (端点, rn) 到 (远端, c_r)——
            # 两端都按"母线行进方向"排（西段在前、东段在后），首末点覆写为
            # 精确值。凸（c_r=rn−R）是原行为；凹（c_r=rn+R）由 YZYX 端块的
            # R15 凹填角引入：弧从外侧高处降到筒壁。
            far = ax_c - R if west else ax_c + R
            pts: list[tuple[float, float]] = []
            for i in range(FILLET_SEGS + 1):
                t = i / FILLET_SEGS
                if west:
                    th = math.pi - t * (math.pi / 2.0)        # 凸：180° → 90°
                    if c_r > rn:
                        th = math.pi + t * (math.pi / 2.0)    # 凹：180° → 270°
                else:
                    th = math.pi / 2.0 - t * (math.pi / 2.0)  # 凸：90° → 0°
                    if c_r > rn:
                        th = 1.5 * math.pi + t * (math.pi / 2.0)  # 凹：270° → 360°
                pts.append((ax_c + R * math.cos(th), c_r + R * math.sin(th)))
            if west:
                pts[0] = (far, c_r)
                pts[-1] = (x_end, rn)
            else:
                pts[0] = (x_end, rn)
                pts[-1] = (far, c_r)
            return _Cap(R, pts, h)
    return None


# ---------------------------------------------------------------------------
# 4) 检测主入口
# ---------------------------------------------------------------------------

def detect_axis_revolve(d: Drawing, corr: CorrespondenceResult,
                        rep: RecognizeReport) -> list[Feature]:
    """端视短弧簇 × 子午视图轴向线 ⇒ REVOLVE 特征列表（不成立返回空表）。"""
    out: list[Feature] = []
    cands = _axis_candidates(d, corr)
    if not cands:
        return out
    _VEC = {"x": Vector3(1.0, 0.0, 0.0), "y": Vector3(0.0, 1.0, 0.0),
            "z": Vector3(0.0, 0.0, 1.0)}
    for cand in cands:
        dir_name = cand.dir_name
        mframes = [corr.frames[v] for v in sorted(corr.frames)
                   if corr.frames[v].p_axis != dir_name
                   and dir_name in (corr.frames[v].u_axis,
                                    corr.frames[v].v_axis)]
        if not mframes:
            continue
        rep.notes.append(
            f"轴回转：{dir_name} 轴 @({cand.centre.x:.2f},{cand.centre.y:.2f},"
            f"{cand.centre.z:.2f})，端视图 {'/'.join(cand.views)} 的短弧半径 "
            f"{'/'.join(f'{r:g}' for r in cand.radii)} ⇒ 候选回转族")
        for rn in cand.radii:
            if rn < AXIS_R_TOL:
                continue
            segs_by_view: dict[str, list[tuple[float, float]]] = {}
            ev_lines: list[str] = []
            for fr in mframes:
                segs, ev = _span_scan(d, fr, dir_name, cand.centre, rn)
                if segs:
                    segs_by_view[fr.view_id] = segs
                    ev_lines.extend(ev)
            if not segs_by_view:
                rep.notes.append(
                    f"轴回转：r{rn:g} 没有任何子午视图的轴向线 ⇒ 跳过")
                continue
            spans = _cross_view_spans(segs_by_view)
            if not spans:
                rep.notes.append(
                    f"轴回转：r{rn:g} 的多视图 span 交空 ⇒ 放弃（不猜哪边对）")
                continue
            arc_ev: list[str] = []
            # 端视图中该半径短弧组的句柄（证据）
            for fr0 in (corr.frames[v] for v in cand.views
                        if v in corr.frames):
                for (cx, cy, r), items in _short_arc_groups(d, fr0).items():
                    if abs(r - rn) <= RADIUS_TOL:
                        arc_ev.extend(h for h, _ in items)
            for x0, x1 in spans:
                if x1 - x0 < MIN_SEG:
                    continue
                west = _end_cap(d, mframes, dir_name, cand.centre, x0, rn, True)
                east = _end_cap(d, mframes, dir_name, cand.centre, x1, rn, False)
                pts: list[tuple[float, float]] = \
                    list(west.pts) if west else [(x0, rn)]
                if east:
                    # east.pts[0] = (x1, rn)：连同它一起接上——(x0,rn)→(x1,rn)
                    # 就是顶线直段（2026-10-17 实测：丢掉它就搭对角斜线，
                    # 且自交的母线让 MakeRevol 出无效体）
                    pts.extend(east.pts)
                else:
                    pts.append((x1, rn))
                ev_t = tuple(dict.fromkeys(
                    arc_ev + ev_lines
                    + ([west.handle] if west else [])
                    + ([east.handle] if east else [])))
                f = Feature(
                    id=FeatureId(0),
                    type=Claim(
                        FeatureType.REVOLVE,
                        "axis_revolve:end_view_short_arcs+section_span",
                        Tier.PROJECTION, ev_t),
                    params={
                        "dir": mk_claim(dir_name,
                                        "axis_revolve:short_arc_cluster",
                                        Tier.PROJECTION, ev_t),
                        "angle_deg": mk_claim(
                            180.0, "axis_revolve:half_toward_material",
                            Tier.CONVENTION, ev_t),
                        "radius_profile": mk_claim(
                            pts, "axis_revolve:axial_span_scan",
                            Tier.PROJECTION, ev_t),
                        "origin": mk_claim(cand.centre,
                                           "axis_revolve:short_arc_center",
                                           Tier.PROJECTION, ev_t),
                    },
                    axis=Claim(Axis3(cand.centre, _VEC[dir_name]),
                               "axis_revolve:short_arc_cluster",
                               Tier.PROJECTION, ev_t),
                    placement=Claim(cand.centre,
                                    "axis_revolve:short_arc_cluster",
                                    Tier.PROJECTION, ev_t),
                    source_view=mframes[0].view_id,
                    evidence=list(ev_t),
                )
                out.append(f)
                cap_note = ""
                if west or east:
                    cap_note = (f"，端部圆角 R"
                                f"{west.radius if west else east.radius:g}")
                rep.notes.append(
                    f"轴回转：r{rn:g} 段 [{x0:.2f},{x1:.2f}]（{x1 - x0:.2f}mm，"
                    f"{len(pts)} 点母线{cap_note}）")
    return out


# ---------------------------------------------------------------------------
# 5) 剖面边界补扫：子午段 × HATCH 材料双探针 ⇒ 表外半径的 REVOLVE / HOLE
# ---------------------------------------------------------------------------

#: 材料双探针的径向偏移（mm）——大于出图线宽/HATCH 边界的抖动，小于 YZYX
#: 最薄壁（端块筒壁 ~12.5、盘区壁 ~24）。
BORE_PROBE = 1.5
#: 同几何段合并容差：半径 / 端点（mm）。
BORE_MERGE_R = 0.05
BORE_MERGE_X = 0.1


def _used_handles(part) -> set[str]:
    """全树已消费的原图元 handle 本体（evidence ∪ 参数/轴 Claim 的证据）。

    实测口径（YZYX 2026-10-17）：证据里存的都是**裸 handle**（``7C4``/``7CF``），
    无 ``#序号`` 形态——对两侧都做 ``split("#")[0]`` 因此安全；HATCH 边界
    （``7BD#32`` 这类）从未进过任何特征的证据，不会误伤整圈边界。
    """
    used: set[str] = set()
    for f in part.features:
        for h in f.evidence or ():
            used.add(str(h).split("#")[0])
        claims = list(f.params.values())
        if f.axis is not None:
            claims.append(f.axis)
        for c in claims:
            for h in (getattr(c, "evidence", None) or ()):
                used.add(str(h).split("#")[0])
    return used


@dataclass(frozen=True)
class _BoreSeg:
    """子午段（同几何合并后）：半径 + 端点 + 中点径向坐标 + 句柄。

    ``x0/x1`` 与 ``ax_probe`` 都是**沿轴绝对坐标**（t 口径，与发射器共用——
    候选轴的轴向分量恒 0，t 与图元分量值逐位相等）；``rad`` 是段中点的
    径向分量值（带符号，判段在轴的哪侧）。
    """

    r: float
    x0: float
    x1: float
    ax_probe: float
    rad: float
    handles: tuple[str, ...]


def _meridian_segments(d: Drawing, fr: ViewFrame, dir_name: str,
                       centre: Point3) -> list[_BoreSeg]:
    """子午视图的 ∥轴段 → 合并表（**不滤角色**；同几何归并）。

    不滤角色的理由与 `_end_cap` 同：YZYX 端块的筒壁与凹填角弧被绘图误设成
    粗实线层 + CENTER2（role=axis），几何上却是真轮廓——过滤交给材料探针
    （两侧同态的标注/中心线段自然出局）。归并只并"同一条线的两次画法"
    （r 与两端点都在容差内），**不做相交合并**——那会把一条全长可见线
    搭进 HATCH 边界的子段，吞掉段自身的证据。
    """
    comp = {"x": lambda p: p.x, "y": lambda p: p.y, "z": lambda p: p.z}
    gu, gv = comp[fr.u_axis], comp[fr.v_axis]
    u_is_ax = fr.u_axis == dir_name
    groups: list[dict] = []
    for ln in _axial_lines(d, fr, dir_name, centre):
        if ln.r < AXIS_R_TOL:
            continue
        lo, hi = min(ln.t0, ln.t1), max(ln.t0, ln.t1)
        for g in groups:
            if (abs(g["r"] - ln.r) <= BORE_MERGE_R
                    and abs(g["x0"] - lo) <= BORE_MERGE_X
                    and abs(g["x1"] - hi) <= BORE_MERGE_X):
                g["handles"].append(ln.handle)
                break
        else:
            if u_is_ax:
                ax_probe = 0.5 * (gu(ln.p0) + gu(ln.p1))
                rad = 0.5 * (gv(ln.p0) + gv(ln.p1))
            else:
                ax_probe = 0.5 * (gv(ln.p0) + gv(ln.p1))
                rad = 0.5 * (gu(ln.p0) + gu(ln.p1))
            # r 取到图纸精度（4 位）：垂距的浮点尾（48.24999999999909）会让
            # apply_prior 的标准值精化把旧值挂进 alternatives ⇒ is_settled
            # 假 ⇒ "特征歧义未消解"拦路（实测 #44）。三个同型孔里只有尾差
            # 最脏的那个被报，正是这个机理。
            groups.append({"r": round(ln.r, 4), "x0": lo, "x1": hi,
                           "ax_probe": ax_probe, "rad": rad,
                           "handles": [ln.handle]})
    return [_BoreSeg(g["r"], g["x0"], g["x1"], g["ax_probe"], g["rad"],
                     tuple(dict.fromkeys(g["handles"]))) for g in groups]


def _rad_point(fr: ViewFrame, dir_name: str, ax_val: float,
               rad_val: float) -> Point2:
    """(沿轴坐标, 径向坐标) → material_map 口径的 Point2（u 分量在前）。"""
    if fr.u_axis == dir_name:
        return Point2(ax_val, rad_val)
    return Point2(rad_val, ax_val)


def _material_flip(mat, fr: ViewFrame, dir_name: str, seg: _BoreSeg,
                   c_rad: float) -> str | None:
    """段两侧 ±BORE_PROBE 的材料翻转：内侧材料 ⇒ "add"、外侧材料 ⇒ "cut"。

    内侧 = 朝轴心（小 r）侧。两侧同态（都空 = 腔区标注残留；都实 =
    HATCH 覆盖外的内部段）返回 None——不是边界，调用方跳过。
    """
    sgn = 1.0 if seg.rad >= c_rad else -1.0
    in_mat = mat(_rad_point(fr, dir_name, seg.ax_probe, seg.rad - sgn * BORE_PROBE))
    out_mat = mat(_rad_point(fr, dir_name, seg.ax_probe, seg.rad + sgn * BORE_PROBE))
    if in_mat and not out_mat:
        return "add"
    if out_mat and not in_mat:
        return "cut"
    return None


def _dedup_rows(rows: list[tuple]) -> list[tuple]:
    """跨帧同几何合并（同一候选轴内：半径/端点容差内取首帧为代表）。"""
    out: list[tuple] = []
    for row in rows:
        for o in out:
            if (o[0] is row[0]
                    and abs(o[2].r - row[2].r) <= BORE_MERGE_R
                    and abs(o[2].x0 - row[2].x0) <= BORE_MERGE_X
                    and abs(o[2].x1 - row[2].x1) <= BORE_MERGE_X):
                break
        else:
            out.append(row)
    return out


def _revolve_covers(part, rn: float) -> list[tuple[float, float]]:
    """全树 REVOLVE 母线里 r≈rn 的**水平段**区间（该半径已被表过的实际覆盖）。

    对"半径段是否已被旧路表达"只认**已发射的几何**——旧路 visible span 是
    "这条线画到哪"（7C4 全长 [−166.5,−0.5]），拿它当覆盖会把从未建过的区段
    （r145 [−46.5,−26.5]）也圈进去；#12 的实际母线只在 [−166.5,−146.5]。
    每段现算（不缓存）——本次发射的新母线也进覆盖表，顺带防同半径重复。
    """
    out: list[tuple[float, float]] = []
    for f in part.features:
        if f.type.value != FeatureType.REVOLVE.value:
            continue
        c = f.params.get("radius_profile")
        if c is None:
            continue
        prof = c.value
        for (t0, r0), (t1, r1) in zip(prof, prof[1:]):
            if abs(r0 - rn) <= RADIUS_TOL and abs(r1 - rn) <= RADIUS_TOL:
                out.append((min(t0, t1), max(t0, t1)))
    return out


def _overlaps_emitted(emitted: list[tuple[float, float, float]],
                      r: float, x0: float, x1: float) -> bool:
    for r0, a0, a1 in emitted:
        if abs(r0 - r) > BORE_MERGE_R:
            continue
        ov = min(a1, x1) - max(a0, x0)
        if ov > 0.5 * min(a1 - a0, x1 - x0) - 1e-9:
            return True
    return False


BORE_SUPPORT_FRAC = 0.5


def _non_section_support(d: Drawing, corr: CorrespondenceResult,
                         mats: dict, cand, dir_name: str, seg: _BoreSeg,
                         cache: dict) -> bool:
    """add 段的"非剖面视图"可见线支持：≥1 个非剖面子午帧的 visible span
    覆盖段长 50% 以上，才信"该段绕轴回转成实体"。

    剖面视图里的一条"水平 HATCH 边界线"可以同时是**后方可见轮廓**（窗口区
    对面的筒壁）或**平顶实体的顶面轮廓**在切面上的投影——与本视图的
    "回转母线"同图同形。YZYX 实锤（v15a 截面网格）：r145 [2604.3,2624.3]
    与 r140 [2629.3,2645.3] 两段在单剖面视图里材料探针全过，但真值该处
    只有半径 ≈70 的塔帽，发的 r145/r140 实心回转是过发（俯视"多"58 段）。
    真回转段的半径在正交视图（俯视 V3 等，无 HATCH）里也留有可见轮廓线：
    r145 盘 [2484.3,2504.3] 在 V1+V3 都有，r107.5 筒在 V3 有。
    """
    for vid in sorted(corr.frames):
        fr = corr.frames[vid]
        if fr.p_axis == dir_name or dir_name not in (fr.u_axis, fr.v_axis):
            continue
        if (dir_name, vid) in mats:
            continue                        # 剖面视图（有 HATCH）不算数
        ck = (vid, round(seg.r, 2))
        if ck not in cache:
            segs2, _ = _span_scan(d, fr, dir_name, cand.centre, seg.r)
            cache[ck] = segs2
        ov = sum(max(0.0, min(b1, seg.x1) - max(b0, seg.x0))
                 for b0, b1 in cache[ck])
        if ov >= BORE_SUPPORT_FRAC * (seg.x1 - seg.x0):
            return True
    return False


def axis_bore_scan(d: Drawing, corr: CorrespondenceResult, part,
                   rep: RecognizeReport) -> int:
    """剖面边界补扫：子午段 × HATCH 材料双探针 ⇒ 表外半径的 REVOLVE / HOLE。

    ``detect_axis_revolve`` 的半径表来自**端视短弧簇**——右端块的 Ø160 腔 /
    筒 / 凹填角在端视图里是画满（或半剖省笔）的圆，进不了短弧表；它们只在
    剖面视图（V1）以「轴向线 × HATCH 材料边界」存在。本函数不再依赖端视弧：

    1. 对每个候选轴的全部子午帧枚举 ∥轴段（不滤角色，见 `_meridian_segments`），
       跨帧同几何合并；
    2. 排除三道：段句柄已被任意既有特征消费（塔腔冠 r177.5 在 POCKET 里）；
       半径落表且段在旧路 `_span_scan` 证据里、或落在旧路 span 区间内
       （r145 的 HATCH 边界子段 = 已被 #12 表达的同一段）；
    3. 材料双探针定极性：内侧材料 ⇒ **add**（段是外轮廓 ⇒ REVOLVE 母线，
       端部复用 `_end_cap` 的凹凸帽；再经**非剖面视图支持门**——剖面
       HATCH 边界水平线可能只是"后方可见轮廓/平顶实体顶面"的投影，须
       正交视图的可见线佐证，见 `_non_section_support`）；外侧材料 ⇒
       **cut**（段是内壁 ⇒ HOLE，孔口取"沿轴向外 2mm 处轴心为空"的那端，
       depth = span，through 按 CONVENTION=False 钉死——图上有孔底轮廓线，
       不许 `derive_through` 拿基体厚度把它改判成通孔）。
    """
    cands = _axis_candidates(d, corr)
    if not cands:
        return 0
    _VEC = {"x": Vector3(1.0, 0.0, 0.0), "y": Vector3(0.0, 1.0, 0.0),
            "z": Vector3(0.0, 0.0, 1.0)}
    used = _used_handles(part)
    rows: list[tuple] = []
    mats: dict[tuple, tuple] = {}
    mfr_by_dir: dict[str, list[ViewFrame]] = {}
    for cand in cands:
        dir_name = cand.dir_name
        mframes = [corr.frames[v] for v in sorted(corr.frames)
                   if corr.frames[v].p_axis != dir_name
                   and dir_name in (corr.frames[v].u_axis,
                                    corr.frames[v].v_axis)]
        mfr_by_dir[dir_name] = mframes
        for fr in mframes:
            view = next((v for v in d.views if v.id == fr.view_id), None)
            if view is None:
                continue
            mat = _material_map(d, fr, view.bbox)
            if not getattr(mat, "has_hatch", False):
                continue                    # 无剖面线的视图不打材料
            c_rad = {"x": cand.centre.x, "y": cand.centre.y,
                     "z": cand.centre.z}[fr.v_axis if fr.u_axis == dir_name
                                         else fr.u_axis]
            mats[(dir_name, fr.view_id)] = (mat, c_rad)
            for seg in _meridian_segments(d, fr, dir_name, cand.centre):
                rows.append((cand, fr, seg))
    if not rows:
        return 0
    rows = _dedup_rows(rows)
    emitted: list[tuple[float, float, float]] = []
    old_ev: dict[tuple, set] = {}
    sup_cache: dict[tuple, list] = {}
    n_out = 0
    for cand, fr, seg in rows:
        dir_name = cand.dir_name
        if seg.x1 - seg.x0 < MIN_SEG:
            continue
        if _overlaps_emitted(emitted, seg.r, seg.x0, seg.x1):
            continue
        mat, c_rad = mats[(dir_name, fr.view_id)]
        body = {h.split("#")[0] for h in seg.handles}
        if body & used:
            rep.notes.append(
                f"剖面补扫：r{seg.r:g} [{seg.x0:.2f},{seg.x1:.2f}] 已被既有特征"
                f"用作证据 ⇒ 跳过")
            continue
        rn_tab = next((t for t in cand.radii
                       if abs(t - seg.r) <= RADIUS_TOL), None)
        if rn_tab is not None:
            ck = (dir_name, fr.view_id, rn_tab)
            if ck not in old_ev:
                _, ev_old = _span_scan(d, fr, dir_name, cand.centre, rn_tab)
                old_ev[ck] = {str(h).split("#")[0] for h in ev_old}
            if body & old_ev[ck]:
                rep.notes.append(
                    f"剖面补扫：r{seg.r:g} [{seg.x0:.2f},{seg.x1:.2f}] 旧路可见段"
                    f"已表达 ⇒ 跳过")
                continue
            if any(b0 - BORE_MERGE_X <= seg.x0 and seg.x1 <= b1 + BORE_MERGE_X
                   for b0, b1 in _revolve_covers(part, rn_tab)):
                rep.notes.append(
                    f"剖面补扫：r{seg.r:g} [{seg.x0:.2f},{seg.x1:.2f}] 已被 "
                    f"r{rn_tab:g} 回转母线覆盖 ⇒ 跳过")
                continue
        pol = _material_flip(mat, fr, dir_name, seg, c_rad)
        if pol is None:
            continue
        ev_t = tuple(seg.handles)
        if pol == "add":
            if not _non_section_support(d, corr, mats, cand, dir_name, seg,
                                        sup_cache):
                rep.notes.append(
                    f"剖面补扫：r{seg.r:g} [{seg.x0:.2f},{seg.x1:.2f}] 无非剖面"
                    f"视图可见线支持 ⇒ 拒发（HATCH 边界可能只是后方可见轮廓/"
                    f"顶面轮廓的投影）")
                continue
            mframes = mfr_by_dir[dir_name]
            west = _end_cap(d, mframes, dir_name, cand.centre,
                            seg.x0, seg.r, True)
            east = _end_cap(d, mframes, dir_name, cand.centre,
                            seg.x1, seg.r, False)
            pts: list[tuple[float, float]] = \
                list(west.pts) if west else [(seg.x0, seg.r)]
            if east:
                pts.extend(east.pts)
            else:
                pts.append((seg.x1, seg.r))
            ev_t = tuple(dict.fromkeys(
                seg.handles
                + ((west.handle,) if west else ())
                + ((east.handle,) if east else ())))
            f = Feature(
                id=FeatureId(-1),
                type=Claim(FeatureType.REVOLVE,
                           "axis_bore:section_material_side",
                           Tier.PROJECTION, ev_t),
                params={
                    "dir": mk_claim(dir_name, "axis_bore:section_material_side",
                                    Tier.PROJECTION, ev_t),
                    "angle_deg": mk_claim(
                        180.0, "axis_bore:half_toward_material",
                        Tier.CONVENTION, ev_t),
                    "radius_profile": mk_claim(
                        pts, "axis_bore:material_side_flip",
                        Tier.PROJECTION, ev_t),
                    "origin": mk_claim(cand.centre,
                                       "axis_bore:short_arc_cluster",
                                       Tier.PROJECTION, ev_t),
                },
                axis=Claim(Axis3(cand.centre, _VEC[dir_name]),
                           "axis_bore:short_arc_cluster",
                           Tier.PROJECTION, ev_t),
                placement=Claim(cand.centre, "axis_bore:short_arc_cluster",
                                Tier.PROJECTION, ev_t),
                source_view=fr.view_id,
                evidence=list(ev_t),
            )
            f.id = part.next_id()
            part.add(f)
            emitted.append((seg.r, seg.x0, seg.x1))
            n_out += 1
            cap_note = ""
            if west or east:
                cap_note = (f"，端部圆角 R"
                            f"{west.radius if west else east.radius:g}")
            rep.notes.append(
                f"剖面补扫：r{seg.r:g} [{seg.x0:.2f},{seg.x1:.2f}] 外侧空 ⇒ "
                f"REVOLVE 母线（{len(pts)} 点{cap_note}）")
            continue
        # cut：段是内壁 ⇒ 钻 HOLE。孔口 = 沿轴向外 2mm 处轴心为空的那端
        # （端面外/已切穿的腔都是空；孔底一侧轴心上是材料）。
        west_open = not mat(_rad_point(fr, dir_name, seg.x0 - 2.0, c_rad))
        east_open = not mat(_rad_point(fr, dir_name, seg.x1 + 2.0, c_rad))
        d_neg = east_open and not west_open
        mouth = seg.x1 if d_neg else seg.x0
        c_ax = {"x": cand.centre.x, "y": cand.centre.y,
                "z": cand.centre.z}[dir_name]
        t0 = (mouth - c_ax) * (-1.0 if d_neg else 1.0)
        v0 = _VEC[dir_name]
        vec = Vector3(-v0.x, -v0.y, -v0.z) if d_neg else v0
        f = Feature(
            id=FeatureId(-1),
            type=Claim(FeatureType.HOLE,
                       "axis_bore:section_material_side",
                       Tier.PROJECTION, ev_t),
            params={
                "radius": mk_claim(seg.r, "axis_bore:material_side_flip",
                                   Tier.PROJECTION, ev_t),
                "through": mk_claim(
                    False, "axis_bore:section_profile_has_bottom",
                    Tier.CONVENTION, ev_t),
                "depth": mk_claim(seg.x1 - seg.x0, "axis_bore:section_span",
                                  Tier.PROJECTION, ev_t),
                "axial_at": mk_claim(t0, "axis_bore:material_side_flip",
                                     Tier.PROJECTION, ev_t),
                "dir": mk_claim(dir_name, "axis_bore:section_material_side",
                                Tier.PROJECTION, ev_t),
                "origin": mk_claim(cand.centre, "axis_bore:short_arc_cluster",
                                   Tier.PROJECTION, ev_t),
            },
            axis=Claim(Axis3(cand.centre, vec), "axis_bore:short_arc_cluster",
                       Tier.PROJECTION, ev_t),
            placement=Claim(cand.centre, "axis_bore:short_arc_cluster",
                            Tier.PROJECTION, ev_t),
            source_view=fr.view_id,
            evidence=list(ev_t),
        )
        f.id = part.next_id()
        part.add(f)
        emitted.append((seg.r, seg.x0, seg.x1))
        n_out += 1
        rep.notes.append(
            f"剖面补扫：r{seg.r:g} [{seg.x0:.2f},{seg.x1:.2f}] 内侧空 ⇒ "
            f"HOLE Ø{2.0 * seg.r:g} 深 {seg.x1 - seg.x0:.2f}"
            f"（孔口在{'东' if d_neg else '西'}端）")
    return n_out
