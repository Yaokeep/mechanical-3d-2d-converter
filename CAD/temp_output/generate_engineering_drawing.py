#!/usr/bin/env python
"""从电机 3D 模型生成标准工程图 — 三视图 + 剖面图.

使用 PythonOCC HLR 隐藏线消除投影，
生成符合中国国标（第一角投影法）的 DXF 工程图。

v4 最终版:
  - 正确检测圆/弧并去重（同圆心同半径 → 整圆）
  - 直线段直接输出 LINE
  - 弧段离散化为折线
  - 剖面图 + 剖面线
"""

import math
import sys
from pathlib import Path
from collections import defaultdict

PROJECT_ROOT = Path(__file__).parent.parent.parent
SRC_PATH = PROJECT_ROOT / "src"
for p in [str(PROJECT_ROOT), str(SRC_PATH)]:
    if p not in sys.path:
        sys.path.insert(0, p)

import ezdxf
from ezdxf.enums import TextEntityAlignment

from OCC.Core.gp import (
    gp_Pnt, gp_Dir, gp_Ax1, gp_Ax2, gp_Ax3, gp_Vec,
    gp_Circ, gp_Trsf, gp_XYZ, gp_Pln,
)
from OCC.Core.BRepBuilderAPI import (
    BRepBuilderAPI_MakeEdge, BRepBuilderAPI_MakeWire,
    BRepBuilderAPI_MakeFace, BRepBuilderAPI_Transform,
)
from OCC.Core.BRepPrimAPI import (
    BRepPrimAPI_MakePrism, BRepPrimAPI_MakeRevol,
    BRepPrimAPI_MakeCylinder, BRepPrimAPI_MakeBox,
)
from OCC.Core.BRepAlgoAPI import (
    BRepAlgoAPI_Fuse, BRepAlgoAPI_Cut, BRepAlgoAPI_Common,
)
from OCC.Core.TopoDS import TopoDS_Shape
from OCC.Core.STEPControl import STEPControl_Writer, STEPControl_AsIs
from OCC.Core.IFSelect import IFSelect_RetDone
from OCC.Core.TopExp import TopExp_Explorer
from OCC.Core.TopAbs import TopAbs_EDGE, TopAbs_WIRE, TopAbs_FACE
from OCC.Core.Bnd import Bnd_Box
from OCC.Core.BRepBndLib import brepbndlib
from OCC.Core.BRepAdaptor import BRepAdaptor_Curve
from OCC.Core.GeomAbs import GeomAbs_Line, GeomAbs_Circle
from OCC.Core.HLRBRep import HLRBRep_Algo, HLRBRep_HLRToShape
from OCC.Core.HLRAlgo import HLRAlgo_Projector


OUTPUT_DIR = Path(__file__).parent
STEP_OUTPUT = OUTPUT_DIR / "motor_3d_model.step"
DXF_OUTPUT = OUTPUT_DIR / "motor_engineering.dxf"


# ============================================================
# 1. 电机 3D 模型
# ============================================================

def _fuse(a, b):
    f = BRepAlgoAPI_Fuse(a, b); f.Build()
    return f.Shape() if f.IsDone() else a

def _cut(a, b):
    f = BRepAlgoAPI_Cut(a, b); f.Build()
    return f.Shape() if f.IsDone() else a

def _cyl(cx, cy, r, h, z0=0):
    return BRepPrimAPI_MakeCylinder(
        gp_Ax2(gp_Pnt(cx, cy, z0), gp_Dir(0, 0, 1)), r, h).Shape()

def _box(cx, cy, cz, wx, wy, hz):
    return BRepPrimAPI_MakeBox(
        gp_Pnt(cx - wx/2, cy - wy/2, cz), wx, wy, hz).Shape()


