# -*- coding: utf-8 -*-
"""侧轴凸台（挂耳）身上的三处结构 —— 月牙缺口 / 张缝 / 销孔（阶段 7 续）。

## 缺口在哪

高度分解把基体降到"最低公共顶面"之后，**侧轴凸台**（轴 ⟂ 拉伸方向的圆柱，
bracket 挂耳 r12 ∥ y）身上还有三处由它的姿态决定的结构，图纸全画了，但
"基体 + 凸台"两条现有词汇读不出来：

1. **月牙缺口**（``_foot_cut``）—— 挂耳悬在 z∈[12,36]，它下面的俯视轮廓
   区域（条带 − 圆盘）是**空的**（金标准探针 G2：z=6 时该区只有圆盘）。
   基体却把俯视轮廓整片拉到板厚 ⇒ 挂耳底下多出 22mm 厚的假料。刀形 =
   凸台条带（面内 ``c ± r``，轴向跨越两端）**减去**它倚靠的那个材料圆盘
   分区，自板底切到板顶。
2. **张缝**（``_slit_cut``）—— 从中央孔壁通到耳尖的 2mm 缝（夹紧结构）。
   在含凸台轴的视图里它是**一对关于凸台轴向中点对称**的平行线：线的另一向
   跨度给出缝的走向长度，第三向跨度给出缝高（bracket 实测贯穿全高 2..46）。
3. **销孔**（``_pin_holes``）—— 沿凸台轴钻穿的横孔（bracket r3）。读数 =
   在凸台足迹内、关于凸台轴心对称、跨度盖住凸台整个轴向的一对轮廓线，半径
   = 半间距。孔壁虚线被 HLR 可见优先吃掉时它会以"可见剪影"出现，两种画法
   落在同一个判据上。

## 为什么不能只靠 cylinder_features

那一路的输入是**圆**（``CylinderHint``），这三处的图纸依据全是**直线对**；
出图侧 HLR 可见优先去重还会把孔壁虚线吃掉（挂耳 r12 实测只剩 3.00 长的薄壁
缘）。本模块直接读轴平行线段家族（``height_zones.frame_lines``），判据全部
落在"线对 + 对称 + 覆盖面"上。

## 顺序契约（依赖关系是一等公民）

树内排列只是给人看的，**发射顺序由 ``depends_on`` 决定** ——
``library.build_order`` 先按（层号, id）排，POCKET/HOLE(3) 永远落在
BOSS(2) 之后，所以：

- 月牙缺口**切在凸台之前**：先切掉基体的假料，凸台再补回自己的圆柱
  （两刀分离正是"凸台悬空"的表达）。表达方式 = 给凸台挂
  ``f.depends_on.append(foot.id)``，否决层号把二者颠倒的默认序。
  实测教训：只把它插在列表前面不够 —— 发射器照层号排，月牙刀把凸台
  下半（z<24 那截圆柱）整段切光，挂耳少料 2,761。
- 张缝、销孔**切在凸台之后**（切在已经加好的凸台上）——
  ``slit.depends_on.append(f.id)`` / ``pin.depends_on.append(f.id)``。
- 销孔通孔声明必须用 ``Tier.CONVENTION`` —— ``derive_through`` 只不降
  ``> Tier.DERIVED`` 的声明；PROJECTION 会被它按"深度 vs 材料厚度"改写，
  而凸台轴向没有厚度表（会被误判成盲孔）。判据本身是制图性的：轮廓线贯穿
  凸台全轴 = 通孔。

依赖：``..model.*``、``.height_zones``、``.library``、``.recognizer``
（纯数据 + ezdxf/numpy 口径，跑默认 python）。
"""
from __future__ import annotations

import math
from typing import TYPE_CHECKING

from ..model.claim import Claim, Tier
from ..model.feature_tree import Feature, FeatureType, Part
from ..model.geom import Axis3, Point3
from ..model.geom2d import Point2, Profile2, ProfileSeg2
from ..model.ids import FeatureId
from .height_zones import (PPGroup, _coord, _dir_vec, _pp_groups, _sample,
                           frame_lines)
from .library import ir_point, mk_claim
from .recognizer import _PLANE_AXES, _axis_name

if TYPE_CHECKING:
    from ..evidence.dxf_reader import Drawing
    from ..views.correspondence import CorrespondenceResult
    from .recognizer import RecognizeReport

__all__ = ["side_channels"]

