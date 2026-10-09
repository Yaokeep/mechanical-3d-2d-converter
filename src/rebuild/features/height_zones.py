# -*- coding: utf-8 -*-
"""高度分解 —— 俯视轮廓内的**分区高度**（阶段 7）。

## 缺口在哪

``base_feature`` 读到的基体 = **俯视轮廓环 × 该向全跨度**，一次拉伸。
对板类零件（block_3view / plate_100x60）这没错：轮廓内每点同一个高度。
但 bracket 这类零件在俯视轮廓内**分区不同高**：臂到 z=30、腹板到 24、
环盘到 46、挂耳悬在 12..36。高度信号不在俯视图里，在**正视图的剪影**里，
旧读法完全不看 —— bracket 基体单项 367,301 vs 全体金值 191,987.8（+91%）。

## 读法（两路证据的乘积，缺一不分解）

1. **分区从哪来** —— 正对轮廓面那个视图（俯视）里的圆（已由跨视图对应升成
   ``CylinderHint``）：先按**轴共线**分组，组内**按半径降序奇偶定角色**
   （最外 = 材料边界、次外 = 孔、再次 = 材料…）。等径的**材料**圆两两相配
   ⇒ 切线凸包（长圆/跑道面）；等径的**孔**圆两两相配 ⇒ 长圆槽；落单的材料圆
   ⇒ 圆盘。相配前要用**图纸自己的切线**核实（两圆之间真有那两条平行线才并，
   否则是"两个独立凸台"——见 ``_stadium``）。
2. **每区多高** —— 侧视图（``v_axis == 拉伸方向`` 且 ``u_axis == 轮廓 b1``）
   的**可见轮廓环**（``views/ring`` 通道）逐点求上下包络，对分区在 b1 上的
   投影取 ``top = min(包络顶)``、``bot = max(包络底)``。取 min/max 的道理：
   分区在 b1 上投影时只有它自己"当顶/当底"的那几列才是它的高度，别处分区
   更高/更低（挂耳伸不到环盘顶上，故耳区读数 36 来自环盘伸不到的那一段）。
   基体降到**轮廓区间内的最低顶面**，其余分区自它向上抬。

## 不分解的条件（一律记账，不猜）

- 剪影沿轮廓 b1 **平**（顶面极差 ≤ ``UNIFORM_TOL``）⇒ 板件，一次拉伸就是
  对的（block_3view / plate_100x60 走这条，逐位不变）。
- 剪影不平、但轮廓内**没有轴 ∥ 拉伸方向的圆**可作分区依据 ⇒ 记"高度分解
  未做"（l_bracket 的 L 形已由**它自己那个视图**的轮廓环表达，四棱锥走锥化）。
- 基体带 ``taper_scale``（锥化）⇒ 另一族读法，不动。
- 基体是 REVOLVE / 轮廓外沿是圆 ⇒ 回转体通道先接管（本模块不参与）。

## 与发射器的契约（全部用现有表达，不加新参数）

- **抬升区** → ``BASE`` 段：``dir`` + ``length = t_hi − base_top`` + ``profile``
  + ``origin = ir_point(0, dir, 0, 0, base_top)``。两个发射器都"自 origin 的
  沿轴坐标起、沿 +轴 拉 length"，多块 BASE 是并集（``_add_material`` 首块即
  基体、之后 Fuse ✓）。
  ⚠️ 分区轮廓的 (a, b) 写**绝对模型坐标**（origin 的面内分量取 0）—— 与基体
  自己"相对 origin"的口径不同：基体的 origin 是包围盒角点，这里刻意取零件原点。
- **长圆槽 / 矩形腔** → ``POCKET``：``profile`` + ``depth`` + ``axial_at = 腔底``。
- **圆孔** → ``HOLE``：``radius`` + ``depth`` + ``axial_at = 孔口``；通/盲由
  ``recognizer.derive_through`` 拿**图纸总跨度**（不是分解后基体的 height）比出。

## 侧轴圆柱（挂耳）的轴向位置

轴 ⟂ 拉伸方向的圆柱（bracket 的挂耳 r12 沿 y）原先只有半径与"轮廓线对间距"
（实测 3.00 —— 那是薄壁缘的棱，HLR 可见优先把孔壁虚线吃掉了），轴向位置缺省
按 0 起 ⇒ 挂耳建在 y∈[0,3]、整件 bbox 差 +125.55。正读法在
``side_axis_spans``：**轴向上的那个视图**里，圆柱的轮廓是一对**平行于轴**的线，
垂直位置在 ``c ⟂ ± r``（c、r 都来自圆本身），这一对线沿轴的跨度 = 轴向区间。

依赖：``..model.*``、``..evidence``、``..views.*``、``.library``、``.recognizer``
（纯数据 + ezdxf/numpy 口径，跑默认 python）。
"""
from __future__ import annotations

import math
from bisect import bisect_left, bisect_right
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Iterable, NamedTuple

from ..model.claim import Claim, Tier
from ..model.feature_tree import Feature, FeatureType, Part
from ..model.geom import Axis3, Point3, Vector3
from ..model.geom2d import Line2, Point2, Profile2, ProfileSeg2
from ..model.ids import FeatureId
from ..model.questions import OpenQuestion, Question
from ..views.correspondence import CorrespondenceResult, CylinderHint, ViewFrame
from ..views.ring import extract_ring
from .library import ir_point, mk_claim
from .recognizer import AXIS_POS_TOL, _PLANE_AXES, _axis_name

if TYPE_CHECKING:
    from ..evidence.dxf_reader import Drawing
    from .recognizer import RecognizeReport

__all__ = ["Band", "HeightPlan", "PPGroup", "Seg", "Zone", "build_bands",
           "decompose", "frame_lines", "side_axis_spans"]

