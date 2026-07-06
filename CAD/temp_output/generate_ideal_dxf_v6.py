"""理想 DXF v6 — 纯 2 视图 CSG.

View 1 (XY): GT_X × GT_Y = 80×80, Y[60,141]
View 2 (XZ): GT_X × GT_Z = 80×97, Y[180,277]
共享 X 坐标 [80,160], Y 间隙 = 180-141 = 39mm > 25mm
"""

import ezdxf
from pathlib import Path

OUTPUT = Path(__file__).parent / "motor_ideal_v6.dxf"


def add_polyline(msp, pts):
    msp.add_lwpolyline(pts, close=True, dxfattribs={"layer": "GEOMETRY"})


def add_circle(msp, cx, cy, r):
    msp.add_circle((cx, cy), radius=r, dxfattribs={"layer": "GEOMETRY"})


def main():
    doc = ezdxf.new()
    msp = doc.modelspace()
    doc.layers.add("GEOMETRY", color=7)

    doc.header["$DIMLFAC"] = 1.0
    doc.header["$MEASUREMENT"] = 1
    doc.header["$INSUNITS"] = 4

    XC = 120.0  # 共享 X 中心

    # ============ View 1: XY面 (CSG "front") ============
    # 80×80 方形 + 全部圆孔
    # DXF Y = GT_Y + 100
    Y1_BASE = 100.0

    def f1x(gx): return gx + XC
    def f1y(gy): return gy + Y1_BASE

    H = 40.5  # 81/2, 稍大避免 R=40 内切
    add_polyline(msp, [
        (f1x(-H), f1y(-H)), (f1x(H), f1y(-H)),
        (f1x(H), f1y(H)), (f1x(-H), f1y(H)),
    ])

    for gx in [-24.7, 24.7]:
        for gy in [-24.7, 24.7]:
            add_circle(msp, f1x(gx), f1y(gy), 1.6)
    for r in [40.0, 30.0, 25.0, 21.0, 16.0, 8.5, 8.0, 7.0, 6.0]:
        add_circle(msp, f1x(0), f1y(0), r)
    for gx in [-24.7, 24.7]:
        for gy in [-24.7, 24.7]:
            add_circle(msp, f1x(gx), f1y(gy), 2.7)

    v1_ymax = f1y(H)  # 140.5

    # ============ View 2: XZ面 (CSG "top") ============
    # 80×97 阶梯轮廓
    # DXF Y = GT_Z + Y2_BASE
    # Y 间隙 = 180 - 140.5 ≈ 39mm
    Y2_BASE = v1_ymax + 40 + 26.5  # 确保 Z=-26.5→Y=140.5+40=180.5

    def f2x(gx): return gx + XC  # 共享 X!
    def f2y(gz): return gz + Y2_BASE

    # 阶梯轮廓
    add_polyline(msp, [
        (f2x(-40), f2y(-26.5)), (f2x(40), f2y(-26.5)),
        (f2x(40), f2y(0)), (f2x(30), f2y(0)),
        (f2x(30), f2y(70.4)), (f2x(-30), f2y(70.4)),
        (f2x(-30), f2y(0)), (f2x(-40), f2y(0)),
    ])

    # ---- 保存 ----
    doc.saveas(str(OUTPUT))
    print(f"理想 DXF v6: {OUTPUT}")

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

    print(f"\nView1 Ymax={v1_ymax:.0f}, View2 Ymin={f2y(-26.5):.0f}")
    print(f"Y间隙={f2y(-26.5)-v1_ymax:.0f}mm")
    print(f"共享 X 范围: [{f2x(-40):.0f}, {f2x(40):.0f}]")


if __name__ == "__main__":
    main()
