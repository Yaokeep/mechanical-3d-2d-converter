# -*- coding: utf-8 -*-
"""约束求解 / 一致性检查（ARCHITECTURE §6.2、阶段 3）。

**不是数值优化，是约束传播 + 一致性检查。** 图纸是"示意精确"的：两条线
是否同心/共线/相等**可信**，距离**不可信** —— 所以先抽关系，再让尺寸去
定距离。本模块做三件事：

1. **合并同一参数的多个来源**（``merge_with_conflict``）：值取高 tier，
   证据取并，其余进备选（§3 原则二）。两路都是"图上明标"却数值不符 ⇒
   **冲突**，必须报警而不是挑一个用（§6.2：这是特性不是错误）
2. **先验填充与标注**（``apply_prior``）：标准值只做两件事 ——
   给"只有猜测"的参数填一个 PRIOR 值；给"非标准的实测值"挂上标准值备选
   并说明偏离多少。**它绝不改标注值**（tier 决定优先级，不靠代码自觉）
3. **抽几何关系成约束**（``relations``）：同心/共线/等半径/对称 ——
   这些是求解器消元与 gate 判定的输入

## 为什么不在这里做数值迭代

先把**结构**摆对：关系（可靠）+ 尺寸（不可靠）分开之后，绝大多数尺寸链
顺序可解，不需要迭代。真正的迭代求解器是等到有"过定且冲突"的实例
可以拿来验收时再写 —— 现在写等于凭空设计（§3 原则三：仪器先于引擎）。
"""
from __future__ import annotations

from dataclasses import dataclass, field

from ..model.claim import Claim, Tier
from ..model.feature_tree import Constraint, ConstraintType, Feature, Part
from ..model.geom import Axis3, Vector3
from ..model.ids import FeatureId
from ..model.questions import OpenQuestion, Question, QuestionList
from . import prior as _prior

#: 两路数值"一致"的容差（mm）。取值同 views 层的 MATCH_TOL：
#: 图纸出图与几何量取一致时是 1e-6 级，不一致通常差几毫米
VALUE_TOL = 0.6

#: 参与先验的参数字典：参数名 → 先验种类。
#:
#: **只有半径与直径在这里**：R10/R20 优先数系管的是"配合/刀具决定"的尺寸
#: ——圆角、凹槽、轴径、孔径。板厚、台阶高、拉伸长度是**设计长度**
#: （想多长就多长），把它们往优先数上吸会造出"图纸标 19，我报 20"的假精化。
#: 早期版本把 height/depth/length/width 一并放进来的实测症状：
#: bracket 的 `#1.height 19 → 备选 20`，纯噪声。
_PRIOR_KINDS: dict[str, str] = {
    "radius": "radius",
    "diameter": "diameter",
}


@dataclass(frozen=True)
class Refinement:
    """一次参数精化（进报告，让人看得见"这个数是怎么变的"）。"""

    feature: FeatureId
    param: str
    before: str
    after: str
    reason: str

    def __str__(self) -> str:
        return (f"#{self.feature}.{self.param}: {self.before} → {self.after}"
                f"（{self.reason}）")


@dataclass(frozen=True)
class Conflict:
    """图纸自相矛盾：同一参数的两路声明都够硬却对不上。"""

    label: str
    claims: tuple[Claim, ...]
    detail: str
    feature: FeatureId | None = None

    def __str__(self) -> str:
        vals = " / ".join(f"{c.value!r}（{c.tier.name}，{c.method}）"
                          for c in self.claims)
        return f"{self.label}: {vals} — {self.detail}"


@dataclass
class SolveReport:
    """求解过程的可读输出。"""

    refinements: list[Refinement] = field(default_factory=list)
    conflicts: list[Conflict] = field(default_factory=list)
    constraints: list[Constraint] = field(default_factory=list)
    questions: QuestionList = field(default_factory=QuestionList)
    notes: list[str] = field(default_factory=list)

    def describe(self, questions: bool = True) -> str:
        """``questions=False``：只报约束与精化，待确认项由上层统一列
        （上层与本节共用同一份 ``QuestionList`` 时，不然会印两遍）。"""
        lines = [f"约束 {len(self.constraints)} 条，"
                 f"精化 {len(self.refinements)} 处，"
                 f"冲突 {len(self.conflicts)} 处"]
        for c in self.constraints:
            lines.append(f"  {c}")
        for r in self.refinements:
            lines.append(f"  精化 {r}")
        for c in self.conflicts:
            lines.append(f"  ⚠ 冲突 {c}")
        lines.extend(f"  {n}" for n in self.notes)
        if questions:
            for q in self.questions:
                lines.append(f"  待确认 {q}")
        return "\n".join(lines)


# ---- 1) 合并（带冲突检测） ----

