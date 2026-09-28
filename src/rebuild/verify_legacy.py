# -*- coding: utf-8 -*-
"""拿图纸判旧管线的输出 —— 阶段 0 的验收入口。

    <cad-occt python> -m src.rebuild.verify_legacy <图纸.dxf> <模型.step> [--json]

**为什么先做这个**（ARCHITECTURE §8 阶段 0）：验证器要先被证明可用，
再拿它盯着重写重建器。指向旧管线有三个好处——
① 现在就有真靶子（bracket 收敛、spoon 崩），判据立刻能校准；
② 拿到一条**不依赖基准模型**的回归线（基准在 `三维/`，是用户私有数据）；
③ 把旧管线的失败模式量化成一张地图。

判据只有图纸与模型，**不需要基准**：图纸经视图包围盒给出模型三向尺寸，
实测 STEP 给出三向尺寸，比尺度无关的比例。

⚠️ 必须用 cad-occt 环境跑（要读 STEP）：

    PY=/c/Users/yaoshuo/miniconda3/envs/cad-occt/python.exe
    PYTHONIOENCODING=utf-8 $PY -m src.rebuild.verify_legacy CAD/temp_output/spoon_三视图.dxf \
        CAD/temp_output/spoon_三视图_3d.step
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.rebuild.evidence.dxf_reader import read_dxf          # noqa: E402
from src.rebuild.views import detect_views, type_views         # noqa: E402
from src.rebuild.verify import (                               # noqa: E402
    RATIO_TOL,
    compare,
    coverage,
    coverage_report,
    decide,
    expect_from_drawing,
)
from src.rebuild.verify.gate import Verdict                    # noqa: E402

H1 = "=" * 72
H2 = "-" * 72

#: 退出码：0 通过 / 1 拒绝 / 2 需人工确认 / 3 出错
_EXIT = {Verdict.ACCEPT: 0, Verdict.REJECT: 1,
         Verdict.NEEDS_CONFIRMATION: 2, Verdict.ERROR: 3}


def _probe_measured(step: Path):
    """import step_probe 的失败要给出可操作的提示，而不是 ImportError 堆栈。"""
    try:
        from src.rebuild.verify.step_probe import probe_step
    except ImportError as exc:
        return None, (f"读不了 STEP：{exc}。本步需要 OCC —— 请用 cad-occt 环境："
                      "/c/Users/yaoshuo/miniconda3/envs/cad-occt/python.exe")
    m = probe_step(step)
    return m, ("" if m.ok else m.error)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="verify_legacy",
        description="用图纸判一个 STEP 模型（阶段 0：指向旧管线的输出）")
    ap.add_argument("dxf", help="输入 DXF 图纸")
    ap.add_argument("step", help="待判的 STEP 模型")
    ap.add_argument("--json", action="store_true", help="机器可读输出")
    args = ap.parse_args(argv)

    dxf_path, step_path = Path(args.dxf), Path(args.step)
    for p in (dxf_path, step_path):
        if not p.exists():
            print(f"[FAIL] 文件不存在：{p}", file=sys.stderr)
            return 3

    drawing = read_dxf(dxf_path)
    detect_views(drawing)
    view_questions = type_views(drawing)

    expected = expect_from_drawing(drawing)
    expected.questions.extend(list(view_questions))

    measure, err = _probe_measured(step_path)
    measured = measure.extents if measure is not None else None

    cmp = compare(expected, measured)
    if measure is not None and measure.has_dangling:
        cmp.notes.append(
            f"模型含游离几何：裸包围盒 {tuple(f'{v:.2f}' for v in measure.raw_extents)}"
            f" 大于实体域 {tuple(f'{v:.2f}' for v in measure.extents)}")
    result = decide(cmp, expected, measured_ok=(measure is not None and measure.ok),
                    measure_error=err)

    cov = coverage(drawing)

    if args.json:
        print(json.dumps({
            "dxf": str(dxf_path), "step": str(step_path),
            "verdict": result.verdict.value,
            "reasons": result.reasons,
            "expected": expected.triple(),
            "measured": measured,
            "rel_error": cmp.rel_error,
            "implied_scale": cmp.implied_scale,
            "ratio_error": cmp.ratio_error,
            "failing_axes": cmp.failing_axes,
            "ratio_tol": RATIO_TOL,
            "volume": measure.volume if measure else None,
            "n_solids": measure.n_solids if measure else None,
            "n_faces": measure.n_faces if measure else None,
            "coverage": {
                "evidence_ratio": cov.evidence_ratio,
                "text_ratio": cov.text_ratio,
                "tier_hist": cov.tier_hist,
                "orphans": len(cov.orphans),
            },
            "questions": [
                {"kind": q.kind.value, "detail": q.detail, "view": q.view,
                 "candidates": list(q.candidates)}
                for q in result.questions
            ],
        }, ensure_ascii=False, indent=2))
        return _EXIT[result.verdict]

    _print_report(dxf_path, step_path, expected, measure, cmp, result, cov)
    return _EXIT[result.verdict]


def _fmt(v) -> str:
    return "—" if v is None else f"{v:.3f}"


def _print_report(dxf_path, step_path, expected, measure, cmp, result, cov) -> None:
    out: list[str] = [H1, f"验证  {dxf_path.name}  ×  {step_path.name}", H1]

    out.append(H2)
    out.append("图纸期望（由视图包围盒推出，每项带依据）")
    out.append(H2)
    for vid, what, val in expected.observations:
        out.append(f"  {vid:4} {what:14} {val:10.3f}")
    if expected.spans:
        out.append("  " + "  ".join(
            f"{a.upper()}={c.value:.3f}<{c.tier.name}>"
            + ("" if c.is_settled else f" 备选{list(c.alternatives)}")
            for a, c in expected.spans.items()))

    out.append(H2)
    out.append("模型实测")
    out.append(H2)
    if measure is None:
        out.append(f"  （量不到：{result.reasons[-1] if result.reasons else '?'}）")
    else:
        out.append(f"  实体域尺寸  X={_fmt(measure.extents[0])}  "
                   f"Y={_fmt(measure.extents[1])}  Z={_fmt(measure.extents[2])}")
        out.append(f"  体积 {measure.volume:.2f}  "
                   f"实体 {measure.n_solids} 个  面 {measure.n_faces} 个")
        if measure.has_dangling:
            out.append(f"  ⚠ 裸包围盒 {tuple(f'{v:.2f}' for v in measure.raw_extents)}"
                       " 大于实体域 —— 含零厚度面片/游离顶点")

    out.append(H2)
    out.append(f"对比（主判据：尺度无关比例，容差 {RATIO_TOL * 100:.0f}%）")
    out.append(H2)
    if cmp.expected and cmp.measured:
        ne = tuple(v / max(cmp.expected) for v in cmp.expected)
        nm = tuple(v / max(cmp.measured) for v in cmp.measured)
        out.append("  轴    图纸        模型        归一图纸   归一模型   偏离")
        for i, a in enumerate(("x", "y", "z")):
            flag = "  ✗" if a in cmp.failing_axes else ""
            out.append(f"  {a.upper()}  {cmp.expected[i]:10.3f}  "
                       f"{cmp.measured[i]:10.3f}  {ne[i]:9.4f}  {nm[i]:9.4f}  "
                       f"{cmp.ratio_error[a] * 100:6.1f}%{flag}")
        out.append("  隐含比例尺  "
                   + "  ".join(f"{a.upper()}={cmp.implied_scale[a]:.4f}"
                               for a in ("x", "y", "z")))
    for n in cmp.notes:
        out.append(f"  • {n}")

    out.append("")
    out.append(coverage_report(cov))

    out.append("")
    out.append(H1)
    out.append(f"判决  {result.verdict.value}")
    out.append(H1)
    for r in result.reasons:
        out.append(f"  • {r}")
    if result.questions:
        out.append(H2)
        out.append(f"待确认（{len(result.questions)} 项）")
        out.append(H2)
        for q in result.questions:
            out.append(f"  • {q}")
    print("\n".join(out))


if __name__ == "__main__":
    raise SystemExit(main())
