"""理想 DXF v4 — 修复视图分离和面检测问题。

关键修正:
- 视图间 Y 间隙 > 25mm（远超 15mm 阈值）
- 俯视图外轮廓 82×82（避免 R=40 圆与边界相切导致面合并）
- 只保留 2 视图（前+俯），CSG 3 棱柱交集足够
"""

import ezdxf
from pathlib import Path

OUTPUT = Path(__file__).parent / "motor_ideal_v4.dxf"


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

    XC = 120.0  # 所有视图共享的 X 中心

    # ============ 前视图 (X-Z): 阶梯轮廓 ============
    # GT Z[-26.5, 70.4] → DXF Y[73.5, 170.4]
    Z_OFFSET = 100.0

    def fx(gx): return gx + XC
    def fy(gz): return gz + Z_OFFSET

    front_pts = [
        (fx(-40), fy(-26.5)),
        (fx(40), fy(-26.5)),
        (fx(40), fy(0)),
        (fx(30), fy(0)),
        (fx(30), fy(70.4)),
        (fx(-30), fy(70.4)),
        (fx(-30), fy(0)),
        (fx(-40), fy(0)),
    ]
    add_polyline(msp, front_pts)
    front_ymax = fy(70.4) + 5  # 170.4 + 5 = 175.4

    # ============ 俯视图 (X-Y): 方形+孔 ============
    # 确保与前视图 Y 间隙 > 25mm
    # 俯视图 Y 中心 = front_ymax + 30 + 40.5  ≈ 246
    TY_CENTER = front_ymax + 30 + 40.5  # ≈ 246

    def tx(gx): return gx + XC
    def ty(gy): return gy + TY_CENTER

    # 外轮廓稍大 81mm（原80），避免 R=40 内切于边界
    HALF = 40.5  # 81/2
    top_pts = [
        (tx(-HALF), ty(-HALF)),
        (tx(HALF), ty(-HALF)),
        (tx(HALF), ty(HALF)),
        (tx(-HALF), ty(HALF)),
    ]
    add_polyline(msp, top_pts)

    # ---- 全部孔 ----
    # 1) 4 个安装孔 R=1.6
    for gx in [-24.7, 24.7]:
        for gy in [-24.7, 24.7]:
            add_circle(msp, tx(gx), ty(gy), 1.6)

    # 2) 中心各级台阶孔
    for r in [40.0, 30.0, 25.0, 21.0, 16.0, 8.5, 8.0, 7.0, 6.0]:
        add_circle(msp, tx(0), ty(0), r)

    # 3) 沉头孔 R=2.7
    for gx in [-24.7, 24.7]:
        for gy in [-24.7, 24.7]:
            add_circle(msp, tx(gx), ty(gy), 2.7)

    # ---- 保存 ----
    doc.saveas(str(OUTPUT))
    print(f"理想 DXF v4 已生成: {OUTPUT}")

    doc2 = ezdxf.readfile(str(OUTPUT))
    msp2 = doc2.modelspace()
    circles = list(msp2.query("CIRCLE"))
    lwpolys = list(msp2.query("LWPOLYLINE"))
    print(f"实体: CIRCLE={len(circles)}, LWPOLYLINE={len(lwpolys)}")

    for lp in lwpolys:
        pts_raw = list(lp.vertices())
        pts = []
        for p in pts_raw:
            if isinstance(p, tuple):
                pts.append(p)
            elif hasattr(p, 'dxf'):
                pts.append((p.dxf.location.x, p.dxf.location.y))
            else:
                pts.append((p.location.x, p.location.y))
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        print(f"  轮廓: X[{min(xs):.0f}~{max(xs):.0f}] Y[{min(ys):.0f}~{max(ys):.0f}]"
              f" 宽={max(xs)-min(xs):.1f} 高={max(ys)-min(ys):.1f}")

    # 验证 Y 间隙
    top_ymin = ty(-HALF)
    print(f"\n前视图 Ymax={front_ymax:.0f}, 俯视图 Ymin={top_ymin:.0f}")
    print(f"Y 间隙 = {top_ymin - front_ymax:.0f}mm")


if __name__ == "__main__":
    main()
