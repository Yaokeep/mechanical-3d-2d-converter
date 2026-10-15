# -*- coding: utf-8 -*-
"""孔标注 ↔ 圆边的绑定（``ConvKind.CALLOUT`` 的消费端）。

约定层把「`4~∅10-7H 深25`」读成结构化结论（直径/数量/深度/通盲 + 所属视图），
本模块把它**挂到具体的圆上** —— 这是"图上明标的尺寸压过从轮廓反推"那条
tier 规则在孔上的落地：投影侧读不出（半剖省了孔壁、简图没画轮廓对）的地方，
标注来补；投影侧读得出的地方（可见/隐藏轮廓对），投影照旧说话。

## 绑定判据（三条，缺一不可）

1. **同一个视图**：孔标注与圆之间**没有引线**（YZYX 实测：4 条 LEADER 全给了
   形位公差 TOLERANCE），所以只能按位置判 —— 文字就近归属到视图
   （``conventions.callout.owner_view``），候选圆只在该视图里找。
   实测这条最有效：两个 r8 圆相距 1359mm 分属两处结构，∅16锥孔 归属
   96mm 的那个、2~M16-7H 归属 139mm 的那个，靠视图分得干干净净。
2. **半径严合**（``BIND_TOL = 0.05``，与 views 层 ``DUP_TOL`` 同一把尺）：
   实测所有真配对 Δr = 0.000，而 r6.56123（φ13.12，另一处结构的同心圆）
   离 φ13 有 0.061 —— 容差取 0.05 刚好把它挡在 `8~∅13` 之外。
3. **可见/隐藏轮廓，排除细实线**：细实线是"轮廓被前面材料盖住"，不是开口。
   实测 3 条细实线 r6.5 弧恰好落在 4×Ø10 的孔心上（φ13 的另一种画法），
   混进来 `8~∅13` 会数出 11 个圆。

## 数量：**核对、但不当闸门**

``n`` 与数到的圆数不符时**照绑、只记账**（``count_ok=False``）：半径严合 +
同视图 + 图上明写，三条合起来已经说明"这些圆就是这组孔"；图面少画（半剖
省略、简化画法、被画成别的半径）是出图侧的表现差，不改变这个事实。反例
就在实测里：`4~∅10-7H 深25` 只数到 3 个可见 r5（第 4 处画成 Ø7 + 细实线
φ10）、`2~M16-7H` 只数到 1 个（V0 半剖，剖切侧的孔没有圆）—— 按闸门处理
会把这 4+2 个孔全丢掉。

## 轴向区间在组内传播

同一条标注说的是一组**同样安置**的孔（`8~∅13` 八个都通法兰），故组内任一
圆的轮廓对读出了轴向区间（``CylinderHint.span``），就传播给全组 —— 依据
是"同组同构"这条制图约定（``Tier.CONVENTION``），不是投影直接量出来的。
实测 8 个 Ø13 里 2 个读到了 span（0..12 = 法兰厚），传播后八个孔都落在
法兰里，与真值 v15a 的 z −1..13 一致（这正是"半剖只画半边"的补法）。
"""
from __future__ import annotations

from dataclasses import dataclass, field

from ..conventions import ConvKind
from ..conventions.callout import HoleCallout
from ..evidence.model import Role
from ..model.claim import Claim, Tier
from ..views.correspondence import CorrespondenceResult, CylinderHint

#: 半径配对容差（mm）—— 与 views 层 ``DUP_TOL`` 同一把尺（见模块 docstring）
BIND_TOL = 0.05

#: 通孔要给的 ``axial_at``：轴原点即圆的投影原点（第三坐标恒为 0），
#: 对通孔而言它只是**切刀下界**（材料必在 + 轴向一侧），不是图纸读数
_THROUGH_START = 0.0


@dataclass(frozen=True)
class HoleBinding:
    """一条孔标注与一组圆边的绑定结果。"""

    callout: HoleCallout
    handles: tuple[str, ...]          # 组内全部圆边 handle
    radius: float
    count_ok: bool
    span: tuple[float, float] | None = None
    #: 提供 span 的那个圆（传播的来源，审计用；空 = 没读到 span）
    span_from: str = ""
    #: 组内各圆到 span 的距离同不同源 —— 只有 span_from 那条是投影直接量到的
    propagated: bool = False

    @property
    def span_len(self) -> float | None:
        return None if self.span is None else self.span[1] - self.span[0]


@dataclass
class CalloutBindings:
    """一次绑定的全量产出：``by_handle`` 供识别器按圆边查，``notes`` 记账。"""

    by_handle: dict[str, HoleBinding] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    def of(self, handles: tuple[str, ...]) -> HoleBinding | None:
        for h in handles:
            b = self.by_handle.get(str(h))
            if b is not None:
                return b
        return None

    def handles(self) -> frozenset[str]:
        return frozenset(self.by_handle)