#: 剪影包络的采样步长（mm）。轮廓弧按弧长采样，故 0.3 在 r25.5 上 ≈ 0.67°
BAND_STEP = 0.30
#: 查询分区高度时两端各收一点：分区的 b1 端点是弧的切点，端列可能混入邻区
QUERY_SHRINK = 0.50
#: 剪影"平不平"的判据：轮廓区间内顶面极差 ≤ 它 ⇒ 不分解（mm）
UNIFORM_TOL = 0.80
#: 抬升判据：分区顶高于基体顶 > 它才建抬升（mm）
RAISE_TOL = 0.20
#: 分区高度与剪影层级互认的容差（mm）
HEIGHT_TOL = 0.80
#: 等径判据（mm）
SAME_R_TOL = 0.05
#: 相配核实：切线要覆盖两圆中点附近这一段（两端各收这么多，mm）
MATE_SHRINK = 0.60
#: 轴平行线段的定位容差（mm）
LINE_TOL = 0.60
#: 切线段碎段之间的最大间隙（超过它就当两条独立线，mm）
MERGE_GAP = 0.80
#: 侧轴圆柱的轴向区间下限（太短说明读到的是残段而不是轮廓，mm）
SIDE_MIN_SPAN = 1.0
#: 按 pp 归组时的同位置容差（轮廓环焊接会把 150.055 吸到 150.050，mm）
PP_CLUSTER = 0.02

_DIRS: dict[str, tuple[float, float, float]] = {
    "x": (1.0, 0.0, 0.0), "y": (0.0, 1.0, 0.0), "z": (0.0, 0.0, 1.0),
}


def _coord(p: Point3, axis: str) -> float:
    return {"x": p.x, "y": p.y, "z": p.z}[axis]


def _dir_vec(name: str) -> Vector3:
    x, y, z = _DIRS[name]
    return Vector3(x, y, z)


def _view(d: "Drawing", vid: str):
    return next((v for v in d.views if v.id == vid), None)


# ---------------------------------------------------------------------------
# 剪影包络
# ---------------------------------------------------------------------------

def _sample(seg: ProfileSeg2, step: float) -> Iterable[tuple[float, float]]:
    """沿轮廓段密采样（直线按长度、弧按弧长），产出视图坐标点。"""
    if seg.kind != "arc":
        dx = seg.p2.x - seg.p1.x
        dy = seg.p2.y - seg.p1.y
        n = max(1, min(4000, int(math.ceil(math.hypot(dx, dy) / step))))
        for i in range(n + 1):
            t = i / n
            yield (seg.p1.x + dx * t, seg.p1.y + dy * t)
        return
    if seg.center is None or seg.radius <= 1e-9:
        return
    c, r = seg.center, seg.radius
    a0 = math.atan2(seg.p1.y - c.y, seg.p1.x - c.x)
    a1 = math.atan2(seg.p2.y - c.y, seg.p2.x - c.x)
    tau = 2.0 * math.pi
    span = ((a1 - a0) % tau) if seg.ccw else ((a0 - a1) % tau)
    n = max(2, min(4000, int(math.ceil(r * span / step))))
    sgn = 1.0 if seg.ccw else -1.0
    for i in range(n + 1):
        q = a0 + sgn * span * i / n
        yield (c.x + r * math.cos(q), c.y + r * math.sin(q))


@dataclass(frozen=True)
class Band:
    """一个侧视图的剪影包络：b1 → (顶, 底)，全为**模型坐标**。

    ``xs`` 升序，与 ``tops``/``bots`` 对齐。一个 b1 上的顶/底 = 该列剪影沿
    拉伸方向的上下极值（轮廓环闭合，故每列一般两点）。
    """

    view_id: str
    u_axis: str
    v_axis: str
    xs: tuple[float, ...]
    tops: tuple[float, ...]
    bots: tuple[float, ...]

    def __len__(self) -> int:
        return len(self.xs)

    def _idx(self, lo: float, hi: float, shrink: float) -> tuple[int, int]:
        i = bisect_left(self.xs, lo + shrink)
        j = bisect_right(self.xs, hi - shrink)
        if j <= i:
            i, j = bisect_left(self.xs, lo), bisect_right(self.xs, hi)
        return i, j

    def tops_in(self, lo: float, hi: float, shrink: float = QUERY_SHRINK
                ) -> list[float]:
        i, j = self._idx(lo, hi, shrink)
        return list(self.tops[i:j])

    def bots_in(self, lo: float, hi: float, shrink: float = QUERY_SHRINK
                ) -> list[float]:
        i, j = self._idx(lo, hi, shrink)
        return list(self.bots[i:j])

    def top_over(self, lo: float, hi: float,
                 shrink: float = QUERY_SHRINK) -> float | None:
        vs = self.tops_in(lo, hi, shrink)
        return min(vs) if vs else None

    def bot_over(self, lo: float, hi: float,
                 shrink: float = QUERY_SHRINK) -> float | None:
        vs = self.bots_in(lo, hi, shrink)
        return max(vs) if vs else None

    def levels(self, lo: float | None = None, hi: float | None = None,
               tol: float = 0.4) -> list[float]:
        """区间内的**层级**（顶/底合并聚类）—— 报告用，也是探针的对照。"""
        i, j = (0, len(self.xs)) if lo is None or hi is None else self._idx(lo, hi, 0.0)
        vals = sorted(list(self.tops[i:j]) + list(self.bots[i:j]))
        out: list[float] = []
        for v in vals:
            if not out or abs(v - out[-1]) > tol:
                out.append(v)
        return out