def merge_with_conflict(a: Claim, b: Claim, *, label: str = "",
                        tol: float = VALUE_TOL
                        ) -> tuple[Claim, Conflict | None]:
    """两路声明合一：值取优、证据取并、其余进备选；硬碰硬则报冲突。

    "冲突"的判据从严：**两路都在 ANNOTATED 及以上**才叫冲突。标注与
    轮廓反推不符是常态（出图误差），把它当冲突会淹掉真正的矛盾。
    """
    best, other = ((a, b) if (a.tier, len(a.evidence)) >= (b.tier, len(b.evidence))
                   else (b, a))
    ev = tuple(dict.fromkeys(best.evidence + other.evidence))
    alts = tuple(dict.fromkeys(
        x for x in (best.alternatives
                    + ((other.value,) if other.value != best.value else ())
                    + other.alternatives)
        if x != best.value))
    merged = Claim(best.value, best.method, best.tier, ev, alts)
    conflict = None
    if (a.tier >= Tier.ANNOTATED and b.tier >= Tier.ANNOTATED
            and isinstance(a.value, (int, float)) and isinstance(b.value, (int, float))
            and abs(a.value - b.value) > tol):
        conflict = Conflict(
            label or "同一参数两路标注不一致", (a, b),
            f"两路都是图上明标却差 {abs(a.value - b.value):.2f}"
            f"（容差 {tol:g}）—— 图纸自相矛盾或读错了归属，"
            "不得挑一个用", None)
    return merged, conflict


# ---- 2) 先验 ----

def apply_prior(f: Feature, rep: SolveReport) -> None:
    """标准值先验：只在"填空白"与"提醒"两处出手，**绝不改标注值**。

    这一条直接对应 CLAUDE.md 的"信息论局限"表 ——
    「R8 vs R8.5」：图纸标 φ17 ⇒ 半径 8.5。旧管线只能照抄 8.5；
    这里会把 R8（R10 优先数）挂成**备选**并算清偏离 5.88%，于是
    "真件多半是 R8"这件事第一次出现在报告里，由 gate 去问人。
    """
    for name, kind in _PRIOR_KINDS.items():
        c = f.params.get(name)
        if c is None or not isinstance(c.value, (int, float)):
            continue
        s = _prior.snap_radius(c.value) if kind == "radius" \
            else _prior.snap_diameter(c.value)
        if not s.standard:
            continue
        if not s.changed:
            rep.notes.append(f"#{f.id}.{name} = {c.value:g} 与 {s.source} 标准值一致")
            continue
        if c.tier <= Tier.PRIOR:
            # 只有猜测/先验级的参数 ⇒ 吸附就是改进（值也跟着变）
            new = Claim(s.value, f"prior:{s.source}", Tier.PRIOR,
                        evidence=c.evidence, alternatives=(c.value,))
            f.params[name] = new
            rep.refinements.append(Refinement(
                f.id, name, str(c), str(new),
                f"{s.source} 标准值吸附（原值偏离 {s.delta_pct:.2f}%）"))
            continue
        # 标注/投影级的参数 ⇒ **值不动**，只把标准值挂成备选并说清偏离
        if s.value not in c.alternatives:
            f.params[name] = Claim(c.value, c.method, c.tier, c.evidence,
                                   c.alternatives + (s.value,))
            src = "图上标注" if c.tier >= Tier.ANNOTATED else "投影量得"
            rep.refinements.append(Refinement(
                f.id, name, f"{c.value:g}", f"{c.value:g}（备选 {s.value:g}）",
                f"{src}值不是 {s.source} 标准值（最近 {s.value:g}，"
                f"偏离 {s.delta_pct:.2f}%）—— 值保持原值，标准值进备选待裁决"))
            q = Question(
                OpenQuestion.AMBIGUOUS_FEATURE,
                f"#{f.id}.{name} {src} {c.value:g}，但 {s.source} 标准值是 "
                f"{s.value:g}（偏离 {s.delta_pct:.2f}%）——"
                + ("若这是凹槽/圆角，真值多半取标准值（本条正是 CLAUDE.md "
                   "「R8 vs R8.5」那种情形）" if kind == "radius"
                   else "孔是被钻头加工的，直径通常取标准值"),
                evidence=c.evidence,
                candidates=(f"{s.value:g}（{s.source} 标准值）",
                            f"{c.value:g}（{src}）"))
            rep.questions.add(q)


# ---- 3) 几何关系 ----

def _axis_of(f: Feature) -> Axis3 | None:
    if f.axis is None or f.axis.value is None:
        return None
    return f.axis.value


def _parallel(a: Vector3, b: Vector3) -> bool:
    return abs(abs(a.dot(b)) - 1.0) < 1e-6


