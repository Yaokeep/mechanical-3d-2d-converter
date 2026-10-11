# -*- coding: utf-8 -*-
"""YZYX 齿箱上盖五视图 HLR 可见轮廓导出（OCC 侧，无基准验收第二件前半）。

对每视图方向做精确 HLR（VCompound + OutLineVCompound），离散成 2D 折线
写 CAD/temp_output/_yz_hlr.json（原始 u,v，未映射——映射在 yz_match.py 消费端做）：
  {"TL": [[[u,v],...], ...], "BL": [...], "TR": [...]}
TL 为 A—A 全剖（保留 y>=0 半，从 -Y 看）；BL 俯视；
TR 为 C—C 复合投影（见下）；TRW 为其反方向备选（评分对照用）。
用法: PYTHONIOENCODING=utf-8 $PY yz_hlr.py [stepfile] [out.json]
总入口见 yz_accept.py（三件套一起跑 + 基线判红）。
"""
import sys
import json
import faulthandler
faulthandler.enable()

from OCC.Core.BRepAlgoAPI import BRepAlgoAPI_Common, BRepAlgoAPI_Fuse
from OCC.Core.BRepAdaptor import BRepAdaptor_Curve
from OCC.Core.BRepPrimAPI import BRepPrimAPI_MakeBox
from OCC.Core.GCPnts import GCPnts_QuasiUniformDeflection
from OCC.Core.HLRAlgo import HLRAlgo_Projector
from OCC.Core.HLRBRep import HLRBRep_Algo, HLRBRep_HLRToShape
from OCC.Core.IFSelect import IFSelect_RetDone
from OCC.Core.STEPControl import STEPControl_Reader
from OCC.Core.TopAbs import TopAbs_EDGE
from OCC.Core.TopoDS import topods
from OCC.Core.TopExp import TopExp_Explorer
from OCC.Core.gp import gp_Ax2, gp_Dir, gp_Pnt


def half_box(s, x0, x1, y0, y1, z0, z1):
    b = BRepPrimAPI_MakeBox(gp_Pnt(x0, y0, z0), gp_Pnt(x1, y1, z1)).Shape()
    op = BRepAlgoAPI_Common(s, b)
    op.Build()
    return op.Shape()


def half_yplus(s):
    return half_box(s, -1000, 1000, 0, 1000, -1000, 1000)


SPLIT_X = -96.5          # C—C 剖切平面（图纸位置）
# 切面 ε：槽底母线（x=−96.5, z=0, y∈±50）与两条样条面在其中近相切交汇，
# 切盒面与该棱线/槽侧切点完全重合 → OCC 布尔静默退化（v10 实测 TR 可见 9 条、
# TRW 0 条；而 v9 同切面时 TR147/TRW68 正常）。0.05mm ≪ 2mm 评分阈值，
# 投影上不可见，不影响任何判据。
SPLIT_EPS = 0.05
SPLIT = SPLIT_X + SPLIT_EPS


def quarter_cut(s):
    """TR 半剖制备：去掉 {x<SPLIT ∩ y<0} 四分之一角 ⇒ 保留 {x≥SPLIT} ∪ {y≥0}。

    从 −X 看：−y 半只剩 x≥SPLIT，视线直抵 x=SPLIT 剖切面 ⇒ 显示剖面；
    +y 半完整 ⇒ 显示外形投影（r110 满弧等）。与图纸"C 向半剖"构型一致。
    """
    b1 = BRepPrimAPI_MakeBox(gp_Pnt(SPLIT, -1000, -1000),
                             gp_Pnt(1000, 1000, 1000)).Shape()
    b2 = BRepPrimAPI_MakeBox(gp_Pnt(-1000, 0, -1000),
                             gp_Pnt(1000, 1000, 1000)).Shape()
    fu = BRepAlgoAPI_Fuse(b1, b2)
    fu.Build()
    op = BRepAlgoAPI_Common(s, fu.Shape())
    op.Build()
    return op.Shape()


def full_cut(s):
    """两侧同剖：只保留 {x≥SPLIT}（C—C 右半补充投影用，见 TR 组装处）。"""
    b = BRepPrimAPI_MakeBox(gp_Pnt(SPLIT, -1000, -1000),
                            gp_Pnt(1000, 1000, 1000)).Shape()
    op = BRepAlgoAPI_Common(s, b)
    op.Build()
    return op.Shape()


