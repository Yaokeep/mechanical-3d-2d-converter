# -*- coding: utf-8 -*-
"""线型约定 —— 虚线 / 点划线 / 波浪线（**断裂视图**）。

## 为什么这条规则非有不可

整条旧管线里**没有"断裂视图"这个概念**。断裂视图（细长零件为省图面而
从中截掉一段、两端画波浪线）在老管线里就是一个普通的完整视图，于是
"图面量到 100mm"被当成"零件长 100mm"。这个错的形态特别坏：

- 数值合理（就是个长度），量级正常，不报任何警告
- 下游所有沿该方向的尺寸、位置、体积推导**全部**连带错

判据只有一条且很硬：**波浪线/断裂线在图上把视图切断**。被截掉的那一段
在图纸上根本不存在，所以该视图沿断裂线**法向**的坐标全部不可用 ——
注意不只是"总长不可用"，**连特征位置也不可用**（图上 x=60 的孔，其真实
模型 x 不等于 60+偏移）。所以本层的产出不是"尺寸打个折"，而是
:class:`~.registry.BrokenView`：**该方向的坐标整条作废**。

## 双点划线（PHANTOM）为什么不在读取器里判

双点划线在机械制图里既可作断裂线，也可作**假想投影轮廓**（相邻零件、
运动极限位置）。二者在图面上无法用线型区分，只判线型必然误报。
读取器只认"波浪线/断裂线"这类**明确**命名（图层或线型名含
波浪/断裂/BREAK），其余交给使用方按视图上下文决定。
"""
from __future__ import annotations

from dataclasses import dataclass

from ..evidence.model import Role
from ..model.claim import Claim, Tier
from ..model.geom2d import BBox2
from ..model.ids import EvidenceRef
from ..model.questions import OpenQuestion, Question
from .registry import (
    BrokenView, Convention, ConvKind, RuleCtx, by_handle_index, cluster_boxes,
    orient_of, register, union_boxes,
)

#: 同一个视图里，两条断裂线相距一般远大于这个值；用它把"一条被炸成多段"
#: 与"两条独立的断裂线"区分开
_BREAK_GAP = 2.0


@dataclass(frozen=True)
class HiddenProfile:
    """虚线概况（``ConvKind.HIDDEN`` 的 value）。"""

    count: int
    bbox: BBox2 | None = None


@register("linetype.breaks")
def breaks(ctx: RuleCtx) -> list[Convention]:
    """波浪线/断裂线 ⇒ 该视图沿断裂线法向被缩短（坐标不可用）。

    走向判据：断裂线**横跨**零件，所以一条竖着的波浪线 ⇒ 图面横向（u）
    被截掉一段；一条横着的波浪线 ⇒ 纵向（v）被截掉一段。
    同方向有多条（常规是一对，两端各一条）⇒ 仍旧只标记该方向不可用。
    """
    idx = by_handle_index(ctx.d)
    out: list[Convention] = []
    for v in ctx.d.views:
        items: list[tuple[EvidenceRef, BBox2]] = []
        for h in v.evidence:
            e = idx.get(h)
            if e is not None and e.role.value == Role.BREAK_LINE:
                items.append((e.handle, e.exact_bbox))
        if not items:
            continue

        which: set[str] = set()
        refs: list[EvidenceRef] = []
        for group in cluster_boxes(items, _BREAK_GAP):
            cur = union_boxes([b for _, b in group])
            refs.extend(h for h, _ in group)
            o = orient_of(cur)
            # 竖线（走向 v）横跨零件 ⇒ 图面横向被截断
            if o == "v":
                which.add("u")
            elif o == "h":
                which.add("v")
            else:
                ctx.qs.add(Question(
                    OpenQuestion.BROKEN_VIEW,
                    f"{v.id} 里有一条断裂线，但它的走向判不出来"
                    f"（包围盒 {cur.width:.2f}×{cur.height:.2f}）——"
                    "无法确定是哪个方向被截断，两个方向都按不可信处理",
                    view=v.id, evidence=tuple(h for h, _ in group),
                ))
                which.update(("u", "v"))
        box_union = union_boxes([b for _, b in items])

        if not which:
            continue
        bv = BrokenView(which=tuple(sorted(which)), bbox=box_union,
                        lines=tuple(refs))
        out.append(Convention(
            rule="linetype.breaks", kind=ConvKind.BREAK, view=v.id, value=bv,
            claim=Claim(bv, "convention:break_line", Tier.CONVENTION,
                        evidence=tuple(refs)),
            note=f"图上 {'/'.join(sorted(which))} 向被断裂截去一段"
                 f"（{len(refs)} 条断裂线）⇒ 该向坐标不可直接当模型坐标用",
            evidence=tuple(refs),
        ))
        ctx.qs.add(Question(
            OpenQuestion.BROKEN_VIEW,
            f"{v.id} 是**断裂视图**：图上 {'/'.join(sorted(which))} 方向被截去一段，"
            "该方向的图面尺寸与特征位置**都不等于真实值**。"
            "需要真实总长时必须另找依据（尺寸标注/其他视图），"
            "不得用本视图的图面跨度",
            view=v.id, evidence=tuple(refs),
        ))
    return out


@register("linetype.hidden")
def hidden(ctx: RuleCtx) -> list[Convention]:
    """虚线 ⇒ 内部特征存在（孔/槽/内腔），且**从该方向看不见**。

    这条结论本身很弱，但它是"孔还是凸台"消解链条上的一环：
    正交视图里的轮廓是**实线**还是**虚线**，是区分二者的唯一依据
    （§3 原则二：俯视图里两者同形，不许提前消解）。
    """
    idx = by_handle_index(ctx.d)
    out: list[Convention] = []
    for v in ctx.d.views:
        refs: list[EvidenceRef] = []
        box: BBox2 | None = None
        for h in v.evidence:
            e = idx.get(h)
            if e is None or e.role.value != Role.HIDDEN:
                continue
            refs.append(e.handle)
            bb = e.exact_bbox
            box = bb if box is None else box.union(bb)
        if not refs:
            continue
        hp = HiddenProfile(count=len(refs), bbox=box)
        out.append(Convention(
            rule="linetype.hidden", kind=ConvKind.HIDDEN, view=v.id, value=hp,
            claim=Claim(hp, "convention:linetype", Tier.CONVENTION,
                        evidence=tuple(refs)),
            note=f"{len(refs)} 条虚线 ⇒ 有内部特征（孔/槽/内腔），"
                 "该方向上被前面材料挡住",
            evidence=tuple(refs),
        ))
    return out