def build_motor_model():
    """构建电机 3D 模型: 80x80x96.9mm。"""
    print("=" * 60)
    print("构建电机 3D 模型 (80x80x96.9mm)")
    print("=" * 60)

    print("  [1/4] 底座 + 凸台...")
    base = _box(0, 0, -26.5, 80, 80, 26.5)
    body = _box(0, 0, 0, 60, 60, 70.4)
    main = _fuse(base, body)

    print("  [2/4] 中心阶梯孔...")
    bore = None; z = -26.5
    for r, h in [(40, 5), (30, 8), (25, 10), (21, 6), (16, 12), (8.5, 55.9)]:
        c = _cyl(0, 0, r, h, z)
        bore = c if bore is None else _fuse(bore, c)
        z += h

    print("  [3/4] 安装孔 R=1.6 + 沉头孔 R=2.7...")
    small = None
    for gx in [-24.7, 24.7]:
        for gy in [-24.7, 24.7]:
            h1 = _cyl(gx, gy, 1.6, 30, -28)
            h2 = _cyl(gx, gy, 2.7, 8, -26.5)
            h3 = _cyl(gx, gy, 1.6, 22, -18.5)
            one = _fuse(_fuse(h1, h2), h3)
            small = one if small is None else _fuse(small, one)

    print("  [4/4] 布尔减...")
    motor = _cut(main, _fuse(bore, small))

    w = STEPControl_Writer()
    w.Transfer(motor, STEPControl_AsIs)
    w.Write(str(STEP_OUTPUT))
    print(f"  STEP: {STEP_OUTPUT}")

    bb = Bnd_Box(); brepbndlib.Add(motor, bb)
    x1, y1, z1, x2, y2, z2 = bb.Get()
    print(f"  尺寸: X={x2-x1:.1f} Y={y2-y1:.1f} Z={z2-z1:.1f} mm")
    return motor


# ============================================================
# 2. HLR 投影
# ============================================================