def discretize(comp):
    out = []
    if comp is None:
        return out
    ex = TopExp_Explorer(comp, TopAbs_EDGE)
    while ex.More():
        e = topods.Edge(ex.Current())
        try:
            ad = BRepAdaptor_Curve(e)
            d = GCPnts_QuasiUniformDeflection(ad, 0.3)
            if d.IsDone() and d.NbPoints() >= 2:
                out.append([(d.Value(i).X(), d.Value(i).Y(), d.Value(i).Z())
                            for i in range(1, d.NbPoints() + 1)])
        except Exception:
            pass
        ex.Next()
    return out


def project(shp, N, Vx):
    prj = HLRAlgo_Projector(gp_Ax2(gp_Pnt(0, 0, 0), N, Vx))
    hlr = HLRBRep_Algo()
    hlr.Add(shp)
    hlr.Projector(prj)
    hlr.Update()
    hlr.Hide()
    hs = HLRBRep_HLRToShape(hlr)
    return discretize(hs.VCompound()) + discretize(hs.OutLineVCompound())


def run_hlr(src: str, dst: str, verbose: bool = True) -> dict:
    """读 STEP → 五视图 HLR 折线 → 写 JSON。返回 res dict。"""
    rd = STEPControl_Reader()
    if rd.ReadFile(src) != IFSelect_RetDone:
        raise RuntimeError("STEP 读取失败")
    rd.TransferRoots()
    shape = rd.OneShape()

    VIEWS = [
        ("TL", half_yplus(shape), gp_Dir(0, -1, 0), gp_Dir(1, 0, 0)),
        ("BL", shape, gp_Dir(0, 0, 1), gp_Dir(1, 0, 0)),
        # TRW = 反方向备选（保留西半、从 +X 看），仅用于评分对照。
        ("TRW", half_box(shape, -1000, SPLIT, -1000, 1000, -1000, 1000),
         gp_Dir(1, 0, 0), gp_Dir(0, 1, 0)),
        # DR = 右下大拱视图：整件从东侧 +X 看（u=y, v=z）。判据：RB r107.5 与
        # R5 填角弧从东可见（西看会被 disc r145 遮死）；塔端 r172.5 为相切棱不画
        # （图纸同样无 r172.5 弧）。
        ("DR", shape, gp_Dir(1, 0, 0), gp_Dir(0, 1, 0)),
    ]
    res = {}
    for name, shp, N, Vx in VIEWS:
        res[name] = project(shp, N, Vx)

    # TR = C—C 复合投影（从 −X 看）——图纸右半是"外形视图"却画出了斜肩
    # (60,122)->(75,125) 与右裙脚圆角弧，而这两个特征单一投影无论如何都看不见
    # （被西端面 spigot r110 / disc r145 / body 挡住；也不可能存在一刀两全：
    #  保留 disc 则斜肩被挡，去掉 disc 则 r145 满弧消失）：
    #   ① quarter_cut（去 {x<−96.5 ∩ y<0}）：−y 半剖面 + +y 半完整外形
    #      → 给左侧剖面内容与右半外形弧（r110 / r145 等）；
    #   ② full_cut 只取 u≥0：+y 半也剖到 x=−96.5 → 给斜肩、右裙脚圆角、
    #      内壁 (60,·) 等"只有剖切才可见"的右半内容（图纸右半正是把它们画出）。
    TR_N, TR_VX = gp_Dir(-1, 0, 0), gp_Dir(0, 1, 0)
    tr2 = [poly for poly in project(full_cut(shape), TR_N, TR_VX)
           if min(p[0] for p in poly) >= -0.5]
    res["TR"] = project(quarter_cut(shape), TR_N, TR_VX) + tr2

    for name in ("TL", "BL", "TR", "TRW", "DR"):
        vis = res[name]
        us = [p[0] for poly in vis for p in poly]
        vs = [p[1] for poly in vis for p in poly]
        if verbose:
            if us:
                print(f"[{name}] 可见 {len(vis)} 条  u∈[{min(us):.1f},{max(us):.1f}]  "
                      f"v∈[{min(vs):.1f},{max(vs):.1f}]")
            else:
                print(f"[{name}] 可见 0 条 !!")
    with open(dst, "w", encoding="utf-8") as f:
        json.dump(res, f)
    if verbose:
        print(f"-> {dst}")
    return res


def main() -> int:
    src = sys.argv[1] if len(sys.argv) > 1 else "CAD/temp_output/_yz_3d.step"
    dst = sys.argv[2] if len(sys.argv) > 2 else "CAD/temp_output/_yz_hlr.json"
    run_hlr(src, dst)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
