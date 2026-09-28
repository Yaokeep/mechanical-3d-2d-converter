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
from .model.questions import OpenQuestion, QuestionList
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
                 OpenQuestion.INCONSISTENT_FRAME, OpenQuestion.OUT_OF_DOMAIN)

    def blocking(self) -> list:
        """拦得住发射的待确认项：类型未定的特征、缺尺寸、坐标系冲突。

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
        res.step = emit.build_part_occ(part, target, allow_guess=allow_guess)
        res.notes.append(f"OCC 发射成功：{res.step}")
    except Exception as e:                              # noqa: BLE001 —— 记账不吞
        res.errors.append(f"OCC 发射失败：{type(e).__name__}: {e}")


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
    return res
