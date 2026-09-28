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

from ..evidence.model import Kind
from ..evidence.text_parser import CutSpec, TextKind
from ..model.claim import Claim, Tier
from ..model.geom2d import BBox2
from ..model.ids import EvidenceRef
from ..model.questions import OpenQuestion, Question
from .registry import (
    Convention, ConvKind, RuleCtx, by_handle_index, register, union_boxes,
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


@register("section.scope")
def scope(ctx: RuleCtx) -> list[Convention]:
    """剖切种类 ⇒ 截面材料的适用范围（以及能不能当棱柱用）。"""
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
            ctx.qs.add(Question(
                OpenQuestion.AMBIGUOUS_FEATURE,
                f"{v.id}（{cut.label}）的剖切种类读不出来（原标题「{cut.raw}」）—— "
                "按「不能用它裁材料」处理：错裁是净删真材料，方向性地把模型做小",
                view=v.id, evidence=refs,
            ))
        elif not usable:
            ctx.qs.add(Question(
                OpenQuestion.AMBIGUOUS_FEATURE,
                f"{v.id}（{cut.label}）是「{kind}」：{reason} ⇒ "
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
    """一处被剖到的材料（``ConvKind.MATERIAL`` 的 value）。"""

    count: int
    bbox: BBox2 | None = None
    pattern: str = ""


@register("section.material")
def material(ctx: RuleCtx) -> list[Convention]:
    """HATCH ⇒ 这块是材料（不是空洞）。

    剖面线是图纸里**唯一**直接说"这里是材料"的符号：轮廓说"这里有边界"，
    剖面线说"边界之内是实心"。两条信息合起来才有"材料区"。
    """
    idx = by_handle_index(ctx.d)
    out: list[Convention] = []
    for v in ctx.d.views:
        refs: list[EvidenceRef] = []
        boxes: list[BBox2] = []
        pattern = ""
        for h in v.evidence:
            e = idx.get(h)
            if e is None or e.kind != Kind.HATCH:
                continue
            refs.append(e.handle)
            boxes.append(e.exact_bbox)
            pattern = pattern or e.pattern
        if not refs:
            if isinstance(v.cut, CutSpec):
                ctx.qs.add(Question(
                    OpenQuestion.MISSING_DIMENSION,
                    f"{v.id} 是剖视图但图上没有剖面线 ⇒ 拿不到「这块是材料」的"
                    "直接证据，材料/空洞只能靠轮廓推",
                    view=v.id, evidence=tuple(v.evidence[:1]),
                ))
            continue
        mp = MaterialPatch(count=len(refs), bbox=union_boxes(boxes),
                           pattern=pattern)
        out.append(Convention(
            rule="section.material", kind=ConvKind.MATERIAL, view=v.id,
            value=mp,
            claim=Claim(mp, "convention:hatch", Tier.CONVENTION,
                        evidence=tuple(refs)),
            note=f"{len(refs)} 处剖面填充"
                 + (f"（图案 {pattern}）" if pattern else "")
                 + " ⇒ 这些区域是材料",
            evidence=tuple(refs),
        ))
    return out