#: 线对关于凸台轴心 / 轴向中点的对称容差（mm）
SYM_TOL = 0.30
#: 销孔半壁厚裕度：ρ ≤ r − HOLE_WALL_MIN（贴着凸台轮廓的"线对"不是孔，mm）
HOLE_WALL_MIN = 1.00
#: 最小可信半径（比这还小的线对多半是碎段残差，mm）
MIN_R = 0.50
#: 孔线对必须盖住凸台轴向跨度的比例
HOLE_COVER_MIN = 0.60
#: "两端都够到"的容差（mm）
TOUCH_TOL = 1.00
#: 张缝半宽上限（缝宽 ≤ 2·SLIT_MAX_HALF；再宽就不该走这条读法，mm）
SLIT_MAX_HALF = 2.00
#: 缝轮廓往两侧各胀这么多，避开与真实缝边界共面（mm）
SLIT_GROW = 0.01
#: 缝轮廓的内端再往中央孔方向伸这么多（伸进孔里无害：那儿本来就是空，mm）
SLIT_INNER_RUN = 2.00
#: 月牙缺口轮廓往凸台轴向两端各放这么多（mm）
FOOT_MARGIN = 0.50
#: 轮廓往零件外侧放这么多，保证刀口落在材料外（mm）
PART_MARGIN = 0.20
#: 月牙缺口的触发门限：条带下剪影底高出板底这么多才切（mm）
UNDERCUT_MIN = 0.50

_TAU = 2.0 * math.pi


def _axis_letter(f: Feature) -> str:
    """特征轴向的字母（"y"），无轴 / 轴向读不出返回 ""。"""
    if f.axis is None or f.axis.value is None:
        return ""
    return _axis_name(f.axis.value.direction).lstrip("+−-").lower()


def _ab_signed_area(segs: list[ProfileSeg2]) -> float:
    """采样折线的鞋带面积（符号即环向：正 = 逆时针）。"""
    pts = [p for s in segs for p in _sample(s, 0.5)]
    if len(pts) < 3:
        return 0.0
    acc = 0.0
    for (x1, y1), (x2, y2) in zip(pts, pts[1:] + pts[:1]):
        acc += x1 * y2 - x2 * y1
    return 0.5 * acc


def _reversed(segs: list[ProfileSeg2]) -> list[ProfileSeg2]:
    """反向遍历同一条闭合环（弧的 ccw / 端点角一并换）。"""
    out: list[ProfileSeg2] = []
    for s in reversed(segs):
        if s.kind == "arc":
            out.append(ProfileSeg2("arc", s.p2, s.p1, center=s.center,
                                   radius=s.radius, ccw=not s.ccw,
                                   sa=s.ea, ea=s.sa))
        else:
            out.append(ProfileSeg2("line", s.p2, s.p1))
    return out


def _as_ccw(segs: list[ProfileSeg2]) -> Profile2:
    """环向归正（契约：外环纸面 CCW 正面积）。"""
    if _ab_signed_area(segs) < 0.0:
        segs = _reversed(segs)
    return Profile2(tuple(segs))


def _rect_profile(x0: float, y0: float, x1: float, y1: float) -> Profile2:
    """轴对齐矩形（CCW：左下 → 右下 → 右上 → 左上）。"""
    return Profile2((
        ProfileSeg2("line", Point2(x0, y0), Point2(x1, y0)),
        ProfileSeg2("line", Point2(x1, y0), Point2(x1, y1)),
        ProfileSeg2("line", Point2(x1, y1), Point2(x0, y1)),
        ProfileSeg2("line", Point2(x0, y1), Point2(x0, y0)),
    ))


def _side_axis(f: Feature, dir_name: str) -> str | None:
    """侧轴凸台判定：轴 ⟂ 拉伸方向且在轮廓平面内 ⇒ 返回轴字母，否则 None。"""
    al = _axis_letter(f)
    if al in ("", dir_name):
        return None
    need = ("radius", "height", "axial_at")
    if any(k not in f.params for k in need):
        return None                      # 轴向区间还没读出来（side_axis_spans 没成）
    return al


# ---------------------------------------------------------------------------
# 月牙缺口
# ---------------------------------------------------------------------------

