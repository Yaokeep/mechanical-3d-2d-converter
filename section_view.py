#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""剖面图生成 — 半空间裁剪 + 真实截面 HATCH。

与 `generate_engineering_drawing.generate_section_view` 的区别（后者是
motor 专用的一次性实现，本模块为通用）：

  1. 剖切面**参数化**（任意原点/法向），不再硬编码 X=0
  2. 剖面线取**真实截面 face 的外环 + 内环**，输出 DXF HATCH 实体——
     旧实现按视图包围盒画 45° 直线，剖面线会溢出零件轮廓、盖住孔洞，
     在有内腔的零件上完全不可读
  3. 多实体 STEP 先 Fuse：重叠实体的内部边界会被 HLR 当作真实边投影
     （bracket angker 三实体重叠 83,561mm³ → front 视图 700 条线）

2D 映射与 `project_shape_to_2d` 的 HLRAlgo_Projector 保持一致：
取 gp_Ax2(原点, dz=view_dir, dx=up×view_dir)，点的 2D 坐标为
(P·dx, P·dy)，其中 dy = dz×dx。front(沿-Y,up=Z) → (X, Z)；
side(沿+X,up=Z) → (Y, Z)，与 model_to_drawing 的视图约定吻合。
"""

import math
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent
CAD_TEMP = PROJECT_ROOT / "CAD" / "temp_output"
for _p in [str(PROJECT_ROOT), str(CAD_TEMP)]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

from OCC.Core.BRep import BRep_Tool  # noqa: E402
from OCC.Core.BRepAdaptor import BRepAdaptor_Curve, BRepAdaptor_Surface  # noqa: E402
from OCC.Core.BRepAlgoAPI import BRepAlgoAPI_Common, BRepAlgoAPI_Fuse  # noqa: E402
from OCC.Core.BRepBndLib import brepbndlib  # noqa: E402
from OCC.Core.BRepGProp import brepgprop  # noqa: E402
from OCC.Core.BRepPrimAPI import BRepPrimAPI_MakeBox  # noqa: E402
from OCC.Core.BRepTools import breptools, BRepTools_WireExplorer  # noqa: E402
from OCC.Core.Bnd import Bnd_Box  # noqa: E402
from OCC.Core.GCPnts import GCPnts_QuasiUniformDeflection  # noqa: E402
from OCC.Core.GeomAbs import GeomAbs_Cylinder, GeomAbs_Plane  # noqa: E402
from OCC.Core.GProp import GProp_GProps  # noqa: E402
from OCC.Core.gp import gp_Dir, gp_Pnt, gp_Vec  # noqa: E402
from OCC.Core.TopAbs import (  # noqa: E402
    TopAbs_FACE, TopAbs_REVERSED, TopAbs_SOLID, TopAbs_WIRE,
)
from OCC.Core.TopExp import TopExp_Explorer  # noqa: E402
from OCC.Core.TopoDS import topods  # noqa: E402

# 截面 face 判定容差（mm）——面上采样点到剖切面的距离
_ON_PLANE_TOL = 1e-4
# 轮廓离散弦高容差（mm）：0.05 在 R25 圆上约 2.6° 一段，肉眼已是圆
_DEFLECTION = 0.05


# ============================================================
# 1. 实体准备
# ============================================================

def fuse_solids(shape, verbose=True):
    """多实体 compound → 单实体。返回 (fused, info)。

    STEP 常把一个零件导出成多个重叠实体（bracket angker 为 3 个，
    重叠 83,561mm³）。不融合直接 HLR，重叠体的**内部边界会被当成
    真实轮廓边**投影出来，图纸上出现大量并不存在的线；同时体积统计
    会重复计数。

    注意 compound 布尔的静默部分失败（CLAUDE.md v0.6.14 根因）：
    必须逐实体 Fuse，不能把 compound 整体丢给布尔运算。
    """
    sols = []
    ex = TopExp_Explorer(shape, TopAbs_SOLID)
    while ex.More():
        sols.append(topods.Solid(ex.Current()))
        ex.Next()

    raw_vol = _volume(shape)
    if len(sols) <= 1:
        return shape, {"n_before": len(sols), "n_after": len(sols),
                       "vol": raw_vol, "overlap": 0.0}

    fused = sols[0]
    for s in sols[1:]:
        op = BRepAlgoAPI_Fuse(fused, s)
        if not op.IsDone():
            if verbose:
                print("  [WARN] Fuse 失败，退回原始 compound")
            return shape, {"n_before": len(sols), "n_after": len(sols),
                           "vol": raw_vol, "overlap": 0.0}
        fused = op.Shape()

    # 注：这里**不要**调 ShapeUpgrade_UnifySameDomain。融合结果本身很干净
    # （81 面 → 77 面，无碎片化），而 Build() 在该形状上会让 OCC 段错误
    # （exit 139，实测 bracket angker）。v0.6.4 用它清理的是布尔**差**产生
    # 的共面碎片（1734 面），与此处场景不同。
    n_after = _count(fused, TopAbs_SOLID)
    vol = _volume(fused)
    info = {"n_before": len(sols), "n_after": n_after,
            "vol": vol, "overlap": raw_vol - vol}
    if verbose:
        print(f"  [融合] {len(sols)} 实体 → {n_after}，"
              f"体积 {raw_vol:,.1f} → {vol:,.1f}"
              f"（重叠 {info['overlap']:,.1f}）")
    return fused, info


def _volume(shape):
    p = GProp_GProps()
    brepgprop.VolumeProperties(shape, p)
    return p.Mass()


def _count(shape, kind):
    n = 0
    ex = TopExp_Explorer(shape, kind)
    while ex.More():
        n += 1
        ex.Next()
    return n


def bbox_of(shape):
    bb = Bnd_Box()
    brepbndlib.Add(shape, bb)
    return bb.Get()          # (xmin, ymin, zmin, xmax, ymax, zmax)


# ============================================================
# 2. 结构分析 — 自动推荐剖切位置
# ============================================================

def analyze_structure(shape, verbose=True):
    """识别内部特征，返回结构描述 + 推荐剖切面。

    判据：
      - 圆柱面按 (轴向绝对值, 半径) 聚类 → 孔/轴candidates，
        轴向决定该特征在哪个视图里是"圆"、在哪个视图里需要剖开
      - 掏空度 = 体积/包围盒体积，越低说明内部越空、越需要剖面
      - 对称面：包围盒在某轴上关于中位面对称且有孔轴穿过 → 优先全剖
    """
    x1, y1, z1, x2, y2, z2 = bbox_of(shape)
    vol = _volume(shape)
    bv = (x2 - x1) * (y2 - y1) * (z2 - z1)
    fill = vol / bv if bv > 0 else 1.0

    cyls = []
    ex = TopExp_Explorer(shape, TopAbs_FACE)
    while ex.More():
        f = topods.Face(ex.Current())
        s = BRepAdaptor_Surface(f)
        if s.GetType() == GeomAbs_Cylinder:
            c = s.Cylinder()
            ax, lo = c.Axis().Direction(), c.Axis().Location()
            fp = GProp_GProps()
            brepgprop.SurfaceProperties(f, fp)
            cyls.append({
                "r": c.Radius(),
                "axis": (abs(round(ax.X(), 3)), abs(round(ax.Y(), 3)),
                         abs(round(ax.Z(), 3))),
                "loc": (lo.X(), lo.Y(), lo.Z()),
                "area": fp.Mass(),
            })
        ex.Next()

    groups = {}
    for c in cyls:
        k = (c["axis"], round(c["r"], 2))
        g = groups.setdefault(k, {"area": 0.0, "locs": [], "n": 0})
        g["area"] += c["area"]
        g["locs"].append(c["loc"])
        g["n"] += 1

    info = {
        "vol": vol, "bbox": (x2 - x1, y2 - y1, z2 - z1),
        "range": (x1, y1, z1, x2, y2, z2),
        "fill": fill, "groups": groups,
        "has_internal": fill < 0.85 or len(groups) >= 2,
    }
    if verbose:
        print(f"  [结构] 体积 {vol:,.1f}  bbox "
              f"{x2-x1:.2f}×{y2-y1:.2f}×{z2-z1:.2f}  掏空度 {fill*100:.1f}%")
        print(f"  [结构] 圆柱面 {len(cyls)} 个 → {len(groups)} 组"
              f"（轴向+半径聚类）")
        for (ax, r), g in sorted(groups.items(), key=lambda kv: -kv[1]["area"]):
            print(f"           轴{_axis_name(ax):>6s} r={r:6.2f} "
                  f"×{g['n']:2d}面 面积{g['area']:9.1f}")
    return info


def _axis_name(ax):
    for name, v in (("X", (1, 0, 0)), ("Y", (0, 1, 0)), ("Z", (0, 0, 1))):
        if all(abs(a - b) < 0.05 for a, b in zip(ax, v)):
            return name
    return "斜"


def suggest_sections(info, max_n=3):
    """按内部特征推荐剖切面。

    规则（机械制图惯例）：
      1. 沿零件最长方向的**纵向全剖**最能表达内腔走向 → 首选，
         剖在对称面上（多数零件关于该面对称，剖面即中截面）
      2. 对每一簇**垂直于纵向的孔轴**，补一个横剖，剖在孔轴位置上——
         这样孔在剖面里是真实的矩形缺口而非隐藏线
      3. 只保留特征量最大的前 max_n 个，避免图纸堆砌
    """
    x1, y1, z1, x2, y2, z2 = info["range"]
    cx, cy, cz = (x1 + x2) / 2, (y1 + y2) / 2, (z1 + z2) / 2
    dims = [x2 - x1, y2 - y1, z2 - z1]
    longest = dims.index(max(dims))

    out = []
    # --- 1. 纵向全剖：切掉 "近侧" 一半，沿最长方向铺开 ---
    if longest == 0:      # X 最长 → 从前面看，剖在 y=cy
        out.append({"label": "A—A", "origin": (0, cy, 0), "normal": (0, 1, 0),
                    "view_dir": (0, -1, 0), "up": (0, 0, 1),
                    "parent": "top", "desc": f"纵向全剖 y={cy:.2f}（中截面）"})
    elif longest == 1:    # Y 最长 → 从侧面看，剖在 x=cx
        out.append({"label": "A—A", "origin": (cx, 0, 0), "normal": (1, 0, 0),
                    "view_dir": (1, 0, 0), "up": (0, 0, 1),
                    "parent": "top", "desc": f"纵向全剖 x={cx:.2f}（中截面）"})
    else:                 # Z 最长 → 从前面看，剖在 y=cy
        out.append({"label": "A—A", "origin": (0, cy, 0), "normal": (0, 1, 0),
                    "view_dir": (0, -1, 0), "up": (0, 0, 1),
                    "parent": "top", "desc": f"纵向全剖 y={cy:.2f}（中截面）"})

    # --- 2. 横剖：穿过垂直于纵向的孔轴 ---
    # 注意不能对同组孔位取均值——r20 组的两个孔在 x=-18.11 / 31.89，
    # 均值 x=15.2 是两孔之间的实心处，剖了什么也看不到。必须按位置聚类，
    # 每个聚类是一处真实特征。
    cands = []
    for (ax, r), g in info["groups"].items():
        if _axis_name(ax) == "斜":
            continue
        ai = ax.index(max(ax))
        if ai == longest:
            continue                      # 与纵向同轴的孔，纵剖已表达
        per_face = g["area"] / max(1, g["n"])
        for lo in g["locs"]:
            cands.append({"pos": lo[longest], "r": r, "area": per_face})

    clusters = []
    for c in sorted(cands, key=lambda c: c["pos"]):
        for cl in clusters:
            if abs(c["pos"] - cl["pos"]) < max(8.0, c["r"] * 1.5):
                cl["area"] += c["area"]
                cl["r"] = max(cl["r"], c["r"])
                cl["n"] += 1
                break
        else:
            clusters.append({"pos": c["pos"], "r": c["r"],
                             "area": c["area"], "n": 1})

    labels = ["B—B", "C—C", "D—D"]
    picked = []
    for cl in sorted(clusters, key=lambda c: -c["area"]):
        pos, r = cl["pos"], cl["r"]
        if any(abs(pos - p) < max(8.0, r * 1.5) for p in picked):
            continue
        picked.append(pos)
        org = [0.0, 0.0, 0.0]
        org[longest] = pos
        nrm = [0.0, 0.0, 0.0]
        nrm[longest] = 1.0
        vd = [0.0, 0.0, 0.0]
        vd[longest] = 1.0
        out.append({
            "label": labels[len(picked) - 1],
            "origin": tuple(org), "normal": tuple(nrm),
            "view_dir": tuple(vd), "up": (0, 0, 1),
            "parent": "front",
            "desc": f"横剖 {'xyz'[longest]}={pos:.2f}（穿 r{r:.1f} 孔轴）",
        })
        if len(out) >= max_n or len(picked) >= len(labels):
            break
    return out[:max_n]


# ============================================================
# 3. 剖切 + 截面提取
# ============================================================

def _proj_axes(view_dir, up):
    """复刻 HLRAlgo_Projector 的 gp_Ax2 局部系：返回 (dx, dy) 单位向量。"""
    dz = gp_Dir(*view_dir)
    vu = gp_Dir(*up)
    dx = gp_Dir(gp_Vec(
        vu.Y() * dz.Z() - vu.Z() * dz.Y(),
        vu.Z() * dz.X() - vu.X() * dz.Z(),
        vu.X() * dz.Y() - vu.Y() * dz.X(),
    ))
    dy = gp_Dir(gp_Vec(
        dz.Y() * dx.Z() - dz.Z() * dx.Y(),
        dz.Z() * dx.X() - dz.X() * dx.Z(),
        dz.X() * dx.Y() - dz.Y() * dx.X(),
    ))
    return dx, dy


def _to2d(p, dx, dy):
    return (p.X() * dx.X() + p.Y() * dx.Y() + p.Z() * dx.Z(),
            p.X() * dy.X() + p.Y() * dy.Y() + p.Z() * dy.Z())


def half_space_cut(shape, origin, normal, keep_negative=True):
    """用半空间盒裁掉剖切面一侧，保留另一侧。

    keep_negative=True 保留法向**负**侧（观察者与剖切面之间的材料被移走），
    符合"剖视图移去观察者一侧"的制图约定。
    """
    x1, y1, z1, x2, y2, z2 = bbox_of(shape)
    pad = max(x2 - x1, y2 - y1, z2 - z1) * 2 + 100
    lo = [x1 - pad, y1 - pad, z1 - pad]
    hi = [x2 + pad, y2 + pad, z2 + pad]
    ai = max(range(3), key=lambda i: abs(normal[i]))
    cut_at = origin[ai]
    if (normal[ai] > 0) == keep_negative:
        hi[ai] = cut_at
    else:
        lo[ai] = cut_at
    box = BRepPrimAPI_MakeBox(gp_Pnt(*lo), gp_Pnt(*hi)).Shape()
    op = BRepAlgoAPI_Common(shape, box)
    if not op.IsDone():
        raise RuntimeError("剖切布尔失败")
    return op.Shape()


def cut_faces(half, origin, normal):
    """挑出落在剖切面上的面 —— 这些面就是要打剖面线的截面。"""
    ai = max(range(3), key=lambda i: abs(normal[i]))
    cut_at = origin[ai]
    out = []
    ex = TopExp_Explorer(half, TopAbs_FACE)
    while ex.More():
        f = topods.Face(ex.Current())
        s = BRepAdaptor_Surface(f)
        if s.GetType() == GeomAbs_Plane:
            pl = s.Plane()
            n = pl.Axis().Direction()
            nv = (n.X(), n.Y(), n.Z())
            # 法向与剖切面平行，且面上一点落在剖切面上
            if abs(abs(nv[ai]) - 1.0) < 1e-3:
                loc = pl.Location()
                if abs((loc.X(), loc.Y(), loc.Z())[ai] - cut_at) < _ON_PLANE_TOL:
                    out.append(f)
        ex.Next()
    return out


def _discretize_wire(wire, dx, dy):
    """按顺序离散一条环 → 2D 点列。"""
    pts = []
    it = BRepTools_WireExplorer(wire)
    while it.More():
        e = it.Current()
        try:
            ad = BRepAdaptor_Curve(e)
            d = GCPnts_QuasiUniformDeflection(ad, _DEFLECTION)
            if not d.IsDone():
                it.Next()
                continue
            n = d.NbPoints()
            seq = range(1, n + 1)
            if e.Orientation() == TopAbs_REVERSED:
                seq = range(n, 0, -1)
            for i in seq:
                pts.append(_to2d(d.Value(i), dx, dy))
        except Exception:
            pass
        it.Next()

    # 相邻重复点压缩（相邻边共享端点）
    out = []
    for p in pts:
        if not out or math.hypot(p[0] - out[-1][0], p[1] - out[-1][1]) > 1e-7:
            out.append(p)
    if len(out) > 1 and math.hypot(out[0][0] - out[-1][0],
                                   out[0][1] - out[-1][1]) < 1e-7:
        out.pop()
    return out


def face_to_paths(face, dx, dy):
    """截面 face → (外环 2D 点列, [内环点列, ...])。内环即孔，需留白。"""
    outer_w = breptools.OuterWire(face)
    outer, inners = [], []
    ex = TopExp_Explorer(face, TopAbs_WIRE)
    while ex.More():
        w = topods.Wire(ex.Current())
        pts = _discretize_wire(w, dx, dy)
        if len(pts) >= 3:
            if w.IsSame(outer_w):
                outer = pts
            else:
                inners.append(pts)
        ex.Next()
    return outer, inners


def project_section_poly(shape, view_dir, up, deflection=0.05):
    """多边形 HLR 投影（剖面专用）。

    为什么剖面不能用 `project_shape_to_2d` 的精确 HLR：本零件含 9 个
    B 样条面 + 2 个球面，被布尔裁剪后精确 HLR（HLRBRep_Algo）在所有
    输出通道返回 **0 条边**——形状本身 BRepCheck 有效、体积正确，
    换 ShapeFix / BRepBuilderAPI_Copy / IncrementalMesh / breptools.Clean
    / 平移 / 换包围盒尺寸全部无效（纯 box 半切正常，说明不是布尔本身
    的问题，是该零件裁剪后的裁剪曲面精确 HLR 顶不住）。
    HLRBRep_PolyAlgo 基于三角网格，同一形状给出 335 可见 + 289 隐藏边。

    代价：曲线输出为折线，故 circles 恒为空——剖面图里圆弧以折线表达，
    肉眼与真圆无异（弦高 0.05mm），但不要拿这个结果去做圆特征识别。
    """
    from OCC.Core.BRepMesh import BRepMesh_IncrementalMesh
    from OCC.Core.HLRAlgo import HLRAlgo_Projector
    from OCC.Core.HLRBRep import HLRBRep_PolyAlgo, HLRBRep_PolyHLRToShape
    from OCC.Core.gp import gp_Ax2
    from OCC.Core.TopAbs import TopAbs_EDGE

    BRepMesh_IncrementalMesh(shape, deflection, False, 0.5, True)
    dz = gp_Dir(*view_dir)
    dxd, _ = _proj_axes(view_dir, up)
    proj = HLRAlgo_Projector(gp_Ax2(gp_Pnt(0, 0, 0), dz, dxd))
    algo = HLRBRep_PolyAlgo()
    algo.Load(shape)
    algo.Projector(proj)
    algo.Update()
    ts = HLRBRep_PolyHLRToShape()
    ts.Update(algo)

    out = {"lines": [], "circles": [], "hidden_lines": [], "hidden_circles": []}
    for method, key in (("VCompound", "lines"),
                        ("OutLineVCompound", "lines"),
                        ("HCompound", "hidden_lines"),
                        ("OutLineHCompound", "hidden_lines")):
        try:
            comp = getattr(ts, method)()
        except Exception:
            continue
        if comp is None or comp.IsNull():
            continue
        ex = TopExp_Explorer(comp, TopAbs_EDGE)
        while ex.More():
            try:
                ad = BRepAdaptor_Curve(ex.Current())
                p1 = ad.Value(ad.FirstParameter())
                p2 = ad.Value(ad.LastParameter())
                out[key].append((p1.X(), p1.Y(), p2.X(), p2.Y()))
            except Exception:
                pass
            ex.Next()
    return out


def generate_section(shape, spec, verbose=True):
    """按 spec 生成一个剖面视图。

    Returns: {"view": HLR投影结果, "hatch": [(外环, [内环...]), ...],
              "label": "A—A", "desc": ...}
    """
    half = half_space_cut(shape, spec["origin"], spec["normal"])
    view = project_section_poly(half, spec["view_dir"], spec["up"])
    dx, dy = _proj_axes(spec["view_dir"], spec["up"])

    faces = cut_faces(half, spec["origin"], spec["normal"])
    hatch = []
    true_area = poly_area = 0.0
    for f in faces:
        outer, inners = face_to_paths(f, dx, dy)
        if len(outer) < 3:
            continue
        hatch.append((outer, inners))
        fp = GProp_GProps()
        brepgprop.SurfaceProperties(f, fp)
        true_area += fp.Mass()
        poly_area += _poly_area(outer) - sum(_poly_area(i) for i in inners)

    # 自检：2D 路径围出的面积必须等于 OCC 实测截面面积，否则说明
    # 环没闭合 / 内外环判反 / 2D 映射错，剖面线会画到材料外面去
    err = abs(poly_area - true_area) / true_area if true_area > 0 else 0.0
    if verbose:
        n_in = sum(len(h[1]) for h in hatch)
        # 控制台是 GBK，不能用 ✓/✗（UnicodeEncodeError）
        flag = "[OK]" if err < 0.01 else f"[!] 偏差{err*100:.1f}%"
        print(f"  [{spec['label']}] {spec['desc']}")
        print(f"           {len(view['lines'])}线 {len(view['circles'])}圆 | "
              f"截面 {len(hatch)} 块 {n_in} 孔洞 | "
              f"面积 {poly_area:,.1f} vs 实测 {true_area:,.1f} {flag}")
    return {"view": view, "hatch": hatch, "label": spec["label"],
            "desc": spec["desc"], "spec": spec,
            "area": true_area, "area_err": err}


def _poly_area(pts):
    """鞋带公式，取绝对值（不关心环的绕向）。"""
    s = 0.0
    n = len(pts)
    for i in range(n):
        x1, y1 = pts[i]
        x2, y2 = pts[(i + 1) % n]
        s += x1 * y2 - x2 * y1
    return abs(s) / 2.0


def bbox_2d(view_dict, margin=2.0):
    """视图 2D 包围盒 —— 弧按**实际角度跨度**取极值。

    `generate_engineering_drawing._bbox_all` 对弧一律按整圆算 (cx±r, cy±r)，
    在有大半径短弧的视图上会虚胖：bracket top 视图里一条 r28.5、
    实际只覆盖 y∈[-7,7] 的弧，把视图高度从真实 51.01 撑到 57.00
    （比 side 视图同轴实测多 6mm）。那个函数被闭环链的布局共用，
    不去动它；这里另给准确实现供图纸排版使用。
    """
    xs, ys = [], []

    def _arc(cx, cy, r, is_full, angles):
        if is_full or not angles:
            xs.extend([cx - r, cx + r])
            ys.extend([cy - r, cy + r])
            return
        for a1, a2 in angles:
            lo, hi = (a1, a2) if a2 >= a1 else (a1, a2 + 2 * math.pi)
            pts = [lo, hi]
            # 象限极值点（0/90/180/270）落在跨度内才计入
            k = math.ceil(lo / (math.pi / 2)) * (math.pi / 2)
            while k <= hi:
                pts.append(k)
                k += math.pi / 2
            for a in pts:
                xs.append(cx + r * math.cos(a))
                ys.append(cy + r * math.sin(a))

    for key in ("lines", "hidden_lines"):
        for x1, y1, x2, y2 in view_dict.get(key, []):
            xs.extend([x1, x2])
            ys.extend([y1, y2])
    for key in ("circles", "hidden_circles"):
        for c in view_dict.get(key, []):
            _arc(*c)
    if not xs:
        return 0.0, 0.0, 100.0, 100.0
    return (min(xs) - margin, min(ys) - margin,
            max(xs) + margin, max(ys) + margin)


# ============================================================
# 4. DXF 绘制
# ============================================================

LAYERS = [
    ("可见轮廓", 7, "CONTINUOUS", 0.5),
    ("隐藏线", 5, "HIDDEN", 0.25),
    ("剖面线", 3, "CONTINUOUS", 0.18),
    ("剖切线", 1, "CONTINUOUS", 0.7),
    ("标注", 2, "CONTINUOUS", 0.25),
]


def setup_layers(doc):
    for name, color, ltype, lw in LAYERS:
        ly = doc.layers.add(name, color=color)
        if ltype != "CONTINUOUS":
            try:
                ly.set_linetype(ltype)
            except Exception:
                pass
        try:
            ly.dxf.lineweight = int(lw * 100)
        except Exception:
            pass


def draw_hatch(msp, hatch_paths, ox, oy, scale=2.0):
    """截面 → DXF HATCH 实体（真剖面线，孔洞留白）。

    外环 EXTERNAL + 内环 DEFAULT，配合 NESTED 样式让 ezdxf/CAD 自己做
    奇偶填充——孔不会被剖面线盖住。旧实现按包围盒画 45° 直线，
    在有内腔的零件上剖面线会糊满孔和零件外的空白。
    """
    import ezdxf
    n = 0
    for outer, inners in hatch_paths:
        h = msp.add_hatch(dxfattribs={"layer": "剖面线", "color": 3})
        h.set_pattern_fill("ANSI31", scale=scale)
        h.dxf.hatch_style = ezdxf.const.HATCH_STYLE_NESTED
        h.paths.add_polyline_path(
            [(x + ox, y + oy) for x, y in outer], is_closed=True,
            flags=ezdxf.const.BOUNDARY_PATH_EXTERNAL)
        for inner in inners:
            h.paths.add_polyline_path(
                [(x + ox, y + oy) for x, y in inner], is_closed=True,
                flags=ezdxf.const.BOUNDARY_PATH_DEFAULT)
        n += 1
    return n


def draw_cut_marker(msp, spec, parent_view, ox, oy, bb, mirror_x=False):
    """在父视图上画剖切线：粗短划 + 箭头 + 字母。

    父视图 2D 映射决定剖切面画成横线还是竖线：
      top 视图 (DXF_X=-3D_X, DXF_Y=3D_Y)：法向 Y → 横线 y=origin_y；
                                          法向 X → 竖线 x=-origin_x
    """
    nrm = spec["normal"]
    ai = max(range(3), key=lambda i: abs(nrm[i]))
    x1, y1, x2, y2 = bb
    ext = 6.0        # 剖切线伸出视图轮廓的长度
    seg = 8.0        # 端部粗短划长度
    label = spec["label"]

    if ai == 1:      # 法向 Y → 父视图上是横线
        yy = spec["origin"][1] + oy
        xa, xb = x1 + ox - ext, x2 + ox + ext
        msp.add_line((xa, yy), (xa + seg, yy), dxfattribs={"layer": "剖切线"})
        msp.add_line((xb - seg, yy), (xb, yy), dxfattribs={"layer": "剖切线"})
        for xe, sgn in ((xa, 1), (xb, -1)):
            # 箭头指向观察方向（-Y 看 → 图纸上向下）
            msp.add_line((xe, yy), (xe + sgn * 4, yy - 6),
                         dxfattribs={"layer": "剖切线"})
            msp.add_text(label, height=5.0,
                         dxfattribs={"layer": "标注"}).set_placement(
                             (xe + sgn * 2, yy + 3))
    else:            # 法向 X → 父视图上是竖线
        v = spec["origin"][0]
        xx = (-v if mirror_x else v) + ox
        ya, yb = y1 + oy - ext, y2 + oy + ext
        msp.add_line((xx, ya), (xx, ya + seg), dxfattribs={"layer": "剖切线"})
        msp.add_line((xx, yb - seg), (xx, yb), dxfattribs={"layer": "剖切线"})
        for ye, sgn in ((ya, 1), (yb, -1)):
            msp.add_line((xx, ye), (xx + 6, ye + sgn * 4),
                         dxfattribs={"layer": "剖切线"})
            msp.add_text(label, height=5.0,
                         dxfattribs={"layer": "标注"}).set_placement(
                             (xx + 3, ye + sgn * 2))


def draw_label(msp, text, cx, cy, height=6.0):
    msp.add_text(text, height=height,
                 dxfattribs={"layer": "标注"}).set_placement(
                     (cx, cy), align=__import__("ezdxf").enums.TextEntityAlignment.MIDDLE_CENTER)
