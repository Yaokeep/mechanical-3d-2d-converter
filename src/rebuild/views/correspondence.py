# -*- coding: utf-8 -*-
"""跨视图对应关系 —— "三维思维"的技术核心（ARCHITECTURE §4.3、§6.1）。

## 为什么它是承重点

旧管线：三个视图**各自**拉伸成棱柱再求交。代码不知道"俯视图里那个圆"
和"主视图里那两条虚线"是同一个孔，于是"3D 定位"变成一次碰运气的搜索。

本模块：先确立**视图 → 模型的坐标映射**（``ViewFrame``），再把每个图元
翻译成它约束的 3D 对象 —— 圆柱轴、位置约束、点。之后 3D 定位退化成
**投影射线求交**，是平凡算术。

```
俯视图：中心线过圆 c=(45.3, 151.1)          （图纸系）
主视图：中心线 x=45.3
⇒ Axis3(过 (45.3, y?, ...), 向 Z, r=25.5)   ← 两个视图各给一半信息
```

## 模型坐标系（本模块的约定）

**与图纸系同向，原点取零件包围盒最小角**：X = 图纸横向、Z = 图纸纵向、
Y = 由俯视图/侧视图补出的第三向。这样"图纸上量到的图元坐标"与"模型坐标"
只差一个平移，不需要旋转 —— 而平移在 `ViewFrame` 里一处解决。

## 视图 → 模型轴的三张表

| 视图 | 图纸横向 u | 图纸纵向 v | 投影方向（第三轴） |
|---|---|---|---|
| 主/后视 | X | Z | Y |
| 俯/仰视 | X | Y | Z |
| 左/右侧视 | Y | Z | X |
| 剖视 | 由**切平面法向**定（法向 = 投影方向） | | |

剖视那一行是**可推的**：切平面法向即观察方向，剩下两轴就是视图内的 u/v。
实测 bracket：`A—A 纵向全剖 y=0.00` ⇒ 法向 Y ⇒ 视图内容是 (X,Z)，
与 V3 实测 203.3×44.0 吻合；`B—B 横剖 x=121.89` ⇒ 法向 X ⇒ 内容是 (Y,Z)，
与 V4 的 51.0×44.0 吻合。**两个都逐位吻合**，所以这条推理可用。

## 各来源的可信度（对应 ARCHITECTURE §4.3 的四条）

1. **图上明标**（剖面标题的切平面与半径）→ tier=ANNOTATED
2. **中心线**（同视图十字交叉 / 跨视图共线）→ tier=CONVENTION
3. **投影**（圆 ⇒ 轴向为投影方向的圆柱）→ tier=PROJECTION
4. **几何一致**（等半径对、平行线对）→ tier=PROJECTION（仅作候选）

## 遗留（诚实清单）

- **REAR/BOTTOM/RIGHT 的镜像没消解**：这些视图本身就没定性（views/view_typer
  的俯/仰、主/后歧义），镜像只会让 y/z 反号。本模块给出 `mirror_axes`，
  并把两次解释都算出来；**未定就都留着**，不擅自选一个。
- **POINT 对应只做有界版**：端点两两配对是组合爆炸，此处只对
  "与圆/弧心重合或在包围盒极值上"的特征点做配对（见 `_points`），
  全量版属于阶段 3 求解器的活。
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from ..evidence.model import Drawing, Evidence, Kind, Role, View, ViewType
from ..evidence.text_parser import CutSpec, TextKind
from ..model.claim import Claim, Tier, merge
from ..model.geom import Axis3, Point3, Vector3
from ..model.geom2d import Arc2, Circle2, Line2, Point2
from ..model.ids import EvidenceRef
from ..model.questions import OpenQuestion, Question, QuestionList

#: 几何配对容差（mm）。图纸是"示意精确"：位置能对上就到 1e-6 级，
#: 对不上通常是差几毫米 —— 这个容差卡在中间，避免把噪声配对、
#: 又不至于漏掉出图误差级的真实对应。
MATCH_TOL = 0.6
#: 视图间共享轴的取值一致性容差（比 MATCH_TOL 松：视图间可能有出图偏差）
AGREE_TOL = 1.0

#: 视图类型 → (图纸横向对应的模型轴, 图纸纵向对应的模型轴)
_AXES_OF_VIEW: dict[ViewType, tuple[str, str]] = {
    ViewType.FRONT: ("x", "z"), ViewType.REAR: ("x", "z"),
    ViewType.TOP: ("x", "y"), ViewType.BOTTOM: ("x", "y"),
    ViewType.LEFT: ("y", "z"), ViewType.RIGHT: ("y", "z"),
}
_ALL_AXES = ("x", "y", "z")


def _other(axes: tuple[str, str]) -> str:
    return next(a for a in _ALL_AXES if a not in axes)


@dataclass(frozen=True)
class ViewFrame:
    """视图 → 模型的坐标映射（纯平移，见模块开头的坐标系约定）。

    ``u_axis``/``v_axis`` 是图纸横向/纵向对应的模型轴，``p_axis`` 是投影方向
    （即"这个视图看不出来的那一维"）。``u_off``/``v_off`` 把图纸坐标平移到
    模型系：``模型坐标 = 图纸坐标 + 偏移``。

    ``mirror_axes`` 列出**符号未定**的轴：俯/仰、主/后、左/右 各自只差一次
    镜像，未定性时同一张图纸有两种解释。此处的立场是
    **两种都算、都不选**（§3 原则二），由 gate 决定要不要降级。

    ``broken_axes`` 列出**被断裂画法打断**的轴：该向的图只画了一部分，
    跨度是残缺值。立场同样是"不猜"——``model_span`` 对这类轴返回 ``None``，
    让所有拿跨度做判断的调用方（区间一致性、总尺寸定标）自动退让，
    而不是拿一个偏小的跨度去把一个零件按比例压扁。
    """

    view_id: str
    view_type: ViewType
    u_axis: str
    v_axis: str
    p_axis: str
    u_off: float = 0.0
    v_off: float = 0.0
    #: 该视图的 u/v 在模型系里覆盖的区间（用于镜像翻转与一致性检查）
    u_span: tuple[float, float] = (0.0, 0.0)
    v_span: tuple[float, float] = (0.0, 0.0)
    mirror_axes: tuple[str, ...] = ()
    broken_axes: tuple[str, ...] = ()
    def u_to_model(self, u: float, mirror: bool = False) -> float:
        """图纸横向坐标 → 模型坐标（``mirror`` 按 u 跨度翻转）。"""
        val = u + self.u_off
        if mirror and self.u_axis in self.mirror_axes:
            lo, hi = self.u_span
            val = lo + hi - val
        return val

    def v_to_model(self, v: float, mirror: bool = False) -> float:
        val = v + self.v_off
        if mirror and self.v_axis in self.mirror_axes:
            lo, hi = self.v_span
            val = lo + hi - val
        return val

    def to_model(self, u: float, v: float, mirror: bool = False) -> Point3:
        """图纸坐标 → 模型点（第三维取 0，由别的视图补）。"""
        coords = {self.u_axis: self.u_to_model(u, mirror),
                  self.v_axis: self.v_to_model(v, mirror),
                  self.p_axis: 0.0}
        return Point3(coords["x"], coords["y"], coords["z"])

    def model_span(self, axis: str) -> tuple[float, float] | None:
        """该视图在某个模型轴上覆盖的区间。

        断裂画法打断的轴返回 ``None``（跨度残缺，不可作任何定标依据）。
        """
        if axis in self.broken_axes:
            return None
        if axis == self.u_axis:
            return self.u_span
        if axis == self.v_axis:
            return self.v_span
        return None

    def __str__(self) -> str:
        tag = f" 断裂={','.join(self.broken_axes)}" if self.broken_axes else ""
        return (f"{self.view_id}({self.view_type.value}) "
                f"u={self.u_axis}+{self.u_off:.2f} v={self.v_axis}+{self.v_off:.2f} "
                f"p={self.p_axis}{tag}")


# ---- 圆柱提示：圆（一个视图）+ 轮廓线（另一个视图）合成的 3D 解释 ----

@dataclass(frozen=True)
class CylinderHint:
    """一个圆柱的 3D 解释 —— 孔/凸台识别器的输入。

    `solid` 是**歧义的答案**（§3 原则二）：True = 多了材料（凸台），
    False = 少了材料（孔），None = 还没定。它由正交视图里那两条轮廓线是
    实线还是虚线决定 —— 这是"孔 vs 凸台"唯一的消解依据。
    """

    axis: Axis3
    radius: float
    length: float | None = None
    solid: bool | None = None
    #: 半径的来源说明（如 "circle:1F"）
    radius_method: str = ""
    #: 轮廓来源说明
    profile_method: str = ""

    @property
    def resolved(self) -> bool:
        return self.length is not None and self.solid is not None


class CorrKind(StrEnum):
    AXIS = "axis"        # 中心线/切平面 ⇒ 同一条 3D 轴
    POINT = "point"      # 顶点对 ⇒ 3D 点（投影射线求交）
    FEATURE = "feature"  # 圆(视图A) ↔ 轮廓对(视图B) ⇒ 圆柱


@dataclass(frozen=True)
class Correspondence:
    """一条跨视图对应。``mapping`` 是它产出的 3D 解释。"""

    kind: CorrKind
    refs: tuple[tuple[str, EvidenceRef], ...]     # (视图 id, handle) 对
    mapping: Claim[Any]
    note: str = ""

    @property
    def views(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(v for v, _ in self.refs))

    def __str__(self) -> str:
        return (f"{self.kind.value:8} {'×'.join(self.views):14} "
                f"{self.mapping}   {self.note}")


@dataclass
class CorrespondenceResult:
    correspondences: list[Correspondence] = field(default_factory=list)
    frames: dict[str, ViewFrame] = field(default_factory=dict)
    questions: QuestionList = field(default_factory=QuestionList)

    def by_kind(self, kind: CorrKind) -> list[Correspondence]:
        return [c for c in self.correspondences if c.kind == kind]

    def axes(self) -> list[Correspondence]:
        """所有产出了 ``Axis3`` 的对应（报告与识别器的主要消费品）。"""
        return [c for c in self.correspondences
                if isinstance(c.mapping.value, Axis3)]

    def cylinders(self) -> list[Correspondence]:
        return [c for c in self.correspondences
                if isinstance(c.mapping.value, CylinderHint)]


# ---- 1) 视图坐标系 ----

def solve_frames(d: Drawing, qs: QuestionList | None = None,
                 broken: dict[str, tuple[str, ...]] | None = None
                 ) -> tuple[dict[str, ViewFrame], QuestionList]:
    """给每个视图确立 图纸坐标 → 模型坐标 的映射，并做**跨视图一致性检查**。

    一致性检查是白拿的冗余：主视图与俯视图都给出 X 向尺寸、主视图与左视图
    都给出 Z 向尺寸、俯视图与左视图都给出 Y 向尺寸。两路不符 ⇒ 图纸本身
    不自洽（或某视图定性错了），**必须报出来而不是挑一个用**。

    ``broken``：断裂视图（详见 ``conventions.linetype``）。该视图沿某方向的
    图面跨度和位置本来就是残缺的（波浪线处截掉了一段），所以它

    - 不能当该方向的**基准视图**（会把零件尺寸定小）
    - 不参与该方向的**一致性检查**（拿残缺尺寸比完整尺寸必然"不一致"）

    而其他视图仍能给出该方向的完整尺寸 —— 这正是"另找依据"的落点。
    """
    questions = qs if qs is not None else QuestionList()
    broken = broken or {}

    def broken_axes_of(v: View) -> tuple[str, ...]:
        """把约定层的图纸方向（u/v）翻成模型轴名 —— 这需要视图的轴向表，
        故只有本函数（视图坐标系的家）能做这个翻译。"""
        dirs = broken.get(v.id, ())
        if not dirs or v.id not in axis_of:
            return ()
        ua, va = axis_of[v.id]
        return tuple(a for d_, a in (("u", ua), ("v", va)) if d_ in dirs)

    typed = [v for v in d.views if v.bbox is not None and v.resolved_type]
    if not typed:
        # 视图形不成对（只有一个视图，或有视图但都没定性）—— 图纸并没有
        # "什么都看不出来"，它仍然把**正对着的那个面**画全了。此时按
        # "图面即 xy 平面、第三维沿 z" 建一个约定坐标系，让识别层能照常量
        # 出轮廓与孔，只把**垂直于图面的那一维**留成未知（recognizer 会把
        # 它降成 GUESS + 拦路待确认项）。返回空表则连轮廓都拿不到，是过度拒绝。
        if not d.views:
            return {}, questions
        v = max((x for x in d.views if x.bbox is not None),
                key=lambda x: (x.bbox.xmax - x.bbox.xmin)
                * (x.bbox.ymax - x.bbox.ymin), default=None)
        if v is None:
            return {}, questions
        assert v.bbox is not None
        frame = ViewFrame(
            view_id=v.id, view_type=v.resolved_type or v.type.value,
            u_axis="x", v_axis="y", p_axis="z",
            u_span=(v.bbox.xmin, v.bbox.xmax),
            v_span=(v.bbox.ymin, v.bbox.ymax),
        )
        questions.add(Question(
            OpenQuestion.AMBIGUOUS_VIEW,
            f"{v.id} 是唯一可用的视图且未能定性 ⇒ 按「图面即 xy 平面」"
            "建坐标（垂直于图面的一维留作未知，由特征层降级为猜测）",
            view=v.id,
        ))
        return {v.id: frame}, questions

    # 先定各视图的 u/v/p 轴
    axis_of: dict[str, tuple[str, str]] = {}
    for v in typed:
        t = v.resolved_type
        assert t is not None
        if t == ViewType.SECTION:
            axes = _section_axes(v)
            if axes is None:
                questions.add(Question(
                    OpenQuestion.MISSING_SECTION_POS,
                    f"{v.id} 是剖视图但切平面位置未知，无法确定它的视图坐标轴",
                    view=v.id, evidence=tuple(v.annotations[:1]),
                ))
                continue
            axis_of[v.id] = axes
        elif t in _AXES_OF_VIEW:
            axis_of[v.id] = _AXES_OF_VIEW[t]
        # SIDE/UNKNOWN/AUXILIARY/DETAIL 不参与（它们的轴未知）

    # 模型各轴的范围：谁给的最可信，按"该视图的主方向"优先
    span: dict[str, tuple[float, float]] = {}
    for axis, prefer in (("x", (ViewType.FRONT, ViewType.TOP)),
                         ("z", (ViewType.FRONT, ViewType.LEFT)),
                         ("y", (ViewType.TOP, ViewType.LEFT))):
        for want in prefer:
            hit = [v for v in typed if v.resolved_type == want
                   and v.id in axis_of and axis in axis_of[v.id]
                   and axis not in broken_axes_of(v)]
            if hit:
                v = hit[0]
                ua, va = axis_of[v.id]
                assert v.bbox is not None
                span[axis] = ((v.bbox.xmin, v.bbox.xmax) if axis == ua
                              else (v.bbox.ymin, v.bbox.ymax))
                break

    frames: dict[str, ViewFrame] = {}
    for v in typed:
        if v.id not in axis_of:
            continue
        ua, va = axis_of[v.id]
        pa = _other((ua, va))
        assert v.bbox is not None
        broken_here = broken_axes_of(v)
        # 偏移：让本视图的 u/v 区间与已定的模型区间对齐。
        # **跨度一致**（差 ≤ 容差）时按左缘对齐 —— 视图间平移是布局，
        # 左缘是自然基准。**跨度不一致**时左缘对齐会引入半个跨度差的伪
        # 平移：实测 PF60K 俯视图只画 ±30 的方框，r40 的角弧不撑 bbox，
        # X 向跨度 60 vs 主视图的 80，左缘对齐把圆心平移了 10mm（与主视
        # 图轴线错位、所有圆的配对轮廓都找不到）。此时按**中心对齐**并
        # 记账 —— 中心是跨度的固有基准，与子集关系无关。
        # **断裂轴不参与**：残缺跨度与完整跨度比必然"不一致"，比它没有
        # 意义（该轴的内容坐标本来就是拼接的残片，不构成定标依据）。
        def _align(own: tuple[float, float], ref: tuple[float, float] | None,
                   axis: str, is_broken: bool) -> tuple[float, tuple[float, float]]:
            """返回 (偏移, 该轴区间登记)。ref=None ⇒ 本视图自己定。"""
            olo, ohi = own
            if ref is None:
                return 0.0, own
            rlo, rhi = ref
            if is_broken:
                return rlo - olo, ref
            w_o, w_r = ohi - olo, rhi - rlo
            if abs(w_o - w_r) <= max(MATCH_TOL, 0.01 * max(w_o, w_r)):
                off = rlo - olo
            else:
                off = (rlo + rhi) / 2.0 - (olo + ohi) / 2.0
                questions.add(Question(
                    OpenQuestion.AMBIGUOUS_VIEW,
                    f"{axis.upper()} 向跨度两路不一致：{v.id} 量得 {w_o:.2f}、"
                    f"基准视图量得 {w_r:.2f}（差 {abs(w_o - w_r):.2f}）——"
                    "按**中心对齐**（左缘对齐会引入半个跨度差的伪平移）",
                    view=v.id, evidence=tuple(v.evidence[:1]),
                    candidates=(f"中心对齐 {off:+.2f}", f"左缘对齐 {rlo - olo:+.2f}"),
                ))
            # 登记该轴区间（有基准时借基准的区间，与跨视图并集口径一致）
            return off, ref

        u_off, u_span = _align((v.bbox.xmin, v.bbox.xmax), span.get(ua), ua,
                               ua in broken_here)
        v_off, v_span = _align((v.bbox.ymin, v.bbox.ymax), span.get(va), va,
                               va in broken_here)
        mirror: tuple[str, ...] = ()
        # 俯/仰、主/后、左/右 只差一次镜像 —— 方向没定就两种解释都留着
        t = v.resolved_type
        if t in (ViewType.BOTTOM, ViewType.REAR, ViewType.RIGHT) or (
                not v.type.is_settled):
            mirror = (ua,) if ua in ("y",) or t == ViewType.REAR else (va,)
        frame = ViewFrame(
            view_id=v.id, view_type=t, u_axis=ua, v_axis=va, p_axis=pa,
            u_off=u_off, v_off=v_off,
            u_span=u_span, v_span=v_span, mirror_axes=mirror,
            broken_axes=broken_axes_of(v),
        )
        frames[v.id] = frame

        # ---- 一致性检查（同一个模型轴被两个视图各说了一次） ----
        # ⚠️ 修复前此检查恒不触发：比较的第二项用的是 u_lo/u_hi，而它们
        # 在基准缺失时就是 mine 的拷贝、存在时又恰等于 ref ⇒ 条件恒真。
        # 现在改回拿**本视图自身的 bbox 跨度**与基准跨度比。
        broken_here = broken_axes_of(v)
        for axis, mine in ((ua, (v.bbox.xmin, v.bbox.xmax)),
                           (va, (v.bbox.ymin, v.bbox.ymax))):
            if axis in broken_here:
                continue     # 断裂视图的跨度量的是残缺的部分，比了必然"不一致"
            ref = span.get(axis)
            if ref is None:
                continue
            a, b = mine[1] - mine[0], ref[1] - ref[0]
            if abs(a - b) > max(MATCH_TOL, 0.01 * max(a, b)):
                questions.add(Question(
                    OpenQuestion.AMBIGUOUS_VIEW,
                    f"{axis.upper()} 向尺寸两路不一致：{v.id} 给 {a:.2f}、"
                    f"基准视图给 {b:.2f}（差 {abs(a - b):.2f}）—— "
                    "可能是视图定性错或图纸本身不自洽",
                    view=v.id, evidence=tuple(v.evidence[:1]),
                    candidates=(f"{a:.2f}", f"{b:.2f}"),
                ))
    return frames, questions


def _section_axes(v: View) -> tuple[str, str] | None:
    """剖视图的内容轴 = 切平面内的两轴（法向即投影方向）。"""
    cut = v.cut
    if not isinstance(cut, CutSpec) or not cut.is_located:
        return None
    n = cut.cut_axis
    if n not in _ALL_AXES:
        return None
    rest = [a for a in _ALL_AXES if a != n]
    # 图纸纵向对应 Z（本仓库出图与常规一致），故若含 z 则 z 为 v
    if "z" in rest:
        return (rest[0], "z") if rest[0] != "z" else ("x", "z")
    return (rest[0], rest[1])


# ---- 2) 剖面标题 ⇒ 3D 轴线 ----

def _section_extent(frames: dict[str, ViewFrame], axis: str) -> tuple[float, float] | None:
    """零件在某模型轴上的总跨度（取所有视图给出的最大值）。"""
    spans = [f.model_span(axis) for f in frames.values()]
    spans = [s for s in spans if s is not None]
    if not spans:
        return None
    return (min(s[0] for s in spans), max(s[1] for s in spans))


@dataclass(frozen=True)
class _Row:
    """一个剖面的定位结果：方向与垂直位置已定，只差切平面法向上的坐标。

    ``cands`` 是该法向上由**几何**给出的候选位置（半径 r 的圆）。标题给的是
    **符号**位置，两者之差就是配准关系 —— 见 :func:`_solve_registration`。
    """

    v: View
    cut: CutSpec
    n: str                       # 切平面法向轴
    axis_dir: str                # 孔轴方向（切平面内的另一轴）
    perp: str                    # 垂直于孔轴的方向
    center: float                # 孔轴在模型系的垂直坐标
    centers: dict[str, float]    # 每个候选方向 → 垂直于它的中心（备选轴要用）
    r: float
    refs: tuple[tuple[str, EvidenceRef], ...]
    rule: str
    cands: tuple[tuple[float, EvidenceRef, str], ...] = ()   # (位置, 圆, 来源视图)
    extra_alts: tuple[str, ...] = ()


@dataclass(frozen=True)
class _Reg:
    """同一法向轴上、所有剖面**共用**的配准关系（标题坐标 → 模型坐标）。

    kind: ``translate``（模型 = 标题 + param）/ ``mirror``（模型 = param − 标题）
    / ``none``（无从判定，按标题原值用）。
    """

    kind: str = "none"
    param: float = 0.0

    def pos_of(self, title: float) -> float:
        if self.kind == "translate":
            return title + self.param
        if self.kind == "mirror":
            return self.param - title
        return title


def axes_from_sections(d: Drawing, frames: dict[str, ViewFrame],
                       qs: QuestionList) -> list[Correspondence]:
    """剖面标题 → 3D 轴线（**本仓库唯一可用的轴线来源**，见模块注释）。

    标题给出两件硬信息：切平面位置与半径。剩下两件要推：

    - **方向**：轴必在切平面内（标题写"穿 … 孔轴"），即在剩余两个轴之一上。
      主判据与坐标系无关：**垂直于轴**的那个方向上截面跨度 ≈ 2R（切平面过轴
      ⇒ 截出直径）。备判据（孔没切到轴时）才是"沿轴跨度 ≈ 零件总跨度"。
    - **垂直位置**：垂直于轴的那个方向上取截面跨度的中点。
    - **切平面位置**：**不能直接用标题值** —— 标题写在出图侧的零件坐标系里，
      与图纸视图坐标系之间差一个平移甚至镜像，由 :func:`_solve_registration`
      跨剖面联合配准。
    """
    idx = _index(d)
    # ---- 第一遍：逐剖面定位（方向 + 垂直位置），收集配准候选 ----
    rows: list[_Row] = []
    for v in d.views:
        if v.resolved_type != ViewType.SECTION or v.bbox is None:
            continue
        cut = v.cut
        if not isinstance(cut, CutSpec) or not cut.is_located:
            continue
        if cut.radius is None and cut.diameter is None:
            continue                       # 无半径 ⇒ 只知切平面，不知轴
        r = cut.radius if cut.radius is not None else cut.diameter / 2.0  # type: ignore[operator]
        title = next((t for t in d.texts
                      if t.kind == TextKind.SECTION_TITLE
                      and t.cut is not None and t.cut.label == cut.label), None)
        refs: tuple[tuple[str, EvidenceRef], ...] = (
            ((v.id, title.handle),) if title is not None else ()
        )
        n = cut.cut_axis
        in_plane = [a for a in _ALL_AXES if a != n]
        if v.id not in frames:
            qs.add(Question(
                OpenQuestion.MISSING_SECTION_POS,
                f"{v.id}（{cut.label}）的切平面位置读到了，但视图坐标系没建起来",
                view=v.id, evidence=tuple(v.annotations[:1]),
            ))
            continue
        f = frames[v.id]
        # 截面在**本视图自己的**图纸范围里占多长 —— 不能用 frame 的对齐窗口
        # （那是"零件在该轴上的总跨度"，各视图共享，用它算得分恒等于 1）。
        assert v.bbox is not None
        span_d = {}
        for axis in in_plane:
            if axis == f.u_axis:
                span_d[axis] = abs(f.u_to_model(v.bbox.xmax)
                                   - f.u_to_model(v.bbox.xmin))
            elif axis == f.v_axis:
                span_d[axis] = abs(f.v_to_model(v.bbox.ymax)
                                   - f.v_to_model(v.bbox.ymin))
        total = {a: _section_extent(frames, a) for a in in_plane}

        # 判据一（主）：**垂直于轴**的跨度 ≈ 2R —— 切平面过轴就截出直径。
        # 这条与坐标系无关，是最硬的信号。实测 bracket：63/64 两个剖面都是
        # 5/5 与 40/40 逐位吻合。
        # 判据二（备）：轴方向上的截面跨度 ≈ 零件总跨度（旧规则，只在
        # 判据一失效时用 —— 孔没切到轴、或半径是别的特征的）。
        scores: dict[str, tuple[float, float]] = {}
        for axis in in_plane:
            perp = next(a for a in in_plane if a != axis)
            d_perp, d_axis = span_d.get(perp), span_d.get(axis)
            if d_perp is None or d_axis is None:
                continue
            e1 = abs(d_perp - 2 * r) / max(2 * r, 1e-9)
            tot = total.get(axis)
            e2 = (abs(d_axis - (tot[1] - tot[0])) / max(tot[1] - tot[0], 1e-9)
                  if tot else 1.0)
            scores[axis] = (e1, e2)

        DIR_TOL = 0.15
        cand = [a for a, (e1, _) in scores.items() if e1 <= DIR_TOL]
        rule = "convention:section_diameter"
        if not cand:
            cand = [a for a, (_, e2) in scores.items() if e2 <= DIR_TOL]
            rule = "convention:section_extent"
        if not cand:
            qs.add(Question(
                OpenQuestion.AMBIGUOUS_FEATURE,
                f"{cut.label}（{v.id}）截面形状判不出孔轴方向："
                f"垂直跨度 {[f'{a}:{span_d.get(a, 0):.2f}' for a in in_plane]}、"
                f"2R={2 * r:.2f} —— 切平面可能没穿过孔轴",
                view=v.id, evidence=tuple(v.annotations[:1]),
                candidates=tuple(in_plane),
            ))
            continue
        cand.sort(key=lambda a: scores[a])
        axis_dir = cand[0]
        perp = next(a for a in in_plane if a != axis_dir)
        # 每个候选方向都先记下"垂直于它的中心" —— 备选轴要用**另一个方向**的
        # 中心，产出时才需要，故这里一次算全
        centers: dict[str, float] = {}
        for a in cand:
            pa = next(x for x in in_plane if x != a)
            if pa == f.u_axis:
                lo, hi = f.u_to_model(v.bbox.xmin), f.u_to_model(v.bbox.xmax)
            else:
                lo, hi = f.v_to_model(v.bbox.ymin), f.v_to_model(v.bbox.ymax)
            centers[a] = (lo + hi) / 2.0

        cands = _cut_pos_candidates(d, idx, frames, v, cut, axis_dir, r)
        if not cands:
            qs.add(Question(
                OpenQuestion.MISSING_SECTION_POS,
                f"{cut.label}：标题写 {n}={cut.cut_pos:g}，但图纸里没有半径 {r:g} 的圆"
                "可用于配准 —— 切平面在模型系的真实位置未知，暂按标题原值使用"
                "（可能与视图坐标系不同源）",
                view=v.id, evidence=tuple(v.annotations[:1]),
            ))
        rows.append(_Row(
            v=v, cut=cut, n=n, axis_dir=axis_dir, perp=perp,
            center=centers[axis_dir], centers=centers, r=r, refs=refs,
            rule=rule, cands=cands, extra_alts=tuple(cand[1:]),
        ))

    if not rows:
        return []

    # ---- 配准：**跨剖面联合**求解（单个剖面区分不了平移与镜像） ----
    regs = _solve_registration(rows, qs)

    # ---- 第二遍：产出轴线 ----
    out: list[Correspondence] = []
    dirs = {"x": Vector3(1, 0, 0), "y": Vector3(0, 1, 0), "z": Vector3(0, 0, 1)}
    for row in rows:
        v, cut, n = row.v, row.cut, row.n
        reg = regs.get(n, _Reg())
        pos_n = reg.pos_of(cut.cut_pos)
        hit = _match_cand(row, pos_n)
        reg_ev: tuple[EvidenceRef, ...] = (hit[1],) if hit else ()
        reg_note = _reg_note(reg, row, pos_n, hit[2] if hit else "")
        coords = {row.axis_dir: 0.0, row.perp: row.center, n: pos_n}
        origin = Point3(coords["x"], coords["y"], coords["z"])

        radius_claim = Claim(row.r, "note:section_title", Tier.ANNOTATED,
                             evidence=row.refs[0][1:] or ())
        method = f"note:section_title+{row.rule}({cut.label})"
        evidence = tuple(h for _, h in row.refs) + reg_ev
        alts: tuple[Axis3, ...] = ()
        if row.extra_alts:
            # 备选轴：方向换另一个候选，位置改由**那个方向**的截面跨度中点定
            other = row.extra_alts[0]
            alt_perp = next(a for a in (row.axis_dir, row.perp) if a != other)
            c2 = {n: pos_n, other: 0.0,
                  alt_perp: row.centers.get(other, row.center)}
            alts = (Axis3(Point3(c2["x"], c2["y"], c2["z"]), dirs[other],
                          radius_claim),)
        mapping = Claim(Axis3(origin, dirs[row.axis_dir], radius_claim), method,
                        Tier.ANNOTATED, evidence=evidence, alternatives=alts)
        out.append(Correspondence(
            CorrKind.AXIS, row.refs, mapping,
            note=f"{cut.label} 切平面 {n}={cut.cut_pos:g}（{reg_note}）"
                 f"⇒ 轴沿 {row.axis_dir.upper()}，半径 {row.r:g}",
        ))
    return out


def _cut_pos_candidates(d: Drawing, idx: dict[str, Evidence],
                        frames: dict[str, ViewFrame], v: View, cut: CutSpec,
                        axis_dir: str, r: float
                        ) -> tuple[tuple[float, EvidenceRef, str], ...]:
    """由**几何**给出切平面的候选模型坐标：在"投影方向 = 孔轴"的视图里找半径 r 的圆。

    标题里的坐标是出图侧在**零件自身坐标系**里写的，而图纸的视图有各自的
    摆放偏移 —— 两者之间至少差一个平移，实测 bracket 还差一个镜像。直接拿标题
    的数字当模型坐标用是**静默的错**（它错得很像对的：数值合理、量级正常）。

    配准只能靠几何：切平面法向 n、半径 r 的孔，必然在"投影方向 = 孔轴方向"
    的那个视图里留下一个**半径 r 的圆**；这些圆沿 n 的坐标就是切平面在模型系
    里的位置。
    """
    n = cut.cut_axis
    out: list[tuple[float, EvidenceRef, str]] = []
    for w in d.views:
        if w.id == v.id or w.id not in frames or w.bbox is None:
            continue
        wf = frames[w.id]
        if wf.p_axis != axis_dir:
            continue          # 该视图看不出来"孔轴方向"这一维 ⇒ 圆不成圆
        for h, p, cr in _circles_of(d, idx, w):
            if abs(cr - r) > MATCH_TOL:
                continue
            if wf.u_axis == n:
                pos = wf.u_to_model(p.x)
            elif wf.v_axis == n:
                pos = wf.v_to_model(p.y)
            else:
                continue
            out.append((pos, h, w.id))
    return tuple(out)


def _solve_registration(rows: list[_Row],
                        qs: QuestionList) -> dict[str, _Reg]:
    """跨剖面**联合**解出"标题坐标 → 模型坐标"的关系 —— 单个剖面解不出这件事。

    一个剖面只有一组候选圆时，"平移"与"镜像"都能拟合它（自由度为 1，欠定）。
    只有两个及以上剖面给出**同一个**关系才算数。这正是 bracket 的情形：

    - 平移解不存在：B—B 的偏移 −76.59、C—C 的 +203.41 互不相同
    - 镜像解存在：k = 167.191 同时拟合两者（45.301+121.89 = 185.301−18.11）

    ⇒ 符号通道与图面几何**互为镜像**。这不是"缺信息"，是两路证据矛盾，
    必须报出来（``INCONSISTENT_FRAME``）而不是悄悄选一路。位置仍取几何值 ——
    几何是零件的直接投影，符号是它的转录。
    """
    groups: dict[str, list[_Row]] = {}
    for row in rows:
        groups.setdefault(row.n, []).append(row)

    out: dict[str, _Reg] = {}
    for n, group in groups.items():
        have = [r for r in group if r.cands]
        if not have:
            out[n] = _Reg()          # 位置无从判定，按标题原值（Question 已单报）
            continue
        ev = tuple(h for r in have for _, h, _ in r.cands[:1])
        offsets = {round(p - r.cut.cut_pos, 2) for r in have for p, _, _ in r.cands}
        if len(offsets) == 1:
            out[n] = _Reg("translate", next(iter(offsets)))
            continue
        mirrors = {round(p + r.cut.cut_pos, 2) for r in have for p, _, _ in r.cands}
        if len(mirrors) == 1 and len(have) >= 2:
            k = next(iter(mirrors))
            out[n] = _Reg("mirror", k)
            qs.add(Question(
                OpenQuestion.INCONSISTENT_FRAME,
                f"切平面法向 {n}：剖面标题的坐标与图面坐标**互为镜像**"
                f"（图面 = {k:.3f} − 标题；{len(have)} 个剖面各自独立给出同一常量），"
                f"而平移解不存在（候选偏移 {sorted(offsets)}）。出图侧至少有一个视图的"
                "投影方向与常规相反（本仓库 project_shape_to_2d 取 dx = up × dz，"
                "dz=(0,0,-1) 时把俯视图画成了仰视图）。切平面位置已按几何圆配准，"
                "**不要改用标题原值**",
                evidence=ev,
                candidates=(f"mirror:{k:.3f}",)
                           + tuple(f"offset:{o:.2f}" for o in sorted(offsets)),
            ))
            continue
        qs.add(Question(
            OpenQuestion.AMBIGUOUS_FEATURE,
            f"切平面法向 {n}：{len(group)} 个剖面给出的配准关系互不相容 —— "
            f"候选平移 {sorted(offsets)}、候选镜像 {sorted(mirrors)}；"
            "符号通道与几何通道不同源，切平面位置暂按标题原值使用（可疑）",
            evidence=ev,
            candidates=tuple(f"offset:{o:.2f}" for o in sorted(offsets)),
        ))
        out[n] = _Reg()
    return out


def _match_cand(row: _Row, pos: float) -> tuple[float, EvidenceRef, str] | None:
    """找出与配准结果吻合的那个候选圆（用于证据与 note 的出处）。"""
    best: tuple[float, EvidenceRef, str] | None = None
    for cand in row.cands:
        if abs(cand[0] - pos) > MATCH_TOL:
            continue
        if best is None or abs(cand[0] - pos) < abs(best[0] - pos):
            best = cand
    return best


def _reg_note(reg: _Reg, row: _Row, pos: float, src: str) -> str:
    """配准过程的自然语言交代（写进 Correspondence.note，报告可见）。"""
    t = row.cut.cut_pos
    if reg.kind == "translate":
        if abs(reg.param) < 0.01:
            return f"与圆 {src} 配准吻合" if src else "与视图坐标系同源"
        return (f"标题 {t:g} + 出图偏移 {reg.param:+.2f} = {pos:.2f}"
                + (f"（圆 {src}）" if src else ""))
    if reg.kind == "mirror":
        return (f"标题 {t:g} 经图面镜像 {reg.param:.3f}−标题 = {pos:.2f}"
                + (f"（圆 {src}）" if src else ""))
    return f"未配准，按标题原值 {t:g}"


# ---- 3) 中心线 ⇒ 轴线 / 位置约束 ----

def _centerline_orient(geom: Line2) -> tuple[str, float] | None:
    """中心线的走向：("v", 图纸x) 竖线 / ("h", 图纸y) 横线；斜线返回 None。"""
    dx = abs(geom.end.x - geom.start.x)
    dy = abs(geom.end.y - geom.start.y)
    if dy > 0 and dx <= 1e-6 * max(1.0, dy):
        return ("v", (geom.start.x + geom.end.x) / 2.0)
    if dx > 0 and dy <= 1e-6 * max(1.0, dx):
        return ("h", (geom.start.y + geom.end.y) / 2.0)
    return None


def axes_from_centerlines(d: Drawing, frames: dict[str, ViewFrame],
                          qs: QuestionList) -> list[Correspondence]:
    """中心线 ⇒ 3D 轴（同视图十字交叉）或 ⇒ 位置约束（跨视图共线）。

    **本仓库的图纸一条中心线都没有**（见下方"实测"），所以这条路径只能靠
    合成证据单测；它保留的原因是真图纸（用户手画的）一定有中心线。

    实测（2026-09-28）：bracket 三视图/剖面图纸、spoon、pf60k、block_3view
    六张图逐张查过，`Kind.AXIS` 数分别是 0/0/0/0/6 —— 前五张是 HLR 机器出图，
    根本不画中心线；block_3view 有 6 条但它们不参与轮廓（白名单已排除）。
    """
    # 收集：每个视图里的竖直/水平中心线
    vert: dict[str, list[tuple[EvidenceRef, float]]] = {}   # 图纸 x
    horiz: dict[str, list[tuple[EvidenceRef, float]]] = {}  # 图纸 y
    for e in d.evidence:
        if e.kind != Kind.AXIS or not isinstance(e.geom, Line2):
            continue
        v = d.view_of(e.handle)
        if v is None or v.id not in frames:
            continue
        o = _centerline_orient(e.geom)
        if o is None:
            continue            # 斜中心线（斜视图用）暂不处理
        (vert if o[0] == "v" else horiz).setdefault(v.id, []).append((e.handle, o[1]))

    out: list[Correspondence] = []

    # ---- 3a 同视图交叉 ⇒ 一条垂直于该视图的 3D 轴 ----
    for vid, vs in vert.items():
        f = frames[vid]
        if f.u_axis not in ("x", "y") or f.v_axis not in ("x", "y", "z"):
            continue
        hs = horiz.get(vid, [])
        if not hs:
            continue
        for h_v, x_l in vs:
            for h_h, y_l in hs:
                um, vm = f.u_to_model(x_l), f.v_to_model(y_l)
                coords = {f.u_axis: um, f.v_axis: vm, f.p_axis: 0.0}
                origin = Point3(coords["x"], coords["y"], coords["z"])
                dirs = {"x": Vector3(1, 0, 0), "y": Vector3(0, 1, 0),
                        "z": Vector3(0, 0, 1)}
                mapping = Claim(
                    Axis3(origin, dirs[f.p_axis]),
                    "convention:centerline_cross", Tier.CONVENTION,
                    evidence=(h_v, h_h),
                )
                out.append(Correspondence(
                    CorrKind.AXIS, ((vid, h_v), (vid, h_h)), mapping,
                    note=f"{vid} 十字中心线交点 ⇒ 垂直于该视图的轴",
                ))

    # ---- 3b 跨视图共线 ⇒ 同一位置约束（轴方向由第三视图或圆补） ----
    pos: dict[tuple[str, str], list[tuple[str, EvidenceRef, float]]] = {}
    for vid, vs in vert.items():
        f = frames[vid]
        for h, x_l in vs:
            val = f.u_to_model(x_l)
            key = (f.u_axis, f"{val:.1f}")
            pos.setdefault(key, []).append((vid, h, val))
    for vid, hs in horiz.items():
        f = frames[vid]
        for h, y_l in hs:
            val = f.v_to_model(y_l)
            key = (f.v_axis, f"{val:.1f}")
            pos.setdefault(key, []).append((vid, h, val))

    for (axis, _), items in pos.items():
        views = {v for v, _, _ in items}
        if len(views) < 2:
            continue                    # 单视图内的位置不算"跨视图对应"
        vals = [val for _, _, val in items]
        if max(vals) - min(vals) > AGREE_TOL:
            continue                    # 位置对不上 ⇒ 不是同一条轴（防误配）
        refs = tuple((v, h) for v, h, _ in items)
        mapping = merge([Claim(val, f"centerline:{v}", Tier.CONVENTION,
                               evidence=(h,)) for v, h, val in items])
        out.append(Correspondence(
            CorrKind.AXIS, refs, mapping,
            note=f"{len(views)} 个视图的中心线在 {axis.upper()}={vals[0]:.2f} 共线 "
                 "⇒ 同一位置（轴方向待第三视图补）",
        ))
    return out


# ---- 4) 圆 ⇒ 圆柱（+ 与正交视图的轮廓线配对） ----

def _index(d: Drawing) -> dict[str, Evidence]:
    """handle → Evidence。

    ``Drawing.by_handle`` 是**线性扫描**，这几处热循环里逐 handle 调它
    等于 O(n²)（6600 图元的图纸实测卡死），故就地建一次索引。
    """
    return {e.handle: e for e in d.evidence}


def _circles_of(d: Drawing, idx: dict[str, Evidence], v: View
                ) -> list[tuple[EvidenceRef, Point3, float]]:
    """视图里的整圆/整圆弧 → (handle, 图纸圆心, 半径)。

    HLR 出图的圆常被打成整圆弧（Arc2 张角 2π），故两种都收。
    """
    out: list[tuple[EvidenceRef, Point3, float]] = []
    for h in v.evidence:
        e = idx.get(h)
        if e is None or e.kind != Kind.EDGE:
            continue
        g = e.geom
        if isinstance(g, Circle2):
            out.append((e.handle, Point3(g.center.x, g.center.y, 0.0), g.radius))
        elif isinstance(g, Arc2):
            span = (g.end_angle - g.start_angle) % (2 * math.pi)
            if span > 2 * math.pi - 0.02:
                out.append((e.handle, Point3(g.center.x, g.center.y, 0.0), g.radius))
    return out


@dataclass(frozen=True)
class _Pair:
    """两条平行轮廓线构成的一对（圆柱在某视图里的侧面轮廓）。"""

    h1: EvidenceRef
    h2: EvidenceRef
    sep: float          # 两线间距 = 直径
    perp_mid: float     # 间距中点（图纸坐标，沿"垂直于线"的方向）
    length: float       # 两线长度的较小者 = 圆柱轴向长度
    visible: bool


def _parallel_line_pairs(idx: dict[str, Evidence], v: View, along: str,
                         want_sep: float) -> list[_Pair]:
    """找视图里**指定朝向、指定间距**的平行线对 —— 圆柱的侧面轮廓。

    ``along``：线条在图纸里的朝向，"h" 水平 / "v" 竖直。
    调用方由"圆柱轴对应视图的哪一轴"推出（见 cylinders_from_circles）。

    实现要点：**不做两两配对**。2711+3821 条边的图纸上 O(n²) 是分钟级
    （实测卡死），改为按垂直坐标分桶，只查 ±want_sep 那几个桶 —— O(n)。
    """
    horizontal = along == "h"
    bucketed: dict[int, list[tuple[EvidenceRef, float, float, bool]]] = {}
    for h in v.evidence:
        e = idx.get(h)
        if e is None or e.kind != Kind.EDGE or not isinstance(e.geom, Line2):
            continue
        # **只有可见/隐藏轮廓能当侧面轮廓**：剖面图的剖面线边界与可见轮廓
        # 完全重合，若混进来，"实线还是虚线"就变成了"先碰上哪条重合实体"
        # 的运气。实测 bracket 的 C—C 剖视图：r20（真值是环状挂耳的外径，
        # 与 r25.5 结构相同）因先碰上 hatch 角色 → solid=False 读成孔，
        # 而 r25.5 碰上实线 → 凸台——同一图纸同一结构两种答案。
        if e.role.value not in (Role.VISIBLE, Role.HIDDEN):
            continue
        g = e.geom
        dx, dy = abs(g.end.x - g.start.x), abs(g.end.y - g.start.y)
        major, minor = (dx, dy) if horizontal else (dy, dx)
        if major <= 1e-9 or minor > 1e-6 * major:
            continue                      # 斜线 / 短线不算轮廓
        perp = (g.start.y + g.end.y) / 2.0 if horizontal \
            else (g.start.x + g.end.x) / 2.0
        line_len = major
        if line_len <= 1e-9:
            continue
        bucketed.setdefault(round(perp / MATCH_TOL),
                            []).append((h, perp, line_len,
                                        e.role.value == Role.VISIBLE))

    out: list[_Pair] = []
    span = round(want_sep / MATCH_TOL)
    for b, items in bucketed.items():
        for h1, p1, len1, vis1 in items:
            for nb in range(b + span - 1, b + span + 2):
                for h2, p2, len2, vis2 in bucketed.get(nb, []):
                    if h1 == h2 or vis1 != vis2:
                        continue
                    if nb == b and h1 > h2:
                        # 同桶（间距 < 容差）时对称访问会给出两次，按名字去一次。
                        # ⚠️ 曾对所有桶都做 `h1 > h2`——那是按 **handle 字符串**
                        # 去重：handle 序与位置序不一致的合法对会被整对丢弃
                        # （实测 bracket：x=2.00 与 x=42.03 的可见轮廓对
                        # "1955"/"1918" 因 1955>1918 被误判重复，r20 只剩
                        # 剖面线的重合对可配对）。向上搜索每个对只访问一次，
                        # 无需去重；只有同桶对称才要。
                        continue
                    sep = abs(p2 - p1)
                    if abs(sep - want_sep) > MATCH_TOL:
                        continue
                    out.append(_Pair(h1, h2, sep, (p1 + p2) / 2.0,
                                     min(len1, len2), vis1))
    return out


def cylinders_from_circles(d: Drawing, frames: dict[str, ViewFrame],
                           qs: QuestionList) -> list[Correspondence]:
    """圆 ⇒ 圆柱轴；再拿正交视图里的轮廓对补上长度与"孔还是凸台"。

    **同心圆不合并**：同一个圆心上的多个圆是**多条圆边**，可能读成
    沉孔/倒角/台阶（同一根轴上的两个直径），也可能读成"盘 + 中心孔"、
    "凸台 + 通孔"—— 它们是两种特征布局，图纸本身分不出来（§3 原则二：
    歧义不提前消解）。这里每个半径各报一条，把"这是哪种"留给求解层与
    待确认项。曾经的做法是只取最大半径（文档里写"外径取最大、内径取最小"
    但代码只做了前半句），后果实测：flange_d80 的 Ø40 中心孔**整个消失**，
    体积从 85,652 涨到 115,811（+35%）。
    """
    out: list[Correspondence] = []
    idx = _index(d)
    for v in d.views:
        if v.id not in frames or v.bbox is None:
            continue
        f = frames[v.id]
        merged: dict[tuple[int, int], list[tuple[EvidenceRef, Point3, float]]] = {}
        for handle, center, r in _circles_of(d, idx, v):
            key = (round(center.x / MATCH_TOL), round(center.y / MATCH_TOL))
            merged.setdefault(key, []).append((handle, center, r))
        for group in merged.values():
            group.sort(key=lambda it: -it[2])          # 半径降序
            # 同半径的多条圆边 = 同一条圆边被重复画了（重合图元）⇒ 并成一条；
            # **半径不同**的才是"多条同心圆边"，各报一条（见 docstring）
            uniq: list[list[tuple[EvidenceRef, Point2, float]]] = []
            for item in group:
                if uniq and abs(uniq[-1][-1][2] - item[2]) <= MATCH_TOL:
                    uniq[-1].append(item)
                else:
                    uniq.append([item])
            refs0 = [(v.id, h) for h, _, _ in group]
            ev = tuple(h for h, _, _ in group)
            if len(uniq) > 1:
                qs.add(Question(
                    OpenQuestion.AMBIGUOUS_FEATURE,
                    f"{v.id} 同一圆心上有 {len(uniq)} 条同心圆边（"
                    + " / ".join(f"r{g[0][2]:g}" for g in uniq)
                    + "）—— 是沉孔/倒角/台阶（一根轴上两个直径），"
                    "还是同一面上的两个独立圆边（如盘+中心孔）？"
                    "每条圆边各建一个特征，交由约束裁剪",
                    view=v.id, evidence=ev,
                    candidates=("step", "counterbore", "independent"),
                ))
            origin = f.to_model(group[0][1].x, group[0][1].y)
            dirs = {"x": Vector3(1, 0, 0), "y": Vector3(0, 1, 0),
                    "z": Vector3(0, 0, 1)}
            for same in uniq:
                out.append(_circle_to_cylinder(
                    d, idx, v, f, frames, qs, tuple(h for h, _, _ in same),
                    same[0][2], origin, dirs[f.p_axis], refs0))
    return out


def _circle_to_cylinder(d: Drawing, idx, v: View, f: ViewFrame, frames: dict,
                        qs: QuestionList, handles: tuple, r: float,
                        origin: Point3, axis_dir: Vector3,
                        refs0: list[tuple[str, EvidenceRef]]
                        ) -> Correspondence:
    """一条圆边 ⇒ 一个圆柱的对应（长度与"孔/凸台"靠正交视图的轮廓对补）。

    ``handles`` 是这条圆边的全部图元（重合图元会有多条），``refs0`` 是同一
    圆心上的**全部**圆边 —— 它们共同证明"这根轴在这里"。

    圆柱轴向 = ``f.p_axis``。在别的视图 ``w`` 里，它要么画在 ``w`` 的横向、
    要么画在 ``w`` 的纵向 —— 两种情况下的"垂直方向"分别映射到 ``w.v_axis`` /
    ``w.u_axis``，**必须过 frame 换算**才能和模型坐标比（直接拿图纸坐标比
    模型坐标是错的，这里错过一次）。
    """
    handle = handles[0]
    marker = f"circle:{v.id}"
    radius_claim = Claim(r, marker, Tier.PROJECTION, evidence=handles)
    hint = CylinderHint(Axis3(origin, axis_dir, radius_claim), r,
                        radius_method=marker)
    refs: list[tuple[str, EvidenceRef]] = list(refs0)
    best: tuple[_Pair, str, float] | None = None
    best_vis: _Pair | None = None
    best_hid: _Pair | None = None
    for w in d.views:
        if w.id == v.id or w.id not in frames or w.bbox is None:
            continue
        wf = frames[w.id]
        if wf.p_axis == f.p_axis:
            continue                # 同向视图给不出正交信息
        if wf.u_axis == f.p_axis:
            along, perp_axis = "h", wf.v_axis
        elif wf.v_axis == f.p_axis:
            along, perp_axis = "v", wf.u_axis
        else:
            continue
        want = {"x": origin.x, "y": origin.y, "z": origin.z}[perp_axis]
        for pr in _parallel_line_pairs(idx, w, along, 2 * r):
            got = (wf.u_to_model(pr.perp_mid) if perp_axis == wf.u_axis
                   else wf.v_to_model(pr.perp_mid))
            if abs(got - want) > MATCH_TOL:
                continue
            if best is None or pr.length > best[0].length:
                best = (pr, w.id, got)
            if pr.visible:
                if best_vis is None or pr.length > best_vis.length:
                    best_vis = pr
            elif best_hid is None or pr.length > best_hid.length:
                best_hid = pr
    if best is not None:
        pr, wid, _ = best
        refs += [(wid, pr.h1), (wid, pr.h2)]
        solid: bool | None = pr.visible
        # 实/虚轮廓冲突：同一条圆柱轮廓在图上既有实线对又有虚线对、两者
        # 量级又可比时，"实线=凸台、虚线=孔"这条判据在这张图上失效 ——
        # 实线对很可能是**另一条棱**恰在该位置的重合投影（实测 bracket：
        # r6/r15.7 的实线对在真值 HLR 里确有一条真实可见边与之重合，是
        # 图纸本身的真歧义，不是出图伪影）。此时不许替用户拍板（§3 原则
        # 二），留 solid=None 由识别层记 GUESS、交求解层/后置消解。
        # 判据取"短的 ≥ 长的一半"：实测冲突样本都落在 0.5 附近（11/22、
        # 10.25/20.5、14/28、5/10、5.05/10.10），而真正的单侧证据比值
        # 都远小于 0.5（bracket r20 为 4.54/19、PF60K r30 为 9.87/56.5）。
        # ⚠️ 已知抓不到的一类：只有实线对、虚线对被**可见优先去重**吃掉的
        # 样本（bracket r12：3.00 长可见对，实为薄壁缘的棱，孔的壁虚线与之
        # 重合后没进图）⇒ 仍读成薄凸台。要治它得靠"HLR 重合消影"推理，
        # 不是长度判据能做的。
        if (best_vis is not None and best_hid is not None
                and min(best_vis.length, best_hid.length)
                >= 0.5 * max(best_vis.length, best_hid.length)):
            solid = None
            qs.add(Question(
                OpenQuestion.AMBIGUOUS_FEATURE,
                f"{v.id} 的 r{r:g} 圆在正交视图里既有实线轮廓对（最长 "
                f"{best_vis.length:.2f}）又有虚线轮廓对（最长 "
                f"{best_hid.length:.2f}），量级可比 —— 实线对可能是另一条"
                "棱的重合投影，孔/凸台未定",
                view=v.id,
                evidence=(handle, best_vis.h1, best_vis.h2,
                          best_hid.h1, best_hid.h2),
                candidates=("hole", "boss"),
            ))
        hint = CylinderHint(hint.axis, r, length=pr.length, solid=solid,
                            radius_method=marker, profile_method=f"outline:{wid}")
        return Correspondence(
            CorrKind.FEATURE, tuple(refs),
            Claim(hint, f"corr:circle+outline({v.id}+{wid})", Tier.PROJECTION,
                  evidence=tuple(h for _, h in refs)),
            note=f"r{r:g} 圆柱，长 {pr.length:.2f}，"
                 + ("孔/凸台未定（实/虚轮廓证据相当）" if solid is None
                    else ("凸台（轮廓实线）" if solid else "孔（轮廓虚线）")),
        )
    qs.add(Question(
        OpenQuestion.AMBIGUOUS_FEATURE,
        f"{v.id} 的 r{r:g} 圆在正交视图里找不到间距 2r 的轮廓对 —— "
        "无法确定它是孔还是凸台、也不知道轴向长度",
        view=v.id, evidence=(handle,),
        candidates=("hole", "boss"),
    ))
    return Correspondence(
        CorrKind.FEATURE, tuple(refs),
        Claim(hint, f"corr:circle({v.id})", Tier.PROJECTION,
              evidence=(handle,)),
        note=f"r{r:g} 圆柱，轴沿 {f.p_axis.upper()}；"
             "正交视图里没找到匹配的轮廓对（长度与孔/凸台未定）",
    )


# ---- 5) 特征点 ⇒ 3D 点（有界版） ----

def _key_points(idx: dict[str, Evidence], v: View
                ) -> list[tuple[EvidenceRef, Point2, str]]:
    """视图里**有辨识度**的点：圆心/弧心（去重）。

    **刻意不收包围盒极值点**：一个视图的每条边上都有落在极值上的端点，
    两视图配对时它们会两两组合出成百上千条"交点"（实测 400 条上限瞬间打满，
    全是 (2.0, y, 2.0) 这样的垃圾）。圆心不一样 —— 它是**形状特征**的位置，
    两个视图里的圆心若投影交会，那是同一个孔的锚点。
    端点配对要靠拓扑（同一个环上的顶点）而不是坐标巧合，留给求解器。
    """
    out: list[tuple[EvidenceRef, Point2, str]] = []
    seen: set[tuple[int, int]] = set()
    for h in v.evidence:
        e = idx.get(h)
        if e is None or e.kind != Kind.EDGE:
            continue
        g = e.geom
        if not isinstance(g, (Circle2, Arc2)):
            continue
        key = (round(g.center.x / MATCH_TOL), round(g.center.y / MATCH_TOL))
        if key in seen:
            continue                  # 同心圆（沉孔/倒角）只取一次
        seen.add(key)
        out.append((e.handle, g.center, "center"))
    return out


def points_from_vertices(d: Drawing, frames: dict[str, ViewFrame],
                         qs: QuestionList, cap: int = 400
                         ) -> list[Correspondence]:
    """端点/圆心 ⇒ 3D 点（**投影射线求交**）。

    有界版本：只收"有辨识度的点"（见 ``_key_points``），且只在
    **轴互补**的两个视图之间配对（主 (x,z) × 俯 (x,y) ⇒ 补出 y）。
    全量两两配对是阶段 3 求解器的活。

    产出用于：给识别器一个确定的 3D 定位锚（"这个凸台的顶面圆心在
    (121.89, 0, 44)"），也是 `verify/predict` 反查的落点。
    """
    out: list[Correspondence] = []
    idx = _index(d)
    by_id = {v.id: v for v in d.views}
    ids = [v.id for v in d.views if v.id in frames and v.bbox is not None]

    def val(f: ViewFrame, p: Point2, axis: str) -> float | None:
        """点在某个模型轴上的取值（该轴不在本视图可见范围内则为 None）。"""
        if axis == f.u_axis:
            return f.u_to_model(p.x)
        if axis == f.v_axis:
            return f.v_to_model(p.y)
        return None

    for i, va in enumerate(ids):
        if len(out) >= cap:
            break
        pts_a = _key_points(idx, by_id[va])
        if not pts_a:
            continue
        fa = frames[va]
        for vb in ids[i + 1:]:
            fb = frames[vb]
            if fb.p_axis == fa.p_axis:
                continue            # 投影方向相同 ⇒ 两视图给同样的两维，交不出第三维
            # 两视图共有且都看得见的轴（3 轴里排除两个投影方向后剩下的那个）
            shared = next(a for a in _ALL_AXES
                          if a not in (fa.p_axis, fb.p_axis))
            # 桶键用**共见轴**的取值：只有它相近的点才可能对应
            buckets: dict[int, list[tuple[EvidenceRef, Point2, str]]] = {}
            for h, p, kind in pts_a:
                v = val(fa, p, shared)
                if v is not None:
                    buckets.setdefault(round(v / MATCH_TOL), []).append((h, p, kind))
            for h2, p2, k2 in _key_points(idx, by_id[vb]):
                v_shared = val(fb, p2, shared)
                if v_shared is None:
                    continue
                b0 = round(v_shared / MATCH_TOL)
                for b in (b0 - 1, b0, b0 + 1):
                    for h1, p1, k1 in buckets.get(b, []):
                        if abs(val(fa, p1, shared) - v_shared) > MATCH_TOL:
                            continue
                        # A 补 B 看不见的那一维，B 补 A 看不见的那一维
                        coords: dict[str, float] = {shared: v_shared}
                        for axis, src, pt2 in ((fb.p_axis, fa, p1),
                                               (fa.p_axis, fb, p2)):
                            got = val(src, pt2, axis)
                            if got is None:
                                break
                            coords[axis] = got
                        if len(coords) != 3:
                            continue
                        pt = Point3(coords["x"], coords["y"], coords["z"])
                        out.append(Correspondence(
                            CorrKind.POINT, ((va, h1), (vb, h2)),
                            Claim(pt, f"corr:projection({va}({k1})+{vb}({k2}))",
                                  Tier.PROJECTION, evidence=(h1, h2)),
                            note=f"两视图投影交会 ⇒ 3D 点 "
                                 f"({pt.x:.2f},{pt.y:.2f},{pt.z:.2f})",
                        ))
                        if len(out) >= cap:
                            return out
    return out


# ---- 主入口 ----

def build_correspondence(d: Drawing, qs: QuestionList | None = None,
                         broken: dict[str, tuple[str, ...]] | None = None
                         ) -> CorrespondenceResult:
    """算出图纸里的全部跨视图对应。副作用：无（frames 记在返回值里）。

    ``broken`` 是约定层给出的断裂视图（``{view_id: ("u"/"v", …)}``，
    见 ``conventions.linetype``）—— 断裂视图沿某方向的图面坐标**整条不可用**，
    必须在这里就挡掉，否则后面每一条对应都会静默用错坐标。
    """
    questions = qs if qs is not None else QuestionList()
    frames, questions = solve_frames(d, questions, broken=broken)
    res = CorrespondenceResult(frames=frames, questions=questions)
    if not frames:
        return res

    res.correspondences.extend(axes_from_sections(d, frames, questions))
    res.correspondences.extend(axes_from_centerlines(d, frames, questions))
    res.correspondences.extend(cylinders_from_circles(d, frames, questions))
    res.correspondences.extend(points_from_vertices(d, frames, questions))

    if not res.axes():
        questions.add(Question(
            OpenQuestion.MISSING_SECTION_POS,
            "图纸里没有任何可定位的轴线（无中心线、无带半径的剖面标题）—— "
            "特征的三维定位只能靠轮廓投影，误差会显著变大",
        ))
    return res


def describe(res: CorrespondenceResult) -> str:
    """人读的对应关系报告。"""
    lines: list[str] = []
    if res.frames:
        lines.append("视图坐标系（图纸 → 模型，纯平移）")
        for f in res.frames.values():
            lines.append(f"  {f}")
    lines.append("")
    for kind, title in ((CorrKind.AXIS, "轴线/位置对应"),
                        (CorrKind.FEATURE, "圆柱（圆 + 轮廓）"),
                        (CorrKind.POINT, "3D 点（投影交会）")):
        items = res.by_kind(kind)
        lines.append(f"{title}（{len(items)} 条）")
        if not items:
            lines.append("  （无）")
        for c in items[:24]:
            lines.append(f"  {c}")
        if len(items) > 24:
            lines.append(f"  … 另有 {len(items) - 24} 条")
        lines.append("")
    return "\n".join(lines)