def _foot_cut(d: "Drawing", plan, f: Feature, al: str, r: float, a: float,
              b: float, rep: "RecognizeReport") -> Feature | None:
    """挂耳脚下（条带 − 圆盘）× 板高 的假料切除。"""
    ax: Axis3 = f.axis.value
    b1, b2 = _PLANE_AXES[plan.dir_name]
    cross = b2 if al == b1 else b1
    swap = (al == b1)                    # 轮廓 (a, b) 是否与 (cross, al) 交换
    co = _coord(ax.origin, cross)
    lo_c, hi_c = co - r, co + r

    def to_ab(u_cross: float, u_al: float) -> tuple[float, float]:
        return (u_al, u_cross) if swap else (u_cross, u_al)

    # ① 找出条带倚靠的那个**材料圆盘**分区（t 跨度要盖住板厚）
    hits: list = []
    for z in plan.zones:
        if z.role != "material" or z.kind != "disc" or len(z.circles) != 1:
            continue
        ca_, cb_, rd = z.circles[0]       # (b1 坐标, b2 坐标, r)
        ca = ca_ if cross == b1 else cb_
        cb = ca_ if al == b1 else cb_
        if abs(ca - co) > r + rd + FOOT_MARGIN:
            continue                      # 面内离条带太远
        if cb - rd > b + FOOT_MARGIN or cb + rd < a - FOOT_MARGIN:
            continue                      # 轴向不相交
        if z.t_lo > plan.t_lo + 0.5 or z.t_hi < plan.base_top - 0.5:
            continue                      # 圆盘自身没盖住板厚，不拿它当倚靠
        hits.append((z, ca, cb, rd))
    if len(hits) != 1:
        rep.notes.append(
            f"侧轴凸台 #{f.id}（r{r:g}，轴 ∥ {al}）：条带下要倚靠的材料圆盘分区"
            f"找到 {len(hits)} 个（需恰好 1 个）⇒ 月牙缺口未切（基体在挂耳"
            "脚下仍是假料）")
        return None
    z, ca, cb, rd = hits[0]
    if abs(ca - co) < r:
        rep.notes.append(
            f"侧轴凸台 #{f.id}：圆盘中心落在条带内部（|{ca:.3f}−{co:.3f}| < "
            f"{r:g}）⇒ 月牙缺口形状不确定，未切")
        return None

    # ② 触发门限：条带下的剪影底 = 凸台自身的底（悬空才切；坐在实墙上不切）
    sill = plan.band.bot_over(lo_c, hi_c)
    if sill is None or sill - plan.t_lo < UNDERCUT_MIN:
        rep.notes.append(
            f"侧轴凸台 #{f.id}：条带下剪影底 {sill} 与板底 {plan.t_lo:.2f} 齐平"
            f"（高差 < {UNDERCUT_MIN}）⇒ 凸台坐在实料上，月牙缺口未切")
        return None

    # ③ 刀形：(条带 − 圆盘) 的环 —— 圆盘弧 + 三条直线
    lo_m, hi_m = a - FOOT_MARGIN, b + FOOT_MARGIN
    if abs(lo_m - cb) >= rd - 0.01 or abs(hi_m - cb) >= rd - 0.01:
        rep.notes.append(
            f"侧轴凸台 #{f.id}：条带轴向跨度 [{lo_m:.2f},{hi_m:.2f}] 超出圆盘"
            f"（c={cb:.2f} r={rd:.2f}）可求交范围 ⇒ 月牙缺口未切")
        return None
    side = 1.0 if co > ca else -1.0

    def xd(t: float) -> float:
        return ca + side * math.sqrt(max(0.0, rd * rd - (t - cb) ** 2))

    a_out = co + side * (r + PART_MARGIN)
    p1 = to_ab(xd(lo_m), lo_m)
    p2 = to_ab(a_out, lo_m)
    p3 = to_ab(a_out, hi_m)
    p4 = to_ab(xd(hi_m), hi_m)
    c_ab = to_ab(ca, cb)
    sa = math.atan2(p4[1] - c_ab[1], p4[0] - c_ab[0])
    ea = math.atan2(p1[1] - c_ab[1], p1[0] - c_ab[0])
    ccw = ((ea - sa) % _TAU) <= math.pi   # 取劣弧（跨圆盘的那一小段）
    segs = [
        ProfileSeg2("line", Point2(*p1), Point2(*p2)),
        ProfileSeg2("line", Point2(*p2), Point2(*p3)),
        ProfileSeg2("line", Point2(*p3), Point2(*p4)),
        # 弧写在最后（链序 p4 → p1）——chain_break 验的是遍历序
        ProfileSeg2("arc", Point2(*p4), Point2(*p1), center=Point2(*c_ab),
                    radius=rd, ccw=ccw, sa=sa, ea=ea),
    ]
    depth = plan.base_top - plan.t_lo
    if depth <= 0.5:
        return None
    ev = tuple(dict.fromkeys(tuple(z.evidence) + tuple(f.evidence[:1])))
    prof = _as_ccw(segs)
    o = Point3(0.0, 0.0, 0.0)             # 轮廓写绝对坐标（见 make_cut 的口径注）
    rep.notes.append(
        f"侧轴凸台 #{f.id}（r{r:g}，轴 ∥ {al}）：条带下剪影底 {sill:.2f} 高出板底"
        f" {sill - plan.t_lo:.2f} ⇒ 挂耳悬空——自板底 {plan.t_lo:.2f} 到板顶 "
        f"{plan.base_top:.2f} 切掉(条带 − 圆盘 r{rd:.2f})的月牙缺口"
        f"（sweep {str(z.lead)}）")
    return Feature(
        id=FeatureId(-1),
        type=Claim(FeatureType.POCKET, "side_axis:foot_cut", Tier.PROJECTION, ev),
        params={"profile": Claim(prof, "side_axis:foot_cut",
                                 Tier.PROJECTION, ev),
                "depth": mk_claim(depth, "side_axis:foot_cut",
                                  Tier.PROJECTION, ev),
                # POCKET 契约：axial_at = 腔底
                "axial_at": mk_claim(plan.t_lo, "side_axis:foot_cut",
                                     Tier.PROJECTION, ev)},
        placement=Claim(o, "side_axis:foot_cut", Tier.PROJECTION, ev),
        axis=Claim(Axis3(Point3(0.0, 0.0, 0.0), _dir_vec(plan.dir_name), None),
                   "side_axis:foot_cut", Tier.PROJECTION, ev),
        source_view=plan.view_id, evidence=list(ev))


