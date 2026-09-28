# -*- coding: utf-8 -*-
"""待确认项（ARCHITECTURE §2 目标 4「知道什么时候该拒绝」）。

**这一层不是错误日志，是产品输出。** 一个"图上确实没有这个信息"的结论
和"我算出来了"同样有价值 —— 旧管线的问题是它把两者都当成成功
（见 CLAUDE.md：卷尺模型 X=178 Y=2 Z=14 后强制 Z 拉伸 ×2.90 仍报"重建成功"）。

单独成模块而不是塞在 feature_tree 里：视图定性、约定识别、覆盖率检查
都要产出待确认项，让它们反过来依赖特征树是错的依赖方向。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from .ids import EvidenceRef


class OpenQuestion(StrEnum):
    """欠定项的种类 —— 报告里要明确告诉用户"缺什么"。"""

    MISSING_DIMENSION = "缺尺寸标注"
    MISSING_SECTION_POS = "缺剖切位置"
    AMBIGUOUS_FEATURE = "特征歧义未消解"    # value 与 alternatives 并存
    AMBIGUOUS_VIEW = "视图歧义未消解"        # 同上，但落点是视图定性
    MISSING_VIEW = "缺视图"
    UNREADABLE_NOTE = "标注无法解析"
    UNKNOWN_PROJECTION = "投影制未确定"      # 第一角/第三角判不出
    #: 标注里的坐标与图面几何**不同源**（差镜像/坐标系不一致）——
    #: 不是"缺信息"，是两路证据互相矛盾，必须报出来而不是悄悄选一路
    INCONSISTENT_FRAME = "标注坐标系与图面不一致"
    UNKNOWN_VIEW = "视图未定性"
    OUT_OF_DOMAIN = "超出解释域"             # 自由曲面等（§12）


@dataclass
class Question:
    """一个具体的"待确认"条目。

    ``candidates`` 是**还没排除掉的可能性**（如侧视图是左视图还是右视图）——
    有了它，人只需要回答一个问题，而不是重新看一遍图。
    """

    kind: OpenQuestion
    detail: str
    view: str = ""
    evidence: tuple[EvidenceRef, ...] = ()
    candidates: tuple[Any, ...] = ()

    def __str__(self) -> str:
        loc = f"[{self.view}] " if self.view else ""
        s = f"{loc}{self.kind.value}: {self.detail}"
        if self.candidates:
            s += f"（候选：{' / '.join(str(c) for c in self.candidates)}）"
        return s


@dataclass
class QuestionList:
    """待确认项集合 —— 带去重，避免多路推理各报一遍。"""

    items: list[Question] = field(default_factory=list)

    def add(self, q: Question) -> Question:
        for old in self.items:
            if old.kind == q.kind and old.view == q.view and old.detail == q.detail:
                return old
        self.items.append(q)
        return q

    def extend(self, qs: list[Question]) -> None:
        for q in qs:
            self.add(q)

    def by_kind(self, kind: OpenQuestion) -> list[Question]:
        return [q for q in self.items if q.kind == kind]

    def __len__(self) -> int:
        return len(self.items)

    def __iter__(self):
        return iter(self.items)
