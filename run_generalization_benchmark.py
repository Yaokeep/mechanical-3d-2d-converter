#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""通用性盲测表（P0）：held-out 图纸 → 特征树 → STEP 的**体检仪**。

与 `run_rebuild_acceptance.py` 的分工必须分清：

    验收表（run_rebuild_acceptance.py） = **回归门**。
        靶子都是参与过开发的（6 简单件 + bracket + PF60K），判 [OK]/[RED]，
        红了就是回归，必须修。
    本表（run_generalization_benchmark.py） = **诊断仪**。
        靶子是从未参与 `src/rebuild/` 开发的 held-out 件，**不判红绿**——
        输出的是"读懂了多少 / 卡在哪 / force 照建会偏多少"，用来回答
        "框架是不是只会做 YZYX"，而不是"这版有没有退化"。

判读口径：
  * `gate=pass`   —— 拦路疑问 0，框架自己认为可以发射；
  * `gate=blocked`—— 有拦路疑问，默认拒绝发射（这是框架的设计产出，不是 bug）。
    2026-10-17 P1-C 起 gate 包含**发射后自检**（模型 bbox vs 图纸视图跨度，
    `INCONSISTENT_EXTENT`）——所以本脚本第 1 遍就真的发射一次；自检判矛盾时
    管线会把刚写出的 STEP 删掉。本脚本默认再用 `force=True` 照建一份，
    **仅用于量化"硬推会偏多少"**，体积/bbox 偏差不计成败。
  * `volume ±%`   —— force 模型 vs 金值；`gate=pass` 时才是真正的精度信号。

金值来源（均已核实）：
  * D79307 / IMU —— `sw_export_step.py` 从 `三维/*.SLDPRT` 导出的时间戳 STEP
    （命名规则 `<stem>_<YYYYmmdd_HHMMSS>.step`，见该脚本 `export_sldprt_to_step`）；
  * 轴测量 —— `三维/轴测量.STEP`（旧管线 100% 覆盖靶子的同一基准）；
  * spoon  —— `三维/spoon.STEP`。

⚠️ 这些图纸来自 `model_to_drawing.py` 的闭环出图（与管线同源），不是第三方
图纸；它们能检验"换零件几何是否还读得动"，但**不能**替代真实第三方图纸。
后续 P0.5 应补入非闭环来源的图纸。

用法：
    PY=/c/Users/yaoshuo/miniconda3/envs/cad-occt/python.exe
    PYTHONIOENCODING=utf-8 $PY run_generalization_benchmark.py [靶子...]
    PYTHONIOENCODING=utf-8 $PY run_generalization_benchmark.py --sections  # 连剖面图版本一起测
    PYTHONIOENCODING=utf-8 $PY run_generalization_benchmark.py --no-force  # 有拦路就不发射

报告写到 `CAD/temp_output/_generalization_report.md`（`_` 前缀，gitignored）。
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "CAD" / "temp_output"
REPORT_MD = OUT / "_generalization_report.md"
REPORT_JSON = OUT / "_generalization_report.json"


@dataclass(frozen=True)
class Case:
    name: str
    dxf: str
    gold: str
    note: str
    #: 同一零件的剖面图版本（图纸是闭环出图，零件相同、金值相同）
    section_dxf: str | None = None


CASES: dict[str, Case] = {
    "D79307": Case(
        name="D79307",
        dxf="CAD/temp_output/D79307A264FCA6D8EC32E95B1B11BDBD.dxf",
        gold="CAD/temp_output/D79307A264FCA6D8EC32E95B1B11BDBD_20261001_190520.step",
        note="35×20×40 拱形件（旧管线已完成 −0.001%）",
        section_dxf="CAD/temp_output/D79307A264FCA6D8EC32E95B1B11BDBD_剖面图.dxf",
    ),
    "IMU": Case(
        name="IMU",
        dxf="CAD/temp_output/IMU.dxf",
        gold="CAD/temp_output/IMU_20261001_185624.step",
        note="40×20×45（旧管线出图靶子）",
        section_dxf="CAD/temp_output/IMU_剖面图.dxf",
    ),
    "轴测量": Case(
        name="轴测量",
        dxf="CAD/temp_output/轴测量.dxf",
        gold="三维/轴测量.STEP",
        note="L 形底 + r20 半圆槽 + 三角楔形槽（旧管线 100% 覆盖）",
        section_dxf="CAD/temp_output/轴测量_剖面图.dxf",
    ),
    "spoon": Case(
        name="spoon",
        dxf="CAD/temp_output/spoon_三视图.dxf",
        gold="三维/spoon.STEP",
        note="勺形自由曲面件（无剖面图版本）",
        section_dxf=None,
    ),
}


