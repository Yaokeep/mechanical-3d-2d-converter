#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""新框架（`src/rebuild/`）验收表：图纸 → 特征树 → STEP / SW 原生特征模型。

这是新框架的**回归入口**（与旧管线的 `run_simple_regression.py` 平行：
那个查 `dxf_to_3d_general.py`，这个查 `src/rebuild/`）。两张表：

    OCC 表（默认，需 cad-occt）  : 逐靶子重建 STEP，量体积/bbox/实体数
    SW  表（`--sw`，需 SW 2025）: 逐靶子建 SW 原生特征模型，量体积/bbox，
                                  并核**特征步数与特征模型一致**

    PY=/c/Users/yaoshuo/miniconda3/envs/cad-occt/python.exe
    PYTHONIOENCODING=utf-8 $PY run_rebuild_acceptance.py [靶子...]
    PYTHONIOENCODING=utf-8 python run_rebuild_acceptance.py --sw [靶子...]

`[OK]` 与 `[GAP]` 的区别是本脚本的重点：**GAP 是已知的结构缺口**，不是回归。
GAP 的三条（`l_bracket` / `图形练习` / `bracket`）都是同一个原因 —— 基体轮廓
目前取**视图包围盒**（矩形棱柱），真实外轮廓是 L 形/台阶/回转体；轮廓环
（视图环 → 带圆弧的 profile）落地后它们应当转绿。`PF60K` 另有一条：多视图
下的回转体识别（它是法兰盘，却按板类零件建）。
⚠️ 因此**不要**为了让表好看去调发射器：表上红的地方就是还没读出来的地方，
改发射器只会把"没读到"变成"读错了"（体积对了结构全错，正是本框架要消灭的病）。

**发射失败怎么算**（2026-09-28 实测补）：本脚本一律 `force=True` 硬推，
所以欠定靶子会在发射器里炸掉。判据用框架自己的 gate（`r.blocking()`）：
非空阻塞疑问 ⇒ 记 `[GAP] 按设计拒绝`（**不计** FAIL，但照样不绿）；一条阻塞
疑问都没有却失败 ⇒ 记 `**发射失败（疑似发射器 bug）**` 并计入 FAIL。
两个实测拒绝（SW 侧，OCC 侧同样发射成功但结构错）：
  * `PF60K` —— IR 把同一轴上的 7 条同心圆读成 7 个同轴通孔（r30/25/21/16/8.5/7/6，
    类型全是 GUESS）。第一个 Ø60 切完后第二个 Ø50 **无材料可切** ⇒ `FeatureCut3`
    返回 None（切除不幂等，见 CLAUDE.md）。框架自己已把这条列成阻塞疑问
    （"是沉孔/倒角/台阶，还是同一面上的两个独立圆边？"）。
  * `bracket` 两条 —— 第 7 个特征是 V1 里那条 r12 圆：找不到间距 2r 的轮廓对，
    类型 GUESS(hole|boss)。圆心 (193.3, ·, 24)、r12，而基体（包围盒）x 上界
    205.3 = 193.3 + 12 ⇒ 切除圆柱与基体右面**恰好相切**，SW 拒绝。真实零件
    此处是臂端圆头（不是孔）——正是"包围盒基体 + hole/boss 未消解"合起来的后果。

体积金值来源：
  * 6 个简单靶子 —— `run_simple_regression.py` 的 CASES 表（逐位黄金值）
  * `PF60K` —— `CLAUDE.md` 精度断点表（261,935）
  * `bracket 三视图` —— `三维/bracket angker.stp` 三个实体 **Fuse 后**的体积
    （191,987.84，bbox 203.30×51.00×44.00）。该文件是三块实体拼成的一个零件
    （体1 164,641.56 / 体2 55,957.87 / 体3 54,949.02，两两有交叠），
    直接量全文件得 275,548.37 —— 与旧管线基线比的是融合值，别拿全文件数对。
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "CAD" / "temp_output"