def project_shape_to_2d(shape, view_dir, view_up=(0, 0, 1)):
    """HLR 投影 → 结构化边数据。

    Returns:
        {"lines": [(x1,y1,x2,y2), ...],        # 直线段
         "circles": [(cx,cy,r,is_full), ...],   # 圆/弧 (去重后)
         "hidden_lines": [...],
         "hidden_circles": [...]}
    """
    origin = gp_Pnt(0, 0, 0)
    dz = gp_Dir(*view_dir)
    v_up = gp_Dir(*view_up)
    dx = gp_Dir(gp_Vec(
        v_up.Y()*dz.Z() - v_up.Z()*dz.Y(),
        v_up.Z()*dz.X() - v_up.X()*dz.Z(),
        v_up.X()*dz.Y() - v_up.Y()*dz.X(),
    ))
    proj = HLRAlgo_Projector(gp_Ax2(origin, dz, dx))

    hlr = HLRBRep_Algo()
    hlr.Add(shape, 1)
    hlr.Projector(proj)
    hlr.Update()
    hlr.Hide()
    shapes = HLRBRep_HLRToShape(hlr)

    # 原始数据收集
    vis_lines = []
    vis_arcs = []    # [(cx,cy,r,start_angle,end_angle), ...]
    hid_lines = []
    hid_arcs = []

    def _safe(method):
        try:
            obj = getattr(shapes, method)()
            if obj is None: return None
            if hasattr(obj, "IsNull") and obj.IsNull(): return None
            return obj
        except Exception: return None

    def _extract(compound, lines_out, arcs_out):
        if compound is None: return
        try:
            if hasattr(compound, "IsNull") and compound.IsNull(): return
        except Exception: return

        exp = TopExp_Explorer()
        exp.Init(compound, TopAbs_EDGE)
        while exp.More():
            edge = exp.Current()
            try:
                adaptor = BRepAdaptor_Curve(edge)
                ct = adaptor.GetType()
                p1 = adaptor.Value(adaptor.FirstParameter())
                p2 = adaptor.Value(adaptor.LastParameter())

                if ct == GeomAbs_Line:
                    lines_out.append((p1.X(), p1.Y(), p2.X(), p2.Y()))
                elif ct == GeomAbs_Circle:
                    circ = adaptor.Circle()
                    cen = circ.Location()
                    r = circ.Radius()
                    t1 = adaptor.FirstParameter()
                    t2 = adaptor.LastParameter()
                    arc_len = abs(t2 - t1)
                    if arc_len > 2*math.pi - 0.01:
                        arcs_out.append((cen.X(), cen.Y(), r, -1.0))  # -1 = 整圆
                    else:
                        # 圆弧: 记录起点和终点的角度（在投影平面）
                        ang1 = math.atan2(p1.Y()-cen.Y(), p1.X()-cen.X())
                        ang2 = math.atan2(p2.Y()-cen.Y(), p2.X()-cen.X())
                        arcs_out.append((cen.X(), cen.Y(), r, ang1, ang2))
            except Exception:
                pass
            exp.Next()

    for method, (vl, va, hl, ha) in [
        ("VCompound",        (vis_lines, vis_arcs, None, None)),
        ("OutLineVCompound", (vis_lines, vis_arcs, None, None)),
        ("Rg1LineVCompound", (vis_lines, vis_arcs, None, None)),
        ("HCompound",        (None, None, hid_lines, hid_arcs)),
        ("OutLineHCompound", (None, None, hid_lines, hid_arcs)),
    ]:
        comp = _safe(method)
        if vl is not None:
            _extract(comp, vl, va)
        else:
            _extract(comp, hl, ha)

    # 圆弧去重：同圆心 + 同半径的弧 → 合并为整圆
    def _dedup_arcs(arcs):
        """去重弧段列表，输出 [(cx,cy,r,is_full), ...]。

        规则：同(cx,cy,r)的多个弧段 → 1 个 CIRCLE。
        """
        groups = defaultdict(list)
        full_circles = []
        for a in arcs:
            if len(a) == 4 and a[3] == -1.0:
                # 整圆
                cx, cy, r, _ = a
                key = (round(cx, 2), round(cy, 2), round(r, 3))
                full_circles.append(key)
            elif len(a) == 5:
                cx, cy, r, ang1, ang2 = a
                key = (round(cx, 2), round(cy, 2), round(r, 3))
                groups[key].append((ang1, ang2))

        result = []
        seen = set()

        for key in full_circles:
            if key not in seen:
                result.append((key[0], key[1], key[2], True))
                seen.add(key)

        for key, angles in groups.items():
            if key in seen:
                continue
            # 计算总覆盖角度
            total_angle = 0.0
            for a1, a2 in angles:
                span = a2 - a1
                if span < 0: span += 2*math.pi
                total_angle += span
            is_full = total_angle > 2*math.pi - 0.1
            result.append((key[0], key[1], key[2], is_full))
            seen.add(key)

        return result

    vis_circles = _dedup_arcs(vis_arcs)
    hid_circles = _dedup_arcs(hid_arcs)

    # 直线去重（去除完全相同的线段）
    def _dedup_lines(lines):
        seen = set()
        result = []
        for x1, y1, x2, y2 in lines:
            # 规范化方向
            if (x1, y1) > (x2, y2):
                x1, y1, x2, y2 = x2, y2, x1, y1
            key = (round(x1, 1), round(y1, 1), round(x2, 1), round(y2, 1))
            if key not in seen:
                seen.add(key)
                result.append((x1, y1, x2, y2))
        return result

    return {
        "lines": _dedup_lines(vis_lines),
        "circles": vis_circles,
        "hidden_lines": _dedup_lines(hid_lines),
        "hidden_circles": hid_circles,
    }


def project_all_views(shape):
    """三视图（第一角投影法）。"""
    views = {}
    print("\n" + "=" * 60)
    print("HLR 投影 — 三视图")
    print("=" * 60)
    views["front"] = project_shape_to_2d(shape, (0, -1, 0), (0, 0, 1))
    views["top"]   = project_shape_to_2d(shape, (0, 0, -1), (0, 1, 0))
    views["right"] = project_shape_to_2d(shape, (1, 0, 0), (0, 0, 1))
    for k, v in views.items():
        print(f"  {k}: {len(v['lines'])}线 {len(v['circles'])}圆, "
              f"隐藏 {len(v['hidden_lines'])}线 {len(v['hidden_circles'])}圆")
    return views


