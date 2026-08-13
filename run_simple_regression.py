#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""简单模型回归套件 — 6 个已验证用例的自动几何验收。

验收标准（用户准则：以实际生成模型为准，不只看日志数值）：
  1. 实际生成 STEP 模型（可选 --sw 导入 SolidWorks 生成时间戳 .sldprt）
  2. 体积与黄金值精确吻合（黄金值来自用户目检通过的模型实测）
  3. 实体数 = 1（无分离实体/脱落凸台）
  4. 包围盒按轴对比（X/Y/Z 逐轴）——体积旋转不变，
     按轴对比才能发现法兰竖盘、block Y/Z 交换这类定向缺陷

用法（需 cad-occt 环境）:
  /c/Users/yaoshuo/miniconda3/envs/cad-occt/python.exe run_simple_regression.py
  /c/Users/yaoshuo/miniconda3/envs/cad-occt/python.exe run_simple_regression.py --sw

报告输出: CAD/temp_output/regression_report.txt (UTF-8)
"""

import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent
TEMP_DIR = PROJECT_ROOT / "CAD" / "temp_output"
TEMP_DIR.mkdir(exist_ok=True)
DWG2DXF_EXE = PROJECT_ROOT / "tools" / "libredwg" / "dwg2dxf.exe"
REPORT_PATH = TEMP_DIR / "regression_report.txt"

# ---------------------------------------------------------------------------
# 黄金值：来自用户目检通过的模型实测（2026-08-13）。
# 体积单位 mm³，bbox 为 (X, Y, Z) 逐轴尺寸。
# 理论值对照:
#   图形练习 = ⅓×60×60×60 = 72000（四棱锥，俯视图对角线为顶点辅助线）
#   法兰练习 = π×40²×20 − 4×π×5²×20 = 30000π ≈ 94247.78（Ø80 圆盘平放 + 4×Ø10 孔）
#   flange_d80 = π×24×(40² − 20² − 4×4²) = 27264π ≈ 85652.4（Ø80 圆盘 + Ø40 孔 + 4×Ø8 孔）
#   plate_100x60 = 100×60×20 − 2×π×5²×20 = 120000 − 1000π ≈ 116858.4
# ---------------------------------------------------------------------------
CASES = [
    {
        "name": "block_3view",
        "path": "CAD/test_simple/block_3view.dxf",
        # 100×60×30 块 + 前视图 2×Ø10 通孔（沿 Y，深30）+ 俯视图 2×Ø10 通孔（沿 Z，深60）
        # 垂直交叉重叠 2×(16r³/3)=1333.3：180000 − 2π·25·30 − 2π·25·60 + 1333.3 = 167196.2
        "vol": 167196.2,
        "bbox": (100, 30, 60),    # 前视图 100×60（高 60→Z），俯视图 100×30（深 30→Y）
    },
    {
        "name": "plate_100x60",
        "path": "CAD/test_simple/plate_100x60.dxf",
        "vol": 116858.4,
        "bbox": (100, 60, 20),
    },
    {
        "name": "l_bracket",
        "path": "CAD/test_simple/l_bracket.dxf",
        "vol": 19800.0,
        "bbox": (60, 60, 18),
    },
    {
        "name": "flange_d80",
        "path": "CAD/test_simple/flange_d80.dxf",
        "vol": 85652.4,
        "bbox": (80, 80, 24),
    },
    {
        "name": "图形练习",
        "path": "CAD/图形练习.dwg",
        "vol": 72000.0,           # 四棱锥：⅓×60×60×60
        "bbox": (60, 60, 60),
    },
    {
        "name": "法兰练习",
        "path": "CAD/法兰练习.dwg",
        "vol": 94247.78,          # 30000π：Ø80 圆盘平放 + 4×Ø10 孔
        "bbox": (80, 80, 20),     # 平放：厚度 20 在 Z 轴（定向验收关键）
    },
]

VOL_TOLERANCE = 0.003   # 体积相对容差 0.3%
BBOX_TOLERANCE = 1.0    # 包围盒逐轴绝对容差 mm
SOLIDS_EXPECTED = 1     # 实体数（分离实体即失败）


# ---------------------------------------------------------------------------
# STEP 几何分析（与转换代码相同的 OCC 懒加载方式）
# ---------------------------------------------------------------------------

def _ensure_occ():
    """懒加载 PythonOCC（与 dxf_to_3d_general 相同的设计）。"""
    import importlib
    for name in ("OCC.Core.BRep", "OCC.Core.BRepBndLib", "OCC.Core.Bnd",
                 "OCC.Core.GProp", "OCC.Core.BRepGProp", "OCC.Core.STEPControl",
                 "OCC.Core.TopExp", "OCC.Core.TopAbs"):
        importlib.import_module(name)


def analyze_step(step_path: Path) -> dict:
    """读取 STEP 并返回 {volume, solids, bbox}。失败返回 None。"""
    from OCC.Core.BRep import BRep_Builder
    from OCC.Core.Bnd import Bnd_Box
    from OCC.Core.BRepBndLib import brepbndlib
    from OCC.Core.GProp import GProp_GProps
    from OCC.Core.BRepGProp import brepgprop
    from OCC.Core.STEPControl import STEPControl_Reader
    from OCC.Core.TopExp import TopExp_Explorer
    from OCC.Core.TopAbs import TopAbs_SOLID
    from OCC.Core.TopoDS import topods

    reader = STEPControl_Reader()
    if reader.ReadFile(str(step_path)) != 1:
        return None
    reader.TransferRoots()
    shape = reader.OneShape()

    props = GProp_GProps()
    brepgprop.VolumeProperties(shape, props)
    volume = props.Mass()

    solids = 0
    ex = TopExp_Explorer(shape, TopAbs_SOLID)
    while ex.More():
        solids += 1
        ex.Next()

    bbox = Bnd_Box()
    brepbndlib.Add(shape, bbox)
    x1, y1, z1, x2, y2, z2 = bbox.Get()
    return {
        "volume": volume,
        "solids": solids,
        "bbox": (x2 - x1, y2 - y1, z2 - z1),
        "bbox_raw": (x1, y1, z1, x2, y2, z2),
    }


# ---------------------------------------------------------------------------
# 用例执行
# ---------------------------------------------------------------------------

def _to_dxf(src: Path) -> Path:
    """DWG → DXF（与 dxf_to_3d_general.main 相同的 dwg2dxf 调用）。"""
    dxf_out = src.with_suffix(".dxf")
    if dxf_out.exists() and dxf_out.stat().st_mtime >= src.stat().st_mtime:
        return dxf_out
    if not DWG2DXF_EXE.exists():
        raise RuntimeError(f"未找到 dwg2dxf.exe: {DWG2DXF_EXE}")
    result = subprocess.run(
        [str(DWG2DXF_EXE), "-y", "-v", "-o", str(dxf_out), str(src)],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"DWG→DXF 转换失败: {result.stderr}")
    return dxf_out


def run_case(case: dict, with_sw: bool) -> dict:
    """运行单个用例：转换 → STEP 分析 → 与黄金值对比。"""
    import dxf_to_3d_general as d23

    src = PROJECT_ROOT / case["path"]
    if not src.exists():
        return {"name": case["name"], "status": "SKIP", "note": f"文件不存在: {src}"}

    try:
        dxf_path = _to_dxf(src) if src.suffix.lower() == ".dwg" else src
    except RuntimeError as e:
        return {"name": case["name"], "status": "FAIL", "note": str(e)}

    step_out = TEMP_DIR / f"regress_{case['name']}.step"
    print(f"\n{'=' * 60}\n用例: {case['name']}\n{'=' * 60}")

    try:
        body = d23.convert_dxf_to_3d(str(dxf_path), str(step_out))
    except Exception as e:
        return {"name": case["name"], "status": "FAIL",
                "note": f"转换异常: {e}"}
    if body is None:
        return {"name": case["name"], "status": "FAIL",
                "note": "转换返回 None"}

    result = analyze_step(step_out)
    if result is None:
        return {"name": case["name"], "status": "FAIL",
                "note": "STEP 分析失败"}

    # 对比黄金值
    problems = []
    vol = result["volume"]
    vol_expected = case["vol"]
    vol_tol = abs(vol_expected) * VOL_TOLERANCE + 0.5
    if abs(vol - vol_expected) > vol_tol:
        problems.append(f"体积 {vol:.2f} ≠ 期望 {vol_expected:.2f} "
                        f"(Δ={vol - vol_expected:+.2f})")

    bbox = result["bbox"]
    bbox_expected = case["bbox"]
    axis_names = "XYZ"
    for i in range(3):
        if abs(bbox[i] - bbox_expected[i]) > BBOX_TOLERANCE:
            problems.append(
                f"bbox[{axis_names[i]}]={bbox[i]:.2f} ≠ 期望 "
                f"{bbox_expected[i]:.2f}（定向缺陷？）")

    if result["solids"] != SOLIDS_EXPECTED:
        problems.append(f"实体数 {result['solids']} ≠ 期望 {SOLIDS_EXPECTED} "
                        f"（分离实体/脱落凸台）")

    note = "; ".join(problems) if problems else "OK"

    if with_sw:
        from datetime import datetime
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        sw_out = TEMP_DIR / f"regress_{case['name']}_{ts}.sldprt"
        try:
            ok = d23.import_to_solidworks(str(step_out), str(sw_out))
            note += f" | SW: {'已保存 ' + sw_out.name if ok else '导入失败'}"
        except Exception as e:
            note += f" | SW 异常: {e}"

    return {
        "name": case["name"],
        "status": "PASS" if not problems else "FAIL",
        "vol": vol,
        "bbox": bbox,
        "solids": result["solids"],
        "note": note,
    }


def main():
    with_sw = "--sw" in sys.argv
    print(f"简单模型回归套件 — {len(CASES)} 个用例"
          f"{'（含 SW 导入）' if with_sw else '（仅 STEP）'}")

    report_lines = [f"回归报告  {'(SW 导入)' if with_sw else '(STEP)'}", "=" * 60]
    passed = 0
    for case in CASES:
        r = run_case(case, with_sw)
        line = (f"[{r['status']:4s}] {r['name']:12s} "
                f"体积={r.get('vol', float('nan')):.2f} "
                f"bbox={tuple(f'{v:.1f}' for v in r.get('bbox', (0, 0, 0)))} "
                f"实体={r.get('solids', '?')} | {r['note']}")
        print(line)
        report_lines.append(line)
        if r["status"] == "PASS":
            passed += 1

    summary = f"\n结果: {passed}/{len(CASES)} 通过"
    print(summary)
    report_lines.append(summary)
    REPORT_PATH.write_text("\n".join(report_lines), encoding="utf-8")
    print(f"报告: {REPORT_PATH}")
    return 0 if passed == len(CASES) else 1


if __name__ == "__main__":
    _ensure_occ()
    sys.exit(main())
