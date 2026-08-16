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
from OCC.Core.TopAbs import TopAbs_SOLID, TopAbs_IN
from OCC.Core.Bnd import Bnd_Box
from OCC.Core.BRepBndLib import brepbndlib
from OCC.Core.BRepAdaptor import BRepAdaptor_Curve, BRepAdaptor_Surface
from OCC.Core.GeomAbs import (GeomAbs_Line, GeomAbs_Circle,
                              GeomAbs_Cylinder, GeomAbs_Cone,
                              GeomAbs_BSplineCurve)
from OCC.Core.BRepClass3d import BRepClass3d_SolidClassifier
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

def _circle_proj_extrema(c3, r, xv, yv, f, l, d):
    """圆/弧 (圆心 c3, 半径 r, 基向量 xv/yv, 参数范围 [f,l]) 在方向
    d 上的投影极值点对 (pA, pB)（3D）。候选角 = 弧端点 + p'(t)=0 解。"""
    cand = [f, l]
    denom = xv.X() * d.X() + xv.Y() * d.Y() + xv.Z() * d.Z()
    numer = yv.X() * d.X() + yv.Y() * d.Y() + yv.Z() * d.Z()
    if abs(denom) > 1e-12:
        t0 = math.atan2(numer, denom)
        for tt in (t0, t0 + math.pi):
            while tt < f:
                tt += 2 * math.pi
            while tt >= l + 2 * math.pi:
                tt -= 2 * math.pi
            if f <= tt < l:
                cand.append(tt)

    def _pp(t):
        return r * math.cos(t) * denom + r * math.sin(t) * numer

    vals = [(_pp(t), t) for t in cand]
    tmin = min(vals)[1]
    tmax = max(vals)[1]
    pA = gp_Pnt(c3.X() + r * (math.cos(tmin) * xv.X()
                             + math.sin(tmin) * yv.X()),
                c3.Y() + r * (math.cos(tmin) * xv.Y()
                             + math.sin(tmin) * yv.Y()),
                c3.Z() + r * (math.cos(tmin) * xv.Z()
                             + math.sin(tmin) * yv.Z()))
    pB = gp_Pnt(c3.X() + r * (math.cos(tmax) * xv.X()
                             + math.sin(tmax) * yv.X()),
                c3.Y() + r * (math.cos(tmax) * xv.Y()
                             + math.sin(tmax) * yv.Y()),
                c3.Z() + r * (math.cos(tmax) * xv.Z()
                             + math.sin(tmax) * yv.Z()))
    return pA, pB


