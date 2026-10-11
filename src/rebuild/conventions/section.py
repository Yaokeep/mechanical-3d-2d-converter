# -*- coding: utf-8 -*-
"""剖切约定 —— 全剖 / 半剖 / 局部剖 / 旋转剖 / 阶梯剖。

## 这条规则拦住的错，是已经发生过的

旧管线 v0.6.15 起把剖视图当"按真实截面裁假材料"的棱柱用。它对**全剖**
成立 —— 切平面过轴、整幅视图都是剖切材料，截出来的面就是真实截面。
对**半剖/局部剖/旋转剖/阶梯剖**全都不成立：

- 半剖：只有一半是剖切材料，另一半是**外形视图**。按整幅裁 ⇒ 把真材料
  当成假材料删掉（正是 CLAUDE.md 记的"任何窗口的全长拉伸都误裁真材料"）
- 局部剖：剖切范围由波浪线界定，范围外的部分是外形
- 旋转剖 / 阶梯剖 / 复合剖：**多个切平面**，单平面截面棱柱在几何上就
  不是这个零件 —— 不是精度问题，是模型形状错了

所以本规则的产出是**能不能用**（``SectionScope.usable_as_prism``）以及
一条说清理由的 OpenQuestion。判不出来时按"不能用"处理：宁可少裁，
不可错裁（错裁是净删真材料，方向性地把模型做小）。
"""
from __future__ import annotations

from dataclasses import dataclass

from ..evidence.model import Kind, Role
from ..evidence.text_parser import CutSpec, TextKind
from ..model.claim import Claim, Tier
from ..model.geom2d import BBox2
from ..model.ids import EvidenceRef
from ..model.questions import OpenQuestion, Question
from .registry import (
    Convention, ConvKind, RuleCtx, by_handle_index, cluster_boxes, register,
    union_boxes,
)

#: 图上写的剖切种类 → 适用范围。**整词包含**匹配，长的先判
_FULL = ("纵向全剖", "横向全剖", "全剖", "横剖", "纵剖", "剖视", "剖面")
_HALF = ("半剖",)
_LOCAL = ("局部剖",)
_MULTI = ("旋转剖", "阶梯剖", "复合剖", "斜剖")


@dataclass(frozen=True)
class SectionScope:
    """一个剖视图的适用范围（``ConvKind.SECTION`` 的 value）。"""

    label: str
    kind: str                 # 图上写的种类原文（抽到的关键词）
    scope: str                # full / half / local / multi / unknown
    usable_as_prism: bool     # 能否当"单平面截面棱柱"用于裁材料
    reason: str = ""


def _classify(kind: str) -> tuple[str, bool, str]:
    if any(k in kind for k in _MULTI):
        return ("multi", False, "多个切平面，单平面截面棱柱在几何上就不是这个零件")
    if any(k in kind for k in _LOCAL):
        return ("local", False, "剖切范围由波浪线界定，范围外是外形视图")
    if any(k in kind for k in _HALF):
        return ("half", False, "只有一半是剖切材料，另一半是外形视图")
    if any(k in kind for k in _FULL):
        return ("full", True, "整幅视图都是剖切材料，截面即真实截面")
    return ("unknown", False, "剖切种类未识别")


def _coverage_ratio(v, boxes: list[BBox2]) -> float | None:
    """剖面材料沿图面的覆盖比 —— 全剖 ≈1，半剖/局部剖明显 <1。

    取**横向（u）优先**：全剖的截面即使内部有空洞（壁厚件），剖面线仍
    横跨整个截面宽度；面积比会把空洞当成"没剖到"而误判局部剖。
    横向不足 0.9 时退回纵向（横向全剖、纵向半剖的罕见画法），取较大者。
    """
    if not boxes or v.bbox is None:
        return None
    total = union_boxes(boxes)
    w = total.width / v.bbox.width if v.bbox.width > 0 else 0.0
    if w >= 0.9:
        return w
    h = total.height / v.bbox.height if v.bbox.height > 0 else 0.0
    return max(w, h)


