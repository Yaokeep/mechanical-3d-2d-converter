"""DXF 阶梯轴 → SolidWorks .sldprt 原生文件

使用 src.core.sw_automation (v0.4.1+) 的 SW COM 驱动 + DXF 几何解析。
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


def main():
    dxf_path = "CAD/20160112-181116-09933.dxf"
    output_path = str(Path("CAD/20160112-181116-09933.sldprt").absolute())

    print("=" * 60)
    print("DXF 阶梯轴 → SolidWorks .sldprt 原生文件")
    print("=" * 60)

    # Step 1: 解析 DXF
    print(f"\n[1/3] 解析 DXF: {dxf_path}")
    geometry = parse_shaft_from_dxf(dxf_path)
    sections = dxf_to_sw_sections(geometry["sections"])
    keyways = dxf_to_sw_keyways(geometry["keyways"])

    # Step 2: SW 建模
    print(f"\n[2/3] 连接 SolidWorks 并建模 ...")
    driver = SolidWorksDriver(visible=True)
    if not driver.connect():
        print("[FAIL] 无法连接 SolidWorks")
        sys.exit(1)

    try:
        if not driver.new_part():
            print("[FAIL] 无法创建新零件")
            sys.exit(1)

        # 使用 ShaftBuilder (v0.4.1 修复版)
        builder = ShaftBuilder(driver)
        ok = builder.build(
            sections=sections,
            keyways=keyways,
            chamfer_mm=DEFAULT_CHAMFER_MM,
            fillet_r_mm=DEFAULT_FILLET_R_MM,
        )

        driver.rebuild()
        driver.zoom_to_fit()

        if ok:
            print("\n" + "=" * 60)
            print("阶梯轴建模成功！")
            print("特征树:")
            print("  1. Revolve-ShaftBody (旋转基体)")
            print(f"  2. Chamfer-LeftEnd (左端倒角 C{DEFAULT_CHAMFER_MM})")
            print(f"  3. Chamfer-RightEnd (右端倒角 C{DEFAULT_CHAMFER_MM})")
            print(f"  4. Fillet-Transitions (过渡圆角 R{DEFAULT_FILLET_R_MM})")
            for i, kw in enumerate(keyways):
                print(f"  {5+i}. Keyway-{i+1} (键槽 {kw[2]:.0f}×{kw[3]:.0f}mm)")
            print("=" * 60)
        else:
            print("\n[WARN] 部分步骤未成功，请检查 SolidWorks 特征树")

        # Step 3: 保存
        print(f"\n[3/3] 保存 .sldprt: {output_path}")
        driver.save_as(output_path)

    except Exception as e:
        print(f"\n[FAIL] 未预期的异常: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    finally:
        driver.disconnect()


if __name__ == "__main__":
    main()
