"""理想 DXF v7 — 正确区分凸台 vs 内孔.

XY视图: 80×80方形 + 4个安装孔(R=1.6) + 4个沉头孔(R=2.7), 无中心圆
XZ视图: 80×97阶梯轮廓 (包含中心孔形状)
"""

import ezdxf
from pathlib import Path

OUTPUT = Path(__file__).parent / "motor_ideal_v7.dxf"


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

    XC = 120.0

    # ============ View 1: XY面 (CSG "front") ============
    # 80×80 方形 + 安装孔 + 沉头孔
    # 注意：使用 81mm 方形（避免 R=2.7 孔与边界干涉）
    Y1_BASE = 100.0

    def f1x(gx): return gx + XC
    def f1y(gy): return gy + Y1_BASE

    H = 40.0  # 80/2
    add_polyline(msp, [
        (f1x(-H), f1y(-H)), (f1x(H), f1y(-H)),
        (f1x(H), f1y(H)), (f1x(-H), f1y(H)),
    ])

    # 4 个安装孔 R=1.6（通孔）
    for gx in [-24.7, 24.7]:
        for gy in [-24.7, 24.7]:
            add_circle(msp, f1x(gx), f1y(gy), 1.6)

    v1_ymax = f1y(H)  # 140.5

    # ============ View 2: XZ面 (CSG "top") ============
    # 80×97 阶梯轮廓
    Y2_BASE = v1_ymax + 40 + 26.5  # Z=-26.5 → Y=140.5+40=180.5

    def f2x(gx): return gx + XC
    def f2y(gz): return gz + Y2_BASE

    add_polyline(msp, [
        (f2x(-40), f2y(-26.5)), (f2x(40), f2y(-26.5)),
        (f2x(40), f2y(0)), (f2x(30), f2y(0)),
        (f2x(30), f2y(70.4)), (f2x(-30), f2y(70.4)),
        (f2x(-30), f2y(0)), (f2x(-40), f2y(0)),
    ])

    doc.saveas(str(OUTPUT))
    print(f"理想 DXF v7: {OUTPUT}")

    doc2 = ezdxf.readfile(str(OUTPUT))
    circles = list(doc2.query("CIRCLE"))
    lwpolys = list(doc2.query("LWPOLYLINE"))
    print(f"CIRCLE={len(circles)}, LWPOLYLINE={len(lwpolys)}")
    for lp in lwpolys:
        pts = []
        for p in lp.vertices():
            if isinstance(p, tuple): pts.append(p)
            elif hasattr(p, 'dxf'): pts.append((p.dxf.location.x, p.dxf.location.y))
            else: pts.append((p.location.x, p.location.y))
        xs = [p[0] for p in pts]; ys = [p[1] for p in pts]
        print(f"  轮廓: X[{min(xs):.0f}~{max(xs):.0f}] Y[{min(ys):.0f}~{max(ys):.0f}]"
              f" {max(xs)-min(xs):.0f}x{max(ys)-min(ys):.0f}")
    print(f"Y间隙={f2y(-26.5)-v1_ymax:.0f}mm")


if __name__ == "__main__":
    main()
