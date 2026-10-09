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
轮廓环通道（视图环 → 带圆弧的 profile）已落地（2026-10-07）：基体轮廓
优先取**视图轮廓环**（要求铺满轮廓跨度），提不到才退回包围盒矩形。`l_bracket`
因此转绿（19,800 逐位）。锥化词汇（``taper_scale``：侧看三角形剪影 ⇒
沿该轴自低端收敛到一点）同日落地，`图形练习` 转绿（四棱锥 ⅓·60³ = 72,000
逐位；此前按侧面三角棱柱读成 108,000）。多视图回转体识别 2026-10-09 落地
（`features/revolve.py`：同轴圆簇 + 剖面轴扫读母线 ⇒ REVOLVE 基体；方料段
按"外轮廓 − 回转外径圆"的四角月牙补料，不回盖回转体孔），`PF60K` 转绿
（OCC 262,097.7 / SW 262,099.1 vs 金值 261,935 = +0.06%）。高度分解 + 圆角/
侧通道 2026-10-10 落地（`features/height_zones.py` 俯视圆分区 × 侧视剪影
包络 ⇒ 基体降到最低公共顶面、分区抬升；`roundovers.py` 顶边 R3 凸圆角 +
根部 R3 凹圆角；`side_channels.py` 挂耳月牙/张缝/销孔；
`views/correspondence.resolve_frame_mirrors` 帧镜像裁决），`bracket` 两条
随之转绿（OCC 191,970.1 / −0.01%、192,196.5 / +0.11%；SW 193,032.3 /
193,032.8 / +0.54%——SW 侧比 OCC 高的那 ~+1.06k 是发射器口径差、早于本轮，
圆角区已由盒探针证两发射器吻合 ≤0.4mm³）。**当前全表 9 靶子无 GAP**。
⚠️ 因此**不要**为了让表好看去调发射器：表上红的地方就是还没读出来的地方，
改发射器只会把"没读到"变成"读错了"（体积对了结构全错，正是本框架要消灭的病）。