def build_band(d: "Drawing", frame: ViewFrame, view) -> Band | None:
    """把一个视图的可见轮廓环变成剪影包络（提不到环 ⇒ None）。"""
    res = extract_ring(d, view)
    if res.ring is None:
        return None
    cols: dict[int, list[float]] = {}
    for s in res.ring.segs:
        for x, y in _sample(s, BAND_STEP):
            k = int(math.floor(x / BAND_STEP))
            c = cols.get(k)
            if c is None:
                cols[k] = [y, y]
            else:
                if y < c[0]:
                    c[0] = y
                if y > c[1]:
                    c[1] = y
    if not cols:
        return None
    rows: list[tuple[float, float, float]] = []
    for k in sorted(cols):
        lo, hi = cols[k]
        xm = frame.u_to_model((k + 0.5) * BAND_STEP)
        a, b = frame.v_to_model(lo), frame.v_to_model(hi)
        rows.append((xm, max(a, b), min(a, b)))
    rows.sort(key=lambda r: r[0])
    return Band(view.id, frame.u_axis, frame.v_axis,
                tuple(r[0] for r in rows), tuple(r[1] for r in rows),
                tuple(r[2] for r in rows))


def merge_bands(bands: list[Band]) -> Band:
    """多个同向剪影取**并集**：同一 b1 上顶取大、底取小。

    两个视图看的是同一个实体，剪影本该一致；不一致时取并集 = 投影的并
    （沿深度求并），对"分区高度"这一问是保守且正确的一侧。
    """
    if len(bands) == 1:
        return bands[0]
    acc: dict[int, list[float]] = {}
    for b in bands:
        for x, t, bo in zip(b.xs, b.tops, b.bots):
            k = int(round(x / 0.05))
            c = acc.get(k)
            if c is None:
                acc[k] = [x, t, bo]
            else:
                c[1] = max(c[1], t)
                c[2] = min(c[2], bo)
    rows = sorted(acc.values(), key=lambda c: c[0])
    first = bands[0]
    return Band(first.view_id, first.u_axis, first.v_axis,
                tuple(r[0] for r in rows), tuple(r[1] for r in rows),
                tuple(r[2] for r in rows))


# ---------------------------------------------------------------------------
# 轴平行线段（相配核实 + 侧轴圆柱读数共用）
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Seg:
    """视图里**平行于某条模型轴**的直线段（模型坐标）。"""

    lo: float          # 沿该轴的区间
    hi: float
    pp: float          # 垂直于该轴的位置
    handle: str
    role: str
    #: 合并成这条的成员 handle（HLR 把一条切线打成碎段时不止一个）
    handles: tuple[str, ...] = ()

    def covers(self, a: float, b: float, tol: float = 0.5) -> bool:
        return self.lo <= a + tol and self.hi >= b - tol


def frame_lines(d: "Drawing", frame: ViewFrame, along: str) -> list[Seg]:
    """视图里所有平行于模型轴 ``along`` 的直线段（映射成该视图两轴的模型坐标）。

    斜线一律丢弃：正交视图里真斜线只可能是隐藏斜断面那种特殊词汇，不参与
    本通道（高度分解只认轴平行的轮廓线与切线）。
    """
    v = _view(d, frame.view_id)
    if v is None:
        return []
    if along == frame.u_axis:
        oth = frame.v_axis
    elif along == frame.v_axis:
        oth = frame.u_axis
    else:
        return []
    out: list[Seg] = []
    for h in v.evidence:
        e = d.by_handle(h)
        if e is None or not isinstance(e.geom, Line2):
            continue
        g = e.geom
        pu = {frame.u_axis: frame.u_to_model(g.start.x),
              frame.v_axis: frame.v_to_model(g.start.y)}
        pv = {frame.u_axis: frame.u_to_model(g.end.x),
              frame.v_axis: frame.v_to_model(g.end.y)}
        if abs(pu[oth] - pv[oth]) > 1e-6:
            continue                     # 不平行于 along
        lo, hi = sorted((pu[along], pv[along]))
        if hi - lo < 1e-9:
            continue
        out.append(Seg(lo, hi, (pu[oth] + pv[oth]) / 2.0, h, e.role.value))
    return out


def _tangent_lines(segs: list[Seg], pp: float, lo: float, hi: float
                   ) -> Seg | None:
    """在 ``pp`` 处找一条覆盖 ``lo..hi`` 的轴平行线（取最长者）。

    HLR 出图会把一条长切线按交点打成多段碎段（实测 bracket 的臂切线
    y=131.05 被拆成 28 段、长 0.3~1.4），所以先把共线（``pp`` 容差内、
    区间间隙 ≤ ``MERGE_GAP``）的段并成若干"连续run"，再看哪条 run 盖住
    ``lo..hi`` —— 判据是 run 的整体覆盖，不是单段。
    """
    hits = [s for s in segs if abs(s.pp - pp) <= LINE_TOL]
    if not hits:
        return None
    hits.sort(key=lambda s: s.lo)
    runs: list[list] = []                # [lo, hi, [Seg, ...]]
    for s in hits:
        if runs and s.lo <= runs[-1][1] + MERGE_GAP:
            runs[-1][1] = max(runs[-1][1], s.hi)
            runs[-1][2].append(s)
        else:
            runs.append([s.lo, s.hi, [s]])
    best: list | None = None
    for r in runs:
        if r[0] <= lo + MATE_SHRINK and r[1] >= hi - MATE_SHRINK:
            if best is None or (r[1] - r[0]) > (best[1] - best[0]):
                best = r
    if best is None:
        return None
    lo_r, hi_r, ss = best
    main = max(ss, key=lambda s: s.hi - s.lo)
    return Seg(lo_r, hi_r, main.pp, main.handle, main.role,
               tuple(dict.fromkeys(s.handle for s in ss)))


class PPGroup(NamedTuple):
    """一个 ``pp`` 位置的线组读数。

    ``lo``/``hi`` 是最长的那条连续 run（端面线用它）；``ulo``/``uhi`` 是该
    ``pp`` 上**所有** run 的并集（缝会把一条线劈成两段——挂耳销孔的壁线在
    缝处断开成 [141.055,150.055]+[152.055,161.055]，只看最长 run 会误判
    它只盖住一半）。
    """

    lo: float
    hi: float
    ulo: float
    uhi: float
    handles: tuple[str, ...]


