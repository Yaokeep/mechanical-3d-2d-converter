# -*- coding: utf-8 -*-
"""约定层 —— 规则注册与调度（ARCHITECTURE §5 第 2 层）。

本层的职责：把**制图约定**（"中心线是轴""虚线是不可见的""波浪线处断开"
"均布就是一圈等距"）显式地写成规则，每条规则独立可加、独立可测、
**一条坏掉不拖垮其余的**（见 :func:`run_rules` 的隔离）。

为什么要有"注册"这一层而不是散落的函数：

1. 报告要能说清"这条结论是哪条约定推出来的"（``Convention.rule``），
   否则下游出了问题无从归因 —— 这正是旧管线 8957 行最难查的地方
2. 规则的长尾性（ARCHITECTURE 阶段 2 明写"永远长不完"）要求**增量**：
   加一条不动其余，测试也只针对那一条
3. 失败隔离：某条规则在畸形图纸上抛异常，应当变成一条 OpenQuestion
   而不是让整张图读不出结果

依赖方向：``conventions → model, evidence, views``（不反向）。
本层**不需要 OCC**，跑默认 python。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Callable, Iterable

from ..evidence.model import Drawing
from ..model.claim import Claim
from ..model.ids import EvidenceRef
from ..model.questions import OpenQuestion, Question, QuestionList


class ConvKind(StrEnum):
    """约定结论的种类 —— 决定谁来消费它。"""

    AXIS = "轴线"            # 中心线 ⇒ 3D 轴（位置/方向）
    SYMMETRY = "对称"        # 中心线 ⇒ 对称面（求解器的等式约束）
    PATTERN = "阵列"         # 均布孔 ⇒ 一圈 n 个（图上只画 1~2 个）
    THREAD = "螺纹"          # M8/Tr20 ⇒ 大径小径圆组不是两个孔
    HIDDEN = "不可见"        # 虚线 ⇒ 内部特征存在
    BREAK = "断裂"           # 波浪线/断裂线 ⇒ 该视图沿某轴被缩短
    SECTION = "剖切"         # 全剖/半剖/局部… ⇒ 截面材料的适用范围
    MATERIAL = "被剖到"      # HATCH ⇒ 这块是材料（不是空洞）
    FILLET = "圆角"          # 未注圆角 R2 ⇒ 图上画的尖角其实是圆的


@dataclass(frozen=True)
class BrokenView:
    """断裂视图的识别结果（``ConvKind.BREAK`` 的 value）。

    ``which`` 用**图纸方向**说话（"u" 横向 / "v" 纵向），不写模型轴名 ——
    哪个模型轴对应"横向"是视图坐标系（views 层）的结论，本层不该抢答。
    """

    which: tuple[str, ...]            # 坐标不可用的图纸方向
    bbox: Any = None
    lines: tuple[EvidenceRef, ...] = ()


def by_handle_index(d: Drawing) -> dict[str, Any]:
    """``Drawing.by_handle`` 是**线性扫描** —— 规则里逐 handle 调它等于 O(n²)。

    本层每条规则都要"遍历某视图的全部图元再查它的几何"，故一律先建索引。
    """
    return {e.handle: e for e in d.evidence}


def orient_of(b: Any) -> str | None:
    """包围盒的走向：``"v"`` 竖着 / ``"h"`` 横着 / ``None`` 近方形判不出。"""
    if b.height > b.width * 1.05:
        return "v"
    if b.width > b.height * 1.05:
        return "h"
    return None


def cluster_boxes(items: list[tuple[Any, Any]],
                  gap: float) -> list[list[tuple[Any, Any]]]:
    """按包围盒邻近性**链式**聚类（重叠或间距 < gap 即同类）。

    传入与返回都是 ``[(条目, 包围盒), …]``。波浪线被打散成多段（或本身就是
    折线）时，先合起来再判走向 —— 单段的方向可能毫无意义。
    """
    used = [False] * len(items)
    out: list[list[tuple[Any, Any]]] = []
    for i, (_, box) in enumerate(items):
        if used[i]:
            continue
        used[i] = True
        group, cur = [items[i]], box
        changed = True
        while changed:
            changed = False
            for j, (_, box2) in enumerate(items):
                if used[j]:
                    continue
                if cur.expanded(gap).overlaps(box2):
                    used[j] = True
                    group.append(items[j])
                    cur = cur.union(box2)
                    changed = True
        out.append(group)
    return out


def union_boxes(boxes: Any) -> Any:
    """一组包围盒的并（空集返回 None）。"""
    out = None
    for b in boxes:
        out = b if out is None else out.union(b)
    return out


@dataclass(frozen=True)
class Convention:
    """一条约定推出的结论。

    ``claim`` 承载"这条结论有多可信"，``rule`` 记出处，
    ``view`` 是落点（空表示与具体视图无关，如技术要求里的螺纹代号）。
    """

    rule: str
    kind: ConvKind
    view: str = ""
    value: Any = None
    claim: Claim[Any] | None = None
    note: str = ""
    evidence: tuple[EvidenceRef, ...] = ()

    @property
    def tier(self):
        return self.claim.tier if self.claim is not None else None

    def __str__(self) -> str:
        loc = f"[{self.view}] " if self.view else ""
        t = f"<{self.tier.name}>" if self.tier is not None else ""
        body = self.note or str(self.value)
        return f"{self.kind.value:6} {loc}{t} {body}".replace("  ", " ")


@dataclass
class RuleCtx:
    """规则运行上下文 —— 规则只从这里拿东西，不自己去查全局。"""

    d: Drawing
    qs: QuestionList = field(default_factory=QuestionList)
    #: 视图坐标系；``needs_frames=True`` 的规则在它为 None 时被跳过
    frames: dict[str, Any] | None = None
    #: 已产出的约定（后注册的规则可以看到先注册的结论）
    conv: list[Convention] = field(default_factory=list)

    def views(self):
        return self.d.views

    def by_kind(self, kind: ConvKind) -> list[Convention]:
        return [c for c in self.conv if c.kind == kind]


@dataclass(frozen=True)
class Rule:
    name: str
    fn: Callable[[RuleCtx], Iterable[Convention]]
    needs_frames: bool = False
    doc: str = ""


#: 规则表 —— 注册顺序即执行顺序（先注册的结论对后注册的可见）
_RULES: list[Rule] = []


def register(name: str, needs_frames: bool = False):
    """把一个函数登记成约定规则（装饰器）。"""

    def deco(fn: Callable[[RuleCtx], Iterable[Convention]]):
        _RULES.append(Rule(name=name, fn=fn, needs_frames=needs_frames,
                           doc=(fn.__doc__ or "").strip().split("\n")[0]))
        return fn

    return deco


@dataclass
class Conventions:
    """一次约定推理的全部产出。"""

    items: list[Convention] = field(default_factory=list)
    questions: QuestionList = field(default_factory=QuestionList)
    #: 视图 id → 被断裂缩短的模型轴（该轴的坐标在图纸上不可信）
    broken: dict[str, tuple[str, ...]] = field(default_factory=dict)
    #: 跑挂了的规则 (名字, 异常文本) —— 失败隔离的账本，报告里要露出来
    failed: list[tuple[str, str]] = field(default_factory=list)

    def of_kind(self, kind: ConvKind) -> list[Convention]:
        return [c for c in self.items if c.kind == kind]

    def for_view(self, view_id: str) -> list[Convention]:
        return [c for c in self.items if c.view == view_id]

    def by_rule(self, name: str) -> list[Convention]:
        return [c for c in self.items if c.rule == name]

    def describe(self) -> str:
        lines = [f"约定结论 {len(self.items)} 条"]
        for c in self.items:
            lines.append("  " + str(c))
        if self.broken:
            lines.append("  断裂视图：" + "、".join(
                f"{k}（沿 {'/'.join(v)} 缩短）" for k, v in sorted(self.broken.items())))
        if self.failed:
            lines.append("  规则失败：" + "、".join(n for n, _ in self.failed))
        return "\n".join(lines)


def run_rules(ctx: RuleCtx, only: Iterable[str] | None = None) -> Conventions:
    """按注册顺序跑规则，**逐条隔离**。

    一条规则抛异常 ⇒ 记进 ``failed`` 并转成 OpenQuestion，其余照跑。
    "整张图因为一条规则坏掉而读不出结果"是旧管线最要命的失败模式：
    它不报错，只是安静地少给一些结论。
    """
    out = Conventions(questions=ctx.qs)
    want = set(only) if only is not None else None
    for r in _RULES:
        if want is not None and r.name not in want:
            continue
        if r.needs_frames and ctx.frames is None:
            continue
        try:
            got = list(r.fn(ctx))
        except Exception as exc:                      # noqa: BLE001 —— 隔离是设计目的
            out.failed.append((r.name, f"{type(exc).__name__}: {exc}"))
            ctx.qs.add(Question(
                OpenQuestion.OUT_OF_DOMAIN,
                f"约定规则 {r.name} 执行失败（{type(exc).__name__}: {exc}）—— "
                "本条规则的结论缺失，其余规则不受影响",
            ))
            continue
        for c in got:
            out.items.append(c)
            ctx.conv.append(c)          # 后续规则可见
            # 断裂信息单独汇总：视图坐标系（views 层）要拿它把
            # "图纸横向"翻译成模型轴，再决定该轴坐标是否可信
            if c.kind == ConvKind.BREAK and isinstance(c.value, BrokenView):
                prev = out.broken.get(c.view, ())
                out.broken[c.view] = tuple(sorted(set(prev) | set(c.value.which)))
    return out


def registered() -> list[str]:
    """已注册规则名（供报告与自检列举）。"""
    return [r.name for r in _RULES]