@register("section.scope")
def scope(ctx: RuleCtx) -> list[Convention]:
    """剖切种类 ⇒ 截面材料的适用范围（以及能不能当棱柱用）。

    标题**明写**种类（"横剖 x=…"）时只认标题；标题没写（如「c 向」式
    标题，YZYX C—C）时从剖面线覆盖范围做**几何推断**：剖面线横跨整个
    视图 ⇒ 全剖，只盖一部分 ⇒ 局部剖（不可作截面棱柱）。
    """
    titles = {t.handle: t for t in ctx.d.texts
              if t.kind == TextKind.SECTION_TITLE and t.cut is not None}
    out: list[Convention] = []
    for v in ctx.d.views:
        cut = v.cut
        if not isinstance(cut, CutSpec):
            continue
        kind = cut.kind or ""
        sc, usable, reason = _classify(kind)
        refs: tuple[EvidenceRef, ...] = ()
        for h in v.annotations:
            if h in titles and titles[h].cut is not None \
                    and titles[h].cut.label == cut.label:
                refs = (h,)
                break
        if sc == "unknown":
            # 标题没写种类 ⇒ 从剖面线覆盖范围几何推断（tier 保持 GUESS）
            _, boxes, _ = _material_boxes(ctx, v)
            ratio = _coverage_ratio(v, boxes)
            if ratio is None:
                reason = "剖切种类未识别，且图上没有剖面线可做几何推断"
            elif ratio >= 0.9:
                sc, usable = "full", True
                reason = (f"标题没写剖切种类，剖面线覆盖 {ratio:.0%}"
                          " ⇒ 几何推断为全剖")
            else:
                sc, usable = "local", False
                reason = (f"标题没写剖切种类，剖面线只覆盖 {ratio:.0%}"
                          " ⇒ 几何推断为局部剖")
        if sc == "unknown":
            ctx.qs.add(Question(
                OpenQuestion.AMBIGUOUS_FEATURE,
                f"{v.id}（{cut.label}）的剖切种类读不出来（原标题「{cut.raw}」）—— "
                "按「不能用它裁材料」处理：错裁是净删真材料，方向性地把模型做小",
                view=v.id, evidence=refs,
            ))
        elif not usable:
            ctx.qs.add(Question(
                OpenQuestion.AMBIGUOUS_FEATURE,
                f"{v.id}（{cut.label}）是「{kind or '几何推断的局部剖'}」：{reason} ⇒ "
                "**不得**按整幅截面拉伸裁材料（会误删真材料）",
                view=v.id, evidence=refs,
            ))
        info = SectionScope(label=cut.label, kind=kind, scope=sc,
                            usable_as_prism=usable, reason=reason)
        tier = Tier.CONVENTION if kind else Tier.GUESS
        out.append(Convention(
            rule="section.scope", kind=ConvKind.SECTION, view=v.id, value=info,
            claim=Claim(info, "convention:section_kind", tier, evidence=refs),
            note=f"「{kind or '未写种类'}」⇒ 适用范围 {sc}"
                 f"{'，可作截面棱柱' if usable else '，不可作截面棱柱'}：{reason}",
            evidence=refs,
        ))
    return out


@dataclass(frozen=True)
class MaterialPatch:
    """一处被剖到的材料（``ConvKind.MATERIAL`` 的 value）。

    ``zones`` 是剖面填充按邻近聚出的**分区**（局部剖的"哪几块是材料"），
    并集 bbox 之外的覆盖信息都在这里；全剖通常只有 1 个分区。
    """

    count: int
    bbox: BBox2 | None = None
    pattern: str = ""
    zones: tuple[BBox2, ...] = ()


#: 分区聚类的邻近间隙：小于它算同一片剖面填充。
#: YZYX C—C 实测剖面线间距 8.84/6.25、三区相互间隔 >15 ⇒ 15 能分出区、
#: 又不把同区内的相邻剖面线拆散
_ZONE_GAP = 15.0


def _material_boxes(ctx: RuleCtx, v) -> tuple[list[EvidenceRef], list[BBox2], str]:
    """一个视图里的全部剖面材料信号（HATCH 填充 + 画成 LINE 的剖面线）。

    两条规则（material / scope）共用：材料信号有两种画法 —— 真 HATCH 实体
    （bracket）与 `剖面线` 图层的 LINE（YZYX C—C），缺一即漏读。
    """
    idx = by_handle_index(ctx.d)
    refs: list[EvidenceRef] = []
    boxes: list[BBox2] = []
    pattern = ""
    for h in v.evidence:
        e = idx.get(h)
        if e is None:
            continue
        if e.kind == Kind.HATCH or e.role.value == Role.HATCH_LINES:
            refs.append(e.handle)
            boxes.append(e.exact_bbox)
            pattern = pattern or (e.pattern or "lines")
    return refs, boxes, pattern


@register("section.material")
def material(ctx: RuleCtx) -> list[Convention]:
    """HATCH ⇒ 这块是材料（不是空洞）。

    剖面线是图纸里**唯一**直接说"这里是材料"的符号：轮廓说"这里有边界"，
    剖面线说"边界之内是实心"。两条信息合起来才有"材料区"。
    """
    out: list[Convention] = []
    for v in ctx.d.views:
        refs, boxes, pattern = _material_boxes(ctx, v)
        if not refs:
            if isinstance(v.cut, CutSpec):
                ctx.qs.add(Question(
                    OpenQuestion.MISSING_DIMENSION,
                    f"{v.id} 是剖视图但图上没有剖面线 ⇒ 拿不到「这块是材料」的"
                    "直接证据，材料/空洞只能靠轮廓推",
                    view=v.id, evidence=tuple(v.evidence[:1]),
                ))
            continue
        items = list(zip(refs, boxes))
        zones = tuple(union_boxes([b for _, b in g])
                      for g in cluster_boxes(items, _ZONE_GAP))
        mp = MaterialPatch(count=len(refs), bbox=union_boxes(boxes),
                           pattern=pattern, zones=zones)
        out.append(Convention(
            rule="section.material", kind=ConvKind.MATERIAL, view=v.id,
            value=mp,
            claim=Claim(mp, "convention:hatch", Tier.CONVENTION,
                        evidence=tuple(refs)),
            note=f"{len(refs)} 处剖面填充"
                 + (f"（图案 {pattern}）" if pattern else "")
                 + f"，聚成 {len(zones)} 个区 ⇒ 这些区域是材料",
            evidence=tuple(refs),
        ))
    return out
