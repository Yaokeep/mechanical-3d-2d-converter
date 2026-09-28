# -*- coding: utf-8 -*-
"""覆盖率（ARCHITECTURE §6.3）。

分两个层次，阶段 0 只做前者：

1. **读取覆盖率**（本模块）：图纸里有多少图元被框架**读到并归位**了 ——
   有没有图元没进任何视图、有没有文字没被分类、有多少数值还只是"推测"。
   它是"图纸 → 理解"的覆盖。
2. **解释覆盖率**（阶段 3~4）：模型的每个特征能不能解释图纸里的图元、
   图纸里的每个图元能不能被某个特征解释（双向）。那需要特征树。

**为什么读取覆盖率现在就有用**：旧管线的失败模式之一是**静默丢弃**
（剖面标题整条丢、视图外图元不理）。丢弃是无声的，所以需要一把
"读到了百分之几"的尺子 —— 数字掉下去就是丢东西了。
"""
from __future__ import annotations

from dataclasses import dataclass, field

from ..evidence.model import Drawing
from ..evidence.text_parser import TextKind
from ..model.claim import Tier
from ..model.questions import Question, QuestionList


@dataclass
class Coverage:
    """一张图纸的读取覆盖率。"""

    n_evidence: int = 0
    n_evidence_in_view: int = 0
    n_texts: int = 0
    n_texts_classified: int = 0
    n_dimensions: int = 0
    #: 逐 tier 的图元数（角色 Claim 的置信度分布）
    tier_hist: dict[str, int] = field(default_factory=dict)
    orphans: list[str] = field(default_factory=list)   # 没进任何视图的图元
    unparsed: list[str] = field(default_factory=list)  # 没分类的文字
    questions: QuestionList = field(default_factory=QuestionList)

    @property
    def evidence_ratio(self) -> float:
        return self.n_evidence_in_view / self.n_evidence if self.n_evidence else 1.0

    @property
    def text_ratio(self) -> float:
        return (self.n_texts_classified / self.n_texts) if self.n_texts else 1.0

    def summary(self) -> str:
        return (f"图元归位 {self.n_evidence_in_view}/{self.n_evidence}"
                f"（{self.evidence_ratio * 100:.1f}%）  "
                f"文字分类 {self.n_texts_classified}/{self.n_texts}"
                f"（{self.text_ratio * 100:.1f}%）  "
                f"标注 {self.n_dimensions} 条")


def coverage(d: Drawing) -> Coverage:
    """算读取覆盖率。孤儿图元与未分类文字一并列出（不静默）。"""
    c = Coverage(n_evidence=len(d.evidence), n_texts=len(d.texts),
                 n_dimensions=len(d.dimensions))

    assigned: set[str] = set()
    for v in d.views:
        assigned |= set(v.all_handles())

    for e in d.evidence:
        key = Tier(e.role.tier).name
        c.tier_hist[key] = c.tier_hist.get(key, 0) + 1
        if e.handle in assigned:
            c.n_evidence_in_view += 1
        else:
            c.orphans.append(str(e.handle))

    for t in d.texts:
        if t.kind in (TextKind.PLAIN, TextKind.UNKNOWN):
            c.unparsed.append(f"{t.handle}:{t.text[:20]}")
        else:
            c.n_texts_classified += 1

    if c.orphans:
        c.questions.add(Question(
            "图元未归入任何视图",
            f"{len(c.orphans)} 个图元不在任何视图内（前几个："
            + ", ".join(c.orphans[:5]) + "）",
            evidence=tuple(c.orphans[:5]),
        ))
    return c


def coverage_report(c: Coverage) -> str:
    """人读的覆盖率报告。"""
    out = [
        "-" * 72,
        "读取覆盖率",
        "-" * 72,
        f"  {c.summary()}",
    ]
    if c.tier_hist:
        dist = "  ".join(f"{k}={v}" for k, v in sorted(c.tier_hist.items()))
        out.append(f"  角色依据分布  {dist}")
    if c.orphans:
        out.append(f"  ⚠ 未归位图元 {len(c.orphans)} 个："
                   + ", ".join(c.orphans[:8]))
    if c.unparsed:
        out.append(f"  未分类文字 {len(c.unparsed)} 条（纯文字/技术要求，"
                   "不含可抽信息属正常）：")
        for u in c.unparsed[:8]:
            out.append(f"    {u}")
    return "\n".join(out)
