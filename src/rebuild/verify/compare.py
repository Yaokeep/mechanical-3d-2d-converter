# -*- coding: utf-8 -*-
"""图纸期望 vs 模型实测（ARCHITECTURE §8 阶段 0）。

**不用基准就能判。** 图纸本身给出了模型的三个方向尺寸：

    主视图 (XZ)：宽 = X 向尺寸，高 = Z 向尺寸
    俯视图 (XY)：宽 = X 向尺寸，高 = Y 向尺寸
    左/右视图 (YZ)：宽 = Y 向尺寸，高 = Z 向尺寸

于是每个方向有**两路独立来源**（X 来自主+俯、Z 来自主+侧、Y 来自俯+侧），
两路互校既是图纸自洽性检查、也让"某视图定性错了"暴露出来 ——
这是旧管线完全没有的冗余。

## 判据的主次

1. **比例（尺度无关）**：把两个三元组各自按其最大分量归一化后逐分量比。
   这是主判据 —— 图纸可能是缩比的，绝对尺寸不能直接比。
   实测效力：spoon 图纸归一化 (1, 0.142, 0.231)，重建 (1, 0.011, 0.232)，
   Y 差 13 倍 ⇒ 一眼毙掉。
2. **隐含比例尺**：逐轴 实测/图纸。三者一致 ⇒ 图纸与模型只是缩比；
   都接近 1 ⇒ 1:1，绝对尺寸也对得上。

## 视图定性的不确定怎么处理

俯/仰、左/右的备选（见 views/view_typer.py）**不阻塞判比例** ——
俯视图与仰视图的包围盒尺寸相同，取舍只影响内容不影响尺寸。
所以本模块只用包围盒尺寸，歧义的备选在这里是良性的；
真正受影响的是特征落位，那是阶段 1 之后的事。
"""
from __future__ import annotations

from dataclasses import dataclass, field

from ..evidence.model import Drawing, View, ViewType
from ..model.claim import Claim, Tier, merge
from ..model.ids import EvidenceRef
from ..model.questions import OpenQuestion, Question, QuestionList

#: 归一化比例的相对容差
RATIO_TOL = 0.05
#: 逐轴隐含比例尺之间的一致性容差
SCALE_TOL = 0.02

AXES = ("x", "y", "z")

#: 视图类型 → (横向对应的模型轴, 纵向对应的模型轴)
_AXIS_OF_VIEW: dict[ViewType, tuple[str, str]] = {
    ViewType.FRONT: ("x", "z"),
    ViewType.REAR: ("x", "z"),
    ViewType.TOP: ("x", "y"),
    ViewType.BOTTOM: ("x", "y"),
    ViewType.LEFT: ("y", "z"),
    ViewType.RIGHT: ("y", "z"),
}


def _extreme_refs(d: Drawing, v: View, axis: str, side: str,
                  tol: float = 1e-6) -> tuple[EvidenceRef, ...]:
    """视图在某方向取到极值的那些图元的 handle —— 期望尺寸的**依据**。

    有了它，"X=203.30 是哪儿来的"能一路查到具体哪两条边（``inspect --explain``）。
    """
    assert v.bbox is not None
    target = {"u": {"min": v.bbox.xmin, "max": v.bbox.xmax},
              "v": {"min": v.bbox.ymin, "max": v.bbox.ymax}}[axis][side]
    out: list[EvidenceRef] = []
    for ref in v.evidence:
        e = d.by_handle(ref)
        if e is None:
            continue
        b = e.exact_bbox
        if axis == "u":
            edge = b.xmin if side == "min" else b.xmax
        else:
            edge = b.ymin if side == "min" else b.ymax
        if abs(edge - target) <= tol:
            out.append(ref)
        if len(out) >= 3:
            break
    return tuple(out)


