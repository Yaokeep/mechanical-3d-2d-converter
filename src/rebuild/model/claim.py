# -*- coding: utf-8 -*-
"""Claim —— 本框架里唯一的数值载体。

设计原则（docs/ARCHITECTURE.md §3 原则一）：
**系统里不存在裸数值。** 每个数字都带依据、方法、置信度、备选。

这一个决定把"读符号 / 约定语法 / 零件先验 / 知道拒绝"四层能力
从四个独立功能变成一个结构上的必然结果 —— 第 4 层塌缩成对
Claim 置信度与剩余备选的查询，而不是一个外加模块。

注意：**刻意不提供 `__float__` 等隐式转换**。取用必须显式写 `.value`，
这样"这里用了个裸值"在代码审查时是可见的。
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from enum import IntEnum
from typing import Generic, Iterable, TypeVar

from .ids import EvidenceRef

T = TypeVar("T")


class Tier(IntEnum):
    """置信度分级。**顺序即优先级** —— gate 按此判定（ARCHITECTURE §4.1）。

    高 tier 覆盖低 tier：同一参数的多个 Claim 取最高者，
    这正是"图上明标的尺寸"压过"从轮廓反推"的机制。
    """

    GUESS = 0       # 兜底启发式 —— 一律进"待确认"
    PRIOR = 1       # 按标准/先验推测（标准值吸附：实测 7.94 → R8）
    PROJECTION = 2  # 由跨视图对应 + 投影射线得出
    DERIVED = 3     # 由约束求解得出（尺寸链闭合推出未标尺寸）
    CONVENTION = 4  # 按制图约定推出（中心线⇒轴线、HATCH⇒被剖到）
    ANNOTATED = 5   # 图上明标（尺寸文字 / DIMENSION 实体）—— 最可信


#: 报告用的中文标签（report.py 消费）
TIER_LABEL: dict[Tier, str] = {
    Tier.ANNOTATED: "图上标注",
    Tier.CONVENTION: "制图约定",
    Tier.DERIVED: "约束求解",
    Tier.PROJECTION: "投影对应",
    Tier.PRIOR: "标准先验",
    Tier.GUESS: "推测",
}

#: 无需证据即可成立的 tier（其余 tier 必须带 evidence，见 __post_init__）
_TIERS_WITHOUT_EVIDENCE = frozenset({Tier.PRIOR, Tier.GUESS})


@dataclass(frozen=True)
class Claim(Generic[T]):
    """一个带依据的数值。

    Args:
        value:        当前最优取值
        method:       来源方法，命名空间化：``"dimension"`` / ``"note:section_title"``
                      / ``"convention:centerline"`` / ``"constraint:chain"`` / ``"prior:series"``
        tier:         置信度分级
        evidence:     支持它的 DXF 图元 handle（**没依据就不许高 tier**）
        alternatives: 未消解的分支 —— 非空即"未定"，gate 必须降级处理

    典型用法::

        Claim(121.89, "note:section_title", Tier.ANNOTATED, evidence=(ref,))
        Claim(7.94, "projection:circle", Tier.PROJECTION, evidence=(ref,)).with_tier(
            Tier.PRIOR, method="prior:series", value=8.0)
    """

    value: T
    method: str
    tier: Tier = Tier.GUESS
    evidence: tuple[EvidenceRef, ...] = ()
    alternatives: tuple[T, ...] = ()

    def __post_init__(self) -> None:
        # 无依据的只能是推测 —— 防止"凭空的图上标注"这类谎报
        if not self.evidence and self.tier not in _TIERS_WITHOUT_EVIDENCE:
            raise ValueError(
                f"tier={self.tier.name} 必须带 evidence（method={self.method!r}）；"
                f"无依据的结论只能是 {sorted(t.name for t in _TIERS_WITHOUT_EVIDENCE)}"
            )
        # value 是当前最优，不应同时出现在备选里
        if self.value in self.alternatives:
            raise ValueError(f"value={self.value!r} 不应同时出现在 alternatives 里")

    # ---- 状态查询（第 4 层"知道拒绝"就建在这两个属性上） ----

    @property
    def is_settled(self) -> bool:
        """歧义是否已消解。False ⇒ 进"待确认"。"""
        return not self.alternatives

    @property
    def is_trusted(self) -> bool:
        """是否可信到可以据此下结论（已定且依据够硬）。"""
        return self.is_settled and self.tier >= Tier.CONVENTION

    @property
    def is_guessed(self) -> bool:
        """是否属于"我猜的"—— 一律要报给用户。"""
        return self.tier <= Tier.PRIOR

    # ---- 精化 ----

    def with_tier(
        self,
        tier: Tier,
        method: str | None = None,
        evidence: tuple[EvidenceRef, ...] | None = None,
    ) -> "Claim[T]":
        """换依据/置信度，值不变。

        用于求解器逐级精化：``PROJECTION`` → 撞上图上标注 → ``ANNOTATED``。
        """
        return replace(
            self,
            tier=tier,
            method=self.method if method is None else method,
            evidence=self.evidence if evidence is None else evidence,
        )

    def refined(self, value: T, method: str, tier: Tier,
                evidence: tuple[EvidenceRef, ...] = ()) -> "Claim[T]":
        """换值并带上新依据；旧值进 alternatives（保留歧义，不丢弃）。"""
        alts = tuple(a for a in (self.value,) + self.alternatives if a != value)
        return Claim(value, method, tier, evidence, alts)

    # ---- 比较 ----

    @classmethod
    def best(cls, claims: Iterable["Claim[T]"]) -> "Claim[T]":
        """取置信度最高者；并列时取 evidence 最多者（依据越厚越可信）。"""
        items = list(claims)
        if not items:
            raise ValueError("Claim.best() 收到空集")
        return max(items, key=lambda c: (c.tier, len(c.evidence)))

    def __str__(self) -> str:  # 报告用
        tier = TIER_LABEL.get(self.tier, self.tier.name)
        s = f"{self.value!r} <{tier}>"
        if not self.is_settled:
            s += f" 备选{list(self.alternatives)}"
        return s


def merge(claims: Iterable[Claim[T]]) -> Claim[T]:
    """把同一参数的多路 Claim 合成一个：取最优，其余进备选。

    这是"歧义不提前消解"（§3 原则二）的落地方式 —— 多路推理各出一份，
    合成后仍保留备选，由 gate 判定是否已消解。
    """
    items = list(claims)
    best = Claim.best(items)
    alts = tuple(
        c.value for c in items
        if c is not best and c.value != best.value and c.value not in best.alternatives
    )
    return replace(best, alternatives=best.alternatives + alts)
