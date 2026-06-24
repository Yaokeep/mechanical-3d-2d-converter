"""DXF 阶梯轴 → SolidWorks .sldprt 原生文件

使用 src.core.sw_automation (v0.4.1+) 的 SW COM 驱动 + DXF 几何解析。

用法:
    python dxf_to_sldprt.py <输入.dxf> [输出.sldprt]
    python dxf_to_sldprt.py CAD/20160112-181116-09933.dxf
    python dxf_to_sldprt.py CAD/20160112-181116-09933.dxf CAD/MyShaft.sldprt

注意: 仅支持 DXF 格式。如需转换 DWG，请先用 ODA FileConverter
或 CAD 软件将 DWG 另存为 DXF，或使用同目录下已有的 DXF 文件。
"""

import sys
from pathlib import Path

# 确保项目根目录和 src/ 在 sys.path 中
PROJECT_ROOT = Path(__file__).parent
SRC_PATH = PROJECT_ROOT / "src"
for p in [str(PROJECT_ROOT), str(SRC_PATH)]:
    if p not in sys.path:
        sys.path.insert(0, p)

from convert_dwg_to_3d import parse_shaft_from_dxf
from src.core.sw_automation.sw_driver import SolidWorksDriver
from src.core.sw_automation.sw_shaft_builder import (
    ShaftBuilder,
    DEFAULT_CHAMFER_MM,
    DEFAULT_FILLET_R_MM,
)


def dxf_to_sw_sections(sections: list) -> list:
    """将 DXF 解析的截面参数转换为 SW 格式: (x_start, x_end, radius_mm)。"""
    return [(s["x_start"], s["x_end"], s["radius"]) for s in sections]


def dxf_to_sw_keyways(keyways: list) -> list:
    """将 DXF 解析的键槽参数转换为 SW 格式: (x_start, x_end, width, depth, shaft_radius)。"""
    return [(kw["x_start"], kw["x_end"], kw["width"],
             kw["depth"], kw["shaft_radius"]) for kw in keyways]


def extract_chamfer_params(chamfers: list) -> tuple[float, float]:
    """从 DXF 检测的倒角线提取左右端倒角尺寸。

    Returns:
        (left_chamfer_mm, right_chamfer_mm): 未检测到的一端使用 0.0。
    """
    left_size = 0.0
    right_size = 0.0
    for ch in chamfers:
        if ch.get("is_left", False):
            left_size = max(left_size, ch["size"])
        else:
            right_size = max(right_size, ch["size"])
    return left_size, right_size


def print_usage():
    """打印使用说明。"""
    print(__doc__)


