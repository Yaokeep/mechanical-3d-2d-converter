# -*- coding: utf-8 -*-
"""简化画法约定 —— 螺纹 / 未注圆角 / 均布孔的文字侧。

制图标准允许（甚至要求）图上**不画全**：螺纹按大径画、小径画 3/4 圈细实线；
未注圆角不画；均布孔只标注"n×φd 均布"。这些都是**约定**而不是缺信息 ——
但必须是"知道约定的存在"才算读到了，否则就会：

- 把螺纹的大径圆与小径圆当成**两个孔**（多出一个 φ，且都错）
- 把图上画的尖角当成真的尖角（应力分析、加工工时全错）
- 把"8×φ3.3 均布"读成"8 个孔，位置未知"

本模块只处理**文字侧**（图上写了什么）；几何侧的圆周分布由
``centerline.patterns`` 从圆心几何直接认出来，二者互为佐证。
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from ..evidence.model import Kind
from ..model.claim import Claim, Tier
from ..model.geom2d import Arc2, Circle2
from ..model.ids import EvidenceRef
from ..model.questions import OpenQuestion, Question
from .registry import Convention, ConvKind, RuleCtx, by_handle_index, register

#: 螺纹代号：M8 / M10×1.5 / Tr20×4 / G1/2 / NPT1/4 …
#: 左边界防 "SM8"；右边界防 "M8x" 之外的粘连
_THREAD_RE = re.compile(
    r"(?<![A-Za-z0-9])(M|Tr|G|Rp|Rc|NPT|BSP)\s?(\d+(?:\.\d+)?)"
    r"(?:\s?[×xX]\s?(\d+(?:\.\d+)?))?")

#: 文字长于这个长度就不当螺纹标注看（零件名/图号里也常出现 M4 这样的片段，
#: 本项目 `麒浚传动_PF60K-14-50-70-M4-L2-12` 就是活例子）
_THREAD_MAX_LEN = 24

#: 未注圆角/倒角
_FILLET_WORDS = ("未注圆角", "未注倒角", "未注圓角", "未注半径", "UNSPECIFIED FILLET")


@dataclass(frozen=True)
class ThreadSpec:
    """一处螺纹标注（``ConvKind.THREAD`` 的 value）。"""

    code: str            # "M8"
    major_d: float       # 大径 mm
    pitch: float | None = None
    hole_ref: EvidenceRef | None = None   # 图纸上对应的大径圆（找到时）
    text_ref: EvidenceRef | None = None


@dataclass(frozen=True)
class FilletSpec:
    """未注圆角（``ConvKind.FILLET`` 的 value）。"""

    radius: float
    note: str = ""


@register("simplification.threads")
def threads(ctx: RuleCtx) -> list[Convention]:
    """螺纹代号 ⇒ 大径/小径圆组**不是两个孔**，是一个螺纹孔。

    强度分级是诚实的：图上找得到对应的大径圆（半径 ≈ d/2）才算
    CONVENTION（有几何佐证），找不到只记 GUESS（只有文字）。
    """
    idx = by_handle_index(ctx.d)
    out: list[Convention] = []
    for t in ctx.d.texts:
        raw = (t.text or "").strip()
        if not raw or len(raw) > _THREAD_MAX_LEN:
            continue
        m = _THREAD_RE.search(raw)
        if not m:
            continue
        major = float(m.group(2))
        pitch = float(m.group(3)) if m.group(3) else None
        v = ctx.d.view_of(t.handle)
        hole_ref: EvidenceRef | None = None
        if v is not None:
            for h in v.evidence:
                e = idx.get(h)
                if e is None or e.kind != Kind.EDGE:
                    continue
                g = e.geom
                r = g.radius if isinstance(g, (Circle2, Arc2)) else None
                if r is not None and abs(r - major / 2.0) <= 0.3:
                    hole_ref = e.handle
                    break
        spec = ThreadSpec(code=m.group(0).strip(), major_d=major, pitch=pitch,
                          hole_ref=hole_ref, text_ref=t.handle)
        tier = Tier.CONVENTION if hole_ref else Tier.GUESS
        ev = (t.handle,) + ((hole_ref,) if hole_ref else ())
        out.append(Convention(
            rule="simplification.threads", kind=ConvKind.THREAD,
            view=v.id if v is not None else "", value=spec,
            claim=Claim(spec, "convention:thread_code", tier, evidence=ev),
            note=f"「{raw}」⇒ 螺纹 {spec.code}（大径 {major:g}"
                 + (f"，螺距 {pitch:g}" if pitch else "")
                 + "）：大径圆与 3/4 细实线圆是**同一个螺纹孔**，"
                 "不得当成两个孔"
                 + ("；已找到对应大径圆" if hole_ref else
                    "；图上没找到对应的大径圆，只有文字依据"),
            evidence=ev,
        ))
        if not hole_ref:
            ctx.qs.add(Question(
                OpenQuestion.MISSING_DIMENSION,
                f"文字「{raw}」是螺纹代号，但图纸上没找到半径 ≈ {major / 2:g} 的圆 —— "
                "螺纹孔的深度与所在位置都没有几何依据",
                view=v.id if v is not None else "", evidence=(t.handle,),
            ))
    return out


@register("simplification.fillets")
def fillets(ctx: RuleCtx) -> list[Convention]:
    """「未注圆角 R2」⇒ 图上画的尖角其实都是 R2 圆角。"""
    out: list[Convention] = []
    for t in ctx.d.texts:
        up = (t.text or "").upper()
        if not any(w in up for w in _FILLET_WORDS):
            continue
        r = next((val for name, val in t.values if name in ("r", "φ")), None)
        if r is None:
            ctx.qs.add(Question(
                OpenQuestion.UNREADABLE_NOTE,
                f"「{t.text}」写了未注圆角但没读到半径值 —— 这条技术要求没用上",
                evidence=(t.handle,),
            ))
            continue
        spec = FilletSpec(radius=r, note=t.text)
        out.append(Convention(
            rule="simplification.fillets", kind=ConvKind.FILLET, value=spec,
            claim=Claim(spec, "note:unspecified_fillet", Tier.ANNOTATED,
                        evidence=(t.handle,)),
            note=f"「{t.text}」⇒ 图上未画出的圆角一律 R{r:g}"
                 "（不影响体积精度，但影响「这处是不是尖角」的一切判断）",
            evidence=(t.handle,),
        ))
    return out
