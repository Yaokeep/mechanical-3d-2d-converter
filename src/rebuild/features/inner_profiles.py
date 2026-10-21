# -*- coding: utf-8 -*-
"""内腔轮廓 —— 基体视图里的**隐藏腔面** → 沿基体轴的 POCKET。

## 为什么要有这条通道

基体是"轮廓环 × 拉伸长度"的一块料。图纸上**从外表面开进去的缺口/腔**
（IMU 的两个 L 形角缺口：x±(12..20)、z(2..12)、自 y=3 起深 17）不在
```extract_ring``` 的外环里——外环只描述"最外面一圈"。这类结构在基体
视图里表现为**隐藏线围出的面**，旧路径完全没有消费者，发射出来的基体
把缺口填成实心（实测 IMU 多料 2,816.79 = 2×1,115.37 角缺口 + 573.19 槽）。

## 判据（全部来自图纸，不按零件名/坐标写死）

基体视图（产出基体 profile 的那个视图）的平面被切成若干有界面
（```views.ring.extract_faces``，包含 DCEL 遍历——切向折返的腔口也能走进去）。
满足下面三条的是"从外表面开口的内腔"：

1. **隐藏主导**（``HID_FRAC``）：边界**长度**里 ≥ 65% 是隐藏线。腔壁被前方
   材料盖住，正视图里本来就该是虚线；反过来可见线围成的面是表面台阶/凸台
   足迹，不是内腔（实测 YZYX V3 的六个凸台足迹 hf ≤ 0.56、IMU V1 角缺口
   0.70）。用长度占比而不是段数：PDF 矢量化图纸的腔边界是碎段链。
2. **边界咬住外轮廓**（``nsh ≥ 1``）：至少一条边与 ``extract_ring`` 的外环
   共边。开口缺口从外表面切进去，边界必然贴着外轮廓；纯内部封闭腔不满足，
   留给别的通道——**宁可漏，不可错切**。
3. **不是圆柱**：面里若有一条弧与某个 ``CylinderHint`` 的圆匹配（半径、
   圆心），那是孔/凸台，由 ``cylinder_features`` 负责（IMU 的 r4 槽走圆柱
   通道：半径 4、深度从轮廓对读）。这里再切一遍就重复了。

**轴向范围**由垂直视图读，不从 0 猜：在**含基体轴**的其它（非剖面）视图里，
找"垂直于该轴的那一维"上与候选面投影**中心接近且足够宽**（``SPAN_CENTER``/
``SPAN_WIDTH_MIN``）的面，取它沿轴的范围。多个视图给出的范围按 0.1mm 去重
计票，**唯一多数**才采用；单视图的孤证或打平 ⇒ 不建（§3 原则二）。

## 没做什么（写下来是为了以后别顺手加）

- 不在非基体视图取腔面：bracket V1/V2 分别有 17/36 个隐藏主导面（那是
  凸台与孔的背面轮廓），而基体视图 V0 是 0 —— 只在基体视图取，正是把
  这些噪声挡在外面。
- 不做"沿轴贯穿"的默认：IMU 角缺口横跨 y∈[3,20] 而不是全厚 [0,20]，
  按全厚切会多削 3mm 的实料。范围读不到就不建。
- 锥化基体（``taper_scale``）不参与：轮廓沿轴缩放时"拉伸柱"的假设不成立。
"""
from __future__ import annotations

import math
from collections import Counter

from ..model.claim import Claim, Tier
from ..model.feature_tree import Feature, FeatureType
from ..model.geom import Axis3, Point3, Vector3
from ..model.geom2d import Point2, Profile2, ProfileSeg2
from ..model.ids import FeatureId
from ..views.correspondence import CorrespondenceResult, ViewFrame
from ..views.ring import FaceRing, extract_faces, extract_ring

#: 隐藏段**长度**占比下限（见模块文档第 1 条）
HID_FRAC = 0.65
#: 候选面最小面积（mm²）——与 ring.AREA_FLOOR 同量级，低于此是碎线噪声
MIN_AREA = 5.0
#: 候选面面积上限（相对外环面积）：主体块不是内腔
OUTER_AREA_FRAC = 0.9
#: 垂直视图匹配：投影中心相对候选跨度允许的偏移比例
SPAN_CENTER = 0.25
#: 垂直视图匹配：匹配面的投影跨度不得小于候选跨度的这个比例
SPAN_WIDTH_MIN = 0.5
#: 圆柱提示匹配容差（半径 / 圆心）
HINT_R_TOL = 0.1
HINT_C_TOL = 0.5

