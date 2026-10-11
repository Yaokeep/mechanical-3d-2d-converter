# -*- coding: utf-8 -*-
"""尺寸标注约定 —— DIMENSION 实体 ⇒ 「数值 ↔ 几何锚点」的配对证据。

## 为什么这条规则非有不可

YZYX #1 争议三轮的定案证据是图纸**自带的 DIMENSION 实体**：「20」
标在 (−75,145)→(−75,125)、「3」标在 (−75,125)→(−60,122)、「120」标在
(−60,122)→(60,122)（ezdxf ``get_measurement`` 实测，逐位吻合）。这不是
推断——是图上明写的标注（tier=ANNOTATED，比一切启发式都硬）。

旧管线（和新框架的读取器）都**读了** DIMENSION 却没有下游消费：
值存在 ``Drawing.dimensions`` 里，识别器与约定层都不查它。本规则把
「这个值标在哪段几何上」显式配出来（``Dimension.p1/p2`` 就是被量的
两端，见 ARCHITECTURE §4.3），下游拿 ``Conventions.of_kind(DIMENSION)``
就能问"图上有没有一个尺寸在说这段的距离/这个圆的半径"。

## 职责边界

只做**忠实配对**，不解释"这个值应该驱动哪个特征参数"——那是特征层
的事。锚点配不上**不报阻塞疑问**（"没锚上"≠"缺尺寸"），只记在 note
里：一张旧图纸的标注 defpoint 与几何脱开几毫米是常态，把它升级成
拦路疑问会把"图面噪音"变成"拒绝重建"。
"""
from __future__ import annotations

from dataclasses import dataclass

from ..evidence.model import Dimension, Kind
from ..model.claim import Claim, Tier
from ..model.ids import EvidenceRef
from .registry import Convention, ConvKind, RuleCtx, by_handle_index, register

#: 锚点配对容差（mm）：defpoint 与几何端点/圆心在它之内就算锚上。
#: 图纸标注 defpoint 是精确的（YZYX 实测逐位吻合），1mm 只放旧图噪音
_ANCHOR_TOL = 1.0

#: 半径/直径类标注的圆心在 defpoint（p3）；线性类在被量的两端（p1/p2）
_CENTER_DIMTYPES = ("radius", "diameter")


@dataclass(frozen=True)
class DimClaim:
    """一条尺寸标注的证据配对（``ConvKind.DIMENSION`` 的 value）。

    ``value`` 是图上标注的数值（``get_measurement`` 实测或 defpoint 兜底），
    ``anchors`` 是被量几何的证据引用（边/圆/弧）—— 这就是
    「尺寸 ↔ 几何锚点」配对的直接产物。
    """

    value: float | None
    dimtype: str
    dim_ref: EvidenceRef
    anchors: tuple[EvidenceRef, ...] = ()
    view: str = ""


def _edge_points(geom):
    """一条边的候选锚点（直线端点 / 圆心）。"""
    pts = []
    if hasattr(geom, "start") and hasattr(geom, "end"):
        pts.append(geom.start)
        pts.append(geom.end)
    if hasattr(geom, "center"):
        pts.append(geom.center)
    return pts


def _match_anchors(idx, view, points) -> tuple[EvidenceRef, ...]:
    """视图里哪些边锚在给定点上（容差 _ANCHOR_TOL）。"""
    anchors: list[EvidenceRef] = []
    for h in view.evidence:
        e = idx.get(h)
        if e is None or e.kind != Kind.EDGE:
            continue
        if any(pt.distance_to(p) <= _ANCHOR_TOL
               for pt in _edge_points(e.geom) for p in points):
            anchors.append(e.handle)
    return tuple(anchors)


@register("dimension.anchors")
def anchors(ctx: RuleCtx) -> list[Convention]:
    """DIMENSION 实体 ⇒ 「数值 ↔ 几何锚点」配对（尺寸证据）。

    线性/对齐：p1/p2 = 被量的两端 → 找端点落在容差内的边；
    半径/直径：p3 = defpoint（圆心）→ 找圆心落在容差内的圆/弧。
    锚上多少条都如实记；一条都没锚上也产出结论（note 里写明），
    供报告与覆盖率摆到台面上。
    """
    dims = {d.handle: d for d in ctx.d.dimensions}
    if not dims:
        return []
    idx = by_handle_index(ctx.d)
    out: list[Convention] = []
    for v in ctx.d.views:
        for h in v.annotations:
            dim = dims.get(h)
            if dim is None:
                continue
            dc = _dim_claim(dim, idx, v)
            out.append(Convention(
                rule="dimension.anchors", kind=ConvKind.DIMENSION, view=v.id,
                value=dc,
                claim=Claim(dc, "annotation:dimension",
                            Tier.ANNOTATED if dc.value is not None else Tier.GUESS,
                            evidence=(dim.handle,)),
                note=_dim_note(dc),
                evidence=(dim.handle,) + dc.anchors,
            ))
    return out


def _dim_claim(dim: Dimension, idx, view) -> DimClaim:
    """单条尺寸的锚点配对（独立函数便于自检直测）。"""
    if dim.dimtype in _CENTER_DIMTYPES:
        pts = [dim.p3] if dim.p3 is not None else []
    else:
        pts = [p for p in (dim.p1, dim.p2) if p is not None]
    found = _match_anchors(idx, view, pts) if pts else ()
    return DimClaim(value=dim.value, dimtype=dim.dimtype, dim_ref=dim.handle,
                    anchors=found, view=view.id)


def _dim_note(dc: DimClaim) -> str:
    """DimClaim 的人类可读描述（规则产出的 note）。"""
    val = f"{dc.value:g}" if dc.value is not None else "?"
    body = f"「{val}」{dc.dimtype}"
    if dc.anchors:
        body += f"，锚到 {len(dc.anchors)} 条边 ⇒ 图上明标的尺寸证据"
    else:
        body += "，没锚到任何边 ⇒ 数值可用但对应的几何未知"
    return body