@dataclass
class Result:
    case: str
    dxf: str
    note: str
    n_features: int = 0
    n_questions: int = 0
    n_blocking: int = 0
    question_kinds: dict[str, int] = field(default_factory=dict)
    blocking_details: list[str] = field(default_factory=list)
    gate: str = "?"
    force_used: bool = False
    gold_volume: float | None = None
    volume: float | None = None
    volume_delta_pct: float | None = None
    gold_extents: tuple | None = None
    extents: tuple | None = None
    bbox_delta: tuple | None = None
    n_solids: int | None = None
    step: str | None = None
    errors: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def _measure(path: Path):
    from src.rebuild.verify.step_probe import probe_step
    return probe_step(path)


def run_case(case: Case, *, force_blocked: bool) -> Result:
    from src.rebuild.pipeline import rebuild

    res = Result(case=case.name, dxf=case.dxf, note=case.note)
    p = ROOT / case.dxf
    gold_p = ROOT / case.gold
    if not p.exists():
        res.errors.append(f"图纸不存在：{case.dxf}")
        return res
    if not gold_p.exists():
        res.errors.append(f"金值不存在：{case.gold}")
        return res

    # ---- 第 1 遍：完整流程（含**发射后自检**），gate 以这一步为准 ----
    # 2026-10-17 P1-C 起 gate 不再只是"理解层疑问清单"：`rebuild(step=...)`
    # 建完会拿模型 bbox 与图纸跨度比，矛盾记 INCONSISTENT_EXTENT 并把文件删掉。
    # 所以这里必须真的走一遍发射——只调 `rebuild(p)` 会漏掉发射后自检。
    out = OUT / f"_gen_{case.name}.step"
    if out.exists():
        out.unlink()          # 防止上一次的残留文件让"已发射"判断失真
    r = rebuild(p, step=out)
    res.notes = list(r.notes)
    res.errors = list(r.errors)
    if r.part is None:
        res.gate = "no-part"
        return res
    res.n_features = len(r.part.features)
    res.n_questions = len(r.questions)
    blk = r.blocking()
    res.n_blocking = len(blk)
    res.question_kinds = dict(Counter(q.kind.value for q in r.questions))
    res.blocking_details = [f"[{q.kind.value}] {getattr(q, 'detail', '')[:180]}"
                            for q in blk[:8]]
    res.gate = "blocked" if blk else "pass"
    if blk:
        if not force_blocked:
            return res
        # ---- 第 2 遍：有拦路时 force 硬推，仅量化"未定型照建会偏多少" ----
        res.force_used = True
        r = rebuild(p, step=out, force=True)
        res.notes.extend(n for n in r.notes if n not in res.notes)
        res.errors.extend(e for e in r.errors if e not in res.errors)
    if r.step is None or not Path(r.step).exists():
        return res
    res.step = str(r.step)
    m = _measure(Path(r.step))
    if not m.ok:
        res.errors.append(f"STEP 读不回：{m.error}")
        return res
    g = _measure(gold_p)
    if not g.ok:
        res.errors.append(f"金值 STEP 读不回：{g.error}")
        return res
    res.gold_volume = g.volume
    res.volume = m.volume
    res.volume_delta_pct = ((m.volume - g.volume) / g.volume * 100.0
                            if g.volume else None)
    res.gold_extents = tuple(g.extents) if g.extents else None
    res.extents = tuple(m.extents) if m.extents else None
    if res.gold_extents and res.extents:
        res.bbox_delta = tuple(a - b for a, b in zip(res.extents, res.gold_extents))
    res.n_solids = m.n_solids
    return res


def _fmt(v: float | None, nd: int = 2) -> str:
    return "-" if v is None else f"{v:+.{nd}f}"


def verdict(res: Result) -> str:
    """给一次体检下**诊断**（不是红绿门）。

    最关键的一类不是 blocked，而是 **silent-wrong**：gate 认为没问题、
    实际体积/bbox 大偏——框架连"自己在猜"都不知道。这类比拒绝危险得多。
    """
    if res.gate == "blocked":
        return "拒绝（正确行为）"
    if res.gate == "no-part":
        return "理解失败"
    if res.volume_delta_pct is None:
        return "发射失败"
    bad_v = abs(res.volume_delta_pct) > 0.5
    bad_b = bool(res.bbox_delta) and any(abs(x) > 1.0 for x in res.bbox_delta)
    if bad_v or bad_b:
        return "**静默错误（gate 未拦住）**"
    return "命中"


