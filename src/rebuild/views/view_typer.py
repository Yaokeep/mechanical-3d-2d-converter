# -*- coding: utf-8 -*-
"""视图定性 —— 每个视图是主/俯/左/剖（ARCHITECTURE §4.2、§6.1）。

## 两条依据，强弱分明

1. **图上明写的标签**（tier=ANNOTATED）—— 最可信，直接采信。
2. **布局对齐关系**（tier=CONVENTION / PRIOR）—— 无标签时才用。

## 无标签时的几何规则（已用带标签的图纸反验）

制图约定：**同一轴向的两个视图会对齐**。于是——

- **X 区间重叠** ⇒ 两视图垂直堆叠 ⇒ 共享图纸横向的那根轴
- **Y 区间重叠** ⇒ 两视图左右并排 ⇒ 共享图纸竖向的那根轴
- **同时有一个"列伙伴"和一个"行伙伴"的视图 = 主视图**；
  它的列伙伴是俯/仰视图，行伙伴是左/右侧视图。

这条规则**与投影制无关**（只用到"对齐"这一公约），故可以在不知道
第一角/第三角的情况下先把主视图定下来。实测：无标签的
``bracket_angker_三视图_v4.dxf`` 与带中文标签的剖面图纸布局一致，
推出的主/俯/左与标签逐个吻合。

## 两处歧义的**同一个根**

- **列伙伴在上还是下**：第一角俯视图在主视图**下**方，第三角在**上**方。
- **行伙伴在左还是右**：第一角左视图在主视图**右**方，第三角右视图在**右**方。

两处都由**投影制**决定，而判错投影制会让整个零件镜像（ARCHITECTURE §4.2）。
所以本模块**只从标题栏明写的画法标志读投影制**，绝不从布局反推 ——
本仓库的出图脚本恰恰是非标准布局（实测：俯视图在主视图**上方**，
左视图又在主视图**右方**，两种画法都解释不了）。判不出就如实保留备选、
报一条 ``UNKNOWN_PROJECTION``：用户回答一次，两处歧义同时消解。

## 俯/仰 与 主/后 是真歧义，不是没做

俯视图与仰视图、主视图与后视图各自只差一次镜像，**同一张图纸无论怎么算
都判不出**（要靠第二张图纸或三维先验）。故取位置推算的值 + 另一个作备选，
让 gate 决定是否降级 —— 而不是静默当俯视图用。
"""
from __future__ import annotations

from ..evidence.model import Drawing, ProjectionMethod, View, ViewType
from ..evidence.text_parser import CutSpec, TextKind
from ..model.claim import Claim, Tier
from ..model.geom2d import BBox2
from ..model.questions import OpenQuestion, Question, QuestionList

#: 区间重叠容差（mm）—— 视图是精确对齐的，给一点余量防浮点比较
ALIGN_TOL = 0.5


def _overlap(a_lo: float, a_hi: float, b_lo: float, b_hi: float) -> bool:
    return min(a_hi, b_hi) - max(a_lo, b_lo) > ALIGN_TOL


def _partners(views: list[View]) -> tuple[dict[str, list[View]], dict[str, list[View]]]:
    """算出每个视图的列伙伴/行伙伴。

    列伙伴 = X 区间重叠（垂直堆叠）；行伙伴 = Y 区间重叠（左右并排）。
    """
    cols: dict[str, list[View]] = {v.id: [] for v in views}
    rows: dict[str, list[View]] = {v.id: [] for v in views}
    for i, a in enumerate(views):
        if a.bbox is None:
            continue
        for b in views[i + 1:]:
            if b.bbox is None:
                continue
            if _overlap(a.bbox.xmin, a.bbox.xmax, b.bbox.xmin, b.bbox.xmax):
                cols[a.id].append(b)
                cols[b.id].append(a)
            if _overlap(a.bbox.ymin, a.bbox.ymax, b.bbox.ymin, b.bbox.ymax):
                rows[a.id].append(b)
                rows[b.id].append(a)
    return cols, rows