def _pp_groups(segs: list[Seg], tol: float = PP_CLUSTER
               ) -> dict[float, PPGroup]:
    """按 ``pp`` 把轴平行线段归组，组内再按 ``MERGE_GAP`` 并成连续 run。

    两次归并各有其因：轮廓环焊接会把图纸的 150.055 吸到 150.050（µm 级抖动，
    取 ``PP_CLUSTER``）；HLR 出图又会把一条端面线按交点打成碎段（挂耳端面线
    实测 9 段）。**判长度必须用合并后的 run**——单段长度会把真端面线
    当成短残段筛掉（挂耳端面线单段最短 0.2，合并后 18.0）。
    """
    groups: list[list] = []              # [Σpp, n, [Seg, ...]]
    for s in sorted(segs, key=lambda t: t.pp):
        if groups and s.pp - (groups[-1][0] / groups[-1][1]) <= tol:
            groups[-1][0] += s.pp
            groups[-1][1] += 1
            groups[-1][2].append(s)
            continue
        groups.append([s.pp, 1, [s]])
    out: dict[float, PPGroup] = {}
    for gsum, gn, ss in groups:
        ss = sorted(ss, key=lambda t: t.lo)
        runs: list[list] = []            # [lo, hi, [Seg, ...]]
        for s in ss:
            if runs and s.lo <= runs[-1][1] + MERGE_GAP:
                runs[-1][1] = max(runs[-1][1], s.hi)
                runs[-1][2].append(s)
            else:
                runs.append([s.lo, s.hi, [s]])
        best = max(runs, key=lambda r: r[1] - r[0])
        out[round(gsum / gn, 4)] = PPGroup(
            best[0], best[1], min(r[0] for r in runs), max(r[1] for r in runs),
            tuple(dict.fromkeys(x.handle for r in runs for x in r[2])))
    return out


# ---------------------------------------------------------------------------
# 分区（圆 → 材料/切除）
# ---------------------------------------------------------------------------

@dataclass
class Zone:
    """俯视轮廓里的一块分区（模型系，绝对坐标）。

    ``circles`` 是 ``(a, b, r)``：``a``/``b`` 是轮廓平面 (b1, b2) 两轴上的
    坐标（不是硬编码的 x/y）—— 沿 x 拉伸的零件轮廓平面是 (y, z)。
    """

    role: str                    # "material" | "cut"
    kind: str                    # "disc" | "stadium"
    profile: Profile2
    circles: tuple[tuple[float, float, float], ...]   # (a, b, r) 绝对模型坐标
    hints: tuple[CylinderHint, ...]
    b1_lo: float
    b1_hi: float
    lead: str
    evidence: tuple[str, ...] = ()
    view_id: str = ""
    #: 实测高度（band 读数，沿拉伸方向）
    t_lo: float = 0.0
    t_hi: float = 0.0
    resolved: bool = False

    def __str__(self) -> str:
        cs = "、".join(f"({c[0]:.2f},{c[1]:.2f}) r{c[2]:.2f}" for c in self.circles)
        return (f"{self.role}/{self.kind} {cs} → z[{self.t_lo:.2f},{self.t_hi:.2f}]"
                f" {self.lead}")


def _quad_arc(c: tuple[float, float], r: float, a0: float, a1: float
              ) -> list[ProfileSeg2]:
    """把 [a0, a1]（跨度 π）的弧拆成两段 π/2 的**劣弧**。

    拆两半是给 SW 发射器的：``CreateArc(direction=False)`` = 取劣弧，恰好 π 的
    半圆两条都合法、方向歧义（见 ``sw_builder._sketch_profile`` docstring）
    —— π/2 段没有这个歧义。OCC 侧不在乎。
    """
    am = (a0 + a1) / 2.0
    out = []
    for s, e in ((a0, am), (am, a1)):
        p1 = Point2(c[0] + r * math.cos(s), c[1] + r * math.sin(s))
        p2 = Point2(c[0] + r * math.cos(e), c[1] + r * math.sin(e))
        out.append(ProfileSeg2("arc", p1, p2, center=Point2(*c), radius=r,
                               ccw=True, sa=s, ea=e))
    return out


def _disc_profile(cx: float, cy: float, r: float) -> Profile2:
    """圆盘：四段 π/2 逆时针弧（段序 = 遍历序，CCW 正面积）。"""
    segs: list[ProfileSeg2] = []
    for i in range(4):
        segs += _quad_arc((cx, cy), r, i * math.pi / 2, (i + 1) * math.pi / 2)
    return Profile2(tuple(segs))


def _stadium_profile(c1: tuple[float, float], c2: tuple[float, float], r: float
                     ) -> Profile2:
    """长圆（等径两圆的切线凸包）：两端帽（各 π，拆两段）+ 上下两条切线。"""
    ux, uy = c2[0] - c1[0], c2[1] - c1[1]
    n = math.hypot(ux, uy)
    if n < 1e-9:
        return _disc_profile(c1[0], c1[1], r)
    ux, uy = ux / n, uy / n
    nx, ny = -uy, ux                     # 左法向
    A1 = (c1[0] + r * nx, c1[1] + r * ny)
    B1 = (c1[0] - r * nx, c1[1] - r * ny)
    A2 = (c2[0] + r * nx, c2[1] + r * ny)
    B2 = (c2[0] - r * nx, c2[1] - r * ny)
    th = math.atan2(ny, nx)
    segs: list[ProfileSeg2] = []
    segs += _quad_arc(c1, r, th, th + math.pi)           # c1 端帽（走 −u 侧）
    segs.append(ProfileSeg2("line", Point2(*B1), Point2(*B2)))
    segs += _quad_arc(c2, r, th + math.pi, th + 2 * math.pi)   # c2 端帽（+u 侧）
    segs.append(ProfileSeg2("line", Point2(*A2), Point2(*A1)))
    return Profile2(tuple(segs))