def main():
    # ---- 解析命令行参数 ----
    if len(sys.argv) < 2:
        print_usage()
        sys.exit(1)

    dxf_path = sys.argv[1]

    # 检查输入文件是否存在
    if not Path(dxf_path).exists():
        print(f"[FAIL] 文件不存在: {dxf_path}")
        sys.exit(1)

    # 检查是否为 DWG 格式（不支持）
    if dxf_path.lower().endswith(".dwg"):
        print("[FAIL] 不支持 DWG 格式，请将 DWG 另存为 DXF 后重试。")
        print("  提示: 可用 AutoCAD / DraftSight / ODA FileConverter 转换")
        print(f"  或使用已有的 DXF 文件: CAD/20160112-181116-09933.dxf")
        sys.exit(1)

    # 确定输出路径
    if len(sys.argv) >= 3:
        output_base = sys.argv[2]
    else:
        input_stem = Path(dxf_path).stem
        input_dir = Path(dxf_path).parent
        output_base = str((input_dir / f"{input_stem}.sldprt").absolute())

    # 添加时间戳后缀，避免覆盖 SW 中已打开的文件
    from datetime import datetime
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    p = Path(output_base)
    output_path = str(p.parent / f"{p.stem}_{ts}{p.suffix}")
    print(f"  输出: {output_path}")

    print("=" * 60)
    print("DXF 阶梯轴 → SolidWorks .sldprt 原生文件")
    print("=" * 60)

    # Step 1: 解析 DXF
    print(f"\n[1/3] 解析 DXF: {dxf_path}")
    try:
        geometry = parse_shaft_from_dxf(dxf_path)
    except Exception as e:
        print(f"[FAIL] DXF 解析失败: {e}")
        sys.exit(1)

    sections = dxf_to_sw_sections(geometry["sections"])
    keyways = dxf_to_sw_keyways(geometry["keyways"])

    # 从 DXF 中提取倒角和圆角参数
    fillet_r_mm = geometry.get("fillet_radius", DEFAULT_FILLET_R_MM)
    left_chamfer, right_chamfer = extract_chamfer_params(
        geometry.get("chamfers", [])
    )

    print(f"  识别到 {len(sections)} 个轴段, {len(keyways)} 个键槽")
    for i, s in enumerate(sections):
        print(f"    段{i+1}: X {s[0]:.1f} ~ {s[1]:.1f} mm, 半径 R{s[2]:.1f} mm")
    for i, kw in enumerate(keyways):
        print(f"    键槽{i+1}: X {kw[0]:.1f} ~ {kw[1]:.1f} mm, "
              f"{kw[2]:.0f}×{kw[3]:.0f} mm")
    print(f"  DXF 圆角半径: R{fillet_r_mm:.1f}")
    print(f"  DXF 倒角: 左端 C{left_chamfer:.1f}, 右端 C{right_chamfer:.1f}")
    if left_chamfer == 0.0 and right_chamfer == 0.0:
        print(f"    (未检测到倒角线，使用默认 C{DEFAULT_CHAMFER_MM})")

    # Step 2: SW 建模
    print(f"\n[2/3] 连接 SolidWorks 并建模 ...")
    driver = SolidWorksDriver(visible=True)
    if not driver.connect():
        print("[FAIL] 无法连接 SolidWorks，请确认 SW 2025 已启动")
        sys.exit(1)

    try:
        if not driver.new_part():
            print("[FAIL] 无法创建新零件")
            sys.exit(1)

        # 使用 ShaftBuilder
        builder = ShaftBuilder(driver)
        ok = builder.build(
            sections=sections,
            keyways=keyways,
            left_chamfer_mm=left_chamfer if left_chamfer > 0 else 0.0,
            right_chamfer_mm=right_chamfer if right_chamfer > 0 else 0.0,
            fillet_r_mm=fillet_r_mm,
        )

        driver.rebuild()
        driver.zoom_to_fit()

        if ok:
            print("\n" + "=" * 60)
            print("阶梯轴建模成功！")
            print("特征树:")
            print("  1. Revolve-ShaftBody (旋转基体)")
            feat_num = 2
            if left_chamfer > 0:
                print(f"  {feat_num}. Chamfer-LeftEnd (左端倒角 C{left_chamfer:.1f})")
                feat_num += 1
            if right_chamfer > 0:
                print(f"  {feat_num}. Chamfer-RightEnd (右端倒角 C{right_chamfer:.1f})")
                feat_num += 1
            print(f"  {feat_num}. Fillet-Transitions (过渡圆角 R{fillet_r_mm:.1f})")
            feat_num += 1
            for i, kw in enumerate(keyways):
                print(f"  {feat_num+i}. Keyway-{i+1} (键槽 {kw[2]:.0f}×{kw[3]:.0f}mm)")
            print("=" * 60)
        else:
            print("\n[WARN] 部分步骤未成功，请检查 SolidWorks 特征树")

        # Step 3: 保存
        print(f"\n[3/3] 保存 .sldprt: {output_path}")
        ok = driver.save_as(output_path)
        if ok:
            print(f"[OK] 文件已保存: {output_path}")
        else:
            print("[FAIL] 保存失败 — 请确认 SW 中无同名文件打开且磁盘空间充足")

    except Exception as e:
        print(f"\n[FAIL] 未预期的异常: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    finally:
        driver.disconnect()


if __name__ == "__main__":
    main()