def _y_center(b: BBox2) -> float:
    return (b.ymin + b.ymax) / 2.0


def _x_center(b: BBox2) -> float:
    return (b.xmin + b.xmax) / 2.0


def _vert_choice(above: bool, method: ProjectionMethod | None
                 ) -> tuple[ViewType, ViewType]:
    """列伙伴（俯/仰）的取舍 → (采用值, 备选值)。

    标准：第一角俯视图在主视图**下**方，第三角在**上**方。
    投影制未知时默认"俯视图在上"—— 这是**本仓库出图脚本的布局**
    （`bracket_angker_图纸_20260922_剖面图.dxf` 里三个视图都带中文标签，
    实测俯视图就在主视图上方），属于项目先验而非通用约定，故 tier=PRIOR。
    """
    third = method == ProjectionMethod.THIRD_ANGLE
    if above:
        return (ViewType.TOP, ViewType.BOTTOM) if third or method is None \
            else (ViewType.BOTTOM, ViewType.TOP)
    return (ViewType.BOTTOM, ViewType.TOP) if third or method is None \
        else (ViewType.TOP, ViewType.BOTTOM)


def _horiz_choice(right: bool, method: ProjectionMethod | None
                  ) -> tuple[ViewType, ViewType]:
    """行伙伴（左/右）的取舍 → (采用值, 备选值)。

    标准：第一角左视图在主视图**右**方，第三角右视图在**右**方。
    投影制未知时默认"第一角"—— 依据是本仓库带标签的图纸把主视图**右**侧的
    视图标成"左视图"，同样是项目先验，tier=PRIOR。
    """
    third = method == ProjectionMethod.THIRD_ANGLE
    if right:
        return (ViewType.RIGHT, ViewType.LEFT) if third \
            else (ViewType.LEFT, ViewType.RIGHT)
    return (ViewType.LEFT, ViewType.RIGHT) if third \
        else (ViewType.RIGHT, ViewType.LEFT)


# ---- 各条依据 ----

def _claim_from_label(v: View, t) -> Claim[ViewType] | None:
    """标签直接给出的类型。SIDE 只说了"是个侧视图"，左右未定 ⇒ 返回 None。"""
    if not t.view_type or t.view_type == ViewType.SIDE:
        return None
    return Claim(ViewType(t.view_type), "label:view_label",
                 Tier.ANNOTATED, evidence=(t.handle,))


def _side_label_of(d: Drawing, v: View):
    """本视图的标签若只写了"侧视图"，返回它（用来给位置推断补一个更硬的依据）。"""
    if v.label_handle is None:
        return None
    t = d.text_by_handle(v.label_handle)
    if t is not None and t.view_type == ViewType.SIDE:
        return t
    return None


# ---- 主入口 ----

def type_views(d: Drawing, qs: QuestionList | None = None) -> QuestionList:
    """给 ``d.views`` 逐个定性，并把欠定项写进返回的 QuestionList。

    副作用：填 ``View.type``；若有投影制标志，也填 ``View.method``。
    """
    questions = qs if qs is not None else QuestionList()

    # ---- 0) 投影制：只认标题栏明写的符号 ----
    method: ProjectionMethod | None = None
    method_ev = ()
    for t in d.texts:
        if t.kind == TextKind.PROJECTION and t.projection:
            method = ProjectionMethod(t.projection)
            method_ev = (t.handle,)
            break
    if method is None:
        questions.add(Question(
            OpenQuestion.UNKNOWN_PROJECTION,
            "图纸未标注第一角/第三角画法 —— 左/右侧视与俯/仰视的取舍只能猜测",
        ))
    else:
        for v in d.views:
            v.method = Claim(method, "title_block:projection",
                             Tier.ANNOTATED, method_ev)

    # ---- 1) 标签与剖面标题（ANNOTATED，最硬） ----
    for v in d.views:
        if v.cut is not None:
            # 剖视图：切平面来自剖面标题文字，属图上明标
            v.type = Claim(ViewType.SECTION, "note:section_title",
                           Tier.ANNOTATED, tuple(v.annotations[:1]))
            continue
        if v.label_handle is None:
            continue
        t = d.text_by_handle(v.label_handle)
        if t is None:
            continue
        claim = _claim_from_label(v, t)
        if claim is not None:
            v.type = claim

    # ---- 2) 布局关系：给还没有定性的视图（含只写了"侧视图"的）定类型 ----
    _type_by_layout(d, questions, method)

    # ---- 3) 兜底：还是没定性的一律报出来，绝不静默当成主视图 ----
    for v in d.views:
        if v.resolved_type is None and v.type.value == ViewType.UNKNOWN:
            questions.add(Question(
                OpenQuestion.UNKNOWN_VIEW, "视图类型未能判定",
                view=v.id, evidence=tuple(v.evidence[:1]),
                candidates=("front", "top", "left", "right", "section"),
            ))
    return questions