# ---------------------------------------------------------------------------
# 张缝
# ---------------------------------------------------------------------------

def _slit_cut(d: "Drawing", corr: "CorrespondenceResult", plan, f: Feature,
              al: str, r: float, a: float, b: float,
              rep: "RecognizeReport") -> Feature | None:
    """关于凸台轴向中点对称的窄缝（线对间距 ≤ 2·SLIT_MAX_HALF）。"""
    ax: Axis3 = f.axis.value
    b1, b2 = _PLANE_AXES[plan.dir_name]
    cross = b2 if al == b1 else b1
    swap = (al == b1)
    co = _coord(ax.origin, cross)
    mid = (a + b) / 2.0

    def to_ab(u_cross: float, u_al: float) -> tuple[float, float]:
        return (u_al, u_cross) if swap else (u_cross, u_al)

    found: list = []                      # (p, q, cross_lo, cross_hi, view, ev)
    h_lo: float | None = None
    h_hi: float | None = None
    for fr in corr.frames.values():
        if al not in (fr.u_axis, fr.v_axis):
            continue
        oth = fr.v_axis if fr.u_axis == al else fr.u_axis
        grp = _pp_groups(frame_lines(d, fr, oth))
        lv = sorted(grp)
        for i in range(len(lv)):
            for j in range(i + 1, len(lv)):
                p, q = lv[i], lv[j]
                if abs((p + q) / 2.0 - mid) > SYM_TOL:
                    continue
                if not (2.0 * MIN_R <= q - p <= 2.0 * SLIT_MAX_HALF):
                    continue
                gp, gq = grp[p], grp[q]
                ulo = min(gp.ulo, gq.ulo)
                uhi = max(gp.uhi, gq.uhi)
                ev = tuple(dict.fromkeys(gp.handles + gq.handles))
                if oth == cross:
                    # 线的走向 = 轮廓面内的横轴 ⇒ 给缝的走向长度；必须够到
                    # 凸台轮廓里（否则是外轮廓上的残段配对，不是缝）
                    if ulo > co - r:
                        continue
                    found.append((p, q, ulo, uhi, fr.view_id, ev))
                elif oth == plan.dir_name:
                    h_lo = ulo if h_lo is None else min(h_lo, ulo)
                    h_hi = uhi if h_hi is None else max(h_hi, uhi)
    if not found:
        rep.notes.append(
            f"侧轴凸台 #{f.id}（r{r:g}，轴 ∥ {al}）：找不到关于轴向中点 "
            f"{mid:.2f} 对称的窄线对（≤ {2 * SLIT_MAX_HALF:g}）⇒ 张缝未读"
            "（该凸台很可能没有缝）")
        return None
    keys = {round((p + q) / 2.0, 1) for p, *_ in found}
    if len(keys) > 1:
        rep.notes.append(
            f"侧轴凸台 #{f.id}：对称窄线对出现 {len(keys)} 组不同位置 ⇒ 缝的"
            "归属有歧义，未切")
        return None
    p, q, cross_lo, cross_hi, view_id, ev = max(found, key=lambda t: t[3] - t[2])
    h_from_lines = h_lo is not None
    hlo = h_lo if h_from_lines else plan.t_lo
    hhi = h_hi if h_from_lines else plan.t_hi
    ax_at = hlo - PART_MARGIN
    depth = (hhi + PART_MARGIN) - ax_at
    if depth <= 0.5:
        return None
    x0 = cross_lo - SLIT_INNER_RUN
    x1 = cross_hi + PART_MARGIN
    y0, y1 = p - SLIT_GROW, q + SLIT_GROW
    prof = _rect_profile(*to_ab(x0, y0), *to_ab(x1, y1))
    o = Point3(0.0, 0.0, 0.0)
    rep.notes.append(
        f"侧轴凸台 #{f.id}（r{r:g}，轴 ∥ {al}）：{view_id} 里关于中点 {mid:.2f} "
        f"对称的线对 {p:.3f}/{q:.3f}（宽 {q - p:.2f}）读出张缝——走向 "
        f"{cross_lo:.2f}..{cross_hi:.2f}、高 {hlo:.2f}..{hhi:.2f}"
        f"（{'线对读数' if h_from_lines else '高取材料总跨度'}，轮廓外放 "
        f"{PART_MARGIN:g}）")
    return Feature(
        id=FeatureId(-1),
        type=Claim(FeatureType.POCKET, "side_axis:slit_cut", Tier.PROJECTION, ev),
        params={"profile": Claim(prof, "side_axis:slit_cut",
                                 Tier.PROJECTION, ev),
                "depth": mk_claim(depth, "side_axis:slit_cut",
                                  Tier.PROJECTION, ev),
                "axial_at": mk_claim(ax_at, "side_axis:slit_cut",
                                     Tier.PROJECTION, ev)},
        placement=Claim(o, "side_axis:slit_cut", Tier.PROJECTION, ev),
        axis=Claim(Axis3(Point3(0.0, 0.0, 0.0), _dir_vec(plan.dir_name), None),
                   "side_axis:slit_cut", Tier.PROJECTION, ev),
        source_view=view_id, evidence=list(ev))


