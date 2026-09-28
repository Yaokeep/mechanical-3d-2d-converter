# -*- coding: utf-8 -*-
"""人读报告与 explain 查询（docs/ARCHITECTURE.md §9）。

**探针脚本的替代品。** 旧管线需要为每个问题写一个 `_probe_*.py`
（现存 34 个）—— 那种数量的探针本身是"系统无法自我解释"的症状。
有了 provenance（每个数值带 evidence），调试退化成一次查询。

本模块只依赖 model/evidence 层，跑默认 python 即可。
"""
from __future__ import annotations

from .model.claim import Claim
from .evidence.model import Drawing
from .evidence.text_parser import TextKind

H1 = "=" * 72
H2 = "-" * 72


def _rule(title: str = "") -> str:
    return f"\n{H2}\n{title}\n{H2}" if title else H2


# ---- 证据报告 ----

def evidence_report(d: Drawing) -> str:
    """图纸读到了什么 —— 第 1 层的验收视图。"""
    out: list[str] = []
    out.append(H1)
    out.append(f"图纸证据报告  {d.path}")
    out.append(H1)

    # 图元统计
    out.append(_rule("图元统计"))
    counts = d.kind_counts()
    if not counts:
        out.append("  （无图元）")
    for k, n in counts.items():
        out.append(f"  {k:28} {n:6d}")
    out.append(f"  {'合计':28} {len(d.evidence):6d}")

    # 图层
    out.append(_rule("图层"))
    for name in d.layers:
        out.append(f"  {name}")

    # 剖面标题 —— 旧管线整条丢弃的通道
    out.append(_rule("剖面标题（旧管线丢弃的符号通道）"))
    titles = [t for t in d.texts if t.kind == TextKind.SECTION_TITLE]
    if not titles:
        out.append("  （无）")
    for t in titles:
        c = t.cut
        assert c is not None
        loc = (f"切平面 {c.cut_axis}={c.cut_pos:g}" if c.is_located
               else "切平面位置未知")
        extra = []
        if c.radius is not None:
            extra.append(f"r={c.radius:g}")
        if c.diameter is not None:
            extra.append(f"φ={c.diameter:g}")
        out.append(f"  {c.label}  种类={c.kind or '—':8} {loc}"
                   + (f"  {' '.join(extra)}" if extra else ""))
        out.append(f"       依据 {t.handle}  @({t.x:.1f}, {t.y:.1f})")

    # 剖面标记（成对短标记）
    markers = [t for t in d.texts if t.kind == TextKind.SECTION_MARKER]
    if markers:
        out.append(_rule("剖面标记（剖切线两端）"))
        for t in markers:
            out.append(f"  {t.text:6} @({t.x:.1f}, {t.y:.1f})  依据 {t.handle}")

    # 视图标签
    labels = [t for t in d.texts if t.kind == TextKind.VIEW_LABEL]
    out.append(_rule("视图标签"))
    if not labels:
        out.append("  （无）")
    for t in labels:
        out.append(f"  {t.text:8} → {t.view_type:10} @({t.x:.1f}, {t.y:.1f})  "
                   f"依据 {t.handle}")

    # 其它带数值的文字
    notes = [t for t in d.texts if t.kind == TextKind.NOTE]
    out.append(_rule("带数值的文字（技术要求/备注）"))
    if not notes:
        out.append("  （无）")
    for t in notes:
        vals = "  ".join(f"{n}={v:g}" for n, v in t.values)
        out.append(f"  {t.text[:44]:46} {vals}")

    # 尺寸标注
    out.append(_rule("尺寸标注（尺寸 ↔ 几何锚点）"))
    if not d.dimensions:
        out.append("  （无 DIMENSION 实体）")
        out.append("  ⚠ 无标注 ⇒ 符号通道为空，重建只能靠几何反推 ——")
        out.append("     这正是 CLAUDE.md 那张'信息论局限'表的部分成因")
    for dim in d.dimensions:
        v = f"{dim.value:g}" if dim.value is not None else "?"
        anchor = ""
        if dim.p1 is not None and dim.p2 is not None:
            anchor = (f"  锚 ({dim.p1.x:.2f},{dim.p1.y:.2f})"
                      f"↔({dim.p2.x:.2f},{dim.p2.y:.2f})")
        ovr = f"  覆盖文字 '{dim.text_override}'" if dim.is_overridden else ""
        out.append(f"  {dim.dimtype:10} {v:>10}{anchor}{ovr}")

    out.append("")
    return "\n".join(out)


# ---- explain 查询 ----

def explain(d: Drawing, handle: str, claims: list[Claim] | None = None) -> str:
    """溯源一条图元：它是什么、被谁引用。

    这就是"为什么是 25.5？"的答案入口。
    """
    out: list[str] = []
    ev = d.by_handle(handle)
    out.append(H2)
    out.append(f"explain {handle}")
    out.append(H2)
    if ev is None:
        out.append("  图纸里没有这个 handle")
    else:
        out.append(f"  种类   {ev.kind.value}")
        out.append(f"  角色   {ev.role}")
        out.append(f"  图层   {ev.layer or '—'}   线型 {ev.linetype or '—'}")
        if ev.pattern:
            out.append(f"  填充   {ev.pattern}")
        out.append(f"  几何   {ev.geom}")
        out.append(f"  视图   {ev.view or '（未归属）'}")

    # 引用了它的文字
    for t in d.texts:
        if t.handle == handle:
            out.append(f"  文字   种类={t.kind.value}"
                       + (f" 视图={t.view_type}" if t.view_type else ""))
            if t.cut:
                out.append(f"         剖面 {t.cut}")
            if t.values:
                out.append(f"         数值 {list(t.values)}")

    # 其它证据对它的引用（如 HATCH 边界引用 HATCH 本体）
    refs = [e.handle for e in d.evidence
            if handle in [str(r) for r in e.role.evidence]]
    if refs:
        out.append(f"  被引用 由 {', '.join(refs)}")

    if claims:
        out.append(_rule("相关 Claim"))
        for c in claims:
            if handle in [str(r) for r in c.evidence]:
                out.append(f"  {c.method:24} {c}")
    return "\n".join(out)


# ---- 待确认清单 ----

def open_questions_report(questions: list) -> str:
    """列出"不知道什么"—— §2 目标 4 的直接体现。"""
    out = [H2, f"待确认（{len(questions)} 项）", H2]
    if not questions:
        out.append("  （无）")
    for q in questions:
        out.append(f"  • {q}")
    return "\n".join(out)
