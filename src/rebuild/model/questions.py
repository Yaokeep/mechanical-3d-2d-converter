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
    #: 断裂视图（波浪线处断开）—— 该视图沿某方向的坐标**在图纸上就不存在**，
    #: 拿它当完整视图会把尺寸算错且毫无提示（旧管线完全没有这个概念）
    BROKEN_VIEW = "断裂视图（该向尺寸不可用）"
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
class Answer:
    """一条疑问的裁决 —— ``answer`` 是选中的候选（或新的结论）。

    ``by`` 记录**谁做的裁决**（如 ``"revolve:1V0"``）。这个字段不是装饰：
    报告里"这条疑问是谁解的"决定了它的可信度，也让人能顺藤摸到裁决逻辑。
    """

    question: Question
    answer: Any
    by: str = ""

    def __str__(self) -> str:
        return f"{self.question} ⇒ {self.answer}（by {self.by}）"


@dataclass
class QuestionList:
    """待确认项集合 —— 带去重，避免多路推理各报一遍。

    ``resolved`` 是**已裁决**的条目：疑问在后续推理里被新证据消解后，
    不删条目（删了就没人能回答"你当时怎么想的"），而是移到已裁决区并
    记下答案与裁决者。``blocking()`` 之类的下游查询只看未裁决的那部分。
    """

    items: list[Question] = field(default_factory=list)
    resolved: list[Answer] = field(default_factory=list)

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
        """**未裁决**的指定种类疑问（已裁决的不会再拦路）。"""
        return [q for q in self.items if q.kind == kind]

    def find(self, kind: OpenQuestion, view: str = "", *,
             detail_contains: str = "") -> list[Question]:
        """按种类/视图/描述子串找**未裁决**的疑问（消解端的检索入口）。"""
        out = []
        for q in self.items:
            if q.kind != kind:
                continue
            if view and q.view != view:
                continue
            if detail_contains and detail_contains not in q.detail:
                continue
            out.append(q)
        return out

    def resolve(self, q: Question, answer: Any, by: str = "") -> bool:
        """裁决一条疑问：移出待办、记入 ``resolved``。返回是否命中。"""
        if q not in self.items:
            return False
        self.items.remove(q)
        self.resolved.append(Answer(q, answer, by))
        return True

    def __len__(self) -> int:
        return len(self.items)

    def __iter__(self):
        return iter(self.items)