# ---------------------------------------------------------------------------
# 销孔
# ---------------------------------------------------------------------------

def _pin_holes(d: "Drawing", corr: "CorrespondenceResult", f: Feature,
               al: str, r: float, a: float, b: float, part: Part,
               rep: "RecognizeReport") -> list[Feature]:
    """沿凸台轴钻穿的横孔：关于轴心对称、跨住凸台整个轴向的一对轮廓线。"""
    ax: Axis3 = f.axis.value
    votes: dict[float, list[tuple]] = {}
    for fr in corr.frames.values():
        if al not in (fr.u_axis, fr.v_axis):
            continue
        oth = fr.v_axis if fr.u_axis == al else fr.u_axis
        co = _coord(ax.origin, oth)
        grp = _pp_groups(frame_lines(d, fr, al))
        lv = sorted(grp)
        for i in range(len(lv)):
            for j in range(i + 1, len(lv)):
                p, q = lv[i], lv[j]
                if abs((p + q) / 2.0 - co) > SYM_TOL:
                    continue
                rho = (q - p) / 2.0
                if not (MIN_R <= rho <= r - HOLE_WALL_MIN):
                    continue              # 贴轮廓的"线对"（间距≈Ø2r）不是孔
                gp, gq = grp[p], grp[q]
                ulo = min(gp.ulo, gq.ulo)
                uhi = max(gp.uhi, gq.uhi)
                if b - a <= 0.0:
                    continue
                frac = max(0.0, min(uhi, b) - max(ulo, a)) / (b - a)
                if frac < HOLE_COVER_MIN:
                    continue
                if not (ulo <= a + TOUCH_TOL and uhi >= b - TOUCH_TOL):
                    continue              # 两端都要够到（半程线不是孔的剪影）
                ev = tuple(dict.fromkeys(gp.handles + gq.handles))
                votes.setdefault(round(rho, 2), []).append(
                    (p, q, frac, fr.view_id, ev))
    if not votes:
        rep.notes.append(
            f"侧轴凸台 #{f.id}（r{r:g}，轴 ∥ {al}）：找不到关于轴心对称、跨住"
            "凸台轴向的线对 ⇒ 销孔未读（该凸台很可能没有横孔）")
        return []
    best = max(votes, key=lambda k: (len(votes[k]), -k))
    out: list[Feature] = []
    for rho in sorted(votes, key=lambda k: (-len(votes[k]), k)):
        if len(votes[rho]) < len(votes[best]):
            continue
        p, q, frac, view_id, ev = votes[rho][0]
        # 已有的同轴同径孔不重复建（cylinder_features 可能先读过）
        dup = any(g.type.value == FeatureType.HOLE.value
                  and _axis_letter(g) == al
                  and "radius" in g.params
                  and abs(float(g.params["radius"].value) - rho) <= 0.5
                  for g in part.features)
        if dup:
            continue
        comp = {"x": ax.origin.x, "y": ax.origin.y, "z": ax.origin.z}
        comp[al] = 0.0
        o = Point3(comp["x"], comp["y"], comp["z"])
        rep.notes.append(
            f"侧轴凸台 #{f.id}（r{r:g}，轴 ∥ {al}）：{view_id} 里关于轴心对称的"
            f"线对 {p:.3f}/{q:.3f}（ρ={rho:g}，覆盖凸台轴向 {frac * 100:.0f}%、"
            f"两端贯穿）⇒ 销孔 r{rho:g} 沿 {al} 钻通"
            f"（{len(votes[rho])} 个视图各读到一次）")
        out.append(Feature(
            id=FeatureId(-1),
            type=Claim(FeatureType.HOLE, "side_axis:pin_hole", Tier.PROJECTION,
                       ev),
            params={"radius": mk_claim(rho, "side_axis:pin_hole",
                                       Tier.PROJECTION, ev),
                    # 制图约定判据（轮廓贯穿全轴）—— 见模块注：必须 > DERIVED
                    "through": Claim(True, "side_axis:pin_through",
                                     Tier.CONVENTION, ev),
                    "axial_at": mk_claim(a, "side_axis:pin_hole",
                                         Tier.PROJECTION, ev)},
            axis=Claim(Axis3(o, _dir_vec(al), None), "side_axis:pin_hole",
                       Tier.PROJECTION, ev),
            placement=Claim(o, "side_axis:pin_hole", Tier.PROJECTION, ev),
            source_view=view_id, evidence=list(ev)))
    return out


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------

