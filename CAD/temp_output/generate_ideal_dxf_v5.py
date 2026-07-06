"""理想 DXF v5 — 修正 CSG 视图映射.

CSG 视图约定:
- "front": 显示 3D_X × 3D_Y (GT的XY面, 80×80)
- "top":   显示 3D_X × 3D_Z (GT的XZ面, 80×97阶梯)
"""

import ezdxf
from pathlib import Path

OUTPUT = Path(__file__).parent / "motor_ideal_v5.dxf"


def add_polyline(msp, pts):
    msp.add_lwpolyline(pts, close=True, dxfattribs={"layer": "GEOMETRY"})


def add_circle(msp, cx, cy, r):
    msp.add_circle((cx, cy), radius=r, dxfattribs={"layer": "GEOMETRY"})


def main():
    doc = ezdxf.new()
    msp = doc.modelspace()
    doc.layers.add("GEOMETRY", color=7)

    doc.header["$DIMLFAC"] = 1.0
    doc.header["$DIMSCALE"] = 1.0
    doc.header["$MEASUREMENT"] = 1
    doc.header["$INSUNITS"] = 4

    XC = 120.0

    # ============ 俯视图 (CSG "front"): XY 面 ============
    # GT X[-40,40]=80, GT Y[-40,40]=80 → 80×80 方形 + 全部孔
    # DXF: X = GT_X + XC, Y = GT_Y + 100
    BASE_Y = 100.0

    def fx(gx): return gx + XC
    def fy(gy): return gy + BASE_Y

    # 方形轮廓（稍大 81×81，避免 R=40 内切）
    H = 40.5
    add_polyline(msp, [
        (fx(-H), fy(-H)),
        (fx(H), fy(-H)),
        (fx(H), fy(H)),
        (fx(-H), fy(H)),
    ])

    # 4 个安装孔 R=1.6 at (±24.7, ±24.7)
    for gx in [-24.7, 24.7]:
        for gy in [-24.7, 24.7]:
            add_circle(msp, fx(gx), fy(gy), 1.6)

    # 中心各级台阶孔
    for r in [40.0, 30.0, 25.0, 21.0, 16.0, 8.5, 8.0, 7.0, 6.0]:
        add_circle(msp, fx(0), fy(0), r)

    # 沉头孔 R=2.7
    for gx in [-24.7, 24.7]:
        for gy in [-24.7, 24.7]:
            add_circle(msp, fx(gx), fy(gy), 2.7)

    front_ymax = fy(H) + 15  # ≈ 156

    # ============ 侧视图 (CSG "top"): XZ 面 ============
    # GT X[-40,40]=80, GT Z[-26.5,70.4]=96.9 → 阶梯轮廓
    # DXF: X = GT_X + XC, Y = GT_Z + TY_BASE
    TY_BASE = front_ymax + 35

    def tx(gx): return gx + XC
    def ty(gz): return gz + TY_BASE

    # 侧视阶梯轮廓（与 Z 轴对齐）
    add_polyline(msp, [
        (tx(-40), ty(-26.5)),
        (tx(40), ty(-26.5)),
        (tx(40), ty(0)),
        (tx(30), ty(0)),
        (tx(30), ty(70.4)),
        (tx(-30), ty(70.4)),
        (tx(-30), ty(0)),
        (tx(-40), ty(0)),
    ])

    side_ymax = ty(70.4) + 15

    # ============ 前视图 (CSG "side" 可选): YZ 面 ============
    # GT Y[-40,40]=80, GT Z[-26.5,70.4]=96.9 → 阶梯轮廓
    SX_BASE = XC + 120
    SY_BASE = BASE_Y  # 与俯视图共享 Y

    def sx(gy): return gy + SX_BASE
    def sy(gz): return gz + SY_BASE

    add_polyline(msp, [
        (sx(-40), sy(-26.5)),
        (sx(40), sy(-26.5)),
        (sx(40), sy(0)),
        (sx(30), sy(0)),
        (sx(30), sy(70.4)),
        (sx(-30), sy(70.4)),
        (sx(-30), sy(0)),
        (sx(-40), sy(0)),
    ])

    # ---- 保存 ----
    doc.saveas(str(OUTPUT))
    print(f"理想 DXF v5 已生成: {OUTPUT}")

    doc2 = ezdxf.readfile(str(OUTPUT))
    circles = list(doc2.query("CIRCLE"))
    lwpolys = list(doc2.query("LWPOLYLINE"))
    print(f"实体: CIRCLE={len(circles)}, LWPOLYLINE={len(lwpolys)}")

    for lp in lwpolys:
        pts_raw = list(lp.vertices())
        pts = []
        for p in pts_raw:
            if isinstance(p, tuple): pts.append(p)
            elif hasattr(p, 'dxf'): pts.append((p.dxf.location.x, p.dxf.location.y))
            else: pts.append((p.location.x, p.location.y))
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        print(f"  轮廓: X[{min(xs):.0f}~{max(xs):.0f}] Y[{min(ys):.0f}~{max(ys):.0f}]"
              f" {max(xs)-min(xs):.0f}x{max(ys)-min(ys):.0f}mm")

    top_ymin = ty(-26.5)
    print(f"\n俯视Ymax={front_ymax:.0f}, 侧视Ymin={top_ymin:.0f}, 间隙={top_ymin-front_ymax:.0f}mm")


if __name__ == "__main__":
    main()