#: 靶子 → (图纸, 金值体积 mm³, 金值 bbox (x,y,z) 或 None, 期望)
#: 期望 "ok" = 应当与金值吻合；"gap" = 已知结构缺口（轮廓环未落地），偏差是预期
CASES: dict[str, tuple[str, float | None, tuple | None, str]] = {
    "block_3view": ("CAD/test_simple/block_3view.dxf", 167196.2, (100, 30, 60), "ok"),
    "plate_100x60": ("CAD/test_simple/plate_100x60.dxf", 116858.4, (100, 60, 20), "ok"),
    "flange_d80": ("CAD/test_simple/flange_d80.dxf", 85652.4, (80, 80, 24), "ok"),
    "法兰练习": ("CAD/法兰练习.dxf", 94247.78, (80, 80, 20), "ok"),
    "l_bracket": ("CAD/test_simple/l_bracket.dxf", 19800.0, (60, 60, 18), "gap"),
    "图形练习": ("CAD/图形练习.dxf", 72000.0, (60, 60, 60), "gap"),
    "bracket 三视图": ("CAD/temp_output/bracket_angker_三视图_v4.dxf",
                       191987.84, (203.30, 51.00, 44.00), "gap"),
    "bracket 剖面图": ("CAD/temp_output/bracket_angker_图纸_20260922_剖面图.dxf",
                       191987.84, (203.30, 51.00, 44.00), "gap"),
    "PF60K": ("CAD/temp_output/pf60k_闭环_三视图_20260817.dxf", 261935.0, None, "gap"),
}


def _mark(expect: str) -> str:
    return "[OK ]" if expect == "ok" else "[GAP]"


def _refusal(r, expect: str) -> str:
    """发射失败时，判定它是"发射器的 bug"还是"框架本来就在拒绝"。

    判据用框架**自己的** gate：`RebuildResult.blocking()`（类型未定 / 缺尺寸 /
    坐标系冲突）非空 ⇒ 这张图纸本来就欠定，`force=True` 是硬推的，发射失败
    是**登记在案的**结果；blocking 为空却失败 ⇒ 没人预警过，那是真 bug。
    ⚠️ 这条规则的意义在于**不许把拒绝洗成绿**：欠定的靶子照样打 `[GAP]`，
    只是不再计进 FAIL —— 让它绿的办法是识别侧把疑问消解掉，不是放宽这里。
    """
    nb = len(r.blocking()) if r is not None else 0
    if expect == "gap" and nb:
        first = r.blocking()[0]
        return (f"[GAP] 按设计拒绝（{nb} 条阻塞疑问未消解，force 强推后发射器拒绝）\n"
                f"{'':<21} 其一：{getattr(first, 'detail', '')[:150]}")
    return f"**发射失败（无阻塞疑问，疑似发射器 bug）**：{nb} 条阻塞疑问"


# ---------------------------------------------------------------------------
# OCC 表
# ---------------------------------------------------------------------------

def run_occ(names: list[str]) -> int:
    from src.rebuild.pipeline import rebuild
    from src.rebuild.verify.step_probe import probe_step

    bad = 0
    for name in names:
        src, gold_v, gold_b, expect = CASES[name]
        p = ROOT / src
        if not p.exists():
            print(f"{_mark(expect)} {name:<14} 图纸不存在：{src}")
            continue
        r = rebuild(p, step=OUT / f"_acc_{name.replace(' ', '_')}.step", force=True)
        if r.errors:
            print(f"{_mark(expect)} {name:<14} {r.errors[0][:110]}")
            print(f"{'':<21} {_refusal(r, expect)}")
            bad += 1
            continue
        m = probe_step(r.step)
        if not m.ok:
            print(f"{_mark(expect)} {name:<14} STEP 读不回：{m.error}")
            bad += 1
            continue
        n = len(r.part.features)
        dv = (m.volume - gold_v) / gold_v * 100.0 if gold_v else float("nan")
        db = (" ".join(f"{a - b:+.2f}" for a, b in zip(m.extents, gold_b))
              if (gold_b and m.extents) else "-")
        print(f"{_mark(expect)} {name:<14} {n:>2} 特征  体积 {m.volume:>11,.1f} vs "
              f"{gold_v if gold_v else 0:>10,.1f} {dv:+7.2f}%  bbox 差 {db}  "
              f"实体 {m.n_solids}")
    return bad