def _groups(hints: list[CylinderHint], b1_axis: str, b2_axis: str
            ) -> list[list[CylinderHint]]:
    """轴共线的圆分组（组内按半径降序）。"""
    groups: list[list[CylinderHint]] = []
    reps: list[tuple[float, float]] = []
    for h in sorted(hints, key=lambda h: -h.radius):
        p = (_coord(h.axis.origin, b1_axis), _coord(h.axis.origin, b2_axis))
        hit = None
        for i, q in enumerate(reps):
            if math.hypot(p[0] - q[0], p[1] - q[1]) <= AXIS_POS_TOL:
                hit = i
                break
        if hit is None:
            groups.append([h])
            reps.append(p)
        else:
            groups[hit].append(h)
    for g in groups:
        g.sort(key=lambda h: -h.radius)
    return groups


def _zone(role: str, kind: str, circles: list[tuple[float, float, float]],
          hints: list[CylinderHint], profile: Profile2, b1_axis: str,
          lead: str, view_id: str) -> Zone:
    lo = min(c[0] - c[2] for c in circles)
    hi = max(c[0] + c[2] for c in circles)
    ev = tuple(dict.fromkeys(h for x in hints for h in x.evidence))
    return Zone(role, kind, profile, tuple(circles), tuple(hints), lo, hi,
                lead, ev, view_id)


def _hyphen(h: CylinderHint) -> str:
    o = h.axis.origin
    return f"({o.x:.2f},{o.y:.2f}) r{h.radius:.2f}"


def _ab(h: CylinderHint, b1_axis: str, b2_axis: str) -> tuple[float, float, float]:
    return (_coord(h.axis.origin, b1_axis), _coord(h.axis.origin, b2_axis),
            h.radius)


def _disc_zone(h: CylinderHint, role: str, b1_axis: str, b2_axis: str,
               view_id: str) -> Zone:
    a, b, r = _ab(h, b1_axis, b2_axis)
    return _zone(role, "disc", [(a, b, r)], [h], _disc_profile(a, b, r),
                 b1_axis, f"落单圆 {_hyphen(h)}", view_id)


def _stadium_zone(a: CylinderHint, b: CylinderHint, role: str, b1_axis: str,
                  b2_axis: str, segs: list[Seg], view_id: str) -> Zone | None:
    """等径两圆相配成**长圆** —— 但要图纸自己给出那两条切线才并。

    判据：切线在 ``⟂ = c ± r`` 处（c 取各圆心在 b2 上的坐标）、且沿 b1 把两圆
    之间那一段覆盖住（超出端帽各收 ``MATE_SHRINK``）。两圆心 b2 坐标不同时
    切线是斜的 ⇒ 轴平行线表里找不到 ⇒ 退回两个独立分区（"两个独立凸台"
    就是这么消解的 —— 不并就是少建一块连接料，多了会凭空加料）。
    """
    ca, cb = _ab(a, b1_axis, b2_axis), _ab(b, b1_axis, b2_axis)
    r = (ca[2] + cb[2]) / 2.0
    lo = min(ca[0], cb[0]) + r
    hi = max(ca[0], cb[0]) - r
    if hi < lo:
        hi = lo
    cands: dict[str, Seg] = {}
    for c in (ca, cb):
        for pp in (c[1] + r, c[1] - r):
            s = _tangent_lines(segs, pp, lo, hi)
            if s is not None:
                cands[s.handle] = s
    if len(cands) < 2:
        return None
    hits = list(cands.values())
    ev = tuple(dict.fromkeys([h for x in (a, b) for h in x.evidence]
                             + [h for s in hits[:2] for h in s.handles]))
    z = _zone(role, "stadium", [(ca[0], ca[1], r), (cb[0], cb[1], r)],
              [a, b], _stadium_profile((ca[0], ca[1]), (cb[0], cb[1]), r),
              b1_axis,
              f"等径圆 r{r:.2f} × 2 相配（切线 "
              + "、".join(s.handle for s in hits[:2]) + "）",
              view_id)
    z.evidence = ev
    return z


def _zones_from_groups(groups: list[list[CylinderHint]], b1_axis: str,
                       b2_axis: str, segs: list[Seg], view_id: str
                       ) -> tuple[list[Zone], list[str]]:
    """同轴奇偶定角色 → 等径相配 → 分区。返回 (分区, 记账)。"""
    mats: list[CylinderHint] = []
    cuts: list[CylinderHint] = []
    for g in groups:
        for i, h in enumerate(g):
            (mats if i % 2 == 0 else cuts).append(h)
    notes: list[str] = []
    zones: list[Zone] = []
    for role, pool in (("material", mats), ("cut", cuts)):
        used = [False] * len(pool)
        for i, h in enumerate(pool):
            if used[i]:
                continue
            mate = next((j for j in range(i + 1, len(pool))
                         if not used[j]
                         and abs(pool[j].radius - h.radius) <= SAME_R_TOL), None)
            if mate is None:
                zones.append(_disc_zone(h, role, b1_axis, b2_axis, view_id))
                used[i] = True
                continue
            z = _stadium_zone(h, pool[mate], role, b1_axis, b2_axis, segs,
                              view_id)
            if z is None:
                notes.append(
                    f"等径圆 {_hyphen(h)} 与 {_hyphen(pool[mate])} 之间读不到"
                    "切线 ⇒ 按两个独立分区处置（不并成长圆）")
                zones.append(_disc_zone(h, role, b1_axis, b2_axis, view_id))
                zones.append(_disc_zone(pool[mate], role, b1_axis, b2_axis,
                                        view_id))
            else:
                zones.append(z)
            used[i] = used[mate] = True
    return zones, notes


# ---------------------------------------------------------------------------
# 方案
# ---------------------------------------------------------------------------

