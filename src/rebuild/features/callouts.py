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

from dataclasses import dataclass, field, replace

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

#: span 来源方法 → Claim tier（未列出的一律 CONVENTION —— 传播与分区推断
#: 都是从"同组同构"/"顶面即孔口"这类约定走出来的，不是投影直读）
_SPAN_TIER = {"projection:outline_pair": Tier.PROJECTION}

#: "同心分区定孔口"的轴距容差（mm）：分区圆与孔圆共轴才认
_MOUTH_AXIS_TOL = 0.1


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
    #: span 的**来源方法**（空 = 由轮廓对读出、按 span_from 定 tier）；
    #: ``infer_callout_mouth_spans`` 推出的 span 写 "zone:concentric_mouth"
    span_how: str = ""

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
        how = b.span_how or ("projection:outline_pair"
                             if b.span_from in handles else "callout:group_span")
        claim_tier = _SPAN_TIER.get(how, Tier.CONVENTION)
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


# ---------------------------------------------------------------------------
# 孔口定位：同心材料分区的顶面（§C6 第三段）
# ---------------------------------------------------------------------------

def infer_callout_mouth_spans(binds: CalloutBindings, corr: CorrespondenceResult,
                              plan, notes: list[str]) -> int:
    """给"标注给了深度、轮廓对却没读到"的孔组，用俯视**材料分区顶面**定孔口。

    这是 ``bound_hole_params`` 第 2 条出路（"孔口在哪一端没有依据 ⇒ 拒绝发射"
    —— 不许按 0 起硬切）的补法：孔口其实还在别处写着。俯视圆分区里，与孔
    **同轴、半径更大**的那块**材料**分区，它的实测顶面（``Zone.t_hi``）就是
    孔口面 —— 孔从这块材料的顶面下钻，深度按标注。

    YZYX 实测（`4~∅10-7H 深25`）：三个绑定的 r5 圆里两个的同心材料分区顶面
    = 1686.25（图纸系，= v15a 真值 z145 顶面），一个（东下孔位）的分区读数
    1589.50 —— 与真值矛盾。故取**组内多数派**：2:1 ⇒ 推得 span (1661.25,
    1686.25) ≡ 真值 z[120,145]。打平或没多数时不推，维持"拒绝发射" ——
    宁可少建不可错建（与剖视规则同一条原则）。

    守卫（防循环证据）：同心分区的圆半径必须**大于**孔半径 —— 与孔同半径的
    圆是孔自己，更小的同心圆是孔里的沉头/底孔轮廓（也不构成孔口）。

    返回推断成功的组数；``notes`` 追加记账。
    """
    zones = getattr(plan, "zones", None) or ()
    if not zones:
        return 0
    hint_by_handle: dict[str, CylinderHint] = {}
    for c in corr.cylinders():
        h = c.mapping.value
        if not isinstance(h, CylinderHint) or h.axis.radius is None:
            continue
        for e in h.axis.radius.evidence:
            hint_by_handle.setdefault(str(e), h)
    uniq: dict[int, HoleBinding] = {}
    for b in binds.by_handle.values():
        uniq.setdefault(id(b), b)
    n = 0
    for b in uniq.values():
        if b.span is not None or b.callout.depth is None:
            continue
        votes: dict[float, list[str]] = {}
        voters = 0
        for h in b.handles:
            hint = hint_by_handle.get(h)
            if hint is None:
                continue
            z = _concentric_material_zone(zones, hint)
            if z is None:
                continue
            voters += 1
            if z.t_hi - b.callout.depth < z.t_lo - 1e-9:
                continue          # 从该顶面下钻会钻出分区 ⇒ 它不是孔口面
            votes.setdefault(round(z.t_hi, 2), []).append(h)
        if not votes:
            continue
        mouth, who = max(votes.items(), key=lambda kv: len(kv[1]))
        if len(who) * 2 <= voters:
            notes.append(
                f"孔标注「{b.callout.text}」：同心材料分区的顶面读数不一致"
                f"（{len(votes)} 种），不构成多数 ⇒ 维持拒绝发射（宁可少建）")
            continue
        nb = replace(b, span=(mouth - b.callout.depth, mouth),
                     span_from=who[0], propagated=bool(len(b.handles) > 1),
                     span_how="zone:concentric_mouth")
        for h, cur in list(binds.by_handle.items()):
            if cur is b:
                binds.by_handle[h] = nb
        notes.append(
            f"孔标注「{b.callout.text}」：轮廓对没读到，孔口由同心材料分区"
            f"顶面定出（{mouth:.2f}，{len(who)}/{voters} 个圆一致）⇒ 轴向区间 "
            f"{mouth - b.callout.depth:.2f}..{mouth:.2f}，深度按标注 "
            f"{b.callout.depth:g} 下钻")
        n += 1
    return n


def _concentric_material_zone(zones, hint: CylinderHint):
    """与 ``hint`` 同轴、半径更大的**材料**分区里，半径最小的那个。

    "同心" = 轴共垂距 ≤ ``_MOUTH_AXIS_TOL``（``_axis_gap``，纯浮点）。
    取半径最小者 = 最贴近孔口的那层材料（实测同轴材料分区常有 r50 大环台
    与 r6.5 小凸台两层，孔口在小的那层上）。
    """
    best: tuple[float, object] | None = None
    for z in zones:
        if z.role != "material":
            continue
        for h2 in z.hints:
            if h2.axis.radius is None:
                continue
            r2 = h2.axis.radius.value
            if not isinstance(r2, (int, float)) or r2 <= hint.radius + 1e-9:
                continue
            if _axis_gap(hint.axis, h2.axis) > _MOUTH_AXIS_TOL:
                continue
            if best is None or r2 < best[0]:
                best = (float(r2), z)
    return best[1] if best is not None else None


def _axis_gap(a1, a2) -> float:
    """两条 3D 轴的公垂距（不平行取异面公垂距；近平行取点线距）。纯浮点。"""
    u, v = a1.direction.normalized(), a2.direction.normalized()
    w = a2.origin - a1.origin
    cx = u.y * v.z - u.z * v.y
    cy = u.z * v.x - u.x * v.z
    cz = u.x * v.y - u.y * v.x
    c = (cx * cx + cy * cy + cz * cz) ** 0.5
    if c < 1e-9:                      # 平行：|w − (w·u)u|
        t = w.x * u.x + w.y * u.y + w.z * u.z
        dx, dy, dz = w.x - t * u.x, w.y - t * u.y, w.z - t * u.z
        return (dx * dx + dy * dy + dz * dz) ** 0.5
    return abs(w.x * cx + w.y * cy + w.z * cz) / c
