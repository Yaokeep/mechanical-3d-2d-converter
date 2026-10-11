# -*- coding: utf-8 -*-
"""回转体识别（阶段 5b）—— 同心圆定轴 × 轴向剖面扫描 ⇒ REVOLVE 母线 + 附属体。

## 为什么单开一路

板类零件的基体是一块拉伸体（``base_feature`` 的轮廓环 × 最薄向），而
回转体（法兰/盘/阶梯轴）的"轮廓"根本不在视图 bbox 里——它在**剖面**：
俯视图给一串同心圆（半径表），主视图给轴向剖面（母线）。PF60K 按板读
体积 −63%，正是这个缺口。

## 判据链（全部只用图纸直接可读的信号）

1. **定轴**：跨视图对应里 ≥3 条共轴的圆轮廓（半径互异）⇒ 回转轴 +
   名义半径表 Rset。少于 3 条不成"回转"（两个同心圆是孔/凸台的常见结构）。
2. **剖面扫描**（能看到轴向线的那个视图）：轴向线段按到轴的距离归一到
   Rset（±0.3，名义值），同半径合并（gap ≤ 1.0，吃掉出图把一条轮廓打成
   几段的裂缝）；合并段的事件端点给出**轴向分段**；每段自零件外（最外
   半径之外必为空）向轴心做**奇偶扫描** ⇒ 材料区间。
3. **母线**：相邻两段的材料边界集合**对称差**即该处的横边端点（成对
   出现；落单者与轴 r=0 配对——段边界上的"通/堵"）；竖边是合并段本身。
   竖边 + 横边构成图，从两个 r≈0 的端点（度 1 节点）走一遍 = 母线。
   PF60K 实测走出 18 点母线，与手工读图逐点一致。
4. **附着**：方料（俯视轮廓顶点读出"方∩圆"的切点半径 26.46——俯视
   bbox 是方宽 60、而轮廓顶点还有 26.46 一族——剖面上该半径的线给出
   方料的 z 跨度；截面取**四角月牙** = 外轮廓 − 回转外径圆，杜绝实心
   拉伸把回转体读出的孔盖死）、键槽（一视图读半宽 r≈2、另一视图读槽底
   r≈7.8，两段 z 范围应一致）、角孔轴向位置（孔壁轮廓线到**孔轴**的距离
   ≈ 孔半径 ⇒ 其 z 跨度即孔口位置）。

## 不建的东西（如实记账，别顺手"修"）

- **主母线锥区**：母线在锥区仍取端点半径的平台近似（R40→R30 过渡
  不并入母线）；锥台本身 v0.6.25 起由 ``_cone_zone`` 独立建（锥台
  REVOLVE + 4 帽切 + 内腔补偿切），不再只是记账。
- **镜像/朝向**：回转体绕轴镜像几何不变；键槽朝向由侧视图的**带符号**
  读数直接给出（不依赖 mirror 语义）。
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Callable

from ..model.claim import Claim, Tier
from ..model.feature_tree import Feature, FeatureType
from ..model.geom import Axis3, Point3, Vector3
from ..model.geom2d import Arc2, Line2, Point2, Profile2, ProfileSeg2
from ..model.ids import FeatureId
from ..model.questions import OpenQuestion, Question
from ..views.correspondence import CorrespondenceResult, CylinderHint
from ..views.ring import extract_ring
from .library import ir_point, mk_claim
from .recognizer import (AXIS_POS_TOL, _PLANE_AXES, _axis_name,
                         _outline_ring_profile, axis_distance)

if TYPE_CHECKING:
    from ..evidence.dxf_reader import Drawing
    from .recognizer import RecognizeReport

#: 半径归一到"名义同心圆"的容差（轮廓线离散/出图抖动都在 0.05 以内）
RADIUS_TOL = 0.30
#: 轴向线段的合并间断上限：出图把一条轮廓切成几段。PF60K 的 r30 在锥区
#: （R40→R30 斜线过渡，按设计不建）被断开 1.76mm（实测 21.74..23.5），
#: 合并回平台恰是"锥区取端点半径的平台近似"——小于此值的间断一律
#: 视为出图裂缝/过渡区，真断口（如 r25 的两个环带间 88mm）不受影响
SEG_GAP = 2.0
#: "轴向线"判据：两端在垂直于轴的平面内的位移上限
AXIAL_DRIFT = 0.15
#: 事件端点聚类容差
EVENT_TOL = 0.1
#: 母线的轴端点判据（|r| ≤ 此值算"落在轴上"）
AXIS_R_TOL = 0.5
#: 剖面扫描的跨度覆盖率下限：母线应铺满零件在该轴的跨度
SCAN_SPAN_MIN = 0.60
#: 方料/键槽的"非 Rset"判据：与任一名义半径的差必须超过这个数
R_OFFSET_TOL = 0.15


@dataclass
class AxLine:
    """一条轴向线段（model 坐标），剖面扫描与附属体读数的公共原始料。"""

    view: str
    p0: Point3
    p1: Point3
    handle: str
    #: 沿回转轴的坐标区间（建线时按轴名算好，避免下游到处判轴）
    t0: float
    t1: float
    #: 视图平面内**垂直于回转轴**的分量轴名（V1 是 x、V2 是 y）——
    #: 轴向线 model 坐标里"视图看不出的那一维"是占位 0（to_model 填的），
    #: 径向距离只能从这一维读
    rad_axis: str = "x"
    #: 到回转轴的径向距离 |线中点[rad_axis] − 轴心[rad_axis]|（建线时算好）
    r: float = 0.0


@dataclass
class ConeZone:
    """锥化过渡区（``detect_revolve`` 的独立 pass 产物）。

    基体母线建到方料顶面后由 ``r_hi`` 锥收到 ``r_top`` 的圆锥台，被方料的
    四个平面削平（截面 = 方 ∩ r(z) 圆）。精确建模 = 独立锥台 REVOLVE +
    4 个 POCKET 帽切除 + 内腔补偿切——全复用现有词汇，两个发射器零改动
    （v0.6.25，PF60K 锥区欠料 −852.5 由此归零）。
    """

    t0: float
    t1: float
    r_hi: float
    r_top: float
    cone: Feature
    caps: list[Feature]
    #: 内腔补偿切（HOLE / 环带 POCKET）：REVOLVE 发射器闭合到轴 ⇒ 锥台
    #: 恒为 r≤r(z) 实心盘，会把基体锥带的内腔填实，须按主母线内壁切回
    restores: list[Feature]
    evidence: tuple


@dataclass
class RevolvePlan:
    """``detect_revolve`` 的产出：基体 + 附属体 + 消解 ``attach_revolve`` 的材料。"""

    base: Feature
    #: 方料块（BASE，id 由 recognize 统一分配）
    solids: list[Feature] = field(default_factory=list)
    #: 键槽（POCKET）
    pocket: Feature | None = None
    #: 锥化过渡区（独立锥台 REVOLVE + 帽切 POCKET，证据不足为 None）
    cone: ConeZone | None = None
    #: 名义同心圆半径表
    rset: tuple[float, ...] = ()
    #: 回转轴（model 系）
    axis: Axis3 | None = None
    dir_name: str = "z"
    #: 母线起点/终点 r≈0 处的轴向坐标（角孔"端面开口"判据）
    t_lo: float = 0.0
    t_hi: float = 0.0
    #: 方料的 z 跨度（角孔"嵌于方料"判据）
    square_spans: list[tuple[float, float]] = field(default_factory=list)
    #: 方料的外接半径（孔壁判据要排除它——26.458 与角孔 24.75+1.65 只差
    #: 0.058，实测会顶替 r1.65 的孔壁把 z 跨度拉长）
    square_r: float | None = None
    #: 各视图的轴向线段（attach 反查孔位/朝向）
    lines: dict[str, list[AxLine]] = field(default_factory=dict)
    note: str = ""

    def skip_outline(self, hint: CylinderHint) -> bool:
        """基体（回转）自己的轮廓圆**不是**特征——跳过全部 Rset 同心圆。

        与 ``recognizer._base_outline`` 同旨：那些圆描述的是基体自身
        （每一条都在剖面上表现为母线的竖边），建进特征树就是"把零件
        又加/减了一遍"。
        """
        r = hint.radius
        if min(abs(r - x) for x in self.rset) > RADIUS_TOL:
            return False
        ax = self.axis
        if ax is None:
            return False
        if not _parallel_either(hint.axis.direction, ax.direction):
            return False
        dd = axis_distance(hint.axis, ax)
        return dd is not None and dd <= AXIS_POS_TOL


# ---------------------------------------------------------------------------
# 小工具
# ---------------------------------------------------------------------------

def _parallel_either(a: Vector3, b: Vector3) -> bool:
    return (max(abs(a.x - b.x), abs(a.y - b.y), abs(a.z - b.z)) < 1e-3
            or max(abs(a.x + b.x), abs(a.y + b.y), abs(a.z + b.z)) < 1e-3)


def _axis_dirname(v: Vector3) -> str | None:
    """方向向量 → 坐标轴名（只认坐标轴；斜轴不猜）。"""
    for name, s in (("x", 1.0), ("y", 1.0), ("z", 1.0)):
        c = {"x": v.x, "y": v.y, "z": v.z}[name]
        if abs(abs(c) - 1.0) < 1e-6:
            return name
    return None


def _cluster(vals: list[float], tol: float) -> list[float]:
    """一维值聚类 → 各簇均值（升序）。"""
    out: list[list[float]] = []
    for x in sorted(vals):
        if out and x - out[-1][-1] <= tol:
            out[-1].append(x)
        else:
            out.append([x])
    return [sum(g) / len(g) for g in out]


def _merge_spans(spans: list[tuple[float, float]], gap: float
                 ) -> list[tuple[float, float]]:
    out: list[tuple[float, float]] = []
    for a, b in sorted(spans):
        if out and a - out[-1][1] <= gap:
            out[-1] = (out[-1][0], max(out[-1][1], b))
        else:
            out.append((a, b))
    return out


def _nearest(r: float, rset: tuple[float, ...]) -> tuple[float, float]:
    """(最近的名义半径, 距离)。"""
    best = min(rset, key=lambda x: abs(x - r))
    return best, abs(best - r)


def _radial(p: Point3, ax_pt: Point3, dir_name: str) -> float:
    """点到轴线（过 ``ax_pt``、沿 ``dir_name``）的垂距。"""
    if dir_name == "z":
        return math.hypot(p.x - ax_pt.x, p.y - ax_pt.y)
    if dir_name == "x":
        return math.hypot(p.y - ax_pt.y, p.z - ax_pt.z)
    return math.hypot(p.x - ax_pt.x, p.z - ax_pt.z)


# ---------------------------------------------------------------------------
# 轴向线提取与剖面扫描
# ---------------------------------------------------------------------------

def _axial_lines(d: Drawing, frame, dir_name: str,
                 ax_pt: Point3, slant: bool = False) -> list[AxLine]:
    """一个视图里全部**轴向**（平行于回转轴）线段（model 坐标）。

    ``slant=True`` 时反过来收 **drift 超限的斜线**（锥母线候选）——主扫描
    丢弃的线，锥段 pass 单独要它（两端径向读数由调用方自算）。

    ``r`` 取视图平面内垂直于轴的分量（``to_model`` 对"视图看不出的那一维"
    填的是占位 0，拿它进 hypot 会得到 ~193 的伪距离——2026-10-09 实测）。
    """
    if dir_name not in (frame.u_axis, frame.v_axis):
        return []                                     # 沿轴看的视图没有轴向线
    rad_axis = frame.v_axis if frame.u_axis == dir_name else frame.u_axis
    view = next((v for v in d.views if v.id == frame.view_id), None)
    if view is None:
        return []
    c_ax = {"x": ax_pt.x, "y": ax_pt.y, "z": ax_pt.z}[rad_axis]
    out: list[AxLine] = []
    for h in view.evidence:
        e = d.by_handle(h)
        if e is None or not isinstance(e.geom, Line2):
            continue
        g = e.geom
        p0 = frame.to_model(g.start.x, g.start.y)
        p1 = frame.to_model(g.end.x, g.end.y)
        c0 = {"x": p0.x, "y": p0.y, "z": p0.z}[dir_name]
        c1 = {"x": p1.x, "y": p1.y, "z": p1.z}[dir_name]
        if abs(c1 - c0) < 0.5:                        # 非轴向（横向线）
            continue
        if dir_name == "z":
            drift = math.hypot(p1.x - p0.x, p1.y - p0.y)
        elif dir_name == "x":
            drift = math.hypot(p1.y - p0.y, p1.z - p0.z)
        else:
            drift = math.hypot(p1.x - p0.x, p1.z - p0.z)
        if slant:
            if drift <= AXIAL_DRIFT:
                continue                              # 只收斜线
        elif drift > AXIAL_DRIFT:                     # 斜线（锥区微段等）
            continue
        r0 = {"x": p0.x, "y": p0.y, "z": p0.z}[rad_axis]
        r1 = {"x": p1.x, "y": p1.y, "z": p1.z}[rad_axis]
        out.append(AxLine(frame.view_id, p0, p1, h,
                          min(c0, c1), max(c0, c1),
                          rad_axis=rad_axis, r=abs((r0 + r1) / 2 - c_ax)))
    return out


def _scan(lines: list[AxLine], rset: tuple[float, ...]
          ) -> tuple[list[tuple[float, float]], list[list[tuple[float, float]]],
                     list[float], dict[float, list[AxLine]]] | None:
    """剖面扫描：``(母线点列, 每段材料区间, 事件表, 竖边表)`` 或 None。

    奇偶扫描从外向内——零件轮廓之外必为空，这是本算法的"外锚点"。
    """
    # 1. 按名义半径分组、同半径合并
    by_r: dict[float, list[tuple[float, float]]] = {}
    edges_of: dict[float, list[AxLine]] = {}
    for ln in lines:
        r = ln.r
        if r < AXIS_R_TOL:                            # 中心线
            continue
        nom, dist = _nearest(r, rset)
        if dist > RADIUS_TOL:
            continue                                  # 非同心圆的线（方料/键槽/角孔）
        by_r.setdefault(nom, []).append((ln.t0, ln.t1))
        edges_of.setdefault(nom, []).append(ln)
    if len(by_r) < 3:
        return None
    spans = {r: _merge_spans(v, SEG_GAP) for r, v in by_r.items()}

    # 2. 事件表（全部段端点聚类）
    T = _cluster([x for v in spans.values() for ab in v for x in ab], EVENT_TOL)
    if len(T) < 4:
        return None

    def snap(x: float) -> float:
        return min(T, key=lambda t: abs(t - x))

    # 3. 每段的边界集合（用段中点判归属）
    seg_bounds: list[set[float]] = []
    for i in range(len(T) - 1):
        tm = (T[i] + T[i + 1]) / 2.0
        seg_bounds.append({r for r, v in spans.items()
                           if any(a <= tm < b for a, b in v)})
    if any(not b for b in seg_bounds):
        return None

    # 4. 奇偶扫描（从外向内；落单 = 材料触轴）
    intervals: list[list[tuple[float, float]]] = []
    for bounds in seg_bounds:
        ivs: list[tuple[float, float]] = []
        inside = False
        hi = 0.0
        for r in sorted(bounds, reverse=True):
            if not inside:
                inside, hi = True, r
            else:
                inside = False
                ivs.append((r, hi))
        if inside:
            ivs.append((0.0, hi))
        ivs.reverse()
        intervals.append(ivs)

    # 5. 图遍历：竖边（合并段）+ 横边（边界集合对称差配对）
    vert: list[tuple[tuple[float, float], tuple[float, float]]] = []
    for r, v in spans.items():
        for a, b in v:
            vert.append(((snap(a), r), (snap(b), r)))
    horiz: list[tuple[tuple[float, float], tuple[float, float]]] = []
    for i in range(len(T)):
        left = seg_bounds[i - 1] if i > 0 else set()
        right = seg_bounds[i] if i < len(seg_bounds) else set()
        dd = sorted(left ^ right)
        if len(dd) % 2 == 1:
            dd = [0.0] + dd                            # 落单者和轴配对
        for a, b in zip(dd[::2], dd[1::2]):
            horiz.append(((T[i], a), (T[i], b)))
    busbar = _walk(vert + horiz)
    if busbar is None:
        return None
    return busbar, intervals, T, edges_of


def _walk(edges: list[tuple[tuple[float, float], tuple[float, float]]]
          ) -> list[tuple[float, float]] | None:
    """边集 → 从 r≈0 端点出发的母线（节点度 >2 / 端点 ≠ 2 个 ⇒ None）。"""
    adj: dict[tuple[float, float], list[int]] = {}
    for i, (a, b) in enumerate(edges):
        adj.setdefault(a, []).append(i)
        adj.setdefault(b, []).append(i)
    leaves = [n for n, es in adj.items() if len(es) == 1 and n[1] < AXIS_R_TOL]
    if len(leaves) != 2 or any(len(es) > 2 for es in adj.values()):
        return None
    start = min(leaves)
    used: set[int] = set()
    path = [start]
    cur = start
    while True:
        nxt = [i for i in adj[cur] if i not in used]
        if not nxt:
            break
        i = nxt[0]
        a, b = edges[i]
        used.add(i)
        cur = b if a == cur else a
        path.append(cur)
    if len(used) != len(edges) or path[-1][1] >= AXIS_R_TOL:
        return None
    return path


# ---------------------------------------------------------------------------
# 检测主入口
# ---------------------------------------------------------------------------

def detect_revolve(d: Drawing, corr: CorrespondenceResult,
                   rep: RecognizeReport) -> RevolvePlan | None:
    """三视图里的回转体 → ``RevolvePlan``（不成立返回 None，退回原基体路径）。"""
    hints: list[CylinderHint] = []
    for c in corr.cylinders():
        h = c.mapping.value
        if isinstance(h, CylinderHint):
            hints.append(h)
    if len(hints) < 3:
        return None
    # 分簇：方向平行 + 轴距 ≤ AXIS_POS_TOL
    groups: list[list[CylinderHint]] = []
    for h in hints:
        for g in groups:
            if not _parallel_either(h.axis.direction, g[0].axis.direction):
                continue
            dd = axis_distance(h.axis, g[0].axis)
            if dd is not None and dd <= AXIS_POS_TOL:
                g.append(h)
                break
        else:
            groups.append([h])
    best: tuple[list[CylinderHint], list[float]] | None = None
    for g in groups:
        rs = _cluster([h.radius for h in g], RADIUS_TOL)
        if len(rs) >= 3 and (best is None or len(rs) > len(best[1])):
            best = (g, rs)
    if best is None:
        return None
    g, rset = best
    dir_name = _axis_dirname(g[0].axis.direction)
    if dir_name is None:
        return None
    ax_pt = g[0].axis.origin

    # 全部视图的轴向线（V0 这类沿轴看的视图没有轴向线，自然为空）
    lines: dict[str, list[AxLine]] = {}
    for f in corr.frames.values():
        ls = _axial_lines(d, f, dir_name, ax_pt)
        if ls:
            lines[f.view_id] = ls

    # 剖面扫描：p_axis ≠ 轴（能看到轴向剖面的视图），首个成功者胜
    scan = None
    for f in corr.frames.values():
        if f.p_axis == dir_name or dir_name not in (f.u_axis, f.v_axis):
            continue
        sp = f.model_span(dir_name)
        res = _scan(lines.get(f.view_id, []), tuple(rset))
        if res is None:
            continue
        busbar, _intervals, T, edges_of = res
        if sp is not None and sp[1] > sp[0]:
            cov = (T[-1] - T[0]) / (sp[1] - sp[0])
            if cov < SCAN_SPAN_MIN:
                continue
        scan = (f.view_id, busbar, T, edges_of)
        break
    if scan is None:
        return None
    vid, busbar, T, edges_of = scan

    ev: list[str] = []
    for h in g:
        if h.axis.radius is not None:
            # 半径的证据**整组**收：同一半径往往画两条圆边（可见一条 + 被挡的
            # 隐藏一条），`radius.evidence` 就是该半径组的全部图元。曾经只取
            # [:1]，丢掉的隐藏条令"同心圆边"疑问的证据覆盖判据（attach_revolve
            # 里的消解）判不过 —— PF60K 实测 7 条半径共 12 条圆边、只收进 7 条
            ev.extend(str(x) for x in h.axis.radius.evidence)
    for r, ls in edges_of.items():
        if ls:
            ev.append(ls[0].handle)
    ev_t = tuple(dict.fromkeys(ev))

    zdir = Vector3(0.0, 0.0, 1.0) if dir_name == "z" else (
        Vector3(1.0, 0.0, 0.0) if dir_name == "x" else Vector3(0.0, 1.0, 0.0))
    centre = Point3(ax_pt.x, ax_pt.y, 0.0)
    # 母线 t 用**绝对**轴坐标，故 origin 的轴向分量为 0
    o_abs = ir_point(Point3(0.0, 0.0, 0.0), dir_name, ax_pt.x, ax_pt.y, 0.0)

    prof_pts = [(t, r) for (t, r) in busbar]
    base = Feature(
        id=FeatureId(0),
        type=Claim(FeatureType.REVOLVE,
                   "revolve:coaxial_circles+axial_section", Tier.PROJECTION,
                   ev_t),
        params={
            "dir": mk_claim(dir_name, "revolve:coaxial_circles",
                            Tier.PROJECTION, ev_t),
            "angle_deg": mk_claim(360.0, "revolve:convention_full_turn",
                                  Tier.CONVENTION, ev_t),
            "radius_profile": mk_claim(prof_pts, "revolve:axial_section_scan",
                                       Tier.PROJECTION, ev_t),
            "origin": mk_claim(o_abs, "revolve:coaxial_circles",
                               Tier.PROJECTION, ev_t),
        },
        axis=Claim(Axis3(centre, zdir), "revolve:coaxial_circles",
                   Tier.PROJECTION, ev_t),
        placement=Claim(centre, "revolve:coaxial_circles", Tier.PROJECTION,
                        ev_t),
        source_view=vid, evidence=list(ev_t),
    )

    plan = RevolvePlan(base=base, rset=tuple(rset),
                       axis=Axis3(centre, zdir), dir_name=dir_name,
                       t_lo=T[0], t_hi=T[-1], lines=lines)
    rep.notes.append(
        f"基体：{vid} 正对轴 ({_axis_name(zdir)}) 的剖面扫描出 **{len(prof_pts)} "
        f"点母线**（z {T[0]:.2f}..{T[-1]:.2f}，{len(rset)} 个同心圆半径 "
        f"{', '.join(f'{r:g}' for r in rset)}）⇒ 按**回转体**读")
    _square(d, corr, plan, rep, dir_name)
    _keyway(plan, rep)
    _cone_zone(d, corr, plan, rep, dir_name)
    return plan


# ---------------------------------------------------------------------------
# 附属体读数
# ---------------------------------------------------------------------------

def _view_box_model(frame, view) -> dict[str, tuple[float, float]]:
    """把视图 bbox 映射回 model 系：``{轴名: (lo, hi)}``。"""
    out: dict[str, tuple[float, float]] = {}
    out[frame.u_axis] = (view.bbox.xmin + frame.u_off,
                         view.bbox.xmax + frame.u_off)
    out[frame.v_axis] = (view.bbox.ymin + frame.v_off,
                         view.bbox.ymax + frame.v_off)
    return out


def _square(d: Drawing, corr: CorrespondenceResult, plan: RevolvePlan,
            rep: RecognizeReport, dir_name: str) -> None:
    """方料读数：轮廓顶点给切点半径，剖面线表给 z 跨度 ⇒ 每段一块 BASE。"""
    f0 = next((f for f in corr.frames.values() if f.p_axis == dir_name), None)
    if f0 is None:
        return
    view = next((v for v in d.views if v.id == f0.view_id), None)
    if view is None or view.bbox is None:
        return
    res = extract_ring(d, view)
    if res.ring is None or min(res.ring.coverage) < 0.5:
        return
    mbox = _view_box_model(f0, view)
    b1_axis, b2_axis = _PLANE_AXES[dir_name]
    if b1_axis not in mbox or b2_axis not in mbox:
        return
    lo1, hi1 = mbox[b1_axis]
    lo2, hi2 = mbox[b2_axis]
    prof0, note0 = _outline_ring_profile(d, f0, dir_name, lo1, hi1, lo2, hi2)
    if prof0 is None:
        return
    c = plan.axis.origin
    c1 = {"x": c.x, "y": c.y, "z": c.z}[b1_axis]
    c2 = {"x": c.x, "y": c.y, "z": c.z}[b2_axis]
    cand: set[float] = set()
    for s in prof0.segments:
        for p in (s.p1, s.p2):
            for v in (abs(p.x + lo1 - c1), abs(p.y + lo2 - c2)):
                if v > 1.0:
                    cand.add(round(v, 3))
    cand = {v for v in cand
            if min(abs(v - x) for x in plan.rset + (0.0,)) > RADIUS_TOL}
    # 多候选时用剖面线表消歧：该半径的轴向线必须成段（跨 z ≥ 2）
    keep = []
    for v in sorted(cand):
        segs = [ln for ls in plan.lines.values() for ln in ls
                if abs(ln.r - v) <= RADIUS_TOL]
        if segs:
            keep.append((v, segs))
    if len(keep) != 1:
        if keep:
            rep.notes.append(
                f"方料：轮廓顶点给出 {len(keep)} 个候选半径"
                f"（{'/'.join(f'{v:g}' for v, _ in keep)}），不唯一 ⇒ 不建方料")
        return
    sq_r, segs = keep[0]
    plan.square_r = sq_r
    spans = _merge_spans([(ln.t0, ln.t1) for ln in segs], SEG_GAP)
    ev0 = tuple(ln.handle for ln in segs[:4])
    n_moons = 0
    for a, b in spans:
        if b - a < 0.5:
            continue
        origin = ir_point(Point3(0.0, 0.0, 0.0), dir_name, lo1, lo2, a)
        # 方料截面必须**减掉回转体在该段的外径圆**：实心外轮廓拉伸会把
        # 回转体读出的孔全盖住——PF60K 实测 [2,7] 段的 Ø50 孔被方料封死，
        # 多建 π·25²·5 = 9,817.7mm³（逐位等于孔面积×深）。r≤r_in 的径向
        # 结构与孔全部由回转体自己的母线表达，方料只留**四角月牙**
        # （外轮廓 − r_in 圆）。月牙读不出 ⇒ 不建（留缺口记账），
        # 绝不回退实心——那是结构性错误（孔被封），不是精度损失。
        r_in = _span_outer_r(plan, a, b)
        moons = _square_moons(prof0, c1 - lo1, c2 - lo2, r_in)
        if not moons:
            rep.notes.append(
                f"方料：z{a:.2f}..{b:.2f} 段的四角月牙读不出"
                f"（外径圆 r{r_in:g} 与轮廓的切点不是 4 个）⇒ 该段不建方料")
            continue
        for pr in moons:
            sol = Feature(
                id=FeatureId(-1),
                type=Claim(FeatureType.BASE, "revolve:square_block",
                           Tier.PROJECTION, ev0),
                params={
                    "dir": mk_claim(dir_name, "revolve:square_block",
                                    Tier.PROJECTION, ev0),
                    "length": mk_claim(b - a, "revolve:square_block",
                                       Tier.PROJECTION, ev0),
                    "profile": Claim(pr, "revolve:square_moon",
                                     Tier.PROJECTION, ev0),
                    "origin": mk_claim(origin, "revolve:square_block",
                                       Tier.PROJECTION, ev0),
                },
                axis=Claim(Axis3(ir_point(Point3(0.0, 0.0, 0.0), dir_name,
                                          lo1, lo2, a),
                                 Vector3(0.0, 0.0, 1.0) if dir_name == "z"
                                 else (Vector3(1.0, 0.0, 0.0) if dir_name == "x"
                                       else Vector3(0.0, 1.0, 0.0))),
                           "revolve:square_block", Tier.PROJECTION, ev0),
                placement=Claim(origin, "revolve:square_block",
                                Tier.PROJECTION, ev0),
                source_view=f0.view_id, evidence=list(ev0),
            )
            plan.solids.append(sol)
            n_moons += 1
        plan.square_spans.append((a, b))
    if plan.solids:
        rep.notes.append(
            f"方料：轮廓顶点读出切点半径 r{sq_r:g}（轮廓环 {note0}），"
            f"剖面上该半径的线跨 "
            + "、".join(f"z{a:.2f}..{b:.2f}" for a, b in plan.square_spans)
            + f" ⇒ 逐段补四角月牙（外轮廓 − 回转外径圆）共 {n_moons} 块")


def _span_outer_r(plan: RevolvePlan, a: float, b: float) -> float:
    """母线在轴段 [a, b] 内的最大半径 = 该段回转体的外径。

    方料月牙的内边界必须取它而不是轮廓切点半径（26.46）——后者只是
    "方∩圆"的交点半径读数（判方料存在用的信号），回转到不了那里。
    """
    prof = plan.base.params["radius_profile"].value
    rs = [float(r) for t, r in prof if a - 0.05 <= float(t) <= b + 0.05]
    return max(rs) if rs else 0.0


def _square_moons(prof: Profile2, cx: float, cy: float, r_in: float
                  ) -> list[Profile2] | None:
    """把"方∩圆"外轮廓切成四个角的月牙（外轮廓 − 内切圆 ``r_in``）。

    ``r_in``（= 回转体外径）圆与方边相切于四个切点，轮廓环在切点处
    天然断开（PF60K 实测 16 段 = 每边 2 直线 + 每角 2 弧，分断点正是
    切点，无需求交）。每两个相邻切点之间的环序链 + 新造的 ``r_in``
    短弧（末切点 → 首切点）构成一个月牙（单条闭合链、CCW 正面积）。
    切点数 ≠ 4（或 r_in 无效）⇒ None——让调用方如实不建而非实心盖孔。
    """
    if r_in <= 0.0 or len(prof.segments) < 8:
        return None
    tol = 0.05
    segs = list(prof.segments)
    n = len(segs)

    def _tangent(p: Point2) -> bool:
        dx, dy = abs(p.x - cx), abs(p.y - cy)
        return ((abs(dx - r_in) <= tol and dy <= tol)
                or (abs(dy - r_in) <= tol and dx <= tol))

    starts = [i for i in range(n) if _tangent(segs[i].p1)]
    if len(starts) != 4:
        return None
    tau = 2.0 * math.pi
    moons: list[Profile2] = []
    for k in range(4):
        i0, i1 = starts[k], starts[(k + 1) % 4]
        chain = segs[i0:i1] if i0 < i1 else segs[i0:] + segs[:i1]
        if len(chain) < 2:
            return None
        pa, pb = chain[0].p1, chain[-1].p2
        sa = math.atan2(pb.y - cy, pb.x - cx)
        ea = math.atan2(pa.y - cy, pa.x - cx)
        ccw = ((ea - sa) % tau) <= math.pi + 1e-9       # 回程取短弧
        arc = ProfileSeg2(kind="arc", p1=pb, p2=pa,
                          center=Point2(cx, cy), radius=r_in,
                          ccw=ccw, sa=sa, ea=ea)
        moons.append(Profile2(tuple(chain) + (arc,)))
    return moons


def _keyway(plan: RevolvePlan, rep: RecognizeReport) -> None:
    """键槽：一侧视图读半宽（r≈2 的短半径线），另一侧读槽底（r≈7.8），取交集 z。"""
    if plan.axis is None:
        return
    c = plan.axis.origin
    w_ln: list[AxLine] = []
    d_ln: list[AxLine] = []
    for ls in plan.lines.values():
        for ln in ls:
            r = ln.r
            if min(abs(r - x) for x in plan.rset) <= R_OFFSET_TOL:
                continue                              # 同心圆轮廓
            if 0.8 <= r <= 3.0:
                w_ln.append(ln)
            elif 3.0 < r <= 9.0:
                d_ln.append(ln)
    if not w_ln or not d_ln:
        return

    def span_of(ls: list[AxLine]) -> tuple[float, float]:
        sp = _merge_spans([(l.t0, l.t1) for l in ls], SEG_GAP)
        return max(sp, key=lambda ab: ab[1] - ab[0])

    w0, w1 = span_of(w_ln)
    d0, d1 = span_of(d_ln)
    z0, z1 = max(w0, d0), min(w1, d1)
    if z1 - z0 < 1.0:
        return
    ww = [l for l in w_ln if l.t0 >= z0 - 0.5 and l.t1 <= z1 + 0.5]
    if not ww:
        return
    w_half = sum(l.r for l in ww) / len(ww)
    # 槽底半径与朝向（带符号 pos）——取自与槽 z 范围一致的线
    dd = [l for l in d_ln if l.t0 >= z0 - 0.5 and l.t1 <= z1 + 0.5]
    if not dd:
        return
    # 槽底是距轴**最远**的槽壁面；同带内还会有"侧壁与孔壁的交线"
    # （PF60K 实测 √(6²−2²)=5.657 与槽底 7.8 同跨），按半径聚类取最大簇
    r_bot = max(_cluster([l.r for l in dd], RADIUS_TOL))
    dd = [l for l in dd if abs(l.r - r_bot) <= RADIUS_TOL]
    r_bot = sum(l.r for l in dd) / len(dd)
    # 朝向：带符号的侧向分量之和。只统计 rad_axis == 侧向轴 的线——
    # 另一视图的线（rad_axis 是宽度向）其分量不含朝向信息，混进来会把
    # 符号拉向 0；且它那一维的 model 值是占位 0，纯属噪声（2026-10-09）
    b1_axis, b2_axis = _PLANE_AXES[plan.dir_name]
    sgn = 0.0
    n_sgn = 0
    for l in dd:
        if l.rad_axis != b2_axis:
            continue
        sgn += {"x": (l.p0.x + l.p1.x) / 2 - c.x,
                "y": (l.p0.y + l.p1.y) / 2 - c.y,
                "z": (l.p0.z + l.p1.z) / 2 - c.z}[l.rad_axis]
        n_sgn += 1
    if n_sgn == 0:
        return                                        # 没有侧向读数 ⇒ 不猜朝向
    sgn = 1.0 if sgn >= 0.0 else -1.0
    evk = tuple(l.handle for l in (w_ln + dd)[:4])
    prof = [(-w_half, 0.0), (w_half, 0.0),
            (w_half, sgn * r_bot), (-w_half, sgn * r_bot)]
    zdir = plan.axis.direction
    plan.pocket = Feature(
        id=FeatureId(-1),
        type=Claim(FeatureType.POCKET, "revolve:keyway", Tier.PROJECTION, evk),
        params={
            "profile": mk_claim(prof, "revolve:keyway", Tier.PROJECTION, evk),
            "depth": mk_claim(z1 - z0, "revolve:keyway", Tier.PROJECTION, evk),
            "axial_at": mk_claim(z0, "revolve:keyway", Tier.PROJECTION, evk),
        },
        axis=Claim(Axis3(Point3(c.x, c.y, 0.0), zdir), "revolve:keyway",
                   Tier.PROJECTION, evk),
        placement=Claim(Point3(c.x, c.y, z0), "revolve:keyway",
                        Tier.PROJECTION, evk),
        source_view="", evidence=list(evk),
    )
    rep.notes.append(
        f"键槽：宽 {2 * w_half:g}（半宽读数 {w_half:g}）、槽底 r{r_bot:g}"
        f"（朝 {'+y' if sgn > 0 else '−y'}）、z {z0:.2f}..{z1:.2f}"
        f" ⇒ POCKET 深 {z1 - z0:g}")


def _coaxial_arc_radii(d: Drawing, corr: CorrespondenceResult,
                       plan: RevolvePlan, dir_name: str
                       ) -> tuple[float, tuple] | None:
    """沿轴看的视图里、圆心与回转轴同轴的**弧**的半径（锥底圆证据）。

    锥底圆常只以弧存在——PF60K r40 弧 8+16 段共 114.9°，够不上
    ``correspondence._circles_of`` 的 170° 圆边门。取**大于主母线最大外径**
    的最大弧半径簇（防把 r30 圆碎片当锥底）。
    """
    ax = plan.axis
    c0 = ax.origin
    radii: list[float] = []
    handles: list[str] = []
    for f in corr.frames.values():
        if f.p_axis != dir_name:
            continue
        view = next((v for v in d.views if v.id == f.view_id), None)
        if view is None:
            continue
        for h in view.evidence:
            e = d.by_handle(h)
            if e is None or not isinstance(e.geom, Arc2):
                continue
            g = e.geom
            m = f.to_model(g.center.x, g.center.y)
            if math.hypot(m.x - c0.x, m.y - c0.y) > AXIS_POS_TOL:
                continue
            if (g.end_angle - g.start_angle) % (2 * math.pi) < math.radians(1.0):
                continue                              # 防退化弧（PF60K r40 弧每段仅 3.6°）
            radii.append(g.radius)
            handles.append(h)
    if not radii:
        return None
    prof = plan.base.params["radius_profile"].value
    outer_max = max((float(r) for _t, r in prof), default=0.0)
    big = [r for r in radii if r > outer_max + 5.0]
    if not big:
        return None
    r_hi = float(max(big))
    ev = tuple(dict.fromkeys(h for h, r in zip(handles, radii)
                             if abs(r - r_hi) <= RADIUS_TOL))
    return r_hi, ev


def _cone_zone(d: Drawing, corr: CorrespondenceResult, plan: RevolvePlan,
               rep: RecognizeReport, dir_name: str) -> None:
    """锥化过渡区：母线建到方料顶面后 r_hi→r_top 的锥台，被方料四平面削平。

    判据全保守（任一步证据不足即不建，行为=现状）：
    ① 沿轴看视图有圆心同轴的弧，半径 > 主母线最大外径 → r_hi；
    ② 剖面视图有**成对镜像**的斜线（drift 超限被主扫描丢弃者），低端径向
       读数落 r_hi、高端读数 r_top 与主母线锥顶外径一致（RADIUS_TOL 内）；
    ③ 斜线低端 t 与方料顶面（square_spans 最高顶）共面（≤0.05）、
       t1−t0 ≥ 0.5、r_hi−r_top ≥ 5。

    建模（B4 方案，全复用现有词汇、发射器零改动）：
    锥台 REVOLVE ``[(t0,0),(t0,r_hi),(t1,r_top)]`` + 4 个轴对齐 POCKET 帽切。
    帽盒 [r_top, r_hi+0.1]×[−w,w]，w=√(r_hi²−r_top²)+0.1——中边帽
    |y|≤√(r_hi²−r_top²) 全含，盒内基准材料（方∩锥∩{x≥30}）为空 ⇒ 多切为零。
    """
    if not plan.square_spans or plan.axis is None:
        return
    found = _coaxial_arc_radii(d, corr, plan, dir_name)
    if found is None:
        return
    r_hi, ev_arc = found
    ax = plan.axis
    c_ax = {"x": ax.origin.x, "y": ax.origin.y, "z": ax.origin.z}
    prof = plan.base.params["radius_profile"].value
    tops = [b for _a, b in plan.square_spans]

    def outer_at(t: float) -> float:
        """主母线在轴向坐标 t 处的外径：找覆盖 t 的竖边/点取最大半径。

        锥顶 t1 往往落在平台竖边**内部**（PF60K 主母线 r30 是 (2,30)→(95,30)
        一整条），点列本身在 t1 处没有点，按点列搜索会扑空。
        """
        best = 0.0
        for (ta, ra), (tb, rb) in zip(prof, prof[1:]):
            if min(ta, tb) - 0.01 <= t <= max(ta, tb) + 0.01:
                best = max(best, float(ra), float(rb))
        return best

    # 斜线收集：剖面视图里的 drift 超限线，两端径向读数（rad_axis 分量到轴距）
    cand: list[tuple[AxLine, float]] = []
    for f in corr.frames.values():
        if f.p_axis == dir_name or dir_name not in (f.u_axis, f.v_axis):
            continue
        for ln in _axial_lines(d, f, dir_name, ax.origin, slant=True):
            c0v = {"x": ln.p0.x, "y": ln.p0.y, "z": ln.p0.z}[dir_name]
            c1v = {"x": ln.p1.x, "y": ln.p1.y, "z": ln.p1.z}[dir_name]
            p_lo = ln.p0 if c0v <= c1v else ln.p1
            p_hi = ln.p1 if c0v <= c1v else ln.p0
            r_lo = abs({"x": p_lo.x, "y": p_lo.y, "z": p_lo.z}[ln.rad_axis]
                       - c_ax[ln.rad_axis])
            r_top = abs({"x": p_hi.x, "y": p_hi.y, "z": p_hi.z}[ln.rad_axis]
                        - c_ax[ln.rad_axis])
            if abs(r_lo - r_hi) > RADIUS_TOL:
                continue                              # 低端必须落锥底名义半径
            if r_hi - r_top < 5.0:
                continue
            if not any(abs(ln.t0 - b) <= 0.05 for b in tops):
                continue                              # 锥底与某方料段顶共面
            if abs(outer_at(ln.t1) - r_top) > RADIUS_TOL:
                continue                              # 锥顶须续上主母线外径
            cand.append((ln, r_top))
    if not cand:
        return
    # 镜像成对：同签名（t 区间 + 锥顶半径）≥2 条、径向分量中点分布在轴两侧
    by_sig: dict[tuple, list[tuple[AxLine, float, float]]] = {}
    for ln, r_top in cand:
        mid = ({"x": (ln.p0.x + ln.p1.x) / 2, "y": (ln.p0.y + ln.p1.y) / 2,
                "z": (ln.p0.z + ln.p1.z) / 2}[ln.rad_axis]
               - c_ax[ln.rad_axis])
        sig = (round(ln.t0, 1), round(ln.t1, 1), round(r_top, 1))
        by_sig.setdefault(sig, []).append((ln, mid, r_top))
    pair = None
    for sig, items in by_sig.items():
        mids = [m for _ln, m, _r in items]
        if len(items) >= 2 and min(mids) < -AXIS_POS_TOL \
                and max(mids) > AXIS_POS_TOL:
            pair = (sig, items)
            break
    if pair is None:
        return
    _sig, items = pair
    # t0 取与斜线低端共面的方料段顶（与月牙顶面精确共面；斜线端差 0.0033）
    t0 = min(tops, key=lambda b: abs(items[0][0].t0 - b))
    t1 = sum(ln.t1 for ln, _m, _r in items) / len(items)
    r_top = sum(r for _ln, _m, r in items) / len(items)
    if t1 - t0 < 0.5:
        return
    ev = ev_arc + tuple(ln.handle for ln, _m, _r in items)
    centre = Point3(c_ax["x"], c_ax["y"], c_ax["z"])
    zdir = ax.direction
    o_abs = ir_point(Point3(0.0, 0.0, 0.0), dir_name, centre.x, centre.y, 0.0)
    cone = Feature(
        id=FeatureId(-1),
        type=Claim(FeatureType.REVOLVE, "revolve:cone_zone",
                   Tier.PROJECTION, ev),
        params={
            "dir": mk_claim(dir_name, "revolve:cone_zone", Tier.PROJECTION, ev),
            "angle_deg": mk_claim(360.0, "revolve:cone_zone",
                                  Tier.PROJECTION, ev),
            # 母线从轴起：发射器把母线闭合成环时"末点→轴上垂足→沿轴→
            # 首点垂足"，首点 r>0 与 r=0 扫出的是**同一个**多边形
            # （垂足段把 r≤首点半径全扫进来）⇒ REVOLVE 语义恒为 r≤r(z)
            # 实心盘（实测 r_top 起环带体体积逐位不变，v0.6.25）。
            # 锥台因此会把基体锥带内腔填实（PF60K π·234×1.763=+1,296.3
            # 逐位对账），内腔由随后的 restores（HOLE + 环带 POCKET）切回。
            "radius_profile": mk_claim([(t0, 0.0), (t0, r_hi), (t1, r_top)],
                                       "revolve:cone_zone",
                                       Tier.PROJECTION, ev),
            "origin": mk_claim(o_abs, "revolve:cone_zone",
                               Tier.PROJECTION, ev),
        },
        axis=Claim(Axis3(centre, zdir), "revolve:cone_zone",
                   Tier.PROJECTION, ev),
        placement=Claim(centre, "revolve:cone_zone", Tier.PROJECTION, ev),
        source_view="", evidence=list(ev),
    )
    # 四帽：轴对齐盒（相对轴心），+0.1 余量防相切布尔
    w = math.sqrt(r_hi * r_hi - r_top * r_top) + 0.1
    rt, rh = r_top, r_hi + 0.1
    boxes = [
        [(rt, -w), (rh, -w), (rh, w), (rt, w)],        # +x 帽
        [(-rh, -w), (-rt, -w), (-rt, w), (-rh, w)],    # −x 帽
        [(-w, rt), (w, rt), (w, rh), (-w, rh)],        # +y 帽
        [(-w, -rh), (w, -rh), (w, -rt), (-w, -rt)],    # −y 帽
    ]
    caps = [
        Feature(
            id=FeatureId(-1),
            type=Claim(FeatureType.POCKET, "revolve:cone_cap",
                       Tier.PROJECTION, ev),
            params={
                "profile": mk_claim(box, "revolve:cone_cap",
                                    Tier.PROJECTION, ev),
                "depth": mk_claim(t1 - t0, "revolve:cone_cap",
                                  Tier.PROJECTION, ev),
                "axial_at": mk_claim(t0, "revolve:cone_cap",
                                     Tier.PROJECTION, ev),
            },
            axis=Claim(Axis3(centre, zdir), "revolve:cone_cap",
                       Tier.PROJECTION, ev),
            placement=Claim(centre, "revolve:cone_cap", Tier.PROJECTION, ev),
            source_view="", evidence=list(ev),
        )
        for box in boxes
    ]
    # 内腔补偿切：REVOLVE 闭合到轴 ⇒ 锥台恒为 r≤r(z) 实心盘，会把基体
    # 锥带的内腔填实（PF60K π·234×1.763=+1,296.3 逐位对账）——须按主母线
    # 内壁把腔切回。walls = 主母线竖边（|Δr|≤RADIUS_TOL）的恒定半径，
    # 同半径合并后**并集须覆盖整个 [t0,t1]**（半截竖边不采信）；升序后
    # 环 [edges[j],edges[j+1]] 下方壁数 = j ⇒ j 偶为腔、j 奇为材料
    # （锥台盘自带材料，腔须切）。PF60K：walls=[7,16,21,30] ⇒ 腔 =
    # r≤7（HOLE）+ r∈[16,21]（C 形环带 POCKET）。
    raw_walls: list[float] = []
    for (ta, ra), (tb, rb) in zip(prof, prof[1:]):
        if abs(ra - rb) > RADIUS_TOL or float(ra) <= 0.0:
            continue
        if min(ta, tb) > t1 + 0.05 or max(ta, tb) < t0 - 0.05:
            continue                              # 竖边须与锥带相交
        raw_walls.append(float(ra))
    walls: list[float] = []
    for r in sorted(raw_walls):
        if not walls or abs(r - walls[-1]) > RADIUS_TOL:
            walls.append(r)

    def _covers(r: float) -> bool:
        """同半径竖边段的 t 并集是否覆盖 [t0−0.05, t1+0.05]。"""
        segs = sorted((min(ta, tb), max(ta, tb))
                      for (ta, ra), (tb, rb) in zip(prof, prof[1:])
                      if abs(ra - rb) <= RADIUS_TOL
                      and abs(float(ra) - r) <= RADIUS_TOL)
        cur = t0 - 0.05
        for a, b in segs:
            if a > cur + 1e-6:
                return False
            cur = max(cur, b)
        return cur >= t1 + 0.05 - 1e-6

    walls = [r for r in walls if _covers(r)]
    restores: list[Feature] = []
    edges = [0.0] + walls
    for j in range(len(edges) - 1):
        if j % 2 == 1:
            continue                              # 奇环 = 材料，锥台盘自带
        r_in, r_out = edges[j], edges[j + 1]
        if r_in <= 0.0:
            # 最内腔 = 圆孔：HOLE 自锥底 t0 朝 +轴向 钻 t1−t0（孔口契约）
            restores.append(Feature(
                id=FeatureId(-1),
                type=Claim(FeatureType.HOLE, "revolve:cone_restore",
                           Tier.PROJECTION, ev),
                params={
                    "radius": mk_claim(r_out, "revolve:cone_restore",
                                       Tier.PROJECTION, ev),
                    "depth": mk_claim(t1 - t0, "revolve:cone_restore",
                                      Tier.PROJECTION, ev),
                    "axial_at": mk_claim(t0, "revolve:cone_restore",
                                         Tier.PROJECTION, ev),
                },
                axis=Claim(Axis3(centre, zdir), "revolve:cone_restore",
                           Tier.PROJECTION, ev),
                placement=Claim(centre, "revolve:cone_restore",
                                Tier.PROJECTION, ev),
                source_view="", evidence=list(ev),
            ))
        else:
            # 环带腔：C 形单链 profile = 外圆 CCW 两半 + 径向缝 + 内圆
            # CW 两半 + 回缝。缝零宽、落在切除区内，两发射器均支持
            # Profile2 弧段（三点弧），无需改动
            segs = [
                ProfileSeg2("arc", Point2(r_out, 0.0), Point2(-r_out, 0.0),
                            Point2(0.0, 0.0), r_out, True, 0.0, math.pi),
                ProfileSeg2("arc", Point2(-r_out, 0.0), Point2(r_out, 0.0),
                            Point2(0.0, 0.0), r_out, True, math.pi,
                            2.0 * math.pi),
                ProfileSeg2("line", Point2(r_out, 0.0), Point2(r_in, 0.0)),
                ProfileSeg2("arc", Point2(r_in, 0.0), Point2(-r_in, 0.0),
                            Point2(0.0, 0.0), r_in, False, 0.0, math.pi),
                ProfileSeg2("arc", Point2(-r_in, 0.0), Point2(r_in, 0.0),
                            Point2(0.0, 0.0), r_in, False, math.pi,
                            2.0 * math.pi),
                ProfileSeg2("line", Point2(r_in, 0.0), Point2(r_out, 0.0)),
            ]
            restores.append(Feature(
                id=FeatureId(-1),
                type=Claim(FeatureType.POCKET, "revolve:cone_restore",
                           Tier.PROJECTION, ev),
                params={
                    "profile": mk_claim(Profile2(tuple(segs)),
                                        "revolve:cone_restore",
                                        Tier.PROJECTION, ev),
                    "depth": mk_claim(t1 - t0, "revolve:cone_restore",
                                      Tier.PROJECTION, ev),
                    "axial_at": mk_claim(t0, "revolve:cone_restore",
                                         Tier.PROJECTION, ev),
                },
                axis=Claim(Axis3(centre, zdir), "revolve:cone_restore",
                           Tier.PROJECTION, ev),
                placement=Claim(centre, "revolve:cone_restore",
                                Tier.PROJECTION, ev),
                source_view="", evidence=list(ev),
            ))
    plan.cone = ConeZone(t0=t0, t1=t1, r_hi=r_hi, r_top=r_top,
                         cone=cone, caps=caps, restores=restores, evidence=ev)
    rep.notes.append(
        f"锥段：z{t0:.2f}..{t1:.2f} r{r_hi:g}→{r_top:g}（成对锥母线 + "
        f"同轴弧，方料顶面 {t0:.3f}）⇒ 独立锥台 REVOLVE + {len(caps)} 个 "
        f"POCKET 帽切 + {len(restores)} 个内腔补偿切"
        + (f"（walls={[round(w, 2) for w in walls]}）" if restores else ""))


# ---------------------------------------------------------------------------
# 附着：solve 之后的补轴向位置 + 定型 + 消解疑问
# ---------------------------------------------------------------------------

def attach_revolve(d: Drawing, corr: CorrespondenceResult, plan: RevolvePlan,
                   part, rep: RecognizeReport) -> None:
    """在 ``solve`` 之后收尾：

    1. 角孔（轴平行回转轴、不在轴上）从孔壁轮廓线读出轴向位置（z 跨度
       到**孔轴**的距离 ≈ 孔半径的那族线）；
    2. 有硬依据的 GUESS 孔定型：孔口在零件端面 / 孔嵌于方料块内 ⇒ HOLE；
    3. 消解对应疑问（``#id.type``、"孔/凸台未定"、r1.65 vs R10 标准值、
       同心圆边的"沉孔/台阶 vs 独立圆边"——判据见末尾按证据覆盖消解那段）。
    """
    qs = rep.questions
    if plan.axis is None:
        return
    zdir = plan.axis.direction
    all_lines = [ln for ls in plan.lines.values() for ln in ls]

    for f in list(part.features):
        if f.type.value != "hole" or f.axis is None or f.axis.value is None:
            continue
        ax = f.axis.value
        if not _parallel_either(ax.direction, zdir):
            continue
        rg = _radial(ax.origin, plan.axis.origin, plan.dir_name)
        if rg <= 1.5:
            continue                                  # 轴上的孔不是"角孔"
        r_h = f.params.get("radius")
        if r_h is None:
            continue
        # 孔轴的径向位置读数 = |孔轴心 − 回转轴心| 的**视图平面侧向分量**
        # （轴向线在另一维的 model 坐标是占位 0，垂距只能走 ln.r）
        ch = {"x": ax.origin.x - plan.axis.origin.x,
              "y": ax.origin.y - plan.axis.origin.y,
              "z": ax.origin.z - plan.axis.origin.z}
        handles: list[str] = []
        zs: list[float] = []
        for ln in all_lines:
            if plan.square_r is not None and abs(ln.r - plan.square_r) <= RADIUS_TOL:
                continue                              # 方料轮廓不是孔壁
            # 这条线是孔壁轮廓吗：其径向读数到"孔轴径向位置"的距离
            # ≈ 孔半径（孔壁线成对出现于孔轴两侧）
            dr = abs(abs(ln.r - abs(ch[ln.rad_axis])) - r_h.value)
            if dr <= 0.5:
                handles.append(ln.handle)
                zs.extend((ln.t0, ln.t1))
        if len(zs) < 2:
            continue
        z0, z1 = min(zs), max(zs)
        depth = f.params.get("depth")
        if depth is not None and abs((z1 - z0) - depth.value) > 0.8:
            continue                                  # 与轮廓对深度对不上 ⇒ 不采信
        evh = tuple(dict.fromkeys(handles))
        if "axial_at" not in f.params:
            f.params["axial_at"] = Claim(z0, "revolve:hole_wall_span",
                                         Tier.PROJECTION, evh)
        # 定型依据
        if z0 <= plan.t_lo + 0.35:
            by, why = ("revolve:endface_opening",
                       "孔口开在零件端面（凸台没有外伸空间）")
        elif any(a - 0.35 <= z0 and z1 <= b + 0.35
                 for a, b in plan.square_spans):
            by, why = ("revolve:embedded_in_square",
                       "孔段完全嵌在方料块内（嵌于材料内的圆柱不构成凸台）")
        else:
            continue
        if not f.type.is_settled:
            f.type = Claim(FeatureType.HOLE, by, Tier.PROJECTION, evh)
            rep.notes.append(f"#{f.id} 定型为孔：{why}")
        for q in qs.find(OpenQuestion.AMBIGUOUS_FEATURE,
                         detail_contains=f"#{f.id}（"):
            qs.resolve(q, f"hole（{why}）", by)

    # r1.65 vs R10 标准值：M4 螺纹底孔 Ø3.3 是加工标准（GB/T 196 粗牙），
    # 不取 R10 优先数的 1.6 —— 这是"标注值优先"原则的又一例
    for q in qs.find(OpenQuestion.AMBIGUOUS_FEATURE,
                     detail_contains="标准值是 1.6（"):
        qs.resolve(q, "1.65 = M4 螺纹底孔 Ø3.3（GB/T 196 粗牙系列）",
                   "revolve:thread_prior")

    # 跨视图对应的"孔/凸台未定"：本零件里这类疑问只可能来自角孔
    # （同心圆全被 skip_outline 摘掉了），定型后一并裁决
    for q in qs.find(OpenQuestion.AMBIGUOUS_FEATURE,
                     detail_contains="孔/凸台未定"):
        qs.resolve(q, "hole（见 revolve 的端面/方料依据）",
                   "revolve:corr_ambiguity")

    # 同心圆边的"沉孔/倒角/台阶 vs 同一面上的独立圆边"歧义：本零件的两组圆
    # **各由实据吸收**，不是猜掉的 ——
    # ① 轴上的那组：剖面扫描把各半径读成母线台阶（半径证据整组进 base.evidence，
    #    见 detect_revolve 里收证据那段）；
    # ② 角上的那组：各圆边已各自定型成独立孔（轴向位置由孔壁线跨度定，见上）。
    # 判据是**证据覆盖**：疑问的证据 handle 全落在谁名下，就是谁消解了它 ——
    # 比按文字/半径猜稳（同一半径可能圆成 8 / 8.5 两说，按半径比会翻车）。
    absorbed = {str(x) for x in plan.base.evidence}
    holes_ev: set[str] = set()
    for f in part.features:
        if f.type.value == "hole" and f.type.is_settled:
            holes_ev.update(str(x) for x in f.evidence)
    for q in qs.find(OpenQuestion.AMBIGUOUS_FEATURE,
                     detail_contains="条同心圆边"):
        ev = {str(x) for x in q.evidence}
        if ev <= absorbed:
            qs.resolve(q, "回转体母线的台阶（剖面扫描把该半径读成母线台阶，"
                          "不再各建特征）", "revolve:profile_absorbed")
        elif ev <= holes_ev:
            qs.resolve(q, "独立孔（各圆边已各自定型为孔，轴向位置由孔壁线跨度定）",
                       "revolve:independent_holes")

    # HLR 重合消影/混合壁之疑（corr 层按"母线带内实/虚并存"报的）：圆边
    # 被回转基体吸收 ⇒ 实虚并存是凹槽/台阶自身的图面（槽底轮廓与槽缘棱），
    # "孔壁虚线被消影"的读法不成立；已定型为独立孔的按孔收（消影孔读法）。
    for q in qs.find(OpenQuestion.AMBIGUOUS_FEATURE, detail_contains="消影"):
        if not q.evidence:
            continue
        h0 = str(q.evidence[0])
        if h0 in absorbed:
            qs.resolve(q, "母线台阶（圆边被回转基体吸收，实虚并存是凹槽/"
                          "台阶自身的图面，非消影之孔）",
                       "revolve:profile_absorbed")
        elif h0 in holes_ev:
            qs.resolve(q, "孔（圆边已定型为独立孔，实虚并存按消影孔读）",
                       "revolve:independent_holes")


__all__ = ["AxLine", "RevolvePlan", "attach_revolve", "detect_revolve"]