@dataclass
class HeightPlan:
    """高度分解方案：基体降到的顶面 + 抬升区 + 切除区。"""

    dir_name: str
    b1_axis: str
    t_lo: float                  # 材料沿拉伸方向的总下界（图纸读数）
    base_top: float              # 基体降到的高度
    t_hi: float                  # 材料总上界
    zones: list[Zone]
    view_id: str                 # 剪影来源视图
    old_length: float = 0.0      # 基体原 length（记账用）
    notes: list[str] = field(default_factory=list)
    #: 剪影包络本身（侧通道要拿它量"某段 b1 区间的实测高度"）
    band: "Band | None" = None

    def span(self) -> tuple[float, float]:
        return (self.t_lo, self.t_hi)

    @property
    def raises(self) -> list[Zone]:
        return [z for z in self.zones
                if z.role == "material" and z.t_hi > self.base_top + RAISE_TOL]

    @property
    def cuts(self) -> list[Zone]:
        return [z for z in self.zones if z.role == "cut"]

    def consumed(self) -> list[CylinderHint]:
        return [h for z in self.zones for h in z.hints]

    def features(self) -> list[Feature]:
        out: list[Feature] = []
        for z in self.raises:
            out.append(make_raise(z, self.dir_name, self.base_top))
        for z in self.cuts:
            f = make_cut(z, self.dir_name)
            if f is not None:
                out.append(f)
        return out

    def description(self) -> str:
        parts = [f"{z.lead} → z[{z.t_lo:.2f},{z.t_hi:.2f}]" for z in self.raises]
        cuts = [f"{z.lead} → z[{z.t_lo:.2f},{z.t_hi:.2f}]" for z in self.cuts]
        return (f"高度分解：基体自 {len(self.zones)} 个圆分区读到高度——基体降到 "
                f"{self.base_top:.2f}（{self.dir_name} 向 {self.t_lo:.2f}.."
                f"{self.t_hi:.2f} 为材料总跨度），抬升区 " + "；".join(parts) +
                ("；切除区 " + "；".join(cuts) if cuts else "") +
                f"（剪影取 {self.view_id}）")


def make_raise(z: Zone, dir_name: str, base_top: float) -> Feature:
    """抬升区 → 一块 BASE（轮廓绝对坐标、origin 面内分量 0、沿 +轴 拉 length）。"""
    o = ir_point(Point3(0.0, 0.0, 0.0), dir_name, 0.0, 0.0, base_top)
    ev = z.evidence
    return Feature(
        id=FeatureId(-1),
        type=Claim(FeatureType.BASE, "height:zone_raise", Tier.PROJECTION, ev),
        params={
            "dir": mk_claim(dir_name, "height:zone_raise", Tier.PROJECTION, ev),
            "length": mk_claim(z.t_hi - base_top, "height:zone_raise",
                               Tier.PROJECTION, ev),
            "profile": Claim(z.profile, "height:zone_contour", Tier.PROJECTION, ev),
            "origin": mk_claim(o, "height:zone_raise", Tier.PROJECTION, ev),
        },
        placement=Claim(o, "height:zone_raise", Tier.PROJECTION, ev),
        source_view=z.view_id, evidence=list(ev),
    )


def make_cut(z: Zone, dir_name: str) -> Feature | None:
    """切除区：落单圆 → HOLE，长圆/矩形 → POCKET。

    ``depth`` 一律给**实测材料厚度**（``t_hi − t_lo``）；通/盲交给
    ``derive_through`` 与图纸总跨度比（那里拿的是 ``HeightPlan.span``，
    不是分解后基体的 height）。
    """
    depth = z.t_hi - z.t_lo
    if depth <= 0.5:
        return None
    ev = z.evidence
    # 轮廓写的是**绝对坐标**、轴向位置一律由 ``axial_at`` 表达 ⇒ placement 的
    # 沿轴分量必须是 0。曾把它写成 z.t_lo：发射器按 ``o + d·axial_at`` 定位，
    # 两处相加 = 2×z.t_lo（实测 pocket 该切 z[2,30] 却切到 z[4,32]，留 2mm 假底板）。
    o = Point3(0.0, 0.0, 0.0)
    if z.kind == "disc" and len(z.circles) == 1:
        h = z.hints[0]
        rad = h.axis.radius if h.axis.radius is not None else mk_claim(
            z.circles[0][2], "projection:circle", Tier.PROJECTION, ev)
        # 孔的轴**必须落在圆心**上（轮廓面内的两个分量来自圆，不是 0）——
        # 只给沿轴分量会把 Ø31.4 的环孔切在 (0,0) 上（实测多料 3.4 万）
        a, b, _r = z.circles[0]
        o = ir_point(Point3(0.0, 0.0, 0.0), dir_name, a, b, 0.0)
        return Feature(
            id=FeatureId(-1),
            type=Claim(FeatureType.HOLE, "height:zone_cut", Tier.PROJECTION, ev),
            params={"radius": rad,
                    "depth": mk_claim(depth, "height:zone_cut",
                                      Tier.PROJECTION, ev),
                    # 契约：HOLE 的 axial_at = 孔口（沿轴方向的起切面）
                    "axial_at": mk_claim(z.t_lo, "height:zone_cut",
                                         Tier.PROJECTION, ev)},
            axis=Claim(Axis3(o, _dir_vec(dir_name), None), "height:zone_cut",
                       Tier.PROJECTION, ev),
            placement=Claim(o, "height:zone_cut", Tier.PROJECTION, ev),
            source_view=z.view_id, evidence=list(ev),
        )
    return Feature(
        id=FeatureId(-1),
        type=Claim(FeatureType.POCKET, "height:zone_cut", Tier.PROJECTION, ev),
        params={
            "profile": Claim(z.profile, "height:zone_cut", Tier.PROJECTION, ev),
            "depth": mk_claim(depth, "height:zone_cut", Tier.PROJECTION, ev),
            # POCKET 契约：axial_at = **腔底**，自底向上挖 depth
            "axial_at": mk_claim(z.t_lo, "height:zone_cut", Tier.PROJECTION, ev),
        },
        placement=Claim(o, "height:zone_cut", Tier.PROJECTION, ev),
        source_view=z.view_id, evidence=list(ev),
    )


