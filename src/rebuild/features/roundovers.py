# -*- coding: utf-8 -*-
"""顶边凸圆角 + 分区根部凹圆角（阶段 7 第四笔）。

## 缺口在哪

高度分解落地后，基体是"降下来的直角棱柱 + 抬升区并集"——**处处是尖角**。
bracket 金值件的外长边顶棱是 **R3 凸圆角**、抬升区与基体顶面的交角还有
**R3 根部凹圆角**（凹的那条在体育场右端盘的壁上、±58° 一圈）。两者都读不出
的问题不在轮廓——轮廓给的是**未倒角**的直壁；圆角只体现在两处图纸信号里，
而这两条线此前没人看：

- 凸圆角：正视图里一条 **z = 顶面 − R** 的水平线 —— 圆角曲面与直壁的**切线**
  （bracket：z=21 那条，run [21.21, 161.00]，71 段全可见）
- 凹圆角：正视图里一条 **z = 顶面 + R** 的水平线 —— 圆角曲面与抬升区外壁的
  **切线**（bracket：z=27 的 [82.66, 92.00]，9.34 可见；侧视图同一层
  [134.13, 167.98] = 151.05 ± 16.92，两条独立读数互证 —— 见下方"角域反解"）

实测两端分工（`_z9_gfaces.py` 金值面清单）：凸圆角是两条柱面 r3 轴心 z=21、
凹陷圆角是环面 R23 r3 心 (72.01, 151.06, 27.00)，体积预算 −452.63 / +93.0，
与高度分解后的基线（192,342.70 vs 金值 191,987.84）对得上账。

## 读法

**凸（:func:`top_roundovers`）**：基体带内 (t_lo, base_top) **覆盖最宽的一条
水平层线** ⇒ t_r、R = base_top − t_r；把轮廓环里**共线连续的直段**并成 run，
再过四道门（每道都对着一个实测反例，缺一个就会多倒）：

| 门 | 判据 | 挡掉什么 |
|----|------|----------|
| A | 相邻直段方向差 ≤ ``MERGE_ANG_DEG`` | 把 3 段浅折线并成 1 条真 run（也把 90° 转角断开） |
| B | run 方向 ∥ ±b1（≤ ``AXIS_ANG_DEG``） | 弧段、斜段、挂耳台阶 |
| C | run 的 b1 跨度 ⊆ 该层图纸**可见** run | 挂耳那条 y=141.05 长 run（图纸只画到 188.42） |
| D | u 区间内环的其余点都在 run 直线的**材料侧** | 内部斜台（段 106，它被图纸 run 盖住） |

四道门合起来在 bracket 上精确复现金值实测的 6 段 {114,115,116,119,120,121}
（两条 run，上壁 y≈176.5→173.9、下壁 y≈128.2→125.6），一条不多一条不少。

**凹（:func:`raise_root_fillets`）**：base_top 与**最低抬升区顶**之间那条层线
⇒ t_r2、R = t_r2 − base_top；对每个 material 抬升区（圆盘 / 长圆端盘），把该层
图纸 run 投到分区足迹上——run 落在足迹投影**内部**且一端贴住投影轮廓端 ⇒
由另一端反解角域 θm = acos((run 端 − 圆心) / r)。bracket 上
[82.66, 92.00] → θm = 57.8°，与侧视图 [134.13, 167.98] 的
asin(16.92/20) = 57.8° 独立吻合（金值面清单实测同值）。

⚠️ 切线壁（体育场两段直壁）**不建**：那里基体板自己的顶边圆角把材料吃掉，
根部圆角退化成一条 < 1.5mm 宽的过渡（金值里是 B-spline 混合面，z 只到
25.46）。盒探针实测那两个带上 z>24 的料只多 0.35mm³/35mm —— 记账，不猜。

## 与发射器的契约

两条都是 ``FILLET``（LAYER 4），``depends_on`` 指向基体：

- ``mode="top_round"``：``radius``（FILLET 契约的必需项）+ ``segments``（基体
  轮廓段下标）；placement = **基体的 placement**（同一 (a, b) 坐标系）。发射器
  从 ``depends_on`` 找到基体，取那几段的真实几何（直线 → ``MakePrism``、
  弧 → ``MakeRevol``）扫剖面成刀、**减**。
- ``mode="root"``：``radius`` + ``wall_r``（被圆角壁半径）+ ``theta_deg``（角域，
  绕 placement 轴、自 b1 轴起算）；placement 的 origin = 圆心 × z=base_top、
  方向 = 拉伸方向。刀 = 剖面绕轴 ``MakeRevol`` 后**并**上去。

两条都走"工具式"（扫剖面）而不是 `BRepFilletAPI_MakeFillet` —— 后者在本零件
任何子集上都 `IsDone()=False`（`_z9_round*.py` 六轮实验，含两次挂死）。

依赖：``..model.*``、``..evidence``、``..views.*``、``.height_zones``、
``.library``、``.recognizer``（纯数据 + ezdxf/numpy，跑默认 python）。
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING

from ..model.claim import Claim, Tier
from ..model.feature_tree import Feature, FeatureType
from ..model.geom import Point3
from ..model.geom2d import Profile2
from ..model.ids import FeatureId
from .height_zones import PP_CLUSTER, Seg, _pp_groups, frame_lines
from .library import axis_from_point, ir_point, mk_claim, profile_plane
from .recognizer import _PLANE_AXES

if TYPE_CHECKING:
    from ..evidence.dxf_reader import Drawing
    from ..views.correspondence import CorrespondenceResult, ViewFrame
    from .height_zones import HeightPlan, Zone
    from .recognizer import RecognizeReport

__all__ = ["raise_root_fillets", "top_roundovers"]

#: 门 A：相邻直段方向差 ≤ 它 ⇒ 同一条 run（度）。bracket 外长边是三段浅折线
#: （整段方向变化 ≈ 2.3°），15 并得起来、又能把 90° 转角断开。
MERGE_ANG_DEG = 15.0
#: 门 B：run 方向与 ±b1 的夹角上限（度）
AXIS_ANG_DEG = 15.0
#: 门 C：图纸 run 覆盖轮廓 run 时的两端容差（mm）
COVER_TOL = 1.0
#: 门 D：材料侧判据的容差（mm）
SIDE_TOL = 0.30
#: 层线碎段并成 run 时的最大间隙（mm）
GAP_TOL = 0.80
#: 选"内部层"时距基体带两端的最近距离（mm）——贴着端点的是轮廓自身的边
LEVEL_EDGE_MIN = 0.80
#: 层线要覆盖基体 b1 跨度的这个比例，才认它是"整条顶边的切线"（挡掉孔台阶线）
LEVEL_COVER_MIN = 0.60
#: 凸圆角半径的合理范围（mm）——超出就不认这层
TOP_R_MIN, TOP_R_MAX = 0.30, 12.0
#: 根部圆角半径的合理范围（mm）
ROOT_R_MIN, ROOT_R_MAX = 0.50, 10.0
#: 根部圆角角域的半角范围（度）——太小是"run 塌成一点"，太大是"绕了整圈"
ROOT_HALF_MIN, ROOT_HALF_MAX = 12.0, 88.0
#: 判"run 贴住足迹轮廓端"的容差（mm）
END_TOL = 1.50


# ---------------------------------------------------------------------------
# 视图侧：层线读数
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class _LevelRun:
    """一条层线 run（沿 b1，模型坐标），带证据 handle。"""

    lo: float
    hi: float
    handles: tuple[str, ...]

    @property
    def span(self) -> float:
        return self.hi - self.lo


def _level_runs(d: "Drawing", frame: "ViewFrame", along: str, pp: float,
                role: str = "visible") -> list[_LevelRun]:
    """视图里沿 `along` 的直线段中层级 = `pp` 的那些，按角色并成 run。

    只收 ``Line2``（``frame_lines`` 已滤掉斜线与弧）——圆角切线与轴平行，
    斜线是别的结构（挂耳台阶、倒角）。
    """
    segs: list[Seg] = [s for s in frame_lines(d, frame, along)
                       if abs(s.pp - pp) <= PP_CLUSTER and s.role == role]
    segs.sort(key=lambda s: s.lo)
    out: list[_LevelRun] = []
    for s in segs:
        if out and s.lo <= out[-1].hi + GAP_TOL:
            prev = out.pop()
            out.append(_LevelRun(prev.lo, max(prev.hi, s.hi),
                                 prev.handles + (s.handle,)))
        else:
            out.append(_LevelRun(s.lo, s.hi, (s.handle,)))
    return out


def _elev_frames(corr: "CorrespondenceResult", dir_name: str,
                 b1_axis: str) -> list["ViewFrame"]:
    """``v`` 轴 = 拉伸方向、``u`` 轴 = 轮廓 b1 的视图（看得到"高"的那张）。"""
    return [fr for fr in corr.frames.values()
            if fr.v_axis == dir_name and fr.u_axis == b1_axis
            and b1_axis not in fr.broken_axes]


def _inner_levels(d: "Drawing", frame: "ViewFrame", along: str,
                  lo: float, hi: float) -> list[float]:
    """(lo, hi) 之间有**可见**线段的层高，升序。"""
    if hi <= lo:
        return []
    segs = frame_lines(d, frame, along)
    out: list[float] = []
    for pp in sorted(_pp_groups(segs).keys()):
        if not (lo <= pp <= hi):
            continue
        if any(abs(s.pp - pp) <= PP_CLUSTER and s.role == "visible" for s in segs):
            out.append(pp)
    return out


# ---------------------------------------------------------------------------
# 门 A~D：轮廓环 → 被倒圆的 run
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class _Run:
    """轮廓环里一条共线连续的直段 run（模型坐标，u = b1、v = b2）。"""

    segs: tuple[int, ...]
    u0: float
    v0: float
    u1: float
    v1: float
    ang: float                      # 方向角（弧度），[-π, π)

    @property
    def span(self) -> float:
        return abs(self.u1 - self.u0)


def _ang_diff(a: float, b: float) -> float:
    d = (a - b) % (2 * math.pi)
    return d - 2 * math.pi if d > math.pi else d


def _prof_points(prof: Profile2, lo: float, hi: float, org_a: float, org_b: float,
                 n_arc: int = 16) -> list[tuple[float, float]]:
    """轮廓上 u ∈ [lo, hi] 的**模型坐标**采样点（弧按角采样 + 补圆的四极值点）。

    门 D 靠它判"u 区间里其余点是否都在 run 的材料侧"——只取段端点会漏弧凸出。
    ⚠️ ``lo/hi`` 是模型坐标，轮廓段存的是相对 placement 的局部坐标（实测忘加
    平移会把 106 那条内棱放进来、把 119~121 那条真 run 挡掉，一进一出）。
    """
    out: list[tuple[float, float]] = []

    def keep(x: float, y: float) -> None:
        if lo - 1e-9 <= x + org_a <= hi + 1e-9:
            out.append((x + org_a, y + org_b))

    for s in prof.segments:
        if s.kind != "arc":
            for p in (s.p1, s.p2):
                keep(p.x, p.y)
            continue
        cx, cy, r = s.center.x, s.center.y, s.radius
        span = ((s.ea - s.sa) % (2 * math.pi)) if s.ccw else \
               -((s.sa - s.ea) % (2 * math.pi))
        for k in range(n_arc + 1):
            t = s.sa + span * k / n_arc
            keep(cx + r * math.cos(t), cy + r * math.sin(t))
        for x, y in ((cx + r, cy), (cx - r, cy), (cx, cy + r), (cx, cy - r)):
            keep(x, y)
    return out


def _line_runs(prof: Profile2, org_a: float, org_b: float) -> list[_Run]:
    """门 A：连续直段（方向差 ≤ ``MERGE_ANG_DEG``）并成 run，换到模型坐标。"""
    segs = list(prof.segments)
    n = len(segs)
    if n < 3:
        return []
    tol = math.radians(MERGE_ANG_DEG)
    out: list[_Run] = []
    cur: list[int] = []

    def flush() -> None:
        if not cur:
            return
        s0, s1 = segs[cur[0]], segs[cur[-1]]
        u0, v0 = org_a + s0.p1.x, org_b + s0.p1.y
        u1, v1 = org_a + s1.p2.x, org_b + s1.p2.y
        if math.hypot(u1 - u0, v1 - v0) < 1e-9:
            cur.clear()
            return
        out.append(_Run(tuple(cur), u0, v0, u1, v1,
                        math.atan2(v1 - v0, u1 - u0)))
        cur.clear()

    def dir_of(i: int) -> float:
        s = segs[i]
        return math.atan2(s.p2.y - s.p1.y, s.p2.x - s.p1.x)

    for i in range(n):
        if segs[i].kind != "line":
            flush()
            continue
        if cur and abs(_ang_diff(dir_of(cur[-1]), dir_of(i))) > tol:
            flush()
        cur.append(i)
    flush()
    return out


# ---------------------------------------------------------------------------
# 凸：基体顶边圆角
# ---------------------------------------------------------------------------

def top_roundovers(d: "Drawing", corr: "CorrespondenceResult", base: Feature,
                   plan: "HeightPlan | None", rep: "RecognizeReport"
                   ) -> list[Feature]:
    """基体顶边的凸圆角（R 由基体带内覆盖最宽的层线读出）。

    返回 [] 是常态（多数零件不画这条切线，或轮廓不是 Profile2）。
    """
    prof_c = base.params.get("profile")
    prof = prof_c.value if prof_c is not None else None
    dir_name = base.params["dir"].value if "dir" in base.params else None
    if not isinstance(prof, Profile2) or not isinstance(dir_name, str):
        return []
    b1_axis, _b2 = _PLANE_AXES[dir_name]
    b1v, b2v = profile_plane(dir_name)
    axis_vec = b1v.cross(b2v)
    org = base.placement.value.as_vector          # Point3 → Vector3（点乘用）
    org_t = org.dot(axis_vec)
    base_top = org_t + float(base.params["length"].value)
    t_lo = plan.t_lo if plan is not None else org_t
    frames = _elev_frames(corr, dir_name, b1_axis)
    if not frames:
        return []
    fr = frames[0]
    org_a, org_b = org.dot(b1v), org.dot(b2v)

    # ---- 基体带内覆盖最宽的一条层线 ⇒ t_r、R ----
    bb = prof.bbox()
    prof_span = bb.xmax - bb.xmin
    best: tuple[float, list[_LevelRun]] | None = None
    for pp in _inner_levels(d, fr, b1_axis, t_lo + LEVEL_EDGE_MIN,
                            base_top - LEVEL_EDGE_MIN):
        runs = _level_runs(d, fr, b1_axis, pp)
        cover = sum(x.span for x in runs)
        if cover < prof_span * LEVEL_COVER_MIN:
            continue
        if best is None or cover > sum(x.span for x in best[1]):
            best = (pp, runs)
    if best is None:
        return []
    t_r, runs = best
    r = base_top - t_r
    if not (TOP_R_MIN < r < TOP_R_MAX):
        return []
    drawn = [(x.lo, x.hi) for x in runs]
    handles = tuple(h for x in runs for h in x.handles)

    # ---- 门 A~D ----
    ccw = prof.signed_area() > 0
    hit: list[int] = []
    for run_ in _line_runs(prof, org_a, org_b):
        ang = abs(_ang_diff(run_.ang, 0.0))
        if min(ang, abs(math.pi - ang)) > math.radians(AXIS_ANG_DEG):
            continue                                           # 门 B
        u_lo, u_hi = sorted((run_.u0, run_.u1))
        if not any(lo - COVER_TOL <= u_lo and u_hi <= hi + COVER_TOL
                   for lo, hi in drawn):
            continue                                           # 门 C
        # 门 D：u 区间内其余点必须都在 run 直线的一侧（= 它是外边界不是内棱）
        du, dv = run_.u1 - run_.u0, run_.v1 - run_.v0
        ln = math.hypot(du, dv)
        nx, ny = -dv / ln, du / ln                            # 前进方向的左法向
        sgn = 1.0 if ccw else -1.0                            # CCW ⇒ 材料在左
        bad = False
        tested = False
        for px, py in _prof_points(prof, u_lo, u_hi, org_a, org_b):
            d_ = sgn * ((px - run_.u0) * nx + (py - run_.v0) * ny)
            if d_ < -SIDE_TOL:
                bad = True
                break
            tested = tested or d_ > SIDE_TOL
        if bad or not tested:
            continue
        hit.extend(run_.segs)
    hit = sorted(set(hit))
    if not hit:
        rep.notes.append(
            f"顶边圆角：读到 R{r:g}（切线层 z={t_r:.2f}），但轮廓里没有段同时过"
            "四道门（共线 run / 方向 ∥ 轴 / 被该层图纸 run 覆盖 / 材料侧）")
        return []
    ev = tuple(dict.fromkeys(list(handles[:8]) + list(base.evidence[:1])))
    f = Feature(
        id=FeatureId(-1),
        type=Claim(FeatureType.FILLET, "projection:top_edge_tangent",
                   Tier.PROJECTION, ev),
        params={
            "radius": mk_claim(r, "projection:top_edge_tangent",
                               Tier.PROJECTION, ev),
            "mode": mk_claim("top_round", "projection:top_edge_tangent",
                             Tier.PROJECTION, ev),
            "segments": mk_claim(tuple(hit), "projection:top_edge_tangent",
                                 Tier.PROJECTION, ev),
        },
        placement=base.placement,
        depends_on=[base.id],
        source_view=fr.view_id,
        evidence=list(ev),
    )
    rep.notes.append(
        f"顶边圆角：R{r:g}（切线层 z={t_r:.2f}，图纸 run "
        + "、".join(f"[{lo:.2f},{hi:.2f}]" for lo, hi in drawn)
        + f"）⇒ 轮廓段 {hit} 倒圆")
    return [f]


# ---------------------------------------------------------------------------
# 凹：抬升区的根部圆角
# ---------------------------------------------------------------------------

def raise_root_fillets(d: "Drawing", corr: "CorrespondenceResult", base: Feature,
                       plan: "HeightPlan | None", rep: "RecognizeReport"
                       ) -> list[Feature]:
    """抬升区外壁与基体顶面交角处的凹圆角（R 由两者之间那条层线读出）。"""
    if plan is None or not plan.raises:
        return []
    dir_name = plan.dir_name
    b1_axis, _b2 = _PLANE_AXES[dir_name]
    b1v, b2v = profile_plane(dir_name)
    axis_vec = b1v.cross(b2v)
    base_top = plan.base_top
    top_min = min(z.t_hi for z in plan.raises)
    frames = _elev_frames(corr, dir_name, b1_axis)
    if not frames:
        return []
    fr = frames[0]
    out: list[Feature] = []
    for pp in _inner_levels(d, fr, b1_axis, base_top + LEVEL_EDGE_MIN,
                            top_min - LEVEL_EDGE_MIN):
        r = pp - base_top
        if not (ROOT_R_MIN < r < ROOT_R_MAX):
            continue
        runs = _level_runs(d, fr, b1_axis, pp)
        made = [f for f in (_root_for_zone(fr, z, runs, r, dir_name, base_top,
                                           base)
                            for z in plan.raises) if f is not None]
        if made:
            out.extend(made)
            break                       # 只用最靠下的那条能量出来的层
    if not out:
        rep.notes.append(
            f"根部圆角：基体顶 {base_top:.2f} 与最低抬升区顶 {top_min:.2f} 之间"
            "没有可用的层线 ⇒ 未读（不猜）")
    return out


def _root_for_zone(fr: "ViewFrame", z: "Zone", runs: list[_LevelRun], r: float,
                   dir_name: str, base_top: float, base: Feature) -> Feature | None:
    """一个抬升区：某层线 run 落在足迹投影内且贴住轮廓端 ⇒ 反解角域。"""
    if z.kind not in ("disc", "stadium") or not z.circles:
        return None
    cr0 = z.circles[0][2]
    u_lo = min(c[0] for c in z.circles) - cr0
    u_hi = max(c[0] for c in z.circles) + cr0
    if u_hi - u_lo <= 2 * END_TOL:
        return None
    for lr in runs:
        if not (u_lo - COVER_TOL <= lr.lo and lr.hi <= u_hi + COVER_TOL):
            continue
        if lr.span >= (u_hi - u_lo) - 2 * END_TOL:
            continue                   # 整条都画 = 那是抬升区自己的顶棱，不是圆角
        for sign in (+1.0, -1.0):
            end = u_hi if sign > 0 else u_lo
            near = lr.hi if sign > 0 else lr.lo
            other = lr.lo if sign > 0 else lr.hi
            if abs(near - end) > END_TOL:
                continue
            # 圆心取贴住那一头的端盘（stadium 两个等径圆，disc 只有一个）
            cs = sorted(z.circles, key=lambda c: c[0])
            cx, cy, cr = cs[-1] if sign > 0 else cs[0]
            q = (other - cx) / cr if sign > 0 else (cx - other) / cr
            if not (-1.0 <= q <= 1.0):
                continue
            half = math.degrees(math.acos(max(-1.0, min(1.0, q))))
            if not (ROOT_HALF_MIN <= half <= ROOT_HALF_MAX):
                continue
            ev = tuple(dict.fromkeys(list(lr.handles[:4]) + list(z.evidence[:1])))
            o = ir_point(Point3(0.0, 0.0, 0.0), dir_name, cx, cy, base_top)
            t0 = -half if sign > 0 else 180.0 - half
            t1 = half if sign > 0 else 180.0 + half
            return Feature(
                id=FeatureId(-1),
                type=Claim(FeatureType.FILLET, "projection:root_fillet_tangent",
                           Tier.PROJECTION, ev),
                params={
                    "radius": mk_claim(r, "projection:root_fillet_tangent",
                                       Tier.PROJECTION, ev),
                    "mode": mk_claim("root", "projection:root_fillet_tangent",
                                     Tier.PROJECTION, ev),
                    "wall_r": mk_claim(cr, "projection:zone_contour",
                                       Tier.PROJECTION, ev),
                    "theta_deg": mk_claim(
                        (t0, t1), "projection:root_fillet_tangent",
                        Tier.PROJECTION, ev),
                },
                placement=Claim(axis_from_point(o, dir_name),
                                "projection:root_fillet_tangent",
                                Tier.PROJECTION, ev),
                depends_on=[base.id],
                source_view=fr.view_id,
                evidence=list(ev),
            )
    return None