def generate_section_view(shape):
    """全剖主视图 — X=0。"""
    print("\n  [剖面] 全剖主视图 (X=0)...")
    big = 300
    half = _box(big/2, 0, -big, big, big*2, big*2)
    c = BRepAlgoAPI_Common(shape, half); c.Build()
    hs = c.Shape() if c.IsDone() else shape
    r = project_shape_to_2d(hs, (0, -1, 0), (0, 0, 1))
    print(f"  剖面: {len(r['lines'])}线 {len(r['circles'])}圆, "
          f"隐藏 {len(r['hidden_lines'])}线")
    return r


# ============================================================
# 3. 工程图布局和 DXF 输出
# ============================================================

def _bbox_all(view_dict):
    """计算所有边（线+圆心）的 2D 包围盒。"""
    xs, ys = [], []
    for x1, y1, x2, y2 in view_dict["lines"]:
        xs.extend([x1, x2]); ys.extend([y1, y2])
    for cx, cy, r, is_full in view_dict["circles"]:
        xs.extend([cx - r, cx + r])
        ys.extend([cy - r, cy + r])
    for x1, y1, x2, y2 in view_dict["hidden_lines"]:
        xs.extend([x1, x2]); ys.extend([y1, y2])
    for cx, cy, r, is_full in view_dict["hidden_circles"]:
        xs.extend([cx - r, cx + r])
        ys.extend([cy - r, cy + r])
    if not xs: return 0, 0, 100, 100
    m = 2
    return min(xs)-m, min(ys)-m, max(xs)+m, max(ys)+m


def _draw_view_elements(msp, view_dict, ox, oy):
    """绘制一个视图的所有元素。"""
    # 可见直线
    for x1, y1, x2, y2 in view_dict["lines"]:
        msp.add_line((x1+ox, y1+oy), (x2+ox, y2+oy),
                     dxfattribs={"layer": "可见轮廓"})
    # 可见圆
    for cx, cy, r, is_full in view_dict["circles"]:
        msp.add_circle((cx+ox, cy+oy), r, dxfattribs={"layer": "可见轮廓"})
    # 隐藏直线
    for x1, y1, x2, y2 in view_dict["hidden_lines"]:
        msp.add_line((x1+ox, y1+oy), (x2+ox, y2+oy),
                     dxfattribs={"layer": "隐藏线"})
    # 隐藏圆
    for cx, cy, r, is_full in view_dict["hidden_circles"]:
        msp.add_circle((cx+ox, cy+oy), r, dxfattribs={"layer": "隐藏线"})


def _draw_hatch(msp, section_dict, ox, oy, spacing=3.5):
    """在剖面视图中绘制 45° 剖面线（仅在可见轮廓内部）。"""
    # 简化：计算包围盒，在包围盒内绘制 45° 截面线
    xs, ys = [], []
    for x1, y1, x2, y2 in section_dict["lines"]:
        xs.extend([x1, x2]); ys.extend([y1, y2])
    for cx, cy, r, is_full in section_dict["circles"]:
        xs.extend([cx - r, cx + r]); ys.extend([cy - r, cy + r])
    if not xs: return
    x1, y1, x2, y2 = min(xs), min(ys), max(xs), max(ys)

    diag = math.hypot(x2-x1, y2-y1)
    n = int(diag / spacing) + 2
    for i in range(-n, n+1):
        off = i * spacing
        segs = []
        # 与 x=x1 交点: y = x1 + off
        py = x1 + off
        if y1 <= py <= y2: segs.append((x1, py))
        # 与 x=x2: y = x2 + off
        py = x2 + off
        if y1 <= py <= y2: segs.append((x2, py))
        # 与 y=y1: x = y1 - off
        px = y1 - off
        if x1 <= px <= x2: segs.append((px, y1))
        # 与 y=y2: x = y2 - off
        px = y2 - off
        if x1 <= px <= x2: segs.append((px, y2))
        if len(segs) >= 2:
            segs.sort()
            msp.add_line((segs[0][0]+ox, segs[0][1]+oy),
                         (segs[-1][0]+ox, segs[-1][1]+oy),
                         dxfattribs={"layer": "剖面线"})