def _type_by_layout(d: Drawing, qs: QuestionList,
                    method: ProjectionMethod | None) -> None:
    """按对齐关系定位：先找主视图，再把未定性的视图相对它定位。

    **必须在全量视图上算对齐关系**（含已由标签定性的），
    否则"已知主视图 + 未定性侧视图"这种最常见的情形会因为
    传入的列表里没有主视图而判不出来。
    """
    views = [v for v in d.views if v.bbox is not None]
    if not views:
        return
    untyped = [v for v in d.views if v.resolved_type is None]
    if not untyped:
        return

    cols, rows = _partners(views)

    # 主视图：优先用已定性的；否则用"同时有列伙伴和行伙伴"者
    front = next((v for v in views if v.resolved_type == ViewType.FRONT), None)
    if front is None:
        cands = [v for v in untyped if cols[v.id] and rows[v.id]]
        if len(cands) == 1:
            front = cands[0]
            front.type = Claim(ViewType.FRONT, "layout:both_partners",
                               Tier.CONVENTION,
                               evidence=tuple(front.evidence[:1]))

    if front is None:
        _type_without_front(views, untyped, cols, qs)
        return

    assert front.bbox is not None
    for v in untyped:
        if v is front or v.bbox is None:
            continue
        ref = tuple(v.evidence[:1])
        # 只写了"侧视图"的标签是 ANNOTATED 依据 —— 位置推断据此升一档可信度
        side_label = _side_label_of(d, v)
        if side_label is not None:
            ref = (side_label.handle,)

        if v in cols[front.id]:
            # 列伙伴 = 俯/仰视图。上下由投影制决定：第一角俯在下、第三角俯在上。
            above = _y_center(v.bbox) > _y_center(front.bbox)
            val, alt = _vert_choice(above, method)
            if method is not None:
                v.type = Claim(val, f"convention:{method.value}",
                               Tier.CONVENTION, ref)
            else:
                v.type = Claim(val, "prior:layout:above_front", Tier.PRIOR, ref,
                               alternatives=(alt,))
                qs.add(Question(
                    OpenQuestion.UNKNOWN_PROJECTION,
                    f"{v.id} 在主视图 {front.id} 的"
                    f"{'上' if above else '下'}方：第一角应为"
                    f"{alt.value}、第三角应为{val.value} —— 俯/仰只差一次镜像",
                    view=v.id, evidence=ref,
                    candidates=(val.value, alt.value),
                ))
        elif v in rows[front.id]:
            # 行伙伴 = 左/右侧视图 —— 判错整件沿 X 镜像（§4.2）
            right = _x_center(v.bbox) > _x_center(front.bbox)
            val, alt = _horiz_choice(right, method)
            if method is not None:
                v.type = Claim(val, f"convention:{method.value}",
                               Tier.CONVENTION, ref)
            else:
                v.type = Claim(val, "prior:layout:side_position",
                               Tier.PRIOR, ref, alternatives=(alt,))
                qs.add(Question(
                    OpenQuestion.UNKNOWN_PROJECTION,
                    f"{v.id} 在主视图 {front.id} 的"
                    f"{'右' if right else '左'}侧：第一角应为"
                    f"{_horiz_choice(right, ProjectionMethod.FIRST_ANGLE)[0].value}"
                    f"、第三角应为"
                    f"{_horiz_choice(right, ProjectionMethod.THIRD_ANGLE)[0].value}",
                    view=v.id, evidence=ref,
                    candidates=(val.value, alt.value),
                ))
        else:
            qs.add(Question(
                OpenQuestion.UNKNOWN_VIEW,
                f"{v.id} 与主视图 {front.id} 既不同列也不同行，类型未定",
                view=v.id, evidence=ref, candidates=("auxiliary", "detail"),
            ))