**发射失败怎么算**（2026-09-28 实测补）：本脚本一律 `force=True` 硬推，
所以欠定靶子会在发射器里炸掉。判据用框架自己的 gate（`r.blocking()`）：
非空阻塞疑问 ⇒ 记 `[GAP] 按设计拒绝`（**不计** FAIL，但照样不绿）；一条阻塞
疑问都没有却失败 ⇒ 记 `**发射失败（疑似发射器 bug）**` 并计入 FAIL。
两个实测拒绝（**均已解**）：
  * `PF60K`（**已解**，2026-10-09 回转体识别）——曾任其一是 IR 把同一轴上的
    7 条同心圆读成 7 个同轴通孔（r30/25/21/16/8.5/7/6，类型全是 GUESS）。
    第一个 Ø60 切完后第二个 Ø50 **无材料可切** ⇒ `FeatureCut3` 返回 None
    （切除不幂等，见 CLAUDE.md）。消解方式是**识别侧换读法**（不是放宽
    发射器）：7 圆实为回转体母线的台阶，读成 REVOLVE 后阻塞疑问同步消解；
    另发现并修掉阵列发射位置 bug（`pattern_plan` 曾把图纸系相位 `start_deg`
    当相对角旋转 → PF60K 的 45° 起始相位把 3 个兄弟孔位飞出发射体 → 整树
    拒绝；已改为**锚在 child 自身**旋转，详见 `sw_builder.pattern_plan` docstring）。
  * `bracket`（**已解**，2026-10-07）——曾任其一是 V1 里那条 r12 圆：圆心
    (193.3, ·, 24)、r12，与**包围盒**基体 x 上界 205.3 恰好相切 ⇒ SW 拒绝。
    轮廓环落地后基体是真环（臂端圆头就在环上），r12 不再与基体面相切，
    加上 `sw_builder` 的基体拉伸修复（碎片线链无损合并 + 劣弧 `direction=False`），
    现在 **8 特征 → SW 8 建成**（361,379.4，与 OCC 361,044.7 吻合 0.09%）。
    r12 的 GUESS(hole|boss) 仍是识别侧待消解的记账。

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
#: 期望 "ok" = 应当与金值吻合；"gap" = 已知结构缺口，偏差是预期（**当前无靶子
#: 登记为此**——bracket 两条 2026-10-10 阶段 7 高度分解 + 圆角/侧通道落地后转绿）
CASES: dict[str, tuple[str, float | None, tuple | None, str]] = {
    "block_3view": ("CAD/test_simple/block_3view.dxf", 167196.2, (100, 30, 60), "ok"),
    "plate_100x60": ("CAD/test_simple/plate_100x60.dxf", 116858.4, (100, 60, 20), "ok"),
    "flange_d80": ("CAD/test_simple/flange_d80.dxf", 85652.4, (80, 80, 24), "ok"),
    "法兰练习": ("CAD/法兰练习.dxf", 94247.78, (80, 80, 20), "ok"),
    "l_bracket": ("CAD/test_simple/l_bracket.dxf", 19800.0, (60, 60, 18), "ok"),
    "图形练习": ("CAD/图形练习.dxf", 72000.0, (60, 60, 60), "ok"),
    # bracket 2026-10-10 阶段 7（高度分解 + 圆角/侧通道 + 镜像裁决）转绿：
    # OCC 三视图 191,970.1（−0.01%）/ 剖面图 192,196.5（+0.11%），实体 1、11 特征；
    # SW 193,032.3 / 193,032.8（+0.54%，发射器口径差，圆角区盒探针与 OCC ≤0.4mm³）
    "bracket 三视图": ("CAD/temp_output/bracket_angker_三视图_v4.dxf",
                       191987.84, (203.30, 51.00, 44.00), "ok"),
    "bracket 剖面图": ("CAD/temp_output/bracket_angker_图纸_20260922_剖面图.dxf",
                       191987.84, (203.30, 51.00, 44.00), "ok"),
    # PF60K 2026-10-09 回转体识别落地后转绿：OCC 262,097.7 / SW 262,099.1
    # vs 261,935 = +0.06%（剩余 +0.06% 的落点已记账：r=8 台阶区 +1,005.3 /
    # 锥区 −852.5，见 CLAUDE.md——两处都是识别侧读数口径，非发射器问题）
    "PF60K": ("CAD/temp_output/pf60k_闭环_三视图_20260817.dxf", 261935.0, None, "ok"),
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
            verdict = _refusal(r, expect)
            print(f"{_mark(expect)} {name:<14} {r.errors[0][:110]}")
            print(f"{'':<21} {verdict}")
            if verdict.startswith("**"):
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
        if r.sldprt is None:
            # 发射被**静默跳过**（`pipeline._emit_sw` 对"SW 不可用"只记 notes
            # 不记 errors；典型是循环中途 SW 进程退出）。硬连下去就是 2026-10-10
            # 那次 ActiveDoc=None 的崩溃——在这里拦住并把原因打出来。
            note = next((n for n in r.notes if "跳过 .sldprt" in n), "未知原因")
            print(f"{_mark(expect)} {name:<14} SW 侧发射被跳过：{note}")
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
    if sw:
        from src.rebuild.emit import sw_builder as _SB
        if not _SB.sw_available():
            print("**SW 2025 没在运行** —— 先启动 SolidWorks 再跑 SW 表。")
            print("（SW 不在时 `pipeline._emit_sw` 对每靶子的发射是**静默跳过**，"
                  "而 `SB.connect()` 会把 SW 拉起来却没有文档，量体积以 "
                  "ActiveDoc=None 崩溃——2026-10-10 首跑实测，故提前拦在这里）")
            return 2
    bad = run_sw(names) if sw else run_occ(names)
    print("-" * 100)
    if bad:
        print(f"[FAIL] {bad} 个靶子疑似发射器 bug（无阻塞疑问却失败）—— 要查的不是表，是发射器")
    else:
        print("[完成] 无发射器 bug——最后一条 [GAP]（bracket 高度分解）2026-10-10 已消灭，"
              "当前全表应为 [OK ]；若再见 [GAP]，那是已知结构缺口或被 force 强推的欠定图纸，"
              "不是回归")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
