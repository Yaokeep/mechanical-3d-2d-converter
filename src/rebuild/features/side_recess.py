# -*- coding: utf-8 -*-
"""YZYX 式**侧凹槽族**：甲板 / 深腔 / 浅腔平台 / 唇外修剪 / 壁根圆角。

图纸的画法（俯视 = 投影方向 ∥ 拉伸轴的帧；剖面 = 投影方向 ∥ 凹槽长轴的帧）：

    俯视：壁面线（**隐藏** ∥u、|v|=B）与它外圈的唇线（**可见** ∥u、|v|=W>B）；
          带内的**隐藏** ∥v 端面线把凹槽切成若干段；
          深段的两端画转角圆（弧，圆心 (u_end∓R, ±(B+R))，R = 铣刀半径）；
          甲板端面以东另有端壁西面（**可见** ∥v、**横贯全宽**的大横线 ——
          端面线只画到带侧，只有真端壁横贯全宽，据此认它）。
    剖面：壁面线（∥v、|v|=B）与唇面线（∥v、|v|=W）各自的 z 跨度；
          斜肩（斜线：一端落在 ±B 上、另一端落在 ±W 上）；
          平台顶（唯一一组**整体落在带内**的 ∥u 线，z ∈ (槽底, 甲板顶)）；
          槽底（盖住带侧的 ∥u 线里、低于平台底的最高一条）；
          壁根圆角（弧，圆心 (±(B+r), 槽底+r)）；
          端块外柱面（弧：半径 ≥ 唇距、圆心在带中线且低于槽底、端点落在
          唇线/槽底上 —— 端壁外的「裙」，端块外侧按它裁圆角）。

⚠️ **坐标系**：本模块读到的全是**图纸模型系**坐标（不是零件系）——原点偏移
如 YZYX 的 (2650.80, 3462.94, 1541.25)。所有「在南侧/北侧」的分侧判据一律用
**相对带中心** ``center_pp``（一对镜像壁面线的中点）的差值，绝不能用坐标自身
的符号：图纸 y 3402.94 是零件 −60，符号完全相反。几何一律用实测绝对坐标写。

发射（全部图纸模型系绝对坐标，轮廓面 (a,b) = (带轴, 深度轴)）：

    ① 甲板抬升 BASE：u∈[首端面, 末端面] × v∈[两唇线] × z∈[base_top, 甲板顶]
    ② 深段 ×2 POCKET：(壁,槽底)(唇,槽底)(唇,斜肩_W)(壁,斜肩_B)
    ③ 浅段 ×2×2 POCKET：下 (…, 平台底)、上 (平台顶, …, 斜肩)
    ④ 唇外盒切 ×2 POCKET：唇线外侧到视图 v 端，z∈[槽底, base_top+1]
    ⑤ 壁根月牙 ×2 BASE：方角减圆，(壁..壁+r, 槽底..槽底+r) − 圆盘，**最后** fuse
       （``depends_on`` = 本侧深腔 + 浅腔；它复用的是铣刀在腔壁上留下的 R 圆角）
    ⑥ 端块假料 ×2 POCKET：甲板末端→端壁西面之间的端块，唇线外、槽底以上、
       柱面圆外的全删（端块外轮廓 = 剖面读到的大圆；东端面 z 上的假料在
       ①④ 的跨度之外，没人管 —— 实测点 (e) 唇 y=−77.8 z=55.4）

**拒发**（只记账、不猜）：
- 壁/唇线对、端面线、剖面任一读数缺 → 不建（对称件要求两侧都读得出）；
- 转角圆没把「深段」分出来 → 不建：剖面读的槽底/斜肩/平台分派不到具体段，
  硬按全段深腔会把浅段平台一起切掉；
- 只认**成对**读数：南北同一读法差 > ``SYM_TOL`` 时取南侧并记账。

**已知没读**（本轮范围外，别当成读错）：西端块 x<−141.5 在 z>80 以上的体
（甲板抬升只盖端面线定出的凹槽跨度）、俯视 x=−26.5 的甲板台阶（剖面在
−96.5，属西段，读不到东段顶高）、深段端面的立角圆角 c=(u_end∓5, ±65)
（无探针点、与月牙同一族但走俯视弧）、端壁（x≥端壁西面）的内部结构
（⑥ 只把端块假料裁到壁面为止 —— 壁面以东不再动）。
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING

from ..model.claim import Claim, Tier
from ..model.feature_tree import Feature, FeatureType, Part
from ..model.geom import Axis3, Point3
from ..model.geom2d import Arc2, Line2, Point2, Profile2, ProfileSeg2
from ..model.ids import FeatureId
from .height_zones import (MERGE_GAP, PP_CLUSTER, _dir_vec, _pp_groups, _view,
                           frame_lines)
from .library import ir_point, mk_claim
from .recognizer import _PLANE_AXES
from .side_channels import _as_ccw, _rect_profile

if TYPE_CHECKING:
    from ..evidence.dxf_reader import Drawing
    from ..views.correspondence import CorrespondenceResult, ViewFrame
    from .recognizer import RecognizeReport

__all__ = ["side_recess"]

#: 南北/对位容差（mm）
SYM_TOL = 0.50
#: 壁面线最短跨度（筛掉碎段，mm）
WALL_MIN = 8.0
#: 端面线最短长度（mm）
END_MIN = 3.0
#: 带侧覆盖率门限（槽底线往往只画到壁面/唇面一侧，故 0.6）
COVER_MIN = 0.60
#: 转角圆对位容差（mm）
ROUND_TOL = 0.80
#: 月牙两端过冲（mm）。必须 > 0：验收探针恰好落在段界 x=u_end 上，
#: 月牙若止于段界，点就落在面上（ON）而不是体内（IN）
OVER = 0.10
#: 唇外盒切顶 = 基体顶 + 该值（mm）
TRIM_TOP = 1.00
#: 盒切外伸（mm）
OUT_MARGIN = 2.00
#: 最小可信半径 / 带宽（mm）
MIN_R = 0.30
BAND_MIN = 3.0
#: 端块外柱面弧的端点容差（mm）：图上弧两端被角部小圆角裁短，认「落在唇线/
#: 槽底上」要放宽（实测 94F 起点差 1.0、终点差 4.2）
SKIRT_TOL = 6.0
#: 平台顶必须落在 (槽底, 壁面线顶) 之间，且距两端至少这么多（mm）
PLAT_EDGE_MIN = 1.00


def _side_name(sign: int) -> str:
    return "北" if sign > 0 else "南"


# ---------------------------------------------------------------------------
# 读数
# ---------------------------------------------------------------------------

@dataclass
class Band:
    """俯视图里**一侧**的带读法（图纸模型系坐标）。"""

    sign: int                  # 相对带中心的符号（−1 = 南 / +1 = 北）
    b: float                   # 壁面距中心 |v−c|
    w: float                   # 唇线距中心 |v−c|
    center_pp: float           # 带中心（一对镜像壁面线的中点，图纸 v 实测）
    wall_pp: float             # 壁面线实测 v
    lip_pp: float              # 唇线实测 v
    wall: tuple[float, float]  # 壁面线 u 跨度
    lip: tuple[float, float]   # 唇线 u 跨度
    ends: tuple[float, ...]    # 端面 u（升序）
    ev: tuple[str, ...] = ()

    @property
    def segments(self) -> list[tuple[float, float]]:
        return list(zip(self.ends, self.ends[1:]))

    @property
    def band_pp(self) -> tuple[float, float]:
        """带在 v 上的区间（升序实测坐标）。"""
        return (min(self.wall_pp, self.lip_pp), max(self.wall_pp, self.lip_pp))

    def outward(self) -> float:
        """由壁面向唇线（远离零件中心）的 v 方向，±1。"""
        return 1.0 if self.lip_pp > self.wall_pp else -1.0


@dataclass
class Deck:
    """剖面上读到的 z 读数（切平面穿过凹槽）。"""

    t_lo: float                # 槽底（= 板顶）
    s_b: float                 # 斜肩在壁面处的高
    s_w: float                 # 斜肩在唇线处的高
    deck_top: float            # 甲板顶
    p_bot: float               # 平台底（= 唇面线底）
    p_top: float               # 平台顶（带内受限的 ∥u 线）
    r_f: float                 # 壁根圆角半径
    ev: tuple[str, ...] = ()


def _merge(vals: list[float], tol: float) -> list[float]:
    out: list[float] = []
    for v in sorted(vals):
        if out and v - out[-1] <= tol:
            out[-1] = (out[-1] + v) / 2.0
            continue
        out.append(v)
    return out


def _uv(fr: "ViewFrame", p) -> dict[str, float]:
    """图纸点 → {轴名: 模型坐标}。"""
    return {fr.u_axis: fr.u_to_model(p.x), fr.v_axis: fr.v_to_model(p.y)}


def _role_of(d: "Drawing", handles: tuple[str, ...]) -> str:
    for h in handles:
        e = d.by_handle(h)
        if e is not None:
            return e.role.value
    return ""


def _band_center(d: "Drawing", fr: "ViewFrame") -> float | None:
    """带中心 = 一对镜像壁面线（隐藏 ∥u、跨度够长）的中点，图纸 v 实测坐标。

    分侧、判「在带内」全靠它——坐标原点在图纸里是任意的，符号没有意义。
    """
    ul = frame_lines(d, fr, fr.u_axis)
    hid = _pp_groups([s for s in ul if s.role == "hidden"])
    cands = sorted(p for p, g in hid.items() if (g.uhi - g.ulo) >= WALL_MIN)
    if len(cands) < 2:
        return None
    return (cands[0] + cands[-1]) / 2.0


def _read_band(d: "Drawing", fr: "ViewFrame", sign: int, center: float,
               rep: "RecognizeReport") -> Band | None:
    """一侧的「隐藏壁面线 + 可见唇线 + 隐藏端面线」三联读数。"""
    ul = frame_lines(d, fr, fr.u_axis)          # ∥u，键 = v
    vl = frame_lines(d, fr, fr.v_axis)          # ∥v，键 = u
    hid_u = _pp_groups([s for s in ul if s.role == "hidden"])
    vis_u = _pp_groups([s for s in ul if s.role == "visible"])

    # ① 壁面：本侧（相对中心）隐藏 ∥u 里跨度最长者
    wall = [(p, g) for p, g in hid_u.items()
            if (p - center) * sign > 0 and (g.uhi - g.ulo) >= WALL_MIN]
    if not wall:
        return None
    b_p, b_g = max(wall, key=lambda t: t[1].uhi - t[1].ulo)
    b = abs(b_p - center)

    # ② 唇线：本侧可见 ∥u 里距中心 > B、且 u 跨度盖住壁面线的**最近**者
    #（外圈法兰边的跨度也盖得住，取最近者才不会误选 —— 实测 y=±197.5 的
    # 法兰边跨度 [−144.5,159.5] 同样覆盖壁面线的 [−136.5,−15.5]）
    lips = [(p, g) for p, g in vis_u.items()
            if (p - center) * sign > 0 and abs(p - center) > b + BAND_MIN
            and g.ulo <= b_g.ulo + SYM_TOL and g.uhi >= b_g.uhi - SYM_TOL]
    if not lips:
        return None
    w_p, w_g = min(lips, key=lambda t: abs(t[0] - center))

    # ③ 端面：本侧隐藏 ∥v 里整段落在带内、u 不越出唇线的
    hid_v = _pp_groups([s for s in vl if s.role == "hidden"])
    v0, v1 = sorted((b_p, w_p))          # 带在 v 上的区间（升序实测）
    ends: list[float] = []
    end_h: list[str] = []
    for u, g in hid_v.items():
        lo, hi = g.ulo, g.uhi
        if (hi - lo) < END_MIN:
            continue
        if not (w_g.ulo - SYM_TOL <= u <= w_g.uhi + SYM_TOL):
            continue                     # 带外的短竖线不是这族凹槽的端面
        # ⚠️ 端面线通常**南北各画一段**（壁..唇），同 pp 归进一组后 ulo/uhi 的
        # 并集横跨整个带（实测 [−75,+75]）——判「落在带内」必须用与带的**重叠
        # 长度**，不能拿并集去比区间（那样永远为假、端面一个也认不出）。
        ov = min(hi, v1) - max(lo, v0)
        if ov >= END_MIN:
            ends.append(u)
            end_h.extend(g.handles)
    ends = _merge(ends, 0.60)
    if len(ends) < 2:
        return None
    ev = tuple(dict.fromkeys(tuple(b_g.handles) + tuple(w_g.handles) + tuple(end_h)))
    return Band(sign=sign, b=b, w=abs(w_p - center), center_pp=center,
                wall_pp=b_p, lip_pp=w_p,
                wall=(b_g.ulo, b_g.uhi), lip=(w_g.ulo, w_g.uhi),
                ends=tuple(ends), ev=ev)


def _plan_rounds(d: "Drawing", vid: str, fr: "ViewFrame", band: Band
                 ) -> list[tuple[float, float, float, str]]:
    """俯视里属于本侧的**转角圆**弧：圆心 (u, 中心±(B+R))、半径 R ≤ 带宽。"""
    v = _view(d, vid)
    if v is None:
        return []
    out: list[tuple[float, float, float, str]] = []
    for h in v.evidence:
        e = d.by_handle(h)
        if e is None or not isinstance(e.geom, Arc2):
            continue
        g = e.geom
        r = float(g.radius)
        if r <= MIN_R or r > (band.w - band.b) + ROUND_TOL:
            continue
        c = _uv(fr, g.center)
        cu = c[fr.u_axis]
        cv = c[fr.v_axis] - band.center_pp
        if abs(abs(cv) - (band.b + r)) > ROUND_TOL:
            continue
        if cv * band.sign <= 0:
            continue
        out.append((cu, cv, r, h))
    return out


def _deep_segments(segs: list[tuple[float, float]],
                   rounds: list[tuple[float, float, float, str]]
                   ) -> list[tuple[float, float]]:
    """两端都有转角圆（刀半径留下的角）的段 = 深腔段。"""
    out: list[tuple[float, float]] = []
    for u0, u1 in segs:
        west = any(abs(cu - (u0 + r)) <= ROUND_TOL for cu, _cv, r, _h in rounds)
        east = any(abs(cu - (u1 - r)) <= ROUND_TOL for cu, _cv, r, _h in rounds)
        if west and east:
            out.append((u0, u1))
    return out


def _find_section(d: "Drawing", corr: "CorrespondenceResult", frP: "ViewFrame",
                  dir_name: str, axis: str) -> tuple[str, "ViewFrame"] | None:
    """剖面对：投影方向 ∥ 凹槽长轴、面内两轴 = (带宽轴, 拉伸轴)。优先有定位剖切者。"""
    cands: list[tuple[str, ViewFrame]] = []
    for vid, fr in sorted(corr.frames.items()):
        if fr.p_axis != axis:
            continue
        if {fr.u_axis, fr.v_axis} != {frP.v_axis, dir_name}:
            continue
        cands.append((vid, fr))
    if not cands:
        return None

    def located(vid: str) -> bool:
        v = _view(d, vid)
        c = getattr(v, "cut", None)
        return bool(c is not None and getattr(c, "is_located", False)
                    and getattr(c, "cut_axis", "") == axis)

    hits = [c for c in cands if located(c[0])]
    return (hits + cands)[0]


def _pairs_at(groups: dict, val: float, sign: int, center: float) -> list:
    """键距中心 ≈ val（本侧符号）的组。"""
    return [(p, g) for p, g in groups.items()
            if abs(abs(p - center) - val) <= SYM_TOL and (p - center) * sign > 0]


def _runs_at(segs: list, pp: float, tol: float = PP_CLUSTER,
             gap: float = MERGE_GAP) -> list[tuple[float, float, list[str]]]:
    """某 pp 上的**逐条连续 run**（``_pp_groups`` 的同一套并段逻辑）。

    ``PPGroup`` 只给「最长 run + 全部 run 的并集」，而并集在南北两侧都画了线时
    会横跨整个带（实测：槽底线 z=12 南北各一段、并集 [−191,197]；平台线 z=100
    南北各一段、并集 150mm）——凡按「落在带内 / 盖住带侧」判据的都得按 run 走。
    """
    take = [s for s in segs if abs(s.pp - pp) <= tol]
    if not take:
        return []
    take.sort(key=lambda t: t.lo)
    runs: list[list] = []
    for s in take:
        if runs and s.lo <= runs[-1][1] + gap:
            runs[-1][1] = max(runs[-1][1], s.hi)
            runs[-1][2].append(s.handle)
        else:
            runs.append([s.lo, s.hi, [s.handle]])
    return [(r[0], r[1], r[2]) for r in runs]


def _read_deck(d: "Drawing", fr: "ViewFrame", band: Band, dir_name: str,
               rep: "RecognizeReport") -> Deck | None:
    """切平面在带内时，剖面给出的槽底/斜肩/甲板顶/平台/壁根圆角。"""
    band_ax = fr.u_axis if fr.u_axis != dir_name else fr.v_axis
    if band_ax == dir_name:
        return None
    sl = frame_lines(d, fr, band_ax)      # ∥带轴，键 = 深度轴
    sv = frame_lines(d, fr, dir_name)     # ∥深度轴，键 = 带轴
    gv = _pp_groups(sv)
    gs = _pp_groups(sl)

    walls = _pairs_at(gv, band.b, band.sign, band.center_pp)
    lips = _pairs_at(gv, band.w, band.sign, band.center_pp)
    if not walls or not lips:
        return None
    wg = max(walls, key=lambda t: t[1].hi - t[1].lo)[1]
    lg_all = [g for _p, g in lips]
    lg_vis = [g for _p, g in lips if _role_of(d, g.handles) == "visible"]
    lg = max(lg_vis or lg_all, key=lambda g: g.hi - g.lo)
    deck_top = float(lg.hi)               # 唇面线顶 = 甲板顶
    p_bot = float(lg.lo)                  # 唇面线底 = 平台底

    a0, a1 = band.band_pp
    width = a1 - a0

    def side_covers(z: float) -> bool:
        """z 层上有没有一条 run 盖住本带侧 ≥ COVER_MIN（按 run，不看并集）。"""
        return any(min(hi, a1) - max(lo, a0) >= width * COVER_MIN
                   for lo, hi, _h in _runs_at(sl, z))

    # 槽底：低于平台底、仍在带侧留够料的最高 ∥u 线
    below = [z for z in gs if z < p_bot - 0.50 and side_covers(z)]
    if not below:
        return None
    t_lo = float(max(below))

    # 平台顶：有一条 run 整体落在带内、且盖住带侧的 ∥u 线
    plat = [z for z in gs
            if any(lo >= a0 - SYM_TOL and hi <= a1 + SYM_TOL
                   and (hi - lo) >= width * COVER_MIN
                   for lo, hi, _h in _runs_at(sl, z))]
    p_top = float(max(plat)) if plat else 0.0
    if plat and not (t_lo + PLAT_EDGE_MIN < p_top < wg.hi - PLAT_EDGE_MIN):
        p_top = 0.0

    v = _view(d, fr.view_id)
    ev: list[str] = list(wg.handles) + list(lg.handles)
    s_b = float(wg.hi)                    # 壁面线顶 = 斜肩在壁侧的高
    # 斜肩：一端落在壁面、另一端落在唇线的斜线
    s_w = float("nan")
    for h in v.evidence:
        e = d.by_handle(h)
        if e is None or not isinstance(e.geom, Line2):
            continue
        a1, a2 = _uv(fr, e.geom.start), _uv(fr, e.geom.end)
        y1, z1 = float(a1[band_ax]) - band.center_pp, float(a1[dir_name])
        y2, z2 = float(a2[band_ax]) - band.center_pp, float(a2[dir_name])
        if abs(y1 - y2) < 1e-6 or abs(z1 - z2) < 1e-6:
            continue                       # 轴平行，不是斜肩
        if abs(abs(y1) - band.b) <= SYM_TOL and abs(abs(y2) - band.w) <= SYM_TOL:
            s_w, s_b2, hh = z2, z1, h
        elif abs(abs(y2) - band.b) <= SYM_TOL and abs(abs(y1) - band.w) <= SYM_TOL:
            s_w, s_b2, hh = z1, z2, h
        else:
            continue
        if abs(s_b2 - wg.hi) > SYM_TOL:
            rep.notes.append(
                f"侧凹槽：剖面斜肩在壁面一侧读到 {s_b2:.2f}，与壁面线顶 {wg.hi:.2f} "
                f"差 {abs(s_b2 - wg.hi):.2f} ⇒ 这两条不是同一条肩线，肩按壁面线顶取")
            s_w = float("nan")
            break
        ev.append(hh)
        break
    if math.isnan(s_w):
        rep.notes.append(
            "侧凹槽：剖面里没读到「一端在壁面、一端在唇线」的斜肩线 ⇒ 肩线按水平 "
            f"{wg.hi:.2f} 取（深腔上界会偏高）")
        s_w = float(wg.hi)

    # 壁根圆角：弧，圆心距中心 (B+r)、z = 槽底+r
    r_f = 0.0
    for h in v.evidence:
        e = d.by_handle(h)
        if e is None or not isinstance(e.geom, Arc2):
            continue
        g = e.geom
        if g.radius <= MIN_R:
            continue
        c = _uv(fr, g.center)
        cy, cz = float(c[band_ax]) - band.center_pp, float(c[dir_name])
        if abs(abs(cy) - (band.b + g.radius)) > SYM_TOL:
            continue
        if abs(cz - (t_lo + g.radius)) > SYM_TOL:
            continue
        r_f = float(g.radius)
        ev.append(h)
        break
    if r_f <= 0.0:
        rep.notes.append("侧凹槽：剖面里没读到壁根圆角弧 ⇒ 月牙不建（壁与板仍按直角）")

    return Deck(t_lo=t_lo, s_b=s_b, s_w=float(s_w), deck_top=deck_top,
                p_bot=p_bot, p_top=p_top, r_f=r_f, ev=tuple(dict.fromkeys(ev)))


def _read_skirt(d: "Drawing", vid: str, fr: "ViewFrame", dir_name: str,
                lips: tuple[float, float], center: float, t_lo: float
                ) -> tuple[float, float, float, str] | None:
    """剖面里「绕带中线的外凸大圆」= 端块外柱面（裙）的读数。

    判据（全实测 + 几何自洽）：弧、半径 ≥ 唇距 + ``BAND_MIN``（圆在唇线之外
    还有实质弧度）、圆心在带中心线上（|Δ| ≤ ``SYM_TOL`` —— 柱面绕零件中线）、
    圆心低于槽底（圆在基体内侧；圆心在槽底之上时与唇线构不成外凸角）。
    **两端点**：一个落在唇线高度（|a−圆心| ≈ 唇距）、另一个落在槽底上 ——
    角部圆弧的两端本就该接在这两条线上（图上两端被小圆角裁短 ≤ ``SKIRT_TOL``）。
    ⚠️ 只按半径选最大是错的：实测顶拱 R187.5（878，跨 170°、端点在 |y|≈187）
    与裙弧 R95（94F）**同心**且都 visible，靠端点才分得开。
    返回（r, 圆心带轴坐标, 圆心深度轴坐标, handle）或 None。
    """
    band_ax = fr.u_axis if fr.u_axis != dir_name else fr.v_axis
    if band_ax == dir_name:
        return None
    v = _view(d, vid)
    if v is None:
        return None
    lip = max(abs(lips[0] - center), abs(lips[1] - center))
    best: tuple[float, float, float, str] | None = None
    for h in v.evidence:
        e = d.by_handle(h)
        if e is None or not isinstance(e.geom, Arc2):
            continue
        g = e.geom
        uv = _uv(fr, g.center)
        ca, cb = uv[band_ax], uv[dir_name]
        if abs(ca - center) > SYM_TOL or cb > t_lo - BAND_MIN:
            continue
        if g.radius < lip + BAND_MIN:
            continue

        def near(ang: float) -> tuple[bool, bool]:
            uv_pt = _uv(fr, Point2(g.center.x + g.radius * math.cos(ang),
                                   g.center.y + g.radius * math.sin(ang)))
            a_pt, b_pt = uv_pt[band_ax], uv_pt[dir_name]
            return (abs(abs(a_pt - ca) - lip) <= SKIRT_TOL,
                    abs(b_pt - t_lo) <= SKIRT_TOL)

        s_lip, s_lo = near(g.start_angle)
        e_lip, e_lo = near(g.end_angle)
        if not ((s_lip and e_lo) or (e_lip and s_lo)):
            continue
        if best is None or g.radius > best[0]:
            best = (g.radius, ca, cb, h)
    return best


def _read_end_face(d: "Drawing", vid: str, fr: "ViewFrame", lip_s: float,
                   lip_n: float, u1: float) -> tuple[float, str] | None:
    """俯视图里甲板末端之东最近的「可见 ∥v 全宽横线」= 端壁西面（端块东界）。

    判据：u = 常数且 > 甲板末端 + ``BAND_MIN``、v 跨度盖住两条唇线 —— 端面线
    只画到带侧（端块外柱面的足迹 |v−中心| ∈ [B, r]），只有真端壁横贯全宽。
    """
    v = _view(d, vid)
    if v is None:
        return None
    lo_lip, hi_lip = min(lip_s, lip_n), max(lip_s, lip_n)
    best: tuple[float, str] | None = None
    for h in v.evidence:
        e = d.by_handle(h)
        if e is None or e.role.value != "visible" or not isinstance(e.geom, Line2):
            continue
        uv0 = _uv(fr, e.geom.start)
        uv1 = _uv(fr, e.geom.end)
        u_a, u_b = uv0[fr.u_axis], uv1[fr.u_axis]
        v_a, v_b = uv0[fr.v_axis], uv1[fr.v_axis]
        if abs(u_a - u_b) > 1e-6 or abs(v_a - v_b) < END_MIN:
            continue
        u = (u_a + u_b) / 2.0
        if u < u1 + BAND_MIN:
            continue
        vlo, vhi = min(v_a, v_b), max(v_a, v_b)
        if vlo > lo_lip + SYM_TOL or vhi < hi_lip - SYM_TOL:
            continue
        if best is None or u < best[0]:
            best = (u, h)
    return best


# ---------------------------------------------------------------------------
# 建立特征
# ---------------------------------------------------------------------------


def _mk_pocket(prof: Profile2, axis: str, axial_at: float, depth: float,
               method: str, ev: tuple[str, ...], sv: str) -> Feature:
    return Feature(
        id=FeatureId(-1),
        type=Claim(FeatureType.POCKET, method, Tier.PROJECTION, ev),
        params={"profile": Claim(prof, method, Tier.PROJECTION, ev),
                "depth": mk_claim(depth, method, Tier.PROJECTION, ev),
                # POCKET 契约：axial_at = 腔底（沿 +轴 挖 depth）
                "axial_at": mk_claim(axial_at, method, Tier.PROJECTION, ev)},
        placement=Claim(Point3(0.0, 0.0, 0.0), method, Tier.PROJECTION, ev),
        axis=Claim(Axis3(Point3(0.0, 0.0, 0.0), _dir_vec(axis), None), method,
                   Tier.PROJECTION, ev),
        source_view=sv, evidence=list(ev))


def _quad(inner: float, outer: float, lo: float, hi_inner: float,
          hi_outer: float) -> Profile2:
    """(壁,槽底)(唇,槽底)(唇,肩外)(壁,肩内)：壁/唇都用**实测绝对坐标**。"""
    segs = [
        ProfileSeg2("line", Point2(inner, lo), Point2(outer, lo)),
        ProfileSeg2("line", Point2(outer, lo), Point2(outer, hi_outer)),
        ProfileSeg2("line", Point2(outer, hi_outer), Point2(inner, hi_inner)),
        ProfileSeg2("line", Point2(inner, hi_inner), Point2(inner, lo)),
    ]
    return _as_ccw(segs)


def _crescent(wall: float, circle_c: float, r: float, t_lo: float) -> Profile2:
    """壁根月牙：(壁..壁+r, 槽底..槽底+r) 的方角减去 r 圆盘。

    ``wall`` = 壁面实测坐标、``circle_c`` = 圆心实测坐标（= wall ± r）。
    圆盘与「壁面」「槽底」两面都相切 ⇒ 残留区 = 两段直边（槽底边 + 壁面边，
    过方角 ``(wall, t_lo)``）+ 一段圆盘边界弧。
    ⚠️ 别写成「切点→切点」一条斜边：那样围出的是弦与弧之间的透镜，不是月牙
    （实测症状：区域内换上「对角线下方的三角」，验收点 (b) 月牙落在外面）。
    """
    top = t_lo + r
    p1 = Point2(wall, top)                 # 弧起点（圆盘与壁面相切处）
    p2 = Point2(circle_c, t_lo)            # 弧终点（圆盘与槽底相切处）
    corner = Point2(wall, t_lo)            # 方角（壁面与槽底的交点）
    sa = math.atan2(p1.y - top, p1.x - circle_c)
    ea = math.atan2(p2.y - top, p2.x - circle_c)
    ccw = ((ea - sa) % (2.0 * math.pi)) <= math.pi
    segs = [
        ProfileSeg2("line", p2, corner),   # 槽底边：圆盘切点 → 方角
        ProfileSeg2("line", corner, p1),   # 壁面边：方角 → 圆盘切点
        ProfileSeg2("arc", p1, p2, center=Point2(circle_c, top), radius=r,
                    ccw=ccw, sa=sa, ea=ea),
    ]
    return _as_ccw(segs)


def side_recess(d: "Drawing", corr: "CorrespondenceResult", part: Part,
                rep: "RecognizeReport") -> int:
    """侧凹槽族的读数与发射。返回新特征数；读不到只记账（notes），不猜。"""
    plan = rep.zones
    if plan is None:
        return 0
    dir_name = plan.dir_name
    # 俯视帧：投影方向 = 拉伸轴。⚠️ plan.view_id 是**剪影来源的侧视图**
    # （高度分解拿它读 z 包络），不是俯视 —— 俯视要自己找（可能不止一个
    # p_axis == dir_name 的帧，用「这一帧读得出壁/唇/端面三联」来定）。
    picked: tuple[str, ViewFrame, float, dict[int, Band]] | None = None
    for vid, fr in sorted(corr.frames.items()):
        if fr.p_axis != dir_name:
            continue
        if fr.u_axis == dir_name or fr.v_axis == dir_name:
            continue
        center = _band_center(d, fr)
        if center is None:
            continue
        bd: dict[int, Band] = {}
        for sign in (-1, 1):
            one = _read_band(d, fr, sign, center, rep)
            if one is not None:
                bd[sign] = one
        if len(bd) == 2:
            picked = (vid, fr, center, bd)
            break
    if picked is None:
        rep.notes.append(
            "侧凹槽：俯视帧里读不出「镜像隐藏壁面线 + 可见唇线 + 带内端面线」"
            "三联 ⇒ 不建（对称件两侧都要读得出；不猜）")
        return 0
    pvid, frP, center, bands = picked
    axis, band_ax = frP.u_axis, frP.v_axis
    if _PLANE_AXES.get(axis) != (band_ax, dir_name):
        # 轮廓面 (a,b) 的轴序必须与发射器一致，否则截面包络会转置
        rep.notes.append(
            f"侧凹槽：拉伸轴 {axis} 的面内轴序 {_PLANE_AXES.get(axis)} 与"
            f"（带轴 {band_ax}, 剖面深度轴 {dir_name}）不一致 ⇒ 不建")
        return 0
    base_top = float(plan.base_top)
    south, north = bands[-1], bands[1]
    if len(south.ends) != len(north.ends):
        rep.notes.append(
            f"侧凹槽：南北端面线条数不同（{len(south.ends)}/{len(north.ends)}）⇒ 不建")
        return 0

    hit = _find_section(d, corr, frP, dir_name, axis)
    if hit is None:
        rep.notes.append(
            f"侧凹槽：没有投影方向 ∥ {axis} 的剖面视图可读槽底/斜肩/平台 ⇒ 不建")
        return 0
    svid, frS = hit
    deck = _read_deck(d, frS, south, dir_name, rep)
    if deck is None:
        rep.notes.append(f"侧凹槽：剖面 {svid} 里读不到壁面线/唇面线/槽底 ⇒ 不建")
        return 0
    deck_n = _read_deck(d, frS, north, dir_name, rep)
    if deck_n is not None:
        for name, a, b in (("甲板顶", deck_n.deck_top, deck.deck_top),
                           ("壁侧肩高", deck_n.s_b, deck.s_b),
                           ("槽底", deck_n.t_lo, deck.t_lo)):
            if abs(a - b) > SYM_TOL:
                rep.notes.append(
                    f"侧凹槽：剖面南北{name} 差 {abs(a - b):.2f}（北 {a:.2f} / "
                    f"南 {b:.2f}）⇒ 按南侧读数发射")

    # 深/浅段
    rounds = {s: _plan_rounds(d, pvid, frP, bands[s]) for s in (-1, 1)}
    deep = {s: _deep_segments(bands[s].segments, rounds[s]) for s in (-1, 1)}
    if not deep[-1] or not deep[1]:
        rep.notes.append(
            f"侧凹槽：转角圆没把「深腔段」分出来（南 {len(deep[-1])} 段 / 北 "
            f"{len(deep[1])} 段，俯视共 {len(south.ends) - 1} 段）⇒ 不建"
            "（不猜：剖面读的槽底/斜肩/平台分派不到具体段，全按深腔会把浅段"
            "平台一起切掉）")
        return 0
    shallow = {s: [seg for seg in bands[s].segments if seg not in deep[s]]
               for s in (-1, 1)}

    t_lo, s_b, s_w = deck.t_lo, deck.s_b, deck.s_w
    if not (t_lo < deck.p_bot and s_b > t_lo and s_w >= s_b - SYM_TOL):
        rep.notes.append(
            f"侧凹槽：剖面读数不自洽（槽底 {t_lo:.2f} ≥ 平台底 {deck.p_bot:.2f} 或"
            f"肩 {s_b:.2f}/{s_w:.2f}）⇒ 不建")
        return 0

    n = 0
    # ① 甲板抬升（BASE）：凹槽跨度 × [两唇线] × [base_top, 甲板顶]
    u0, u1 = south.ends[0], south.ends[-1]
    ev_deck = tuple(dict.fromkeys(south.ev + north.ev + deck.ev))
    v_s, v_n = south.lip_pp, north.lip_pp
    prof = _rect_profile(u0, min(v_s, v_n), u1, max(v_s, v_n))
    o = ir_point(Point3(0.0, 0.0, 0.0), dir_name, 0.0, 0.0, base_top)
    ra = Feature(
        id=FeatureId(-1),
        type=Claim(FeatureType.BASE, "recess:deck_raise", Tier.PROJECTION, ev_deck),
        params={"dir": mk_claim(dir_name, "recess:deck_raise", Tier.PROJECTION, ev_deck),
                "length": mk_claim(deck.deck_top - base_top, "recess:deck_raise",
                                   Tier.PROJECTION, ev_deck),
                "profile": Claim(prof, "recess:deck_raise", Tier.PROJECTION, ev_deck),
                "origin": mk_claim(o, "recess:deck_raise", Tier.PROJECTION, ev_deck)},
        placement=Claim(o, "recess:deck_raise", Tier.PROJECTION, ev_deck),
        source_view=pvid, evidence=list(ev_deck),
    )
    ra.id = part.next_id()
    part.add(ra)
    n += 1
    rep.notes.append(
        f"侧凹槽 ①甲板：BASE {axis}∈[{u0:.2f},{u1:.2f}]（长 {u1 - u0:.2f}）"
        f"|{band_ax}|∈[{south.b:.2f},{south.w:.2f}] z∈[{base_top:.2f},"
        f"{deck.deck_top:.2f}]（长 {deck.deck_top - base_top:.2f}）")

    # ② 深腔（每段每侧一刀：自段首沿 +轴 到段尾）
    cuts: dict[int, list[FeatureId]] = {-1: [], 1: []}
    for sign in (-1, 1):
        bd = bands[sign]
        for a0, a1 in deep[sign]:
            f = _mk_pocket(_quad(bd.wall_pp, bd.lip_pp, t_lo, s_b, s_w), axis,
                           a0, a1 - a0, "recess:deep_cut", bd.ev + deck.ev, pvid)
            f.id = part.next_id()
            part.add(f)
            cuts[sign].append(f.id)
            n += 1
            rep.notes.append(
                f"侧凹槽 ②深腔（{_side_name(sign)}）：POCKET {axis}∈[{a0:.2f},"
                f"{a1:.2f}]（长 {a1 - a0:.2f}）|{band_ax}|∈[{bd.b:.2f},"
                f"{bd.w:.2f}] z∈[{t_lo:.2f},{s_b:.2f}→{s_w:.2f}]")
    # ③ 浅腔：平台下 / 平台上
    for sign in (-1, 1):
        bd = bands[sign]
        if not shallow[sign]:
            continue
        if deck.p_top <= 0.0:
            rep.notes.append(
                f"侧凹槽 ③浅腔（{_side_name(sign)}）：有浅段但剖面没读到平台顶"
                "（带内受限 ∥u 线）⇒ 浅段上下限不成立，未切（该段仍是假料）")
            continue
        for a0, a1 in shallow[sign]:
            for lo, hi_i, hi_o, tag in ((t_lo, deck.p_bot, deck.p_bot, "下"),
                                        (deck.p_top, s_b, s_w, "上")):
                f = _mk_pocket(_quad(bd.wall_pp, bd.lip_pp, lo, hi_i, hi_o), axis,
                               a0, a1 - a0, "recess:shallow_cut",
                               bd.ev + deck.ev, pvid)
                f.id = part.next_id()
                part.add(f)
                cuts[sign].append(f.id)   # ⑤ 月牙 depends_on 要含浅腔：
                                          # 后建的浅腔端会削掉月牙的 +OVER 过冲段
                n += 1
                rep.notes.append(
                    f"侧凹槽 ③浅腔{tag}（{_side_name(sign)}）：POCKET {axis}∈"
                    f"[{a0:.2f},{a1:.2f}]（长 {a1 - a0:.2f}）|{band_ax}|∈"
                    f"[{bd.b:.2f},{bd.w:.2f}] z∈[{lo:.2f},"
                    f"{hi_i:.2f}..{hi_o:.2f}]")
    # ④ 唇外盒切：唇线外侧的基体假料（基体轮廓 = 俯视外轮廓，比零件宽）
    vs = sorted(frP.v_span)
    for sign in (-1, 1):
        bd = bands[sign]
        out = bd.outward()
        v_out = (vs[0] - OUT_MARGIN) if out < 0 else (vs[1] + OUT_MARGIN)
        z_top = base_top + TRIM_TOP
        segs = [
            ProfileSeg2("line", Point2(bd.lip_pp, t_lo), Point2(v_out, t_lo)),
            ProfileSeg2("line", Point2(v_out, t_lo), Point2(v_out, z_top)),
            ProfileSeg2("line", Point2(v_out, z_top), Point2(bd.lip_pp, z_top)),
            ProfileSeg2("line", Point2(bd.lip_pp, z_top), Point2(bd.lip_pp, t_lo)),
        ]
        f = _mk_pocket(_as_ccw(segs), axis, u0, u1 - u0, "recess:lip_trim",
                       bd.ev + deck.ev, pvid)
        f.id = part.next_id()
        part.add(f)
        n += 1
        rep.notes.append(
            f"侧凹槽 ④唇外盒切（{_side_name(sign)}）：POCKET {axis}∈[{u0:.2f},"
            f"{u1:.2f}]（长 {u1 - u0:.2f}）到视图边界外 {OUT_MARGIN:.1f} "
            f"z∈[{t_lo:.2f},{z_top:.2f}]（基体轮廓残留的假料）")
    # ⑥ 端块外柱面（裙）：甲板末端 → 端壁西面 之间的端块，外侧按剖面大圆裁圆角
    skirt = _read_skirt(d, svid, frS, dir_name, (south.lip_pp, north.lip_pp),
                        center, t_lo)
    east = _read_end_face(d, pvid, frP, south.lip_pp, north.lip_pp, u1)
    if skirt is not None and east is None:
        rep.notes.append(
            "侧凹槽 ⑥端块裙：剖面读到外凸大圆但俯视里找不到端壁西面（甲板末端"
            "之东的可见全宽 ∥v 线）⇒ 不建（窗口东界不明，不猜）")
    if skirt is not None and east is not None:
        r_sk, ca_sk, cb_sk, h_sk = skirt
        xe, h_x = east
        z_top = base_top + TRIM_TOP
        for sign in (-1, 1):
            bd = bands[sign]
            lip_a = bd.lip_pp
            s_lip = bd.lip_pp - ca_sk
            s_lo = t_lo - cb_sk
            if r_sk * r_sk <= s_lip * s_lip or r_sk * r_sk <= s_lo * s_lo:
                rep.notes.append(
                    f"侧凹槽 ⑥端块裙（{_side_name(sign)}）：R{r_sk:g} 够不到唇线/"
                    "槽底 ⇒ 该侧不建")
                continue
            v_out = (vs[0] - OUT_MARGIN) if sign < 0 else (vs[1] + OUT_MARGIN)
            pE = Point2(lip_a, cb_sk + math.sqrt(r_sk * r_sk - s_lip * s_lip))
            pF = Point2(ca_sk + sign * math.sqrt(r_sk * r_sk - s_lo * s_lo), t_lo)
            sa = math.atan2(pE.y - cb_sk, pE.x - ca_sk)
            ea = math.atan2(pF.y - cb_sk, pF.x - ca_sk)
            ccw = ((ea - sa) % (2.0 * math.pi)) <= math.pi
            segs = [
                ProfileSeg2("line", pF, Point2(v_out, t_lo)),
                ProfileSeg2("line", Point2(v_out, t_lo), Point2(v_out, z_top)),
                ProfileSeg2("line", Point2(v_out, z_top), Point2(lip_a, z_top)),
                ProfileSeg2("line", Point2(lip_a, z_top), pE),
                ProfileSeg2("arc", pE, pF, center=Point2(ca_sk, cb_sk),
                            radius=r_sk, ccw=ccw, sa=sa, ea=ea),
            ]
            f = _mk_pocket(_as_ccw(segs), axis, u1, xe - u1, "recess:skirt_trim",
                           bd.ev + (h_sk, h_x), pvid)
            f.id = part.next_id()
            part.add(f)
            n += 1
            rep.notes.append(
                f"侧凹槽 ⑥端块裙（{_side_name(sign)}）：POCKET {axis}∈[{u1:.2f},"
                f"{xe:.2f}]（长 {xe - u1:.2f}）唇外（|{band_ax}|≥{lip_a:.2f}）"
                f"槽底（{t_lo:.2f}）以上、R{r_sk:g} 柱面外全删"
                f"（圆心 {band_ax}={ca_sk:.2f}/{dir_name}={cb_sk:.2f}，弧 {h_sk}，"
                f"端壁西面 {h_x}）")

    # ⑤ 壁根月牙（**最后**：凸圆角复用的是铣刀在腔壁上留下的 R 圆角）
    if deck.r_f > MIN_R:
        for sign in (-1, 1):
            bd = bands[sign]
            for a0, a1 in deep[sign]:
                circle_c = bd.wall_pp + math.copysign(deck.r_f, bd.outward())
                prof = _crescent(bd.wall_pp, circle_c, deck.r_f, t_lo)
                oo = ir_point(Point3(0.0, 0.0, 0.0), axis, 0.0, 0.0, a0 - OVER)
                f = Feature(
                    id=FeatureId(-1),
                    type=Claim(FeatureType.BASE, "recess:wall_root_round",
                               Tier.PROJECTION, deck.ev),
                    params={"dir": mk_claim(axis, "recess:wall_root_round",
                                            Tier.PROJECTION, deck.ev),
                            "length": mk_claim(a1 - a0 + 2.0 * OVER,
                                               "recess:wall_root_round",
                                               Tier.PROJECTION, deck.ev),
                            "profile": Claim(prof, "recess:wall_root_round",
                                             Tier.PROJECTION, deck.ev),
                            "origin": mk_claim(oo, "recess:wall_root_round",
                                               Tier.PROJECTION, deck.ev)},
                    placement=Claim(oo, "recess:wall_root_round",
                                    Tier.PROJECTION, deck.ev),
                    source_view=svid, evidence=list(deck.ev),
                )
                f.id = part.next_id()
                f.depends_on.extend(cuts[sign])   # 切完再补料：浅腔端会削到过冲段
                part.add(f)
                n += 1
        rep.notes.append(
            f"侧凹槽 ⑤壁根圆角 R{deck.r_f:g}：BASE ×{2 * len(deep[-1])}"
            f"（{axis}∈段界±{OVER}，depends_on 深腔+浅腔 ⇒ 最后 fuse；"
            "月牙止于段界会让验收点落在面上）")

    rep.notes.append(
        f"侧凹槽：俯视 {pvid} + 剖面 {svid} 读出 壁面 |{band_ax}|="
        f"{south.b:.2f}/{north.b:.2f}、唇线 |{band_ax}|={south.w:.2f}/"
        f"{north.w:.2f}、端面 {axis}="
        + "/".join(f"{u:.2f}" for u in south.ends)
        + f"；剖面读 槽底 {t_lo:.2f}、斜肩 ({south.b:.0f}→{s_b:.2f} / "
        f"{south.w:.0f}→{s_w:.2f})、甲板顶 {deck.deck_top:.2f}、平台 "
        f"{deck.p_bot:.2f}..{deck.p_top:.2f}、壁根 R{deck.r_f:g} ⇒ 深段 "
        f"{[(f'{a:.1f}', f'{b:.1f}') for a, b in deep[-1]]}")
    return n