# ---------------------------------------------------------------------------
# SW 表
# ---------------------------------------------------------------------------

def _expected_sw(f, part, SB) -> int:
    """一个 IR 特征在 SW 树里应当变成几步（阵列按 `pattern_plan` 展开，可递归）。"""
    if f.type.value != "pattern":
        return 1
    plan = SB.pattern_plan(f, part)
    return sum(_expected_sw(plan.child, part, SB) for _ in plan.positions)


def run_sw(names: list[str]) -> int:
    from src.rebuild.emit import sw_builder as SB
    from src.rebuild.pipeline import rebuild

    bad = 0
    for name in names:
        src, gold_v, gold_b, expect = CASES[name]
        p = ROOT / src
        if not p.exists():
            print(f"{_mark(expect)} {name:<14} 图纸不存在：{src}")
            continue
        r = rebuild(p, sldprt=OUT / f"_accsw_{name.replace(' ', '_')}", force=True)
        if r.errors:
            verdict = _refusal(r, expect)
            print(f"{_mark(expect)} {name:<14} {r.errors[0][:110]}")
            print(f"{'':<21} {verdict}")
            if verdict.startswith("**"):
                bad += 1
            continue
        want = sum(_expected_sw(f, r.part, SB) for f in r.part.features)
        driver = SB.connect()                 # 模型已留在 SW 里，只连上去量，不关文档
        vol = SB.measure_sw_volume_mm3(driver)
        doc = SB.active_doc(driver)           # 这种 driver 的 sw_model 是 None
        ours = SB.list_sw_features(doc, only_built=True)
        box = doc.GetPartBox(True)
        # SW(x,y,z) = IR(x,−z,y) ⇒ IR 外形 = (SW x, SW z, SW y)
        ext = ((box[3] - box[0]) * 1000.0, (box[5] - box[2]) * 1000.0,
               (box[4] - box[1]) * 1000.0)
        dv = (vol - gold_v) / gold_v * 100.0 if gold_v else float("nan")
        db = (" ".join(f"{a - b:+.2f}" for a, b in zip(ext, gold_b))
              if gold_b else "-")
        steps = "步数一致" if len(ours) == want else f"**步数不一致：应 {want}**"
        print(f"{_mark(expect)} {name:<14} {len(r.part.features):>2} 特征 → SW {len(ours):>2} "
              f"（{steps}）  体积 {vol:>11,.1f} vs {gold_v if gold_v else 0:>10,.1f} "
              f"{dv:+7.2f}%  bbox 差 {db}")
        print(f"{'':<21} SW 树 {' | '.join(ours)}")
        if len(ours) != want:
            bad += 1
    return bad


def main(argv: list[str]) -> int:
    sw = "--sw" in argv
    names = [a for a in argv if not a.startswith("--")] or list(CASES)
    unknown = [n for n in names if n not in CASES]
    if unknown:
        print(f"未知靶子 {unknown}（可选：{', '.join(CASES)}）")
        return 2
    print("=" * 100)
    print("新框架验收表" + ("（SW 原生特征模型，需 SW 2025）" if sw else "（STEP，需 cad-occt）"))
    print("=" * 100)
    bad = run_sw(names) if sw else run_occ(names)
    print("-" * 100)
    if bad:
        print(f"[FAIL] {bad} 个靶子疑似发射器 bug（无阻塞疑问却失败）—— 要查的不是表，是发射器")
    else:
        print("[完成] 无发射器 bug —— [GAP] 行是已知结构缺口（轮廓环/回转体未识别），"
              "其中标「按设计拒绝」的是欠定图纸被 force 强推后发射器拒绝，均不是回归")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