def _supplement_outline_lines(shape, dz, up, dx):
    """补偿 HLR 丢失的轮廓投影（HLRBRep_Algo 对以下两类系统性丢弃）:

      1. 圆边沿其平面方向投影（edge-on circle → 退化线段）
      2. 锥面/圆柱面的轮廓母线（本模型半角 80° 的法兰锥面全部丢失）

    按几何定义直接计算投影线段, 用实体分类器沿视线方向(-dz)采样做
    遮挡可见性过滤。返回 [(x1, y1, x2, y2), ...] 2D 线段。
    """
    # 实体分类器（可见性测试用）
    classifiers = []
    ex = TopExp_Explorer(shape, TopAbs_SOLID)
    while ex.More():
        c = BRepClass3d_SolidClassifier(ex.Current())
        c.PerformInfinitePoint(1e-9)
        classifiers.append(c)
        ex.Next()

    def _inside(pnt):
        for c in classifiers:
            c.Perform(pnt, 1e-6)
            if c.State() == TopAbs_IN:
                return True
        return False

    def _visible(p3):
        """模型表面点 p3 向观察者方向(-dz)采样, 途中穿入材料 → 被遮挡。"""
        for t in (0.01, 0.05, 0.2, 0.5, 1.0, 2.0, 5.0, 10.0, 20.0, 50.0):
            q = gp_Pnt(p3.X() - t * dz.X(),
                       p3.Y() - t * dz.Y(),
                       p3.Z() - t * dz.Z())
            if _inside(q):
                return False
        return True

    def _prj2(p3):
        return (p3.X() * dx.X() + p3.Y() * dx.Y() + p3.Z() * dx.Z(),
                p3.X() * up.X() + p3.Y() * up.Y() + p3.Z() * up.Z())

    out = []

    # ---- 1. 侧视圆边（圆面法线 ⊥ 视线，edge-on）→ 投影为直径线段 ----
    # 注: 法线 ∥ 视线的圆 (face-on) 投影仍是圆, 由 HLR 负责。
    # v0.6.1: 部分圆弧只投影其参数范围内的极值区间, 不再补整条
    # 直径线（弧片底面部分圆补整直径线会制造假轮廓线, 如法兰
    # 圆角方底面 X[2~12] 假底边 → 外环提取断链）。
    ex = TopExp_Explorer(shape, TopAbs_EDGE)
    while ex.More():
        a = BRepAdaptor_Curve(ex.Current())
        if a.GetType() == GeomAbs_Circle:
            circ = a.Circle()
            n = circ.Axis().Direction()
            if abs(n.Dot(dz)) < 0.001:
                c3 = circ.Location()
                r = circ.Radius()
                # 圆面内、垂直于视线的直径方向
                d = gp_Vec(n.Y() * dz.Z() - n.Z() * dz.Y(),
                           n.Z() * dz.X() - n.X() * dz.Z(),
                           n.X() * dz.Y() - n.Y() * dz.X())
                ln = d.Magnitude()
                if ln > 1e-12:
                    d.Scale(1.0 / ln)
                    # 圆参数化基向量
                    xv = circ.XAxis().Direction()
                    yv = circ.YAxis().Direction()
                    f = a.FirstParameter()
                    l = a.LastParameter()
                    # 投影极值候选角: 弧端点 + p'(t)=0 的解
                    cand = [f, l]
                    denom = xv.X() * d.X() + xv.Y() * d.Y() + xv.Z() * d.Z()
                    numer = yv.X() * d.X() + yv.Y() * d.Y() + yv.Z() * d.Z()
                    if abs(denom) > 1e-12:
                        t0 = math.atan2(numer, denom)
                        for tt in (t0, t0 + math.pi):
                            # 归一到 [f, l)
                            while tt < f:
                                tt += 2 * math.pi
                            while tt >= l + 2 * math.pi:
                                tt -= 2 * math.pi
                            if f <= tt < l:
                                cand.append(tt)
                    # 投影坐标 p(t) = r cos t (xv·d) + r sin t (yv·d)
                    def _pp(t):
                        return r * math.cos(t) * denom + r * math.sin(t) * numer
                    vals = [(_pp(t), t) for t in cand]
                    tmin = min(vals)[1]
                    tmax = max(vals)[1]
                    pA = gp_Pnt(c3.X() + r * (math.cos(tmin) * xv.X()
                                             + math.sin(tmin) * yv.X()),
                                c3.Y() + r * (math.cos(tmin) * xv.Y()
                                             + math.sin(tmin) * yv.Y()),
                                c3.Z() + r * (math.cos(tmin) * xv.Z()
                                             + math.sin(tmin) * yv.Z()))
                    pB = gp_Pnt(c3.X() + r * (math.cos(tmax) * xv.X()
                                             + math.sin(tmax) * yv.X()),
                                c3.Y() + r * (math.cos(tmax) * xv.Y()
                                             + math.sin(tmax) * yv.Y()),
                                c3.Z() + r * (math.cos(tmax) * xv.Z()
                                             + math.sin(tmax) * yv.Z()))
                    # 前点（朝观察者一侧的圆上点）做遮挡测试。
                    # fwd = -dz 在圆平面内的分量（朝观察者, 观察者在
                    # -dz 方向——v0.6.1 修复: 此前用 +dz 分量, 前点
                    # 落在模型背面 → 被自己的主体遮挡判不可见）。
                    fwd = gp_Vec(-dz.X() + n.Dot(dz) * n.X(),
                                 -dz.Y() + n.Dot(dz) * n.Y(),
                                 -dz.Z() + n.Dot(dz) * n.Z())
                    fl = fwd.Magnitude()
                    if fl > 1e-12:
                        fwd.Scale(r / fl)
                        front = gp_Pnt(c3.X() + fwd.X(),
                                       c3.Y() + fwd.Y(),
                                       c3.Z() + fwd.Z())
                        if _visible(front):
                            a2, b2 = _prj2(pA), _prj2(pB)
                            out.append((a2[0], a2[1], b2[0], b2[1]))
        ex.Next()

    # ---- 2. 锥面/圆柱面轮廓母线 ----
    ex = TopExp_Explorer(shape, TopAbs_FACE)
    while ex.More():
        s = BRepAdaptor_Surface(ex.Current())
        st = s.GetType()
        if st in (GeomAbs_Cylinder, GeomAbs_Cone):
            if st == GeomAbs_Cylinder:
                axis = s.Cylinder().Axis().Direction()
                alpha = 0.0
                pos = s.Cylinder().Position()
            else:
                cone = s.Cone()
                axis = cone.Axis().Direction()
                alpha = cone.SemiAngle()
                pos = cone.Position()
            x1v = gp_Vec(pos.XDirection())
            x2v = gp_Vec(pos.YDirection())
            az = axis.Dot(dz)
            A = x1v.Dot(gp_Vec(dz))
            B = x2v.Dot(gp_Vec(dz))
            if abs(math.sin(alpha)) < 1e-9:
                # 圆柱: 轮廓母线在垂直于视线的直径两端
                d = gp_Vec(axis.Y() * dz.Z() - axis.Z() * dz.Y(),
                           axis.Z() * dz.X() - axis.X() * dz.Z(),
                           axis.X() * dz.Y() - axis.Y() * dz.X())
                ln = d.Magnitude()
                if ln < 1e-12:
                    ex.Next()
                    continue
                d.Scale(1.0 / ln)
                th = math.atan2(d.Dot(x2v), d.Dot(x1v))
                thetas = [th, th + math.pi]
            else:
                # 锥面: 解 n·dz = 0（法线 ⊥ 视线）
                L = math.cos(alpha) * az / math.sin(alpha)
                norm = math.hypot(A, B)
                if abs(L) > norm + 1e-9:
                    ex.Next()
                    continue
                base = math.atan2(B, A)
                off = math.acos(max(-1.0, min(1.0, L / norm)))
                thetas = [base + off, base - off]
            u1 = s.FirstUParameter()
            u2 = s.LastUParameter()
            span = u2 - u1
            # 部分面片 (span < 2π): 轮廓母线可能被切除, 面片边界 u1/u2
            # 处也是真实轮廓 (切口边缘), 加入候选。
            cand_thetas = list(thetas)
            if span < 2 * math.pi - 1e-6:
                cand_thetas += [u1, u2]
            for th in cand_thetas:
                # 归一到面片角度范围 [u1, u2)
                t = th
                if span < 2 * math.pi - 1e-6:
                    while t < u1:
                        t += 2 * math.pi
                    while t >= u2:
                        t -= 2 * math.pi
                    if t < u1:
                        continue
                v1 = s.FirstVParameter()
                v2 = s.LastVParameter()
                p1 = s.Value(t, v1)
                p2 = s.Value(t, v2)
                if _visible(p1) or _visible(p2):
                    a2 = _prj2(p1)
                    b2 = _prj2(p2)
                    out.append((a2[0], a2[1], b2[0], b2[1]))
            # v0.6.1: 面片 V 边界圆投影——锥面大端/小端圆边可能无
            # 拓扑边（SW 导出时被合并进相邻面, 第 1 部分按拓扑圆边
            # 遍历会漏 → 外轮廓断链, 如法兰锥面大端圆 r=40 的投影
            # 横线缺失）。edge-on 时由面片参数直接补投影线段。
            if abs(az) < 0.001:
                print(f"  [DBG] V边界圆补线: 面类型={st} az={az:.3f} "
                      f"u1={u1:.2f} u2={u2:.2f} v1={v1:.2f} v2={v2:.2f}")
                axv = gp_Vec(axis.X(), axis.Y(), axis.Z())
                a0v = gp_Vec(pos.Location().X(), pos.Location().Y(),
                             pos.Location().Z())
                for vv in (v1, v2):
                    q1 = s.Value(u1, vv)
                    q2 = s.Value(u2, vv)
                    if q1.Distance(q2) < 1e-9:
                        continue
                    d12 = gp_Vec(q2.X() - q1.X(), q2.Y() - q1.Y(),
                                 q2.Z() - q1.Z())
                    dd = d12.Dot(axv)
                    if abs(dd) < 1e-12:
                        # 弦与轴垂直（轴平行 Z 的锥/柱面）: 圆心 =
                        # q1 在轴上的投影, 半径即到轴的距离。
                        t = (q1.X() - a0v.X()) * axv.X() \
                            + (q1.Y() - a0v.Y()) * axv.Y() \
                            + (q1.Z() - a0v.Z()) * axv.Z()
                    else:
                        # 圆心 c3 = a0 + t·ax, 且 |q1-c3| = |q2-c3|
                        n1 = q1.X() ** 2 + q1.Y() ** 2 + q1.Z() ** 2
                        n2 = q2.X() ** 2 + q2.Y() ** 2 + q2.Z() ** 2
                        t = ((n1 - n2) / 2 - d12.Dot(a0v)) / dd
                    c3 = gp_Pnt(a0v.X() + t * axv.X(),
                                a0v.Y() + t * axv.Y(),
                                a0v.Z() + t * axv.Z())
                    rv = q1.Distance(c3)
                    if rv < 1e-9:
                        continue
                    xv = gp_Dir(q1.X() - c3.X(), q1.Y() - c3.Y(),
                                q1.Z() - c3.Z())
                    yv = gp_Dir(axv.Y() * xv.Z() - axv.Z() * xv.Y(),
                                axv.Z() * xv.X() - axv.X() * xv.Z(),
                                axv.X() * xv.Y() - axv.Y() * xv.X())
                    # 圆面内、垂直于视线的直径方向
                    d = gp_Vec(axis.Y() * dz.Z() - axis.Z() * dz.Y(),
                               axis.Z() * dz.X() - axis.X() * dz.Z(),
                               axis.X() * dz.Y() - axis.Y() * dz.X())
                    ln = d.Magnitude()
                    if ln < 1e-12:
                        continue
                    d.Scale(1.0 / ln)
                    pA, pB = _circle_proj_extrema(c3, rv, xv, yv,
                                                  0.0, u2 - u1, d)
                    # 前点（朝观察者一侧的圆上点）做遮挡测试
                    fwd = gp_Vec(-dz.X() + az * axis.X(),
                                 -dz.Y() + az * axis.Y(),
                                 -dz.Z() + az * axis.Z())
                    fl = fwd.Magnitude()
                    if fl < 1e-12:
                        continue
                    fwd.Scale(rv / fl)
                    front = gp_Pnt(c3.X() + fwd.X(), c3.Y() + fwd.Y(),
                                   c3.Z() + fwd.Z())
                    if _visible(front):
                        a2, b2 = _prj2(pA), _prj2(pB)
                        out.append((a2[0], a2[1], b2[0], b2[1]))
        ex.Next()

    # ---- 3. BSpline 边投影补线（v0.6.3）----
    # HLR 对与相邻面相切的 BSpline 边界边常不输出（法兰叶片
    # 顶/底轮廓边在 top 视图丢失 → 外环断链、叶片角从环中消失）。
    # 把实体 BSpline 边离散投影补入, 可见性由中点遮挡测试决定。
    ex = TopExp_Explorer(shape, TopAbs_EDGE)
    while ex.More():
        a = BRepAdaptor_Curve(ex.Current())
        if a.GetType() == GeomAbs_BSplineCurve:
            t1 = a.FirstParameter()
            t2 = a.LastParameter()
            if t2 > t1 + 1e-9:
                n = max(8, min(64, int((t2 - t1) / 0.3) + 1))
                prev = None
                for i in range(n + 1):
                    t = t1 + (t2 - t1) * i / n
                    p = a.Value(t)
                    if prev is not None:
                        m3 = gp_Pnt((prev.X() + p.X()) / 2,
                                    (prev.Y() + p.Y()) / 2,
                                    (prev.Z() + p.Z()) / 2)
                        if _visible(m3):
                            a2, b2 = _prj2(prev), _prj2(p)
                            out.append((a2[0], a2[1], b2[0], b2[1]))
                    prev = p
        ex.Next()
    return out


