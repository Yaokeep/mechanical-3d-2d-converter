# -*- coding: utf-8 -*-
"""中心线约定 —— 轴线 / 对称面 / 螺栓分布圆。

与 ``views/correspondence.py`` 的分工：那里做**跨视图**的对应（中心线在
两个视图里共线 ⇒ 同一条 3D 轴），这里做**单个视图内部**的约定解读：

- 中心线把视图一分为二，且轮廓**确实镜像对称** ⇒ 对称面（等式约束，
  求解器可以拿它消元；也是"图上有 2 个孔其实只有 1 个位置"这类
  信息的来源）
- 一圈等半径的圆，圆心等距分布在一个共同的圆上 ⇒ **均布孔阵列**。
  图上只画了 n 个圆，而不是 n 组孔；不识别它就会把"8 个 φ3.3 孔"当成
  "8 个互不相关的孔"，进而丢掉整个分布特征

两条判据都是**几何自证**的：对称要看镜像支撑率，阵列要看圆心是否真落在
同一个圆上且角度均分。不是"看见中心线就宣布对称"。
"""
from __future__ import annotations

from dataclasses import dataclass
from math import atan2, degrees, hypot

from ..evidence.model import Kind, Role
from ..model.claim import Claim, Tier
from ..model.geom2d import Arc2, Circle2, Line2, Point2
from ..model.ids import EvidenceRef
from ..model.questions import OpenQuestion, Question
from .registry import Convention, ConvKind, RuleCtx, by_handle_index, register

#: 镜像配对容差（mm）
MIRROR_TOL = 0.6
#: 对称面判定：镜像支撑率下限（低于此值只能说明"看着像"，不能当约束用）
SYM_SUPPORT = 0.9
#: 阵列判定：圆心到公共中心的半径一致性容差（相对）
BOLT_TOL = 0.08
#: 角度均分的一致性容差（度）
ANG_TOL = 3.0


@dataclass(frozen=True)
class Symmetry:
    """对称面（``ConvKind.SYMMETRY`` 的 value），图纸系表达。"""

    view: str
    which: str            # "u"：竖中心线（左右对称）/ "v"：横中心线（上下对称）
    at: float             # 中心线在图纸上的位置（u 或 v 坐标）
    support: float        # 镜像支撑率 ∈ [0,1]


@dataclass(frozen=True)
class Pattern:
    """均布孔阵列（``ConvKind.PATTERN`` 的 value），图纸系表达。"""

    view: str
    center: Point2
    radius: float                     # 分布圆半径
    n: int                            # 孔数（图上画出来的）
    hole_radius: float
    angles: tuple[float, ...]         # 各孔的角度（度）
    annotated: bool = False           # 文字里写了"均布/等距"

    @property
    def step(self) -> float:
        return 360.0 / self.n if self.n else 0.0


# ---- 1) 对称面 ----

def _mirror_support(geoms: list[object], which: str, at: float) -> float:
    """轮廓关于某条中心线的**镜像支撑率**。

    做法：把每个图元的特征点镜像过去，看原点集里有没有对应物。
    直线取中点 + 长度（镜像后长度不变），圆/弧取圆心 + 半径。
    支撑率 = 找到对应物的图元占比 —— 这是"真的对称"与"中心线画在中间"
    的区别所在。
    """
    def mirror(p: Point2) -> Point2:
        return Point2(2 * at - p.x, p.y) if which == "u" else Point2(p.x, 2 * at - p.y)

    keys: dict[tuple[int, int, int], int] = {}
    for g in geoms:
        k = _sig(g)
        if k is not None:
            keys[k] = keys.get(k, 0) + 1

    if not keys:
        return 0.0
    hit = 0
    for g in geoms:
        k = _sig(g)
        if k is None:
            continue
        mk = _sig_mirrored(g, mirror)
        if mk is not None and keys.get(mk, 0) > 0:
            hit += 1
    return hit / max(len(geoms), 1)


def _sig(g: object) -> tuple[int, int, int] | None:
    """图元的量化签名（用于镜像配对）。"""
    if isinstance(g, Line2):
        m = g.midpoint
        return (round(m.x / MIRROR_TOL), round(m.y / MIRROR_TOL),
                round(g.length / MIRROR_TOL))
    if isinstance(g, (Circle2, Arc2)):
        r = g.radius
        return (round(g.center.x / MIRROR_TOL), round(g.center.y / MIRROR_TOL),
                round(r / MIRROR_TOL))
    return None


def _sig_mirrored(g: object, mirror) -> tuple[int, int, int] | None:
    if isinstance(g, Line2):
        m = mirror(g.midpoint)
        # 镜像不改变长度，但直线自己可能跨在轴上（中点落在轴上则镜像即自身）
        return (round(m.x / MIRROR_TOL), round(m.y / MIRROR_TOL),
                round(g.length / MIRROR_TOL))
    if isinstance(g, (Circle2, Arc2)):
        c = mirror(g.center)
        return (round(c.x / MIRROR_TOL), round(c.y / MIRROR_TOL),
                round(g.radius / MIRROR_TOL))
    return None


