"""从 GT 电机模型生成理想 DXF 二维图 v3.

关键改进:
- 每个视图只有 1 个外轮廓（单一封闭多边形）
- 全部孔作为 CIRCLE 实体（自动成为独立面）
- 视图共享 X 轴对齐，Y 方向有清晰间隙
"""

import ezdxf
from pathlib import Path

OUTPUT = Path(__file__).parent / "motor_ideal_v3.dxf"


def add_polyline(msp, pts, layer="GEOMETRY"):
    """添加封闭多段线。pts: [(x, y), ...]"""
    msp.add_lwpolyline(pts, close=True, dxfattribs={"layer": layer})


def add_circle(msp, cx, cy, r, layer="GEOMETRY"):
    msp.add_circle((cx, cy), radius=r, dxfattribs={"layer": layer})


def main():
    doc = ezdxf.new()
    msp = doc.modelspace()
    doc.layers.add("GEOMETRY", color=7)

    doc.header["$DIMLFAC"] = 1.0
    doc.header["$DIMSCALE"] = 1.0
    doc.header["$MEASUREMENT"] = 1
    doc.header["$INSUNITS"] = 4

    # GT: X[-40,40], Y[-40,40], Z[-26.5,70.4]
    XC = 120.0  # 所有视图共享的 X 中心

    # ============ 前视图 (X-Z): 单一阶梯轮廓 ============
    # 底座宽80 高26.5 + 机体宽60 高70.4（居中放置）
    # DXF: X = GT_X + XC, Y = GT_Z + Z_OFFSET
    Z_OFFSET = 100.0

    def fx(gx): return gx + XC
    def fy(gz): return gz + Z_OFFSET

    # 单一封闭轮廓（逆时针）
    front_pts = [
        (fx(-40), fy(-26.5)),   # 左下
        (fx(40), fy(-26.5)),    # 右下
        (fx(40), fy(0)),        # 底座右上
        (fx(30), fy(0)),        # 机体右下
        (fx(30), fy(70.4)),     # 机体右上
        (fx(-30), fy(70.4)),    # 机体左上
        (fx(-30), fy(0)),       # 机体左下
        (fx(-40), fy(0)),       # 底座左上
    ]
    add_polyline(msp, front_pts)

    front_ymax = fy(70.4) + 15

    # ============ 俯视图 (X-Y): 方形轮廓 + 全部孔 ============
    TY_OFFSET = front_ymax + 35

    def tx(gx): return gx + XC
    def ty(gy): return gy + TY_OFFSET

    # 单一方形轮廓
    top_pts = [
        (tx(-40), ty(-40)),
        (tx(40), ty(-40)),
        (tx(40), ty(40)),
        (tx(-40), ty(40)),
    ]
    add_polyline(msp, top_pts)

    # ---- 全部孔（作为 CIRCLE 实体） ----
    # 1) 4 个安装孔 R=1.6
    for gx in [-24.7, 24.7]:
        for gy in [-24.7, 24.7]:
            add_circle(msp, tx(gx), ty(gy), 1.6)

    # 2) 中心各级台阶孔（从大到小，确保同心检测）
    #    从 GT 提取的所有可见半径
    for r in [40.0, 30.0, 25.0, 21.0, 16.0, 8.5, 8.0, 7.0, 6.0]:
        add_circle(msp, tx(0), ty(0), r)

    # 3) 台阶沉头孔 R=2.7（在底座四角上方）
    for gx in [-24.7, 24.7]:
        for gy in [-24.7, 24.7]:
            add_circle(msp, tx(gx), ty(gy), 2.7)

    top_ymax = ty(40) + 15

    # ============ 侧视图 (Y-Z): 单一阶梯轮廓 ============
    SX_OFFSET = XC + 110.0

    def sx(gy): return gy + SX_OFFSET
    def sy(gz): return gz + Z_OFFSET

    side_pts = [
        (sx(-40), sy(-26.5)),
        (sx(40), sy(-26.5)),
        (sx(40), sy(0)),
        (sx(30), sy(0)),
        (sx(30), sy(70.4)),
        (sx(-30), sy(70.4)),
        (sx(-30), sy(0)),
        (sx(-40), sy(0)),
    ]
    add_polyline(msp, side_pts)

    # ---- 保存 ----
    doc.saveas(str(OUTPUT))
    print(f"理想 DXF v3 已生成: {OUTPUT}")

    doc2 = ezdxf.readfile(str(OUTPUT))
    msp2 = doc2.modelspace()
    circles = list(msp2.query("CIRCLE"))
    lwpolys = list(msp2.query("LWPOLYLINE"))
    print(f"实体: CIRCLE={len(circles)}, LWPOLYLINE={len(lwpolys)}")

    # 验证视图边界
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
        print(f"  轮廓: X[{min(xs):.0f}~{max(xs):.0f}] Y[{min(ys):.0f}~{max(ys):.0f}] "
              f"宽={max(xs)-min(xs):.0f} 高={max(ys)-min(ys):.0f}")


if __name__ == "__main__":
    main()