@dataclass
class Expected:
    """图纸给出的模型三向尺寸（图纸单位，通常 mm）。"""

    spans: dict[str, Claim[float]] = field(default_factory=dict)
    #: 每路的原始观测，用于报告与冲突诊断
    observations: list[tuple[str, str, float]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    questions: QuestionList = field(default_factory=QuestionList)

    @property
    def missing(self) -> list[str]:
        return [a for a in AXES if a not in self.spans]

    def triple(self) -> tuple[float, float, float] | None:
        if self.missing:
            return None
        return (self.spans["x"].value, self.spans["y"].value,
                self.spans["z"].value)


#: 同一轴向的两路观测在多大差异内算"一致"（mm）
AGREE_TOL_ABS = 0.5
#: 相对部分：大零件允许成比例的更大差异
AGREE_TOL_FRAC = 0.005


def _combine(obs: list[Claim[float]], axis: str
             ) -> tuple[Claim[float], str, Question | None]:
    """把同一轴向的多路观测合成一个 Claim。

    **一致就不该记成歧义。** 浮点噪声会让两次相同的测量差出 1e-13 ——
    若照搬 ``merge()``（值不等即进备选），三视图 bracket 的 X 会平白变成
    "未定"，把本该 ACCEPT 的模型降级成 NEEDS_CONFIRMATION。
    故先按容差判等：容差内 ⇒ 取均值、算已定；超出 ⇒ 才保留备选并报冲突。

    Returns:
        (Claim, 一行说明, 冲突时的 Question；一致时为 None)
    """
    if len(obs) == 1:
        c = obs[0]
        return c, f"{axis} 向单路来源 {c.value:.3f}（{c.method}）", None

    values = [c.value for c in obs]
    spread = max(values) - min(values)
    tol = max(AGREE_TOL_ABS, AGREE_TOL_FRAC * max(values))
    detail = "、".join(f"{v:.3f}" for v in values)
    if spread <= tol:
        return (
            Claim(sum(values) / len(values),
                  "views:" + "+".join(c.method for c in obs), Tier.PROJECTION,
                  evidence=tuple(r for c in obs for r in c.evidence)),
            f"{axis} 向 {len(obs)} 路观测一致（{detail}，差 {spread:.3f}）",
            None,
        )

    return (
        merge(obs),
        f"{axis} 向两路来源不一致（差 {spread:.2f}）：{detail}",
        Question(
            OpenQuestion.AMBIGUOUS_VIEW,
            f"{axis} 向尺寸两路来源不一致，差 {spread:.2f}（{detail}）—— "
            "可能是视图定性错、视图内混入多余图元（如剖切线/引出线）、"
            "或出图侧轮廓近似误差",
            candidates=tuple(f"{c.value:.2f}" for c in obs),
        ),
    )


def expect_from_drawing(d: Drawing) -> Expected:
    """从视图包围盒推模型三向尺寸。

    只用正投影视图（主/俯/仰/左/右/后）；**剖视图不参与** ——
    剖视图只画剖切到的那一块，它的包围盒不是零件的完整尺寸
    （bracket 的 C—C 剖是 40.03 × 28.00，而零件是 204 × 51 × 44）。
    """
    ex = Expected()
    per_axis: dict[str, list[Claim[float]]] = {a: [] for a in AXES}

    for v in d.views:
        t = v.resolved_type
        if t is None or v.bbox is None or t not in _AXIS_OF_VIEW:
            continue
        if t == ViewType.SECTION:
            continue
        ax_u, ax_v = _AXIS_OF_VIEW[t]
        for drawing_axis, model_axis, span in (
            ("u", ax_u, v.bbox.xmax - v.bbox.xmin),
            ("v", ax_v, v.bbox.ymax - v.bbox.ymin),
        ):
            lo = _extreme_refs(d, v, drawing_axis, "min")
            hi = _extreme_refs(d, v, drawing_axis, "max")
            refs = lo + hi
            if not refs:
                continue          # 无依据的尺寸不进 Claim（架构原则一）
            claim = Claim(
                span, f"view:{v.id}.{drawing_axis}", Tier.PROJECTION,
                evidence=refs,
            )
            per_axis[model_axis].append(claim)
            ex.observations.append((v.id, f"{model_axis}（{t.value}）", span))

    for a in AXES:
        obs = per_axis[a]
        if not obs:
            continue
        claimed, note, conflict = _combine(obs, a)
        ex.spans[a] = claimed
        ex.notes.append(note)
        if conflict is not None:
            ex.questions.add(conflict)

    if ex.missing:
        ex.questions.add(Question(
            OpenQuestion.MISSING_VIEW,
            "缺视图，无法确定 " + "/".join(a.upper() for a in ex.missing)
            + " 向尺寸（需要主+俯才给出 X/Y，主+侧才给出 Z）",
            candidates=tuple(a.upper() for a in ex.missing),
        ))
    return ex


# ---- 对比 ----

def _normalize(t: tuple[float, float, float]) -> tuple[float, float, float]:
    m = max(abs(v) for v in t)
    return tuple(v / m for v in t) if m > 0 else t


@dataclass
class Comparison:
    """图纸期望 vs 模型实测的对比结果。"""

    expected: tuple[float, float, float] | None
    measured: tuple[float, float, float] | None
    #: 逐轴 (实测 - 图纸) / 图纸
    rel_error: dict[str, float] = field(default_factory=dict)
    #: 逐轴隐含比例尺 实测/图纸
    implied_scale: dict[str, float] = field(default_factory=dict)
    #: 归一化后逐轴偏差
    ratio_error: dict[str, float] = field(default_factory=dict)
    failing_axes: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    questions: QuestionList = field(default_factory=QuestionList)

    @property
    def ratio_ok(self) -> bool:
        return not self.failing_axes

    @property
    def scale_uniform(self) -> bool:
        if len(self.implied_scale) < 2:
            return True
        vals = list(self.implied_scale.values())
        return (max(vals) - min(vals)) / max(vals) <= SCALE_TOL


def compare(expected: Expected,
            measured: tuple[float, float, float] | None) -> Comparison:
    """比图纸期望与实测三向尺寸。尺度无关的比例为主判据。"""
    c = Comparison(expected.triple(), measured)
    c.questions.extend(list(expected.questions))

    if c.expected is None or c.measured is None:
        c.notes.append("尺寸不完整，无法对比")
        return c

    for i, a in enumerate(AXES):
        e, m = c.expected[i], c.measured[i]
        c.implied_scale[a] = m / e if e else float("nan")
        c.rel_error[a] = (m - e) / e if e else float("nan")

    ne, nm = _normalize(c.expected), _normalize(c.measured)
    for i, a in enumerate(AXES):
        err = abs(nm[i] - ne[i])
        c.ratio_error[a] = err / ne[i] if ne[i] else err
        if c.ratio_error[a] > RATIO_TOL:
            c.failing_axes.append(a)
            c.notes.append(
                f"{a.upper()} 向比例不符：图纸 {ne[i]:.4f} vs 模型 {nm[i]:.4f}"
                f"（偏离 {c.ratio_error[a] * 100:.1f}%，容差 {RATIO_TOL * 100:.0f}%）"
            )

    if not c.scale_uniform:
        vals = "、".join(f"{a.upper()} {c.implied_scale[a]:.3f}" for a in AXES)
        c.notes.append(f"逐轴比例尺不一致（{vals}）—— 模型被单方向拉伸过")
    else:
        s = sum(c.implied_scale.values()) / len(c.implied_scale)
        c.notes.append(f"隐含比例尺 {s:.4f}"
                       + ("（1:1）" if abs(s - 1) <= SCALE_TOL
                          else "（图纸与模型相差缩比，比例判定不受影响）"))
        if abs(s - 1) > SCALE_TOL:
            c.questions.add(Question(
                OpenQuestion.UNKNOWN_VIEW,
                f"图纸与模型相差 {s:.4f} 倍 —— 若图纸是 1:1 出图则为模型的整体缩放",
            ))
    return c
