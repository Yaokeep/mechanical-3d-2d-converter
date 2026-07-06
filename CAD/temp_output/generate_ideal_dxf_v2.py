"""从 GT 电机模型生成理想 DXF 二维图 v2.

关键设计:
- 前视图：仅外轮廓（无内部孔），确保 CSG 正确找到 XY 轮廓
- 俯视图：外轮廓 + 全部圆孔，用于 Z 深度 + 孔位置
- 侧视图：外轮廓，用于 YZ 约束
- 视图之间清晰分离（Y 间隙 > 30mm）
- DIMLFAC=1.0（1:1 比例）
- 所有孔使用 FULL CIRCLE（ezdxf 自动拆为 2 个 180° ARC）
"""

import ezdxf
from pathlib import Path

OUTPUT = Path(__file__).parent / "motor_ideal_v2.dxf"


def add_circle(msp, cx, cy, r):
    msp.add_circle((cx, cy), radius=r,
                   dxfattribs={"layer": "GEOMETRY"})


def add_rect(msp, x1, y1, x2, y2):
    pts = [(x1, y1), (x2, y1), (x2, y2), (x1, y2)]
    msp.add_lwpolyline(pts, close=True,
                       dxfattribs={"layer": "GEOMETRY"})


def main():
    doc = ezdxf.new()
    msp = doc.modelspace()
    doc.layers.add("GEOMETRY", color=7)
    doc.layers.add("HIDDEN", color=8)

    # 1:1 比例
    doc.header["$DIMLFAC"] = 1.0
    doc.header["$DIMSCALE"] = 1.0
    doc.header["$MEASUREMENT"] = 1
    doc.header["$INSUNITS"] = 4

    # ================================================================
    # 坐标系：所有视图共享 X 轴对齐
    # GT 模型: X[-40,40], Y[-40,40], Z[-26.5,70.4]
    # 总体尺寸: 80×80×96.9mm
    # ================================================================
    X_CENTER = 120.0  # DXF 中所有视图的 X 中心

    # ---- 前视图 (Front): 看向 -Y, 显示 X-Z 面 ----
    # 只有外轮廓（无孔！）
    FY_OFFSET = 100.0  # GT Z=-26.5 → DXF Y=73.5

    def fx(gx): return gx + X_CENTER
    def fy(gz): return gz + FY_OFFSET

    # 底座外轮廓 (80×26.5)
    add_rect(msp, fx(-40), fy(-26.5), fx(40), fy(0))
    # 机体外轮廓 (60×70.4)
    add_rect(msp, fx(-30), fy(0), fx(30), fy(70.4))

    front_y_max = fy(70.4) + 15

    # ---- 俯视图 (Top): 看向 -Z, 显示 X-Y 面 ----
    # 外轮廓 + 全部圆孔
    TY_OFFSET = front_y_max + 35

    def tx(gx): return gx + X_CENTER
    def ty(gy): return gy + TY_OFFSET

    # 外轮廓
    add_rect(msp, tx(-40), ty(-40), tx(40), ty(40))
    # 机体轮廓
    add_rect(msp, tx(-30), ty(-30), tx(30), ty(30))

    # 4 个安装孔 R=1.6 at (±24.7, ±24.7)
    for gx in [-24.7, 24.7]:
        for gy in [-24.7, 24.7]:
            add_circle(msp, tx(gx), ty(gy), 1.6)

    # 中心各级圆孔（所有可见台阶）
    center_radii = [40.0, 30.0, 25.0, 21.0, 16.0, 8.5, 8.0, 7.0, 6.0, 2.7]
    for r in center_radii:
        add_circle(msp, tx(0), ty(0), r)

    # 台阶孔 R=2.7 at 四个位置 (在 Z=-10.5 和 Z=49.0 高度)
    for gx in [-24.7, 24.7]:
        for gy in [-24.7, 24.7]:
            add_circle(msp, tx(gx), ty(gy), 2.7)

    top_y_max = ty(40) + 15

    # ---- 侧视图 (Side): 看向 X, 显示 Y-Z 面 ----
    # 只有外轮廓
    SX_OFFSET = X_CENTER + 110.0  # 偏移到右侧

    def sx(gy): return gy + SX_OFFSET
    def sy(gz): return gz + FY_OFFSET  # 与前视图共享 Y 偏移

    # 底座外轮廓
    add_rect(msp, sx(-40), sy(-26.5), sx(40), sy(0))
    # 机体外轮廓
    add_rect(msp, sx(-30), sy(0), sx(30), sy(70.4))

    # ---- 保存 ----
    doc.saveas(str(OUTPUT))
    print(f"理想 DXF v2 已生成: {OUTPUT}")

    # 验证
    doc2 = ezdxf.readfile(str(OUTPUT))
    msp2 = doc2.modelspace()
    circles = list(msp2.query("CIRCLE"))
    lwpolys = list(msp2.query("LWPOLYLINE"))
    print(f"实体: CIRCLE={len(circles)}, LWPOLYLINE={len(lwpolys)}")
    print(f"总计: {len(circles) + len(lwpolys)} 几何实体")

    # 打印视图布局
    for lp in lwpolys:
        pts = list(lp.vertices())
        if not pts:
            continue
        xs = [p[0] if isinstance(p, tuple) else p.dxf.location.x for p in pts]
        ys = [p[1] if isinstance(p, tuple) else p.dxf.location.y for p in pts]
        print(f"  矩形: X[{min(xs):.0f}~{max(xs):.0f}] Y[{min(ys):.0f}~{max(ys):.0f}]")

    print(f"\n前视图 Y 范围: {fy(-26.5):.0f} ~ {fy(70.4):.0f}")
    print(f"俯视图 Y 范围: {ty(-40):.0f} ~ {ty(40):.0f}")
    print(f"侧视图 Y 范围: {sy(-26.5):.0f} ~ {sy(70.4):.0f}")
    print(f"视图间 Y 间隙: 前→俯 = {ty(-40) - fy(70.4):.0f}mm")


if __name__ == "__main__":
    main()
