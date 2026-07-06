"""从 GT 电机模型生成理想 DXF 二维图 — 包含 CSG 算法所需的全部几何数据."""

import math
import ezdxf
from pathlib import Path

OUTPUT = Path(__file__).parent / "motor_ideal.dxf"


def add_circle(msp, cx, cy, r, layer="GEOMETRY"):
    """添加完整圆（确保封闭环检测能识别）。"""
    # ezdxf 的 CIRCLE 被 parse_dxf_edges 拆为 2 个 180° ARC
    msp.add_circle((cx, cy), radius=r, dxfattribs={"layer": layer})


def add_rect(msp, x1, y1, x2, y2, layer="GEOMETRY"):
    """添加矩形轮廓（LWPOLYLINE 封闭）。"""
    pts = [(x1, y1), (x2, y1), (x2, y2), (x1, y2)]
    msp.add_lwpolyline(pts, close=True, dxfattribs={"layer": layer})


def main():
    doc = ezdxf.new()
    msp = doc.modelspace()

    # ---- 图层 ----
    doc.layers.add("GEOMETRY", color=7)     # 白色 = 几何轮廓
    doc.layers.add("HIDDEN", color=8)       # 灰色 = 隐藏线（可选）
    doc.layers.add("CENTER", color=1)       # 红色 = 中心线（可选）

    # ---- DIMLFAC = 1.0 (1:1 比例) ----
    doc.header["$DIMLFAC"] = 1.0
    doc.header["$DIMSCALE"] = 1.0
    doc.header["$MEASUREMENT"] = 1
    doc.header["$INSUNITS"] = 4  # mm

    # ---- 坐标偏移 ----
    X_OFFSET = 120.0  # 视图 X 中心

    # ================================================================
    # 前视图 (Front): 看向 -Y, 显示 X(宽) × Z(高)
    # GT: X[-40,40]=80mm, Z[-26.5,70.4]=96.9mm
    # DXF: X = GT_X + X_OFFSET, Y = GT_Z + 80
    # ================================================================
    FY_BASE = 50.0  # 前视图 Y 基准

    def gt_to_front(gx, gz):
        """GT 坐标 → 前视图 DXF 坐标。"""
        return (gx + X_OFFSET, gz + FY_BASE + 26.5)  # Z=-26.5 → Y=50

    # 底座轮廓
    fx1, fy1 = gt_to_front(-40, -26.5)
    fx2, fy2 = gt_to_front(40, 0)
    add_rect(msp, fx1, fy1, fx2, fy2)

    # 机体轮廓
    fx1, fy1 = gt_to_front(-30, 0)
    fx2, fy2 = gt_to_front(30, 70.4)
    add_rect(msp, fx1, fy1, fx2, fy2)

    # 4 个安装孔 (底座上, R=1.6mm, 贯穿)
    for gx in [-24.7, 24.7]:
        fx, fy = gt_to_front(gx, -26.5)  # 孔在底座底面
        add_circle(msp, fx, fy + 13.25, 1.6)  # 画在底座中部偏上（可见）

    # 中心孔可见轮廓 (Z 方向的各级台阶)
    center_steps_front = [
        (40.0, 0.0),     # R=40 at Z=0 (底座顶面)
        (30.0, 0.0),     # R=30 at Z=0 (机体底面)
        (25.0, 5.0),     # R=25 at Z=5
        (21.0, 5.0),     # R=21 at Z=5
        (16.0, 5.0),     # R=16 at Z=5
        (8.5, 70.4),     # R=8.5 at Z=70.4 (顶部开口)
    ]
    for r, gz in center_steps_front:
        fx, fy = gt_to_front(0, gz)
        add_circle(msp, fx, fy, r)

    # 前视图 Y 范围标记
    front_y_max = gt_to_front(0, 70.4)[1] + 10

    # ================================================================
    # 俯视图 (Top): 看向 -Z, 显示 X(宽) × Y(深)
    # GT: X[-40,40]=80mm, Y[-40,40]=80mm
    # DXF: X = GT_X + X_OFFSET, Y = GT_Y + TY_BASE
    # ================================================================
    TY_BASE = front_y_max + 30  # 与俯视图之间留 30mm 间隙

    def gt_to_top(gx, gy):
        """GT 坐标 → 俯视图 DXF 坐标。"""
        return (gx + X_OFFSET, gy + TY_BASE)

    # 底座轮廓
    tx1, ty1 = gt_to_top(-40, -40)
    tx2, ty2 = gt_to_top(40, 40)
    add_rect(msp, tx1, ty1, tx2, ty2)

    # 机体轮廓
    tx1, ty1 = gt_to_top(-30, -30)
    tx2, ty2 = gt_to_top(30, 30)
    add_rect(msp, tx1, ty1, tx2, ty2)

    # 4 个安装孔
    for gx in [-24.7, 24.7]:
        for gy in [-24.7, 24.7]:
            tx, ty = gt_to_top(gx, gy)
            add_circle(msp, tx, ty, 1.6)

    # 中心各级圆孔（从顶视图可见）
    center_steps_top = [
        (40.0, 0, 0),   # 底座顶面孔——最大
        (30.0, 0, 0),   # 机体内孔
        (25.0, 0, 0),
        (21.0, 0, 0),
        (16.0, 0, 0),
        (8.5, 0, 0),    # 顶部最小孔
    ]
    for r, gx, gy in center_steps_top:
        tx, ty = gt_to_top(gx, gy)
        add_circle(msp, tx, ty, r)

    # 俯视图 Y 范围标记
    top_y_max = gt_to_top(0, 40)[1] + 10

    # ================================================================
    # 侧视图 (Side): 看向 X, 显示 Y(深) × Z(高)
    # GT: Y[-40,40]=80mm, Z[-26.5,70.4]=96.9mm
    # DXF: X = GT_Y + SX_OFFSET, Y = GT_Z + SY_BASE
    # ================================================================
    SX_OFFSET = X_OFFSET + 100  # 侧视图 X 偏移（不与前/俯视图重叠）
    SY_BASE = FY_BASE  # 与前视图同 Y 基准（共享 Y=高度）

    def gt_to_side(gy, gz):
        """GT 坐标 → 侧视图 DXF 坐标。"""
        return (gy + SX_OFFSET, gz + SY_BASE + 26.5)

    # 底座轮廓
    sx1, sy1 = gt_to_side(-40, -26.5)
    sx2, sy2 = gt_to_side(40, 0)
    add_rect(msp, sx1, sy1, sx2, sy2)

    # 机体轮廓
    sx1, sy1 = gt_to_side(-30, 0)
    sx2, sy2 = gt_to_side(30, 70.4)
    add_rect(msp, sx1, sy1, sx2, sy2)

    # 4 个安装孔 (侧视可见的)
    for gy in [-24.7, 24.7]:
        sx, sy = gt_to_side(gy, -26.5)
        add_circle(msp, sx, sy + 13.25, 1.6)

    # 中心孔可见轮廓
    for r, gz in center_steps_front:
        sx, sy = gt_to_side(0, gz)
        add_circle(msp, sx, sy, r)

    # ---- 保存 ----
    doc.saveas(str(OUTPUT))
    print(f"理想 DXF 已生成: {OUTPUT}")

    # 分析
    doc2 = ezdxf.readfile(str(OUTPUT))
    msp2 = doc2.modelspace()
    circles = list(msp2.query("CIRCLE"))
    lines = list(msp2.query("LINE"))
    lwpolys = list(msp2.query("LWPOLYLINE"))
    arcs = list(msp2.query("ARC"))
    print(f"实体统计: CIRCLE={len(circles)}, LINE={len(lines)}, "
          f"LWPOLYLINE={len(lwpolys)}, ARC={len(arcs)}")
    print(f"总计: {len(circles)+len(lines)+len(lwpolys)+len(arcs)} 个几何实体")
    print(f"DIMLFAC = {doc2.header.get('$DIMLFAC', 'N/A')}")


if __name__ == "__main__":
    main()