def _type_without_front(views: list[View], untyped: list[View],
                        cols: dict[str, list[View]], qs: QuestionList) -> None:
    """找不到主视图时的退路：只有一对共享宽度 ⇒ 按"下者为主"推。

    这条是**纯猜**（tier=PRIOR），因为主/后视图与俯/仰视图各自同宽，
    单靠宽度分不出谁是谁。
    """
    pairs = [(a, b) for i, a in enumerate(views) for b in views[i + 1:]
             if b in cols[a.id]]
    if len(pairs) == 1:
        a, b = pairs[0]
        assert a.bbox is not None and b.bbox is not None
        lower, upper = ((a, b) if _y_center(a.bbox) < _y_center(b.bbox) else (b, a))
        if lower in untyped:
            lower.type = Claim(ViewType.FRONT, "prior:layout:shared_width_pair",
                               Tier.PRIOR, evidence=tuple(lower.evidence[:1]))
        if upper in untyped:
            upper.type = Claim(ViewType.TOP, "prior:layout:shared_width_pair",
                               Tier.PRIOR, evidence=tuple(upper.evidence[:1]),
                               alternatives=(ViewType.BOTTOM,))
        for v in (lower, upper):
            qs.add(Question(
                OpenQuestion.AMBIGUOUS_VIEW,
                f"缺主视图锚点：{lower.id} 与 {upper.id} 共享宽度，"
                f"按'下者为主、上者为俯'推定 —— 主/后、俯/仰都无法排除",
                view=v.id, evidence=tuple(v.evidence[:1]),
                candidates=("front", "rear", "top", "bottom"),
            ))
        return
    for v in untyped:
        qs.add(Question(
            OpenQuestion.UNKNOWN_VIEW,
            "布局不足以判定视图类型（缺对齐关系）",
            view=v.id, evidence=tuple(v.evidence[:1]),
            candidates=("front", "top", "left", "right"),
        ))


def describe_views(d: Drawing) -> str:
    """视图一览（人读报告用）。"""
    lines: list[str] = []
    for v in d.views:
        b = v.bbox
        box = (f"({b.xmin:8.2f},{b.ymin:8.2f})-({b.xmax:8.2f},{b.ymax:8.2f})"
               if b is not None else "（无包围盒）")
        size = f"[{b.xmax - b.xmin:7.2f} x {b.ymax - b.ymin:7.2f}]" if b else ""
        lines.append(f"  {v.id}  {str(v.type):30} {box} {size}")
        lines.append(f"      几何 {len(v.evidence):5d} 项   "
                     f"标注 {len(v.annotations):3d} 项"
                     + (f"   投影制 {v.method.value}"
                        if v.method is not None else ""))
        t = d.text_by_handle(v.label_handle) if v.label_handle else None
        if t is not None:
            lines.append(f"      标签 {t.text!r}  依据 {t.handle}")
        cut = v.cut
        if isinstance(cut, CutSpec):
            loc = (f"{cut.cut_axis}={cut.cut_pos:g}" if cut.is_located
                   else "位置未知")
            lines.append(f"      剖面 {cut.label} {cut.kind or ''} 切平面 {loc}"
                         + (f"  r={cut.radius:g}" if cut.radius else ""))
    return "\n".join(lines) if lines else "  （未分离出视图）"