def _prof_range(profile) -> tuple[float, float, float, float] | None:
    if isinstance(profile, Profile2):
        b = profile.bbox()
        return (b.xmin, b.ymin, b.xmax, b.ymax)
    try:
        pts = list(profile)
    except TypeError:
        return None
    if not pts:
        return None
    xs = [float(p[0]) for p in pts]
    ys = [float(p[1]) for p in pts]
    return (min(xs), min(ys), max(xs), max(ys))


def _footprint_hints(corr: CorrespondenceResult, dir_name: str, b1_axis: str,
                     b2_axis: str, r1: tuple[float, float],
                     r2: tuple[float, float]) -> list[CylinderHint]:
    """轴 ∥ 拉伸方向、且轴心落在基体轮廓 bbox 内的圆（= 俯视轮廓里的圆）。"""
    want = {f"+{dir_name.upper()}", f"−{dir_name.upper()}"}
    out: list[CylinderHint] = []
    for c in corr.cylinders():
        h = c.mapping.value
        assert isinstance(h, CylinderHint)
        if _axis_name(h.axis.direction) not in want:
            continue
        o = h.axis.origin
        if not (r1[0] - AXIS_POS_TOL <= _coord(o, b1_axis) <= r1[1] + AXIS_POS_TOL
                and r2[0] - AXIS_POS_TOL <= _coord(o, b2_axis) <= r2[1] + AXIS_POS_TOL):
            continue
        out.append(h)
    return out


def decompose(d: "Drawing", corr: CorrespondenceResult, base: Feature,
              rep: "RecognizeReport") -> HeightPlan | None:
    """给出高度分解方案；不该分解 / 读不出 ⇒ None（并记账）。

    成立时**就地**把基体的 ``length`` 改短（改为 ``base_top − t_lo``）——
    与原 origin 一起就是"降到最低公共顶面"的那块底板。
    """
    dir_name = base.params["dir"].value
    if base.type.value == FeatureType.REVOLVE.value or "taper_scale" in base.params:
        return None
    prof = base.params["profile"].value
    if not isinstance(prof, Profile2):
        return None                       # 包围盒矩形的基体：分区无从对齐，不动
    b1_axis, b2_axis = _PLANE_AXES[dir_name]
    org = base.placement.value
    rng = _prof_range(prof)
    if rng is None:
        return None
    o1, o2 = _coord(org, b1_axis), _coord(org, b2_axis)
    r1 = (o1 + rng[0], o1 + rng[2])
    r2 = (o2 + rng[1], o2 + rng[3])
    # ---- ① 侧视图剪影 ----
    bands: list[Band] = []
    for fr in corr.frames.values():
        if fr.v_axis != dir_name or fr.u_axis != b1_axis:
            continue
        v = _view(d, fr.view_id)
        if v is None:
            continue
        b = build_band(d, fr, v)
        if b is not None:
            bands.append(b)
    if not bands:
        return None                      # 没有剪影通道：静默退回（别的靶子如此）
    band = merge_bands(bands)
    tops = band.tops_in(*r1)
    if not tops:
        return None
    if max(tops) - min(tops) <= UNIFORM_TOL:
        rep.notes.append(
            f"高度分解：{b1_axis} 向剪影顶面 {min(tops):.2f}..{max(tops):.2f}"
            f"（极差 ≤ {UNIFORM_TOL}）⇒ 轮廓内没有高低分区，基体照旧一次拉伸")
        return None
    # ---- ② 分区（俯视轮廓里的圆） ----
    hints = _footprint_hints(corr, dir_name, b1_axis, b2_axis, r1, r2)
    if not hints:
        rep.notes.append(
            f"高度分解：{b1_axis} 向剪影顶面 {min(tops):.2f}..{max(tops):.2f} "
            f"不平，但轮廓内没有轴 ∥ {dir_name} 的圆可作分区依据 ⇒ 高度分解"
            "未做（记缺口：高度信号没被读出来）")
        return None
    fview = next((fr for fr in corr.frames.values()
                  if fr.p_axis == dir_name), None)
    segs = frame_lines(d, fview, b1_axis) if fview else []
    zones, znotes = _zones_from_groups(
        _groups(hints, b1_axis, b2_axis), b1_axis, b2_axis, segs,
        fview.view_id if fview else "")
    mats = [z for z in zones if z.role == "material"]
    if not mats:
        rep.notes.append(
            f"高度分解：轮廓内有 {len(hints)} 个圆，但按同轴奇偶全部归为孔/"
            "切除 ⇒ 没有可抬升的材料分区，未分解")
        return None
    # ---- ③ 逐区高度 ----
    org_t = _coord(org, dir_name)
    t0_old = org_t
    t1_old = org_t + float(base.params["length"].value)
    t_lo = min(t0_old, min(band.bots))
    t_hi = max(t1_old, max(band.tops))
    for z in zones:
        z.t_hi = band.top_over(z.b1_lo, z.b1_hi)
        z.t_lo = band.bot_over(z.b1_lo, z.b1_hi)
        z.resolved = z.t_hi is not None and z.t_lo is not None
    base_top = min(tops)
    plan = HeightPlan(dir_name, b1_axis, t_lo, base_top, t_hi, zones, band.view_id,
                      float(base.params["length"].value),
                      list(znotes))
    plan.notes = list(znotes)
    plan.band = band
    # 就地改基体：降到 base_top
    base.params["length"] = Claim(base_top - t_lo, "projection:height_bands",
                                  Tier.PROJECTION, evidence=base.evidence[:1])
    # 记下方案本身（report 层不 import 本模块，故用 notes 传人话）
    rep.notes.append(plan.description())
    for z in zones:
        if not z.resolved:
            rep.questions.add(Question(
                OpenQuestion.MISSING_DIMENSION,
                f"高度分解：分区 {z.lead} 的剪影读数不全（{b1_axis} 投影内没"
                "取到顶/底）⇒ 该区高度按 0 记账", view=z.view_id,
                evidence=list(z.evidence[:1])))
    for msg in znotes:
        rep.notes.append("高度分解：" + msg)
    return plan