def relations(part: Part, rep: SolveReport) -> None:
    """把特征之间**可信的几何关系**抽成约束。

    只抽关系，不定距离 —— 距离由尺寸管（§4.5 的关键判据）。
    """
    axes: list[tuple[Feature, Axis3]] = [(f, a) for f in part.features
                                         if (a := _axis_of(f)) is not None]
    for i, (fa, aa) in enumerate(axes):
        for fb, ab in axes[i + 1:]:
            if not _parallel(aa.direction, ab.direction):
                continue
            d = (ab.origin - aa.origin).cross(aa.direction).norm
            ra, rb = (fa.params.get("radius"), fb.params.get("radius"))
            same_r = (ra is not None and rb is not None
                      and abs(ra.value - rb.value) <= VALUE_TOL)
            if d <= VALUE_TOL:
                rep.constraints.append(Constraint(
                    ConstraintType.COLLINEAR,
                    ((fa.id, "axis"), (fb.id, "axis")),
                    evidence=tuple(fa.evidence[:1] + fb.evidence[:1])))
                if same_r:
                    rep.constraints.append(Constraint(
                        ConstraintType.EQUAL_RADIUS,
                        ((fa.id, "radius"), (fb.id, "radius")),
                        evidence=tuple(fa.evidence[:1] + fb.evidence[:1])))
            elif same_r:
                # 同半径、轴平行但不共线 ⇒ 等半径关系仍成立（是两组相同的孔）
                rep.constraints.append(Constraint(
                    ConstraintType.EQUAL_RADIUS,
                    ((fa.id, "radius"), (fb.id, "radius")),
                    evidence=tuple(fa.evidence[:1] + fb.evidence[:1])))
    for p in (f for f in part.features if f.type.value == "pattern"):
        child = p.params.get("child")
        if child is None:
            continue
        rep.constraints.append(Constraint(
            ConstraintType.CONCENTRIC,
            ((p.id, "center"), (FeatureId(child.value), "axis")),
            evidence=tuple(p.evidence[:1])))
    for s in part.symmetry:
        c = Constraint(ConstraintType.SYMMETRIC, (), s,
                       evidence=s.evidence)
        rep.constraints.append(c)


def solve(part: Part, *, qs: QuestionList | None = None) -> SolveReport:
    """对特征树做一次完整性检查：先验 → 关系 → 冲突 → 欠定。

    就地精化 ``part`` 的参数 Claim（不改值，除非是纯猜测级）。
    """
    rep = SolveReport(questions=qs if qs is not None else QuestionList())
    for f in part.features:
        apply_prior(f, rep)
    relations(part, rep)
    # 欠定：类型或参数仍有歧义的，逐条报出来（gate 的输入）。
    #
    # 两条过滤，都是为了**不重复报**：
    # ① 高于 PROJECTION 的参数（标注/派生）不算"欠定"—— 它们带备选是
    #    有意的（歧义不消解），而那条备选是谁挂上来的、为什么，挂的人
    #    已经用它自己的措辞报过了（如 apply_prior 的"标注 vs 标准值"）。
    #    早期版本把它们一并算进来，bracket 上就出现"#1（boss）仍有未消解
    #    的歧义…radius=25.5(ANNOTATED)"这种把标注明文说成歧义的错报。
    # ② 参数名已被某条待确认项**点名**过（文本里有 `#id.参数名`）的不再重复。
    #    约定：谈某个具体参数时，问题文本一律写成 `#<id>.<参数名>`。
    seen = "\n".join(str(q) for q in rep.questions.items)
    for f in part.unresolved_features():
        if f.type.value == "base":
            continue                    # 基体的近似已在识别阶段报过，不重复
        todo = [(k, f"{k}={v.value!r}({v.tier.name})")
                for k, v in f.params.items()
                if ((v.tier <= Tier.PROJECTION and (not v.is_settled or not v.evidence))
                    or v.is_guessed)
                and f"#{f.id}.{k}" not in seen]
        # **类型**本身没定是比某个参数没定更根本的一件事，得单独算一桩：
        # `_cyl_claim` 在实线/虚线判不出来时给的是 GUESS+备选（孔还是凸台），
        # 而它的 radius/depth 可能是实打实 PROJECTION 带证据的 —— 只说参数
        # 会把它整个漏掉。实测 block_3view 的 4 个 r5 孔：类型未定却一条拦路
        # 疑问都没有，`blocking()` 因此为空，发射闸门形同虚设。
        if not f.type.is_settled and f"#{f.id}.type" not in seen:
            # 文本里带全 `#<id>.type` —— 与参数那条同一套去重约定（上面 `seen`）
            todo.insert(0, ("type",
                            f"#{f.id}.type={f.type.value}({f.type.tier.name})，备选 "
                            f"{[a.value for a in f.type.alternatives]}"))
        if not todo:
            continue
        rep.questions.add(Question(
            OpenQuestion.AMBIGUOUS_FEATURE,
            f"#{f.id}（{f.type.value}）仍有未消解的歧义或纯猜测参数："
            + "、".join(s for _, s in todo),
            evidence=tuple(f.evidence[:1])))
    if part.questions is not rep.questions:     # 同一对象时 extend 会自己迭代自己
        part.questions.extend(rep.questions.items)
    return rep


__all__ = [
    "Conflict", "Refinement", "SolveReport", "VALUE_TOL", "apply_prior",
    "merge_with_conflict", "relations", "solve",
]