_PLANE_AXES: dict[str, tuple[str, str]] = {
    "x": ("y", "z"), "y": ("z", "x"), "z": ("x", "y")}


def inner_pockets(d, corr: CorrespondenceResult, base: Feature,
                  rep) -> list[Feature]:
    """基体视图的隐藏腔面 → POCKET 特征（读不齐的候选只记账、不建）。"""
    params = base.params
    if base.type.value != FeatureType.BASE.value:
        return []                       # 回转体/其它基体不适用
    if "dir" not in params or "profile" not in params:
        return []
    if "taper_scale" in params:
        return []                       # 锥化：轮廓沿轴缩放，柱状假设不成立
    dir_name = params["dir"].value
    frame = corr.frames.get(base.source_view)
    if frame is None or frame.p_axis != dir_name:
        return []
    view = _view_of(d, base.source_view)
    if view is None or view.is_section:
        return []
    b1_axis, b2_axis = _PLANE_AXES[dir_name]
    faces = extract_faces(d, view, roles={"visible", "hidden"})
    if not faces:
        return []
    outer = extract_ring(d, view).ring
    outer_area = outer.area if outer is not None else 0.0
    outer_sigs = {_seg_sig(s) for s in outer.segs} if outer is not None else set()
    hints = _hint_arcs(corr, frame)

    cands: list[FaceRing] = []
    seen: set[tuple] = set()
    for f in faces:
        if f.area < MIN_AREA:
            continue
        if outer_area > 0.0 and f.area > OUTER_AREA_FRAC * outer_area:
            continue                    # 主体块 / 外环本身
        if f.hidden_frac < HID_FRAC:
            continue
        if sum(1 for s in f.segs if _seg_sig(s) in outer_sigs) < 1:
            continue                    # 不贴着外轮廓：封闭内腔，不在此处理
        if _has_hint_arc(f, hints):
            continue                    # 是孔/凸台，交给圆柱通道
        # 同一几何面会被不同遍历/胶合/在微边处断成不同顶点集——按
        # 「面积 + bbox」去重（0.5mm 网格），顶点集键挡不住 32→37→40 这种
        # 同一条边的中间拆分（IMU 实测同一 L 形面 4 份）。
        key = (round(f.area, 1), round(f.bbox.xmin * 2), round(f.bbox.xmax * 2),
               round(f.bbox.ymin * 2), round(f.bbox.ymax * 2))
        if key in seen:
            continue
        seen.add(key)
        cands.append(f)

    out: list[Feature] = []
    for f in cands:
        span = _axial_span(d, corr, frame, f, dir_name)
        if span is None:
            rep.notes.append(
                f"内腔：{base.source_view} 的隐藏面（面积 {f.area:.2f}，"
                f"hf {f.hidden_frac:.2f}）读不到沿 {dir_name} 的范围 ⇒ 不建")
            continue
        prof = _map_face(frame, f.segs, b1_axis, b2_axis)
        if prof is None:
            rep.notes.append(
                f"内腔：{base.source_view} 的隐藏面映射到轮廓平面失败 ⇒ 不建")
            continue
        lo, hi = span
        out.append(_make_pocket(d, view, f, prof, lo, hi, dir_name, rep))
    if out:
        rep.notes.append(
            f"内腔：{len(out)} 个隐藏腔面沿 {dir_name} 建成 POCKET"
            f"（判据 隐藏占比≥{HID_FRAC} + 咬外轮廓 + 非圆柱；"
            f"范围由垂直视图多数票读取）")
    return out


# ---------------------------------------------------------------------------
# 轴向范围（垂直视图）
# ---------------------------------------------------------------------------

