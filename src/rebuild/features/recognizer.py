# -*- coding: utf-8 -*-
"""特征识别 —— 证据 + 对应 + 约定 ⇒ 特征树（ARCHITECTURE §6.3、阶段 3）。

## 本模块的立场：**只认有依据的特征，认不出的如实留着**

旧管线是"先造几何、再反推特征"（`dxf_to_sw_features.py` 从 CSG 结果切片
反推）—— 等于把烧掉的信息再猜一遍。这里是反的：先把**说得清依据的**特征
装进树，每一条都带 evidence 与 tier；说不清的地方变成 ``OpenQuestion``，
由覆盖率的缺口说话（未解释的图元有多少，report 里看得见）。

于是"这个零件重建得对不对"变成可查的问题：**特征树解释了哪些图元、
没解释哪些、每个数字的依据是什么。**

## 三路来源，按可信度参与 merge

1. **剖面标题**（ANNOTATED，最硬）——「B—B 横剖 x=121.89（穿 r25.5 孔轴）」
   直接给出"这里有一条沿 Z 的孔轴，半径 25.5"
2. **跨视图对应**（PROJECTION）—— 一个视图里的圆 + 正交视图里的轮廓对
   ⇒ ``CylinderHint``（圆柱，含长度与"孔还是凸台"）
3. **约定**（CONVENTION）—— 阵列/螺纹/对称面

同一特征被多路说中时**不挑一个丢一个**：值取高 tier，其余进备选、
证据合并（§3 原则二）。bracket 上正是这样：B—B 的 r25.5 与俯视图的
r25.5 圆说的是同一个凸台，合并后证据有两条。

## 不做的事（写下来是为了以后别顺手加）

- **环提取不在本模块里**（2026-10-07 起已接线）：轮廓环是独立的证据通道
  ``views/ring.py``（旧管线"边图→封闭环"那块的最重分量），本模块只负责
  把它换算成发射器契约挂到基体上；**提到环就按环建基体**，提不到才退回
  视图包围盒近似（并如实报一条待确认）
- **不把"未注圆角"塞进特征树**：那是全局技术条件，不是可定位的特征。
  它已经在约定层（``simplification.fillets``）报出来了，重复一遍只会
  让发射器收到建不出来的特征
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from ..evidence.model import Role
from ..model.claim import Claim, Tier
from ..model.feature_tree import Feature, FeatureType, Part, SymmetryOp
from ..model.geom import Axis3, Point3, Vector3
from ..model.geom2d import Point2, Profile2, ProfileSeg2, profile_span
from ..model.ids import FeatureId
from ..model.questions import OpenQuestion, Question, QuestionList
from ..views.correspondence import (MATCH_TOL, CorrespondenceResult,
                                    CylinderHint, ViewFrame)
from ..views.ring import extract_ring
from .library import ir_point, mk_claim
from .solver import Conflict, SolveReport, merge_with_conflict, solve

if TYPE_CHECKING:
    from .revolve import RevolvePlan

#: 两条轴"是同一条"的判据：垂直距离 + 方向夹角
AXIS_POS_TOL = 0.6       # mm
AXIS_DIR_TOL = 1e-3      # 方向余弦差（轴向必须几乎一致）

#: 拉伸方向 → 轮廓平面的两个模型轴（与 ``library.profile_plane`` 同一张表）
_PLANE_AXES: dict[str, tuple[str, str]] = {
    "x": ("y", "z"), "y": ("z", "x"), "z": ("x", "y")}

#: 基体外轮廓环的**跨度覆盖率**下限：环的几何 bbox 必须铺满轮廓跨度。
#: ring.py 自身的 0.75 门控只保证"这个环像外轮廓"，应付不了"内部子环"：
#: 实测 PF60K 的 V1 提出一个 48 段台阶区子环，覆盖率 1.00×0.76 恰好过门，
#: 基体因此丢 24% 高度（体积 −31.4% → −71.5%）。真外轮廓在四张验证图上
#: 全是 1.00×1.00，空隙干净，0.98 只是留出浮点与出图抖动。
RING_SPAN_MIN = 0.98


def _dirs_parallel(a: Vector3, b: Vector3) -> bool:
    return max(abs(a.x - b.x), abs(a.y - b.y), abs(a.z - b.z)) < AXIS_DIR_TOL


def _dirs_parallel_either_way(a: Vector3, b: Vector3) -> bool:
    """同一条直线（方向可反）。识别的轴朝向由证据定，正负号不作区分。"""
    return _dirs_parallel(a, b) or _dirs_parallel(
        a, Vector3(-b.x, -b.y, -b.z))


def axis_distance(a: Axis3, b: Axis3) -> float | None:
    """两条平行轴的垂直距离；不平行返回 None。

    点线距离用叉积：``|(p2−p1) × d| / |d|``（d 已归一）。
    """
    if not _dirs_parallel(a.direction, b.direction):
        return None
    v = b.origin - a.origin
    cross = v.cross(a.direction)
    return cross.norm


@dataclass
class RecognizeReport:
    """识别过程的可读输出（report.py 消费）。"""

    part: Part
    questions: QuestionList = field(default_factory=QuestionList)
    notes: list[str] = field(default_factory=list)
    #: 同一参数两路"硬依据"对不上（§6.2 说的"图纸自相矛盾"）
    conflicts: list[Conflict] = field(default_factory=list)
    #: 求解报告（``recognize`` 末尾自动跑一次；单独调 ``solve`` 则为 None）
    solved: SolveReport | None = None
    #: 回转体检测的产出（``revolve.detect_revolve``；None = 非回转体）。
    #: 基体已换成 REVOLVE 时，附属体（方料/键槽）与消解材料也在这里。
    revolve: "RevolvePlan | None" = None
    #: 高度分解的产出（``height_zones.decompose``；None = 未分解）。
    #: 成立时基体的 ``length`` 已被改短（降到最低公共顶面），材料总跨度
    #: 以 ``zones.span()`` 为准 —— ``derive_through`` 必须照它判通孔。
    zones: "HeightPlan | None" = None

    def describe(self) -> str:
        lines = [f"识别出 {len(self.part.features)} 个特征"]
        for f in self.part.features:
            lines.append(f"  #{f.id} {f.type.value} "
                         f"依据 {f.type.method} <{f.type.tier.name}> "
                         f"图元 {len(f.evidence)} 项")
        lines.extend("  " + n for n in self.notes)
        if self.solved is not None:
            lines.append("  —— 求解 ——")
            lines.extend("  " + ln for ln in
                         self.solved.describe(questions=False).splitlines())
        if self.questions:
            lines.append(f"  待确认 {len(self.questions)} 项")
            lines.extend("    " + str(q) for q in self.questions)
        return "\n".join(lines)


# ---- 1) 基体 ----

def _extents(frames) -> dict[str, float]:
    """各模型轴上的零件总跨度（断裂视图的轴不参与）。"""
    out: dict[str, float] = {}
    for a in "xyz":
        spans = [f.model_span(a) for f in frames.values()]
        spans = [s for s in spans if s is not None]
        if spans:
            out[a] = max(s[1] for s in spans) - min(s[0] for s in spans)
    return out


def _outer_circle(corr: CorrespondenceResult, frame: ViewFrame) -> CylinderHint | None:
    """单视图里"顶到图面外沿"的那个圆 —— 它是**基体的外轮廓**，不是特征。

    判据只有一条：直径 = 图面跨度（容差 2%）。不做同心性检查 ——
    单视图里所有圆的轴都是图面法向，本来就同轴。
    """
    span = max(frame.u_span[1] - frame.u_span[0],
               frame.v_span[1] - frame.v_span[0])
    best: CylinderHint | None = None
    for c in corr.cylinders():
        h = c.mapping.value
        if not isinstance(h, CylinderHint):
            continue
        if abs(h.radius * 2.0 - span) > max(1.0, 0.02 * span):
            continue
        if best is None or h.radius > best.radius:
            best = h
    return best


def guess_single_depth(corr: CorrespondenceResult, frame: ViewFrame
                       ) -> tuple[float, str, tuple[float, ...]]:
    """单视图的**厚度猜测** —— 返回 (值, 依据串, 备选值)。

    图纸只画了一个视图 ⇒ 垂直于图面的那一维**图上不存在**，任何数值都是
    猜的。这里沿用旧管线 ``dxf_to_3d_general.py`` 的三档启发式（原样照抄，
    因为三个单视图回归基线正是它给出的）：

        估算深度（:7598）:  depth = 最大孔径×4 或 图面跨度×0.3，再 max(·, 10)
        圆形主体修正(:8759):  外轮廓是圆且半径<100 ⇒ depth = max(depth×0.15, 10)

    实测复现：plate_100x60 → 20、l_bracket → 18、flange_d80 → 24，
    与 ``run_simple_regression.py`` 的金值逐位相同。

    **降级成 GUESS 是本框架与旧管线的全部差别**：旧管线把这个数当成
    ``projection`` 直接发射，调用方无从分辨"量出来的"与"编出来的"；
    这里它是 ``Tier.GUESS``，备选值一并列出，并由调用方报成拦路待确认项。
    """
    radii = [c.mapping.value.radius for c in corr.cylinders()
             if isinstance(c.mapping.value, CylinderHint)]
    max_r = max(radii) if radii else 0.0
    span = max(frame.u_span[1] - frame.u_span[0],
               frame.v_span[1] - frame.v_span[0])
    if max_r > 0:
        base, method = max_r * 4.0, "guess:max_hole_dia_x4"
        alts = (round(span * 0.3, 3), 10.0)
    else:
        base, method = span * 0.3, "guess:view_span_x0.3"
        alts = (10.0,)
    # 外轮廓是圆 ⇒ 圆形零件，实测该档才是基线值
    outer = _outer_circle(corr, frame)
    circular = outer is not None and outer.radius < 100.0
    depth = max(base, 10.0)
    if circular:
        depth = max(depth * 0.15, 10.0)
        method += "+circular_body_x0.15"
    depth = round(depth, 6)
    # 备选里不能重复主值（``Claim`` 会拒绝），圆形零件取 0.15 档后
    # 恰好与主值撞车是常态（24 = 160×0.15 而 24 也在备选里）
    return depth, method, tuple(a for a in alts if abs(a - depth) > 1e-9)


def _revolve_base(dir_name: str, radius: float, length: float, centre: Point3,
                  ev: tuple, source_view: str, method: str,
                  dir_claim: Claim | None = None) -> Feature:
    """圆轮廓的基体 = **回转体**（法兰/盘/套），不是棱柱。

    ``radius_profile`` 按 ``library`` 的 REVOLVE 契约给：``[(沿轴坐标, 半径)]``，
    整圆柱就是一条水平母线（两点的闭合由发射器补轴段，见 occ_builder）。
    """
    return Feature(
        id=FeatureId(0),
        type=Claim(FeatureType.REVOLVE, method, Tier.PROJECTION, evidence=ev),
        params={
            "dir": dir_claim or Claim(dir_name, "projection:view_normals",
                                      Tier.PROJECTION, evidence=ev),
            "angle_deg": Claim(360.0, "convention:full_revolve",
                               Tier.CONVENTION, evidence=ev),
            "radius_profile": Claim([(0.0, radius), (length, radius)],
                                    "projection:circle_outline",
                                    Tier.PROJECTION, evidence=ev),
            "origin": Claim(centre, "projection:circle_center",
                            Tier.PROJECTION, evidence=ev),
        },
        axis=Claim(Axis3(centre, _axis_vector(dir_name)), method,
                   Tier.PROJECTION, evidence=ev),
        placement=Claim(centre, "projection:circle_center", Tier.PROJECTION,
                        evidence=ev),
        source_view=source_view,
        evidence=list(ev),
    )


def _profile_circle(corr: CorrespondenceResult, dir_name: str,
                    lo1: float, hi1: float, lo2: float,
                    hi2: float) -> CylinderHint | None:
    """轮廓外沿是不是一个圆 —— 是则返回那个圆。

    判据三条（全中才算）：轴与拉伸方向平行、直径 = 轮廓两个跨度、圆心在轮廓中心。
    """
    r_want = (hi1 - lo1) / 2.0
    if abs((hi2 - lo2) / 2.0 - r_want) > max(0.5, 0.02 * r_want):
        return None                      # 轮廓不是方的，先排除
    c1, c2 = (lo1 + hi1) / 2.0, (lo2 + hi2) / 2.0
    b1_axis, b2_axis = _PLANE_AXES[dir_name]
    for c in corr.cylinders():
        h = c.mapping.value
        if not isinstance(h, CylinderHint):
            continue
        if abs(h.radius - r_want) > max(0.5, 0.02 * r_want):
            continue
        if not _dirs_parallel_either_way(h.axis.direction, _axis_vector(dir_name)):
            continue
        co = {"x": h.axis.origin.x, "y": h.axis.origin.y, "z": h.axis.origin.z}
        if abs(co[b1_axis] - c1) > 0.5 or abs(co[b2_axis] - c2) > 0.5:
            continue
        return h
    return None


def _outline_ring_profile(d, frame: ViewFrame, dir_name: str,
                          lo1: float, hi1: float, lo2: float, hi2: float
                          ) -> tuple[Profile2 | None, str]:
    """正对轮廓平面的那个视图 → (a, b) 系的 ``Profile2``（轮廓环通道）。

    证据链：视图可见轮廓边 → ``views.ring.extract_ring``（含覆盖率门控）
    → 视图 2D 坐标过 ``ViewFrame`` 平移到模型系 → 按 ``_PLANE_AXES``
    转置 → 相对轮廓角点 (lo1, lo2) 的 (a, b) 坐标（与包围盒路径**同一
    套坐标口径**，只是形状从矩形换成真轮廓）。

    坐标转置时**弧的旋向可能翻转**：视图的 (u, v) 与平面的 (b1, b2)
    顺序未必一致（沿 y 拉伸的平面是 (z, x)，而前视图 u=x、v=z 恰好
    对调），故弧的 ``ccw``/``sa``/``ea`` 一律在 (a, b) 系里**重判重算**
    ——判据与 SW 发射器同一套（弧中点弦叉积符号），不搬运视图系角度。

    返回 ``(profile, 说明)``；不可用时 profile=None，说明串写明原因供
    报告与待确认项引用。注意**跨度覆盖率门控**（``RING_SPAN_MIN``）：
    环的 bbox 必须铺满 (lo1..hi1, lo2..hi2) 给的轮廓跨度，否则它是
    内部子环（实测 PF60K V1 的台阶区子环 0.76 覆盖率），不是外轮廓。
    """
    b1_axis, b2_axis = _PLANE_AXES[dir_name]
    if frame.p_axis != dir_name:
        return None, f"{frame.view_id} 的投影方向不是 {dir_name}（看不到该轮廓面）"
    if {b1_axis, b2_axis} & set(frame.broken_axes):
        return None, "视图沿轮廓轴断裂，跨度残缺"
    view = next((v for v in d.views if v.id == frame.view_id), None)
    if view is None:
        return None, "视图对象缺失"
    res = extract_ring(d, view)
    if res.ring is None:
        return None, res.note or "环提取无结果"

    def fwd(p: Point2) -> Point2:
        # 必须走 ``u_to_model``/``v_to_model``：帧的翻面（``u_flip``/``v_flip``，
        # 由 ``resolve_frame_mirrors`` 的跨视图投票裁决）就写在那两个方法里。
        # 曾经这里直接用 ``p.x + u_off`` —— bracket 俯视图 V0 判为翻面（u 与
        # 模型 x 反向，实测 u=185.302 处是模型 x=22 的臂端），照搬 u ⇒ 基体轮廓
        # 沿 x 镜像（臂端与环对调），与同图纸读出的圆孔坐标不自洽。
        m = {frame.u_axis: frame.u_to_model(p.x),
             frame.v_axis: frame.v_to_model(p.y)}
        return Point2(m[b1_axis] - lo1, m[b2_axis] - lo2)

    segs: list[ProfileSeg2] = []
    for s in res.ring.segs:
        p1, p2 = fwd(s.p1), fwd(s.p2)
        if s.kind != "arc":
            segs.append(ProfileSeg2("line", p1, p2))
            continue
        if s.center is None or s.radius <= 0:
            return None, "弧段缺圆心/半径（环数据不完整）"
        c = fwd(s.center)
        # 弧中点：先按视图系 sa/ea/ccw 取参数中点，跟着端点一起映射
        tau = 2.0 * math.pi
        span = ((s.ea - s.sa) if s.ccw else (s.sa - s.ea)) % tau
        thm = s.sa + span / 2.0 if s.ccw else s.sa - span / 2.0
        pm = fwd(Point2(s.center.x + s.radius * math.cos(thm),
                        s.center.y + s.radius * math.sin(thm)))
        cross = ((pm.x - p1.x) * (p2.y - pm.y)
                 - (pm.y - p1.y) * (p2.x - pm.x))
        if abs(cross) < 1e-9:
            return None, "弧段旋向不可判（弦叉积为零）"
        segs.append(ProfileSeg2(
            "arc", p1, p2, c, s.radius, cross > 0.0,
            math.atan2(p1.y - c.y, p1.x - c.x),
            math.atan2(p2.y - c.y, p2.x - c.x)))
    prof = Profile2(tuple(segs))
    if prof.chain_break() is not None:
        return None, "映射后段链断开（已被守卫拒绝）"
    if prof.signed_area() < 0.0:
        # 转置对调轴 ⇒ 环翻成 CW，统一回契约的 CCW 正面积
        prof = prof.reversed()
    # 跨度覆盖率门控（见 ``RING_SPAN_MIN``）：外轮廓必须铺满轮廓跨度，
    # 内部子环（台阶区/局部轮廓）在 ring.py 的 0.75 门控下会漏网
    bb = prof.bbox()
    w, h = hi1 - lo1, hi2 - lo2
    if w > 0.0 and h > 0.0:
        cw, ch = bb.width / w, bb.height / h
        if min(cw, ch) < RING_SPAN_MIN:
            return None, (f"环只覆盖轮廓跨度 {cw:.2f}×{ch:.2f}"
                          f"（< {RING_SPAN_MIN}）—— 疑似内部子环，弃用")
    note = (f"{len(prof.segments)} 段（面积 {res.ring.area:.2f}，"
            f"覆盖率 {res.ring.coverage[0]:.2f}×{res.ring.coverage[1]:.2f}，"
            f"rule={res.ring.rule}）")
    return prof, note


#: 锥化剪影判据的容差（比例口径，相对视图跨度）
TAPER_TOL = 0.02


@dataclass(frozen=True)
class _Taper:
    """锥化体判据的结论：沿 ``axis`` 自低端收敛到一点（宽端在 t_lo 一侧）。"""

    axis: str
    views: tuple[str, ...]


def _detect_taper(d, frames, ext: dict[str, float],
                  rep: RecognizeReport) -> "_Taper | None":
    """锥化体（棱锥）判据：侧看轮廓是**干净的三角形**（``图形练习`` 的四棱锥）。

    词汇很窄，五条全中才算（读不出的形状宁可不说，不许猜）：
    1. 某视图的可见轮廓环恰好 3 条直线段；
    2. 底边是**唯一**一条平行于视图 u/v 轴的边（等腰三角形的斜边比底长，
       不能拿"最长边"当底）⇒ 锥化轴 = 该视图的另一条轴；
    3. 顶点在底边中垂线上（偏移 ≤ 2% 跨度）——与"绕轴缩到中心一点"同一读法；
    4. 底边长度 = 底面视图（``p_axis`` = 锥化轴）沿同一条模型轴的跨度 ——
       这条把"三角棱柱"的读法排除在外（棱柱的底面视图跨度对不上底边宽）；
    5. 底/顶分别落在锥化轴跨度的两端，且**宽端在低端**（倒锥不在词汇表，
       检出即记账但不采用）。

    多视图报出不同锥化轴 ⇒ 判无 + 记账（互相矛盾的证据不强行调和）。
    """
    found: list[_Taper] = []
    for frame in frames.values():
        view = next((v for v in d.views if v.id == frame.view_id), None)
        if view is None:
            continue
        res = extract_ring(d, view)
        if res.ring is None or len(res.ring.segs) != 3:
            continue
        segs = res.ring.segs
        if any(s.kind != "line" for s in segs):
            continue
        span = max(frame.u_span[1] - frame.u_span[0],
                   frame.v_span[1] - frame.v_span[0])
        tol = max(0.5, TAPER_TOL * span)
        # 底边 = **唯一**一条与视图轴平行的边（不能取"最长边"：等腰三角形的
        # 斜边比底边长，图形练习里 67.08 > 60，取最长会取到斜边）
        base_edges = [(s.p1, s.p2) for s in segs
                      if abs(s.p1.y - s.p2.y) <= tol or abs(s.p1.x - s.p2.x) <= tol]
        if len(base_edges) != 1:
            continue
        a, bpt = base_edges[0]
        apex = next((s.p1 for s in segs
                     if s.p1.distance_to(a) > 1e-9
                     and s.p1.distance_to(bpt) > 1e-9), None)
        if apex is None:
            continue
        if abs(a.y - bpt.y) <= tol:               # 水平底边 ⇒ 沿 v 轴锥化
            axis_name, edge_axis = frame.v_axis, frame.u_axis
            base_pos, apex_pos = (a.y + bpt.y) / 2.0, apex.y
            base_len = abs(a.x - bpt.x)
            centred = abs(apex.x - (a.x + bpt.x) / 2.0) <= tol
            to_model = frame.v_to_model
        elif abs(a.x - bpt.x) <= tol:             # 竖直底边 ⇒ 沿 u 轴锥化
            axis_name, edge_axis = frame.u_axis, frame.v_axis
            base_pos, apex_pos = (a.x + bpt.x) / 2.0, apex.x
            base_len = abs(a.y - bpt.y)
            centred = abs(apex.y - (a.y + bpt.y) / 2.0) <= tol
            to_model = frame.u_to_model
        else:
            continue
        if not centred or axis_name not in ext:
            continue
        mspan = frame.model_span(axis_name)
        if mspan is None:
            continue
        m_lo, m_hi = mspan
        base_m, apex_m = to_model(base_pos), to_model(apex_pos)
        if abs(base_m - m_hi) <= tol and abs(apex_m - m_lo) <= tol:
            rep.notes.append(
                f"锥化剪影（{frame.view_id}）：三角形朝 −{axis_name} 收敛 —— "
                "倒锥不在本词汇表内，该视图不作数")
            continue
        if abs(base_m - m_lo) > tol or abs(apex_m - m_hi) > tol:
            continue                              # 两端没顶满跨度 ⇒ 不是收敛到端点
        plan = next((f2 for f2 in frames.values() if f2.p_axis == axis_name), None)
        if plan is None:
            continue
        pspan = plan.model_span(edge_axis)
        if pspan is None or abs(base_len - (pspan[1] - pspan[0])) > tol:
            continue
        found.append(_Taper(axis_name, (frame.view_id,)))
    if not found:
        return None
    axes = {t.axis for t in found}
    if len(axes) > 1:
        rep.notes.append(
            f"锥化剪影出现在多个轴上（{sorted(axes)}），互相矛盾 ⇒ 不认定锥化")
        return None
    views = tuple(dict.fromkeys(v for t in found for v in t.views))
    rep.notes.append(
        f"锥化剪影：{', '.join(views)} 的可见轮廓是三角形（顶点居中、两端顶满跨度）"
        f"⇒ 基体读作沿 {found[0].axis} 自低端**收敛到一点**（锥化拉伸）")
    return _Taper(found[0].axis, views)


def _single_face_base(d, corr: CorrespondenceResult, frames,
                      rep: RecognizeReport) -> Feature:
    """单视图基体：看得见的那个面按实量，看不见的那一维按猜。

    与 ``base_feature`` 的分工是"信息量的差别"，不是"代码的差别"：
    三个视图齐了才能说"沿最薄的方向拉伸"（那是量出来的），只有一个
    视图时连"哪一维是深度"都是约定 —— 故 ``dir`` 也是 GUESS。
    """
    frame = next(iter(frames.values()))
    dir_name = frame.p_axis
    b1_axis, b2_axis = _PLANE_AXES[dir_name]
    ev = tuple(dict.fromkeys(e for v in d.views for e in v.evidence[:1]))
    depth, method, alts = guess_single_depth(corr, frame)
    same_normal = len({f.p_axis for f in frames.values()}) == 1
    # 跨度按**轴名**取而不是按 u/v 顺序：p=y 的前视图 (u,v)=(x,z) 与轮廓
    # 平面 (b1,b2)=(z,x) 恰好对调，按顺序取会把轮廓转 90°
    if (frame.u_axis, frame.v_axis) == (b1_axis, b2_axis):
        (lo1, hi1), (lo2, hi2) = frame.u_span, frame.v_span
    elif (frame.u_axis, frame.v_axis) == (b2_axis, b1_axis):
        (lo1, hi1), (lo2, hi2) = frame.v_span, frame.u_span
    else:
        raise ValueError(
            f"{frame.view_id} 的可见轴 ({frame.u_axis},{frame.v_axis}) 与 "
            f"{dir_name} 向轮廓平面 ({b1_axis},{b2_axis}) 不相配")
    box = [(0.0, 0.0), (hi1 - lo1, 0.0), (hi1 - lo1, hi2 - lo2), (0.0, hi2 - lo2)]
    origin = ir_point(Point3(0.0, 0.0, 0.0), dir_name, lo1, lo2, 0.0)
    # 视图少了两个 ⇒ "哪个方向是深度"是**约定**（图面=xy 平面），
    # 两个备选列出来：同一张图转 90° 也是自洽的读法
    dir_claim = Claim(dir_name, "guess:drawing_plane_is_xy", Tier.GUESS,
                      evidence=ev, alternatives=tuple(_PLANE_AXES[dir_name]))
    outer = _outer_circle(corr, frame)
    if outer is not None:
        # 外轮廓是圆 ⇒ 基体是**回转体**（法兰/盘），不是棱柱。
        # 按包围盒做棱柱会把圆盘做成方板：面积差 1−π/4 ≈ 21%，是"数字对得上
        # 结构却错"的典型。
        c = outer.axis.origin
        f = _revolve_base(dir_name, outer.radius, depth,
                          Point3(c.x, c.y, c.z), ev, frame.view_id,
                          "projection:single_view_circle", dir_claim)
        rep.notes.append(
            f"基体（单视图）：外轮廓是圆 r{outer.radius:.2f} ⇒ 按**回转体**建"
            f"（不是包围盒棱柱），沿 {dir_name} 高 {depth:.2f} —— **厚度是猜的**"
            f"（{method}）")
        rep.questions.add(Question(
            OpenQuestion.MISSING_DIMENSION,
            f"图纸只有 {len(frames)} 个视图口径可用，{dir_name} 向尺寸图上不存在 ⇒ "
            f"圆盘厚度按「{method}」猜成 {depth:.2f}"
            f"（备选 {'/'.join(f'{a:g}' for a in alts)}）",
            view=frame.view_id, evidence=ev[:1]))
        return f
    # 轮廓环通道：视图轮廓边 → 闭合环 → (a, b) 系 Profile2。提得到就用
    # 真轮廓，提不到（环失败/断裂/纯圆/子环）才退回包围盒矩形并如实登记
    ring_prof, ring_note = _outline_ring_profile(d, frame, dir_name,
                                                 lo1, hi1, lo2, hi2)
    if ring_prof is not None:
        profile_claim = Claim(ring_prof, "projection:view_outline_ring",
                              Tier.PROJECTION, evidence=ev)
    else:
        profile_claim = Claim(box, "projection:view_bounds", Tier.PROJECTION,
                              evidence=ev)
    f = Feature(
        id=FeatureId(0),
        type=Claim(FeatureType.BASE, "projection:single_view_outline",
                   Tier.PROJECTION, evidence=ev),
        params={
            "dir": dir_claim,
            "length": Claim(depth, method, Tier.GUESS, evidence=ev,
                            alternatives=alts),
            "profile": profile_claim,
            "origin": Claim(origin, "projection:view_bounds", Tier.PROJECTION,
                            evidence=ev),
        },
        placement=Claim(origin, "projection:view_bounds", Tier.PROJECTION,
                        evidence=ev),
        source_view=frame.view_id,
        evidence=list(ev),
    )
    if ring_prof is not None:
        rep.notes.append(
            f"基体（单视图）：轮廓取**轮廓环** —— {ring_note}；视图包围盒 "
            f"{hi1 - lo1:.2f}×{hi2 - lo2:.2f}（{b1_axis},{b2_axis} 面）沿 "
            f"{dir_name} 拉伸 {depth:.2f} —— **厚度是猜的**（{method}）")
    else:
        rep.notes.append(
            f"基体（单视图）：轮廓 {hi1 - lo1:.2f}×{hi2 - lo2:.2f}"
            f"（{b1_axis},{b2_axis} 面）沿 {dir_name} 拉伸 {depth:.2f} —— "
            f"**厚度是猜的**（{method}）；按视图包围盒近似（环不可用："
            f"{ring_note}）")
    rep.questions.add(Question(
        OpenQuestion.MISSING_DIMENSION,
        f"图纸只有 {len(frames)} 个视图口径可用，{dir_name} 向尺寸图上不存在 ⇒ "
        f"厚度按「{method}」猜成 {depth:.2f}"
        f"（备选 {'/'.join(f'{a:g}' for a in alts)}）；"
        "发射前需人确认（旧管线在此处直接当已知量用）",
        view=frame.view_id, evidence=ev[:1]))
    if same_normal:
        rep.notes.append("所有视图法向一致 ⇒ 深度方向无歧义，只有长度是猜的")
    return f


def base_feature(d, corr: CorrespondenceResult, rep: RecognizeReport) -> Feature:
    """基体：正对轮廓平面的视图 → **轮廓环** → 一块拉伸体。

    轮廓优先取视图轮廓环（``views/ring`` 通道，允许圆弧段）；环不可用
    （覆盖率不足/断裂/纯圆视图）才退回视图包围盒矩形，并报一条拦路
    待确认项说明缺口。

    **选哪条轴拉伸**：取零件最小的那个正跨度 —— 板类零件的自然读法是
    "沿最薄的方向拉伸"。这条是启发式（tier=PROJECTION 而非 CONVENTION），
    且必须报出来，因为"最薄方向不是拉伸方向"的零件（如长轴套）会被读错。
    三角形剪影（``_detect_taper``）优先于它：那直接给出锥化轴与收敛方向
    （图形练习的四棱锥），此时基体带 `taper_scale` 参数、按锥化拉伸发射。

    轮廓坐标是"垂直拉伸方向的那个平面"上的 (a, b)，按
    ``library.profile_plane`` 的右手基向量落位 —— 发射器用同一张表，
    所以沿 Y 拉伸的板不会被转 90°。

    只有一个视图能定平面时走 ``_single_face_base``（那一维是猜的）。
    """
    frames = corr.frames
    ext = _extents(frames)
    if not ext:
        raise ValueError("没有任何视图给出可用跨度，无法定基体")
    if len(ext) < 3:
        return _single_face_base(d, corr, frames, rep)
    tap = _detect_taper(d, frames, ext, rep)
    if tap is not None:
        # 锥化轴优先于"最薄方向"：三角形剪影是更强的证据（它直接给出收敛
        # 方向与底/顶两端），且三向跨度并列时"最薄"本来就无从选起
        # （图形练习三向都是 60，按 min 取到的是字典序首位的 x）
        dir_name = tap.axis
    else:
        # 回转体优先于"最薄方向"：≥3 条共轴同心圆 + 轴向剖面扫出母线，
        # 是比"沿最薄向拉板"强得多的读法（PF60K 按板读体积 −63%）。
        # 检测不成立（同心圆不够/扫描失败）返回 None，原路径不受影响。
        from .revolve import detect_revolve
        rv = detect_revolve(d, corr, rep)
        if rv is not None:
            rep.revolve = rv
            return rv.base
        dir_name = min(ext, key=lambda a: ext[a])
    # 轮廓取"看不出的正是拉伸方向"的那个视图（它正对着这个平面）
    prof_view = next((f for f in frames.values() if f.p_axis == dir_name),
                     next(iter(frames.values())))
    b1_axis, b2_axis = _PLANE_AXES[dir_name]
    lo1 = min(f.model_span(b1_axis)[0] for f in frames.values()
              if f.model_span(b1_axis) is not None)
    hi1 = max(f.model_span(b1_axis)[1] for f in frames.values()
              if f.model_span(b1_axis) is not None)
    lo2 = min(f.model_span(b2_axis)[0] for f in frames.values()
              if f.model_span(b2_axis) is not None)
    hi2 = max(f.model_span(b2_axis)[1] for f in frames.values()
              if f.model_span(b2_axis) is not None)
    box = [(0.0, 0.0), (hi1 - lo1, 0.0), (hi1 - lo1, hi2 - lo2), (0.0, hi2 - lo2)]
    t_lo = min(f.model_span(dir_name)[0] for f in frames.values()
               if f.model_span(dir_name) is not None)
    length = ext[dir_name]
    ev = tuple(dict.fromkeys(e for v in d.views for e in v.evidence[:1]))
    # 轮廓外沿是个圆 ⇒ 回转体（法兰/盘），不是棱柱。实测「法兰练习」：
    # 按包围盒做 80×80 的方板 = 128,000，而金值 94,248（圆盘）—— 差 35%。
    # 锥化剪影已成立时不走这条：底面的圆外沿 + 三角形侧影是**圆锥**，按
    # 回转体建会得到平顶圆柱（形状错），而锥化拉伸正是对它的读法
    circ = None if tap is not None else _profile_circle(
        corr, dir_name, lo1, hi1, lo2, hi2)
    if circ is not None:
        c = circ.axis.origin
        prof_f = next((f for f in frames.values()
                       if f.p_axis == dir_name), prof_view)
        f = _revolve_base(dir_name, circ.radius, length,
                          Point3(c.x, c.y, c.z), ev, prof_f.view_id,
                          "projection:circle_outline")
        rep.notes.append(
            f"基体：轮廓外沿是圆 r{circ.radius:.2f} ⇒ 按**回转体**建"
            f"（不是包围盒棱柱），沿 {dir_name} 高 {length:.2f}")
        return f
    origin = ir_point(Point3(0.0, 0.0, 0.0), dir_name, lo1, lo2, t_lo)
    # 轮廓环通道（同 _single_face_base）：提得到真轮廓就用，提不到才退回
    # 包围盒矩形 + 拦路待确认（"包围盒近似"的登记在这些靶子上就此消失）
    ring_prof, ring_note = _outline_ring_profile(d, prof_view, dir_name,
                                                 lo1, hi1, lo2, hi2)
    if ring_prof is not None:
        pmethod = "projection:view_outline_ring"
        profile_claim = Claim(ring_prof, pmethod, Tier.PROJECTION, evidence=ev)
    else:
        pmethod = "projection:view_bounds"
        profile_claim = Claim(box, pmethod, Tier.PROJECTION, evidence=ev)
    params: dict[str, Claim] = {
        "dir": Claim(dir_name,
                     "projection:taper_axis" if tap is not None
                     else "projection:thinnest_extent",
                     Tier.PROJECTION, evidence=ev),
        "length": Claim(length, "projection:view_bounds", Tier.PROJECTION,
                        evidence=ev),
        # 轮廓**相对 origin**（发射器按 ir_point(origin, dir, a, b, t) 落位）；
        # 写成绝对坐标会与 origin 叠加一次，造出双倍偏移的零件
        "profile": profile_claim,
        "origin": Claim(origin, "projection:view_bounds", Tier.PROJECTION,
                        evidence=ev),
    }
    taper_on = tap is not None and ring_prof is not None
    if taper_on:
        # 锥化拉伸契约（见 library.OPTIONAL_PARAMS）：顶部截面 = 底面轮廓
        # 相对 bbox 中心按 (sa, sb) 缩放；(0, 0) = 收敛到一点（棱锥）。
        # 只在底面环可用时给 —— 拿包围盒矩形当底面再收锥是另一种错形状
        params["taper_scale"] = Claim((0.0, 0.0), "projection:taper_silhouette",
                                      Tier.PROJECTION, evidence=ev)
    f = Feature(
        id=FeatureId(0),
        type=Claim(FeatureType.BASE, pmethod, Tier.PROJECTION, evidence=ev),
        params=params,
        placement=Claim(origin, "projection:view_bounds", Tier.PROJECTION,
                        evidence=ev),
        source_view=prof_view.view_id,
        evidence=list(ev),
    )
    if taper_on:
        rep.notes.append(
            f"基体：底面轮廓取**轮廓环**（{prof_view.view_id}）—— {ring_note}；"
            f"沿 {dir_name} 自低端**锥化拉伸**收敛到一点"
            f"（依据 {'、'.join(tap.views)} 的三角形剪影），角点在 "
            f"({origin.x:.2f},{origin.y:.2f},{origin.z:.2f})")
    elif ring_prof is not None:
        extra = ""
        if tap is not None:
            extra = (f"；**检出锥化剪影（{'、'.join(tap.views)}）但底面视图的"
                     "轮廓环不可用 ⇒ 未按锥化建**，形状存疑")
        rep.notes.append(
            f"基体：轮廓取**轮廓环**（{prof_view.view_id}）—— {ring_note}；"
            f"沿 {dir_name} 拉伸 {length:.2f}，角点在 "
            f"({origin.x:.2f},{origin.y:.2f},{origin.z:.2f}){extra}")
    else:
        rep.notes.append(
            f"基体：轮廓 {hi1 - lo1:.2f}×{hi2 - lo2:.2f}（{b1_axis},{b2_axis} 面）"
            f"沿 {dir_name} 拉伸 {length:.2f}，角点在 "
            f"({origin.x:.2f},{origin.y:.2f},{origin.z:.2f})；"
            f"按视图包围盒近似（环不可用：{ring_note}）")
        rep.questions.add(Question(
            OpenQuestion.AMBIGUOUS_FEATURE,
            f"基体只按视图包围盒近似（{b1_axis},{b2_axis} 面上的矩形 "
            f"{hi1 - lo1:.2f}×{hi2 - lo2:.2f} 沿 {dir_name} 拉伸 {length:.2f}）—— "
            f"轮廓内的台阶/缺口**没有**被解释；轮廓环通道不可用（{ring_note}）",
            view=prof_view.view_id, evidence=ev[:1],
        ))
    return f


# ---- 2) 圆柱（跨视图对应） ----

def _cyl_claim(hint: CylinderHint) -> Claim[FeatureType]:
    """孔还是凸台 —— **没定就不许定**（§3 原则二）。

    ``CylinderHint.solid`` 由正交视图里那两条轮廓线是实线还是虚线给出，
    这是二者唯一的消解依据。它没算出来（None）时只能给 GUESS + 备选。
    """
    ev = hint.axis.radius.evidence if hint.axis.radius else ()
    if hint.solid is True:
        return Claim(FeatureType.BOSS, "projection:outline_visible",
                     Tier.PROJECTION, evidence=ev)
    if hint.solid is False:
        return Claim(FeatureType.HOLE, "projection:outline_hidden",
                     Tier.PROJECTION, evidence=ev)
    return Claim(FeatureType.HOLE, "unresolved:outline", Tier.GUESS,
                 alternatives=(FeatureType.BOSS,))


def _base_outline(base: Feature):
    """基体自身的外轮廓圆 → 它**不是**特征，是基体本身。

    单视图圆盘里最大的那个圆会被跨视图对应读成"沿轴的一个圆柱"；而
    沿基体自己的轴、半径又等于基体半径的圆柱只可能是基体的轮廓线
    （实测 flange_d80：Ø80 外圆被读成一个 r40 的孔、法兰练习里被读成
    一个 r40 的凸台 —— 两者都是把零件本身又加/减了一遍）。
    """
    prof = base.params.get("radius_profile")
    if prof is None or not isinstance(prof.value, (list, tuple)) or not prof.value:
        return None
    r_max = max(float(r) for _, r in prof.value)
    ax = base.axis.value if base.axis is not None else None
    if ax is None:
        return None

    def skip(hint: CylinderHint) -> bool:
        if abs(hint.radius - r_max) > 0.05:
            return False
        if not _dirs_parallel_either_way(hint.axis.direction, ax.direction):
            return False
        d = axis_distance(hint.axis, ax)
        return d is not None and d <= AXIS_POS_TOL

    return skip


def cylinder_features(corr: CorrespondenceResult, rep: RecognizeReport,
                      next_id: int, skip=None,
                      no_feature: list[CylinderHint] | None = None,
                      draws_hidden: bool = False) -> list[Feature]:
    """一个 ``CylinderHint`` 一条特征。``skip`` 是基体外轮廓的判据（见上）。

    ``no_feature`` 收下"**没有建成特征**的圆"（供 ``_resolve_questions``
    把它们的 corr 层疑问裁决成"非圆柱"）—— 与 ``skip`` 不是一回事：
    skip 是"这圆是基体自己/已被分区表达"，这里收的是"连轮廓线都没有、
    判不出是什么"。

    ``draws_hidden``：这张图纸**整体上画不画隐藏线**。它决定"找不到轮廓对"
    是强负证据还是空证据 —— 画了隐藏线的图纸（HLR 出图）里，真圆柱被遮挡的
    轮廓线**本该出现**；不画隐藏线的简图上什么都不出现（实测 block_3view：
    4 个 Ø10 孔的轮廓线全图都没有，但孔是真的 —— 那种情况照旧走 GUESS）。
    """
    out: list[Feature] = []
    for c in corr.cylinders():
        hint = c.mapping.value
        assert isinstance(hint, CylinderHint)
        if skip is not None and skip(hint):
            continue
        if hint.length is None and hint.solid is None and draws_hidden:
            # 图纸画了隐藏线，而正交视图里**一条**间距 2r 的轮廓线都没有
            # ⇒ 没有可量取的轴向长度，也没有实/虚判据。这种圆边不许当独立
            # 圆柱特征（§3 原则二"没定就不许定"）—— 建孔建凸台都是替用户
            # 拍板。实测 bracket r9：那是两处 R3 铸造圆角环面与外圆柱的相切
            # 圆（金值里根本没有 r9 柱面），按 GUESS 孔发射会凭空切掉 14.4mm³。
            # 疑问在 corr 层已报（"找不到间距 2r 的轮廓对"）；这里只记账，
            # 消解在 recognize() 收尾（依据 = 这条强负证据本身）。
            if no_feature is not None:
                no_feature.append(hint)
            rep.notes.append(
                f"圆 r{hint.radius:g}：图纸画了隐藏线，而正交视图里没有任何"
                "间距 2r 的轮廓对 ⇒ 孔/凸台与轴向长度都判不出，**不建特征**"
                "（记缺口，待确认项交 _resolve_questions 裁决）")
            continue
        ev = tuple(hint.axis.radius.evidence) if hint.axis.radius else ()
        t = _cyl_claim(hint)
        params: dict[str, Claim] = {}
        if hint.axis.radius is not None:
            params["radius"] = hint.axis.radius
        if hint.length is not None:
            params["height" if t.value == FeatureType.BOSS else "depth"] = mk_claim(
                hint.length, "projection:outline_pair", Tier.PROJECTION, ev)
        f = Feature(
            id=FeatureId(next_id), type=t, params=params,
            axis=Claim(hint.axis, "projection:circle_plus_outline",
                       Tier.PROJECTION, ev),
            placement=Claim(hint.axis.origin, "projection:cylinder", Tier.PROJECTION,
                            ev),
            source_view=c.views[0] if c.views else "",
            evidence=list(ev),
        )
        out.append(f)
        if t.value == FeatureType.HOLE and "depth" not in params:
            # 文本里点出 `#id.depth` 与 `#id.through`：这两个字段是同一桩
            # 未定事（深度不知道 ⇒ 通孔/盲孔也不知道），求解层的"欠定"兜底
            # 靠这两个记号去重，别只点一个
            rep.questions.add(Question(
                OpenQuestion.MISSING_DIMENSION,
                f"#{f.id}.depth / #{f.id}.through：r{hint.radius:g} 在正交视图里"
                "找不到配对的轮廓 ⇒ 深度未知，通孔/盲孔也未定",
                view=f.source_view, evidence=ev))
        next_id += 1
    return out


def _resolve_questions(rep: RecognizeReport, plan,
                       no_feature: list[CylinderHint]) -> int:
    """分区/轮廓证据已把圆的角色定死 ⇒ **裁决** corr 层留下的歧义疑问。

    ``QuestionList.resolve`` 不删条目：把它移进已裁决区并记下答案与裁决者
    （见 ``model/questions.py``）。只裁决**图元全部有结论**的疑问 —— 一条
    圆边还没定，疑问就原样保留（宁可多问，§3 原则二）。

    三类消解（依据都来自识别期新证据，不是放宽门槛）：
      * 「同一圆心上有 N 条同心圆边」→ ``independent``：每个圆各由分区/
        特征层独立解释（材料分区、切除分区、凸台、或非特征切边）——
        "沉孔/台阶"那个假设需要两个圆**成对**解释同一段轴向，分区读数
        不支持它；
      * 「既有实线对又有虚线对」→ ``boss``/``hole``：分区剪影把该圆
        所在的区域读成了材料/切除（实测 bracket r25.5 材料、r15.7 切除），
        比"实线对长度 vs 虚线对长度"这一路更强；
      * 「找不到间距 2r 的轮廓对」→ ``neither``：图纸画了隐藏线仍然全无
        轮廓 ⇒ 非圆柱特征（曲面切边/圆角足迹，实测 r9 = R3 环面相切圆）。
    """
    qs = rep.questions
    roles: dict[str, tuple[str, str]] = {}      # 圆边 handle → (种类, 人话)

    def put(hint: CylinderHint, kind: str, text: str) -> None:
        ev = hint.axis.radius.evidence if hint.axis.radius else ()
        for h in ev:
            roles[h] = (kind, text)

    if plan is not None:
        for z in plan.zones:
            what = "材料分区" if z.role == "material" else "切除分区"
            for h in z.hints:
                r = h.axis.radius.value if h.axis.radius else 0.0
                put(h, "material" if z.role == "material" else "cut",
                    f"r{r:g} → {what} z[{z.t_lo:.2f},{z.t_hi:.2f}]")
    for f in rep.part.features:
        if f.type.value not in (FeatureType.HOLE.value, FeatureType.BOSS.value):
            continue
        rad = f.params.get("radius")
        if rad is None or not isinstance(rad.value, (int, float)):
            continue
        kind = "material" if f.type.value == FeatureType.BOSS.value else "cut"
        for h in f.evidence:
            roles.setdefault(h, (
                kind, f"r{float(rad.value):g} → 特征 #{f.id}"
                      f"（{'凸台' if kind == 'material' else '孔'}）"))
    for h in no_feature:
        put(h, "none", f"r{h.radius:g} → 非特征（图上全无间距 2r 的轮廓对）")

    n = 0
    for q in list(qs.find(OpenQuestion.AMBIGUOUS_FEATURE)):
        ev = tuple(q.evidence)
        if not ev:
            continue
        # 三类的 evidence 结构不同，**各自的"图元全部有结论"判据也不同**：
        #   · 同心圆：ev = 全部圆边 handle ⇒ 逐条都要在 roles 里；
        #   · 实/虚冲突：ev = (圆边, 实线对 h1/h2, 虚线对 h1/h2) —— **只有
        #     ev[0] 是圆边**，线对 handle 设计上就不进 roles（角色表管的是
        #     圆）⇒ 只看 ev[0]；
        #   · 无轮廓对：ev = (圆边,) ⇒ 必须在 roles 且角色为 none。
        if "同一圆心上有" in q.detail:
            if not all(h in roles for h in ev):
                continue                  # 还有圆边没结论：保留疑问
            ans = ("independent（同一圆心各自成立："
                   + "；".join(roles[h][1] for h in dict.fromkeys(ev)) + "）")
            by = "height:zone" if plan is not None else "recognize:circle_roles"
            if qs.resolve(q, ans, by):
                n += 1
        elif "既有实线轮廓对" in q.detail:
            if ev[0] not in roles:
                continue                  # 圆边还没结论：保留疑问
            kind, text = roles[ev[0]]
            if kind not in ("material", "cut"):
                continue
            ans = (("boss（" if kind == "material" else "hole（") + text
                   + "——实/虚线之争由分区剪影裁决）")
            if qs.resolve(q, ans, "height:zone"):
                n += 1
        elif "找不到间距 2r 的轮廓对" in q.detail:
            if all(h in roles and roles[h][0] == "none" for h in ev):
                ans = ("neither（图纸画了隐藏线却没有任何间距 2r 的轮廓 ⇒ "
                       "不是孔也不是凸台，是曲面切边/圆角足迹）")
                if qs.resolve(q, ans, "recognize:no_outline_pair"):
                    n += 1
    return n


# ---- 3) 剖面标题给的轴线 ----

def _cylinder_owner(corr: CorrespondenceResult, part: Part,
                    axis: Axis3) -> Feature | None:
    """圆通道里已读出的圆柱 = 标题声明的这条吗？是 ⇒ 返回树里持有它图元的特征。

    判据：半径相容（``MATCH_TOL``）＋轴平行＋轴位一致（``AXIS_POS_TOL``）。
    "持有"按图元 handle 交集找 —— 高度分区的抬升/切除、凸台、孔都是拿圆
    图元建的，handle 就在 ``evidence`` 里。
    """
    assert axis.radius is not None
    best: tuple[float, Feature | None] | None = None
    for c in corr.cylinders():
        hint = c.mapping.value
        if abs(hint.radius - axis.radius.value) > MATCH_TOL:
            continue
        d = axis_distance(hint.axis, axis)
        if d is None or d > AXIS_POS_TOL:
            continue
        hs = set(hint.evidence)
        owner = next((f for f in part.features if hs & set(f.evidence)), None)
        if best is None or d < best[0]:
            best = (d, owner)
        if d == 0.0:
            break
    return best[1] if best is not None else None


def merge_section_axes(corr: CorrespondenceResult, rep: RecognizeReport,
                       part: Part) -> None:
    """把剖面标题/中心线给出的 3D 轴并进特征树。

    三种归宿，按"该轴/该半径是否已被别处表达"排（顺序不能换）：

    1. 已有特征与它**同轴且半径相容**（|Δr| ≤ ``MATCH_TOL``）⇒ 合并
       （标注压投影，证据并起来）。同轴**异径**的特征不是它的宿主 ——
       bracket 塔柱上标题 r25.5（外圆）与树里 #3 r15.7（内孔）同轴，
       只按轴距匹配会把 #3 的半径篡改成 r25.5（v0.6.21 剖面图实测病）。
    2. 圆通道已读出这条圆柱（半径相容＋轴位一致）⇒ 事实已在树里
       （高度分区/凸台/孔），**不新建孤儿特征**，标题证据并给持有该
       圆图元的特征，只记账。
    3. 都没有且**带半径** ⇒ 图纸明写的一处孔/凸台，建成新特征；
       不带半径的中心线（``radius is None``）⇒ 别硬造特征，只记待确认。
    """
    for c in corr.axes():
        axis = c.mapping.value
        assert isinstance(axis, Axis3)
        r_new = axis.radius
        same: list[tuple[float, Feature]] = []
        for f in part.features:
            if f.axis is None or f.axis.value is None:
                continue
            d = axis_distance(f.axis.value, axis)
            if d is None or d > AXIS_POS_TOL:
                continue
            old = f.params.get("radius")
            if (r_new is not None and old is not None and old.value is not None
                    and abs(old.value - r_new.value) <= MATCH_TOL):
                same.append((abs(old.value - r_new.value), f))
        if same:
            same.sort(key=lambda t: t[0])
            _absorb(same[0][1], axis, c, rep)
            continue
        if r_new is None:
            rep.questions.add(Question(
                OpenQuestion.MISSING_DIMENSION,
                f"{'×'.join(c.views)} 的中心线定出一条 3D 轴"
                f"（过 {'(' + ', '.join(f'{q:.2f}' for q in (axis.origin.x, axis.origin.y, axis.origin.z)) + ')'}），"
                "但图纸没给它的半径 ⇒ 是参考轴还是某个特征的轴未定",
                evidence=tuple(e for _, e in c.refs)))
            continue
        owner = _cylinder_owner(corr, part, axis)
        if owner is not None:
            for e in (h for _, h in c.refs):
                if e not in owner.evidence:
                    owner.evidence.append(e)
            rep.notes.append(
                f"剖面标题 r{r_new.value:g} 轴与已读圆柱重合（宿主 #{owner.id}）"
                f"⇒ 只并证据，不另建特征")
            continue
        f = Feature(
            id=part.next_id(),
            type=Claim(FeatureType.HOLE, "note:section_title", Tier.ANNOTATED,
                       evidence=axis.radius.evidence),
            params={"radius": axis.radius,
                    "through": mk_claim(True, "note:section_title", Tier.ANNOTATED,
                                        axis.radius.evidence)},
            axis=Claim(axis, "note:section_title", Tier.ANNOTATED,
                       axis.radius.evidence),
            placement=Claim(axis.origin, "note:section_title", Tier.ANNOTATED,
                            axis.radius.evidence),
            source_view=c.views[0] if c.views else "",
            evidence=list(axis.radius.evidence),
        )
        part.add(f)
        rep.notes.append(
            f"#{f.id} 由剖面标题建成：r{axis.radius.value:g} 轴沿 "
            f"{_axis_name(axis.direction)}")


def _absorb(f: Feature, axis: Axis3, c, rep: RecognizeReport) -> None:
    """同一根轴的二次声明并进已有特征：值取高 tier，证据合起来。"""
    old = f.params.get("radius")
    new = axis.radius
    if new is not None and old is not None:
        merged, conflict = merge_with_conflict(
            old, new, label=f"#{f.id} 半径的两路声明")
        f.params["radius"] = merged
        if conflict is not None:
            rep.conflicts.append(conflict)
        if new.tier > old.tier:
            rep.notes.append(
                f"#{f.id} 半径被剖面标题精化：{old.value:g} → {new.value:g}"
                f"（{old.tier.name} → {new.tier.name}）")
    ev = new.evidence if new is not None else ()
    for h in ev:
        if h not in f.evidence:
            f.evidence.append(h)
    rep.notes.append(f"#{f.id} 与 {'×'.join(c.views)} 的轴线并为一处"
                     f"（共 {len(f.evidence)} 项依据）")


def _material_extent(base: Feature, rep: "RecognizeReport | None" = None
                     ) -> dict[str, float]:
    """基体在三个模型轴上的"材料厚度"（轮廓环/包围盒同一口径：轮廓跨度）。

    拉伸方向上是 ``length``；轮廓平面内的两轴上是轮廓的宽/高
    （``profile_span`` —— 点列取 max、Profile2 取 bbox，见 geom2d）。
    写成一张表而不是"孔轴必须与拉伸方向同向才判"—— PF60K 的孔沿 z、
    基体沿 y 拉伸，孔轴与拉伸方向不同，但 z 向的材料厚度就是轮廓的
    z 跨度，照样能判。

    回转体（法兰/盘）走另一支：轴向厚度 = 母线沿轴的最大坐标，两个径向
    尺寸 = 2×最大半径。**基体可能是 REVOLVE 而不是 BASE**（圆轮廓走
    `_revolve_base`），只认 "base" 会让整张表取不出来 —— 实测 flange_d80 /
    法兰练习 四个 Ø8 孔因此一个 `through` 都没挂上，发射器直接以缺参数拒绝。
    """
    dir_name = base.params["dir"].value
    b1, b2 = _PLANE_AXES[dir_name]
    if base.type.value == FeatureType.REVOLVE.value:
        prof = base.params["radius_profile"].value
        r = max(float(rr) for _, rr in prof)
        return {dir_name: max(float(t) for t, _ in prof), b1: 2.0 * r, b2: 2.0 * r}
    w1, w2 = profile_span(base.params["profile"].value)
    # 高度分解成立时 ``length`` **不再是材料厚度**（基体已降到最低公共顶面，
    # 抬升区把材料补回去）—— 沿拉伸方向的厚度改取图纸读出的材料总跨度。
    # 不这么换，bracket 的 r15.7 环孔（深 44 vs 分解后基体 22）会被判成通孔
    # 之外的东西…… 更糟的是 r6 槽（深 28）也会被判通孔
    zones = getattr(rep, "zones", None)
    t = float(base.params["length"].value)
    if zones is not None:
        t = zones.span()[1] - zones.span()[0]
    return {dir_name: t, b1: w1, b2: w2}


def derive_through(part: Part, rep: RecognizeReport) -> None:
    """通孔还是盲孔 —— 由「孔深 vs 该轴上的材料厚度」推（旧管线全靠猜）。

    材料厚度取基体在该轴上的跨度。基体目前只有包围盒级精度，故
    tier=DERIVED 而不是 ANNOTATED —— 但它至少是**推出来的**，
    依据（深度/厚度两个数）写进报告，而不是一个静默的 False。

    每一处孔都必须有 ``through``：发射器不知道"通孔"该不该默认，
    缺参数就抛异常。所以定不下来的地方给 GUESS 值 + 备选 + 缺口计数，
    而不是让字段缺席。
    """
    base = next((f for f in part.features
                 if f.type.value in ("base", "revolve")), None)
    if base is None:
        return
    thick = _material_extent(base, rep)
    unknown = 0
    for f in part.features:
        if f.type.value != "hole":
            continue
        cur = f.params.get("through")
        if cur is not None and cur.tier > Tier.DERIVED:
            continue                    # 图纸明写的（剖面标题「穿…孔轴」）不降级
        depth = f.params.get("depth")
        ax = f.axis.value if f.axis is not None else None
        name = _axis_name(ax.direction) if ax is not None else ""
        mat = next((v for k, v in thick.items()
                    if name in (f"+{k.upper()}", f"−{k.upper()}")), None)
        ev = tuple(f.evidence[:1])
        if depth is not None and mat is not None:
            through = depth.value >= mat - AXIS_POS_TOL
            f.params["through"] = Claim(through, "derived:depth_vs_material",
                                        Tier.DERIVED, ev)
            rep.notes.append(
                f"#{f.id} 深 {depth.value:.2f} vs 该轴材料厚 {mat:.2f} ⇒ "
                f"{'通孔' if through else '盲孔'}")
            continue
        # 深度不知道（没配到轮廓对），或孔轴不是主轴（材料厚度算不出来）
        # ⇒ 按制图惯例"没画底轮廓即通孔"取 True，但配对失败也有同样表现：
        # 只给 GUESS 并保留 False 作备选（歧义不消解）
        f.params["through"] = Claim(True, "unresolved:no_bottom_contour",
                                    Tier.GUESS, ev, alternatives=(False,))
        unknown += 1
    if unknown:
        rep.notes.append(
            f"{unknown} 处孔的通孔/盲孔未定（深度或该轴材料厚度缺失）⇒ "
            "暂按通孔、备选盲孔")


def _axis_name(d: Vector3) -> str:
    for name, v in (("+X", (1, 0, 0)), ("−X", (-1, 0, 0)), ("+Y", (0, 1, 0)),
                    ("−Y", (0, -1, 0)), ("+Z", (0, 0, 1)), ("−Z", (0, 0, -1))):
        if max(abs(d.x - v[0]), abs(d.y - v[1]), abs(d.z - v[2])) < 1e-6:
            return name
    return f"({d.x:.2f},{d.y:.2f},{d.z:.2f})"


# ---- 4) 约定：阵列 / 螺纹 / 对称 ----

def pattern_features(conv, corr: CorrespondenceResult, rep: RecognizeReport,
                     part: Part) -> list[Feature]:
    """均布孔阵列 ⇒ PATTERN 特征（child 指向被阵列的那个孔）。

    ``Pattern`` 是**图纸系**表达（与 ``Symmetry`` 同理），必须经视图坐标系
    翻到模型系才能与孔轴比位置 —— 直接拿图纸坐标比模型坐标是"看着像对上了"
    的经典错法。
    """
    from ..conventions import ConvKind
    out: list[Feature] = []
    if conv is None:
        return out
    for c in conv.of_kind(ConvKind.PATTERN):
        p = c.value
        frame = corr.frames.get(p.view)
        if frame is None:
            rep.questions.add(Question(
                OpenQuestion.AMBIGUOUS_VIEW,
                f"{p.view} 认出 {p.n}×φ{2 * p.hole_radius:g} 的均布阵列"
                f"（分布圆 R{p.radius:g}），但该视图没有坐标系 ⇒ "
                "阵列中心在模型系里的位置未定",
                view=p.view, evidence=c.evidence))
            continue
        center3 = frame.to_model(p.center.x, p.center.y)
        # 被阵列的孔**不在分布圆心上**，而在分布圆上：判据是"孔轴到阵列中心的
        # **面内**距离 ≈ 分布圆半径"且"半径 ≈ 阵列孔半径"。早期版本比的是
        # 轴心到圆心的距离 ≤ 容差（= 在圆心处找孔），PF60K 上必然找不到 child
        child = None
        on_circle = 0
        for f in part.features:
            if f.type.value == "pattern" or f.axis is None or f.axis.value is None:
                continue
            r = f.params.get("radius")
            if r is None or abs(r.value - p.hole_radius) > 0.05:
                continue
            o = f.axis.value.origin
            cm = {"x": o.x, "y": o.y, "z": o.z}
            cn = {"x": center3.x, "y": center3.y, "z": center3.z}
            d = ((cm[frame.u_axis] - cn[frame.u_axis]) ** 2
                 + (cm[frame.v_axis] - cn[frame.v_axis]) ** 2) ** 0.5
            if abs(d - p.radius) <= AXIS_POS_TOL:
                if child is None:
                    child = f
                on_circle += 1
        params = {
            "kind": mk_claim("circular", "convention:pattern", Tier.CONVENTION,
                             c.evidence),
            "count": mk_claim(p.n, "convention:pattern", Tier.CONVENTION,
                              c.evidence),
            "bc_radius": mk_claim(p.radius, "convention:pattern", Tier.CONVENTION,
                                  c.evidence),
            "start_deg": mk_claim(p.angles[0] if p.angles else 0.0,
                                  "convention:pattern", Tier.CONVENTION,
                                  c.evidence),
        }
        f = Feature(
            id=part.next_id(),
            type=Claim(FeatureType.PATTERN, "convention:pattern",
                       Tier.CONVENTION, c.evidence),
            params=params,
            placement=Claim(center3, "convention:pattern",
                            Tier.CONVENTION, c.evidence),
            source_view=p.view, evidence=list(c.evidence),
        )
        if child is not None:
            f.depends_on.append(child.id)
            f.params["child"] = mk_claim(child.id, "convention:pattern",
                                         Tier.CONVENTION, c.evidence)
            if on_circle >= p.n:
                # 图上 n 个圆**全部逐个画出**且各有独立特征 ⇒「均布阵列」与
                # 「n 个独立孔位」两种读法的位置逐个相同，阵列只是给分布加注
                # （发射器的覆盖去重保证不重复建）—— 这正是"图上没写「均布」
                # 字样"那条疑问的消解依据：不靠默认值，靠两读等效。
                for q in rep.questions.find(OpenQuestion.AMBIGUOUS_FEATURE,
                                            view=p.view,
                                            detail_contains="等距落在"):
                    rep.questions.resolve(
                        q, "均布阵列（n 个圆全部有独立特征，与逐孔读法位置一致）",
                        "convention:pattern_read_all")
        else:
            rep.questions.add(Question(
                OpenQuestion.AMBIGUOUS_FEATURE,
                f"认出 {p.n}×φ{2 * p.hole_radius:g} 的均布阵列（分布圆 R{p.radius:g}），"
                "但没找到被阵列的那个孔 ⇒ 阵列挂在哪个特征上未定",
                view=p.view, evidence=c.evidence))
        out.append(f)
    return out


def thread_links(conv, rep: RecognizeReport, part: Part) -> int:
    """螺纹标注挂到对应的孔上（挂不上就报出来，不静默丢）。"""
    from ..conventions import ConvKind
    n = 0
    if conv is None:
        return 0
    for c in conv.of_kind(ConvKind.THREAD):
        spec = c.value
        for f in part.features:
            if f.axis is None or f.axis.value is None:
                continue
            if spec.hole_ref is None or spec.hole_ref not in f.evidence:
                continue
            f.params["thread"] = mk_claim(spec.code, "convention:thread_code",
                                          Tier.CONVENTION, (spec.text_ref,))
            n += 1
            break
    return n


def symmetries(conv, corr: CorrespondenceResult, part: Part,
               rep: RecognizeReport) -> None:
    """对称面 —— 约定层给的是**图纸系**，这里翻成模型系。

    翻译需要视图坐标系（``ViewFrame``）：图纸里的"竖中心线"在模型系是
    垂直于该视图 u 轴的那个面。这一步是 views 层的存在价值之一 ——
    约定层只说"这张图上 u 向对称"，不抢答模型轴。
    """
    from ..conventions import ConvKind
    if conv is None:
        return
    for c in conv.of_kind(ConvKind.SYMMETRY):
        s = c.value
        frame = corr.frames.get(s.view)
        if frame is None:
            rep.questions.add(Question(
                OpenQuestion.AMBIGUOUS_VIEW,
                f"{s.view} 判出{'左右' if s.which == 'u' else '上下'}对称，"
                "但该视图没有坐标系 ⇒ 对称面在模型系里的位置未定",
                view=s.view, evidence=c.evidence))
            continue
        if s.which == "u":
            at = frame.u_to_model(s.at)
            normal = _axis_vector(frame.u_axis)
        else:
            at = frame.v_to_model(s.at)
            normal = _axis_vector(frame.v_axis)
        point = {'x': Point3(at, 0.0, 0.0), 'y': Point3(0.0, at, 0.0),
                 'z': Point3(0.0, 0.0, at)}[frame.u_axis if s.which == "u"
                                            else frame.v_axis]
        part.symmetry.append(Claim(SymmetryOp(normal.normalized(), point),
                                   f"convention:symmetry:{s.view}",
                                   Tier.CONVENTION, c.evidence))
        rep.notes.append(
            f"对称面：法向 {_axis_name(normal)} 过 {frame.u_axis if s.which == 'u' else frame.v_axis}"
            f"={at:.2f}（支撑率 {s.support:.0%}）")


def _axis_vector(name: str) -> Vector3:
    return {"x": Vector3(1.0, 0.0, 0.0), "y": Vector3(0.0, 1.0, 0.0),
            "z": Vector3(0.0, 0.0, 1.0)}[name]


# ---- 主入口 ----

def recognize(d, corr: CorrespondenceResult, conv=None,
              qs: QuestionList | None = None) -> RecognizeReport:
    """图纸 → 特征树（含待确认项）。

    ``d`` 是已过 ``detect_views``/``type_views`` 的 ``Drawing``。
    """
    questions = qs if qs is not None else QuestionList()
    rep = RecognizeReport(part=Part(questions=questions), questions=questions)
    if not corr.frames:
        rep.questions.add(Question(
            OpenQuestion.UNKNOWN_VIEW, "没有可用的视图坐标系，无法识别特征"))
        return rep

    part = rep.part
    if conv is not None:                    # 约定先行：对称/阵列要挂到特征上
        symmetries(conv, corr, part, rep)

    base = base_feature(d, corr, rep)
    part.add(base)
    rv = rep.revolve
    next_id = 1
    skip = _base_outline(base)
    if rv is not None:
        # 回转体的附属体（方料块 × N、键槽）紧随基体进树 —— 它们都是
        # **材料/切除**，顺序只对发射器的布尔序列有意义（材料先、切除后，
        # 圆柱特征在更后面，天然满足）
        solids = list(rv.solids) + ([rv.pocket] if rv.pocket is not None else [])
        for f in solids:
            f.id = FeatureId(next_id)
            part.add(f)
            next_id += 1
        skip = rv.skip_outline          # 跳过**全部** Rset 同心圆（不只最外）
        rep.notes.append(
            f"附着：方料 {len(rv.solids)} 块、键槽 {'有' if rv.pocket else '无'}"
            f"，特征自 #{next_id} 号续编")
    else:
        # 高度分解（阶段 7）：基体目前是"俯视轮廓 × 全高"，而真实零件在
        # 轮廓内**分区不同高**（臂薄、腹板中、环台高）—— 侧视图剪影给出
        # 每块的顶/底，轮廓里的圆给出分区边界。成立时基体就地降高、
        # 抬升区与切除区作为 BASE/HOLE/POCKET 紧随基体进树；不成立只记账。
        from .height_zones import decompose, side_axis_spans
        plan = decompose(d, corr, base, rep)
        rep.zones = plan
        if plan is not None:
            first = next_id
            for f in plan.features():
                f.id = FeatureId(next_id)
                part.add(f)
                next_id += 1
            done = {id(h) for h in plan.consumed()}
            prev = skip

            def skip(hint: CylinderHint) -> bool:
                return ((prev is not None and prev(hint)) or id(hint) in done)
            rep.notes.append(
                f"高度分解：{len(plan.raises)} 块抬升区、{len(plan.cuts)} 块"
                f"切除区自 #{first} 号续编（这些圆已由分区表达，不再重复建圆柱）")
    # 圆角（阶段 7 第四笔）：基体顶边的凸 R 与抬升区根部的凹 R —— 依据分别是
    # 「z = 顶−R」与「z = 顶+R」两条切线层线。分解不做时 base_top = 全高，
    # 半径门（TOP_R/ROOT_R 范围）自然把不成立的层线挡掉。
    from .roundovers import raise_root_fillets, top_roundovers
    for f in (top_roundovers(d, corr, base, rep.zones, rep)
              + raise_root_fillets(d, corr, base, rep.zones, rep)):
        f.id = FeatureId(next_id)
        part.add(f)
        next_id += 1
    # 图纸整体画不画隐藏线 —— 决定"找不到轮廓对"是强负证据（HLR 出图，本该
    # 有）还是空证据（简图，本来就没有）。见 cylinder_features 的 docstring。
    # ⚠️ `Evidence.role` 是 **Claim[Role]**（角色可被推翻，见 evidence/model.py），
    # 直接 `e.role == Role.HIDDEN` 恒为假（Claim 与 Role 不同型）—— 取 `.value`。
    draws_hidden = any(e.role.value == Role.HIDDEN for e in d.evidence)
    no_feature: list[CylinderHint] = []
    for f in cylinder_features(corr, rep, next_id=next_id, skip=skip,
                               no_feature=no_feature,
                               draws_hidden=draws_hidden):
        part.add(f)
    if rep.zones is not None:
        n = side_axis_spans(d, corr, part, rep.zones.dir_name, rep)
        if n:
            rep.notes.append(f"侧轴凸台：{n} 个的轴向区间已读出并改写 height/axial_at")
        # 侧通道（阶段 7 续）：挂耳身上的月牙缺口 / 张缝 / 销孔 —— 依据全是
        # 轴平行线段对，与 cylinder_features（读圆）两条腿走路。月牙缺口要
        # 插在凸台**之前**（先切假料、凸台再补圆柱），故由该模块自己定位插入点。
        from .side_channels import side_channels
        m = side_channels(d, corr, part, rep)
        if m:
            rep.notes.append(f"侧轴凸台：月牙缺口/张缝/销孔共 {m} 个特征进树")
    merge_section_axes(corr, rep, part)
    if rep.zones is not None or no_feature:
        # 分区/轮廓证据把圆的角色定死之后，把 corr 层的歧义疑问**裁决**掉
        # （移进 resolved 并记答案+裁决者）—— 不删条目，报告里仍可追"当时
        # 怎么想的"。只在图元全部有结论时裁决，缺一条就保留疑问。
        n = _resolve_questions(rep, rep.zones, no_feature)
        if n:
            rep.notes.append(
                f"疑问消解：{n} 条圆歧义由分区角色/负轮廓证据裁决（见 resolved）")
    for f in pattern_features(conv, corr, rep, part):
        part.add(f)
    if thread_links(conv, rep, part):
        rep.notes.append("螺纹标注已挂到对应孔上")
    # 通孔/盲孔必须等剖面标题那一路也进树之后才能判（标题可能已明写「穿…」）
    derive_through(part, rep)
    # 求解**在层内收尾**：先验/关系/欠定兜底共用同一个待确认清单，
    # 否则调用方忘了传 qs 就会重复报（求解层去重正是靠这份清单）
    rep.solved = solve(part, qs=questions)
    if rv is not None:
        # 消解**必须在 solve 之后**：solve 才把"type 未定/标准值偏离"的
        # 疑问挂进清单，消解端（角孔定型/螺纹底孔先验）才有对象可裁
        from .revolve import attach_revolve
        attach_revolve(d, corr, rv, part, rep)
    rep.conflicts.extend(rep.solved.conflicts)
    return rep


__all__ = [
    "RecognizeReport", "axis_distance", "base_feature", "cylinder_features",
    "derive_through", "merge_section_axes", "pattern_features", "recognize",
    "symmetries", "thread_links",
]
