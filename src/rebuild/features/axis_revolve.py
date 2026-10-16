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
   再聚簇，簇内互异半径 ≥ ``MIN_RADII`` ⇒ 候选轴（轴心 = 圆心过 u/v_to_model
   映射，轴向分量 0——母线 t 因此可用**绝对**图纸坐标，与 `_axial_lines` 同口径）。
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
from ..model.geom2d import Arc2, Circle2
from ..model.ids import FeatureId
from ..views.correspondence import ARC_COVER_MIN, _arc_cover, _profile_arc
from .library import mk_claim
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
            for cl in clusters:
                if (abs(cx - cl["c"][0]) <= CENTER_TOL
                        and abs(cy - cl["c"][1]) <= CENTER_TOL):
                    cl["radii"].add(r)
                    cl["views"].add(vid)
                    break
            else:
                clusters.append({"c": (cx, cy), "radii": {r}, "views": {vid}})
        for cl in clusters:
            if len(cl["radii"]) < MIN_RADII:
                continue
            cx, cy = cl["c"]
            coords = {fr.u_axis: fr.u_to_model(cx),
                      fr.v_axis: fr.v_to_model(cy), fr.p_axis: 0.0}
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
            if e is None or e.kind != Kind.EDGE or e.role.value != Role.VISIBLE:
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
            if abs(r_meas + R - rn) > FILLET_RTOL:
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
                      and abs(dd_rad - (rn - R)) <= FILLET_RTOL):
                    ok = True
            if not ok:
                continue
            # 母线外延点：**西端**从 (远端, rn−R) 沿圆弧到 (端点, rn)；
            # **东端**从 (端点, rn) 到 (远端, rn−R)——两端都按"母线行进方向"
            # 排（西段在前、东段在后），首末点与采样式独立覆写为精确值。
            far = ax_c - R if west else ax_c + R
            pts: list[tuple[float, float]] = []
            for i in range(FILLET_SEGS + 1):
                t = i / FILLET_SEGS
                if west:
                    th = math.pi - t * (math.pi / 2.0)      # 180° → 90°
                else:
                    th = math.pi / 2.0 - t * (math.pi / 2.0)  # 90° → 0°
                pts.append((ax_c + R * math.cos(th),
                            (rn - R) + R * math.sin(th)))
            if west:
                pts[0] = (far, rn - R)
                pts[-1] = (x_end, rn)
            else:
                pts[0] = (x_end, rn)
                pts[-1] = (far, rn - R)
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