@register("centerline.symmetry")
def symmetry(ctx: RuleCtx) -> list[Convention]:
    """中心线 + 轮廓镜像支撑 ⇒ 对称面。"""
    idx = by_handle_index(ctx.d)
    out: list[Convention] = []
    for v in ctx.d.views:
        if v.bbox is None:
            continue
        geoms: list[object] = []
        lines: list[tuple[EvidenceRef, str, float]] = []
        for h in v.evidence:
            e = idx.get(h)
            if e is None:
                continue
            if e.kind == Kind.AXIS and isinstance(e.geom, Line2):
                o = _orient(e.geom)
                if o is not None:
                    lines.append((e.handle, o[0], o[1]))
            elif e.kind == Kind.EDGE and e.role.value != Role.HIDDEN:
                geoms.append(e.geom)
        if not geoms:
            continue
        for handle, which, at in lines:
            sup = _mirror_support(geoms, which, at)
            if sup < SYM_SUPPORT:
                continue
            sym = Symmetry(view=v.id, which=which, at=at, support=sup)
            out.append(Convention(
                rule="centerline.symmetry", kind=ConvKind.SYMMETRY, view=v.id,
                value=sym,
                claim=Claim(sym, "convention:centerline", Tier.CONVENTION,
                            evidence=(handle,)),
                note=f"沿 {'左右' if which == 'u' else '上下'} 镜像支撑 "
                     f"{sup:.0%} ⇒ 该向对称（可作为等式约束；"
                     "解空间减半）",
                evidence=(handle,),
            ))
    return out


def _orient(geom: Line2) -> tuple[str, float] | None:
    """中心线走向：("v", 图纸x) 竖 / ("h", 图纸y) 横；斜线返回 None。"""
    dx = abs(geom.end.x - geom.start.x)
    dy = abs(geom.end.y - geom.start.y)
    if dy > 0 and dx <= 1e-6 * max(1.0, dy):
        return ("v", (geom.start.x + geom.end.x) / 2.0)
    if dx > 0 and dy <= 1e-6 * max(1.0, dx):
        return ("h", (geom.start.y + geom.end.y) / 2.0)
    return None


# ---- 2) 均布孔阵列 ----

@register("centerline.patterns")
def patterns(ctx: RuleCtx) -> list[Convention]:
    """一圈等半径、圆心等距落在同一圆上 ⇒ 均布孔阵列。

    这是"图上只画一个，其余靠约定"之外的另一种情形：**全画出来了**，
    但必须认出它们是**一组**（一个环形阵列特征），而不是 n 个独立孔 ——
    否则会被当成 n 个孤立圆孔，分布特征整个丢掉。
    """
    idx = by_handle_index(ctx.d)
    out: list[Convention] = []
    for v in ctx.d.views:
        groups: dict[int, list[tuple[EvidenceRef, Point2, float]]] = {}
        for h in v.evidence:
            e = idx.get(h)
            if e is None or e.kind != Kind.EDGE:
                continue
            g = e.geom
            if isinstance(g, Circle2):
                c, r = g.center, g.radius
            elif isinstance(g, Arc2) and g.is_full_circle:
                c, r = g.center, g.radius
            else:
                continue
            groups.setdefault(round(r / MIRROR_TOL), []).append((e.handle, c, r))
        for _key, items in groups.items():
            if len(items) < 3:
                continue        # 少于 3 个谈不上"一圈"
            ctr = Point2(sum(c.x for _, c, _ in items) / len(items),
                         sum(c.y for _, c, _ in items) / len(items))
            radii = [hypot(c.x - ctr.x, c.y - ctr.y) for _, c, _ in items]
            r_bar = sum(radii) / len(radii)
            if r_bar < MIRROR_TOL:
                continue        # 半径近乎 0 ⇒ 圆心重合，不是阵列
            if max(abs(r - r_bar) for r in radii) > BOLT_TOL * r_bar:
                continue        # 圆心不在同一个圆上
            angles = sorted(degrees(atan2(c.y - ctr.y, c.x - ctr.x)) % 360.0
                            for _, c, _ in items)
            n = len(angles)
            step = 360.0 / n
            gaps = [(angles[(i + 1) % n] - angles[i]) % 360.0
                    for i in range(n)]
            if max(abs(g - step) for g in gaps) > ANG_TOL:
                continue        # 角度不均分 ⇒ 不是"均布"，只是碰巧等半径
            hole_r = sum(r for _, _, r in items) / n
            anno = any(_says_uniform(t) for t in ctx.d.texts
                       if t.handle in set(v.annotations))
            pat = Pattern(view=v.id, center=ctr, radius=r_bar, n=n,
                          hole_radius=hole_r, angles=tuple(angles),
                          annotated=anno)
            refs = tuple(h for h, _, _ in items)
            out.append(Convention(
                rule="centerline.patterns", kind=ConvKind.PATTERN, view=v.id,
                value=pat,
                claim=Claim(pat, "convention:equally_spaced", Tier.CONVENTION,
                            evidence=refs),
                note=f"{n}×φ{2 * hole_r:g} 均布在 R{r_bar:g} 分布圆上"
                     f"（{v.id}）⇒ 一个环形阵列"
                     + ("；图上文字也写了均布" if anno else ""),
                evidence=refs,
            ))
            if not anno:
                ctx.qs.add(Question(
                    OpenQuestion.AMBIGUOUS_FEATURE,
                    f"{v.id} 的 {n} 个 φ{2 * hole_r:g} 圆圆心等距落在 R{r_bar:g} "
                    "圆上 ⇒ 按均布阵列理解；但图上**没有**写「均布/等距」字样，"
                    "若实为 n 个独立孔位（角度另有标注）须以标注为准",
                    view=v.id, evidence=refs,
                ))
    return out


_UNIFORM_WORDS = ("均布", "等距", "均勻", "均匀", "EQS", "EQ SPACED", "TYP")


def _says_uniform(t) -> bool:
    up = (t.text or "").upper()
    return any(w in up for w in _UNIFORM_WORDS)