def create_dxf_drawing(views, section_view, output_path):
    """生成 DXF 工程图。"""
    print("\n" + "=" * 60)
    print("生成 DXF 工程图")
    print("=" * 60)

    doc = ezdxf.new()

    # 图层
    for name, color, ltype in [
        ("可见轮廓", 7, "CONTINUOUS"), ("隐藏线", 5, "HIDDEN"),
        ("中心线", 1, "CENTER"), ("剖面线", 3, "CONTINUOUS"),
        ("标注", 2, "CONTINUOUS"), ("图框", 7, "CONTINUOUS"),
        ("文字", 7, "CONTINUOUS"),
    ]:
        ly = doc.layers.add(name, color=color)
        if ltype != "CONTINUOUS":
            try: ly.set_linetype(ltype)
            except Exception: pass

    doc.header["$DIMLFAC"] = 1.0
    doc.header["$MEASUREMENT"] = 1
    doc.header["$INSUNITS"] = 4
    msp = doc.modelspace()

    # 视图包围盒
    f_bb = _bbox_all(views["front"])
    t_bb = _bbox_all(views["top"])
    r_bb = _bbox_all(views["right"])
    s_bb = _bbox_all(section_view)

    fw, fh = f_bb[2]-f_bb[0], f_bb[3]-f_bb[1]
    tw, th = t_bb[2]-t_bb[0], t_bb[3]-t_bb[1]
    rw, rh = r_bb[2]-r_bb[0], r_bb[3]-r_bb[1]
    sw, sh = s_bb[2]-s_bb[0], s_bb[3]-s_bb[1]

    # 布局
    G = 45.0
    FX, FY = 0.0, 0.0
    TX = FX + (fw - tw) / 2; TY = FY - th - G
    RX = FX + fw + G;       RY = FY + (fh - rh) / 2
    SX = RX + rw + G;       SY = FY + (fh - sh) / 2

    TW = max(FX+fw+G+rw+G+sw, TX+tw) + 25
    TH = max(FY+fh, RY+rh, SY+sh) + 25

    # 图框
    M = 10
    x0, y0 = -M, -TH-65
    msp.add_lwpolyline(
        [(x0,y0),(TW+M,y0),(TW+M,TH+M+30),(x0,TH+M+30)],
        close=True, dxfattribs={"layer": "图框"})
    msp.add_lwpolyline(
        [(x0+M,y0+M),(TW,y0+M),(TW,TH+30),(x0+M,TH+30)],
        close=True, dxfattribs={"layer": "图框"})

    # 标题栏
    tb_y = y0 + M; tb_h = 20
    msp.add_lwpolyline(
        [(x0+M,tb_y),(TW,tb_y),(TW,tb_y+tb_h),(x0+M,tb_y+tb_h)],
        close=True, dxfattribs={"layer": "图框"})
    for i in range(1, 6):
        cx = x0+M + i*(TW-M)/6
        msp.add_line((cx,tb_y),(cx,tb_y+tb_h), dxfattribs={"layer": "图框"})
    for t, col in [("电机模型",1),("三视图+剖面图",2),("比例 1:1",3),
                   ("单位 mm",4),("PythonOCC HLR 投影",5),("",6)]:
        tx = x0+M + (col-0.5)*(TW-M)/6
        ty = tb_y + tb_h/2
        msp.add_text(t, dxfattribs={"layer":"文字","height":2.5}).set_placement(
            (tx,ty), align=TextEntityAlignment.CENTER)

    # --- 绘制视图 ---
    def _off(bb, vx, vy): return vx-bb[0], vy-bb[1]

    # 主视图
    ox, oy = _off(f_bb, FX, FY)
    print(f"  主视图: {fw:.0f}x{fh:.0f} @ (0,0)")
    _draw_view_elements(msp, views["front"], ox, oy)
    msp.add_text("主视图", dxfattribs={"layer":"文字","height":4}).set_placement(
        (FX+fw/2, FY-8), align=TextEntityAlignment.CENTER)

    # 俯视图
    ox, oy = _off(t_bb, TX, TY)
    print(f"  俯视图: {tw:.0f}x{th:.0f} @ ({TX:.0f},{TY:.0f})")
    _draw_view_elements(msp, views["top"], ox, oy)
    msp.add_text("俯视图", dxfattribs={"layer":"文字","height":4}).set_placement(
        (TX+tw/2, TY-8), align=TextEntityAlignment.CENTER)

    # 右视图
    ox, oy = _off(r_bb, RX, RY)
    print(f"  右视图: {rw:.0f}x{rh:.0f} @ ({RX:.0f},{RY:.0f})")
    _draw_view_elements(msp, views["right"], ox, oy)
    msp.add_text("右视图", dxfattribs={"layer":"文字","height":4}).set_placement(
        (RX+rw/2, RY-8), align=TextEntityAlignment.CENTER)

    # 剖面图
    ox, oy = _off(s_bb, SX, SY)
    print(f"  A-A 剖面: {sw:.0f}x{sh:.0f} @ ({SX:.0f},{SY:.0f})")
    _draw_view_elements(msp, section_view, ox, oy)
    _draw_hatch(msp, section_view, ox, oy, spacing=3.0)
    msp.add_text("A-A", dxfattribs={"layer":"文字","height":4}).set_placement(
        (SX+sw/2, SY-8), align=TextEntityAlignment.CENTER)

    # 剖切符号
    sym_y1, sym_y2 = FY-3, FY+fh+3
    sym_x = FX + fw/2
    msp.add_line((sym_x,sym_y1),(sym_x,sym_y2), dxfattribs={"layer":"中心线"})
    for sx, sy in [(sym_x,sym_y1),(sym_x,sym_y2)]:
        msp.add_line((sx,sy),(sx-4,sy-4), dxfattribs={"layer":"剖面线"})
        msp.add_line((sx,sy),(sx+4,sy-4), dxfattribs={"layer":"剖面线"})
    msp.add_text("A", dxfattribs={"layer":"文字","height":4}).set_placement(
        (sym_x+6, sym_y2), align=TextEntityAlignment.LEFT)

    # 尺寸标注
    do = 10; dh = 3.0
    # 正视图宽
    msp.add_line((FX,FY-do),(FX+fw,FY-do), dxfattribs={"layer":"标注"})
    msp.add_text(f"{fw:.0f}", dxfattribs={"layer":"标注","height":dh}).set_placement(
        (FX+fw/2, FY-do+2), align=TextEntityAlignment.CENTER)
    # 正视图高
    msp.add_line((FX+fw+do,FY),(FX+fw+do,FY+fh), dxfattribs={"layer":"标注"})
    msp.add_text(f"{fh:.0f}", dxfattribs={"layer":"标注","height":dh}).set_placement(
        (FX+fw+do+4, FY+fh/2), align=TextEntityAlignment.MIDDLE_LEFT)
    # 俯视图深
    msp.add_line((TX+tw+do,TY),(TX+tw+do,TY+th), dxfattribs={"layer":"标注"})
    msp.add_text(f"{th:.0f}", dxfattribs={"layer":"标注","height":dh}).set_placement(
        (TX+tw+do+4, TY+th/2), align=TextEntityAlignment.MIDDLE_LEFT)

    print(f"  标注: {fw:.0f}x{fh:.0f} / {tw:.0f}x{th:.0f} / {rw:.0f}x{rh:.0f}")

    doc.saveas(str(output_path))
    print(f"\n  DXF: {output_path}")


# ============================================================
# main
# ============================================================

def main():
    print("=" * 60)
    print("电机 3D 模型 → 标准工程图 (三视图 + 剖面图)")
    print("PythonOCC HLR 隐藏线消除 + 第一角投影法")
    print("=" * 60)

    motor = build_motor_model()
    views = project_all_views(motor)
    section = generate_section_view(motor)
    create_dxf_drawing(views, section, DXF_OUTPUT)

    print("\n完成!")
    print(f"  3D 模型: {STEP_OUTPUT}")
    print(f"  工程图:  {DXF_OUTPUT}")


if __name__ == "__main__":
    main()
