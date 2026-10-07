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

from ..model.claim import Claim, Tier
from ..model.feature_tree import Feature, FeatureType, Part, SymmetryOp
from ..model.geom import Axis3, Point3, Vector3
from ..model.geom2d import Point2, Profile2, ProfileSeg2, profile_span
from ..model.ids import FeatureId
from ..model.questions import OpenQuestion, Question, QuestionList
from ..views.correspondence import CorrespondenceResult, CylinderHint, ViewFrame
from ..views.ring import extract_ring
from .library import ir_point, mk_claim
from .solver import Conflict, SolveReport, merge_with_conflict, solve

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
        m = {frame.u_axis: p.x + frame.u_off, frame.v_axis: p.y + frame.v_off}
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
    circ = _profile_circle(corr, dir_name, lo1, hi1, lo2, hi2)
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
    f = Feature(
        id=FeatureId(0),
        type=Claim(FeatureType.BASE, pmethod, Tier.PROJECTION, evidence=ev),
        params={
            "dir": Claim(dir_name, "projection:thinnest_extent", Tier.PROJECTION,
                         evidence=ev),
            "length": Claim(length, "projection:view_bounds", Tier.PROJECTION,
                            evidence=ev),
            # 轮廓**相对 origin**（发射器按 ir_point(origin, dir, a, b, t) 落位）；
            # 写成绝对坐标会与 origin 叠加一次，造出双倍偏移的零件
            "profile": profile_claim,
            "origin": Claim(origin, "projection:view_bounds", Tier.PROJECTION,
                            evidence=ev),
        },
        placement=Claim(origin, "projection:view_bounds", Tier.PROJECTION,
                        evidence=ev),
        source_view=prof_view.view_id,
        evidence=list(ev),
    )
    if ring_prof is not None:
        rep.notes.append(
            f"基体：轮廓取**轮廓环**（{prof_view.view_id}）—— {ring_note}；"
            f"沿 {dir_name} 拉伸 {length:.2f}，角点在 "
            f"({origin.x:.2f},{origin.y:.2f},{origin.z:.2f})")
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
                      next_id: int, skip=None) -> list[Feature]:
    """一个 ``CylinderHint`` 一条特征。``skip`` 是基体外轮廓的判据（见上）。"""
    out: list[Feature] = []
    for c in corr.cylinders():
        hint = c.mapping.value
        assert isinstance(hint, CylinderHint)
        if skip is not None and skip(hint):
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


# ---- 3) 剖面标题给的轴线 ----

def merge_section_axes(corr: CorrespondenceResult, rep: RecognizeReport,
                       part: Part) -> None:
    """把剖面标题/中心线给出的 3D 轴并进特征树。

    与已有特征同一根轴 ⇒ 合并（标注压投影，证据并起来）；
    对不上任何特征且**带半径** ⇒ 它是图纸明写的一处孔/凸台，建成新特征；
    不带半径的中心线（``radius is None``）⇒ 别硬造特征，只记一条待确认。
    """
    for c in corr.axes():
        axis = c.mapping.value
        assert isinstance(axis, Axis3)
        hit = None
        for f in part.features:
            if f.axis is None or f.axis.value is None:
                continue
            d = axis_distance(f.axis.value, axis)
            if d is not None and d <= AXIS_POS_TOL:
                hit = f
                break
        if hit is not None:
            _absorb(hit, axis, c, rep)
            continue
        if axis.radius is None:
            rep.questions.add(Question(
                OpenQuestion.MISSING_DIMENSION,
                f"{'×'.join(c.views)} 的中心线定出一条 3D 轴"
                f"（过 {'(' + ', '.join(f'{q:.2f}' for q in (axis.origin.x, axis.origin.y, axis.origin.z)) + ')'}），"
                "但图纸没给它的半径 ⇒ 是参考轴还是某个特征的轴未定",
                evidence=tuple(e for _, e in c.refs)))
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


def _material_extent(base: Feature) -> dict[str, float]:
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
    return {dir_name: base.params["length"].value, b1: w1, b2: w2}


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
    thick = _material_extent(base)
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
                child = f
                break
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
    for f in cylinder_features(corr, rep, next_id=1, skip=_base_outline(base)):
        part.add(f)
    merge_section_axes(corr, rep, part)
    for f in pattern_features(conv, corr, rep, part):
        part.add(f)
    if thread_links(conv, rep, part):
        rep.notes.append("螺纹标注已挂到对应孔上")
    # 通孔/盲孔必须等剖面标题那一路也进树之后才能判（标题可能已明写「穿…」）
    derive_through(part, rep)
    # 求解**在层内收尾**：先验/关系/欠定兜底共用同一个待确认清单，
    # 否则调用方忘了传 qs 就会重复报（求解层去重正是靠这份清单）
    rep.solved = solve(part, qs=questions)
    rep.conflicts.extend(rep.solved.conflicts)
    return rep


__all__ = [
    "RecognizeReport", "axis_distance", "base_feature", "cylinder_features",
    "derive_through", "merge_section_axes", "pattern_features", "recognize",
    "symmetries", "thread_links",
]