def bind_hole_groups(conv, corr: CorrespondenceResult, d) -> CalloutBindings:
    """把 ``ConvKind.CALLOUT`` 的孔标注绑到圆边上（判据见模块 docstring）。"""
    out = CalloutBindings()
    if conv is None:
        return out
    idx = {e.handle: e for e in d.evidence}
    cands: list[tuple[CylinderHint, str, float, tuple[str, ...]]] = []
    for c in corr.cylinders():
        hint = c.mapping.value
        assert isinstance(hint, CylinderHint)
        rad = hint.axis.radius
        if rad is None or not c.views:
            continue
        handles = tuple(str(h) for h in rad.evidence)
        thin = any((idx[h].role.value if h in idx else Role.THIN.value)
                   == Role.THIN.value for h in handles)
        if thin:
            continue
        cands.append((hint, c.views[0], float(rad.value), handles))
    for item in conv.of_kind(ConvKind.CALLOUT):
        hc: HoleCallout = item.value
        group = [x for x in cands
                 if x[1] == hc.view and abs(x[2] - hc.radius) <= BIND_TOL]
        if not group:
            out.notes.append(_no_candidate_note(hc, corr))
            continue
        span: tuple[float, float] | None = None
        span_from = ""
        for hint, _v, _r, handles in group:
            if hint.span is not None:
                span, span_from = hint.span, handles[0]
                break
        handles_all = tuple(h for x in group for h in x[3])
        b = HoleBinding(callout=hc, handles=handles_all, radius=hc.radius,
                        count_ok=len(group) == hc.count, span=span,
                        span_from=span_from,
                        propagated=bool(span) and len(group) > 1)
        fresh = [h for h in handles_all if h not in out.by_handle]
        for h in fresh:
            out.by_handle[h] = b
        out.notes.append(_bind_note(hc, b, len(group), len(fresh)))
    return out


def _no_candidate_note(hc: HoleCallout, corr: CorrespondenceResult) -> str:
    if hc.view and hc.view not in corr.frames:
        return (f"孔标注「{hc.text}」归属 {hc.view}，但该视图还没有坐标系"
                f"（视图未定性）⇒ 一个圆都绑不上（记缺口）")
    if not hc.view:
        return f"孔标注「{hc.text}」没落在任何视图附近 ⇒ 绑不上圆（记缺口）"
    return (f"孔标注「{hc.text}」归属 {hc.view}，但那里没有半径严合"
            f"（Δr ≤ {BIND_TOL:g}）且非细实线的圆 ⇒ 一个圆都绑不上（记缺口）")


def _bind_note(hc: HoleCallout, b: HoleBinding, n_group: int,
               n_fresh: int) -> str:
    body = f"孔标注「{hc.text}」⇒ {hc.view} 里绑上 {n_group} 个圆"
    if not b.count_ok:
        body += f"（标注说 {hc.count} 个，图上只数到 {n_group} 个 —— 半剖/简化画法"
        if hc.depth is not None:
            body += "；深度按标注走"
        body += "）"
    if b.span is not None:
        body += (f"；轴向区间 {b.span[0]:.2f}..{b.span[1]:.2f}"
                 f"（由圆 {b.span_from} 的轮廓对读出，"
                 + ("传播给全组" if b.propagated else "即本圆") + "）")
    if n_fresh < n_group:
        body += f"；其中 {n_group - n_fresh} 个圆已被别的标注绑定"
    return body


def bound_hole_params(b: HoleBinding, handles: tuple[str, ...]
                      ) -> tuple[dict[str, Claim], str]:
    """绑定的孔 ⇒ 特征参数（radius 另给）。返回 ``(params, 拒绝发射的理由)``。

    三条出路：
      · span 已知（本圆量的或组内传播的）⇒ **按画出来的区间切**：轴向区间
        就是图上那两条轮廓线之间的范围，比"未注深度⇒通孔"更具体（实测
        Ø13 的 span 0..12 = 法兰厚，而按通孔切会沿轴切穿全零件）
      · span 无、标注给了深度 ⇒ 孔口在**哪一端**没有依据（深25 从哪面下钻
        图面没说）⇒ 拒绝发射，理由交调用方报成疑问（不许按 0 起硬切）
      · span 无、未注深度 ⇒ 通孔，轴向位置不拘（切刀跨全轴）
    """
    ev = tuple(handles)
    if b.span is not None:
        claim_tier, how = (Tier.PROJECTION, "projection:outline_pair") \
            if b.span_from in handles else (Tier.CONVENTION, "callout:group_span")
        return ({
            "depth": mk(b.span[1] - b.span[0], how, claim_tier, ev),
            "axial_at": mk(b.span[0], how, claim_tier, ev),
            "through": Claim(False, how, claim_tier, ev),
        }, "")
    if b.callout.depth is not None:
        return ({}, f"孔深 {b.callout.depth:g} 是标注给的，但孔口在该轴的哪一端"
                    f"图上没有任何依据（轮廓对没读到）⇒ 拒绝发射"
                    f"（按 0 起会横切零件）")
    tier = Tier.ANNOTATED if b.callout.matched and "kw:通孔" in b.callout.matched \
        else Tier.CONVENTION
    how = "annotation:hole_callout" if tier is Tier.ANNOTATED \
        else "convention:no_depth_means_through"
    return ({
        "through": Claim(True, how, tier, ev),
        "axial_at": mk(_THROUGH_START, how, tier, ev),
    }, "")


def mk(value, how: str, tier: Tier, ev: tuple) -> Claim:
    """本模块内部的小工厂（与 recognizer.mk_claim 同形，避免反向依赖）。"""
    return Claim(value, how, tier, evidence=ev)
