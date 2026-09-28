# -*- coding: utf-8 -*-
"""判决 —— ACCEPT / REJECT / NEEDS_CONFIRMATION（ARCHITECTURE §7 收敛条件）。

**判不过是拒绝，不是"照常输出 + 警告"。** 这是与旧管线最根本的分别：
`dxf_to_3d_general.py` 在 spoon 上图元只剩 2 条棱柱相交、主体 X=178 Y=2 Z=14，
随后强制把 Z 拉伸 ×2.90 补齐，最后照样打印"CSG 重建成功！"。
一个不说"我不确定"的系统，它的"成功"没有信息量。

判定顺序（先否定、后降级）：

1. 测不出模型（STEP 读不了 / 没有 SOLID）        → ERROR
2. 比例不符（尺度无关的主判据）                  → REJECT
3. 图纸尺寸本身有冲突（两路来源不齐 / 缺视图）    → NEEDS_CONFIRMATION
4. 其余                                            → ACCEPT（并附上已知待确认项）

第 2 步优先于第 3 步：**已经证伪的结论不该因为有别的不确定而降级**。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from ..model.questions import QuestionList
from .compare import RATIO_TOL, Comparison, Expected


class Verdict(StrEnum):
    ACCEPT = "ACCEPT"
    REJECT = "REJECT"
    NEEDS_CONFIRMATION = "NEEDS_CONFIRMATION"
    ERROR = "ERROR"


@dataclass
class GateResult:
    verdict: Verdict
    reasons: list[str] = field(default_factory=list)
    questions: QuestionList = field(default_factory=QuestionList)
    comparison: Comparison | None = None
    expected: Expected | None = None

    @property
    def ok(self) -> bool:
        return self.verdict == Verdict.ACCEPT

    def __str__(self) -> str:
        return f"{self.verdict.value}（{len(self.questions)} 项待确认）"


def decide(cmp: Comparison, expected: Expected,
           measured_ok: bool = True, measure_error: str = "") -> GateResult:
    """按上表判决。``measured_ok=False`` 表示模型侧没量到。"""
    g = GateResult(Verdict.ACCEPT, comparison=cmp, expected=expected)
    g.questions.extend(list(cmp.questions))

    # 1) 模型侧没量到 —— 不是"通过"
    if not measured_ok or cmp.measured is None:
        g.verdict = Verdict.ERROR
        g.reasons.append(measure_error or "模型侧没有可用的实测尺寸")
        return g

    # 2) 比例不符 —— 直接毙掉，不给"待确认"的余地
    if cmp.failing_axes:
        g.verdict = Verdict.REJECT
        g.reasons.extend(cmp.notes)
        g.reasons.append(
            "主判据（尺度无关比例）不通过："
            + "、".join(a.upper() for a in cmp.failing_axes))
        return g

    # 3) 图纸侧信息不齐或有冲突 —— 判不了，不是通过
    if cmp.expected is None or expected.missing:
        g.verdict = Verdict.NEEDS_CONFIRMATION
        g.reasons.append(
            "图纸未能给出全部三向尺寸（缺 "
            + "/".join(a.upper() for a in expected.missing) + "）")
        return g
    unsettled = [a for a, c in expected.spans.items() if not c.is_settled]
    if unsettled:
        g.verdict = Verdict.NEEDS_CONFIRMATION
        g.reasons.append(
            "图纸尺寸有两路来源不一致（" + "、".join(a.upper() for a in unsettled)
            + "），先确认视图定性")
        return g

    # 4) 通过 —— 但把已知待确认项原样附上，不藏
    g.reasons.extend(cmp.notes)
    g.reasons.append(f"三向尺寸比例一致（容差 {RATIO_TOL * 100:.0f}%）")
    if g.questions:
        g.reasons.append(
            f"仍有 {len(g.questions)} 项待确认（视图定性级别的歧义，"
            "不影响尺寸判定）")
    return g