def side_channels(d: "Drawing", corr: "CorrespondenceResult", part: Part,
                  rep: "RecognizeReport") -> int:
    """侧轴凸台的三处结构读数（月牙缺口 / 张缝 / 销孔）。返回新特征数。

    只在高度分解成立（``rep.zones`` 有方案）时运行——月牙缺口要拿
    ``plan.band`` 的剪影底判悬空，张缝的高度回退要用材料总跨度。
    读不到的一律只记账（notes），不猜。
    """
    plan = rep.zones
    if plan is None or plan.band is None:
        return 0
    n = 0
    bosses = [f for f in part.features
              if f.type.value == FeatureType.BOSS.value]
    for f in bosses:
        al = _side_axis(f, plan.dir_name)
        if al is None:
            continue
        r = float(f.params["radius"].value)
        a = float(f.params["axial_at"].value)
        b = a + float(f.params["height"].value)
        foot = _foot_cut(d, plan, f, al, r, a, b, rep)
        if foot is not None:
            foot.id = part.next_id()
            part.features.insert(part.features.index(f), foot)
            # **布尔序**（depends_on）是一等公民，列表位置不够：发射器按
            # （层号, id）排，POCKET(3) 永远落在 BOSS(2) 之后 —— 没有这条
            # 依赖边，月牙刀会连凸台的下半截一起切掉（实测少料 2,761，
            # 挂耳在 z<24 整段消失）。边一挂，拓扑序就是"切 → 长"。
            f.depends_on.append(foot.id)
            n += 1
        slit = _slit_cut(d, corr, plan, f, al, r, a, b, rep)
        if slit is not None:
            slit.id = part.next_id()
            slit.depends_on.append(f.id)   # 缝切在**已长好的**凸台上
            part.add(slit)
            n += 1
        for pin in _pin_holes(d, corr, f, al, r, a, b, part, rep):
            pin.id = part.next_id()
            pin.depends_on.append(f.id)    # 销孔钻在**已长好的**凸台上
            part.add(pin)
            n += 1
    return n
