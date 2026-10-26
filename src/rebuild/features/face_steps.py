# -*- coding: utf-8 -*-
"""端面台阶裁决 —— 基体深度 / 端面凸台 / 槽 vs 凸台。

## 为什么

基体长度取自「所有视图沿拉伸方向的跨度并集」（``projection:view_bounds``），
它只保证**包住**零件，不保证是零件的主面。铸件/机加工件的端面常有 1~2mm 的
凸台（凸出主面）与沉台/凹面（凹入主面）：它们不该被基体拉满。剖面图的 HATCH
直接给出端面沿拉伸轴的位置随另一轴的变化 —— 哪一段是主面、哪一段是凸台、
哪一段是沉台，是**材料读数**，不是猜测。

实测 20180425 气缸前盖 A—A：基体按并集 bbox 拉满 33（69.83..102.83），而
剖切面处的主材料是 32（69.83..101.83）。右端 Ø75×1 凸台（102.83）、左端
Ø70×1 沉台（70.83）—— A—A 截面剩下的多料 87% 就是这两个 1mm。同一张图里
r35 圆在正交视图里被读成凸台（俯视/正视同形，§3 原则二），剖面线说死它是
**沉台的边**：圆区间内的材料比圆外少 1mm。

## 判据（圆边界内外对账）

不再按"区域聚类"猜主面 —— 主面就在**已知圆的边界两侧**，直接读：

1. 对每个带 HATCH、剖切位置唯一（``section_bore._cut_plane_pos``）的剖视，
   若基体拉伸轴 ``d`` 落在剖切面内（``d ∈ (u_axis, v_axis)`` 且
   ``p_axis ≠ d``），沿剖面另一条轴 ``t`` 逐列取材料沿 ``d`` 的外包区间
   （包住孔 —— 端面只看外包）。
2. 候选圆 = 剖切面内的已知轴线（``_axes``：圆柱提示 / 已建特征）× 半径
   （可见圆提示的半径，或直径标注读出的半径）。直径标注须过几何三条：
   两点沿 t 的间距 = 值、值 = 2r、中点在轴线上。
3. 对每个候选圆、每条端面（lo / hi），在**圆边界内外各取 0.5mm 的窄窗**：
   - 内窗 ``|t−c| ∈ [r−0.85, r−0.15]``，外窗 ``[r+0.15, r+0.85]``；
   - 窗内样本必须局部同高（跨度 ≤ ``LEVEL_SPREAD``），否则说明窗里还夹着
     别的台阶边界 ⇒ 这个圆在此方向不作证（这正是"小孔的采样带恰好跨过
     大圆台阶"这类假阳性的出口：r3.5 孔的窗会同时看到 70.83 与 69.83）；
   - 采样值吸附到**本视图 HATCH 边界的精确直线**（``material.hatch_lines``
     里方向垂直于 ``d`` 的线段），吸附不到就放弃这一侧（不猜）。
4. 层差 ``step``：lo 侧 = 内 − 外，hi 侧 = 外 − 内。**正 = 沉台（凹入
   主面），负 = 凸台（凸出主面）**，两侧同一符号约定。``|step|`` 须在
   ``[FACE_STEP_MIN, FACE_STEP_MAX]`` 内 —— 更大的是结构腔体（不是端面台阶）。
5. 圆外的那个精确层位就是**主面**。同一侧的所有作证圆必须给出同一个主面；
   不一致 ⇒ 说明这一侧不是平面端面（或读错了），整条不接。
6. 基体两端改到主面；每个作证圆发一个特征：
   - 沉台 ⇒ HOLE（平底，``axial_at`` = 主面，朝材料内钻 ``step``）；
   - 凸台 ⇒ BOSS（``axial_at`` = 主面，朝外长 ``|step|``）。
   同一张圆边不能既当凸台又当沉台 ⇒ 返回已用提示，调用方并入
   ``cylinder_features`` 的 skip。

## 门槛与反例

- ``rep.zones`` 非空（高度分解已把基体降高、分区抬升）时整条不接：那里的
  "台阶"是结构分区，同一个事实不能有两个表达（bracket 两条图纸）。
- 基体是回转体（无 ``dir`` 参数）或带 ``taper_scale`` 时不接：它的两端
  不是"端面"。
- 主面读数与并集 bbox 的差超过 ``FACE_STEP_MAX`` ⇒ 不是端面台阶（是结构），
  整体放弃。
- 多个剖面给出的主面必须一致；不一致整体放弃 —— 同一个基体深度不能有
  两个读数。
- 没有可见圆/直径标注作证的半径不建（§3 原则二）。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from ..model.claim import Claim, Tier
from ..model.feature_tree import Feature, FeatureType
from ..model.geom import Axis3, Point3, Vector3
from ..model.ids import FeatureId
from .material import hatch_lines
from .section_bore import (DIM_CENTER_TOL, DIM_TOL, _cut_plane_pos, _scan,
                           dims_geom)

if TYPE_CHECKING:
    from ..evidence.model import Drawing
    from ..views.correspondence import CorrespondenceResult, CylinderHint
    from .recognizer import RecognizeReport

#: 同一层位的吸附后比对容差（精确边界线之间最少相距 1mm，故 0.4 安全）
FACE_TOL = 0.4
#: 端面台阶的最大高度 —— 更大的是结构分区（height_zones 的抬升/切除区）
FACE_STEP_MAX = 3.0
#: 台阶的最小高度（小于它是剖面线/栅格噪声）
FACE_STEP_MIN = 0.3
#: 已知轴线的中心匹配容差（栅格量化 + 图纸坐标误差）
AXIS_MATCH = 0.6
#: 圆半径与圆柱提示半径的匹配容差
RADIUS_TOL = 0.6
#: 候选圆的最小半径（更小的"圆"是孔口/标注残留，不是端面台阶）
MIN_RADIUS = 1.5
#: 窄窗内样本的允许跨度（GRID=0.3 的量化抖动，再留一点余量）
LEVEL_SPREAD = 0.5
#: 采样层位 → 精确 HATCH 边界层的吸附容差（栅格量化最大观测 0.30mm）
SNAP_TOL = 0.5
#: 层位跃变的位置必须落在圆边界上（栅格一个步长的半个 = 0.15mm，留余量）
TRANS_TOL = 0.3
#: 从圆边界向外扫多远找跃变（端面台阶就在边界上，不需要扫太远）
TRANS_WIN = 2.5
#: 跃变两侧取层位的窗口（距跃变的距离，mm）
TRANS_NEAR = 1.0
#: 窗口内最少样本数（GRID=0.3 时 0.7mm 窗口约 2~3 行）
WIN_MIN_ROWS = 2

_DIRS = {"x": Vector3(1.0, 0.0, 0.0),
         "y": Vector3(0.0, 1.0, 0.0),
         "z": Vector3(0.0, 0.0, 1.0)}


@dataclass
class _Sample:
    """沿剖面另一条轴 t 的一列材料外包区间。"""

    t: float          # 模型坐标（t 轴）
    lo: float         # 模型坐标（拉伸轴）
    hi: float


@dataclass
class _Axis:
    """剖面内的一条已知轴线（圆柱提示或已建特征）。"""

    center_t: float
    origin: Point3
    hint: "CylinderHint | None" = None
    radius: float | None = None
    evidence: tuple[str, ...] = ()


@dataclass
class _Cand:
    """一个候选圆（轴线 × 半径 × 依据）。"""

    center_t: float
    radius: float
    proof: str
    evidence: tuple[str, ...] = ()
    hint: "CylinderHint | None" = None


@dataclass
class _Witness:
    """一个圆在某条端面上读出的台阶。"""

    side: str            # "lo" / "hi"
    center_t: float
    radius: float
    main: float          # 圆外的精确层位（= 主面）
    step: float          # 正 = 沉台，负 = 凸台
    proof: str
    evidence: tuple[str, ...] = ()
    hint: "CylinderHint | None" = None
    axis_origin: Point3 | None = None
    view_id: str = ""


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------

def face_steps(d: "Drawing", corr: "CorrespondenceResult", part,
               rep: "RecognizeReport", mats: dict,
               conv=None) -> tuple[list[Feature], list["CylinderHint"]]:
    """剖面材料 ⇒ 端面台阶（基体深度调整 + 凸台/沉台）。

    返回 ``(新特征, 已被表达的圆柱提示)`` —— 后者由调用方并入
    ``cylinder_features`` 的 skip：同一张圆边不能既当凸台又当沉台。
    """
    if rep.zones is not None:
        rep.notes.append(
            "端面台阶：高度分解已把基体降高/分区抬升 ⇒ 端面台阶通道不接"
            "（结构分区与端面台阶不能重复表达）")
        return [], []
    base = next((f for f in part.features
                 if f.type.value == FeatureType.BASE.value), None)
    if base is None or "dir" not in base.params or "taper_scale" in base.params:
        return [], []
    dir_name = base.params["dir"].value
    if not isinstance(dir_name, str) or dir_name not in _DIRS:
        return [], []
    origin = base.params["origin"].value
    length = float(base.params["length"].value)
    b_lo = min(getattr(origin, dir_name), getattr(origin, dir_name) + length)
    b_hi = max(getattr(origin, dir_name), getattr(origin, dir_name) + length)

    witnesses: list[_Witness] = []
    for vid in sorted(mats):
        fr, mm, view = mats[vid]
        if view.bbox is None or not getattr(mm, "has_hatch", False):
            continue
        if dir_name not in (fr.u_axis, fr.v_axis):
            continue                     # 该剖面不含拉伸轴
        if fr.p_axis == dir_name:
            continue
        cut = _cut_plane_pos(d, corr, view, fr)
        if cut is None:
            continue                     # 剖切位置读不出：section_bore 已记账
        got = _read_section(d, corr, conv, part, fr, mm, view, dir_name,
                            cut[0], cut[1], rep)
        witnesses.extend(got)
    if not witnesses:
        return [], []

    main: dict[str, float] = {}
    for side in ("lo", "hi"):
        vals = sorted(w.main for w in witnesses if w.side == side)
        groups: list[list[float]] = []
        for v in vals:
            if groups and v - groups[-1][-1] <= FACE_TOL:
                groups[-1].append(v)
            else:
                groups.append([v])
        if len(groups) > 1:
            rep.notes.append(
                f"端面台阶：{side} 侧读到多个主面 "
                + "、".join(f"{grp[0]:.2f}" for grp in groups)
                + " ⇒ 该侧不是平面端面（或读错了），整条不接")
            return [], []
        if groups:
            main[side] = groups[0][len(groups[0]) // 2]
    if not main:
        return [], []
    dom = (main.get("lo", b_lo), main.get("hi", b_hi))
    if dom[0] >= dom[1]:
        return [], []
    return _apply(witnesses, dom, base, b_lo, b_hi, dir_name, rep)


def _apply(witnesses: list[_Witness], dom: tuple[float, float], base,
           b_lo: float, b_hi: float, dir_name: str, rep) -> tuple:
    """把剖面读数落到特征树（基体两端 + 凸台/沉台）。"""
    dom_lo, dom_hi = dom
    ev_all: tuple[str, ...] = ()
    for w in witnesses:
        ev_all = ev_all + tuple(w.evidence)
    ev_all = tuple(dict.fromkeys(ev_all))
    changed = (abs(dom_lo - b_lo) > FACE_STEP_MIN
               or abs(dom_hi - b_hi) > FACE_STEP_MIN)
    if changed:
        diff = abs(dom_lo - b_lo) + abs(dom_hi - b_hi)
        if diff > FACE_STEP_MAX + FACE_STEP_MIN:
            rep.notes.append(
                f"端面台阶：剖面主面 {dom_lo:.2f}..{dom_hi:.2f} 与基体 "
                f"{b_lo:.2f}..{b_hi:.2f} 相差 {diff:.2f}mm > "
                f"{FACE_STEP_MAX:g}mm ⇒ 不是端面台阶（是结构），不接")
            return [], []
        if not ev_all:
            rep.notes.append(
                "端面台阶：主面读数没有可引的依据（轴线/标注全缺）⇒ 不改基体")
            return [], []
        origin = base.params["origin"].value
        coords = {"x": origin.x, "y": origin.y, "z": origin.z}
        coords[dir_name] = dom_lo
        new_o = Point3(coords["x"], coords["y"], coords["z"])
        base.params["origin"] = Claim(new_o, "section:face_step_span",
                                      Tier.PROJECTION, ev_all)
        base.params["length"] = Claim(dom_hi - dom_lo, "section:face_step_span",
                                      Tier.PROJECTION, ev_all)
        base.placement = Claim(new_o, "section:face_step_span",
                               Tier.PROJECTION, ev_all)
        rep.notes.append(
            f"端面台阶：基体深度由剖面材料裁决 {b_lo:.2f}..{b_hi:.2f} → "
            f"{dom_lo:.2f}..{dom_hi:.2f}（原为并集包围盒；依据剖面线，"
            f"{len(witnesses)} 个圆作证）")

    # 同一个圆被多张剖面/两条端面读到 ⇒ 只建一次
    merged: dict[tuple, _Witness] = {}
    for w in witnesses:
        key = (w.side, round(w.main / FACE_TOL),
               round(w.center_t / 0.1), round(w.radius / RADIUS_TOL))
        old = merged.get(key)
        if old is None or (w.proof and not old.proof):
            merged[key] = w

    out: list[Feature] = []
    used: list = []
    for w in merged.values():
        main = dom[0] if w.side == "lo" else dom[1]
        step = abs(w.step)
        if step < FACE_STEP_MIN or step > FACE_STEP_MAX:
            continue
        if not w.proof:
            rep.notes.append(
                f"端面台阶：{w.side} 面位 {w.main:.2f} 的 "
                f"Ø{2 * w.radius:.2f} 圆没有可见圆/直径标注作证 ⇒ 不建（原则二）")
            continue
        ax_pt = w.axis_origin
        r = w.radius
        if ax_pt is None:
            continue
        coords = {"x": ax_pt.x, "y": ax_pt.y, "z": ax_pt.z}
        coords[dir_name] = 0.0
        a_o = Point3(coords["x"], coords["y"], coords["z"])
        # 正 = 沉台（凹入主面），负 = 凸台（凸出主面）。
        # 凸台朝外（lo 侧 −d、hi 侧 +d）；沉台反向（朝材料内）。
        sign = -1.0 if w.side == "lo" else 1.0
        if w.step > 0:
            sign = -sign
        if w.step > 0:
            ftype, meth = FeatureType.HOLE, "section:face_step_recess"
            params = {
                "radius": Claim(r, meth, Tier.PROJECTION, w.evidence),
                "depth": Claim(step, meth + "_depth", Tier.PROJECTION,
                               w.evidence),
                "axial_at": Claim(main, meth + "_span", Tier.PROJECTION,
                                  w.evidence),
            }
            what = "端面沉台"
        else:
            ftype, meth = FeatureType.BOSS, "section:face_step_pad"
            params = {
                "radius": Claim(r, meth, Tier.PROJECTION, w.evidence),
                "height": Claim(step, meth + "_height", Tier.PROJECTION,
                                w.evidence),
                "axial_at": Claim(main, meth + "_span", Tier.PROJECTION,
                                  w.evidence),
            }
            what = "端面凸台"
        direction = _DIRS[dir_name] if sign > 0 else Vector3(
            -_DIRS[dir_name].x, -_DIRS[dir_name].y, -_DIRS[dir_name].z)
        out.append(Feature(
            id=FeatureId(-1),
            type=Claim(ftype, meth, Tier.PROJECTION, w.evidence),
            params=params,
            axis=Claim(Axis3(a_o, direction, None), meth, Tier.PROJECTION,
                       w.evidence),
            placement=Claim(a_o, meth, Tier.PROJECTION, w.evidence),
            source_view=w.view_id,
            evidence=list(w.evidence),
        ))
        if w.hint is not None:
            used.append(w.hint)
        rep.notes.append(
            f"端面台阶：{what} Ø{2 * r:.2f}×{step:.2f} 在 {dir_name}="
            f"{main:.2f}（{w.proof}；主面 {w.main:.2f}）")
    return out, used


# ---------------------------------------------------------------------------
# 单个剖面：材料外包 → 圆边界内外对账
# ---------------------------------------------------------------------------

def _read_section(d, corr, conv, part, fr, mm, view, dir_name,
                  p_axis, p_pos, rep) -> list[_Witness]:
    """一个剖面 → 作证圆列表（读不出就返回空，并记账）。"""
    t_axis, rows = _rows(fr, mm, view.bbox, dir_name)
    if len(rows) < 5:
        rep.notes.append(
            f"端面台阶：{view.id} 的材料列太少（{len(rows)}）⇒ 不裁决")
        return []
    axes = _axes(corr, part, dir_name, p_axis, p_pos, t_axis)
    if not axes:
        rep.notes.append(
            f"端面台阶：{view.id} 的剖切面内没有已知轴线 ⇒ 无法对账，跳过")
        return []
    dims = dims_geom(d, conv, view, fr) if conv is not None else []
    levels = _exact_levels(d, fr, view.bbox, dir_name)
    if not levels:
        rep.notes.append(
            f"端面台阶：{view.id} 的 HATCH 边界没有沿 {dir_name} 的精确层位"
            " ⇒ 采样值无从吸附，跳过")
        return []
    t_is_u = (fr.u_axis == t_axis)
    cands = _candidates(axes, dims, t_is_u)
    got: list[_Witness] = []
    for cd in cands:
        if cd.radius < MIN_RADIUS:
            continue
        for side in ("lo", "hi"):
            found: list[tuple[float, float]] = []   # (main, step)
            for sgn in (1.0, -1.0):
                step_lv = _transition(rows, side, cd.center_t, cd.radius, sgn,
                                      levels)
                if step_lv is None:
                    continue
                in_e, out_e = step_lv
                step = (in_e - out_e) if side == "lo" else (out_e - in_e)
                if not (FACE_STEP_MIN <= abs(step) <= FACE_STEP_MAX):
                    continue
                found.append((out_e, step))
            if not found:
                continue
            if any(abs(m - found[0][0]) > FACE_TOL
                   or abs(s - found[0][1]) > FACE_TOL for m, s in found):
                rep.notes.append(
                    f"端面台阶：{view.id} 的 {side} 侧 Ø{2 * cd.radius:.2f} "
                    f"(c={cd.center_t:.2f}) 两个方向读数不一致 "
                    + "、".join(f"主面 {m:.2f}/台阶 {s:+.2f}" for m, s in found)
                    + " ⇒ 该圆不作证")
                continue
            main, step = found[0]
            got.append(_Witness(side, cd.center_t, cd.radius, main, step,
                                cd.proof, cd.evidence, cd.hint,
                                _axis_point(axes, cd.center_t), view.id))
    return got


def _axis_point(axes: list[_Axis], center_t: float) -> Point3 | None:
    """取该中心对应的轴线原点（各轴在剖切面上共点，取第一个）。"""
    for ax in axes:
        if abs(ax.center_t - center_t) <= AXIS_MATCH:
            return ax.origin
    return None


def _rows(fr, mm, bbox, dir_name: str) -> tuple[str, list[_Sample]]:
    """沿剖面另一条轴逐列取材料沿 ``dir_name`` 的外包区间。"""
    us, vs, mat = _scan(fr, mm, bbox)
    if fr.u_axis == dir_name:
        t_axis, t_of, d_of = fr.v_axis, fr.v_to_model, fr.u_to_model
        t_vals, d_vals = vs, us
        col = lambda k: [mat[i][k] for i in range(len(us))]  # noqa: E731
    else:
        t_axis, t_of, d_of = fr.u_axis, fr.u_to_model, fr.v_to_model
        t_vals, d_vals = us, vs
        col = lambda k: [mat[k][j] for j in range(len(vs))]  # noqa: E731
    rows: list[_Sample] = []
    for k, tv in enumerate(t_vals):
        b = col(k)
        idx = [i for i, x in enumerate(b) if x]
        if not idx:
            continue
        i0, i1 = idx[0], idx[-1]
        a, c = d_of(d_vals[i0]), d_of(d_vals[i1])
        rows.append(_Sample(t_of(tv), min(a, c), max(a, c)))
    rows.sort(key=lambda r: r.t)
    return t_axis, rows


def _axes(corr, part, dir_name: str, p_axis: str, p_pos: float,
          t_axis: str) -> list[_Axis]:
    """剖切面内的已知轴线（圆柱提示优先，含已建特征的轴）。"""
    out: list[_Axis] = []
    for c in corr.cylinders():
        h = c.mapping.value
        a = getattr(h, "axis", None)
        if a is None:
            continue
        if abs(abs(getattr(a.direction, dir_name)) - 1.0) > 1e-6:
            continue
        if abs(getattr(a.origin, p_axis) - p_pos) > AXIS_MATCH:
            continue
        out.append(_Axis(getattr(a.origin, t_axis), a.origin, h, h.radius,
                         tuple(h.evidence)))
    for f in part.features:
        if f.axis is None or f.axis.value is None:
            continue
        a = f.axis.value
        if abs(abs(getattr(a.direction, dir_name)) - 1.0) > 1e-6:
            continue
        if abs(getattr(a.origin, p_axis) - p_pos) > AXIS_MATCH:
            continue
        out.append(_Axis(getattr(a.origin, t_axis), a.origin, None, None,
                         tuple(f.evidence)))
    return out


def _candidates(axes: list[_Axis], dims, t_is_u: bool) -> list[_Cand]:
    """候选圆 = 已知轴线 × 半径（可见圆提示 / 直径标注）。"""
    out: list[_Cand] = []
    for ax in axes:
        if ax.radius is None:
            continue
        out.append(_Cand(ax.center_t, ax.radius,
                         f"可见圆 r{ax.radius:g}", tuple(ax.evidence), ax.hint))
    for val, p1, p2, h in dims:
        q1 = p1[0] if t_is_u else p1[1]
        q2 = p2[0] if t_is_u else p2[1]
        if abs(abs(q2 - q1) - val) > DIM_TOL:
            continue
        mid = (q1 + q2) / 2.0
        for ax in axes:
            if abs(mid - ax.center_t) > DIM_CENTER_TOL:
                continue
            r = val / 2.0
            if r >= MIN_RADIUS:
                out.append(_Cand(ax.center_t, r, f"直径标注 {val:g}",
                                 tuple(ax.evidence) + (h,), None))
            break
    seen: set[tuple] = set()
    uniq: list[_Cand] = []
    for cd in out:
        key = (round(cd.center_t, 2), round(cd.radius, 2))
        if key in seen:
            continue
        seen.add(key)
        uniq.append(cd)
    return uniq


def _exact_levels(d, fr, bbox, dir_name: str) -> list[float]:
    """本视图 HATCH 边界上垂直于 ``dir_name`` 的精确层位。

    ⚠️ ``hatch_lines`` 返回的 ``Point2`` 是 **(u, v) 两个视图轴方向的模型
    坐标**，不是 model 的 x/y/z 字段 —— 必须按 ``fr.u_axis`` 选分量。
    """
    k = 0 if fr.u_axis == dir_name else 1
    vals: list[float] = []
    for ln in hatch_lines(d, fr, bbox):
        a = ln.start.x if k == 0 else ln.start.y
        b = ln.end.x if k == 0 else ln.end.y
        if abs(a - b) > 1e-6:
            continue
        vals.append((a + b) / 2.0)
    return sorted(set(round(v, 6) for v in vals))


def _transition(rows: list[_Sample], side: str, c: float, r: float,
                sgn: float, levels: list[float]):
    """沿 |t−c| 从圆心向外扫过 r，找**落在圆边界上**的层位跃变。

    返回 ``(圆内层位, 圆外层位)``（均已吸附到精确 HATCH 层位）；没有跃变、
    跃变不在边界上、或两侧层位吸附不到 → None。

    为什么必须比对跃变**位置**：小孔的"圆内 vs 圆外"也可能层位不同，但那是
    附近某个大圆的台阶（实测 r3.5 孔与 r35 沉台：跃变在 |t−c|=3.0，孔半径
    3.5 —— 差 0.5 > ``TRANS_TOL``）。只看两窗层差会把大圆的台阶记到小孔头上。
    """
    seq: list[tuple[float, float]] = []
    for x in rows:
        d = sgn * (x.t - c)
        if 0.5 * r <= d <= r + TRANS_WIN:
            seq.append((d, x.lo if side == "lo" else x.hi))
    if len(seq) < 4:
        return None
    seq.sort()
    runs: list[dict] = []
    for d, v in seq:
        if runs and abs(v - runs[-1]["vs"][-1]) <= LEVEL_SPREAD:
            runs[-1]["ds"].append(d)
            runs[-1]["vs"].append(v)
        else:
            runs.append({"ds": [d], "vs": [v]})
    best: tuple[float, float, float] | None = None
    for i in range(len(runs) - 1):
        d_tr = (max(runs[i]["ds"]) + min(runs[i + 1]["ds"])) / 2.0
        delta = abs(_mean(runs[i + 1]["vs"]) - _mean(runs[i]["vs"]))
        if not (FACE_STEP_MIN <= delta <= FACE_STEP_MAX):
            continue
        if abs(d_tr - r) > TRANS_TOL:
            continue
        in_raw = _level_at_d(seq, d_tr - TRANS_NEAR, d_tr - 0.3)
        out_raw = _level_at_d(seq, d_tr + 0.3, d_tr + TRANS_NEAR)
        if in_raw is None or out_raw is None:
            continue
        in_e = _snap(in_raw, levels)
        out_e = _snap(out_raw, levels)
        if in_e is None or out_e is None:
            continue
        cand = (abs(d_tr - r), in_e, out_e)
        if best is None or cand[0] < best[0]:
            best = cand
    if best is None:
        return None
    return best[1], best[2]


def _level_at_d(seq: list[tuple[float, float]], d0: float,
                d1: float) -> float | None:
    """``[d0, d1]``（距圆心的距离窗口，可反向）内的局部同高层位。"""
    lo, hi = (d0, d1) if d0 <= d1 else (d1, d0)
    vals = [v for d, v in seq if lo <= d <= hi]
    if len(vals) < WIN_MIN_ROWS:
        return None
    if max(vals) - min(vals) > LEVEL_SPREAD:
        return None
    vals.sort()
    return vals[len(vals) // 2]


def _mean(vals: list[float]) -> float:
    return sum(vals) / len(vals)


def _snap(v: float, levels: list[float]) -> float | None:
    """把采样层位吸附到最近的精确 HATCH 边界层位。"""
    best = None
    for lv in levels:
        d = abs(lv - v)
        if d <= SNAP_TOL and (best is None or d < best[0]):
            best = (d, lv)
    return None if best is None else best[1]


__all__ = ["face_steps"]