def print_result(res: Result) -> None:
    tag = {"pass": "[GATE-PASS]", "blocked": "[BLOCKED ]",
           "no-part": "[NO-PART  ]"}.get(res.gate, "[?        ]")
    line = (f"{tag} {res.case:<10} {res.n_features:>2} 特征  "
            f"疑问 {res.n_questions:>2}（拦路 {res.n_blocking}）")
    if res.volume is not None:
        line += (f"  体积 {res.volume:>11,.1f} vs {res.gold_volume:>11,.1f} "
                 f"{_fmt(res.volume_delta_pct)}%  "
                 f"bbox 差 {' '.join(_fmt(x) for x in (res.bbox_delta or ()))}  "
                 f"实体 {res.n_solids}")
    if res.force_used:
        line += "  [force 硬推]"
    line += f"  判定：{verdict(res)}"
    print(line)
    if res.question_kinds:
        kinds = ", ".join(f"{k}×{v}" for k, v in
                          sorted(res.question_kinds.items(), key=lambda kv: -kv[1]))
        print(f"{'':<12}疑问构成：{kinds}")
    for d in res.blocking_details[:3]:
        print(f"{'':<12}拦路：{d}")
    for e in res.errors[:3]:
        print(f"{'':<12}! {e}")


def write_report(results: list[Result]) -> None:
    lines = ["# 通用性盲测报告（P0）", "",
             "> 诊断仪输出，**不判红绿**。`gate=blocked` 是框架按设计拒绝发射，",
             "> 不是 bug；`[force 硬推]` 行的体积偏差只用于量化欠定程度。", ""]
    lines += ["| 靶子 | 特征 | 疑问(拦路) | gate | 体积 vs 金值 | 体积差 | bbox 差 | 实体 | 判定 | 备注 |",
              "|---|---:|---:|---|---:|---:|---|---:|---|---|"]
    for r in results:
        vol = (f"{r.volume:,.1f} / {r.gold_volume:,.1f}"
               if r.volume is not None else "-")
        bb = (" ".join(_fmt(x) for x in r.bbox_delta)
              if r.bbox_delta else "-")
        lines.append(
            f"| {r.case} | {r.n_features} | {r.n_questions}({r.n_blocking}) | "
            f"{r.gate}{' / force' if r.force_used else ''} | {vol} | "
            f"{_fmt(r.volume_delta_pct)}% | {bb} | {r.n_solids or '-'} | "
            f"{verdict(r)} | {r.note} |")
    lines += ["", "## 逐靶子疑问构成", ""]
    for r in results:
        lines.append(f"### {r.case}")
        lines.append("")
        if r.question_kinds:
            for k, v in sorted(r.question_kinds.items(), key=lambda kv: -kv[1]):
                lines.append(f"- `{k}` × {v}")
        else:
            lines.append("- 无")
        for d in r.blocking_details:
            lines.append(f"- 拦路：{d}")
        for e in r.errors:
            lines.append(f"- 错误：{e}")
        lines.append("")
    REPORT_MD.write_text("\n".join(lines), encoding="utf-8")
    REPORT_JSON.write_text(json.dumps(
        [{k: v for k, v in r.__dict__.items()} for r in results],
        ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def _expand(names: list[str], with_sections: bool) -> list[Case]:
    out: list[Case] = []
    for name in names:
        case = CASES[name]
        out.append(case)
        if with_sections and case.section_dxf:
            out.append(Case(name=f"{name}-剖面", dxf=case.section_dxf,
                            gold=case.gold, note=case.note + "；剖面图版"))
    return out


def main(argv: list[str]) -> int:
    force_blocked = "--no-force" not in argv
    with_sections = "--sections" in argv
    names = [a for a in argv if not a.startswith("--")] or list(CASES)
    unknown = [n for n in names if n not in CASES]
    if unknown:
        print(f"未知靶子 {unknown}（可选：{', '.join(CASES)}）")
        return 2

    # 本表要发射 STEP + 量体积，必须在 cad-occt 环境跑
    try:
        from src.rebuild import emit
        if not emit.occ_available():
            print("OCC 不可用：本表需要 cad-occt 解释器。")
            print("  PY=/c/Users/yaoshuo/miniconda3/envs/cad-occt/python.exe")
            return 2
    except Exception as e:                              # noqa: BLE001
        print(f"导入 emit 失败：{type(e).__name__}: {e}")
        return 2

    OUT.mkdir(parents=True, exist_ok=True)
    print("=" * 100)
    print("通用性盲测表（P0）—— held-out 件，不判红绿")
    print("=" * 100)
    results: list[Result] = []
    for case in _expand(names, with_sections):
        print(f"—— {case.name}：{case.note}")
        r = run_case(case, force_blocked=force_blocked)
        print_result(r)
        results.append(r)
    write_report(results)
    print("-" * 100)
    print(f"报告：{REPORT_MD}")
    print(f"      {REPORT_JSON}")
    # 诊断仪：跑完即成功（环境缺失已在上面拦下）
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