def _axial_span(d, corr: CorrespondenceResult, frame: ViewFrame,
                face: FaceRing, dir_name: str) -> tuple[float, float] | None:
    """候选面沿基体轴的范围 —— 垂直视图里匹配面的多数票。

    匹配面 = 在「**该垂直视图**垂直于基体轴的那一维」上（模型系）与
    候选面投影**中心接近**（≤ 25% 跨度）且**跨度 ≥ 50%** 的有界面。
    那一维按各视图自己的 u/v 取：V0 是俯视（x-y）时匹配 x、V2 是侧视
    （y-z）时匹配 z —— 不能用基体视图的 u 轴一以贯之（x 在 V2 里是
    投影方向，拿它找面恒为 None，IMU 实测三视图交叉验证会全灭）。

    满足条件的每个视图至多贡献一个范围（该视图里匹配面的范围并集）；
    全部视图的范围按 0.1mm 去重计票，唯一多数才采用。
    """
    votes: Counter[tuple[float, float]] = Counter()
    n_views = 0
    for fr in corr.frames.values():
        if fr.view_id == frame.view_id:
            continue
        if dir_name not in (fr.u_axis, fr.v_axis):
            continue
        v = _view_of(d, fr.view_id)
        if v is None or v.is_section:
            continue
        other = fr.v_axis if fr.u_axis == dir_name else fr.u_axis
        q_range = _model_range(frame, other, face.bbox)
        if q_range is None:
            continue                    # 基体视图看不到这一维（不该发生）
        n_views += 1
        ranges: set[tuple[float, float]] = set()
        for g in extract_faces(d, v, roles={"visible", "hidden"}):
            gs = _model_range(fr, other, g.bbox)
            if gs is None or not _span_match(q_range, gs):
                continue
            dr = _model_range(fr, dir_name, g.bbox)
            if dr is None:
                continue
            ranges.add((round(dr[0], 1), round(dr[1], 1)))
        # 同一视图给出多个**互异**范围 ⇒ 该视图弃权（并集会把 101..121 与
        # 104..121 混成一票，正是"不猜"要避免的合成）。
        if len(ranges) == 1:
            votes[next(iter(ranges))] += 1
    if not votes or n_views == 0:
        return None
    best_n = max(votes.values())
    best = [r for r, n in votes.items() if n == best_n]
    if len(best) != 1:
        return None                     # 打平：两个范围都说得通 ⇒ 不猜
    if best_n < 2 and n_views >= 2:
        return None                     # 有多个垂直视图却只有一票：对应弱
    lo, hi = best[0]
    if hi - lo <= 0.5:
        return None
    return (lo, hi)


def _span_match(q: tuple[float, float], g: tuple[float, float]) -> bool:
    """候选投影 ``q`` 与面投影 ``g`` 的二维匹配（中心近 + 宽度够）。"""
    wq, wg = q[1] - q[0], g[1] - g[0]
    if wq <= 0.0 or wg <= 0.0:
        return False
    if wg < SPAN_WIDTH_MIN * wq:
        return False
    cq, cg = (q[0] + q[1]) / 2.0, (g[0] + g[1]) / 2.0
    return abs(cq - cg) <= SPAN_CENTER * wq


# ---------------------------------------------------------------------------
# 坐标 / 几何
# ---------------------------------------------------------------------------

def _view_of(d, vid: str):
    return next((v for v in d.views if v.id == vid), None)


def _model_range(fr: ViewFrame, axis: str,
                 bb) -> tuple[float, float] | None:
    """视图 bbox（视图系）→ 模型系某轴上的区间（翻面后取 min/max）。"""
    if axis == fr.u_axis:
        a, b = fr.u_to_model(bb.xmin), fr.u_to_model(bb.xmax)
    elif axis == fr.v_axis:
        a, b = fr.v_to_model(bb.ymin), fr.v_to_model(bb.ymax)
    else:
        return None
    return (min(a, b), max(a, b))


def _seg_sig(s: ProfileSeg2):
    """段的几何签名（用于"面边界与外环共边"的判据）。"""
    if s.kind == "arc" and s.center is not None and s.radius > 0:
        return ("A", round(s.center.x, 1), round(s.center.y, 1),
                round(s.radius, 1))
    return ("L", round(min(s.p1.x, s.p2.x), 1), round(min(s.p1.y, s.p2.y), 1),
            round(max(s.p1.x, s.p2.x), 1), round(max(s.p1.y, s.p2.y), 1))


def _hint_arcs(corr: CorrespondenceResult,
               fr: ViewFrame) -> list[tuple[float, float, float]]:
    """圆柱提示在本视图系里的 (半径, 圆心u, 圆心v)。

    提示的圆心是模型系 ``Axis3.origin``；本视图给不出轴向坐标（0 占位），
    故只取 u/v 两轴分量并反变换回视图系。
    """
    out = []
    for c in corr.cylinders():
        h = c.mapping.value
        o = h.axis.origin
        m = {fr.u_axis: getattr(o, fr.u_axis),
             fr.v_axis: getattr(o, fr.v_axis)}
        u = _to_view(m[fr.u_axis], fr.u_off, fr.u_flip, fr.u_span)
        v = _to_view(m[fr.v_axis], fr.v_off, fr.v_flip, fr.v_span)
        out.append((h.radius, u, v))
    return out


