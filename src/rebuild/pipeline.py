# -*- coding: utf-8 -*-
"""汇流：一张图纸从读入到出模型的**唯一**入口（ARCHITECTURE §8 阶段 4）。

    from src.rebuild.pipeline import rebuild
    r = rebuild("CAD/xx.dxf", step=Path("out.step"))

旧管线的入口是 `dxf_to_3d_general.py` 的 `convert_dxf_to_3d()` —— 一个函数
串起九千行，中间态（视图怎么分的、每个数哪来的）只在日志里。这里把同一件事
拆成**六段可单独调用**的步骤，每段都返回带 provenance 的对象：

    understand()   1–5 段：读 → 分离 → 定性 → 约定 → 对应 → 特征树（默认 python）
    emit_*()       第 6 段：特征树 → OCC B-rep / SW 原生特征树（要 OCC / SW COM）

`rebuild()` 只是把两半接起来并把失败记进 result.errors，不吞异常也不假装成功。

## 为什么"理解"与"发射"分得这么开

前者只需 ezdxf+numpy（默认 python 就能跑，能进 CI），后者要 OCC 或 SW。
更重要的理由是**验收**：理解层的产物（特征树 + 待确认项）可以拿图纸直接判
对错，不必等模型造出来 —— 这正是"仪器先于引擎"的落地方式。发射器只负责
把已定型的 Claim 翻译成几何，它不该有任何决策权。
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .conventions import Conventions, RuleCtx, run_rules
from .evidence import read_dxf
from .features import RecognizeReport, recognize
from .model.questions import OpenQuestion, Question, QuestionList
from .views import build_correspondence, detect_views, type_views

__all__ = ["RebuildResult", "rebuild", "understand"]


@dataclass
class RebuildResult:
    """一次重建的全部产出与全部疑问。"""

    source: Path
    #: 前五段的产物（默认 python 即可得到）
    drawing: Any = None
    conventions: Any = None
    correspondence: Any = None
    report: RecognizeReport | None = None
    #: 第六段的产物（要 OCC / SW COM；不可用或失败时为 None）
    step: Path | None = None
    sldprt: Path | None = None
    #: 发射模型的实体域尺寸 (dx, dy, dz)，发射器量不了时为 None。
    #: 供**发射后自检**用（`extent_questions`）——它必须来自建出来的几何，
    #: 不能来自特征树（那只是自证）
    emitted_extents: tuple[float, float, float] | None = None
    #: 过程话（不含错误）；错误单独放 errors，**不**混进 notes
    notes: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def part(self):
        return self.report.part if self.report is not None else None

    @property
    def questions(self) -> QuestionList:
        return self.report.questions if self.report is not None else QuestionList()

    @property
    def ok(self) -> bool:
        """理解层成功即算成功；发射失败会记在 errors 里，由调用方决定要不要 */"""

        return self.report is not None

    #: 必须由人来定的疑问（`gate` 的输入口径）
    _BLOCKING = (OpenQuestion.AMBIGUOUS_FEATURE, OpenQuestion.MISSING_DIMENSION,
                 OpenQuestion.INCONSISTENT_FRAME, OpenQuestion.OUT_OF_DOMAIN,
                 OpenQuestion.INCONSISTENT_EXTENT)

    def blocking(self) -> list:
        """拦得住发射的待确认项：类型未定的特征、缺尺寸、坐标系冲突、
        发射尺寸与图纸跨度矛盾（P1-C 发射后自检）。

        "投影制未确定"这类**不**在此列 —— 它影响的是镜像方向，
        而镜像在视图坐标系里已经处理过了（`ViewFrame.mirror_axes`）。
        """
        return [q for q in self.questions if q.kind in self._BLOCKING]

    def describe(self) -> str:
        lines = [f"图纸 {self.source}"]
        if self.report is not None:
            lines.append(self.report.describe())
        lines.append("—— 发射 ——")
        lines.append(f"  STEP   {'×' if self.step is None else self.step}")
        lines.append(f"  SLDPRT {'×' if self.sldprt is None else self.sldprt}")
        if self.notes:
            lines.append("—— 过程 ——")
            lines.extend("  " + n for n in self.notes)
        if self.errors:
            lines.append("—— 失败 ——")
            lines.extend("  ! " + e for e in self.errors)
        return "\n".join(lines)

    def as_dict(self) -> dict:
        """机器可读摘要（不含图元细节 —— 那是 `inspect --json` 的活）。"""

        def feats() -> list[dict]:
            out = []
            for f in (self.part.features if self.part else ()):
                out.append({
                    "id": str(f.id), "type": f.type.value,
                    "settled": f.type.is_settled, "tier": f.type.tier.name,
                    "method": f.type.method,
                    "params": {k: {"value": v.value, "tier": v.tier.name,
                                   "alternatives": list(v.alternatives)}
                               for k, v in f.params.items()},
                })
            return out

        return {
            "source": str(self.source),
            "features": feats(),
            "questions": [{"kind": q.kind.value, "view": q.view,
                           "detail": q.detail, "candidates": list(q.candidates)}
                          for q in self.questions],
            "blocking": len(self.blocking()),
            "step": str(self.step) if self.step else None,
            "sldprt": str(self.sldprt) if self.sldprt else None,
            "emitted_extents": list(self.emitted_extents)
            if self.emitted_extents else None,
            "notes": list(self.notes),
            "errors": list(self.errors),
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.as_dict(), ensure_ascii=False, indent=indent,
                          default=str)


# ---- 1~5 段：理解（默认 python 可跑） ----

def understand(path: str | Path, *, qs: QuestionList | None = None
               ) -> tuple[Any, Conventions, Any, RecognizeReport]:
    """DXF → （Drawing, 约定, 对应, 识别报告）。

    六段里前五段的**显式**写法。写出来是为了让调用方能只跑到某一层
    （`inspect` 跑到视图、`verify_legacy` 跑到对应、`selftest` 各层单测），
    而不是每一处都重抄一遍这五行。
    """
    d = read_dxf(path)
    detect_views(d)
    qs = qs if qs is not None else type_views(d)
    conv = run_rules(RuleCtx(d=d))
    qs.extend(conv.questions.items)
    corr = build_correspondence(d, qs, broken=conv.broken)
    rep = recognize(d, corr, conv, qs)
    return d, conv, corr, rep


# ---- 6 段：发射（要 OCC / SW COM） ----

def _emit_occ(part, target: Path, res: RebuildResult,
              allow_guess: bool = False) -> None:
    from . import emit
    if not emit.occ_available():
        res.notes.append("OCC 侧发射器不可用（本解释器没有 pythonocc）"
                         "⇒ 跳过 STEP，理解层结果照常有效")
        return
    try:
        res.step, res.emitted_extents = emit.build_part_occ_with_extents(
            part, target, allow_guess=allow_guess)
        res.notes.append(f"OCC 发射成功：{res.step}")
    except Exception as e:                              # noqa: BLE001 —— 记账不吞
        res.errors.append(f"OCC 发射失败：{type(e).__name__}: {e}")


# ---- 发射后自检：模型 bbox vs 图纸视图跨度（P1-C） ----

#: 容差与验收表同口径：1mm / 0.5%。超出即判"图纸解释不了这块材料"
EXTENT_TOL_MM = 1.0
EXTENT_TOL_FRAC = 0.005

_AXES = ("x", "y", "z")


def drawing_extents(corr) -> dict[str, tuple[float, float]]:
    """图纸各模型轴跨度的**并集**（视图坐标系的图纸读数，绝对坐标）。

    只取 `model_span`（对应层已对齐/镜像/断裂处理过的跨度）；断裂轴的
    span 为 None，不参与 —— 残缺跨度不能当"零件就这么大"的依据。
    """
    ext: dict[str, tuple[float, float]] = {}
    for f in corr.frames.values():
        for a in _AXES:
            sp = f.model_span(a)
            if sp is None:
                continue
            lo, hi = ext.get(a, (sp[0], sp[1]))
            ext[a] = (min(lo, sp[0]), max(hi, sp[1]))
    return ext


def _revolve_sizes(part) -> dict[str, float]:
    """回转体在各轴上能**解释**的尺寸（半径包络）。

    回转体半径由视图里的圆弧直接读出（`axis_revolve` 的短弧簇），但圆弧
    **不撑视图 bbox**：PF60K 俯视图只画 60×60 方框，Ø80 盘的边只在四个
    倒角缺口处露出 r40 的短弧 —— 视图跨度按尺寸算只有 60，模型却是 80。
    所以回转体要单独给出允许量，否则自检会误杀它（实测 9 绿 PF60K）。
    凸台/切除没有这条豁免：它们的外伸必须在图纸里画得出来。
    """
    out: dict[str, float] = {}
    for f in (part.features if part is not None else ()):
        if f.type.value != "revolve":
            continue
        d = f.axis.value.direction
        axis = max((("x", abs(d.x)), ("y", abs(d.y)), ("z", abs(d.z))),
                   key=lambda c: c[1])[0]
        prof = f.params["radius_profile"].value
        rr = [float(r) for _t, r in prof]
        tt = [float(t) for t, _r in prof]
        axial, radial = max(tt) - min(tt), 2.0 * max(rr)
        out[axis] = max(out.get(axis, 0.0), axial)
        for a in _AXES:
            if a != axis:
                out[a] = max(out.get(a, 0.0), radial)
    return out


def extent_questions(part, emitted: tuple[float, float, float] | None,
                     corr) -> list[Question]:
    """发射 bbox 尺寸与图纸跨度矛盾 ⇒ 拦路疑问（可能多条，逐轴）。

    只比**尺寸**，不比绝对位置 —— 图纸系与发射系之间可能有平移
    （回转体基体的轴向平移见 `recognizer._axis_shift`），位置差不是错误。
    允许量 = max(图纸跨度, 回转体包络)；图纸没有该轴跨度时跳过（无依据）。
    """
    if emitted is None or corr is None:
        return []
    drawn = drawing_extents(corr)
    rev = _revolve_sizes(part)
    out: list[Question] = []
    for i, a in enumerate(_AXES):
        if a not in drawn or emitted[i] is None:
            continue
        dsize = drawn[a][1] - drawn[a][0]
        allowed = max(dsize, rev.get(a, 0.0))
        tol = max(EXTENT_TOL_MM, EXTENT_TOL_FRAC * dsize)
        over = emitted[i] - allowed
        if over <= tol:
            continue
        basis = (f"（允许量已放宽到回转体包络 {rev[a]:.2f}）"
                 if rev.get(a, 0.0) > dsize else "")
        out.append(Question(
            OpenQuestion.INCONSISTENT_EXTENT,
            f"{a.upper()} 向发射尺寸 {emitted[i]:.2f} 超出图纸允许 {allowed:.2f}"
            f"（超 {over:.2f} > 容差 {tol:.2f}）：图纸该向跨度 {dsize:.2f}{basis}"
            " —— 多出的材料没有图纸依据，多半是凸台/槽（多料/少料）角色读反，"
            "或基体拉伸方向选错",
        ))
    return out


def _extent_selfcheck(res: RebuildResult, part, corr, *, force: bool) -> None:
    """发射后自检的落地：疑问入册，非 force 时**撤回已写出的文件**。

    为什么是发射后而不是发射前：只有建出来的 B-rep 才知道真实 bbox。用
    特征树的解析包围盒做发射前判据会误杀 —— 切除会裁掉加材料特征的外伸
    （PF60K 的 Ø80 盘外伸后被帽切裁回 60 以内，解析式只看加材料必报超）。
    """
    qs = extent_questions(part, res.emitted_extents, corr)
    if not qs:
        return
    for q in qs:
        res.questions.add(q)                 # 去重由 QuestionList.add 负责
    if force:
        res.notes.append(
            f"发射后自检：{len(qs)} 项尺寸与图纸跨度矛盾（调用方给了 force"
            " ⇒ 模型保留，供诊断）")
        return
    removed: list[str] = []
    for attr in ("step", "sldprt"):
        p = getattr(res, attr)
        if p is None:
            continue
        try:
            Path(p).unlink()
            removed.append(Path(p).name)
        except OSError as e:                             # 删不掉要记账，不能假装撤回
            res.errors.append(f"发射后自检判矛盾，但删不掉 {p}：{e}")
        setattr(res, attr, None)
    res.notes.append(
        "发射后自检发现尺寸与图纸跨度矛盾 ⇒ 已撤回发射"
        + (f"（删除 {', '.join(removed)}）" if removed else "")
        + "。要保留模型做诊断，加 force=True")


def _emit_sw(part, target: Path, res: RebuildResult,
             allow_guess: bool = False) -> None:
    from . import emit
    if not emit.sw_available():
        res.notes.append("SW 侧发射器不可用（SW 未启动 / 无 pywin32）"
                         "⇒ 跳过 .sldprt")
        return
    try:
        res.sldprt = emit.build_part_sw(part, target, allow_guess=allow_guess)
        res.notes.append(f"SW 发射成功：{res.sldprt}")
    except Exception as e:                              # noqa: BLE001
        res.errors.append(f"SW 发射失败：{type(e).__name__}: {e}")


def rebuild(path: str | Path, *, step: Path | None = None,
            sldprt: Path | None = None, sw: bool = False,
            force: bool = False) -> RebuildResult:
    """端到端：图纸 → 特征树 → 模型。

    ``step`` / ``sldprt`` 给 None 表示那一侧不发射。发射失败**不抛**，
    记进 ``result.errors`` —— 因为"理解对了但环境缺 OCC"与"理解错了"
    是两件事，调用方要分得开（`result.ok` 只看理解层）。

    ``force=False``（默认）：存在拦路疑问（`blocking()` 非空，即类型未定的
    特征/缺尺寸/坐标系冲突）时**不发射**，只记一条过程话。理由见 §3 原则一
    —— "知道该拒绝"是这套框架的产出本身，不是失败：歧义未消解就发射，
    等于替用户拍板。``force=True`` 才照样发射（发射器会逐条打 `[GUESS]`），
    它的用途是拿未定型的树去跟旧管线基线做可比性测量。

    发射之后还有一道**自检**（P1-C）：把建出来的模型 bbox 尺寸与图纸视图
    跨度比，超出（且超出部分没有回转体半径包络可解释）就记一条拦路疑问
    `INCONSISTENT_EXTENT`；非 force 时连已写出的文件也一并删掉——不留一个
    "图纸说没有这块材料"的模型在磁盘上。`force=True` 保留模型供诊断。
    """
    src = Path(path)
    res = RebuildResult(source=src)
    d, conv, corr, rep = understand(src)
    res.drawing, res.conventions, res.correspondence, res.report = \
        d, conv, corr, rep
    part = rep.part
    blk = res.blocking()
    if blk and not force:
        kinds = "、".join(sorted({q.kind.value for q in blk}))
        res.notes.append(
            f"有 {len(blk)} 项拦路疑问未消解（{kinds}）⇒ 默认不发射。"
            f"要看「未定型也照建」的结果（例如与旧管线基线比体积），加 force=True")
        return res
    # 放不放行"类型未定"，看**树里的实际状态**，不看疑问清单 —— 清单可能
    # 因为别的原因（缺个深度）非空，而那种情况放行也没用（发射器仍会因
    # 缺必需参数拒绝）。两者口径分开，各自说各自的事。
    guess = any(not f.type.is_settled
                for f in (part.features if part is not None else ()))
    if guess:
        res.notes.append(
            "有类型未定的特征，调用方给了 force ⇒ 按主值发射（每处都打了 [GUESS]）")
    if step is not None:
        _emit_occ(part, Path(step), res, allow_guess=guess)
    if sldprt is not None or sw:
        _emit_sw(part, Path(sldprt) if sldprt
                 else src.with_suffix("").with_name(src.stem + "_重建"),
                 res, allow_guess=guess)
    _extent_selfcheck(res, part, corr, force=force)
    return res