# ---------------------------------------------------------------------------
# 侧轴圆柱（挂耳）的轴向区间
# ---------------------------------------------------------------------------

def side_axis_spans(d: "Drawing", corr: CorrespondenceResult, part: Part,
                    dir_name: str, rep: "RecognizeReport") -> int:
    """轴 ⟂ 拉伸方向的凸台：读出它的轴向区间（模型坐标），改写 height/axial_at。

    返回改写的特征数。读不到就原样留着（并记账）——"按 0 起"至少不静默。
    """
    n = 0
    for f in part.features:
        if f.type.value != FeatureType.BOSS.value:
            continue
        if f.axis is None or f.axis.value is None:
            continue
        ax: Axis3 = f.axis.value
        aname = _axis_name(ax.direction)
        if aname in (f"+{dir_name.upper()}", f"−{dir_name.upper()}"):
            continue                      # 俯视轮廓里的圆：归高度分区管
        al = aname.lstrip("+−").lower()
        r = f.params.get("radius")
        if r is None:
            continue
        r = float(r.value)
        best: tuple[float, float] | None = None
        src = ""
        how = ""
        for oth in ("x", "y", "z"):
            if oth == al:
                continue
            for fr in corr.frames.values():
                if al not in (fr.u_axis, fr.v_axis):
                    continue
                if oth not in (fr.u_axis, fr.v_axis):
                    continue
                v = _view(d, fr.view_id)
                if v is None:
                    continue
                segs = frame_lines(d, fr, al)
                co = _coord(ax.origin, oth)
                spans: list[tuple[float, float]] = []
                for pp in (co + r, co - r):
                    cand = [s for s in segs if abs(s.pp - pp) <= LINE_TOL]
                    if not cand:
                        spans = []
                        break
                    spans.append((min(s.lo for s in cand),
                                  max(s.hi for s in cand)))
                if len(spans) != 2:
                    continue
                a2 = min(spans[0][0], spans[1][0])
                b2 = max(spans[0][1], spans[1][1])
                if b2 - a2 < SIDE_MIN_SPAN:
                    continue
                if best is None or (b2 - a2) > (best[1] - best[0]):
                    best = (a2, b2)
                    src = fr.view_id
                    how = f"∥ {al} 的一对轮廓线"
                # 更硬的一手：**端面线对** —— ⟂ 轴家族里、跨度落在凸台足迹内、
                # 轴向坐标又落在剪影对窗口内的一对线，就是轴向两端的端面线。
                # 凸台与端面之间有 R3 铸造圆角时，pp = c ± r 那对轮廓线只剩
                # 圆角切线长（bracket 挂耳实测 14 vs 端面线对 20），取更外者。
                # ⚠ 两关都不可省：少了**轴向窗口**，V2 里零件别处的竖线（pp = y
                # 从 125.56 到 176.56 全落在 z 窗口内）会被当成端面，读出 51.00
                # 的假跨度覆盖真值（实测）；**长度判据要用合并后的 run**——
                # 端面线被 HLR 打成 9 段碎段，单段长度会把真端面筛掉。
                # 长度判据按**直径**给：端面是被裁过的 Ø2r 圆盘的剪影，
                # 至少要跨过半个直径；铸造圆角自己的剪影线只有 0.29·2r
                # （挂耳实测 7.01 vs 24.00），这样一裁就干净。
                segs2 = frame_lines(d, fr, oth)
                pps = sorted(pp2 for pp2, g in _pp_groups(segs2).items()
                             if g.hi - g.lo >= r
                             and g.lo >= co - r - LINE_TOL
                             and g.hi <= co + r + LINE_TOL
                             and a2 - r - LINE_TOL <= pp2 <= b2 + r + LINE_TOL)
                if len(pps) >= 2:
                    a3, b3 = pps[0], pps[-1]
                    if (b3 - a3 > (best[1] - best[0] if best else 0.0)
                            and a3 <= a2 + LINE_TOL and b3 >= b2 - LINE_TOL):
                        best = (a3, b3)
                        src = fr.view_id
                        how = f"⟂ {al} 的端面线对（{len(pps)} 条候选）"
        if best is None:
            rep.notes.append(
                f"侧轴凸台 #{f.id}（r{r:g}，轴 ∥ {al}）：在含 {al} 的视图里找不到"
                "「⟂ = c ± r」的轮廓线对 ⇒ 轴向区间读不出，轴向位置仍缺（按 0 起）")
            continue
        a, b = best
        ev = tuple(f.evidence[:1])
        # 轴向语义 = 「自 axial_at 沿 +轴向 长出 height」⇒ 负向轴取高的一端
        t0 = a if aname.startswith("+") else b
        f.params["height"] = mk_claim(b - a, "projection:side_axis_span",
                                      Tier.PROJECTION, ev)
        f.params["axial_at"] = mk_claim(t0, "projection:side_axis_span",
                                        Tier.PROJECTION, ev)
        n += 1
        rep.notes.append(
            f"侧轴凸台 #{f.id}（r{r:g}，轴 ∥ {al}）：{src} 里 {how}"
            f"读出轴向区间 {a:.2f}..{b:.2f}（长 {b - a:.2f}）⇒ 改写 height/"
            "axial_at（原按 0 起会伸出基体）")
    return n