def _to_view(model_val: float, off: float, flip: bool,
             span: tuple[float, float]) -> float:
    """``ViewFrame.u_to_model``/``v_to_model`` 的逆。"""
    val = model_val
    if flip:
        val = span[0] + span[1] - val
    return val - off


def _has_hint_arc(face: FaceRing,
                  hints: list[tuple[float, float, float]]) -> bool:
    for s in face.segs:
        if s.kind != "arc" or s.center is None or s.radius <= 0:
            continue
        for r, hu, hv in hints:
            if abs(s.radius - r) > HINT_R_TOL:
                continue
            if math.hypot(s.center.x - hu, s.center.y - hv) <= HINT_C_TOL:
                return True
    return False


def _map_face(fr: ViewFrame, segs: tuple[ProfileSeg2, ...],
              b1_axis: str, b2_axis: str) -> Profile2 | None:
    """视图系段链 → 模型系轮廓（**绝对坐标**，POCKET 契约口径）。

    弧的旋向按映射行列式整体定号（同 ``recognizer._outline_ring_profile``
    的 P1-D 修法）：拿吸附后的顶点逐段判号会让微弧的符号由噪声决定。
    """
    def fwd(p: Point2) -> Point2:
        m = {fr.u_axis: fr.u_to_model(p.x), fr.v_axis: fr.v_to_model(p.y)}
        return Point2(m[b1_axis], m[b2_axis])

    o = fwd(Point2(0.0, 0.0))
    ex = fwd(Point2(1.0, 0.0))
    ey = fwd(Point2(0.0, 1.0))
    det = ((ex.x - o.x) * (ey.y - o.y) - (ex.y - o.y) * (ey.x - o.x))
    if abs(det) < 1e-12:
        return None
    flip = det < 0.0

    out: list[ProfileSeg2] = []
    for s in segs:
        p1, p2 = fwd(s.p1), fwd(s.p2)
        if s.kind != "arc":
            out.append(ProfileSeg2("line", p1, p2))
            continue
        if s.center is None or s.radius <= 0:
            return None
        c = fwd(s.center)
        out.append(ProfileSeg2(
            "arc", p1, p2, c, s.radius, s.ccw != flip,
            math.atan2(p1.y - c.y, p1.x - c.x),
            math.atan2(p2.y - c.y, p2.x - c.x)))
    prof = Profile2(tuple(out))
    if prof.chain_break() is not None:
        return None
    if prof.signed_area() < 0.0:
        prof = prof.reversed()
    return prof


def _dir_vec(name: str) -> Vector3:
    return {"x": Vector3(1.0, 0.0, 0.0),
            "y": Vector3(0.0, 1.0, 0.0),
            "z": Vector3(0.0, 0.0, 1.0)}[name]


# ---------------------------------------------------------------------------
# 特征
# ---------------------------------------------------------------------------

def _make_pocket(d, view, face: FaceRing, prof: Profile2,
                 lo: float, hi: float, dir_name: str, rep) -> Feature:
    ev = _hidden_handles(d, view)
    meth = "projection:hidden_cavity"
    o = Point3(0.0, 0.0, 0.0)
    return Feature(
        id=FeatureId(-1),
        type=Claim(FeatureType.POCKET, meth, Tier.PROJECTION, ev),
        params={
            "profile": Claim(prof, meth, Tier.PROJECTION, ev),
            "depth": Claim(hi - lo, f"{meth}_span", Tier.PROJECTION, ev),
            # POCKET 契约：axial_at = **腔底**，自底向上挖 depth
            "axial_at": Claim(lo, f"{meth}_span", Tier.PROJECTION, ev),
        },
        axis=Claim(Axis3(o, _dir_vec(dir_name), None), meth,
                   Tier.PROJECTION, ev),
        placement=Claim(o, meth, Tier.PROJECTION, ev),
        source_view=view.id, evidence=list(ev),
    )


def _hidden_handles(d, view) -> tuple[str, ...]:
    by_h = {e.handle: e for e in d.evidence}
    return tuple(h for h in view.evidence
                 if by_h.get(h) is not None
                 and by_h[h].role.value == "hidden")