def project_shape_to_2d(shape, view_dir, view_up=(0, 0, 1)):
    """HLR 投影 → 结构化边数据。

    Returns:
        {"lines": [(x1,y1,x2,y2), ...],        # 直线段
         "circles": [(cx,cy,r,is_full,angles), ...],  # 圆/弧 (去重后)
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
                        # 圆弧: 记录起点和终点的角度（在投影平面），
                        # 用中点校正为 CCW 顺序（DXF ARC 约定 CCW）
                        ang1 = math.atan2(p1.Y()-cen.Y(), p1.X()-cen.X())
                        ang2 = math.atan2(p2.Y()-cen.Y(), p2.X()-cen.X())
                        pm = adaptor.Value((t1 + t2) / 2)
                        am = math.atan2(pm.Y()-cen.Y(), pm.X()-cen.X())
                        if (am - ang1) % (2*math.pi) > \
                                (ang2 - ang1) % (2*math.pi):
                            ang1, ang2 = ang2, ang1
                        arcs_out.append((cen.X(), cen.Y(), r, ang1, ang2))
                else:
                    # 椭圆/样条等曲线（回转体外轮廓、圆角投影）→ 离散化为折线
                    t1 = adaptor.FirstParameter()
                    t2 = adaptor.LastParameter()
                    if t2 > t1:
                        n = max(8, min(64, int((t2 - t1) / 0.3) + 1))
                        prev = None
                        for i in range(n + 1):
                            t = t1 + (t2 - t1) * i / n
                            p = adaptor.Value(t)
                            if prev is not None:
                                lines_out.append(
                                    (prev.X(), prev.Y(), p.X(), p.Y()))
                            prev = p
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

    # ---- 假轮廓弧过滤（v0.6.3）----
    # HLR 对部分圆柱面（面片 u 范围 < 2π）沿轴向投影时会输出
    # 面片 u 范围之外的假轮廓弧（silhouette），制造实体上不存在
    # 的圆边。如法兰叶片外壁 r=40 面片（u 跨 7.5°）被画成近整圆。
    # 白名单: 实体 face-on 圆边的投影区间——HLR 弧必须完全落在某条
    # 实体圆边的投影区间内才保留。
    def _arc_angle_range(circ, adap):
        """实体圆边 → 投影平面 CCW 角度区间 (e1, e2)。"""
        cen = circ.Location()
        r = circ.Radius()
        xa = circ.XAxis().Direction()
        ya = circ.YAxis().Direction()
        t1 = adap.FirstParameter()
        t2 = adap.LastParameter()

        def _pt(t):
            return (cen.X() + r * (math.cos(t) * xa.X() + math.sin(t) * ya.X()),
                    cen.Y() + r * (math.cos(t) * xa.Y() + math.sin(t) * ya.Y()),
                    cen.Z() + r * (math.cos(t) * xa.Z() + math.sin(t) * ya.Z()))

        def _ang(p):
            u = (p[0] - cen.X()) * dx.X() + (p[1] - cen.Y()) * dx.Y() \
                + (p[2] - cen.Z()) * dx.Z()
            v = (p[0] - cen.X()) * v_up.X() + (p[1] - cen.Y()) * v_up.Y() \
                + (p[2] - cen.Z()) * v_up.Z()
            return math.atan2(v, u) % (2 * math.pi)

        a1, a2 = _ang(_pt(t1)), _ang(_pt(t2))
        am = _ang(_pt((t1 + t2) / 2))
        if (am - a1) % (2 * math.pi) > (a2 - a1) % (2 * math.pi):
            a1, a2 = a2, a1
        return a1, a2

    edge_ranges = defaultdict(list)   # (cx,cy,r) -> [(e1,e2), ...]
    full_edges = set()                # 实体整圆边投影键
    ex = TopExp_Explorer(shape, TopAbs_EDGE)
    while ex.More():
        a = BRepAdaptor_Curve(ex.Current())
        if a.GetType() == GeomAbs_Circle:
            circ = a.Circle()
            n = circ.Axis().Direction()
            if abs(n.Dot(dz)) > 0.999:
                cen = circ.Location()
                u = cen.X() * dx.X() + cen.Y() * dx.Y() + cen.Z() * dx.Z()
                v = cen.X() * v_up.X() + cen.Y() * v_up.Y() \
                    + cen.Z() * v_up.Z()
                key = (round(u, 1), round(v, 1), round(circ.Radius(), 2))
                if a.LastParameter() - a.FirstParameter() >= 2 * math.pi - 0.01:
                    full_edges.add(key)
                else:
                    edge_ranges[key].append(_arc_angle_range(circ, a))
        ex.Next()

    def _is_legit_arc(arc):
        if len(arc) == 4:  # 整圆: 实体上须有整圆边
            return (round(arc[0], 1), round(arc[1], 1),
                    round(arc[2], 2)) in full_edges
        cx, cy, r, a1, a2 = arc
        key = (round(cx, 1), round(cy, 1), round(r, 2))
        span = (a2 - a1) % (2 * math.pi)
        am = (a1 + span / 2) % (2 * math.pi)
        for e1, e2 in edge_ranges.get(key, []):
            espan = (e2 - e1) % (2 * math.pi)
            if span <= espan + 0.05 and \
                    (am - e1) % (2 * math.pi) <= espan + 0.05:
                return True
        return False

    for name, arcs in (("vis", vis_arcs), ("hid", hid_arcs)):
        kept = [a for a in arcs if _is_legit_arc(a)]
        if len(kept) != len(arcs):
            print(f"  [轮廓过滤] {name} 剔除 {len(arcs)-len(kept)} 条假轮廓弧")
        arcs[:] = kept

    # 圆弧去重：同圆心 + 同半径的弧 → 合并；输出 5 元组
    # (cx, cy, r, is_full, angles)——整圆 angles=None。
    def _dedup_arcs(arcs):
        """去重弧段列表，输出 [(cx,cy,r,is_full,angles), ...]。
        angles: 整圆为 None；弧为 [(a1,a2), ...]（2D CCW 区间列表）。"""
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
                result.append((key[0], key[1], key[2], True, None))
                seen.add(key)

        for key, angles in groups.items():
            if key in seen:
                continue
            # 计算总覆盖角度
            total_angle = 0.0
            for a1, a2 in angles:
                total_angle += (a2 - a1) % (2 * math.pi)
            is_full = total_angle > 2*math.pi - 0.1
            result.append((key[0], key[1], key[2], is_full,
                           None if is_full else angles))
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
        "lines": _dedup_lines(vis_lines + _supplement_outline_lines(
            shape, dz, v_up, dx)),
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
    for cx, cy, r, is_full, angles in view_dict["circles"]:
        xs.extend([cx - r, cx + r])
        ys.extend([cy - r, cy + r])
    for x1, y1, x2, y2 in view_dict["hidden_lines"]:
        xs.extend([x1, x2]); ys.extend([y1, y2])
    for cx, cy, r, is_full, angles in view_dict["hidden_circles"]:
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
    # 可见圆/弧（v0.6.3: 部分弧画 ARC 不再画整圆，避免假轮廓放大）
    for cx, cy, r, is_full, angles in view_dict["circles"]:
        if is_full:
            msp.add_circle((cx+ox, cy+oy), r,
                           dxfattribs={"layer": "可见轮廓"})
        else:
            for a1, a2 in angles:
                msp.add_arc((cx+ox, cy+oy), r,
                            math.degrees(a1), math.degrees(a2),
                            dxfattribs={"layer": "可见轮廓"})
    # 隐藏直线
    for x1, y1, x2, y2 in view_dict["hidden_lines"]:
        msp.add_line((x1+ox, y1+oy), (x2+ox, y2+oy),
                     dxfattribs={"layer": "隐藏线"})
    # 隐藏圆/弧
    for cx, cy, r, is_full, angles in view_dict["hidden_circles"]:
        if is_full:
            msp.add_circle((cx+ox, cy+oy), r,
                           dxfattribs={"layer": "隐藏线"})
        else:
            for a1, a2 in angles:
                msp.add_arc((cx+ox, cy+oy), r,
                            math.degrees(a1), math.degrees(a2),
                            dxfattribs={"layer": "隐藏线"})


def _draw_hatch(msp, section_dict, ox, oy, spacing=3.5):
    """在剖面视图中绘制 45° 剖面线（仅在可见轮廓内部）。"""
    # 简化：计算包围盒，在包围盒内绘制 45° 截面线
    xs, ys = [], []
    for x1, y1, x2, y2 in section_dict["lines"]:
        xs.extend([x1, x2]); ys.extend([y1, y2])
    for cx, cy, r, is_full, angles in section_dict["circles"]:
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
    if section_view is not None:
        s_bb = _bbox_all(section_view)
    else:
        s_bb = (0.0, 0.0, 0.0, 0.0)

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
    if section_view is not None:
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
