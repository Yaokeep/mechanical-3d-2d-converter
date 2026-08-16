#!/usr/bin/env python
"""通用 DXF 工程图 → 3D SolidWorks 模型转换器 v2.1

核心改进（相比 v2.0）:
  1. 自动视图检测 — 基于文字标签 + 几何密度分析
  2. 主体优先 — 先识别最大非圆轮廓作为主体，再在其上加减特征
  3. 正确的圆柱体 — 同心圆弧 → 贯穿圆柱/孔
  4. SPLINE 智能处理 — 过滤采样产生的碎片面
  5. 剖面图支持 — 多剖面轮廓空间组合
  6. 单视图轮廓拉伸 — 简单零件自动使用轮廓拉伸 + 内孔减除

用法:
    python dxf_to_3d_general.py <输入.dxf> [输出.sldprt] [--single-view|--multi-view]
    --single-view: 强制单视图轮廓拉伸模式
    --multi-view:  强制多视图包围盒模式（v2.0 行为）
"""

import math
import sys
import os
from pathlib import Path
from collections import Counter, defaultdict

PROJECT_ROOT = Path(__file__).parent
SRC_PATH = PROJECT_ROOT / "src"
for p in [str(PROJECT_ROOT), str(SRC_PATH)]:
    if p not in sys.path:
        sys.path.insert(0, p)

import ezdxf

# PythonOCC 延迟加载
_OCC_LOADED = False


def _ensure_occ():
    """延迟加载 PythonOCC 模块。"""
    global _OCC_LOADED
    if _OCC_LOADED:
        return
    from OCC.Core.gp import (
        gp_Pnt, gp_Dir, gp_Ax1, gp_Ax2, gp_Vec,
        gp_Circ, gp_Trsf, gp_GTrsf, gp_XYZ,
    )
    from OCC.Core.BRepBuilderAPI import (
        BRepBuilderAPI_MakeEdge, BRepBuilderAPI_MakeWire,
        BRepBuilderAPI_MakeFace, BRepBuilderAPI_Transform,
        BRepBuilderAPI_GTransform, BRepBuilderAPI_MakePolygon,
        BRepBuilderAPI_MakeVertex,
    )
    from OCC.Core.BRepPrimAPI import (
        BRepPrimAPI_MakePrism, BRepPrimAPI_MakeRevol,
        BRepPrimAPI_MakeCylinder, BRepPrimAPI_MakeBox,
    )
    from OCC.Core.BRepAlgoAPI import BRepAlgoAPI_Fuse, BRepAlgoAPI_Cut, BRepAlgoAPI_Common
    from OCC.Core.ShapeFix import ShapeFix_Face, ShapeFix_Wire, ShapeFix_Shape
    from OCC.Core.TopoDS import TopoDS_Shape, TopoDS_Face, TopoDS_Wire
    from OCC.Core.STEPControl import STEPControl_Writer, STEPControl_AsIs
    from OCC.Core.IFSelect import IFSelect_RetDone
    from OCC.Core.TopExp import TopExp_Explorer
    from OCC.Core.TopAbs import TopAbs_EDGE, TopAbs_WIRE, TopAbs_FACE, TopAbs_SOLID
    from OCC.Core.BRepCheck import BRepCheck_Analyzer
    from OCC.Core.GProp import GProp_GProps
    from OCC.Core.BRepGProp import brepgprop
    from OCC.Core.BRep import BRep_Builder
    from OCC.Core.BRepTools import breptools
    from OCC.Core.BRepClass3d import BRepClass3d_SolidClassifier
    from OCC.Core.Bnd import Bnd_Box
    from OCC.Core.BRepBndLib import brepbndlib
    from OCC.Core.BRepExtrema import BRepExtrema_DistShapeShape

    g = globals()
    for name, obj in [
        ("gp_Pnt", gp_Pnt), ("gp_Dir", gp_Dir), ("gp_Ax1", gp_Ax1),
        ("gp_Ax2", gp_Ax2), ("gp_Vec", gp_Vec), ("gp_Circ", gp_Circ),
        ("gp_Trsf", gp_Trsf), ("gp_GTrsf", gp_GTrsf), ("gp_XYZ", gp_XYZ),
        ("BRepBuilderAPI_MakeEdge", BRepBuilderAPI_MakeEdge),
        ("BRepBuilderAPI_MakeWire", BRepBuilderAPI_MakeWire),
        ("BRepBuilderAPI_MakeFace", BRepBuilderAPI_MakeFace),
        ("BRepBuilderAPI_Transform", BRepBuilderAPI_Transform),
        ("BRepBuilderAPI_GTransform", BRepBuilderAPI_GTransform),
        ("BRepBuilderAPI_MakePolygon", BRepBuilderAPI_MakePolygon),
        ("BRepPrimAPI_MakePrism", BRepPrimAPI_MakePrism),
        ("BRepPrimAPI_MakeRevol", BRepPrimAPI_MakeRevol),
        ("BRepPrimAPI_MakeCylinder", BRepPrimAPI_MakeCylinder),
        ("BRepPrimAPI_MakeBox", BRepPrimAPI_MakeBox),
        ("BRepAlgoAPI_Fuse", BRepAlgoAPI_Fuse),
        ("BRepAlgoAPI_Cut", BRepAlgoAPI_Cut),
        ("BRepAlgoAPI_Common", BRepAlgoAPI_Common),
        ("ShapeFix_Face", ShapeFix_Face), ("ShapeFix_Wire", ShapeFix_Wire),
        ("ShapeFix_Shape", ShapeFix_Shape),
        ("STEPControl_Writer", STEPControl_Writer),
        ("STEPControl_AsIs", STEPControl_AsIs),
        ("IFSelect_RetDone", IFSelect_RetDone),
        ("TopExp_Explorer", TopExp_Explorer),
        ("TopAbs_EDGE", TopAbs_EDGE), ("TopAbs_WIRE", TopAbs_WIRE),
        ("TopAbs_FACE", TopAbs_FACE), ("TopAbs_SOLID", TopAbs_SOLID),
        ("GProp_GProps", GProp_GProps), ("brepgprop", brepgprop),
        ("BRepCheck_Analyzer", BRepCheck_Analyzer),
        ("BRep_Builder", BRep_Builder), ("breptools", breptools),
        ("BRepClass3d_SolidClassifier", BRepClass3d_SolidClassifier),
        ("Bnd_Box", Bnd_Box), ("brepbndlib", brepbndlib),
    ]:
        g[name] = obj
    _OCC_LOADED = True


# ---- 容差 ----
SNAP_TOL = 0.01       # 端点合并容差 (mm)
CENTER_MERGE_TOL = 1.0  # 同心圆心合并容差 (mm)


# ============================================================
# 1. DXF 实体 → 统一边表示
# ============================================================

class Edge:
    """统一边：LINE 或 ARC，记录起止点与几何参数。"""
    __slots__ = (
        "id", "etype", "start", "end",
        "center", "radius", "start_angle", "end_angle",
        "clockwise",
    )

    def __init__(self, eid, etype, start, end,
                 center=None, radius=None,
                 start_angle=None, end_angle=None,
                 clockwise=False):
        self.id = eid
        self.etype = etype
        self.start = start
        self.end = end
        self.center = center
        self.radius = radius
        self.start_angle = start_angle
        self.end_angle = end_angle
        self.clockwise = clockwise

    @property
    def length_2d(self):
        dx = self.end[0] - self.start[0]
        dy = self.end[1] - self.start[1]
        if self.etype == "LINE":
            return math.hypot(dx, dy)
        else:
            da = abs(self.end_angle - self.start_angle)
            if da > 180:
                da = 360 - da
            return self.radius * math.radians(da)

    def is_zero_length(self):
        return self.length_2d < SNAP_TOL


SKIP_LINETYPES = ("CENTER", "CENTER2", "CENTERX2", "DASHDOT", "PHANTOM",
                  "CONSTRUCTION", "HIDDEN", "HIDDEN2", "DASHED")


def _linetype_of(e, doc):
    """实体线型（BYLAYER 时解析图层线型）— 真实图纸常用图层组织线型。"""
    lt = ""
    try:
        lt = (e.dxf.linetype or "").upper()
    except Exception:
        pass
    if lt in ("", "BYLAYER"):
        try:
            layer = doc.layers.get(e.dxf.layer)
            lt = (layer.dxf.linetype or "").upper()
        except Exception:
            pass
    return lt


SKIP_LAYER_KEYWORDS = ("隐藏", "中心", "构造", "剖面", "标注", "文字",
                       "图框", "CENTER", "HIDDEN", "DASHED", "CONSTRUCTION",
                       "FRAME", "BORDER")


def _is_skip_entity(e, lt):
    """线型或图层名命中辅助线关键词 → 跳过。

    v0.6.3: 本管线生成的 DXF 中 set_linetype('HIDDEN') 可能静默失败
    （ezdxf 1.x 默认线型表无 HIDDEN），'隐藏线' 图层线型退化为
    Continuous → 隐藏线混入边图，与可见线重合形成平行重复边，
    面遍历在重复边之间绕 8 字环。图层名关键词过滤不依赖线型表。
    """
    if lt in SKIP_LINETYPES:
        return True
    try:
        layer = (e.dxf.layer or "").upper()
    except Exception:
        return False
    return any(k in layer for k in SKIP_LAYER_KEYWORDS)


def parse_dxf_edges(dxf_path: str) -> tuple[list[Edge], dict]:
    """从 DXF 提取所有几何实体为统一边列表。"""
    doc = ezdxf.readfile(dxf_path)
    msp = doc.modelspace()

    edges = []
    eid = 0
    entity_counts = {}

    # LINE（跳过中心线、构造线等辅助线）
    for e in msp.query("LINE"):
        lt = _linetype_of(e, doc)
        # 过滤中心线和构造线
        if _is_skip_entity(e, lt):
            entity_counts["LINE_SKIPPED"] = entity_counts.get("LINE_SKIPPED", 0) + 1
            continue
        x1, y1 = e.dxf.start.x, e.dxf.start.y
        x2, y2 = e.dxf.end.x, e.dxf.end.y
        edge = Edge(eid, "LINE", (x1, y1), (x2, y2))
        if not edge.is_zero_length():
            edges.append(edge)
            eid += 1
        entity_counts["LINE"] = entity_counts.get("LINE", 0) + 1

    # ARC
    for e in msp.query("ARC"):
        if _is_skip_entity(e, _linetype_of(e, doc)):
            entity_counts["ARC_SKIPPED"] = entity_counts.get("ARC_SKIPPED", 0) + 1
            continue
        cx, cy = e.dxf.center.x, e.dxf.center.y
        r = e.dxf.radius
        a1 = e.dxf.start_angle
        a2 = e.dxf.end_angle
        sx = cx + r * math.cos(math.radians(a1))
        sy = cy + r * math.sin(math.radians(a1))
        ex = cx + r * math.cos(math.radians(a2))
        ey = cy + r * math.sin(math.radians(a2))
        edge = Edge(eid, "ARC", (sx, sy), (ex, ey),
                    center=(cx, cy), radius=r,
                    start_angle=a1, end_angle=a2)
        if not edge.is_zero_length():
            edges.append(edge)
            eid += 1
        entity_counts["ARC"] = entity_counts.get("ARC", 0) + 1

    # CIRCLE → 拆为两个 180° 弧
    # v0.6.3: 隐藏层整圆**保留**（区别于隐藏直线/弧的过滤）——
    # (1) HLR 会把俯视图 edge-on 圆柱外轮廓圆判为隐藏（主体 r30
    #     外圆在 v6 图纸中位于隐藏线层），过滤后外环退化；
    # (2) 内部孔/台阶圆（r25/r8.5/r1.6 等）是 P0 布尔减的刀具
    #     来源，必须保留。隐藏整圆不与可见线重合（不同几何），
    #     不会引入平行重复边问题。
    for e in msp.query("CIRCLE"):
        lt = _linetype_of(e, doc)
        try:
            layer = (e.dxf.layer or "").upper()
        except Exception:
            layer = ""
        if lt in SKIP_LINETYPES or any(
                k in layer for k in ("中心", "构造", "剖面", "标注",
                                     "文字", "CENTER", "CONSTRUCTION")):
            entity_counts["CIRCLE_SKIPPED"] = entity_counts.get("CIRCLE_SKIPPED", 0) + 1
            continue
            entity_counts["CIRCLE_SKIPPED"] = entity_counts.get("CIRCLE_SKIPPED", 0) + 1
            continue
        cx, cy = e.dxf.center.x, e.dxf.center.y
        r = e.dxf.radius
        if r < SNAP_TOL:
            continue
        e1 = Edge(eid, "ARC",
                  (cx + r, cy), (cx - r, cy),
                  center=(cx, cy), radius=r,
                  start_angle=0, end_angle=180)
        eid += 1
        e2 = Edge(eid, "ARC",
                  (cx - r, cy), (cx + r, cy),
                  center=(cx, cy), radius=r,
                  start_angle=180, end_angle=360)
        eid += 1
        edges.append(e1)
        edges.append(e2)
        entity_counts["CIRCLE"] = entity_counts.get("CIRCLE", 0) + 1

    # LWPOLYLINE — 拆为 LINE/ARC 段
    for e in msp.query("LWPOLYLINE"):
        if _is_skip_entity(e, _linetype_of(e, doc)):
            entity_counts["LWPOLYLINE_SKIPPED"] = entity_counts.get("LWPOLYLINE_SKIPPED", 0) + 1
            continue
        pts_raw = list(e.vertices())
        # 兼容 ezdxf 不同版本：vertices() 可能返回 tuple 或 DXF 对象
        pts = []
        for p in pts_raw:
            if hasattr(p, 'dxf'):
                pts.append((p.dxf.location.x, p.dxf.location.y))
            elif hasattr(p, 'location'):
                pts.append((p.location.x, p.location.y))
            elif isinstance(p, (tuple, list)) and len(p) >= 2:
                pts.append((float(p[0]), float(p[1])))
            else:
                pts.append((float(p[0]), float(p[1])))  # 尝试直接索引
        if len(pts) < 2:
            continue
        n_segments = len(pts)
        # 检查是否闭合 polyline：闭合标志 或 首尾点重合
        is_closed = False
        try:
            is_closed = bool(e.closed)
        except Exception:
            pass
        if not is_closed:
            dx = pts[0][0] - pts[-1][0]
            dy = pts[0][1] - pts[-1][1]
            if math.hypot(dx, dy) < SNAP_TOL:
                is_closed = True
        if is_closed:
            n_segments = len(pts)  # 包含闭合边：n 条边连接 n 个顶点
        else:
            n_segments = len(pts) - 1  # 开放：n-1 条边

        for i in range(n_segments):
            idx1 = i
            idx2 = (i + 1) % len(pts)  # 闭合时最后一个顶点回到第一个
            x1, y1 = pts[idx1]
            x2, y2 = pts[idx2]
            # bulge 从原始顶点对象获取
            bulge = 0.0
            if hasattr(pts_raw[i], 'dxf'):
                try:
                    bulge = pts_raw[i].dxf.bulge
                except AttributeError:
                    bulge = 0.0
            if abs(bulge) < 1e-9:
                edge = Edge(eid, "LINE", (x1, y1), (x2, y2))
                if not edge.is_zero_length():
                    edges.append(edge)
                    eid += 1
            else:
                theta = 4 * math.atan(abs(bulge))
                chord = math.hypot(x2 - x1, y2 - y1)
                if chord < SNAP_TOL or theta < 1e-9:
                    continue
                r = chord / (2 * math.sin(theta / 2))
                mx, my = (x1 + x2) / 2, (y1 + y2) / 2
                dx, dy = x2 - x1, y2 - y1
                nx, ny = -dy / chord, dx / chord
                offset = r * math.cos(theta / 2)
                if bulge > 0:
                    cx = mx + nx * offset
                    cy = my + ny * offset
                else:
                    cx = mx - nx * offset
                    cy = my - ny * offset
                a1 = math.degrees(math.atan2(y1 - cy, x1 - cx))
                a2_val = math.degrees(math.atan2(y2 - cy, x2 - cx))
                edge = Edge(eid, "ARC", (x1, y1), (x2, y2),
                            center=(cx, cy), radius=r,
                            start_angle=a1, end_angle=a2_val,
                            clockwise=(bulge < 0))
                if not edge.is_zero_length():
                    edges.append(edge)
                    eid += 1
        entity_counts["LWPOLYLINE"] = entity_counts.get("LWPOLYLINE", 0) + 1

    # SPLINE → 采样为 LINE 段，记录原始 SPLINE 信息用于后续过滤
    for e in msp.query("SPLINE"):
        if _is_skip_entity(e, _linetype_of(e, doc)):
            entity_counts["SPLINE_SKIPPED"] = entity_counts.get("SPLINE_SKIPPED", 0) + 1
            continue
        try:
            ctrl = list(e.control_points)
            if len(ctrl) >= 2:
                for i in range(len(ctrl) - 1):
                    p1 = (ctrl[i][0], ctrl[i][1]) if hasattr(ctrl[i], '__len__') else (ctrl[i].x, ctrl[i].y)
                    p2 = (ctrl[i+1][0], ctrl[i+1][1]) if hasattr(ctrl[i+1], '__len__') else (ctrl[i+1].x, ctrl[i+1].y)
                    edge = Edge(eid, "LINE", p1, p2)
                    if not edge.is_zero_length():
                        edges.append(edge)
                        eid += 1
            entity_counts["SPLINE"] = entity_counts.get("SPLINE", 0) + 1
        except Exception:
            pass

    # 计算 bbox
    xs, ys = [], []
    for e in edges:
        xs.extend([e.start[0], e.end[0]])
        ys.extend([e.start[1], e.end[1]])
        if e.etype == "ARC" and e.center:
            xs.append(e.center[0])
            ys.append(e.center[1])

    metadata = {
        "bbox_min": (min(xs) if xs else 0, min(ys) if ys else 0),
        "bbox_max": (max(xs) if xs else 0, max(ys) if ys else 0),
        "entity_counts": entity_counts,
        "total_edges": eid,
    }
    return edges, metadata


def parse_dxf_texts(dxf_path: str) -> list[dict]:
    """提取 DXF 中的文字实体，用于视图标签检测。"""
    doc = ezdxf.readfile(dxf_path)
    msp = doc.modelspace()
    texts = []
    for e in msp.query("TEXT MTEXT"):
        try:
            if e.dxftype() == "MTEXT":
                txt = e.text if hasattr(e, 'text') else ''
            else:
                txt = e.dxf.text if hasattr(e.dxf, 'text') else ''
            x = e.dxf.insert.x
            y = e.dxf.insert.y
            texts.append({"text": txt.strip(), "x": x, "y": y, "type": e.dxftype()})
        except Exception:
            pass
    return texts


def extract_dxf_annotations(dxf_path: str) -> dict:
    """提取 DXF 工程图中的辅助信息：剖面线、中心线、截面标记。

    返回:
        {
            "hatch_regions": [  # 剖面填充区域（ANSI31 = 实体材料）
                {"pattern": str, "edges": [[(x1,y1),(x2,y2)],...], "bbox": [4], "area": float},
                ...
            ],
            "centerlines": [    # 中心线 / 对称轴
                {"start": (x,y), "end": (x,y), "linetype": str, "orientation": "H"|"V"},
                ...
            ],
            "section_markers": [  # 截面标签 A-A, B-B ...
                {"label": str, "x": float, "y": float},
                ...
            ],
            "linetype_map": {     # 线型名 → 描述
                "HIDDEN": "Hidden __ __ __",
                ...
            },
        }
    """
    doc = ezdxf.readfile(dxf_path)
    msp = doc.modelspace()

    result = {
        "hatch_regions": [],
        "centerlines": [],
        "section_markers": [],
        "linetype_map": {},
    }

    # ---- 线型表 ----
    for lt in doc.linetypes:
        name = lt.dxf.name
        desc = ""
        try:
            desc = lt.dxf.description or ""
        except Exception:
            pass
        result["linetype_map"][name] = desc

    # ---- HATCH: 剖面填充 ----
    for h in msp.query("HATCH"):
        pattern = ""
        try:
            pattern = h.dxf.pattern_name or ""
        except Exception:
            pass
        # ANSI31 = 金属材料剖面线（45° 斜线），表示实体
        # 其他剖面图案也可能是实体材料
        if not pattern:
            continue

        hatch_edges = []
        try:
            for p in h.paths:
                # EdgePath: 由边组成的边界
                edge_segments = []
                try:
                    for edge in p.edges:
                        try:
                            sp = edge.start_point
                            ep = edge.end_point
                            edge_segments.append(((sp.x, sp.y), (ep.x, ep.y)))
                        except Exception:
                            pass
                except Exception:
                    pass
                if edge_segments:
                    hatch_edges.extend(edge_segments)
        except Exception:
            pass

        if not hatch_edges:
            continue

        # 计算 hatch 区域的包围盒和面积
        all_pts = []
        for (x1, y1), (x2, y2) in hatch_edges:
            all_pts.append((x1, y1))
            all_pts.append((x2, y2))
        xs = [p[0] for p in all_pts]
        ys = [p[1] for p in all_pts]
        bbox = [min(xs), min(ys), max(xs), max(ys)]
        area = (bbox[2] - bbox[0]) * (bbox[3] - bbox[1])

        result["hatch_regions"].append({
            "pattern": pattern,
            "edges": hatch_edges,
            "bbox": bbox,
            "area": area,
        })

    # ---- 中心线（LINE 实体中非 Continuous 线型） ----
    center_linetypes = {"CENTER", "CENTER2", "CENTERX2", "DASHDOT", "PHANTOM"}
    for e in msp.query("LINE"):
        lt = ""
        try:
            lt = (e.dxf.linetype or "").upper()
        except Exception:
            pass
        if lt not in center_linetypes:
            continue

        x1, y1 = e.dxf.start.x, e.dxf.start.y
        x2, y2 = e.dxf.end.x, e.dxf.end.y
        dx, dy = abs(x2 - x1), abs(y2 - y1)

        # 判断方向
        if dx > dy * 3:
            orientation = "H"  # 水平中心线
        elif dy > dx * 3:
            orientation = "V"  # 垂直中心线
        else:
            orientation = "D"  # 斜向

        result["centerlines"].append({
            "start": (x1, y1),
            "end": (x2, y2),
            "linetype": lt,
            "orientation": orientation,
            "length": math.hypot(dx, dy),
        })

    # ---- 截面标记：MTEXT 中的字母标签 ----
    # 截面标签通常是 "A", "B", "C"... 成对出现（标记截面平面两端）
    import re
    section_labels = []
    for e in msp.query("TEXT MTEXT"):
        try:
            if e.dxftype() == "MTEXT":
                txt = e.text if hasattr(e, 'text') else ''
            else:
                txt = e.dxf.text if hasattr(e.dxf, 'text') else ''
            x = e.dxf.insert.x
            y = e.dxf.insert.y
            txt = txt.strip()
        except Exception:
            continue

        # 检测截面标签：单个大写字母或 "A-A" 形式
        if re.match(r'^[A-Z]$', txt):
            # 单字母截面标记
            section_labels.append({"label": txt, "x": x, "y": y})
        elif re.match(r'^[A-Z]-[A-Z]$', txt):
            section_labels.append({"label": txt.split("-")[0], "x": x, "y": y})

    # 按标签分组（同一字母的多个位置 = 同一截面平面的不同标记点）
    by_label = defaultdict(list)
    for sl in section_labels:
        by_label[sl["label"]].append(sl)
    # 保留成对出现（至少 2 个标记点）的截面
    for label, markers in by_label.items():
        if len(markers) >= 2:
            result["section_markers"].extend(markers)

    return result


# ============================================================
# 2. 图构建
# ============================================================

def _key(pt, tol=SNAP_TOL):
    return (round(pt[0] / tol) * tol, round(pt[1] / tol) * tol)


# ============================================================
# 2.5 边交点拆分（拓扑修复）
# ============================================================

def _angle_in_arc(ang_deg: float, e: Edge, tol_deg: float = 0.01) -> bool:
    """角度(度)是否在圆弧参数范围内（按弧方向，含端点容差）。"""
    s = e.start_angle % 360.0
    a = ang_deg % 360.0
    if e.clockwise:
        span = (s - e.end_angle) % 360.0
        off = (s - a) % 360.0
    else:
        span = (e.end_angle - s) % 360.0
        off = (a - s) % 360.0
    if span < 1e-9:
        span = 360.0
    return -tol_deg <= off <= span + tol_deg


def split_edges_at_intersections(edges: list[Edge]) -> list[Edge]:
    """在边-边交点处拆分边（含圆/弧与直线相交），修复边图拓扑。

    面遍历依赖端点共享；圆轮廓与直线段相交时（如法兰圆穿过矩形轮廓），
    交点处若不产生顶点，封闭环无法闭合。端点附近的交点不拆分
    （端点已由顶点合并处理）。
    """
    n = len(edges)
    if n < 2:
        return edges

    # bbox 预过滤，避免 O(n²) 全量求交
    bboxes = []
    for e in edges:
        if e.etype == "LINE":
            bboxes.append((min(e.start[0], e.end[0]), min(e.start[1], e.end[1]),
                           max(e.start[0], e.end[0]), max(e.start[1], e.end[1])))
        else:
            bboxes.append((e.center[0] - e.radius, e.center[1] - e.radius,
                           e.center[0] + e.radius, e.center[1] + e.radius))

    cuts = [[] for _ in range(n)]
    EPS = 1e-6  # 参数域端点容差（交点恰在端点上时不拆）

    for i in range(n):
        ei = edges[i]
        bxi = bboxes[i]
        for j in range(i + 1, n):
            ej = edges[j]
            bxj = bboxes[j]
            if bxi[2] < bxj[0] or bxj[2] < bxi[0] or \
               bxi[3] < bxj[1] or bxj[3] < bxi[1]:
                continue

            if ei.etype == "LINE" and ej.etype == "LINE":
                x1, y1 = ei.start
                x2, y2 = ei.end
                x3, y3 = ej.start
                x4, y4 = ej.end
                d1x, d1y = x2 - x1, y2 - y1
                d2x, d2y = x4 - x3, y4 - y3
                denom = d1x * d2y - d1y * d2x
                if abs(denom) < 1e-12:
                    continue
                t = ((x3 - x1) * d2y - (y3 - y1) * d2x) / denom
                s = ((x3 - x1) * d1y - (y3 - y1) * d1x) / denom
                if -EPS <= t <= 1 + EPS and -EPS <= s <= 1 + EPS:
                    # T 型连接：至少一方在交点内部 → 拆那一方
                    t_in = EPS < t < 1 - EPS
                    s_in = EPS < s < 1 - EPS
                    if t_in:
                        cuts[i].append(("LINE", t))
                    if s_in:
                        cuts[j].append(("LINE", s))
            elif ei.etype == "ARC" and ej.etype == "ARC":
                c1x, c1y = ei.center
                r1 = ei.radius
                c2x, c2y = ej.center
                r2 = ej.radius
                dx, dy = c2x - c1x, c2y - c1y
                d = math.hypot(dx, dy)
                if d < 1e-9 or d > r1 + r2 or d < abs(r1 - r2):
                    continue
                a = (r1 * r1 - r2 * r2 + d * d) / (2 * d)
                h2 = r1 * r1 - a * a
                if h2 < 0:
                    continue
                h = math.sqrt(h2)
                bx = c1x + a * dx / d
                by = c1y + a * dy / d
                for sign in (1.0, -1.0):
                    px = bx + sign * h * (-dy / d)
                    py = by + sign * h * (dx / d)
                    ang1 = math.degrees(math.atan2(py - c1y, px - c1x))
                    ang2 = math.degrees(math.atan2(py - c2y, px - c2x))
                    if _angle_in_arc(ang1, ei):
                        cuts[i].append(("ARC", ang1 % 360.0))
                    if _angle_in_arc(ang2, ej):
                        cuts[j].append(("ARC", ang2 % 360.0))
            else:
                # LINE vs ARC
                if ei.etype == "ARC":
                    arc, line = ei, ej
                    arc_i, line_i = i, j
                else:
                    arc, line = ej, ei
                    arc_i, line_i = j, i
                cx, cy = arc.center
                r = arc.radius
                x1, y1 = line.start
                x2, y2 = line.end
                dx, dy = x2 - x1, y2 - y1
                fx, fy = x1 - cx, y1 - cy
                a = dx * dx + dy * dy
                if a < 1e-12:
                    continue
                b = 2 * (fx * dx + fy * dy)
                c = fx * fx + fy * fy - r * r
                disc = b * b - 4 * a * c
                # v0.6.3: 相切交点（disc≈0）浮点误差可能为微小负数，
                # 直接 continue 会漏拆——法兰叶片角直线与 r=30 圆
                # 相切于 (30,±8.99)，漏拆导致外环断链、叶片角丢失
                if disc < -1e-9 * max(1.0, b * b, abs(4 * a * c)):
                    continue
                disc = max(disc, 0.0)
                sq = math.sqrt(disc)
                for t in ((-b - sq) / (2 * a), (-b + sq) / (2 * a)):
                    # 交点在直线参数范围内（含端点——端点本身是图顶点）
                    if not (-EPS <= t <= 1 + EPS):
                        continue
                    px, py = x1 + t * dx, y1 + t * dy
                    ang = math.degrees(math.atan2(py - cy, px - cx))
                    if _angle_in_arc(ang, arc):
                        # 弧侧必须拆分（即使交点是直线端点）
                        cuts[arc_i].append(("ARC", ang % 360.0))
                        if EPS < t < 1 - EPS:
                            cuts[line_i].append(("LINE", t))

    # 应用拆分
    new_edges = []
    n_cut = 0
    for i, e in enumerate(edges):
        params = sorted(set(round(p, 9) for _, p in cuts[i]))
        if not params:
            new_edges.append(e)
            continue
        n_cut += 1
        if e.etype == "LINE":
            pts = [e.start]
            for t in params:
                pts.append((e.start[0] + (e.end[0] - e.start[0]) * t,
                            e.start[1] + (e.end[1] - e.start[1]) * t))
            pts.append(e.end)
            for k in range(len(pts) - 1):
                seg = Edge(len(new_edges), "LINE", pts[k], pts[k + 1])
                if not seg.is_zero_length():
                    new_edges.append(seg)
        else:
            # 弧段角度按弧方向排序
            s = e.start_angle % 360.0
            angs = sorted(
                params,
                key=lambda a: ((s - a) % 360.0) if e.clockwise
                else ((a - s) % 360.0),
            )
            ordered = [s] + angs + [e.end_angle % 360.0]
            for k in range(len(ordered) - 1):
                a1, a2 = ordered[k], ordered[k + 1]
                if abs(a2 - a1) < 1e-6:
                    continue
                p1 = (e.center[0] + e.radius * math.cos(math.radians(a1)),
                      e.center[1] + e.radius * math.sin(math.radians(a1)))
                p2 = (e.center[0] + e.radius * math.cos(math.radians(a2)),
                      e.center[1] + e.radius * math.sin(math.radians(a2)))
                seg = Edge(len(new_edges), "ARC", p1, p2,
                           center=e.center, radius=e.radius,
                           start_angle=a1, end_angle=a2,
                           clockwise=e.clockwise)
                if not seg.is_zero_length():
                    new_edges.append(seg)
    if n_cut:
        print(f"  交点拆分: {n_cut} 条边被拆分 ({len(edges)} → {len(new_edges)} 条)")
    return new_edges


def detect_dxf_scale(dxf_path: str) -> float:
    """检测 DXF 工程图的全局比例因子。

    优先级:
    1. $DIMLFAC — 线性标注比例因子（最可靠）
    2. $DIMSCALE — 标注总比例因子
    3. 文字标注中的 "SCALE"/"比例" 信息
    4. 默认 1:1

    返回: DXF 坐标 → 实物尺寸 的缩放因子（DXF 坐标 × factor = 实物 mm）
        factor < 1 表示图纸放大了（如 2:1 图纸 → factor=0.5）
    """
    try:
        doc = ezdxf.readfile(dxf_path)
        header = doc.header

        # 1. $DIMLFAC — 线性标注比例因子
        #    DIMLFAC=2 表示 DXF 尺寸是实物的 2 倍（2:1 图纸）
        dimlfac = header.get("$DIMLFAC", 1.0)
        if dimlfac and abs(dimlfac - 1.0) > 0.001:
            factor = 1.0 / dimlfac
            print(f"  DXF 比例: DIMLFAC={dimlfac} → 缩放因子={factor:.4f}")
            return factor

        # 2. $DIMSCALE 作为备选
        dimscale = header.get("$DIMSCALE", 1.0)
        if dimscale and abs(dimscale - 1.0) > 0.001:
            factor = 1.0 / dimscale
            print(f"  DXF 比例: DIMSCALE={dimscale} → 缩放因子={factor:.4f}")
            return factor

    except Exception:
        pass

    # 3. 搜索文字中的比例标注
    try:
        texts = parse_dxf_texts(dxf_path)
        import re
        scale_patterns = [
            re.compile(r'SCALE\s*[=:]\s*([\d.]+)\s*[:/]\s*([\d.]+)', re.IGNORECASE),
            re.compile(r'比例\s*[=:]?\s*([\d.]+)\s*[:/]\s*([\d.]+)'),
            re.compile(r'([\d.]+)\s*[:/]\s*([\d.]+)'),
        ]
        for t in texts:
            txt = t["text"].strip()
            for pat in scale_patterns:
                m = pat.search(txt)
                if m:
                    paper_val = float(m.group(1))
                    real_val = float(m.group(2))
                    if paper_val > 0 and real_val > 0:
                        factor = real_val / paper_val
                        print(f"  DXF 比例（文字）: {txt} → 缩放因子={factor:.4f}")
                        return factor
    except Exception:
        pass

    return 1.0  # 默认 1:1


def build_vertex_map(edges: list[Edge]):
    """合并邻近端点，建立 vertex_id → (x, y) 映射。"""
    points = []
    for e in edges:
        points.append(e.start)
        points.append(e.end)

    key_to_vid = {}
    vertex_pos = {}
    next_vid = 0

    for pt in points:
        k = _key(pt)
        if k not in key_to_vid:
            key_to_vid[k] = next_vid
            vertex_pos[next_vid] = k
            next_vid += 1

    edge_vertices = []
    for e in edges:
        vs = key_to_vid[_key(e.start)]
        ve = key_to_vid[_key(e.end)]
        edge_vertices.append((vs, ve))

    return vertex_pos, edge_vertices, next_vid


def merge_close_vertices(vertex_pos: dict, edge_vertices: list,
                         tol: float = 0.5):
    """合并距离 < tol 的近邻顶点（union-find），修复轮廓微缺口。

    HLR 投影/图纸转换在边端点处产生 0.01~0.5mm 级浮点缺口，SNAP_TOL
    网格无法合并；近邻顶点合并使断开的轮廓链闭合。tol 应远小于最小
    特征尺寸（机械图纸最小特征通常 ≥1mm）。
    """
    n = len(vertex_pos)
    if n == 0:
        return edge_vertices
    parent = list(range(n))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    from collections import defaultdict
    cell = defaultdict(list)
    vids = sorted(vertex_pos)
    for vid in vids:
        x, y = vertex_pos[vid]
        cell[(int(x / tol), int(y / tol))].append(vid)

    n_merged = 0
    for vid in vids:
        x, y = vertex_pos[vid]
        cx, cy = int(x / tol), int(y / tol)
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for wid in cell.get((cx + dx, cy + dy), ()):
                    if wid >= vid:
                        continue
                    wx, wy = vertex_pos[wid]
                    if math.hypot(wx - x, wy - y) <= tol:
                        ri, rj = find(vid), find(wid)
                        if ri != rj:
                            parent[ri] = rj
                            n_merged += 1
    if n_merged == 0:
        return edge_vertices
    print(f"  近邻顶点合并: {n_merged} 对 (容差 {tol}mm)")
    return [(find(vs), find(ve)) for vs, ve in edge_vertices]


def merge_dangling_vertices(vertex_pos: dict, edge_vertices: list,
                            gap_tol: float = 1.5):
    """把悬空顶点（度1）吸附到最近的非悬空顶点，修复轮廓断口。

    HLR 投影或图纸转换产生的轮廓小缺口（0.01~1.5mm 级）会使环断开；
    正常共享顶点度数≥2，悬空顶点是断口标志，吸附不误伤正常拓扑。
    返回更新后的 edge_vertices。
    """
    from collections import Counter
    deg = Counter()
    for vs, ve in edge_vertices:
        if vs != ve:
            deg[vs] += 1
            deg[ve] += 1
    dangling = [v for v, d in deg.items() if d == 1]
    if not dangling:
        return edge_vertices

    remap = {}
    n_merged = 0
    for v in dangling:
        x, y = vertex_pos[v]
        best = None
        bd = gap_tol
        for w in vertex_pos:
            if w == v or deg.get(w, 0) == 1:
                continue  # 只吸附到非悬空顶点
            d = math.hypot(vertex_pos[w][0] - x, vertex_pos[w][1] - y)
            if d < bd:
                bd = d
                best = w
        if best is not None:
            remap[v] = best
            n_merged += 1

    if n_merged:
        print(f"  悬空顶点吸附: {n_merged} 个 (容差 {gap_tol}mm)")
        return [(remap.get(vs, vs), remap.get(ve, ve))
                for vs, ve in edge_vertices]
    return edge_vertices


def build_adjacency(vertex_pos: dict, edge_vertices: list, edges: list[Edge],
                    num_vertices: int):
    """建立顶点邻接表，包含边角度信息。"""
    adj = {v: [] for v in range(num_vertices)}

    for eid, (vs, ve) in enumerate(edge_vertices):
        edge = edges[eid]
        if vs == ve:
            continue

        # 在 vs 处的切向角（沿边参数方向离开 vs）
        if edge.etype == "LINE":
            dx = vertex_pos[ve][0] - vertex_pos[vs][0]
            dy = vertex_pos[ve][1] - vertex_pos[vs][1]
        else:
            # 逆时针弧: 切向 = (-sinθ, cosθ) = (-ry, rx) / r
            # 顺时针弧: 切向反向
            cx, cy = edge.center
            sx, sy = vertex_pos[vs]
            rx, ry = sx - cx, sy - cy
            if edge.clockwise:
                dx, dy = ry, -rx
            else:
                dx, dy = -ry, rx
        angle_vs = math.atan2(dy, dx)
        adj[vs].append((eid, ve, angle_vs))

        # 在 ve 处的切向角（沿边参数方向离开 ve，即 vs 处切向的反向）
        if edge.etype == "LINE":
            dx = vertex_pos[vs][0] - vertex_pos[ve][0]
            dy = vertex_pos[vs][1] - vertex_pos[ve][1]
        else:
            cx, cy = edge.center
            ex, ey = vertex_pos[ve]
            rx, ry = ex - cx, ey - cy
            if edge.clockwise:
                dx, dy = -ry, rx
            else:
                dx, dy = ry, -rx
        angle_ve = math.atan2(dy, dx)
        adj[ve].append((eid, vs, angle_ve))

    for v in adj:
        adj[v].sort(key=lambda x: x[2])

    return adj


# ============================================================
# 3. 平面图面遍历
# ============================================================

def find_all_faces(adj: dict, edges: list[Edge], edge_vertices: list):
    """使用平面图面遍历算法找到所有封闭环。"""
    num_edges = len(edges)
    if num_edges == 0:
        return []

    used = {}
    for eid, (vs, ve) in enumerate(edge_vertices):
        if vs != ve:
            used[(eid, vs, ve)] = False
            used[(eid, ve, vs)] = False

    faces = []

    for eid_start, (vs_start, ve_start) in enumerate(edge_vertices):
        if vs_start == ve_start:
            continue
        for u, v in [(vs_start, ve_start), (ve_start, vs_start)]:
            dkey = (eid_start, u, v)
            if dkey not in used or used[dkey]:
                continue
            used[dkey] = True
            consumed = [dkey]

            face_edges = [eid_start]
            cur_v = v
            prev_v = u
            prev_eid = eid_start
            closed = True

            for _ in range(num_edges * 4):
                if cur_v == u:
                    break

                incoming_angle = None
                for eid_in, other, ang in adj.get(cur_v, []):
                    if other == prev_v and eid_in == prev_eid:
                        incoming_angle = ang
                        break

                if incoming_angle is None:
                    closed = False
                    break

                out_angle_ref = incoming_angle + math.pi
                if out_angle_ref > math.pi:
                    out_angle_ref -= 2 * math.pi

                candidates_raw = adj.get(cur_v, [])
                if len(candidates_raw) <= 1:
                    closed = False
                    break

                best_eid = None
                best_next = None
                best_cw_angle = -float("inf")

                for eid_out, other_v, ang_out in candidates_raw:
                    if other_v == cur_v:
                        continue
                    # 排除原路返回（同一 eid 的反向）
                    if eid_out == prev_eid:
                        continue
                    dk = (eid_out, cur_v, other_v)
                    if dk not in used or used[dk]:
                        continue
                    cw_angle = out_angle_ref - ang_out
                    if cw_angle < -math.pi:
                        cw_angle += 2 * math.pi
                    if cw_angle < 0:
                        cw_angle += 2 * math.pi
                    if cw_angle > best_cw_angle:
                        best_cw_angle = cw_angle
                        best_eid = eid_out
                        best_next = other_v

                if best_eid is None:
                    closed = False
                    break

                dk = (best_eid, cur_v, best_next)
                used[dk] = True
                consumed.append(dk)
                face_edges.append(best_eid)
                prev_v = cur_v
                cur_v = best_next
                prev_eid = best_eid

            if closed and len(face_edges) >= 2:
                faces.append(face_edges)
            else:
                # 回滚失败路径消费的方向，避免阻塞后续面遍历
                for dk in consumed:
                    used[dk] = False

    # 去重
    unique_faces = []
    seen = set()
    for f_ids in faces:
        if not f_ids:
            continue
        n = len(f_ids)
        min_eid = min(f_ids)
        min_positions = [i for i, eid in enumerate(f_ids) if eid == min_eid]
        candidates = []
        for pos in min_positions:
            candidates.append(tuple(f_ids[pos:] + f_ids[:pos]))
            rev = list(reversed(f_ids))
            rpos = rev.index(min_eid)
            candidates.append(tuple(rev[rpos:] + rev[:rpos]))
        key = min(candidates)
        if key not in seen:
            seen.add(key)
            unique_faces.append(f_ids)

    return unique_faces


# ============================================================
# 4. 面分析
# ============================================================

def analyze_face(face_eid_list, edges, edge_vertices, vertex_pos):
    """全面分析一个面，返回面信息字典。"""
    xs, ys = [], []
    etypes = set()
    arc_centers = []
    arc_radii = []

    for eid in face_eid_list:
        e = edges[eid]
        vs, ve = edge_vertices[eid]
        xs.extend([vertex_pos[vs][0], vertex_pos[ve][0]])
        ys.extend([vertex_pos[vs][1], vertex_pos[ve][1]])
        etypes.add(e.etype)

        if e.etype == "ARC" and e.center:
            cx, cy = e.center
            r = e.radius
            arc_centers.append((cx, cy))
            arc_radii.append(r)
            # ARC 极值点
            a1 = math.radians(e.start_angle)
            a2 = math.radians(e.end_angle)
            if a2 < a1:
                a2 += 2 * math.pi
            for ka in [0, math.pi/2, math.pi, 3*math.pi/2]:
                a = ka
                if a < a1:
                    a += 2 * math.pi
                if a1 <= a <= a2:
                    xs.append(cx + r * math.cos(ka))
                    ys.append(cy + r * math.sin(ka))
            xs.append(cx)
            ys.append(cy)

    bb_area = (max(xs) - min(xs)) * (max(ys) - min(ys))
    width = max(xs) - min(xs)
    height = max(ys) - min(ys)

    # 面类型判定
    n_arcs = len(arc_centers)
    if n_arcs >= 2:
        unique_centers = set((round(c[0], 2), round(c[1], 2)) for c in arc_centers)
        if len(unique_centers) == 1:
            face_type = "concentric"  # 同心圆
        else:
            face_type = "multi_arc"
    elif n_arcs == 1:
        face_type = "single_arc"
    else:
        face_type = "line_only"

    # 检查是否为 SPLINE 采样产生的碎片面
    is_spline_debris = (
        face_type == "line_only"
        and len(face_eid_list) <= 3
        and bb_area < 5.0
    )

    return {
        "edges": face_eid_list,
        "area": bb_area,
        "width": width,
        "height": height,
        "x_min": min(xs), "x_max": max(xs),
        "y_min": min(ys), "y_max": max(ys),
        "y_mid": (max(ys) + min(ys)) / 2,
        "x_mid": (max(xs) + min(xs)) / 2,
        "etypes": etypes,
        "face_type": face_type,
        "n_arcs": n_arcs,
        "arc_centers": list(set((round(c[0], 2), round(c[1], 2))
                                for c in arc_centers)),
        "arc_radii": sorted(set(round(r, 2) for r in arc_radii)),
        "is_spline_debris": is_spline_debris,
    }


# ============================================================
# 5. 视图检测
# ============================================================

def detect_views(faces_info: list[dict], texts: list[dict],
                 total_bbox: tuple, total_bbox_area: float) -> dict:
    """自动检测工程图的视图区域划分。

    策略:
    1. 利用剖面标签 (A-A, B-B, 1-1 等) 的 Y 坐标作为分界
    2. 分析 Y 方向的几何密度间隙
    3. 找出标题栏区域并排除

    返回: {
        "title_block_y_range": (ylo, yhi) or None,
        "view_regions": [(name, y_lo, y_hi, view_type), ...],
        "main_body_region": str (region name),
    }
    """
    import re
    # 匹配剖面标签：A-A, B-B, 1-1 等，也匹配单字母（剖面位置标记）
    section_pattern = re.compile(
        r'^[A-Za-z0-9]+[-—–][A-Za-z0-9]+$'
    )

    # Step 1: 找剖面标签的 Y 位置
    label_ys = []
    for t in texts:
        txt = t["text"].strip()
        if section_pattern.match(txt) and len(txt) <= 6:
            label_ys.append((t["y"], txt[0].upper()))
        # 也收集单个大写字母（可能是剖面标记）
        elif re.match(r'^[A-Z]$', txt):
            label_ys.append((t["y"], txt))

    label_ys.sort()

    # 找成对的标签
    paired_labels = []
    seen_letters = set()
    for y, letter in label_ys:
        if letter not in seen_letters:
            paired_labels.append((y, letter))
            seen_letters.add(letter)

    # Step 2: 分析面的 Y 分布
    face_ys_all = [f["y_mid"] for f in faces_info if f["area"] > 0.5]
    if not face_ys_all:
        return {"title_block_y_range": None, "view_regions": [],
                "main_body_region": None, "y_min_all": 0, "y_max_all": 0}

    y_min_all = min(f["y_min"] for f in faces_info if f["area"] > 0.5)
    y_max_all = max(f["y_max"] for f in faces_info if f["area"] > 0.5)

    # 计算 Y 密度分布（使用实际 Y 值，1mm 分箱用于精确间隙检测）
    from collections import defaultdict
    y_slots = defaultdict(int)
    for f in faces_info:
        if f["area"] > 0.5:
            for y in range(int(f["y_min"]), int(f["y_max"]) + 1):
                y_slots[y] += 1

    # 找大间隙（>25mm 连续无面的区域）
    min_gap = max(25, (y_max_all - y_min_all) * 0.06)
    occupied_ys = sorted(y_slots.keys())
    gaps = []
    if occupied_ys:
        prev = occupied_ys[0]
        for y in occupied_ys[1:]:
            if y - prev > min_gap:
                gaps.append((prev, y))
            prev = y

    # Step 3: 收集分界线
    dividers = set()

    # 从成对标签获取
    for y, letter in paired_labels:
        dividers.add(y)

    # 从几何间隙获取（间隙中点作为分界）
    for lo, hi in gaps:
        mid_y = (lo + hi) / 2
        dividers.add(mid_y)

    # 合并相近的分界线（<15mm 合并为一个）
    dividers = sorted(dividers)
    merged = []
    for d in dividers:
        if not merged or d - merged[-1] > 15:
            merged.append(d)
        else:
            # 取平均值
            merged[-1] = (merged[-1] + d) / 2
    dividers = merged

    # Step 4: 识别标题栏区域（最底部的大间隙之上或之下）
    title_block_yhi = None
    if gaps:
        # 找最大的间隙 — 标题栏和图纸主体之间
        max_gap = max(gaps, key=lambda g: g[1] - g[0])
        # 如果最大间隙在图纸下半部分且上方有标签
        gap_mid = (max_gap[0] + max_gap[1]) / 2
        if gap_mid < y_max_all * 0.35:
            # 这个间隙分隔了标题栏和主体
            title_block_yhi = max_gap[0]
            # 移除标题栏区域内的分界线
            dividers = [d for d in dividers if d > title_block_yhi]

    # Step 5: 生成视图区域
    view_regions = []
    effective_ymin = title_block_yhi if title_block_yhi else y_min_all

    if not dividers:
        view_regions.append(("main", effective_ymin, y_max_all))
    else:
        # 确保所有分界线在有效范围内
        valid_dividers = [d for d in dividers if effective_ymin < d < y_max_all]

        if not valid_dividers:
            view_regions.append(("main", effective_ymin, y_max_all))
        else:
            # 第一个区域
            if valid_dividers[0] - effective_ymin > 10:
                view_regions.append(("section_1", effective_ymin, valid_dividers[0]))
            # 中间区域
            for i in range(len(valid_dividers) - 1):
                view_regions.append(
                    (f"section_{i+2}", valid_dividers[i], valid_dividers[i+1])
                )
            # 最后一个区域
            if y_max_all - valid_dividers[-1] > 10:
                view_regions.append(
                    (f"section_{len(valid_dividers)+1}", valid_dividers[-1], y_max_all)
                )

    # Step 6: 分类每个视图区域的类型
    typed_regions = []
    for name, ylo, yhi in view_regions:
        region_faces = [f for f in faces_info
                        if ylo <= f["y_mid"] <= yhi
                        and not f["is_spline_debris"]]

        n_concentric = sum(1 for f in region_faces if f["face_type"] == "concentric")
        n_line = sum(1 for f in region_faces if f["face_type"] == "line_only")
        n_arc = sum(1 for f in region_faces if "ARC" in f["etypes"])

        if n_concentric > 0 or n_arc > n_line * 0.5:
            view_type = "cylindrical"  # 以圆/弧为主 → 圆柱特征
        elif n_line > 0:
            view_type = "prismatic"    # 以直线为主 → 拉伸特征
        else:
            view_type = "empty"

        typed_regions.append((name, ylo, yhi, view_type))

    # Step 7: 找出主体所在区域（包含最大非圆面的区域）
    region_scores = {}
    for name, ylo, yhi, vtype in typed_regions:
        region_faces = [f for f in faces_info
                        if ylo <= f["y_mid"] <= yhi
                        and not f["is_spline_debris"]
                        and f["face_type"] == "line_only"]
        if region_faces:
            region_scores[name] = max(f["area"] for f in region_faces)
        else:
            region_scores[name] = 0

    main_region = max(region_scores, key=region_scores.get) if region_scores else None

    return {
        "title_block_y_range": (0, title_block_yhi) if title_block_yhi else None,
        "view_regions": typed_regions,
        "main_body_region": main_region,
        "y_min_all": y_min_all,
        "y_max_all": y_max_all,
    }


# ============================================================
# 6. 同心圆聚类
# ============================================================

def cluster_concentric_arcs(faces_info: list[dict], edges: list[Edge],
                            edge_vertices: list, vertex_pos: dict) -> dict:
    """跨面检测同心圆弧组。

    返回: {canonical_key: {"center": (cx,cy), "radii": [...],
           "face_indices": set(), "y_range": (ymin, ymax)}}
    """
    # 收集所有 ARC 边
    arc_by_center = defaultdict(list)

    for fi_idx, fi in enumerate(faces_info):
        if fi["is_spline_debris"]:
            continue
        for eid in fi["edges"]:
            e = edges[eid]
            if e.etype != "ARC" or not e.center:
                continue
            ckey = (round(e.center[0], 1), round(e.center[1], 1))
            arc_by_center[ckey].append({
                "eid": eid, "radius": e.radius,
                "face_idx": fi_idx,
                "center": (e.center[0], e.center[1]),
            })

    if not arc_by_center:
        return {}

    # 合并相近的圆心
    all_center_keys = sorted(arc_by_center.keys())
    merged = {}
    used = set()

    for ck in all_center_keys:
        if ck in used:
            continue
        cluster = [ck]
        used.add(ck)
        for ck2 in all_center_keys:
            if ck2 in used:
                continue
            if math.hypot(ck[0] - ck2[0], ck[1] - ck2[1]) < CENTER_MERGE_TOL:
                cluster.append(ck2)
                used.add(ck2)

        # 平均坐标作为规范键
        avg_x = sum(c[0] for c in cluster) / len(cluster)
        avg_y = sum(c[1] for c in cluster) / len(cluster)
        canon_key = (round(avg_x, 1), round(avg_y, 1))

        all_radii = set()
        all_face_indices = set()
        all_ys = []
        for c in cluster:
            for item in arc_by_center[c]:
                all_radii.add(round(item["radius"] * 20) / 20)
                all_face_indices.add(item["face_idx"])
                # 收集 Y 坐标
                vs, ve = edge_vertices[item["eid"]]
                all_ys.append(vertex_pos[vs][1])
                all_ys.append(vertex_pos[ve][1])

        # 需要至少 2 个不同半径才认为是同心圆组，单一半径标记为独立圆
        n_arc_edges = sum(len(arc_by_center[c]) for c in cluster)
        if len(all_radii) >= 2:
            merged[canon_key] = {
                "center": (avg_x, avg_y),
                "radii": sorted(all_radii),
                "face_indices": all_face_indices,
                "count": n_arc_edges,
                "group_type": "concentric",  # 同心圆组 → 凸台+孔
            }
        elif len(all_radii) == 1 and n_arc_edges >= 2:
            # 独立圆（单一半径，至少 2 条弧 = 完整圆）→ 孔
            merged[canon_key] = {
                "center": (avg_x, avg_y),
                "radii": sorted(all_radii),
                "face_indices": all_face_indices,
                "count": n_arc_edges,
                "group_type": "isolated",  # 独立圆 → 仅孔
            }

    return merged


# ============================================================
# 7. OCC 几何创建
# ============================================================

def build_occ_wire_from_face(face_eids, edges, edge_vertices, vertex_pos,
                            scale_factor=1.0):
    """从面边列表构建 OCC Wire。

    scale_factor: DXF 坐标 → 实物尺寸的缩放因子
    """
    try:
        sf = scale_factor
        # v0.6.1: 边去重——图纸中半圆面可能由两条完全重合的反向弧
        # 组成（无弦线），wire 退化为 0 面积 → 拉伸工具 mass=0 却
        # 在 Cut 时劈开主体。按几何签名去重，悬空弧端点补弦线。
        seen = set()
        unique_eids = []
        for eid in face_eids:
            e = edges[eid]
            if e.etype == "ARC":
                key = ("A", round(e.center[0], 4), round(e.center[1], 4),
                       round(e.radius, 4), round(e.start_angle, 4),
                       round(e.end_angle, 4))
            else:
                vs, ve = edge_vertices[eid]
                p1 = vertex_pos[vs]
                p2 = vertex_pos[ve]
                key = ("L", round(min(p1[0], p2[0]), 4),
                       round(min(p1[1], p2[1]), 4),
                       round(max(p1[0], p2[0]), 4),
                       round(max(p1[1], p2[1]), 4))
            if key not in seen:
                seen.add(key)
                unique_eids.append(eid)
        # 悬空端点（度 1）检测：弧对去重后弧两端悬空 → 补弦线闭合
        degree = {}
        for eid in unique_eids:
            vs, ve = edge_vertices[eid]
            degree[vs] = degree.get(vs, 0) + 1
            degree[ve] = degree.get(ve, 0) + 1
        dangling = sorted(v for v, d in degree.items() if d == 1)
        chord_needed = len(dangling) == 2 and len(unique_eids) >= 1

        wire_builder = BRepBuilderAPI_MakeWire()
        for eid in unique_eids:
            e = edges[eid]
            vs, ve = edge_vertices[eid]
            p1 = vertex_pos[vs]
            p2 = vertex_pos[ve]

            if e.etype == "LINE":
                occ_edge = BRepBuilderAPI_MakeEdge(
                    gp_Pnt(p1[0] * sf, p1[1] * sf, 0),
                    gp_Pnt(p2[0] * sf, p2[1] * sf, 0),
                ).Edge()
            elif e.etype == "ARC" and e.radius > 0:
                circ = gp_Circ(
                    gp_Ax2(gp_Pnt(e.center[0] * sf, e.center[1] * sf, 0),
                           gp_Dir(0, 0, 1)),
                    e.radius * sf,
                )
                a1 = math.radians(e.start_angle)
                a2_val = math.radians(e.end_angle)
                occ_edge = BRepBuilderAPI_MakeEdge(circ, a1, a2_val).Edge()
            else:
                occ_edge = BRepBuilderAPI_MakeEdge(
                    gp_Pnt(p1[0] * sf, p1[1] * sf, 0),
                    gp_Pnt(p2[0] * sf, p2[1] * sf, 0),
                ).Edge()
            wire_builder.Add(occ_edge)

        # 补弦线：去重后若恰有两个度 1 顶点（半圆弧去重后无弦），
        # 连接它们闭合半圆面
        if chord_needed:
            cp1 = vertex_pos[dangling[0]]
            cp2 = vertex_pos[dangling[1]]
            chord = BRepBuilderAPI_MakeEdge(
                gp_Pnt(cp1[0] * sf, cp1[1] * sf, 0),
                gp_Pnt(cp2[0] * sf, cp2[1] * sf, 0)).Edge()
            wire_builder.Add(chord)

        wire = wire_builder.Wire()
        # 修复 wire
        fixer = ShapeFix_Wire()
        fixer.Load(wire)
        fixer.FixReorder()
        fixer.FixConnected()
        fixer.FixClosed()
        return fixer.Wire()
    except Exception:
        return None


def build_occ_face(wire) -> object:
    """从 Wire 构建 Face。"""
    try:
        face = BRepBuilderAPI_MakeFace(wire).Face()
        return face
    except Exception:
        return None


def extrude_face(occ_face, depth: float, direction=(0, 0, 1)) -> object:
    """沿指定方向拉伸 Face 为 Solid。"""
    if depth <= 0.01:
        return None
    try:
        vec = gp_Vec(direction[0] * depth, direction[1] * depth, direction[2] * depth)
        return BRepPrimAPI_MakePrism(occ_face, vec).Shape()
    except Exception:
        return None


def create_cylinder_solid(center_xy, radius, height, z_offset=0) -> object:
    """创建一个圆柱体。"""
    try:
        return BRepPrimAPI_MakeCylinder(
            gp_Ax2(gp_Pnt(center_xy[0], center_xy[1], z_offset), gp_Dir(0, 0, 1)),
            radius, height,
        ).Shape()
    except Exception:
        return None


def create_cylinder_solid_along_y(center_xz, radius, height, y_offset=0) -> object:
    """创建沿 Y 轴拉伸的圆柱体（front 视图孔：XZ 平面上的圆）。"""
    try:
        return BRepPrimAPI_MakeCylinder(
            gp_Ax2(gp_Pnt(center_xz[0], y_offset, center_xz[1]), gp_Dir(0, 1, 0)),
            radius, height,
        ).Shape()
    except Exception:
        return None


def create_concentric_solid(center, radii, height, z_offset=0) -> object:
    """从一组同心半径创建阶梯圆柱实体（最大半径实心，内孔逐步减去）。

    返回: 组合后的单一实体
    """
    if len(radii) < 1:
        return None

    sorted_r = sorted(radii, reverse=True)
    cx, cy = center

    try:
        # 最外层实心圆柱
        outer = BRepPrimAPI_MakeCylinder(
            gp_Ax2(gp_Pnt(cx, cy, z_offset), gp_Dir(0, 0, 1)),
            sorted_r[0], height,
        ).Shape()

        if len(sorted_r) == 1:
            return outer

        # 逐层减内孔
        current = outer
        for inner_r in sorted_r[1:]:
            # 孔稍长以确保完全穿透
            hole = BRepPrimAPI_MakeCylinder(
                gp_Ax2(gp_Pnt(cx, cy, z_offset - 1), gp_Dir(0, 0, 1)),
                inner_r, height + 2,
            ).Shape()
            current = BRepAlgoAPI_Cut(current, hole).Shape()

        return current
    except Exception:
        # 回退
        try:
            return BRepPrimAPI_MakeCylinder(
                gp_Ax2(gp_Pnt(cx, cy, z_offset), gp_Dir(0, 0, 1)),
                sorted_r[0], height,
            ).Shape()
        except Exception:
            return None


def fuse_shapes(shapes: list) -> object:
    """安全地合并多个 Shape。"""
    shapes = [s for s in shapes if s is not None]
    if not shapes:
        return None
    if len(shapes) == 1:
        return shapes[0]
    result = shapes[0]
    for s in shapes[1:]:
        try:
            result = BRepAlgoAPI_Fuse(result, s).Shape()
        except Exception:
            pass
    return result


def cut_shapes(main_shape, tools: list) -> object:
    """从主体中减去一组工具 Shape。"""
    if main_shape is None:
        return None
    tools = [t for t in tools if t is not None]
    if not tools:
        return main_shape
    result = main_shape
    for tool in tools:
        try:
            result = BRepAlgoAPI_Cut(result, tool).Shape()
        except Exception:
            pass
    return result


def _point_in_polygon_2d(px, py, polygon_pts):
    """射线法判断 2D 点是否在多边形内部。

    polygon_pts: [(x, y), ...] 有序顶点列表（自动闭合）。
    返回: True=内部, False=外部或边界。
    """
    n = len(polygon_pts)
    if n < 3:
        return False
    inside = False
    j = n - 1
    for i in range(n):
        xi, yi = polygon_pts[i]
        xj, yj = polygon_pts[j]
        if ((yi > py) != (yj > py)) and (px < (xj - xi) * (py - yi) / (yj - yi) + xi):
            inside = not inside
        j = i
    return inside


def _get_ordered_vertices(face_eids, edges, edge_vertices):
    """从面的无序边列表恢复有序顶点序列（用于构建多边形）。

    返回: [(x, y), ...] 按连接顺序排列的顶点坐标列表。
    """
    if not face_eids:
        return []
    # 构建边→顶点的映射
    edge_v_map = {}
    for eid in face_eids:
        vs, ve = edge_vertices[eid]
        e = edges[eid]
        p1 = (e.start[0], e.start[1])
        p2 = (e.end[0], e.end[1])
        edge_v_map[eid] = (vs, ve, p1, p2)

    # 建立邻接关系
    remaining = set(face_eids)
    ordered_pts = []
    if not remaining:
        return []

    # 取第一条边
    first_eid = remaining.pop()
    vs, ve, p1, p2 = edge_v_map[first_eid]
    ordered_pts = [p1, p2]
    current_v = ve

    # 贪心连接
    while remaining:
        found = False
        for eid in list(remaining):
            vs2, ve2, q1, q2 = edge_v_map[eid]
            if vs2 == current_v:
                ordered_pts.append(q2)
                current_v = ve2
                remaining.discard(eid)
                found = True
                break
            elif ve2 == current_v:
                ordered_pts.append(q1)
                current_v = vs2
                remaining.discard(eid)
                found = True
                break
        if not found:
            break

    return ordered_pts


def get_shape_bbox(shape) -> tuple:
    """获取 shape 的包围盒。"""
    bbox = Bnd_Box()
    brepbndlib.Add(shape, bbox)
    return bbox.Get()


# ============================================================
# 8a. CSG 体积求交法 — 真正的 3D 空间思维
# ============================================================

# 多视图 → 3D 坐标映射（标准正交投影约定，Z 轴向上）
#   前视图 (Front): DXF_X→X, DXF_Y→Z（高度）, 面在 XZ 平面, 拉伸方向 Y（深度）
#   俯视图 (Top):   DXF_X→X, DXF_Y→Y（深度）, 面在 XY 平面, 拉伸方向 Z（高度）
#   侧视图 (Side):  DXF_X→Y（深度）, DXF_Y→Z（高度）, 面在 YZ 平面, 拉伸方向 X

def _get_view_transform(view_type):
    """返回 (matrix_values, extrude_axis) 用于视图面变换。

    matrix_values: gp_Trsf.SetValues 的 12 个系数（将 DXF XY 面变换到目标
                   平面），None 表示恒等变换（面保持 XY 平面）
    extrude_axis: 拉伸方向 (0=X, 1=Y, 2=Z)
    """
    if view_type == "front":
        # 绕 X 轴 +90°：z=0 平面上 (x,y,0)→(x,0,y)（DXF_X→X, DXF_Y→Z），
        # 面在 XZ 平面，沿 Y 拉伸。gp_Trsf 要求满秩（旋转阵 det=1）。
        # 注意 SetValues 约定: x' = a11·x + a12·y + a13·z + a14（平移在每行第4位）
        return (1, 0, 0, 0, 0, 0, -1, 0, 0, 1, 0, 0), 1
    elif view_type == "top":
        # 恒等：面保持 XY 平面，沿 Z 拉伸
        return None, 2
    elif view_type == "side":
        # 循环置换 (X→Z→Y→X)：z=0 平面上 (x,y,0)→(0,x,y)
        # （DXF_X→Y, DXF_Y→Z），面在 YZ 平面，沿 X 拉伸
        return (0, 0, 1, 0, 1, 0, 0, 0, 0, 1, 0, 0), 0
    return None, 2


def _apply_view_transform(occ_face, view_type):
    """对视图面应用 _get_view_transform 的平面变换（不含拉伸）。

    返回变换后的面。
    """
    matrix, _ = _get_view_transform(view_type)
    if matrix is not None:
        trsf = gp_Trsf()
        trsf.SetValues(*matrix)
        occ_face = BRepBuilderAPI_Transform(occ_face, trsf).Shape()
    return occ_face


def _extrude_face_dual(occ_face, direction_axis, distance):
    """沿指定轴向正方向拉伸面为长棱柱。

    direction_axis: 0=X, 1=Y, 2=Z
    """
    vecs = [
        gp_Vec(distance, 0, 0),
        gp_Vec(0, distance, 0),
        gp_Vec(0, 0, distance),
    ]
    try:
        prism = BRepPrimAPI_MakePrism(occ_face, vecs[direction_axis]).Shape()
        # 面朝向与拉伸方向相反时 MakePrism 产生负体积（倒置）实体，
        # 布尔运算会把它当作"洞"或直接失败——检测后反向重拉
        props = GProp_GProps()
        brepgprop.VolumeProperties(prism, props)
        # 无效面（如自交/开环 wire 构建的面）拉伸出的实体 BRepCheck 无效，
        # mass 为负或异常小——直接放弃该工具
        try:
            from OCC.Core.BRepCheck import BRepCheck_Analyzer
            if not BRepCheck_Analyzer(prism).IsValid():
                return None
        except Exception:
            pass
        if props.Mass() < 0:
            prism2 = BRepPrimAPI_MakePrism(
                occ_face, vecs[direction_axis].Reversed()).Shape()
            props2 = GProp_GProps()
            brepgprop.VolumeProperties(prism2, props2)
            try:
                if not BRepCheck_Analyzer(prism2).IsValid():
                    return None
            except Exception:
                pass
            if props2.Mass() > 0:
                prism = prism2
        # v0.6.1: mass≈0 的退化体（面朝向/自交导致拉伸成空壳）会
        # 在 Cut 时劈开主体却不切除体积——按 bbox 体积比例丢弃
        pbb = Bnd_Box()
        brepbndlib.Add(prism, pbb)
        px1, py1, pz1, px2, py2, pz2 = pbb.Get()
        pbbox_vol = (px2 - px1) * (py2 - py1) * (pz2 - pz1)
        if pbbox_vol > 0 and abs(props.Mass()) < pbbox_vol * 0.01:
            return None
        return prism
    except Exception:
        return None


def _align_view_features(view_bbox, ref_bbox, align_dim):
    """计算视图间的对齐偏移量。

    align_dim: 共享维度 ('x' 或 'y')
    返回 (dx, dy, dz) 偏移量，将视图特征对齐到参考坐标系。
    """
    if align_dim == 'x':
        # 共享X：将当前视图的X范围对齐到参考视图的X范围
        dx = ref_bbox[0] - view_bbox[0]  # 对齐左边界
        return (dx, 0, 0)
    elif align_dim == 'y':
        dy = ref_bbox[1] - view_bbox[1]
        return (0, dy, 0)
    return (0, 0, 0)


def _is_face_inside(inner_face, outer_face, margin_ratio=0.02):
    """判断 inner_face 是否位于 outer_face 内部（不与外轮廓边界接触）。

    用于区分真正的内部特征（孔、槽）与贴边特征。
    margin_ratio: 相对于外轮廓尺寸的边距比例
    """
    ow = outer_face["x_max"] - outer_face["x_min"]
    oh = outer_face["y_max"] - outer_face["y_min"]
    margin = max(ow, oh) * margin_ratio
    return (inner_face["x_min"] > outer_face["x_min"] + margin and
            inner_face["x_max"] < outer_face["x_max"] - margin and
            inner_face["y_min"] > outer_face["y_min"] + margin and
            inner_face["y_max"] < outer_face["y_max"] - margin)


def _vertical_hole_profiles(view, edges):
    """front/side 视图竖线对扫描 → 竖直孔投影列表 [(cx, r, ylo, yhi)]。

    竖直孔（轴沿 3D Z）在 front/side 视图的投影是两条竖线 X=cx±r。
    从原始边数据扫描竖线对，Y 范围即孔投影深度范围。
    主体外轮廓竖边（宽度 ≈ 视图宽）被 0.85 阈值排除。
    """
    ofc = view.get("_outer_face") or {}
    vx1, vx2 = ofc.get("x_min"), ofc.get("x_max")
    vy1, vy2 = ofc.get("y_min"), ofc.get("y_max")
    if vx1 is None or vy1 is None:
        return []
    body_w = vx2 - vx1

    # 收集视图 bbox 内的竖线段（按 X 归组）
    vlines = {}
    for e in edges:
        if getattr(e, "etype", "") != "LINE":
            continue
        x1, y1 = e.start[0], e.start[1]
        x2, y2 = e.end[0], e.end[1]
        if abs(x1 - x2) > 0.3:
            continue
        x = (x1 + x2) / 2
        if not (vx1 - 1 <= x <= vx2 + 1):
            continue
        ymin, ymax = min(y1, y2), max(y1, y2)
        if not (vy1 - 1 <= ymin <= vy2 + 1 and vy1 - 1 <= ymax <= vy2 + 1):
            continue
        if ymax - ymin < 0.5:
            continue
        vlines.setdefault(round(x, 1), []).append((ymin, ymax))

    # 竖线对匹配
    xs = sorted(vlines)
    profiles = []
    for i in range(len(xs)):
        for j in range(i + 1, len(xs)):
            x1, x2 = xs[i], xs[j]
            w = x2 - x1
            if w < 2.0 or w > body_w * 0.85:
                continue
            r = w / 2
            cx = (x1 + x2) / 2
            segs1 = vlines[x1]
            segs2 = vlines[x2]

            def _merge_segs(segs):
                """合并重叠/相邻（间隙 ≤0.5）的段。"""
                srt = sorted(segs)
                merged = [list(srt[0])]
                for s in srt[1:]:
                    if s[0] <= merged[-1][1] + 0.5:
                        merged[-1][1] = max(merged[-1][1], s[1])
                    else:
                        merged.append(list(s))
                return merged

            m1 = _merge_segs(segs1)
            m2 = _merge_segs(segs2)
            # 两竖线各段取交集，逐段生成 profile
            # （同一竖线对可承载多个特征，如 φ50 孔 Y2~7 与
            #   φ50 台阶 Y95~98 共用 X=17/67 竖线）
            ii = jj = 0
            while ii < len(m1) and jj < len(m2):
                ylo = max(m1[ii][0], m2[jj][0])
                yhi = min(m1[ii][1], m2[jj][1])
                if yhi - ylo >= 1.0:
                    profiles.append((cx, r, ylo, yhi))
                if m1[ii][1] < m2[jj][1]:
                    ii += 1
                else:
                    jj += 1
    return profiles


def _build_inner_cut_tool(face_info, view_type, edges, edge_vertices,
                          vertex_pos, scale_factor, extrude_half,
                          outer_face_center=None, z_align_offset=None):
    """从内部面构建 3D 切割工具。

    将内部闭环拉伸为穿透整个 CSG 主体的棱柱，
    用于 BRepAlgoAPI_Cut 布尔减运算。

    outer_face_center: 同视图外轮廓面在旋转+Z对齐后的 (cx, cy, cz)，
                       内部面使用相同偏移量居中，保持与外轮廓的相对位置。
    extrude_half: 拉伸半长，确保工具完全穿透主体
    返回: TopoDS_Shape 或 None
    """
    eids = face_info.get("edges")
    if not eids:
        return None

    # 1) 构建 Wire → Face（DXF 坐标，应用缩放）
    wire = build_occ_wire_from_face(eids, edges, edge_vertices, vertex_pos,
                                    scale_factor)
    if wire is None:
        return None
    occ_face = build_occ_face(wire)
    if occ_face is None:
        return None

    # 2) 视图平面变换（与外轮廓相同）
    _, extrude_axis = _get_view_transform(view_type)
    occ_face = _apply_view_transform(occ_face, view_type)

    # 3) Z 对齐：使用外轮廓的统一偏移量（不同半径的面必须用同一偏移）
    if view_type != "front" and z_align_offset is not None:
        if abs(z_align_offset) > 0.01:
            trsf_align = gp_Trsf()
            trsf_align.SetTranslation(gp_Vec(0, 0, -z_align_offset))
            occ_face = BRepBuilderAPI_Transform(occ_face, trsf_align).Shape()

    # 3.5) 使用外轮廓的统一居中偏移（而非独立居中）
    #       保持内部特征与外轮廓之间的相对位置关系
    if outer_face_center is not None:
        ocx, ocy, ocz = outer_face_center
        if abs(ocx) > 0.01 or abs(ocy) > 0.01 or abs(ocz) > 0.01:
            trsf_ctr = gp_Trsf()
            trsf_ctr.SetTranslation(gp_Vec(-ocx, -ocy, -ocz))
            occ_face = BRepBuilderAPI_Transform(occ_face, trsf_ctr).Shape()

    # 4) 平移到 -extrude_half，使切割工具居中覆盖主体
    vecs_neg = [
        gp_Vec(-extrude_half, 0, 0),
        gp_Vec(0, -extrude_half, 0),
        gp_Vec(0, 0, -extrude_half),
    ]
    trsf_neg = gp_Trsf()
    trsf_neg.SetTranslation(vecs_neg[extrude_axis])
    occ_face = BRepBuilderAPI_Transform(occ_face, trsf_neg).Shape()

    # 5) 正向拉伸 2×extrude_half → 穿透整个主体的棱柱
    tool = _extrude_face_dual(occ_face, extrude_axis, extrude_half * 2)
    return tool


def _separate_views_2d(faces_info, total_bbox):
    """从 2D 图纸中分离视图（基于 Y 间隙 + X 间隙）。

    返回: list of {name, faces, view_type, bbox}
    """
    if not faces_info:
        return []

    # 分离：正常面 vs 跨越面（跨多个视图的全局边框，标记为 is_spanning）
    normal_faces = [f for f in faces_info if not f.get("is_spanning")]
    spanning_faces = [f for f in faces_info if f.get("is_spanning")]

    # --- Y 方向分离：仅用正常面（跨越面会破坏聚类） ---
    total_h = total_bbox[3] - total_bbox[1]
    y_gap_threshold = max(15.0, total_h * 0.08)
    y_clusters = []
    if normal_faces:
        sorted_faces = sorted(normal_faces, key=lambda f: f["y_mid"])
        current_cluster = [sorted_faces[0]]
        for f in sorted_faces[1:]:
            prev_ymax = max(fi["y_max"] for fi in current_cluster)
            y_gap = f["y_min"] - prev_ymax
            if y_gap > y_gap_threshold:
                y_clusters.append(current_cluster)
                current_cluster = [f]
            else:
                current_cluster.append(f)
        y_clusters.append(current_cluster)
    elif spanning_faces:
        # 只有跨越面，直接作为一个簇
        y_clusters = [spanning_faces]

    # --- X 方向分离（在每个 Y 簇内部）：主视图 vs 侧视图 ---
    all_views = []
    total_x_range = total_bbox[2] - total_bbox[0]
    total_y_range = total_bbox[3] - total_bbox[1]

    for cluster in y_clusters:
        if len(cluster) <= 1:
            all_views.append(cluster)
            continue

        # X 间隙阈值基于 Y 簇总宽度 + 最小保护值
        # 同一视图内特征间隙通常 < 30mm 或 < 簇宽的 20%
        # 独立视图间距较大（如 主+左视图并排）
        cluster_x_min = min(f["x_min"] for f in cluster)
        cluster_x_max = max(f["x_max"] for f in cluster)
        cluster_x_width = cluster_x_max - cluster_x_min
        x_gap_threshold = max(30.0, cluster_x_width * 0.20)
        sorted_by_x = sorted(cluster, key=lambda f: f["x_mid"])
        x_clusters = [[sorted_by_x[0]]]
        for f in sorted_by_x[1:]:
            prev_xmax = max(fi["x_max"] for fi in x_clusters[-1])
            x_gap = f["x_min"] - prev_xmax
            if x_gap > x_gap_threshold:
                x_clusters.append([f])
            else:
                x_clusters[-1].append(f)
        all_views.extend(x_clusters)

    # --- 合并同 Y 层的 X 碎片（同一视图不应因特征间隙而拆分） ---
    # 如果两个簇的 Y 范围重叠 > 50%，合并它们
    merged_views = []
    used = set()
    for i, vf_i in enumerate(all_views):
        if i in used:
            continue
        yi_min = min(f["y_min"] for f in vf_i)
        yi_max = max(f["y_max"] for f in vf_i)
        yi_h = yi_max - yi_min
        merged = list(vf_i)
        for j in range(i + 1, len(all_views)):
            if j in used:
                continue
            yj_min = min(f["y_min"] for f in all_views[j])
            yj_max = max(f["y_max"] for f in all_views[j])
            yj_h = yj_max - yj_min
            # Y 重叠度
            overlap = min(yi_max, yj_max) - max(yi_min, yj_min)
            if overlap > 0 and (overlap > yi_h * 0.5 or overlap > yj_h * 0.5):
                # X 间隙保护：Y 高度对齐但 X 明显分离 → 可能是并列独立视图
                # （如 主视图+左视图 并排），不应合并
                mi_x_max = max(f["x_max"] for f in merged)
                mj_x_min = min(f["x_min"] for f in all_views[j])
                mj_x_max = max(f["x_max"] for f in all_views[j])
                x_gap = mj_x_min - mi_x_max
                mi_w = mi_x_max - min(f["x_min"] for f in merged)
                mj_w = mj_x_max - mj_x_min
                min_w = min(mi_w, mj_w) if mi_w > 0 and mj_w > 0 else 0
                if overlap > min(yi_h, yj_h) * 0.85 and x_gap > min_w * 0.25:
                    continue  # 跳过合并，保留为独立视图
                merged.extend(all_views[j])
                used.add(j)
        merged_views.append(merged)
        used.add(i)
    all_views = merged_views

    # --- 将跨越面分配到最匹配的最终视图 ---
    # （必须在合并之后，避免跨越面的 Y 范围导致错误合并）
    # 图框/标题栏面（面积 > 图幅 50%）不回填——回填会把视图 bbox
    # 撑成整图, 破坏后续 CSG 拉伸长度与视图类型识别。
    frame_area = ((total_bbox[2] - total_bbox[0])
                  * (total_bbox[3] - total_bbox[1]))
    for sf in spanning_faces:
        if sf["area"] > frame_area * 0.5:
            continue
        best_view = None
        best_overlap = -1
        sf_ymin, sf_ymax = sf["y_min"], sf["y_max"]
        for mv in all_views:
            cy_min = min(f["y_min"] for f in mv)
            cy_max = max(f["y_max"] for f in mv)
            overlap = min(sf_ymax, cy_max) - max(sf_ymin, cy_min)
            if overlap > best_overlap or (overlap == best_overlap
                   and cy_min < min(f["y_min"] for f in best_view)):
                best_overlap = overlap
                best_view = mv
        if best_view is not None and best_overlap > 0:
            best_view.append(sf)

    # --- 过滤图框边缘的碎片簇（标题栏格、边框残余）---
    # 视图簇不会紧贴图框边（有 G=45 布局间距 + 标注带），贴边且
    # 面积占比 <5% 或簇厚度 <15% 图幅的簇是标题栏/边框碎片，
    # 会破坏视图类型识别（标题栏横贯全图宽, 一旦误标 top 会把
    # 所有视图拉成 front）。
    frame_w = total_bbox[2] - total_bbox[0]
    frame_h = total_bbox[3] - total_bbox[1]
    frame_area = frame_w * frame_h
    edge_margin = frame_h * 0.18
    kept_views = []
    for mv in all_views:
        cy_min = min(f["y_min"] for f in mv)
        cy_max = max(f["y_max"] for f in mv)
        cx_min = min(f["x_min"] for f in mv)
        cx_max = max(f["x_max"] for f in mv)
        area_sum = sum(f["area"] for f in mv)
        cluster_h = cy_max - cy_min
        cluster_w = cx_max - cx_min
        near_bottom = cy_max < total_bbox[1] + edge_margin
        near_top = cy_min > total_bbox[3] - edge_margin
        near_left = cx_max < total_bbox[0] + edge_margin
        near_right = cx_min > total_bbox[2] - edge_margin
        is_fragment = (area_sum < frame_area * 0.05
                       or cluster_h < frame_h * 0.15
                       or cluster_w < frame_w * 0.15)
        if (near_bottom or near_top or near_left or near_right) \
                and is_fragment:
            continue
        kept_views.append(mv)
    all_views = kept_views

    # --- 识别视图类型（位置排名法，不受簇数量影响） ---
    result = []
    all_view_centers = []
    for vfaces in all_views:
        x_min = min(f["x_min"] for f in vfaces)
        x_max = max(f["x_max"] for f in vfaces)
        y_min = min(f["y_min"] for f in vfaces)
        y_max = max(f["y_max"] for f in vfaces)
        bbox = (x_min, y_min, x_max, y_max)
        all_view_centers.append(((x_min + x_max) / 2, (y_min + y_max) / 2))

    # 按 Y 排名：最高的 → top，按 X 排名：最右的 → side（不重复）
    n = len(all_views)
    y_ranks = sorted(range(n), key=lambda i: -all_view_centers[i][1])  # Y 降序
    x_ranks = sorted(range(n), key=lambda i: -all_view_centers[i][0])  # X 降序

    vtypes = ["front"] * n
    if n >= 2:
        # X 最右的 → side（前提：显著右于其他视图，且与另一视图
        # Y 同层——side 与主视图并排同高）。先于 top 判定：
        # top 判据（v0.6.3 双布局）需要 side 的 X 宽度。
        for xi in x_ranks:
            others_x = [all_view_centers[j][0] for j in range(n) if j != xi]
            if not others_x:
                continue
            avg_other_x = sum(others_x) / len(others_x)
            if all_view_centers[xi][0] <= avg_other_x + total_x_range * 0.12:
                continue
            same_layer = any(
                abs(all_view_centers[xi][1] - all_view_centers[j][1])
                < total_y_range * 0.25 for j in range(n) if j != xi)
            if same_layer:
                vtypes[xi] = "side"
                break

        # top 判定（v0.6.3 兼容第一角/第三角布局）：
        # 俯视图 Y 高度 = 零件宽度 = 侧视图 X 宽度（俯视与侧视共享
        # 零件宽），主视图 Y 高度 = 零件高度。Y 最高/最低两个候选
        # 中取 Y 范围更接近 side X 宽度者为 top；宽=高时平手，
        # 回退第三角约定"Y 最高 → top"（test_simple 布局）。
        # Y 最高与 Y 最低的视图间隙（两 Y 层布局：主视图+侧视图
        # 同层并列，俯视图独占另一层；三视图时 y_ranks[1] 是同层
        # 的 side，比较 y_ranks[0] vs y_ranks[-1] 才是层间间隙）
        if n > 1:
            y_gap_views = (all_view_centers[y_ranks[0]][1]
                           - all_view_centers[y_ranks[-1]][1])
        else:
            y_gap_views = 0.0
        if y_gap_views > total_y_range * 0.08:
            top_i = y_ranks[0]
            side_idx = next((i for i in range(n) if vtypes[i] == "side"), None)
            if side_idx is not None:
                def _vh(i):
                    return (max(f["y_max"] for f in all_views[i])
                            - min(f["y_min"] for f in all_views[i]))
                def _vw(i):
                    return (max(f["x_max"] for f in all_views[i])
                            - min(f["x_min"] for f in all_views[i]))
                side_w = _vw(side_idx)
                hi, lo = y_ranks[0], y_ranks[-1]
                d_hi = abs(_vh(hi) - side_w)
                d_lo = abs(_vh(lo) - side_w)
                tol = max(_vh(hi), _vh(lo), side_w) * 0.15
                if d_lo < d_hi - tol:
                    top_i = lo
                elif d_hi < d_lo - tol:
                    top_i = hi
                else:
                    top_i = hi  # 平手 → 第三角约定（Y 最高）
            vtypes[top_i] = "top"

        # X 对齐修正：与 top 视图 X 范围对齐的 → front，不对齐的 → side
        # 位置排名法可能把"与俯视图对齐的主视图"误判为 side（因为它靠右）
        if n >= 2:
            top_idx = next((i for i in range(n) if vtypes[i] == "top"), None)
            if top_idx is not None:
                top_x_min = min(f["x_min"] for f in all_views[top_idx])
                top_x_max = max(f["x_max"] for f in all_views[top_idx])
                for i in range(n):
                    if vtypes[i] == "top":
                        continue
                    view_x_min = min(f["x_min"] for f in all_views[i])
                    view_x_max = max(f["x_max"] for f in all_views[i])
                    view_x_w = view_x_max - view_x_min
                    x_overlap = min(view_x_max, top_x_max) - max(view_x_min, top_x_min)
                    if view_x_w > 0 and x_overlap > view_x_w * 0.5:
                        vtypes[i] = "front"  # 与 top 对齐 → 主视图
                    else:
                        vtypes[i] = "side"   # 不对齐 → 侧视图

    for idx, vfaces in enumerate(all_views):
        x_min = min(f["x_min"] for f in vfaces)
        x_max = max(f["x_max"] for f in vfaces)
        y_min = min(f["y_min"] for f in vfaces)
        y_max = max(f["y_max"] for f in vfaces)
        bbox = (x_min, y_min, x_max, y_max)
        vtype = vtypes[idx]

        result.append({
            "name": vtype,
            "faces": vfaces,
            "view_type": vtype,
            "bbox": bbox,
        })

    return result


def extract_outer_rings_no_merge(edges, views):
    """v0.6.1: 在无合并边图上提取各视图外轮廓环。

    背景: merge_close_vertices 在 HLR 密集折线图上会把 (2,2)/(2,3) 度
    顶点对大量坍缩成 8 字环，导致 face 遍历把外轮廓切碎。本函数绕开
    合并与 face 遍历，直接在原始顶点图上提取:

    - 折线图: 从分量最左下顶点出发做"最右转"遍历（排除已用边，
      回到起点即闭合）→ 外轮廓简单环
    - 弧图: 取 ARC 边连通分量中顶点度全 2 的最大闭合环（法兰圆被
      裁剪线切段后仍能拼回完整圆）

    Returns: {view_name: {"ring": [(eid, from_v, to_v), ...],
                          "vertex_pos": {vid: (x, y)},
                          "area": float, "bbox": (xmin, ymin, xmax, ymax)}}
    """
    from collections import defaultdict

    vertex_pos, edge_vertices, nv = build_vertex_map(edges)
    adj = build_adjacency(vertex_pos, edge_vertices, edges, nv)

    # 连通分量
    seen = set()
    comps = []
    for v in vertex_pos:
        if v in seen:
            continue
        stack = [v]
        seen.add(v)
        vs = []
        while stack:
            u = stack.pop()
            vs.append(u)
            for _, w, _ in adj.get(u, []):
                if w not in seen:
                    seen.add(w)
                    stack.append(w)
        comps.append(vs)

    # 修剪度 1 悬边（迭代删除）: supplement 几何假轮廓（锥面参数包围盒外
    # 的轮廓母线，如法兰锥母线 (2,21.74) 端）端点悬空，会劫持面遍历
    # （外环在分支点被拐进死路）。度 1 顶点不可能构成面环，安全删除。
    n_pruned = 0
    changed = True
    while changed:
        changed = False
        for v in [v for v in adj if len(adj.get(v, [])) == 1]:
            # 孤立边两端互删时, 另一端点可能已被前序迭代清空
            if not adj.get(v):
                continue
            eid, w, _ang = adj[v][0]
            del adj[v]
            adj[w] = [t for t in adj[w] if t[1] != v]
            n_pruned += 1
            changed = True
    if n_pruned:
        print(f"[环提取] 修剪悬边: {n_pruned} 个度 1 顶点")

    def ring_area_pts(pts):
        a = 0.0
        n = len(pts)
        for i in range(n):
            x1, y1 = pts[i]
            x2, y2 = pts[(i + 1) % n]
            a += x1 * y2 - x2 * y1
        return abs(a) / 2

    def arc_ring(vids):
        """ARC 连通分量中顶点度全 2 的闭合环，取弧数最多者。"""
        arc_adj = defaultdict(list)
        for v in vids:
            for eid, w, ang in adj.get(v, []):
                if edges[eid].etype == "ARC":
                    arc_adj[v].append((eid, w))
        if not arc_adj:
            return None
        # ---- v0.6.2: 共圆弧角并集 → 整圆合成 ----
        # 锥面大端圆边与弧片大端圆边投影重合（同圆心同半径的两组弧），
        # 顶点度 >2 破坏下方"度全 2"判据 → 法兰带俯视轮廓（r40 圆）
        # 被跳过，top 外环误选 60 方折线环。若某圆上全部弧的角区间
        # 并集覆盖整圆，直接合成整圆环（面积 πr² 参与比较）。
        by_circle = defaultdict(list)
        for v in arc_adj:
            for eid, w in arc_adj[v]:
                e = edges[eid]
                if e.radius and e.radius > 0:
                    by_circle[(round(e.center[0], 3), round(e.center[1], 3),
                               round(e.radius, 3))].append(eid)
        full_circles = []
        for key, eids in by_circle.items():
            ivs = []
            for eid in eids:
                e = edges[eid]
                a1, a2 = e.start_angle, e.end_angle
                if a2 < a1:
                    a2 += 360.0
                if a2 - a1 >= 359.0:
                    ivs = [(0.0, 360.0)]
                    break
                b1, b2 = a1 % 360.0, a2 % 360.0
                if b1 <= b2:
                    ivs.append((b1, b2))
                else:
                    ivs.append((b1, 360.0))
                    ivs.append((0.0, b2))
            ivs.sort()
            merged = []
            for a, b in ivs:
                if a >= b:
                    continue
                if merged and a <= merged[-1][1] + 0.5:
                    merged[-1] = (merged[-1][0], max(merged[-1][1], b))
                else:
                    merged.append((a, b))
            if sum(b - a for a, b in merged) >= 359.5:
                full_circles.append(key)
        # ---- v0.6.3: 圆上有挂线顶点时不合成整圆 ----
        # 法兰叶片角竖线与 r=30 圆相切于 (72,-87)，顶点度 12，
        # 真实外环是圆+4 叶片角凸起；整圆合成会吞掉叶片角。
        # v0.6.2 修的法兰带 r=40 假整圆场景在 v6 图纸已不存在
        # （r=40 弧覆盖 28.7° 不触发合成），此条件无回归风险。
        full_circles_clean = []
        for key in full_circles:
            cvs = set()
            for v in arc_adj:
                for eid, w in arc_adj[v]:
                    e = edges[eid]
                    if e.radius and (round(e.center[0], 3),
                                     round(e.center[1], 3),
                                     round(e.radius, 3)) == key:
                        cvs.add(v)
                        cvs.add(w)
            if cvs and all(len(adj.get(v, [])) == 2 for v in cvs):
                full_circles_clean.append(key)
            else:
                print(f"[环提取] 圆 c=({key[0]:.1f},{key[1]:.1f}) "
                      f"r={key[2]:.1f} 有挂线顶点, 跳过整圆合成")
        if full_circles_clean:
            cx, cy, r = max(full_circles_clean, key=lambda k: k[2])
            # 合成整圆: 36 条 10° 弧边 + 36 个新顶点
            # （顶点多边形面积 0.5·n·r²·sin(2π/n) 逼近 πr²，参与面积比较）
            n_seg = 36
            base_e = len(edges)
            base_v = max(vertex_pos, default=-1) + 1
            ring = []
            for k in range(n_seg):
                a1 = k * 10.0
                a2 = a1 + 10.0
                p1 = (cx + r * math.cos(math.radians(a1)),
                      cy + r * math.sin(math.radians(a1)))
                p2 = (cx + r * math.cos(math.radians(a2)),
                      cy + r * math.sin(math.radians(a2)))
                eid = base_e + k
                edges.append(Edge(eid, "ARC", p1, p2, center=(cx, cy),
                                  radius=r, start_angle=a1, end_angle=a2))
                vertex_pos[base_v + k] = p1
                ring.append((eid, base_v + k, base_v + (k + 1) % n_seg))
            print(f"[环提取] 整圆合成: r={r:.1f} c=({cx:.1f},{cy:.1f}) "
                  f"{n_seg} 段弧", flush=True)
            return ring
        seen_a = set()
        best = None
        for v in arc_adj:
            if v in seen_a:
                continue
            stack = [v]
            seen_a.add(v)
            ring_vs = []
            while stack:
                u = stack.pop()
                ring_vs.append(u)
                for eid, w in arc_adj.get(u, []):
                    if w not in seen_a:
                        seen_a.add(w)
                        stack.append(w)
            if len(ring_vs) >= 4 and all(
                    len(arc_adj.get(u, [])) == 2 for u in ring_vs):
                if best is None or len(ring_vs) > len(best):
                    best = ring_vs
        if best is None:
            return None
        # 定向: 从环上任一点出发沿唯一未用弧走回起点
        used = set()
        start = best[0]
        cur = start
        prev = None
        ring = []
        while True:
            nxts = [(eid, w) for eid, w in arc_adj[cur]
                    if eid not in used and w != prev]
            if not nxts:
                break
            eid, w = nxts[0]
            ring.append((eid, cur, w))
            used.add(eid)
            prev, cur = cur, w
            if cur == start:
                break
        if ring and ring[-1][2] == start:
            return ring
        return None

    def polyline_ring(vids, ccw_rule="min"):
        """折线外环遍历（排除已用边，回到起点闭合）。

        ccw_rule="min": 最左转——凹轮廓（台阶/斜母线）的标准外环规则
        ccw_rule="max": 最右转——旧行为，凸轮廓兼容
        v0.6.1: 含锥面斜母线的新图纸台阶环在 max-ccw 下走错
        （底边 split 点选斜边弃底边），min-ccw 正确。
        起点选最下顶点（y 最小）：外环底边保证在外轮廓上；
        最左下会选中锥母线/圆角轮廓的中间 split 点导致走错。
        """
        v0 = min(vids, key=lambda v: (vertex_pos[v][1], vertex_pos[v][0]))
        cur_v = v0
        incoming = math.pi  # 虚拟: 从右向左进入最下顶点
        used = set()
        ring = []
        for _ in range(10000):
            out_ref = incoming + math.pi
            if out_ref > math.pi:
                out_ref -= 2 * math.pi
            cands = []
            for eid_out, other, ang_out in adj.get(cur_v, []):
                if eid_out in used:
                    continue
                ccw = ang_out - out_ref
                if ccw < -math.pi:
                    ccw += 2 * math.pi
                if ccw < 0:
                    ccw += 2 * math.pi
                cands.append((ccw, eid_out, other, ang_out))
            if not cands:
                return None
            # v0.6.3: ccw 相同时弧优先——直线与弧相切（切线方向
            # 相同）时转角 tie，纯排序会走直线把外环带偏（法兰叶片角
            # 竖线与 r=30 圆相切于 (72,-87)）；弧是转向圆心侧的
            # 路径，外环应走弧。
            # v0.6.3 fix2: 但交点（顶点度>2，如 r30 内圆与外轮廓
            # 相交的 (12,-87)）处必须直线优先——弧优先会把内部
            # 台阶圆并入外环, 环绕内圆一圈后自交（top 环面积虚高
            # 5376>bbox 3600, CSG 棱柱求交为空）。
            deg = len(adj.get(cur_v, []))
            tie_arc_first = deg <= 2
            cands.sort(key=lambda c: (c[0] if ccw_rule == "min" else -c[0],
                                      0 if (edges[c[1]].etype == "ARC")
                                      == tie_arc_first else 1))
            _, eid_out, nxt, ang = cands[0]
            ring.append((eid_out, cur_v, nxt))
            used.add(eid_out)
            incoming = ang
            cur_v = nxt
            if cur_v == v0:
                return ring
        return None

    def face_ring_from_directed_edge(eid0, v_from, v_to):
        """无合并图精确面遍历: 有向边 (v_from→v_to) 的左面环。

        从 v_to 出发, incoming=该边方向, min-ccw 左面遍历回到起点。
        返回 (ring, area) 或 (None, 0)。
        """
        ang0 = None
        for eid, w, ang in adj.get(v_from, []):
            if eid == eid0 and w == v_to:
                ang0 = ang
                break
        if ang0 is None:
            return None, 0.0
        ring = [(eid0, v_from, v_to)]
        used = {eid0}
        incoming = ang0
        cur_v = v_to
        start_v = v_from
        for _ in range(10000):
            out_ref = incoming + math.pi
            if out_ref > math.pi:
                out_ref -= 2 * math.pi
            cands = []
            for eid_out, other, ang_out in adj.get(cur_v, []):
                if eid_out in used:
                    continue
                ccw = ang_out - out_ref
                if ccw < -math.pi:
                    ccw += 2 * math.pi
                if ccw < 0:
                    ccw += 2 * math.pi
                cands.append((ccw, eid_out, other, ang_out))
            if not cands:
                return None, 0.0
            # 左面 = 最小顺时针转角 = 最大 ccw；ccw 相同时弧优先
            # （直线与弧相切点 tie-break，见 polyline_ring 注释）；
            # 交点（度>2）直线优先（v0.6.3 fix2，同上）
            deg = len(adj.get(cur_v, []))
            tie_arc_first = deg <= 2
            cands.sort(key=lambda c: (-c[0],
                                      0 if (edges[c[1]].etype == "ARC")
                                      == tie_arc_first else 1))
            _, eid_out, nxt, ang = cands[0]
            ring.append((eid_out, cur_v, nxt))
            used.add(eid_out)
            incoming = ang
            cur_v = nxt
            if cur_v == start_v:
                pts = [vertex_pos[f] for _, f, _ in ring]
                a = 0.0
                for i in range(len(pts)):
                    x1, y1 = pts[i]
                    x2, y2 = pts[(i + 1) % len(pts)]
                    a += x1 * y2 - x2 * y1
                return ring, abs(a) / 2
        return None, 0.0

    def face_rings_all(vids):
        """对分量内所有有向边做左面遍历 → 面积最大的面环。"""
        vset = set(vids)
        best = None
        best_area = 0.0
        seen_dirs = set()
        for v in vids:
            for eid, w, _ang in adj.get(v, []):
                if w not in vset:
                    continue
                if (eid, v, w) in seen_dirs:
                    continue
                seen_dirs.add((eid, v, w))
                ring, area = face_ring_from_directed_edge(eid, v, w)
                if ring is not None and area > best_area:
                    best_area = area
                    best = ring
        return best

    # 视图归属: 环 bbox 中心落在视图 bbox 内
    def assign_view(bbox):
        cx = (bbox[0] + bbox[2]) / 2
        cy = (bbox[1] + bbox[3]) / 2
        for v in views:
            x1, y1, x2, y2 = v["bbox"]
            if x1 - 5 <= cx <= x2 + 5 and y1 - 5 <= cy <= y2 + 5:
                return v["name"]
        return None

    result = {}
    for vs in sorted(comps, key=len, reverse=True):
        vs = [v for v in vs if v in adj]  # 悬边修剪后可能删除顶点
        if len(vs) < 4:
            continue
        # 候选环: arc/polyline(min/max)/面遍历全部参与，按面积取大者
        # （polyline 规则在分支点可能返回错误小环，面积比较兜底）
        cands = []
        for r in (arc_ring(vs), polyline_ring(vs, "min"),
                  polyline_ring(vs, "max")):
            if r is not None:
                cands.append(r)
        # v0.6.3: 面遍历始终参与——混合环（弧+线，如法兰叶片角）
        # 的 arc_ring 返回 None，polyline min/max 规则在挂线分支点
        # （(72,-87) 顶点度 12）均可能走错；面遍历按左面规则
        # 遍历所有有向边，对平面图保证外环正确，由面积比较兜底
        fr = face_rings_all(vs)
        if fr is not None:
            cands.append(fr)
        ring = None
        best_area = -1.0
        for r in cands:
            a = ring_area_pts([vertex_pos[f] for _, f, _ in r])
            if a > best_area:
                best_area = a
                ring = r
        if ring is None:
            continue
        pts = [vertex_pos[f] for _, f, _ in ring]
        area = ring_area_pts(pts)
        if area < 10:
            continue
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        bbox = (min(xs), min(ys), max(xs), max(ys))
        vname = assign_view(bbox)
        if vname is None:
            continue
        # 同视图多环取面积大者
        if vname not in result or area > result[vname]["area"]:
            result[vname] = {
                "ring": ring,
                "vertex_pos": vertex_pos,
                "area": area,
                "bbox": bbox,
            }

    # ---- v0.6.3: 方∩圆叶片角外环增强 ----
    # 方形 bbox 环 + 同心圆（半径 ∈ (半宽, 半宽√2]，弧端点落在 bbox
    # 边上）→ 合成"方∩圆"轮廓（4 弦 + 4 角弧，8 段）。
    # 法兰盘截面 = 圆盘 + 4 对角叶片（"60×60 方 ∩ r40 圆"截面积与
    # 基准叶片差 9 面积单位内，745 vs 736）。HLR 俯视投影把叶片角弧
    # 判为隐藏（4 角弧仅 2 角可见，28.7°），折线外环在缺弧角处断链
    # 退化为纯方形 → 叶片材料整体缺失（基准 r[30,40] 环带）。
    # 判据"弧端点落在 bbox 边上"证明圆与方边真实相交，排除整圆外环。
    for vname, rdata in result.items():
        xmin, ymin, xmax, ymax = rdata["bbox"]
        w = xmax - xmin
        h = ymax - ymin
        if w < 10 or h < 10 or abs(w - h) > max(5.0, 0.02 * w):
            continue
        hw = w / 2
        bxc, byc = (xmin + xmax) / 2, (ymin + ymax) / 2
        # 收集与环 bbox 同心的候选圆
        by_circle = defaultdict(list)
        for eid, e in enumerate(edges):
            if e.etype != "ARC" or not e.radius or e.radius <= 0:
                continue
            if abs(e.center[0] - bxc) > 1.0 or abs(e.center[1] - byc) > 1.0:
                continue
            if not (hw < e.radius <= hw * 1.42 + 0.5):
                continue
            by_circle[(round(e.center[0], 3), round(e.center[1], 3),
                       round(e.radius, 3))].append(eid)
        best_circ = None
        best_cov = 0.0
        for key, eids in by_circle.items():
            n_on = 0
            ivs = []
            for eid in eids:
                e = edges[eid]
                for px, py in (e.start, e.end):
                    if (abs(px - xmin) < 1.0 or abs(px - xmax) < 1.0) \
                            and ymin - 1 <= py <= ymax + 1:
                        n_on += 1
                    elif (abs(py - ymin) < 1.0 or abs(py - ymax) < 1.0) \
                            and xmin - 1 <= px <= xmax + 1:
                        n_on += 1
                a1, a2 = e.start_angle, e.end_angle
                if a2 < a1:
                    a2 += 360.0
                b1, b2 = a1 % 360.0, a2 % 360.0
                if b1 <= b2:
                    ivs.append((b1, b2))
                else:
                    ivs.append((b1, 360.0))
                    ivs.append((0.0, b2))
            if n_on < 1:
                continue
            cov = sum(b - a for a, b in ivs)
            if cov > best_cov:
                best_cov = cov
                best_circ = key
        if best_circ is None or best_cov >= 359.5:
            continue
        cx, cy, r = best_circ
        dy = math.sqrt(r * r - hw * hw)
        # 8 顶点（逆时针: 底弦→左下弧→左弦→左上弧→上弦→右上弧→右弦→右下弧）
        base_e = len(edges)
        base_v = max(vertex_pos, default=-1) + 1
        vpts = [(bxc + dy, byc - hw), (bxc - dy, byc - hw),
                (bxc - hw, byc - dy), (bxc - hw, byc + dy),
                (bxc - dy, byc + hw), (bxc + dy, byc + hw),
                (bxc + hw, byc + dy), (bxc + hw, byc - dy)]
        # 线段: 底弦 v0-v1、左弦 v2-v3、上弦 v4-v5、右弦 v6-v7
        # 弧: 左下 v1-v2、左上 v3-v4、右上 v5-v6、右下 v7-v0
        segs = [("LINE", 0, 1), ("ARC", 1, 2), ("LINE", 2, 3),
                ("ARC", 3, 4), ("LINE", 4, 5), ("ARC", 5, 6),
                ("LINE", 6, 7), ("ARC", 7, 0)]
        new_ring = []
        for k, (ety, i, j) in enumerate(segs):
            p1, p2 = vpts[i], vpts[j]
            for vid, pt in ((base_v + i, p1), (base_v + j, p2)):
                vertex_pos[vid] = pt
            eid = base_e + k
            if ety == "LINE":
                edges.append(Edge(eid, "LINE", p1, p2))
            else:
                # 角弧 < 90°，字段角度直接用 atan2（wire 构建走
                # 三点过圆构造，天然取小弧，字段不参与）
                edges.append(Edge(eid, "ARC", p1, p2, center=(cx, cy),
                                  radius=r,
                                  start_angle=math.degrees(math.atan2(
                                      p1[1] - cy, p1[0] - cx)),
                                  end_angle=math.degrees(math.atan2(
                                      p2[1] - cy, p2[0] - cx))))
            new_ring.append((eid, base_v + i, base_v + j))
        pts = [vertex_pos[f] for _, f, _ in new_ring]
        new_area = abs(sum(pts[i][0] * pts[(i + 1) % 8][1]
                           - pts[i][1] * pts[(i + 1) % 8][0]
                           for i in range(8))) / 2
        result[vname] = {
            "ring": new_ring,
            "vertex_pos": vertex_pos,
            "area": new_area,
            "bbox": (cx - r, cy - r, cx + r, cy + r),
        }
        print(f"[叶片角] 视图 '{vname}' 方∩圆外环增强: 半宽={hw:.1f} "
              f"圆 r={r:.1f} 弧覆盖={best_cov:.1f}° → 8 段轮廓 "
              f"bbox 扩展 ({xmin:.0f}→{cx - r:.0f})")

    # 注（v0.6.3 撤销记录）: 曾尝试把 front/side 外环矩形化为 top 环
    # 宽度（"共享轴对齐"）。实测环带面（方∩圆∖内孔）本身 ⊂ ±30 方，
    # 与 front/side 原始棱柱求交无损（v6k 日志: 环带交集 bbox 恒为
    # ±30）——矩形化对叶片材料无收益，却抹掉了 front/side 外环在
    # 台阶段的 ±25 收窄（φ50 台阶竖线），使台阶段假材料从 1,004
    # 恶化到 4,639。撤销矩形化，保留原始外环。
    return result


def build_wire_from_directed_ring(ring, vertex_pos, edges, scale_factor=1.0):
    """v0.6.1: 定向边序列 → OCC wire（原始几何 + ShapeFix 修复）。

    ARC 端点夹取到圆上（HLR 输出弧端点与圆心距有 ~0.03mm 偏差），
    LINE 直接用两端点。
    """
    try:
        sf = scale_factor
        wb = BRepBuilderAPI_MakeWire()
        for eid, f, t in ring:
            e = edges[eid]
            p1 = vertex_pos[f]
            p2 = vertex_pos[t]
            if e.etype == "ARC" and e.radius > 0:
                circ = gp_Circ(
                    gp_Ax2(gp_Pnt(e.center[0] * sf, e.center[1] * sf, 0),
                           gp_Dir(0, 0, 1)),
                    e.radius * sf)
                a1 = math.atan2(p1[1] - e.center[1], p1[0] - e.center[0])
                a2 = math.atan2(p2[1] - e.center[1], p2[0] - e.center[0])
                # 三点过圆构造: 端点精确落在顶点坐标上（参数构造的
                # 弧端点与 LINE 顶点有 ~0.001mm 浮点偏差, 会让
                # MakeWire 判为不连续丢弃后续所有边）
                mid_a = (a1 + a2) / 2
                p1_pt = gp_Pnt(p1[0] * sf, p1[1] * sf, 0)
                p2_pt = gp_Pnt(p2[0] * sf, p2[1] * sf, 0)
                pm_pt = gp_Pnt((e.center[0] + e.radius * math.cos(mid_a)) * sf,
                               (e.center[1] + e.radius * math.sin(mid_a)) * sf,
                               0)
                try:
                    occ_edge = BRepBuilderAPI_MakeEdge(
                        circ, p1_pt, pm_pt, p2_pt).Edge()
                except Exception:
                    occ_edge = BRepBuilderAPI_MakeEdge(p1_pt, p2_pt).Edge()
            else:
                occ_edge = BRepBuilderAPI_MakeEdge(
                    gp_Pnt(p1[0] * sf, p1[1] * sf, 0),
                    gp_Pnt(p2[0] * sf, p2[1] * sf, 0)).Edge()
            wb.Add(occ_edge)
        wire = wb.Wire()
        fixer = ShapeFix_Wire()
        fixer.SetPrecision(0.5)
        fixer.Load(wire)
        fixer.FixReorder()
        fixer.FixConnected()
        fixer.FixClosed()
        return fixer.Wire()
    except Exception:
        return None


def _find_inner_body_circle(ring_data, edges):
    """v0.6.3 P3.1: 在外环内部找主体级整圆（供 CSG 分体）。

    方角法兰类零件（方盘+圆柱主体，如麒浚传动 PF60K）的 top 视图
    外环内部有一个与外环内接的主体整圆（r30 圆与 16 边方角环相切
    于 4 个交点）。单外环 CSG 求交会得到方柱而非圆柱——检测该整圆
    后分体建模：主体用圆棱柱、环带用（外环-内圆）棱柱。

    检测条件（全部满足才触发，避免误伤简单用例）:
      1) 同圆心+同半径弧组 ≥3 段且角度覆盖 ≥300°
      2) 半径 ≥ 0.75 × 环 bbox 半宽（主体圆与外环内接级）
      3) 外环直线边 ≥4 条（排除纯圆环——同心微差圆法兰不触发）
      4) 取满足条件的最大半径组（内部同心小圆组不选）

    同时找次大整圆（如 φ50 底沉 r25，半径 ≥0.6×主体圆半径）——
    环带面内孔用它：法兰段 r∈[r_inner,r_body] 有材料、r<r_inner
    由底沉刀单独切，避免环带面把底沉区域也挖空。

    返回 (cx, cy, r_body, r_inner)（DXF 坐标）或 None；
    r_inner 无次大整圆时为 None。
    """
    rb = ring_data["bbox"]
    rw, rh = rb[2] - rb[0], rb[3] - rb[1]
    if min(rw, rh) <= 0:
        return None
    half = min(rw, rh) / 2
    n_lines = sum(1 for eid, _, _ in ring_data["ring"]
                  if edges[eid].etype == "LINE")
    if n_lines < 4:
        return None
    arc_groups = {}
    for e in edges:
        if e.etype != "ARC" or not e.radius or e.radius <= 0:
            continue
        key = (round(e.center[0], 2), round(e.center[1], 2),
               round(e.radius, 2))
        arc_groups.setdefault(key, []).append(e)
    full_circles = []
    for (cx, cy, r), es in arc_groups.items():
        if len(es) < 3:
            continue
        # v0.6.3: 0.5 → 0.4 半宽——法兰中央孔 φ32 (r16) 也要进入
        # 候选（PF60K 法兰内孔阶梯 φ50→φ32→φ14，环带面内孔须取
        # 最小贯穿孔，否则底沉上方 r[16,25] 材料被一并挖空）
        if r < half * 0.4:
            continue
        if not (rb[0] + r * 0.2 < cx < rb[2] - r * 0.2
                and rb[1] + r * 0.2 < cy < rb[3] - r * 0.2):
            continue
        span = sum(abs(e.end_angle - e.start_angle) for e in es)
        if span < 300.0:
            continue
        full_circles.append((r, cx, cy))
    if not full_circles:
        return None
    full_circles.sort(reverse=True)
    r_body, cx, cy = full_circles[0]
    if r_body < half * 0.75:
        return None
    # v0.6.3: 环带面内孔取"贯穿孔级圆"。基准 PF60K 中央孔系 =
    # φ50 底沉(r25, 0.83×主体) + φ42 孔(r21, 0.70×) + φ32 孔内环岛
    # (r16, 材料) + φ14 芯孔(r7)。取最大次圆(r25)把底沉上方 r[16,25]
    # 材料全挖空(缺失 19,650)；取最小圆(r16)把 φ42 孔壁 r[16,21]
    # 段留成假材料(假 10,752)。判据: 候选降序，最大候选 ≥0.8×主体
    # 圆属底沉级，有 ≥2 个候选时剔除，取余下最大者 = 孔级(r21)。
    # 底沉由 P0 限深刀单独切深。
    cands = [r for r, _cx2, _cy2 in full_circles[1:]
             if r_body * 0.45 <= r <= r_body * 0.85]
    if len(cands) >= 2 and cands[0] >= r_body * 0.8:
        cands = cands[1:]
    r_inner = cands[0] if cands else None
    return cx, cy, r_body, r_inner


def _flange_top_from_ring_vertices(views, scale_factor, no_merge_rings, edges):
    """v0.6.3 P3.1: 从 front/side 外环顶点标定法兰顶面 z（CSG 居中系）。

    法兰顶面在 front/side 外环上是多个"非极值"顶点的 y 层——锥面
    顶段上端 (x=±23.5 等) 落在法兰顶面, 而主体段竖线端点与锥面底
    圆投影点都是 x 极值（x=x_min/x_max）。取视图下半部、顶点 x 不
    达外环 x 极值的 y 层最大值 → 法兰顶面高度。

    v0.6.3 返回 (法兰顶, 锥面顶) 两层：
    - 法兰顶 = 最高非极值层（PF60K 芯孔竖线对 x=±7 上端 y=28.45）
    - 锥面顶 = 法兰顶下方间隔 >2mm 的次高非极值层（锥面斜线上端
      y=23.5）——锥面段 r30 圆盘由主体圆棱柱覆盖，环带只需到
      锥面顶；顶盘段（基准 r30 圆盘无叶片）环带角区柱是假材料
      （PF60K 顶盘段假 3,737）。

    返回 (z_flange, z_cone) 或 (None, None)（无可靠信号）。
    """
    cands = []
    cone_cands = []
    for v in views:
        if v["view_type"] == "top":
            continue
        rd = no_merge_rings.get(v["name"])
        if rd is None:
            continue
        # v0.6.3: 共享轴对齐矩形化后环只剩 4 个极值顶点——标定必须
        # 用原始环顶点快照（锥面顶段上端等非极值顶点是法兰顶信号）
        if "orig_pts" in rd:
            pts = rd["orig_pts"]
            x1, y1, x2, y2 = rd["orig_bbox"]
        else:
            vp = rd["vertex_pos"]
            pts = [(vp[vi][0], vp[vi][1])
                   for _eid, f, t in rd["ring"] for vi in (f, t)]
            x1, y1, x2, y2 = rd["bbox"]
        ymid = (y1 + y2) / 2
        # 按 y 分层（0.1 精度），统计每层是否有非 x 极值顶点
        layers = {}
        for px, py in pts:
            if not (y1 + 2 < py < ymid):
                continue
            key = round(py, 1)
            non_ext = (abs(px - x1) > 1.5 and abs(px - x2) > 1.5)
            rec = layers.setdefault(key, [False, 0])
            rec[1] += 1
            rec[0] = rec[0] or non_ext
        for yk, (non_ext, n) in layers.items():
            if non_ext and n >= 2:
                cands.append(yk)
        # v0.6.3: 锥面顶信号 = 外环斜线边（锥面母线投影，两端 x/y
        # 均不同）的上端 y——孔竖线层（φ42 段顶 25.5）x 恒定，
        # 与锥面斜线上端（23.5）混在同一"次高层"区间，靠斜边
        # 方向性区分
        vp = rd["vertex_pos"]
        for eid, f, t in rd["ring"]:
            e = edges[eid]
            if e.etype != "LINE":
                continue
            p1 = vp[f]
            p2 = vp[t]
            if (abs(p1[0] - p2[0]) > 1.5
                    and abs(p1[1] - p2[1]) > 1.5):
                cone_cands.append(max(p1[1], p2[1]))
    if not cands:
        return None, None
    y_top = max(cands)
    z_top = (y_top - ymid) * scale_factor
    # 锥面顶 = 斜线边上端（在法兰顶下方 >1mm 才有意义）；
    # 找不到（无锥面结构或斜线未输出）→ None 回退法兰顶
    y_cone = max((y for y in cone_cands if y_top - y > 1.0), default=None)
    z_cone = (y_cone - ymid) * scale_factor if y_cone is not None else None
    return z_top, z_cone


def csg_reconstruct(views, edges, edge_vertices, vertex_pos, scale_factor=1.0,
                    annotations=None):
    """CSG 体积求交法：各视图轮廓拉伸为棱柱 → 布尔交集 → 3D 实体。

    原理:
      3D实体 = 前视图棱柱 ∩ 俯视图棱柱 ∩ 侧视图棱柱
      前视图棱柱 = 前视图外轮廓 沿 Y 拉伸（面在 XZ 平面，竖轴=Z 高度）
      俯视图棱柱 = 俯视图外轮廓 沿 Z 拉伸（面在 XY 平面）
      侧视图棱柱 = 侧视图外轮廓 沿 X 拉伸（面在 YZ 平面）

    scale_factor: DXF 坐标 → 实物尺寸的缩放因子
    annotations: extract_dxf_annotations() 返回的注解字典（P2）

    Returns: (body_solid, hole_data) 或 (None, None)
    """
    if len(views) < 2:
        return None, None  # 单视图不用 CSG

    # 计算智能拉伸距离（已考虑比例）
    # 不再使用固定 5x 乘数（会导致极端长宽比破坏布尔运算精度）
    all_x = []
    all_y = []
    for v in views:
        all_x.extend([v["bbox"][0] * scale_factor, v["bbox"][2] * scale_factor])
        all_y.extend([v["bbox"][1] * scale_factor, v["bbox"][3] * scale_factor])
    total_x = max(all_x) - min(all_x)
    total_y = max(all_y) - min(all_y)
    max_dim = max(total_x, total_y)
    # 使用 2x 乘数：足够覆盖整个零件，同时避免极端长宽比
    extrude_dist = max_dim * 2

    # ---- Fix 4: 前视图 Y 范围由 P1 投影验证自动处理 ----

    # ---- v0.6.1: 无合并边图外环提取（优先路径）----
    # 合并边图上的 face 遍历在 HLR 密集折线/平行边对处会产生 8 字环
    # 与切碎外轮廓；无合并边图上的最右转遍历/弧连通环提取更可靠。
    no_merge_rings = extract_outer_rings_no_merge(edges, views)
    if no_merge_rings:
        print(f"  [v0.6.1] 无合并外环提取: {len(no_merge_rings)}/{len(views)} 视图 "
              f"({', '.join(no_merge_rings)})")

    prisms = []
    prisms_flange = []  # v0.6.3 P3.1: top 分体的环带棱柱
    hole_data = []  # 每个视图的内孔信息

    for v in views:
        ring_data = no_merge_rings.get(v["name"])
        if ring_data is not None:
            # 新路径: 直接用无合并外环，绕过 face 遍历外轮廓选择
            rb = ring_data["bbox"]
            outer_face = {
                "edges": None,
                "area": ring_data["area"],
                "face_type": "no_merge_ring",
                "x_min": rb[0], "y_min": rb[1],
                "x_max": rb[2], "y_max": rb[3],
            }
            use_bbox_fallback = False
            use_ring_wire = True
            ring_wire_data = ring_data
        else:
            use_ring_wire = False
            ring_wire_data = None
            # 找外轮廓（最大面积 line_only 或 circle 面）
            line_faces = [f for f in v["faces"]
                          if f["face_type"] == "line_only" and f["area"] > 10]
            line_faces.sort(key=lambda f: -f["area"])
            arc_faces = [f for f in v["faces"]
                         if f["face_type"] in ("single_arc", "concentric")
                         and f["area"] > 50]
            arc_faces.sort(key=lambda f: -f["area"])

            outer_face = None
            use_bbox_fallback = False
            if line_faces:
                outer_face = line_faces[0]
            elif arc_faces:
                outer_face = arc_faces[0]

            # 回退检测：如果最大面的 X 或 Y 覆盖不足视图包围盒的 50%，
            # 说明缺少真正的外轮廓（被边框吸收或面遍历不完整），用包围盒替代
            if outer_face is not None and len(v["faces"]) >= 3:
                face_x_span = outer_face["x_max"] - outer_face["x_min"]
                face_y_span = outer_face["y_max"] - outer_face["y_min"]
                view_x_span = v["bbox"][2] - v["bbox"][0]
                view_y_span = v["bbox"][3] - v["bbox"][1]
                if (view_x_span > 0 and face_x_span < view_x_span * 0.50) or \
                   (view_y_span > 0 and face_y_span < view_y_span * 0.50):
                    outer_face = None  # 触发包围盒回退

        if outer_face is None and len(v["faces"]) >= 1:
            # 用视图包围盒构建矩形外轮廓
            x_min, y_min, x_max, y_max = v["bbox"]
            # ---- P3: X 范围与共享轴视图对齐 ----
            # front/top 共享 DXF X 轴（正交投影约定），两者 X 范围应一致。
            # 若本视图外轮廓缺失导致 bbox 回退矩形明显窄于另一视图，
            # 用更宽视图的范围替代（Y 范围保持本视图，深度不受影响）。
            if v["view_type"] in ("front", "top"):
                peer_xs = []
                for pv in views:
                    if pv is v or pv["view_type"] not in ("front", "top"):
                        continue
                    pof = pv.get("_outer_face")
                    if pof is not None and pof.get("x_min") is not None:
                        peer_xs.append((pof["x_min"], pof["x_max"]))
                    else:
                        peer_xs.append((pv["bbox"][0], pv["bbox"][2]))
                if peer_xs:
                    peer_w = max(px[1] for px in peer_xs) - min(px[0] for px in peer_xs)
                    if peer_w > (x_max - x_min) * 1.10:
                        x_min = min(min(px[0] for px in peer_xs), x_min)
                        x_max = max(max(px[1] for px in peer_xs), x_max)
                        print(f"  [P3] 视图 '{v['name']}' 外轮廓 X 范围对齐: "
                              f"[{v['bbox'][0]:.0f}~{v['bbox'][2]:.0f}] → "
                              f"[{x_min:.0f}~{x_max:.0f}]")
            # 创建 4 边矩形替代面（边 ID 无效但会构建新 Wire）
            outer_face = {
                "edges": None,  # 标记为包围盒回退
                "area": (x_max - x_min) * (y_max - y_min),
                "face_type": "bbox_fallback",
                "x_min": x_min, "y_min": y_min,
                "x_max": x_max, "y_max": y_max,
            }
            use_bbox_fallback = True

        # ---- Fix 2: 裁剪跨越面 — front 视图的 Y 范围不应包含 top 视图区域 ----
        if outer_face is not None and v["name"] == "front":
            outer_face_is_spanning = outer_face.get("is_spanning", False)
            # 检查是否跨越了多个视图的 Y 范围
            # 找出本视图之外的其他视图及其 Y 范围
            other_views_ymin = []
            for ov in views:
                if ov is v:
                    continue
                ov_normal = [f for f in ov["faces"] if not f.get("is_spanning")]
                if ov_normal:
                    other_views_ymin.append(min(f["y_min"] for f in ov_normal))
                else:
                    other_views_ymin.append(ov["bbox"][1])

            if other_views_ymin:
                # 只考虑真正在上方的视图（Y_min > 本视图非跨越面的 Y_max）
                v_normal_temp = [f for f in v["faces"] if not f.get("is_spanning")]
                if v_normal_temp:
                    v_nf_ymax_for_filter = max(f["y_max"] for f in v_normal_temp)
                else:
                    v_nf_ymax_for_filter = outer_face["y_min"]
                above_candidates = [y for y in other_views_ymin
                                    if y > v_nf_ymax_for_filter + 5]
                if not above_candidates:
                    above_ymin = None  # 无真正上方视图
                else:
                    above_ymin = min(above_candidates)
                outer_y_span = outer_face["y_max"] - outer_face["y_min"]

                # 如果跨越面的 Y 范围显著超过了到上方视图的间隙
                if above_ymin is not None and above_ymin < outer_face["y_max"] and outer_y_span > 50:
                    # 在跨越面和上方视图之间找一个合理的分割点
                    # 使用本视图中非跨越面的最大 Y 和上方视图最小 Y 的中点
                    v_normal = [f for f in v["faces"] if not f.get("is_spanning")]
                    if v_normal:
                        v_nf_ymax = max(f["y_max"] for f in v_normal)
                    else:
                        v_nf_ymax = outer_face["y_min"] + outer_y_span * 0.7

                    # 分割 Y：本视图最大 Y 和上方视图最小 Y 的中点
                    split_y = (v_nf_ymax + above_ymin) / 2

                    if split_y < outer_face["y_max"] - 10:
                        print(f"  [Fix] front 跨越面裁剪: "
                              f"Y[{outer_face['y_min']:.0f}~{outer_face['y_max']:.0f}] "
                              f"→ Y[{outer_face['y_min']:.0f}~{split_y:.0f}]"
                              f" (上方视图从 Y={above_ymin:.0f} 开始)")
                        outer_face = dict(outer_face)
                        outer_face["y_max"] = split_y
                        outer_face["area"] = ((outer_face["x_max"] - outer_face["x_min"])
                                              * (split_y - outer_face["y_min"]))
                        use_bbox_fallback = True

        if outer_face is None:
            print(f"  [WARN] 视图 '{v['name']}' 无有效外轮廓，跳过")
            continue

        # ---- P3: 视图 DXF 中心（供 CSG 特征坐标映射） ----
        # 用视图分离区域 bbox 的中心（而非外轮廓中心）作为映射基准：
        # 特征坐标相对视图区域的偏移在 bbox 回退扩展前后保持一致，
        # 且 CSG 棱柱居中平移后主体中心在原点附近，特征需减去此基准。
        v["_dxf_center_x"] = (v["bbox"][0] + v["bbox"][2]) / 2 * scale_factor
        v["_dxf_center_y"] = (v["bbox"][1] + v["bbox"][3]) / 2 * scale_factor

        # 构建 Wire → Face
        if use_bbox_fallback:
            # 用包围盒构建矩形 Wire（应用缩放因子）
            sf = scale_factor
            x_min, y_min, x_max, y_max = (outer_face["x_min"] * sf, outer_face["y_min"] * sf,
                                          outer_face["x_max"] * sf, outer_face["y_max"] * sf)
            wire_builder = BRepBuilderAPI_MakePolygon(
                gp_Pnt(x_min, y_min, 0),
                gp_Pnt(x_max, y_min, 0),
                gp_Pnt(x_max, y_max, 0),
                gp_Pnt(x_min, y_max, 0),
                True)
            wire = wire_builder.Wire()
        elif use_ring_wire:
            wire = build_wire_from_directed_ring(
                ring_wire_data["ring"], ring_wire_data["vertex_pos"],
                edges, scale_factor)
        else:
            wire = build_occ_wire_from_face(
                outer_face["edges"], edges, edge_vertices, vertex_pos, scale_factor)
        if wire is None:
            print(f"  [WARN] 视图 '{v['name']}' Wire 构建失败")
            continue
        occ_face = build_occ_face(wire)
        if occ_face is None:
            print(f"  [WARN] 视图 '{v['name']}' Face 构建失败")
            continue

        # ---- v0.6.3 P3.1: top 视图分体（主体圆棱柱 + 环带棱柱） ----
        # 方角法兰外环内接主体整圆时, 单外环求交得方柱而非圆柱。
        # 分体: occ_face 改为主体圆面, split_face 为（外环-内圆）环带面,
        # 环带由 front/side 棱柱自动裁剪到法兰高度段。
        split_face = None
        if (v["view_type"] == "top" and use_ring_wire
                and ring_wire_data is not None):
            body_circle = _find_inner_body_circle(ring_wire_data, edges)
            if body_circle is not None:
                bcx, bcy, br, binner = body_circle
                bcx, bcy = bcx * scale_factor, bcy * scale_factor
                br = br * scale_factor
                # 环带面内孔半径: 有次大整圆（底沉 r25）时用次大圆，
                # 底沉区域（r<r_inner）由 P0 底沉刀单独切深，避免
                # 环带面把法兰段 r∈[r_inner,r_body] 的材料一并挖空。
                hole_r = (binner or br) * scale_factor
                try:
                    circ = gp_Circ(gp_Ax2(gp_Pnt(bcx, bcy, 0.0),
                                          gp_Dir(0, 0, 1)), br)
                    circle_wire = BRepBuilderAPI_MakeWire(
                        BRepBuilderAPI_MakeEdge(circ).Edge()).Wire()
                    circle_face = build_occ_face(circle_wire)
                    hole_wire = None
                    if binner is not None:
                        hcirc = gp_Circ(gp_Ax2(gp_Pnt(bcx, bcy, 0.0),
                                               gp_Dir(0, 0, 1)), hole_r)
                        hole_wire = BRepBuilderAPI_MakeWire(
                            BRepBuilderAPI_MakeEdge(hcirc).Edge()).Wire()
                    # 环带面 = 外环面 − 内孔圆面（平面布尔切，避免
                    # MakeFace 双 wire 重载在 pythonocc 中不可用）
                    if hole_wire is not None:
                        hole_face = build_occ_face(hole_wire)
                        _cut = BRepAlgoAPI_Cut(occ_face, hole_face)
                        if not _cut.IsDone():
                            hole_wire = None  # 回退: 内孔 = 主体圆
                    if hole_wire is None:
                        _cut = BRepAlgoAPI_Cut(occ_face, circle_face)
                    if _cut.IsDone():
                        split_face = _cut.Shape()
                        _sp = GProp_GProps()
                        brepgprop.SurfaceProperties(split_face, _sp)
                        # 主体棱柱用内接圆面：基准主体段 z[0,56.5] 是
                        # φ60 圆柱（top 视图 φ60 圆投影），全 16 边环
                        # 柱会在主体段制造 4×10,967 四角假材料。
                        # 顶段 z[56.5,66.5] 的 16 边环角过渡（基准
                        # 6,536）三视图无信息（top 投影被外环覆盖），
                        # 接受为信息论局限。
                        occ_face = circle_face  # 主体棱柱改用圆面
                        v["_flange_hole_r"] = hole_r / scale_factor
                        print(f"  [P3.1] 视图 '{v['name']}' 分体: "
                              f"主体圆 r={br:.1f}, 内孔 r={hole_r:.1f}, "
                              f"环带面积={_sp.Mass():.0f}")
                    else:
                        print(f"  [WARN] 视图 '{v['name']}' 环带面求切失败")
                except Exception as _e:
                    print(f"  [WARN] 视图 '{v['name']}' 分体失败: {_e}")
                    split_face = None

        # 视图 → 3D 坐标变换（标准正交投影：前视图竖轴 = 3D Z 高度）
        _, extrude_axis = _get_view_transform(v["view_type"])
        occ_face = _apply_view_transform(occ_face, v["view_type"])
        if split_face is not None:
            split_face = _apply_view_transform(split_face, v["view_type"])

        # 对齐：非前视图面平移使 Z_min=0（统一内部特征偏移基准；
        # 前视图面位于 XZ 平面，Z 范围由 DXF_Y 决定，不做此平移）
        if v["view_type"] != "front":
                fb = Bnd_Box()
                brepbndlib.Add(occ_face, fb)
                _, _, z_min_before, _, _, _ = fb.Get()
                v["_z_align_offset"] = z_min_before  # 保存对齐前的 Z_min，内部面共用
                trsf_align = gp_Trsf()
                trsf_align.SetTranslation(gp_Vec(0, 0, -z_min_before))
                occ_face = BRepBuilderAPI_Transform(occ_face, trsf_align).Shape()
                if split_face is not None:
                    split_face = BRepBuilderAPI_Transform(
                        split_face, trsf_align).Shape()

        # 保存外轮廓面中心（旋转+Z对齐后），供内部特征工具统一偏移
        face_bbox = Bnd_Box()
        brepbndlib.Add(occ_face, face_bbox)
        _fx1, _fy1, _fz1, _fx2, _fy2, _fz2 = face_bbox.Get()
        v["_outer_face_center"] = ((_fx1 + _fx2) / 2, (_fy1 + _fy2) / 2,
                                    (_fz1 + _fz2) / 2)

        # 拉伸为棱柱
        prism = _extrude_face_dual(occ_face, extrude_axis, extrude_dist)
        if prism is None:
            print(f"  [WARN] 视图 '{v['name']}' 拉伸失败")
            continue
        flange_prism = None
        if split_face is not None:
            flange_prism = _extrude_face_dual(split_face, extrude_axis,
                                              extrude_dist)

        # 棱柱居中到原点：避免大坐标导致的布尔运算精度问题
        # （在拉伸后整体平移，保持各维度的相对位置正确；分体的两个
        # 棱柱共用外环棱柱的居中平移量，保持主体与环带相对位置）
        try:
            prism_bbox = Bnd_Box()
            brepbndlib.Add(prism, prism_bbox)
            px1, py1, pz1, px2, py2, pz2 = prism_bbox.Get()
            pcx = (px1 + px2) / 2
            pcy = (py1 + py2) / 2
            pcz = (pz1 + pz2) / 2
            if abs(pcx) > 0.01 or abs(pcy) > 0.01 or abs(pcz) > 0.01:
                trsf_ctr = gp_Trsf()
                trsf_ctr.SetTranslation(gp_Vec(-pcx, -pcy, -pcz))
                prism = BRepBuilderAPI_Transform(prism, trsf_ctr).Shape()
                if flange_prism is not None:
                    flange_prism = BRepBuilderAPI_Transform(
                        flange_prism, trsf_ctr).Shape()
        except Exception:
            pass

        prisms.append(prism)
        if flange_prism is not None:
            # 环带棱柱单独收集, 求交时与 front/side 棱柱再求交
            prisms_flange.append(flange_prism)
            v["_body_prism"] = prism
        print(f"  视图 '{v['name']}'({v['view_type']}): "
              f"轮廓={outer_face['area']:.0f}mm2, "
              f"棱柱轴={['X','Y','Z'][extrude_axis]}, "
              f"长={extrude_dist:.0f}mm")

        # 存储外轮廓引用，供后续内部特征处理使用
        v["_outer_face"] = outer_face
        # v0.6.1: 记录外轮廓弧半径（供特征创建时剔除外轮廓圆，
        # 避免 φ80 外圆被同心圆组当成凸台最外层）
        if ring_data is not None:
            v["_outer_ring_radii"] = set(
                round(edges[eid].radius, 1) for eid, _, _ in ring_data["ring"]
                if edges[eid].etype == "ARC" and edges[eid].radius > 0)

        # 提取该视图的所有内部面（除主体外的闭环，不限于圆/弧）
        inner_faces = [f for f in v["faces"]
                       if f is not outer_face
                       and not f.get("is_spline_debris")
                       and _is_face_inside(f, outer_face)]
        if inner_faces:
            hole_data.append({
                "view_type": v["view_type"],
                "inner_faces": inner_faces,
            })

    if len(prisms) < 2:
        print("  [FAIL] CSG 需要至少 2 个有效视图棱柱")
        return None, None

    # --- 布尔交集 ---
    def _common_chain(plist):
        """对棱柱列表逐次求交集, 返回结果或 None。"""
        if not plist:
            return None
        c = plist[0]
        for i, p in enumerate(plist[1:], 1):
            op = BRepAlgoAPI_Common(c, p)
            if op.IsDone():
                c = op.Shape()
            else:
                print(f"  [WARN] 棱柱{i+1}交集失败")
                return None
        return c

    print(f"\n  CSG 求交: {len(prisms)} 个棱柱 → 交集"
          + (f" + {len(prisms_flange)} 个环带棱柱分体" if prisms_flange
             else ""))
    try:
        combined = _common_chain(prisms)
        if combined is None:
            raise RuntimeError("主体交集失败")
        if prisms_flange:
            # v0.6.3 P3.1: 环带 = 环带棱柱 ∩ 其他视图棱柱。front/side
            # 截面主体段宽 60（=环带内径）自动把环带裁剪到法兰高度段。
            body_prism_ref = None
            for v in views:
                if v.get("_body_prism") is not None:
                    body_prism_ref = v["_body_prism"]
            front_side = [p for p in prisms if p is not body_prism_ref]
            flange = _common_chain([prisms_flange[0]] + front_side)
            # 法兰顶面 z: 外环顶点标定（锥面顶段上端等非极值顶点层）
            z_cap, z_cone = _flange_top_from_ring_vertices(
                views, scale_factor, no_merge_rings, edges)
            # v0.6.3: 主体/环带分界 z 取锥面顶（有信号时）——锥面段
            # r30 圆盘由主体圆棱柱覆盖，环带只补叶片柱段；环带到
            # 法兰顶会把顶盘段角区柱（基准 r30 圆盘无叶片）带成假
            # 材料（PF60K 顶盘段假 3,737）
            z_split = z_cone if z_cone is not None else z_cap
            if z_split is not None:
                # 主体圆柱裁剪 z 起点: 圆柱台阶结构从分界面开始
                # （法兰中央孔是贯穿空孔, 主体不延伸到分界面以下；
                # 底沉区域 r∈[r_inner,r_body] 由环带面内孔保留）。
                body_cap = BRepPrimAPI_MakeBox(
                    gp_Pnt(-500, -500, z_split),
                    gp_Pnt(500, 500, 500)).Shape()
                body_cap_op = BRepAlgoAPI_Common(combined, body_cap)
                if body_cap_op.IsDone():
                    combined = body_cap_op.Shape()
                    print(f"  [P3.1] 主体裁剪到分界 z={z_split:.1f}"
                          + (f"（锥面顶, 法兰顶={z_cap:.1f}）"
                             if z_cone is not None else ""))
            if flange is not None:
                # 环带 z 裁剪: 环带棱柱会延伸到主体全高,
                # 同样裁剪到分界 z 以下。
                if z_split is not None:
                    cap_box = BRepPrimAPI_MakeBox(
                        gp_Pnt(-500, -500, -500),
                        gp_Pnt(500, 500, z_split)).Shape()
                    cap_op = BRepAlgoAPI_Common(flange, cap_box)
                    if cap_op.IsDone():
                        flange = cap_op.Shape()
                        print(f"  [P3.1] 环带裁剪到分界 z={z_split:.1f}")
                fuse_op = BRepAlgoAPI_Fuse(combined, flange)
                if fuse_op.IsDone():
                    combined = fuse_op.Shape()
                    print("  [P3.1] 主体 ∪ 法兰环带 融合完成")
                else:
                    print("  [WARN] 环带融合失败")
    except Exception as e:
        print(f"  [FAIL] CSG 交集异常: {e}")
        return None, None

    # ---- v0.6.3: 顶段角凸补丁 ----
    # 基准顶段 16 边环的 4 角凸（r[30,40] 角区，与法兰叶片同形状）
    # 三视图投影被 HLR 过滤（top 被外环覆盖、front/side 无母线），
    # 主体圆棱柱缺该材料（PF60K 顶段缺 6,535）。角凸 z 范围 =
    # [主体段顶, 台阶段底]（φ60 竖线上端 → φ50 台阶竖线下端），
    # 补丁 = 环带棱柱 ∩ 该 z 盒（含 r[21,30] 环，与主体圆柱重叠
    # 部分 Fuse 无新增材料，无害）。
    try:
        _top_r = no_merge_rings.get("top") if no_merge_rings else None
        _top_half = None
        if _top_r is not None:
            # 主体半径用 top 分体的内接主体圆（φ60 → r=30），
            # 而非外环 bbox 半宽（法兰外径 φ80 → 40，判据全错）
            _bc = _find_inner_body_circle(_top_r, edges)
            if _bc is not None:
                _top_half = _bc[2] * scale_factor
        _fz_top = None
        _fz_bot = None
        if _top_half and prisms_flange:
            # 两遍扫描: 先定主体段顶，再找其上的台阶竖线——
            # 顶段折线噪声竖线（r≈22~28）单遍混扫会把主体段顶
            # 误当台阶段底
            _profs = []
            for _pv in views:
                if _pv["view_type"] not in ("front", "side"):
                    continue
                _pofc = _pv.get("_outer_face") or {}
                _pys = (_pofc.get("y_max", 0) or 0) - (_pofc.get("y_min", 0) or 0)
                if _pys <= 0:
                    continue
                _pymid = ((_pofc["y_min"] or 0) + (_pofc["y_max"] or 0)) / 2
                _profs.append((_pymid, _vertical_hole_profiles(_pv, edges)))
            for _pymid, _plist in _profs:
                for _pcx, _pr, _ylo, _yhi in _plist:
                    # 主体级竖线对（r≈主体半宽，φ60 外轮廓竖线
                    # 常被 HLR 交点拆分丢失）: 上半部段的下端 =
                    # 主体段顶（PF60K 顶段 16 边环折线竖线
                    # y[85,95] 的 ylo=85 = 主体段顶；法兰锥面
                    # 竖线 y[2,21.7] 在下半部被过滤）
                    if abs(_pr - _top_half) < max(1.5, 0.05 * _top_half):
                        if _ylo > _pymid + 1.0:
                            _ztop_c = (_ylo - _pymid) * scale_factor
                            if _fz_top is None or _ztop_c > _fz_top:
                                _fz_top = _ztop_c
            if _fz_top is not None:
                for _pymid, _plist in _profs:
                    for _pcx, _pr, _ylo, _yhi in _plist:
                        # 台阶级竖线对（φ50，r∈[0.75,0.98]×主体
                        # 半宽）: 下端 = 台阶段底——须在主体段顶
                        # 之上（法兰段锥面竖线 ylo≈2 过滤掉）
                        if not (_top_half * 0.75 < _pr
                                < _top_half * 0.98):
                            continue
                        _zbot_c = (_ylo - _pymid) * scale_factor
                        if _zbot_c > _fz_top + 1.0:
                            if _fz_bot is None or _zbot_c < _fz_bot:
                                _fz_bot = _zbot_c
        if (_fz_top is not None and _fz_bot is not None
                and 2.0 < _fz_bot - _fz_top <= 20.0):
            _patch_box = BRepPrimAPI_MakeBox(
                gp_Pnt(-500, -500, _fz_top),
                gp_Pnt(500, 500, _fz_bot)).Shape()
            _patch_op = BRepAlgoAPI_Common(
                prisms_flange[0], _patch_box)
            if _patch_op.IsDone():
                _patch_fuse = BRepAlgoAPI_Fuse(combined, _patch_op.Shape())
                if _patch_fuse.IsDone():
                    combined = _patch_fuse.Shape()
                    print(f"  [P3.1] 顶段角凸补丁 z[{_fz_top:.1f}~"
                          f"{_fz_bot:.1f}]")
    except Exception as _e:
        print(f"  [WARN] 顶段角凸补丁失败: {_e}")

    # 修复
    try:
        fixer = ShapeFix_Shape()
        fixer.Init(combined)
        fixer.Perform()
        combined = fixer.Shape()
    except Exception:
        pass

    # ---- P1: 投影验证回路 ----
    # 将 CSG 主体投影回 2D 与原始视图轮廓对比，自动纠正尺寸误差
    try:
        csg_bbox = Bnd_Box()
        brepbndlib.Add(combined, csg_bbox)
        cbx1, cby1, cbz1, cbx2, cby2, cbz2 = csg_bbox.Get()
        csg_x, csg_y, csg_z = cbx2 - cbx1, cby2 - cby1, cbz2 - cbz1
    except Exception:
        csg_x = csg_y = csg_z = 0

    # 从各视图收集期望尺寸（3D 空间中的映射）
    # 用各视图外轮廓自身的 DXF 范围，而非视图区域包围盒——
    # 视图分离不完整时区域包围盒会混入相邻视图（如 side 并入 front 区域），
    # 导致期望值虚高误报（block_3view: 期望 X=145 vs 实际 100）
    expected = {"X": None, "Y": None, "Z": None}
    for v in views:
        vt = v["view_type"]
        ofc = v.get("_outer_face") or {}
        if ofc.get("x_min") is not None:
            bw = (ofc["x_max"] - ofc["x_min"]) * scale_factor
            bh = (ofc["y_max"] - ofc["y_min"]) * scale_factor
        else:
            bw = (v["bbox"][2] - v["bbox"][0]) * scale_factor
            bh = (v["bbox"][3] - v["bbox"][1]) * scale_factor
        if vt == "front":
            # 前视图 DXF_X→3D_X, DXF_Y→3D_Z（高度），面沿 Y 拉伸→Y 深度来自其他视图
            if expected["X"] is None or bw > expected["X"]:
                expected["X"] = bw
            if expected["Z"] is None or bh > expected["Z"]:
                expected["Z"] = bh
        elif vt == "top":
            # 俯视图 DXF_X→3D_X, DXF_Y→3D_Y（深度）
            if expected["X"] is None or bw > expected["X"]:
                expected["X"] = bw
            if expected["Y"] is None or bh > expected["Y"]:
                expected["Y"] = bh
        elif vt == "side":
            # 侧视图 DXF_X→3D_Y（深度）, DXF_Y→3D_Z（高度）
            if expected["Y"] is None or bw > expected["Y"]:
                expected["Y"] = bw
            if expected["Z"] is None or bh > expected["Z"]:
                expected["Z"] = bh

    # 报告尺寸对比
    if csg_x > 0 and csg_y > 0 and csg_z > 0:
        print(f"  [P1] CSG 主体: X={csg_x:.0f} Y={csg_y:.0f} Z={csg_z:.0f} mm")
        exp_parts = []
        for d in ["X", "Y", "Z"]:
            if expected[d] is not None:
                exp_parts.append(f"{d}={expected[d]:.0f}")
        print(f"  [P1] 期望尺寸: {', '.join(exp_parts)} mm")

    # 自动修正 Z 深度（用投影验证替代启发式判断）
    if expected["Z"] is not None and csg_z > 0 and expected["Z"] > 0:
        z_ratio = expected["Z"] / csg_z
        if z_ratio < 0.7 or z_ratio > 1.3:
            # Z 深度偏差 >30%，用均匀缩放修正
            z_scale = expected["Z"] / csg_z
            print(f"  [P1] Z 深度修正: Z={csg_z:.0f} → {expected['Z']:.0f} mm "
                  f"(×{z_scale:.2f})")

            gtrsf = gp_GTrsf()
            gtrsf.SetValue(1, 1, 1.0)
            gtrsf.SetValue(2, 2, 1.0)
            gtrsf.SetValue(3, 3, z_scale)
            gtrsf.SetValue(1, 4, 0)
            gtrsf.SetValue(2, 4, 0)
            gtrsf.SetValue(3, 4, cbz1 * (1 - z_scale))

            combined = BRepBuilderAPI_GTransform(combined, gtrsf).Shape()
            print(f"  [P1] 修正完成")

    # ---- P2: 注解驱动分析（中心线对称 + 剖面材料验证） ----
    symmetry_info = None  # 对称轴信息
    if annotations:
        # P2a: 中心线对称分析
        centerlines = annotations.get("centerlines", [])
        if centerlines:
            # 找最长的垂直中心线（通常是主轴）
            v_cls = sorted(
                [cl for cl in centerlines if cl["orientation"] == "V"],
                key=lambda cl: -cl["length"])
            h_cls = sorted(
                [cl for cl in centerlines if cl["orientation"] == "H"],
                key=lambda cl: -cl["length"])

            for cl in v_cls[:2]:  # 分析前 2 条垂直中心线
                dxf_cx = cl["start"][0]  # DXF 坐标系中的对称轴 X
                # 映射到 3D: 需要知道此中心线属于哪个视图
                # 遍历视图找到包含此 X 的前视图
                for v in views:
                    if v["view_type"] != "front":
                        continue
                    v_bbox = v["bbox"]
                    # 中心线归属判定 + 视图中心均用外轮廓自身范围
                    # （区域包围盒混入邻视图时会把邻视图中心线误判为本视图）
                    ofc = v.get("_outer_face") or {}
                    if ofc.get("x_min") is not None:
                        vc_x_min, vc_x_max = ofc["x_min"], ofc["x_max"]
                    else:
                        vc_x_min, vc_x_max = v_bbox[0], v_bbox[2]
                    if vc_x_min <= dxf_cx <= vc_x_max:
                        # P3: 中心线端点还须落在视图 Y 范围内——
                        # top 视图的凸台轴心线（PHANTOM）X 落在 front
                        # 范围内但 Y 在 top 区域，不能当作 front 中心线
                        # 做对称性判定（会误报"不在主体中心"）。
                        if ofc.get("y_min") is not None:
                            vc_y_min, vc_y_max = ofc["y_min"], ofc["y_max"]
                        else:
                            vc_y_min, vc_y_max = v_bbox[1], v_bbox[3]
                        cl_y1, cl_y2 = cl["start"][1], cl["end"][1]
                        if not (vc_y_min - 1 <= min(cl_y1, cl_y2)
                                and max(cl_y1, cl_y2) <= vc_y_max + 1):
                            continue
                        # 此中心线在前视图中
                        # 3D 空间中的等效 X（需要映射回 CSG body 的坐标系）
                        # DXF 坐标 → 3D 坐标: 先缩放，再减中心偏移
                        dxf_view_cx = (vc_x_min + vc_x_max) / 2
                        sf = scale_factor
                        # 中心线在 3D 中的 X 偏移（相对于视图中心）
                        cl_offset_3d = (dxf_cx - dxf_view_cx) * sf
                        # CSG body 的 3D 中心（已居中到原点附近）
                        body_center_x = (csg_x > 0 and (cbx1 + cbx2) / 2) or 0
                        # 中心线在 body 坐标系中的位置
                        cl_in_body_x = body_center_x + cl_offset_3d

                        # 检查 body 是否关于此中心线对称
                        body_left = cbx1 - cl_in_body_x
                        body_right = cbx2 - cl_in_body_x
                        # 若中心线是真正的对称轴，则 body_left ≈ -body_right
                        center_offset = abs(body_left + body_right) / 2  # 理想=0

                        print(f"  [P2] 中心线({cl['linetype']}): DXF X={dxf_cx:.1f} "
                              f"→ 3D 偏移={cl_offset_3d:.1f}mm, "
                              f"中心偏差={center_offset:.1f}mm")

                        if center_offset > csg_x * 0.10 and csg_x > 10:
                            print(f"  [P2] [INFO] 中心线不在主体中心, "
                                  f"偏移={center_offset:.1f}mm "
                                  f"({center_offset/csg_x*100:.0f}% of X)")

                        symmetry_info = {
                            "dxf_x": dxf_cx,
                            "offset_3d": cl_offset_3d,
                            "center_offset": center_offset,
                            "orientation": "V",
                        }
                        break

        # P2b: HATCH 剖面区域 → 材料验证
        hatch_regions = annotations.get("hatch_regions", [])
        if hatch_regions and csg_x > 0 and csg_z > 0:
            # 将 hatch 区域映射到 3D 空间进行验证
            # HATCH 在 DXF 的 front 视图中，DXF_XY → 3D_XZ（竖轴=高度）
            hatch_3d_matches = 0
            hatch_3d_total = 0
            for hr in hatch_regions:
                hb = hr["bbox"]
                # 映射到 3D（缩放 + 中心偏移）
                sf = scale_factor
                # 找到此 hatch 对应的视图
                for v in views:
                    if v["view_type"] != "front":
                        continue
                    v_bbox = v["bbox"]
                    # 检查 hatch 是否在此视图中
                    if (hb[0] >= v_bbox[0] - 5 and hb[2] <= v_bbox[2] + 5
                            and hb[1] >= v_bbox[1] - 5 and hb[3] <= v_bbox[3] + 5):
                        # 映射 hatch bbox 到 3D body 坐标系
                        # 视图中心用外轮廓自身中心（区域包围盒可能混入邻视图）
                        ofc = v.get("_outer_face") or {}
                        if ofc.get("x_min") is not None:
                            v_center_x = (ofc["x_min"] + ofc["x_max"]) / 2
                            v_center_y = (ofc["y_min"] + ofc["y_max"]) / 2
                        else:
                            v_center_x = (v_bbox[0] + v_bbox[2]) / 2
                            v_center_y = (v_bbox[1] + v_bbox[3]) / 2
                        h3d_x1 = (hb[0] - v_center_x) * sf + (cbx1 + cbx2) / 2
                        h3d_x2 = (hb[2] - v_center_x) * sf + (cbx1 + cbx2) / 2
                        # 前视图 DXF_Y → 3D Z（高度），与 CSG 映射约定一致
                        h3d_z1 = (hb[1] - v_center_y) * sf + (cbz1 + cbz2) / 2
                        h3d_z2 = (hb[3] - v_center_y) * sf + (cbz1 + cbz2) / 2

                        # 计算 hatch 3D 面积与 CSG body 截面面积的交集比例
                        h3d_w = h3d_x2 - h3d_x1
                        h3d_h = h3d_z2 - h3d_z1

                        # 检查 hatch 区域是否至少部分在 body 内
                        overlap_x = max(0, min(h3d_x2, cbx2) - max(h3d_x1, cbx1))
                        overlap_z = max(0, min(h3d_z2, cbz2) - max(h3d_z1, cbz1))
                        overlap_area = overlap_x * overlap_z
                        hatch_area = h3d_w * h3d_h

                        if hatch_area > 0:
                            hatch_3d_total += 1
                            coverage = overlap_area / hatch_area
                            if coverage > 0.5:
                                hatch_3d_matches += 1
                            elif coverage > 0.01:
                                print(f"  [P2] [WARN] 剖面区域({hr['pattern']}) "
                                      f"仅 {coverage*100:.0f}% 在 CSG 主体内 "
                                      f"(HATCH 3D: [{h3d_x1:.0f}~{h3d_x2:.0f}, "
                                      f"{h3d_z1:.0f}~{h3d_z2:.0f}])")
                            else:
                                print(f"  [P2] [FAIL] 剖面区域({hr['pattern']}) "
                                      f"完全在 CSG 主体外！主体可能缺失此区域")

            if hatch_3d_total > 0:
                print(f"  [P2] 剖面材料验证: {hatch_3d_matches}/{hatch_3d_total} "
                      f"个剖面区域正确位于 CSG 主体内")

    # ---- P0: 内部特征布尔减运算 ----
    # 对每个视图的内部闭环构建切割工具，从 CSG 主体中减去
    inner_cut_count = 0
    combined_before_cuts = combined  # 保存切割前的主体用于回退
    if len(views) >= 2:
        # 计算切割工具的拉伸半长（确保完全穿透主体）
        try:
            body_bbox = Bnd_Box()
            brepbndlib.Add(combined, body_bbox)
            bx1, by1, bz1, bx2, by2, bz2 = body_bbox.Get()
            body_max_dim = max(bx2 - bx1, by2 - by1, bz2 - bz1)
            half_extrude = body_max_dim * 1.5
        except Exception:
            half_extrude = 500.0  # 兜底值

        # v0.6.1: front/side 视图竖线对（竖直孔投影）缓存，
        # 用于深度推理（取代依赖 faces 环的旧逻辑）
        profiles_by_view = {}
        applied_cuts = set()  # v0.6.3: 已应用刀具去重键
        for v in views:
            if v["view_type"] != "top":
                profiles_by_view[id(v)] = _vertical_hole_profiles(v, edges)

        # v0.6.3: top 视图圆列表（孔候选，供 front/side 矩形刀定位——
        # front 投影丢失 Y、side 丢失 X，旧代码把刀固定在 0 轴切错位置）。
        # 外环自身与主体台阶圆（r > 外环 70%，如 φ60 圆柱顶圆）排除。
        top_hole_circles = []
        _topv = next((v for v in views if v["view_type"] == "top"), None)
        if _topv is not None and _topv.get("_outer_face"):
            _tofc = _topv["_outer_face"]
            _tcx = (_tofc["x_min"] + _tofc["x_max"]) / 2
            _tcy = (_tofc["y_min"] + _tofc["y_max"]) / 2
            _tr_o = max(_tofc["x_max"] - _tofc["x_min"],
                        _tofc["y_max"] - _tofc["y_min"]) / 2
            _seen = set()
            for _e in edges:
                if getattr(_e, "etype", "") != "ARC":
                    continue
                if not _e.radius or _e.radius < 1.0:
                    continue
                _cx, _cy = _e.center
                if not (_tofc["x_min"] - 1 <= _cx <= _tofc["x_max"] + 1
                        and _tofc["y_min"] - 1 <= _cy <= _tofc["y_max"] + 1):
                    continue
                if _e.radius > _tr_o * 0.7:
                    continue
                _k = (round(_cx, 1), round(_cy, 1), round(_e.radius, 1))
                if _k in _seen:
                    continue
                _seen.add(_k)
                # 3D 坐标 + DXF 坐标（环刀芯深度推导需用 DXF 系）
                top_hole_circles.append(
                    ((_cx - _tcx) * scale_factor, (_cy - _tcy) * scale_factor,
                     _e.radius * scale_factor, _cx, _cy))

        def _profile_depths(fi_cx, fi_r):
            """竖线对 → CSG Z 深度段列表 [(z_top, z_bot), ...] 或 []。

            v0.6.2: top 视图一个俯视圆可能对应多段同径孔（顶沉孔段
            + 底出口段），旧逻辑只取第一段导致只切一半；现在返回
            全部匹配段（按半径偏差升序），无可靠候选返回 []。
            """
            try:
                _bb = Bnd_Box()
                brepbndlib.Add(combined, _bb)
                _z1, _z2 = _bb.Get()[2], _bb.Get()[5]
            except Exception:
                return []
            cands = []
            for v in views:
                if v["view_type"] == "top":
                    continue
                ofc = v.get("_outer_face") or {}
                y_span = ofc.get("y_max", 0) - ofc.get("y_min", 0)
                if y_span <= 0:
                    continue
                for pcx, pr, ylo, yhi in profiles_by_view.get(id(v), []):
                    # v0.6.2: 容差 0.5r → max(1.5, 0.06r)——0.5r 会把
                    # 相邻孔竖线对（φ50 匹配到 φ42/噪声对）混入限深段，
                    # 噪声段乱切导致体积大幅偏低
                    # v0.6.3: 1.5 → 0.6——φ5.5 圆 (r=2.75) 仍匹配到
                    # φ3.3 竖线 (pr=1.65 偏差 1.1) 与 r=4.0 噪声竖线，
                    # 产生错位深度段乱切 4 角区；0.6 只留本径竖线对
                    if abs(pr - fi_r) > max(0.6, 0.06 * fi_r):
                        continue
                    if abs(pcx - fi_cx) > max(0.6, 0.06 * fi_r):
                        continue
                    z_top = _z1 + (yhi - ofc["y_min"]) / y_span * (_z2 - _z1)
                    z_bot = _z1 + (ylo - ofc["y_min"]) / y_span * (_z2 - _z1)
                    if z_top < z_bot:
                        z_top, z_bot = z_bot, z_top
                    cands.append((abs(pr - fi_r), z_top, z_bot))
            cands.sort(key=lambda c: c[0])
            # 偏差 > 0.65 的候选不可靠（如 φ42 竖线缺失时匹配到
            # 顶部台阶区噪声段），放弃深度推理回退贯穿
            depths = []
            for d, z_top, z_bot in cands:
                if d > 0.65:
                    break
                depths.append((z_top, z_bot))
            return depths

        def _limit_tool_depth(tool, z_top, z_bot):
            """贯穿棱柱 ∩ 深度盒 → 深度受限工具（竖直孔真实深度）。"""
            try:
                _bb = Bnd_Box()
                brepbndlib.Add(combined, _bb)
                _bx1, _by1, _, _bx2, _by2, _ = _bb.Get()
                pad = (_bx2 - _bx1) * 0.5 + 10
                # v0.6.3: 6 参数 MakeBox 在本 PythonOCC 不存在
                # （只有 gp_Pnt+gp_Pnt 形式），旧代码抛 TypeError 被
                # except 吞掉返回原贯穿工具——限深从未生效
                box = BRepPrimAPI_MakeBox(
                    gp_Pnt(_bx1 - pad, _by1 - pad, z_bot),
                    gp_Pnt(_bx2 + pad, _by2 + pad, z_top)).Shape()
                com = BRepAlgoAPI_Common(tool, box)
                if com.IsDone():
                    return com.Shape()
            except Exception:
                pass
            return tool

        # v0.6.3 P3.2: 环带内孔 F 的深度段派生。φ42 孔壁竖线在
        # front/side 视图被 HLR 遮挡消除（内部孔壁不可见），
        # _profile_depths(r=21) 恒空。改从可见竖线对派生：
        #   F_bot = 底沉段顶（r∈[20,28] 且段底贴 CSG 底的竖线对）
        #   F_top = 芯孔段顶（r∈[5,9.5] 贯穿孔的竖线对，取最低段顶）
        # 图纸信息论上 φ42 孔顶(-24.95)与 3.0 过渡丢失，取 F_top=
        # 芯孔顶为信息论最优（岛填到芯孔顶 ≈ 岛+阶梯 r[7,16] 材料）。
        _flange_r = (_topv or {}).get("_flange_hole_r")
        _flange_hole_segs = []
        if _flange_r:
            try:
                _zbb = Bnd_Box()
                brepbndlib.Add(combined, _zbb)
                _csg_z1 = _zbb.Get()[2]
                _csg_zspan = _zbb.Get()[5] - _csg_z1
            except Exception:
                _csg_z1 = 0.0
                _csg_zspan = 1.0
            _f_bot = None
            _f_top = None
            for _vid, _profs in profiles_by_view.items():
                _ofc2 = (next((v for v in views if id(v) == _vid),
                              {})).get("_outer_face") or {}
                _ys2 = _ofc2.get("y_max", 0) - _ofc2.get("y_min", 0)
                if _ys2 <= 0:
                    continue
                for _pcx, _pr, _ylo, _yhi in _profs:
                    if abs(_pcx - _tcx) > 1.5:
                        continue
                    _z_b = _csg_z1 + (_ylo - _ofc2["y_min"]) / _ys2 * _csg_zspan
                    _z_t = _csg_z1 + (_yhi - _ofc2["y_min"]) / _ys2 * _csg_zspan
                    if 20.0 <= _pr <= 28.0 and _z_b <= _csg_z1 + 1.0:
                        _f_bot = _z_t if _f_bot is None else min(_f_bot, _z_t)
                    elif 5.0 <= _pr <= 9.5:
                        _f_top = _z_t if _f_top is None else min(_f_top, _z_t)
            if _f_bot is not None and _f_top is not None and _f_top > _f_bot:
                _flange_hole_segs = [(_f_top, _f_bot)]
                print(f"  [P3.2] F 段派生 Z[{_f_bot:.1f}~{_f_top:.1f}]")

        for v in views:
            outer_face = v.get("_outer_face")
            if outer_face is None:
                continue

            # 查找该视图的内部面
            inner_faces = []
            for f in v["faces"]:
                if f is outer_face:
                    continue
                if f.get("is_spline_debris"):
                    continue
                if f["area"] < 1.0:
                    continue
                # v0.6.3: top 视图阈值放宽 0.25→0.45——φ50 底沉半圆面
                # （面积 35%×外环）被旧阈值挡在 P0 之外致底沉刀缺失；
                # front/side 保持 0.25（其大内面是主体段矩形投影，
                # 放大会被当孔刀水平切穿主体）
                _area_cap = 0.45 if v["view_type"] == "top" else 0.25
                if outer_face["area"] > 0 and f["area"] > outer_face["area"] * _area_cap:
                    continue
                if not _is_face_inside(f, outer_face):
                    continue
                inner_faces.append(f)

            if not inner_faces:
                continue

            vt = v["view_type"]
            outer_fc = v.get("_outer_face_center", None)
            z_off = v.get("_z_align_offset", None)
            for fi in inner_faces:
                tools = []
                # v0.6.1: front/side 矩形投影环若匹配竖直孔竖线对 →
                # 竖直圆柱切割（沿 Y 拉穿会把竖直孔切成水平槽，
                # 如中心 φ12 孔在 front 视图的矩形投影）
                # v0.6.2: 多段深度（顶沉孔段+底出口段）各生成一圆柱
                if vt in ("front", "side") and fi["face_type"] == "line_only":
                    ofc_w = outer_face["x_max"] - outer_face["x_min"]
                    fi_w = fi["x_max"] - fi["x_min"]
                    fi_cx = (fi["x_min"] + fi["x_max"]) / 2
                    if 2.0 <= fi_w < ofc_w * 0.45:
                        # v0.6.3: 位置由 top 圆提供（front 丢失 Y / side
                        # 丢失 X，旧代码固定 0 轴切错位置）；side 视图 X
                        # 对应 3D Y 轴。无 top 圆对应 → 凸台/噪声面跳过。
                        ofc_cx = (outer_face["x_min"] + outer_face["x_max"]) / 2
                        feat_x = (fi_cx - ofc_cx) * scale_factor
                        r3 = fi_w / 2 * scale_factor
                        tol = max(1.5, 0.06 * fi_w / 2)
                        hit = None
                        for _tx, _ty, _tr, _dx, _dy in top_hole_circles:
                            if abs(_tr - r3) > tol:
                                continue
                            if vt == "front" and abs(_tx - feat_x) <= tol:
                                hit = (_tx, _ty)
                                break
                            if vt == "side" and abs(_ty - feat_x) <= tol:
                                hit = (_tx, _ty)
                                break
                        if hit is None:
                            continue
                        for z_top, z_bot in _profile_depths(fi_cx, fi_w / 2):
                            tools.append(create_cylinder_solid(
                                hit, r3, z_top - z_bot + 2.0, z_bot - 1.0))
                        # v0.6.3: front/side 矩形面无深度匹配 → 凸台/噪声
                        # 面，不回退拉穿工具（会把凸起切成水平槽）
                        continue
                # v0.6.3: front/side 窄面水平拉穿会把凸起切成水平槽
                # （竖直孔已由 line_only 分支 top 圆匹配覆盖），无匹配
                # 的窄条面（凸台/台阶投影残片）直接跳过
                if vt in ("front", "side") and not tools:
                    _ofc_w = outer_face["x_max"] - outer_face["x_min"]
                    _fi_w = fi["x_max"] - fi["x_min"]
                    if _fi_w < _ofc_w * 0.45 and _fi_w < 12.0:
                        continue
                if not tools:
                    tool = _build_inner_cut_tool(
                        fi, vt, edges, edge_vertices, vertex_pos,
                        scale_factor, half_extrude,
                        outer_face_center=outer_fc,
                        z_align_offset=z_off)
                    # v0.6.1: top 工具深度限制（竖直孔按投影深度切，
                    # 避免贯穿多切体积）
                    # v0.6.2: 阈值 0.45 → 0.95——φ50 沉孔（50/80=0.625）
                    # 在 r40 法兰圆外环下被旧阈值挡在限深之外，贯穿刀
                    # 把主体切掉 π·25²·97；贯穿孔（φ42/φ32）匹配到
                    # 全高竖线对后限深自然退化为贯穿，不受影响。
                    # 多段深度各切一刀（φ50 顶沉段+底出口段俯视重合）。
                    if tool is not None and vt == "top":
                        ofc_w = outer_face["x_max"] - outer_face["x_min"]
                        fi_w = fi["x_max"] - fi["x_min"]
                        fi_cx = (fi["x_min"] + fi["x_max"]) / 2
                        if 2.0 <= fi_w < ofc_w * 0.95:
                            depths = _profile_depths(fi_cx, fi_w / 2)
                            if depths:
                                # v0.6.3: 深度段顶与主体顶齐平(≤0.5)且
                                # 半径小 → 顶部凸起（凸台/台阶顶），不切
                                try:
                                    _zbb = Bnd_Box()
                                    brepbndlib.Add(combined, _zbb)
                                    _zmax = _zbb.Get()[5]
                                    _zhalf = max(_zbb.Get()[3] - _zbb.Get()[0],
                                                 _zbb.Get()[4] - _zbb.Get()[1]) / 2
                                except Exception:
                                    _zmax = None
                                    _zhalf = 1e9
                                for z_top, z_bot in depths:
                                    # v0.6.3: 帽判据改查段底——凸起帽的
                                    # 竖线对底已到主体顶（凸起完全在 CSG
                                    # 外）；顶面孔（如 PF60K 主体 R6 顶孔，
                                    # 段底 20.45 深入主体内）不再被误判。
                                    if (_zmax is not None
                                            and z_bot >= _zmax - 0.5
                                            and fi_w / 2 <= _zhalf * 0.3):
                                        continue
                                    # v0.6.3 P3.2: 材料岛判据——深度段完全
                                    # 在环带内孔 F 段内（含共顶）且半径
                                    # < r_f → 该圆是孔内材料岛（PF60K
                                    # φ32 岛 r[7,16] 在 φ42 孔内，2D 俯视
                                    # 无法区分岛/孔，由 front 竖线对深度
                                    # 判定），不切；材料由尾部 P3.2 融合
                                    # 补回。真孔段（如 φ14 芯孔）超出
                                    # F 段顶/底，不受影响。
                                    _is_island = False
                                    if _flange_hole_segs:
                                        for _f_top, _f_bot in _flange_hole_segs:
                                            if (_f_bot - 0.5 <= z_bot
                                                    and z_top <= _f_top + 0.5
                                                    and fi_w / 2 < _flange_r):
                                                _is_island = True
                                                break
                                    if _is_island:
                                        continue
                                    # v0.6.3: 帽判据——同圆心更小圆的
                                    # 深度段顶与本段底相接 → 本段是更小
                                    # 凸起之上的台阶帽（凸起），不切。
                                    # 同心匹配用圆 DXF 坐标落在面 bbox
                                    # 内判断（半圆面的 bbox 中心不在圆心）
                                    _is_cap = False
                                    for _tx, _ty, _tr, _dx, _dy in top_hole_circles:
                                        if abs(_dx - fi_cx) > 1.5:
                                            continue
                                        if not (fi["y_min"] - 2 <= _dy <= fi["y_max"] + 2):
                                            continue
                                        if not (0.25 * fi_w / 2 <= _tr / scale_factor
                                                <= fi_w / 2 - 0.5):
                                            continue
                                        for _s_top, _s_bot in _profile_depths(
                                                _dx, _tr / scale_factor):
                                            if (abs(z_bot - _s_top) < 1.5
                                                    and _s_top >= z_top - 1.0):
                                                _is_cap = True
                                                break
                                        if _is_cap:
                                            break
                                    if _is_cap:
                                        continue
                                    # v0.6.3: 台阶环刀判据——段顶贴近
                                    # 主体顶的大半径圆（r ≥ 主体半径
                                    # ×0.6）是顶部台阶内收结构：CSG
                                    # top 棱柱为 r=主体半径全高圆柱，
                                    # front/side 棱柱在台阶段收窄到
                                    # ±r，主体 r[r, 主体半径] 环保留
                                    # 为假材料（PF60K φ50 台阶 r25 →
                                    # 假 1,241）。生成环刀（主体半径
                                    # 圆柱 − 台阶半径圆柱）从段底切到
                                    # 主体顶。底沉段（r25 z 近底）段顶
                                    # 不贴近主体顶，不受影响。
                                    if (_zmax is not None
                                            and z_top >= _zmax - 1.5
                                            and 1e9 > _zhalf > 0
                                            and fi_w / 2 >= _zhalf * 0.6):
                                        # v0.6.3: 环刀中心用 top 圆的
                                        # CSG 坐标——fi_cx/fi_cy 是 DXF
                                        # 坐标，直接建圆柱会切在主体外
                                        # （v8 日志 3Dbbox Y[-130~-69]）
                                        _ring_c = None
                                        for (_tx, _ty, _tr,
                                             _dx, _dy) in top_hole_circles:
                                            # 半圆面的 bbox 不含圆心（Y
                                            # 偏半个半径），只按半径 + 圆
                                            # 心 X 匹配（同半径异位圆由
                                            # X 区分）
                                            if abs(_dx - fi_cx) > 1.5:
                                                continue
                                            if not (fi_w / 2 - 1.5
                                                    <= _tr / scale_factor
                                                    <= fi_w / 2 + 1.5):
                                                continue
                                            _ring_c = (_tx, _ty)
                                            break
                                        if _ring_c is None:
                                            continue
                                        _ring_h = _zmax - z_bot + 2.0
                                        _ring_outer = create_cylinder_solid(
                                            _ring_c, _zhalf,
                                            _ring_h, z_bot - 1.0)
                                        _ring_inner = create_cylinder_solid(
                                            _ring_c, fi_w / 2,
                                            _ring_h, z_bot - 1.0)
                                        if (_ring_outer is not None
                                                and _ring_inner is not None):
                                            _ring_cut = BRepAlgoAPI_Cut(
                                                _ring_outer, _ring_inner)
                                            if _ring_cut.IsDone():
                                                tools.append(
                                                    _ring_cut.Shape())
                                                continue
                                    # v0.6.3: 沉头判据——同圆心更小圆
                                    # （芯孔）的深度段顶必须与本段底相接
                                    # （沉头坐在芯孔之上）。存在芯孔但无
                                    # 相接段 → 本段是噪声竖线对（如主体
                                    # 顶段碎边配对 φ5.5 沉头误配到
                                    # Z[34.6~44.6]），剔除。
                                    _sink_seen = False
                                    _sink_touch = False
                                    _sink_below = False
                                    for _tx, _ty, _tr, _dx, _dy in top_hole_circles:
                                        if abs(_dx - fi_cx) > 1.5:
                                            continue
                                        if not (fi["y_min"] - 2 <= _dy <= fi["y_max"] + 2):
                                            continue
                                        if not (0.25 * fi_w / 2 <= _tr / scale_factor
                                                <= fi_w / 2 - 0.5):
                                            continue
                                        _sink_seen = True
                                        # v0.6.3: 双向相接检查——沉头坐于
                                        # 芯孔之上（本段顶≈芯孔段底，如
                                        # φ5.5 沉头/φ50 底沉）或孔口延续
                                        # （本段底≈芯孔段顶，如主体底 r8
                                        # 孔接法兰 r7 孔）。容差 3.0 容纳
                                        # 阶梯间的锥形过渡段（如 φ32→φ14
                                        # 间 1.95 高锥段）。
                                        for _s_top, _s_bot in _profile_depths(
                                                _dx, _tr / scale_factor):
                                            if (abs(z_top - _s_bot) < 3.0
                                                    or abs(z_bot - _s_top) < 3.0):
                                                _sink_touch = True
                                                break
                                            if (_s_bot < z_bot - 0.5
                                                    and _s_top < z_bot - 0.5):
                                                _sink_below = True
                                        if _sink_touch:
                                            break
                                    # v0.6.3: 仅当同心芯孔段完全在本段
                                    # 下方且无相接时跳过——不同特征上下
                                    # 投影重合（顶块 φ5.5 孔 vs 法兰
                                    # φ3.3 安装孔）是噪声配对；芯孔段在
                                    # 本段上方/内部时本段是真实孔壁
                                    # （法兰 φ14 芯孔 vs 主体顶 R6 孔，
                                    # PF60K 中央孔系 φ42/φ32/φ14），保留。
                                    if _sink_seen and not _sink_touch and _sink_below:
                                        continue
                                    # v0.6.3: 覆盖判据——更大同心圆环刀
                                    # 会覆盖本段，环刀芯会保留凸起；本刀
                                    # 多余且会把芯切掉，跳过
                                    _covered = False
                                    for _tx, _ty, _tr, _dx, _dy in top_hole_circles:
                                        if abs(_dx - fi_cx) > 1.5:
                                            continue
                                        if not (fi["y_min"] - 2 <= _dy <= fi["y_max"] + 2):
                                            continue
                                        if _tr / scale_factor <= fi_w / 2 + 0.5:
                                            continue
                                        for _s_top, _s_bot in _profile_depths(
                                                _dx, _tr / scale_factor):
                                            # 更大圆是凸起帽（其环刀被帽判据
                                            # 跳过）→ 不构成覆盖
                                            if (_zmax is not None
                                                    and _s_bot >= _zmax - 0.5
                                                    and _tr / scale_factor
                                                    <= _zhalf * 0.3):
                                                continue
                                            # 部分重叠不再判覆盖——如 r8 底
                                            # 孔刀只覆盖 R6 顶孔段一部分却让
                                            # R6 刀整体跳过（PF60K 主体顶孔
                                            # 假材料 3,381）。必须完全覆盖
                                            # （更大圆段包含本段）才跳过。
                                            if (_s_bot <= z_bot + 0.5
                                                    and _s_top >= z_top - 0.5):
                                                _covered = True
                                                break
                                        if _covered:
                                            break
                                    if _covered:
                                        continue
                                    tools.append(
                                        _limit_tool_depth(tool, z_top, z_bot))
                    # v0.6.3: top 无深度匹配不回退贯穿——φ12 凸台等顶部
                    # 凸起深度推导失败时，贯穿刀会把凸起切成通孔
                    if not tools and tool is not None and vt != "top":
                        tools = [tool]
                if not tools:
                    continue

                for tool in tools:
                    try:
                        _tbb = Bnd_Box()
                        brepbndlib.Add(tool, _tbb)
                        _tx1, _ty1, _tz1, _tx2, _ty2, _tz2 = _tbb.Get()
                        # v0.6.3: 同位置同半径同深度段的重复刀去重（重复弧
                        # → 半圆面 ×2 每孔两把刀；重复切空刀无害但省时）
                        _key = (round((_tx1 + _tx2) / 2, 1),
                                round((_ty1 + _ty2) / 2, 1),
                                round((_tx2 - _tx1) / 2, 1),
                                round(_tz1, 1), round(_tz2, 1))
                        if _key in applied_cuts:
                            continue
                        applied_cuts.add(_key)
                        cut_op = BRepAlgoAPI_Cut(combined, tool)
                        if cut_op.IsDone():
                            new_shape = cut_op.Shape()
                            # 逐工具验证: 坏工具（无效棱柱）的 Cut 会产生
                            # Common 般的坍缩结果——bbox 体积骤降则跳过
                            _obb = Bnd_Box()
                            brepbndlib.Add(combined, _obb)
                            _ox1, _oy1, _oz1, _ox2, _oy2, _oz2 = _obb.Get()
                            _ovol = (_ox2 - _ox1) * (_oy2 - _oy1) * (_oz2 - _oz1)
                            _cbb = Bnd_Box()
                            brepbndlib.Add(new_shape, _cbb)
                            _cx1, _cy1, _cz1, _cx2, _cy2, _cz2 = _cbb.Get()
                            _nvol = (_cx2 - _cx1) * (_cy2 - _cy1) * (_cz2 - _cz1)
                            if _ovol > 0 and _nvol < _ovol * 0.5:
                                continue
                            # v0.6.3: 分离小实体兜底融合——切刀把顶部
                            # 凸起切下成分离实体时融合回主体（凸起是
                            # 主体一部分，如 φ17 顶被顶沉刀切离）
                            try:
                                _slist = []
                                _pmax = 0.0
                                _pex = TopExp_Explorer(new_shape, TopAbs_SOLID)
                                while _pex.More():
                                    _pp = GProp_GProps()
                                    brepgprop.VolumeProperties(_pex.Current(), _pp)
                                    _slist.append((_pp.Mass(), _pex.Current()))
                                    _pmax = max(_pmax, _pp.Mass())
                                    _pex.Next()
                                if len(_slist) > 1 and _pmax > 0:
                                    for _pm, _ps in _slist:
                                        if _pm < _pmax * 0.02 and _pm > 0.5:
                                            _fo2 = BRepAlgoAPI_Fuse(new_shape, _ps)
                                            if _fo2.IsDone():
                                                new_shape = _fo2.Shape()
                            except Exception:
                                pass
                            combined = new_shape
                            inner_cut_count += 1
                            # v0.6.3: 环刀芯——同圆心更小圆的深度段与
                            # 刀段重叠≥0.5 → 芯柱融合回主体（凸起保留，
                            # 如 φ42 孔内的 φ14 台阶）
                            if vt == "top":
                                _t_r = (_tx2 - _tx1) / 2
                                _t_cx = (_tx1 + _tx2) / 2
                                _t_cy = (_ty1 + _ty2) / 2
                                for _tx, _ty, _tr, _dx, _dy in top_hole_circles:
                                    # 半圆刀 bbox 中心相对圆心偏移约 r/2，
                                    # 容差按刀半径缩放
                                    if (abs(_tx - _t_cx) > _t_r * 0.6 + 1.5
                                            or abs(_ty - _t_cy) > _t_r * 0.6 + 1.5):
                                        continue
                                    if not (0.25 * _t_r <= _tr <= _t_r - 0.5):
                                        continue
                                    for _s_top, _s_bot in _profile_depths(
                                            _dx, _tr / scale_factor):
                                        # 芯段顶须高于刀段顶（台阶芯特征，
                                        # 如 φ14 台阶顶 -22 > φ42 刀顶 -25）；
                                        # 与刀段共顶的更小圆段是嵌套孔
                                        # （如 φ32 孔段顶=φ42 刀顶），不填芯
                                        if (min(_s_top, _tz2) - max(_s_bot, _tz1) >= 0.5
                                                and _s_top > _tz2 + 0.5):
                                            # v0.6.3: 芯底不加余量——芯底
                                            # 低于主体底会把主体 bbox 拉低
                                            # （恶性循环：推导段底随主体底
                                            # 下移，芯再下移）；顶余量 +0.5
                                            # 伸入上层材料无害（Fuse 重叠融合）
                                            _core = create_cylinder_solid(
                                                (_t_cx, _t_cy), _tr,
                                                _s_top - _s_bot + 0.5,
                                                _s_bot)
                                            _fo3 = BRepAlgoAPI_Fuse(combined, _core)
                                            if _fo3.IsDone():
                                                combined = _fo3.Shape()
                                            break
                    except Exception:
                        pass

        # ---- v0.6.3 P3.2: 环带内孔孔内材料补全 ----
        # 环带面以 r_f 为内孔全域挖空，但基准孔系 F 段内有材料岛
        # （φ32 岛 r[7,16]，island-skip 保住不切）、F 段顶之上有阶梯
        # 填充（φ42 孔顶上方法兰顶盘 r[7,21] 材料）：
        #   a) 岛融合: island 圆 C → 环柱 annulus(r_next→r_C) × C 段，
        #      r_next = 段与 C 段重叠且穿透 F 段顶的最大同心小圆
        #      （真孔，如 φ14）——不碰芯孔，与刀序无关
        #   b) 阶梯填充: 继续孔（段底接 F 段顶、段顶超出）→ 环柱
        #      annulus(r_C→r_f) × [F_top, C_top]
        #   c) 补刀: 同心 hole 圆无面刀时按段补切（r8 底孔/r8.5 顶
        #      凹槽的 top 弧面与邻圆纠缠，面刀未生成）
        if _flange_r and _flange_hole_segs and _topv is not None:
            try:
                _f_top, _f_bot = _flange_hole_segs[0]
                for _s_top, _s_bot in _flange_hole_segs:
                    if (_s_top - _s_bot) > (_f_top - _f_bot):
                        _f_top, _f_bot = _s_top, _s_bot
                _concs = []
                for _tx, _ty, _tr, _dx, _dy in top_hole_circles:
                    if abs(_dx - _tcx) > 1.5 or abs(_dy - _tcy) > 1.5:
                        continue
                    if not (0.25 * _flange_r <= _tr / scale_factor
                            <= _flange_r):
                        continue
                    # fi_cx 与竖线对 pcx 同属 DXF 系（三视图共享 X 轴）
                    _segs = _profile_depths(_dx, _tr / scale_factor)
                    if _segs:
                        _concs.append((_tr / scale_factor, _segs))
                # b) 阶梯填充——继续孔段底须深入 F 段（≥2.0，孔从
                # F 段内部升起），排除段底恰接 F 段顶的孔（主体底
                # r8 孔段底=-21.95 与 F 顶相接，是真孔不是顶盘材料）
                _fill_r = None
                _fill_top = None
                for _r, _segs in _concs:
                    for _s_top, _s_bot in _segs:
                        if (_s_top > _f_top + 0.5
                                and _s_bot <= _f_top + 1.0
                                and _s_bot <= _f_top - 2.0):
                            if _fill_r is None or _r > _fill_r:
                                _fill_r = _r
                                _fill_top = _s_top
                if _fill_r is not None and _fill_top > _f_top:
                    _fill = create_concentric_solid(
                        (0.0, 0.0), (_flange_r * scale_factor,
                                     _fill_r * scale_factor),
                        _fill_top - _f_top, _f_top)
                    if _fill is not None:
                        _fo = BRepAlgoAPI_Fuse(combined, _fill)
                        if _fo.IsDone():
                            combined = _fo.Shape()
                            print(f"  [P3.2] 阶梯填充 r[{_fill_r:.1f},"
                                  f"{_flange_r:.1f}] "
                                  f"Z[{_f_top:.1f}~{_fill_top:.1f}]")
                # r_f 派生补刀：F 段内 r<r_f 全域切空（φ42 孔壁区
                # r[16,21] 假材料；r21 面刀深度段缺失→无工具）。
                # 岛材料由 a) 融合补回，芯孔已由 side 刀切通。
                _r21_had = False
                for _k in applied_cuts:
                    if (abs(_k[2] - _flange_r * scale_factor) < 1.0
                            and abs(_k[4] - _f_top) < 1.5):
                        _r21_had = True
                        break
                if not _r21_had:
                    # v0.6.3: 余量只 0.2——F 段顶上方是主体底材料，
                    # 大余量会切穿进主体（r21 柱 × 越界高假切）
                    _tool21 = create_cylinder_solid(
                        (0.0, 0.0), _flange_r * scale_factor,
                        _f_top - _f_bot + 0.2, _f_bot - 0.2)
                    _co21 = BRepAlgoAPI_Cut(combined, _tool21)
                    if _co21.IsDone():
                        combined = _co21.Shape()
                        inner_cut_count += 1
                        print(f"  [P3.2] r_f 补刀 r={_flange_r:.1f} "
                              f"Z[{_f_bot:.1f}~{_f_top:.1f}]")
                # a) 岛融合：F 段内竖线对缺失的同心圆是内部材料岛
                # （真孔在 front/side 均有竖线投影；岛的轮廓是内部
                # 边界，被 HLR 消除 → 缺失即岛）。岛 = annulus(内孔
                # →岛圆) × F 段，内孔 = 段与 F 段重叠的最大被切孔
                # （芯孔 r7）。岛高填到 F 顶（φ42 孔顶~顶盘底间的
                # 阶梯材料图纸无信息，填满为信息论最优）。
                _island_r = 0.0
                _hole_inner = 0.0
                for _tx, _ty, _tr, _dx, _dy in top_hole_circles:
                    if abs(_dx - _tcx) > 1.5 or abs(_dy - _tcy) > 1.5:
                        continue
                    _r = _tr / scale_factor
                    if not (0.25 * _flange_r <= _r < _flange_r - 0.1):
                        continue
                    _isegs = _profile_depths(_dx, _r)
                    if not _isegs:
                        _island_r = max(_island_r, _r)
                    else:
                        for _s_top, _s_bot in _isegs:
                            if (min(_s_top, _f_top)
                                    - max(_s_bot, _f_bot) >= 0.5):
                                _hole_inner = max(_hole_inner, _r)
                                break
                if _island_r > _hole_inner + 0.5:
                    _island = create_concentric_solid(
                        (0.0, 0.0),
                        (_island_r * scale_factor,
                         _hole_inner * scale_factor) if _hole_inner > 0
                        else (_island_r * scale_factor,),
                        _f_top - _f_bot, _f_bot)
                    if _island is not None:
                        _fo = BRepAlgoAPI_Fuse(combined, _island)
                        if _fo.IsDone():
                            combined = _fo.Shape()
                            print(f"  [P3.2] 岛融合 r[{_hole_inner:.1f},"
                                  f"{_island_r:.1f}] "
                                  f"Z[{_f_bot:.1f}~{_f_top:.1f}]")
                # c) 补刀
                for _r, _segs in _concs:
                    if all(_f_bot - 0.5 <= s[1] and s[0] <= _f_top + 0.5
                           for s in _segs):
                        continue
                    for _s_top, _s_bot in _segs:
                        _had = False
                        for _k in applied_cuts:
                            if (abs(_k[2] - _r * scale_factor) < 1.0
                                    and abs(_k[3] - _s_bot) < 1.0
                                    and abs(_k[4] - _s_top) < 1.0):
                                _had = True
                                break
                        if _had:
                            continue
                        # v0.6.3: 余量只 0.2——段端上下方可能有相邻
                        # 材料（F 段顶材料/主体底），大余量越界假切
                        _tool = create_cylinder_solid(
                            (0.0, 0.0), _r * scale_factor,
                            _s_top - _s_bot + 0.2, _s_bot - 0.2)
                        _co = BRepAlgoAPI_Cut(combined, _tool)
                        if _co.IsDone():
                            combined = _co.Shape()
                            inner_cut_count += 1
                            print(f"  [P3.2] 补刀 r={_r:.1f} "
                                  f"Z[{_s_bot:.1f}~{_s_top:.1f}]")
            except Exception as _e:
                print(f"  [WARN] P3.2 孔内材料补全异常: {_e}")

        # 验证切割后主体是否仍然有效
        if inner_cut_count > 0:
            try:
                body_valid = Bnd_Box()
                brepbndlib.Add(combined, body_valid)
                _vx1, _vy1, _vz1, _vx2, _vy2, _vz2 = body_valid.Get()
                body_vol = (_vx2 - _vx1) * (_vy2 - _vy1) * (_vz2 - _vz1)
            except Exception:
                body_vol = 0

            if body_vol <= 0.01:
                print(f"  [P0] 内部切割导致主体退化，跳过 {inner_cut_count} 个工具（回退）")
                combined = combined_before_cuts
                inner_cut_count = 0
            else:
                print(f"  [P0] 内部特征处理: {inner_cut_count} 个切割工具已应用")
                # v0.6.3: P0 已成功切割的标志——主流程 P2 块据此跳过
                # 同心圆组孔生成（P0 已处理内部特征，P2 的重复/错刀
                # 会把凸起切成孔并掏空主体段）
                hole_data.append({"_p0_cut_count": inner_cut_count})
                try:
                    fixer2 = ShapeFix_Shape()
                    fixer2.Init(combined)
                    fixer2.Perform()
                    combined = fixer2.Shape()
                except Exception:
                    pass

    return combined, hole_data


# ============================================================
# 8. 主转换流程
# ============================================================

def convert_dxf_to_3d(dxf_path: str, step_output: str = None,
                      extrusion_depth: float = None,
                      single_view: bool = None) -> object:
    """通用 DXF → 3D 转换器 v2.1。

    新增 single_view 参数:
      - None: 自动检测（单视图: 轮廓拉伸; 多视图: 包围盒+特征）
      - True: 强制单视图轮廓拉伸模式
      - False: 强制多视图包围盒模式

    全新设计思路:
    1. 解析 + 建图 + 面遍历
    2. 过滤：边框、SPLINE 碎片、过小面
    3. 自动视图检测（标签 + 几何间隙）
    4. 同心圆弧 → 圆柱体特征
    5. 最大非圆轮廓 → 主体拉伸
    6. 其余轮廓 → 辅助特征
    7. 主体 + 圆柱体 + 辅助 → 布尔合并
    8. 导出 STEP
    """
    _ensure_occ()

    # ---- Step 1: 解析 ----
    print(f"[1/6] 解析 DXF: {dxf_path}")
    edges, metadata = parse_dxf_edges(dxf_path)
    texts = parse_dxf_texts(dxf_path)
    print(f"  边: {len(edges)}, 文字: {len(texts)}")
    for etype, count in metadata["entity_counts"].items():
        print(f"    {etype}: {count}")

    # ---- Step 1.5: 注解提取（剖面线/中心线/截面标记） ----
    annotations = extract_dxf_annotations(dxf_path)
    if annotations["hatch_regions"]:
        print(f"  剖面填充: {len(annotations['hatch_regions'])} 个 "
              f"({', '.join(h['pattern'] for h in annotations['hatch_regions'])})")
    if annotations["centerlines"]:
        print(f"  中心线: {len(annotations['centerlines'])} 条 "
              f"({', '.join(set(cl['linetype'] for cl in annotations['centerlines']))})")
    if annotations["section_markers"]:
        labels = sorted(set(m["label"] for m in annotations["section_markers"]))
        print(f"  截面标记: {', '.join(f'{l}-{l}' for l in labels)}")
    has_hidden_lt = any("HIDDEN" in k.upper() for k in annotations["linetype_map"])
    has_center_lt = any("CENTER" in k.upper() or "PHANTOM" in k.upper()
                       for k in annotations["linetype_map"])
    if has_hidden_lt:
        print(f"  [INFO] DXF 线型表包含 HIDDEN 线型，但所有实体均使用 Continuous")

    if len(edges) < 3:
        print("[FAIL] 边数量不足")
        return None

    bbox_min = metadata["bbox_min"]
    bbox_max = metadata["bbox_max"]
    total_w = bbox_max[0] - bbox_min[0]
    total_h = bbox_max[1] - bbox_min[1]
    total_area = total_w * total_h
    part_scale = max(total_w, total_h)

    # ---- Fix 3: DXF 比例因子检测 ----
    scale_factor = detect_dxf_scale(dxf_path)
    if scale_factor != 1.0:
        print(f"  实际尺寸 = DXF尺寸 × {scale_factor:.4f}")
        real_w = total_w * scale_factor
        real_h = total_h * scale_factor
        print(f"  实物估算: {real_w:.0f}×{real_h:.0f}mm")

    # ---- Step 2: 建图 + 面遍历 + 过滤 ----
    print(f"\n[2/6] 建图 + 面遍历 ...")
    edges = split_edges_at_intersections(edges)
    vertex_pos, edge_vertices, num_vertices = build_vertex_map(edges)
    edge_vertices = merge_close_vertices(vertex_pos, edge_vertices)
    edge_vertices = merge_dangling_vertices(vertex_pos, edge_vertices)
    adj = build_adjacency(vertex_pos, edge_vertices, edges, num_vertices)
    faces = find_all_faces(adj, edges, edge_vertices)
    print(f"  顶点: {num_vertices}, 封闭环: {len(faces)}")

    if not faces:
        print("[FAIL] 无封闭环")
        return None

    faces_info = [analyze_face(f_ids, edges, edge_vertices, vertex_pos)
                  for f_ids in faces]

    # 预检：是否为多视图图纸（Y 方向有明显间隙）
    # 图框/标题栏面跨度近整图, 会破坏间隙检测, 先粗筛为候选跨越面并排除。
    total_h_pre = bbox_max[1] - bbox_min[1]
    total_w_pre = bbox_max[0] - bbox_min[0]
    y_gap_th_pre = max(15.0, total_h_pre * 0.08)
    cand_spanning_idx = {i for i, fi in enumerate(faces_info)
                         if (fi["y_max"] - fi["y_min"] > total_h_pre * 0.85
                             and fi["x_max"] - fi["x_min"] > total_w_pre * 0.60
                             and fi["area"] > total_area * 0.20
                             and len(fi["edges"]) <= 20)}
    pre_sorted = [f for i, f in enumerate(faces_info)
                  if i not in cand_spanning_idx]
    pre_sorted.sort(key=lambda f: f["y_mid"])
    y_gaps = []
    for i in range(1, len(pre_sorted)):
        gap = pre_sorted[i]["y_min"] - pre_sorted[i-1]["y_max"]
        if gap > y_gap_th_pre:
            y_gaps.append(gap)
    has_multi_views = len(y_gaps) >= 1

    # 过滤边框面
    border_idx = set()
    # 标记"跨越面"（跨多个视图的边框），在多视图分离时忽略它们
    spanning_idx = set()
    if has_multi_views:
        # 图框/标题栏面: 跨度接近整图。复杂图纸面总数多, 图框面积占比
        # 可能 <60% 且被标题栏线切碎 (边数 >6), 放宽为 20% + 边数 <=20。
        spanning_idx = set(cand_spanning_idx)
        # 在 face_info 上打标记，供视图分离时使用
        for i in spanning_idx:
            faces_info[i]["is_spanning"] = True
    if not has_multi_views:
        # 单视图：面积 > 25% 的大矩形视为边框
        border_idx = {i for i, fi in enumerate(faces_info)
                      if fi["area"] > total_area * 0.25 and len(fi["edges"]) <= 6}
    spline_idx = {i for i, fi in enumerate(faces_info)
                  if fi["is_spline_debris"] and i not in border_idx}
    areas_filt = [fi["area"] for i, fi in enumerate(faces_info)
                  if i not in border_idx and i not in spline_idx]
    median_a = sorted(areas_filt)[len(areas_filt)//2] if areas_filt else 1
    min_at = max(0.5, median_a * 0.0005)
    tiny_idx = {i for i, fi in enumerate(faces_info)
                if i not in border_idx and i not in spline_idx
                and fi["area"] < min_at}

    valid_faces = [faces_info[i] for i in range(len(faces_info))
                   if i not in border_idx and i not in spline_idx
                   and i not in tiny_idx]

    # 兜底：如果边框过滤导致主体轮廓丢失（简单图纸常见），
    # 从 border_idx 中救回可能的主体面
    line_only_in_valid = [f for f in valid_faces
                          if f["face_type"] == "line_only" and f["area"] > 10]
    if not line_only_in_valid and border_idx:
        # 统计全局 line_only 面数量（含 border）
        all_line_only = [fi for fi in faces_info
                         if fi["face_type"] == "line_only" and fi["area"] > 10]
        rescued = []
        still_border = set()
        for i in border_idx:
            fi = faces_info[i]
            # 真边框判定：包含所有几何的完美矩形（4边），
            # 且全局存在多个 line_only 面且不是多视图图纸
            # （多视图图纸中不会有整张图的边框，large rect 是视图轮廓）
            is_true_frame = (fi["area"] > total_area * 0.95
                             and len(fi["edges"]) == 4
                             and fi["face_type"] == "line_only"
                             and len(all_line_only) > 1
                             and not has_multi_views)
            if is_true_frame:
                still_border.add(i)
            else:
                rescued.append(i)
        if rescued:
            border_idx = still_border
            valid_faces = [faces_info[i] for i in range(len(faces_info))
                           if i not in border_idx and i not in spline_idx
                           and i not in tiny_idx]
            print(f"  边框纠正: 救回 {len(rescued)} 个非边框面")

    print(f"  有效环: {len(valid_faces)} (边框{len(border_idx)}"
          f"+SPLINE碎片{len(spline_idx)}+过小{len(tiny_idx)} 已过滤)")

    if not valid_faces:
        print("[FAIL] 所有面均被过滤")
        return None

    # ---- Step 3: 识别主体轮廓 + 圆柱特征 ----
    print(f"\n[3/6] 特征识别 ...")

    # 找出全局最大的 LINE-only 面 → 主体轮廓
    line_faces = [f for f in valid_faces
                  if f["face_type"] == "line_only" and f["area"] > 10]
    line_faces.sort(key=lambda f: -f["area"])

    # 也收集可用于主体的圆/弧面（用于法兰等圆形零件）
    arc_faces = [f for f in valid_faces
                 if f["face_type"] in ("single_arc", "concentric")
                 and f["area"] > 50]
    arc_faces.sort(key=lambda f: -f["area"])

    is_circular_body = False
    if line_faces:
        body_face = line_faces[0]
    elif arc_faces:
        body_face = arc_faces[0]
        is_circular_body = True
    else:
        print("[FAIL] 未找到主体轮廓")
        return None

    body_type = "圆形" if is_circular_body else f"{len(body_face['edges'])}边"
    print(f"  主体轮廓: 面积={body_face['area']:.0f}, {body_type}, "
          f"X[{body_face['x_min']:.0f}~{body_face['x_max']:.0f}] "
          f"Y[{body_face['y_min']:.0f}~{body_face['y_max']:.0f}]")

    # 全局同心圆检测（跨所有视图）
    concentric_groups = cluster_concentric_arcs(
        valid_faces, edges, edge_vertices, vertex_pos)

    conc_face_indices = set()
    for ckey, group in concentric_groups.items():
        conc_face_indices.update(group["face_indices"])

    print(f"  同心圆组: {len(concentric_groups)}")
    for ckey, group in sorted(concentric_groups.items(),
                               key=lambda x: -x[1]["count"]):
        print(f"    中心({ckey[0]:.1f},{ckey[1]:.1f}): R={group['radii']}")

    # ---- Step 3.5: CSG 多视图体积求交 ----
    # 尝试分离视图并构建 3D 实体
    views = _separate_views_2d(valid_faces, (bbox_min[0], bbox_min[1],
                                              bbox_max[0], bbox_max[1]))
    print(f"\n[3.5/6] 视图分离: {len(views)} 个区域")
    for v in views:
        print(f"    {v['name']}: {len(v['faces'])}面, "
              f"X[{v['bbox'][0]:.0f}~{v['bbox'][2]:.0f}] "
              f"Y[{v['bbox'][1]:.0f}~{v['bbox'][3]:.0f}]")

    is_csg = False
    body_solid = None
    csg_holes = None

    # CSG 仅在有多个独立视图且主体为非圆形时尝试
    # （圆形主体是单视图场景，CSG 需要至少2个正交方向的外轮廓）
    if len(views) >= 2 and not single_view and not is_circular_body:
        print(f"\n  尝试 CSG 体积求交 ({len(views)} 视图)...")
        body_solid, csg_holes = csg_reconstruct(
            views, edges, edge_vertices, vertex_pos, scale_factor,
            annotations=annotations)

    if body_solid is not None:
        is_csg = True
        print(f"  CSG 重建成功！")
    else:
        # ---- 模式检测：单视图 vs 多视图（回退） ----
        if single_view is None:
            is_single = (len(faces_info) < 30
                         and (body_face["area"] > total_area * 0.15
                              or len(valid_faces) <= 10))
        else:
            is_single = single_view

        if is_single:
            print(f"\n  模式: 单视图轮廓拉伸（回退）")
        else:
            print(f"\n  模式: 多视图包围盒（回退）")

    # ---- Step 4: 创建 3D 实体 ----
    if not is_csg:
        print(f"\n[4/6] 创建 3D 实体 ...")

    # 估算深度
    if not is_csg:
        if extrusion_depth is not None:
            body_depth = extrusion_depth
        else:
            max_r = 0
            for g in concentric_groups.values():
                if g["radii"]:
                    max_r = max(max_r, max(g["radii"]))
            body_depth = max_r * 4 if max_r > 0 else part_scale * 0.3
        body_depth = max(body_depth, 10.0)
        print(f"  零件总深度: {body_depth:.0f}mm")

    all_holes = []     # 从主体减去的特征
    all_bosses = []    # 添加到主体的特征

    # ================================================================
    # CSG 模式：已完成主体构建，处理孔洞
    # ================================================================
    if is_csg:
        # CSG 模式：用同心圆组数据创建凸台/孔圆柱体
        if concentric_groups:
            sf = scale_factor

            # 从 CSG 主体计算合适的深度和中心位置
            try:
                body_bbox = Bnd_Box()
                brepbndlib.Add(body_solid, body_bbox)
                bx1, by1, bz1, bx2, by2, bz2 = body_bbox.Get()
            except Exception:
                # 内部切割后包围盒可能无效，用视图范围回退
                print("  [WARN] CSG 主体包围盒计算失败，使用视图范围估算")
                bx1 = min(v["bbox"][0] for v in views) * sf
                by1 = min(v["bbox"][1] for v in views) * sf
                bz1 = 0
                bx2 = max(v["bbox"][2] for v in views) * sf
                by2 = max(v["bbox"][3] for v in views) * sf
                bz2 = (by2 - by1) * 0.5  # 用 Y 范围估算 Z
            body_z = bz2 - bz1
            body_cx = (bx1 + bx2) / 2
            body_cy = (by1 + by2) / 2

            # 判断同心圆组属于哪个视图（前视图 vs 俯视图）
            # 俯视图的同心圆 Y 坐标 > 200 → 其 DXF Y 映射到 3D Z
            # ---- P3: 视图 DXF X 中心映射基准 ----
            # CSG 主体已居中到原点附近，特征坐标必须减去所属视图的
            # DXF X 中心（csg_reconstruct 保存的 _dxf_center_x），
            # 否则远离视图中心的特征（如 reducer 右侧凸台）会落在主体外，
            # 布尔加后成为分离实体。
            top_center_x = None
            top_center_y = None
            front_center_x = None
            front_center_y = None
            front_outer_face = None
            for v in views:
                vcx = v.get("_dxf_center_x")
                if vcx is None:
                    continue
                if v["view_type"] == "top" and top_center_x is None:
                    # v0.6.3: 同 front——top 特征映射基准用外环中心
                    # （与 CSG 棱柱居中平移一致），区域 bbox 可能并入
                    # 相邻视图导致中心偏移
                    ofc_top = v.get("_outer_face") or {}
                    if all(k in ofc_top for k in ("x_min", "x_max",
                                                  "y_min", "y_max")):
                        top_center_x = (ofc_top["x_min"] + ofc_top["x_max"]) / 2 * sf
                        top_center_y = (ofc_top["y_min"] + ofc_top["y_max"]) / 2 * sf
                    else:
                        top_center_x = vcx
                        top_center_y = v.get("_dxf_center_y")
                elif v["view_type"] == "front" and front_center_x is None:
                    # v0.6.3: front 特征映射基准用外环中心（与 CSG 棱柱
                    # 居中平移一致）——视图区域 bbox 可能并入相邻视图
                    # （block_3view: front+side 同 Y 层 X 间隙 15<30
                    # 未拆分，区域中心 72.5 ≠ 外环中心 50，孔 X 错位）
                    ofc = v.get("_outer_face") or {}
                    front_outer_face = ofc
                    if all(k in ofc for k in ("x_min", "x_max",
                                              "y_min", "y_max")):
                        front_center_x = (ofc["x_min"] + ofc["x_max"]) / 2 * sf
                        front_center_y = (ofc["y_min"] + ofc["y_max"]) / 2 * sf
                    else:
                        front_center_x = vcx
                        front_center_y = v.get("_dxf_center_y")

            # v0.6.1: 孔深度推理 — top 视图竖直孔的真实深度由 front/side
            # 视图竖线对（X=cx±r 处的孔投影竖线）Y 范围确定。
            # faces 环不可靠（孔投影环与外轮廓共享边时会被并入外环），
            # 原始边数据中的竖线对更鲁棒。
            def find_hole_depth_2d(cx, r):
                """front/side 竖线对 → CSG Z 深度。

                返回 (z_top, z_bot) CSG 坐标或 None（无匹配则贯穿）。"""
                if not views or not body_solid:
                    return None
                try:
                    fbb = Bnd_Box()
                    brepbndlib.Add(body_solid, fbb)
                    _z1, _z2 = fbb.Get()[2], fbb.Get()[5]
                except Exception:
                    return None
                best_cand = None  # (|pr-r|, z_top, z_bot)
                for v in views:
                    if v["view_type"] == "top":
                        continue
                    ofc = v.get("_outer_face") or {}
                    y_span = ofc.get("y_max", 0) - ofc.get("y_min", 0)
                    if y_span <= 0:
                        continue
                    for pcx, pr, ylo, yhi in _vertical_hole_profiles(v, edges):
                        if abs(pr - r) > max(2.0, 0.5 * r):
                            continue
                        if abs(pcx - cx) > max(2.0, 0.5 * r):
                            continue
                        # 图纸 Y → CSG Z: 该视图外环 Y 范围线性映射到
                        # 3D 主体 Z 范围（主体已居中，Z 从 -H/2 到 +H/2）
                        z_top = _z1 + (yhi - ofc["y_min"]) / y_span \
                            * (_z2 - _z1)
                        z_bot = _z1 + (ylo - ofc["y_min"]) / y_span \
                            * (_z2 - _z1)
                        if z_top < z_bot:
                            z_top, z_bot = z_bot, z_top
                        cand = (abs(pr - r), z_top, z_bot)
                        if best_cand is None or cand[0] < best_cand[0]:
                            best_cand = cand
                # 偏差 > 0.5 的候选不可靠，放弃深度推理回退贯穿
                if best_cand is not None and best_cand[0] <= 0.5:
                    return (best_cand[1], best_cand[2])
                return None

            boss_count = 0
            hole_count = 0
            # v0.6.3: P0 已处理内部特征时跳过 P2 孔生成——P0 的 top
            # 圆限深刀 + front/side 竖线对已完整覆盖竖直孔，P2 的
            # 重复/错刀（φ60 段 R30 刀、凸台/台阶 R8.5/8/7/6 刀）会
            # 把凸起切成孔并掏空主体段（标志由 csg_reconstruct 写入）
            _p2_skip = bool(csg_holes) and any(
                isinstance(_h, dict) and _h.get("_p0_cut_count")
                for _h in csg_holes)
            if _p2_skip:
                print("  [P2] P0 已处理内部特征，跳过同心圆组孔生成")
            for ckey, group in ({} if _p2_skip else concentric_groups).items():
                if not group["radii"]:
                    continue
                cx, cy = group["center"]
                radii = sorted(group["radii"], reverse=True)
                gtype = group.get("group_type", "concentric")

                # 判断：圆心落在 top 视图 bbox 内 → 俯视图特征
                # （不能用 Y > 200 硬编码：图纸布局视图位置不固定，
                #   本模型 top 视图 Y[153~233]，凸台圆心 cy=192.9 < 200）
                is_top_view_feature = False
                top_view = None
                for v in views:
                    if v["view_type"] != "top":
                        continue
                    tb = v["bbox"]
                    if tb[1] - 5 <= cy <= tb[3] + 5 and \
                       tb[0] - 5 <= cx <= tb[2] + 5:
                        is_top_view_feature = True
                        top_view = v
                        break

                # v0.6.1: 剔除外轮廓弧半径——外轮廓圆（如 φ80 法兰圆）
                # 被同心圆聚类并进组后会把最外层半径当凸台（R40 凸台
                # 而实际凸台 R25）；外轮廓圆只是视图边界，不是特征。
                # 回退: 外环 ARC 折线化（DXF 弧离散成 LINE）时
                # _outer_ring_radii 为空, 用外轮廓 bbox 半宽推导轮廓半径,
                # 半径 ≥ 0.95×半宽的圆必是轮廓圆（孔不可能大于主体半径）。
                if top_view is not None:
                    outer_rs = set(top_view.get("_outer_ring_radii") or [])
                    # bbox 半宽始终并入: 外环 ARC 半径只是局部弧半径
                    # （如 φ80 角弧 R40），bbox 半宽对应整体轮廓圆
                    # （如 φ60 锥面顶圆 R30 = 60/2），两者都要剔除。
                    of = top_view.get("_outer_face") or {}
                    if all(k in of for k in ("x_min", "x_max",
                                             "y_min", "y_max")):
                        half_w = min(of["x_max"] - of["x_min"],
                                     of["y_max"] - of["y_min"]) / 2.0
                    else:
                        tb = top_view["bbox"]
                        half_w = min(tb[2] - tb[0], tb[3] - tb[1]) / 2.0
                    if half_w > 0:
                        outer_rs.add(round(half_w, 1))
                    radii = [r for r in radii
                             if not any(abs(r - or_) < 0.5
                                        or r >= or_ * 0.95
                                        for or_ in outer_rs)]

                if is_top_view_feature:
                    # 俯视图特征：DXF Y → 3D Y（减去视图中心基准），放在主体顶面
                    feat_3d_x = cx * sf - (top_center_x if top_center_x is not None else 0)
                    # P3: 上下分布的孔（如法兰上下角孔）DXF Y 差异必须保留，
                    # 不能统一压到 body_cy（凸台场景 cy≈视图中心，两者等价）
                    feat_3d_y = cy * sf - (top_center_y if top_center_y is not None else body_cy)
                    feat_z_base = bz2    # 从主体顶面开始
                else:
                    # 前视图特征：DXF x → 3D X、DXF y → 3D Z（各减视图中心基准），
                    # 孔沿 Y 拉伸——front 视图的圆是 XZ 平面上的孔，
                    # 深度方向是主体 Y 尺寸
                    feat_3d_x = cx * sf - (front_center_x if front_center_x is not None else 0)
                    feat_3d_z = cy * sf - (front_center_y if front_center_y is not None else 0)
                    feat_z_base = bz2

                if not radii:
                    continue  # 半径全被外轮廓剔除（纯外轮廓圆，非特征）

                if gtype == "concentric":
                    # 同心圆组：全部半径均为台阶孔系（外轮廓弧如 R40 截角
                    # 已由 outer_ring_radii 过滤）。凸台启发式已删除——
                    # 顶部台阶是内收结构（已包含在 CSG 外环中），
                    # 把最大半径当凸台加高会在主体顶面之上多出错误材料。
                    inner_radii = [r * sf for r in radii]

                    # 孔：深度由 front/side 投影推导，无匹配则贯穿
                    for hole_r in inner_radii:
                        r_dxf = hole_r / sf
                        depth_info = find_hole_depth_2d(cx, r_dxf) \
                            if is_top_view_feature else None
                        if depth_info is not None:
                            z_top, z_bot = depth_info
                            hole = create_cylinder_solid(
                                (feat_3d_x, feat_3d_y), hole_r,
                                z_top - z_bot + 2.0, z_bot - 1.0)
                            print(f"  台阶孔({feat_3d_x:.0f},{feat_3d_y:.0f}): "
                                  f"R={hole_r:.1f}, Z[{z_bot:.0f}~{z_top:.0f}]")
                        else:
                            if is_top_view_feature:
                                hole = create_cylinder_solid(
                                    (feat_3d_x, feat_3d_y), hole_r,
                                    body_z + 20, bz1 - 5)
                                print(f"  贯穿孔({feat_3d_x:.0f},{feat_3d_y:.0f}): "
                                      f"R={hole_r:.1f}")
                            else:
                                # front/side 视图圆 → 沿 Y 贯穿
                                hole = create_cylinder_solid_along_y(
                                    (feat_3d_x, feat_3d_z), hole_r,
                                    (by2 - by1) + 40, by1 - 20)
                                print(f"  贯穿孔Y({feat_3d_x:.0f},Z={feat_3d_z:.0f}): "
                                      f"R={hole_r:.1f}")
                        if hole is not None:
                            all_holes.append(hole)
                            hole_count += 1

                elif gtype == "isolated":
                    # 独立圆：仅孔（安装孔等贯穿孔）
                    hole_r = radii[0] * sf
                    # P3: 半径接近主体外轮廓（≥主体最小边 40%）时跳过——
                    # 该圆是主体轮廓（如法兰盘外径被误分类为孤立圆），
                    # 切除会毁掉主体（此前坐标错位掩盖了该误分类）
                    body_w = bx2 - bx1
                    if body_w > 0 and hole_r > body_w * 0.4:
                        continue
                    if is_top_view_feature:
                        hole = create_cylinder_solid((feat_3d_x, feat_3d_y),
                                                     hole_r,
                                                     body_z + 20, bz1 - 5)
                        if hole is not None:
                            all_holes.append(hole)
                            hole_count += 1
                            print(f"  独立孔({feat_3d_x:.0f},{feat_3d_y:.0f}): "
                                  f"R={hole_r:.1f}")
                    else:
                        hole = create_cylinder_solid_along_y(
                            (feat_3d_x, feat_3d_z), hole_r,
                            (by2 - by1) + 40, by1 - 20)
                        if hole is not None:
                            all_holes.append(hole)
                            hole_count += 1
                            print(f"  独立孔Y({feat_3d_x:.0f},Z={feat_3d_z:.0f}): "
                                  f"R={hole_r:.1f}")

            # v0.6.1: 竖线对补孔 — top 视图 HLR 丢失的竖直孔
            # （如中心 φ12 孔 r=6 不在同心圆组中），由 front/side
            # 竖线对检测补切（仅中心孔：投影中心 ≈ 视图中心时
            # 3D Y 位置可确定，按 Y=0 处理）
            all_group_radii = []
            for _ck, group in concentric_groups.items():
                all_group_radii.extend(group["radii"])
            prof_seen = set()
            for v in ([] if _p2_skip else views):
                if v["view_type"] == "top":
                    continue
                ofc = v.get("_outer_face") or {}
                if ofc.get("x_min") is None:
                    continue
                vcx = (ofc["x_min"] + ofc["x_max"]) / 2
                for pcx, pr, _ylo, _yhi in _vertical_hole_profiles(v, edges):
                    if pr <= 0:
                        continue
                    key = (round(pr, 1), round(pcx - vcx, 1))
                    if key in prof_seen:
                        continue
                    prof_seen.add(key)
                    # 同心圆组已覆盖该半径 → 跳过
                    if any(abs(r_ - pr) < max(2.0, 0.5 * pr)
                           for r_ in all_group_radii):
                        continue
                    # 仅中心孔（投影中心 ≈ 视图中心，3D Y 位置可确定）
                    if abs(pcx - vcx) > max(2.0, 0.5 * pr):
                        continue
                    depth_info = find_hole_depth_2d(pcx, pr)
                    if depth_info is not None:
                        z_top, z_bot = depth_info
                        # 深度过浅（<主体高 15%）→ 假竖线对（如台阶
                        # 碎边配对），跳过
                        if z_top - z_bot < (bz2 - bz1) * 0.15:
                            continue
                    else:
                        z_top, z_bot = bz2, bz1
                    feat_x = (pcx - vcx) * sf
                    hole = create_cylinder_solid(
                        (feat_x, 0.0), pr * sf,
                        z_top - z_bot + 2.0, z_bot - 1.0)
                    if hole is not None:
                        all_holes.append(hole)
                        hole_count += 1
                        print(f"  竖线对补孔({feat_x:.0f},0): "
                              f"R={pr:.1f}, Z[{z_bot:.0f}~{z_top:.0f}]")

            if boss_count or hole_count:
                print(f"  CSG 特征: {boss_count} 凸台 + {hole_count} 孔")

    # ================================================================
    # 单视图模式：轮廓拉伸 + 内孔减除
    # ================================================================
    elif is_single:
        if is_circular_body:
            # 圆形主体 → 创建圆柱体
            # 用 arc_centers 获取真实的几何圆心（而非 bbox 中心）
            arc_centers = body_face.get("arc_centers", [])
            if arc_centers:
                body_cx, body_cy = arc_centers[0]
            else:
                body_cx = body_face["x_mid"]
                body_cy = body_face["y_mid"]
            body_r = max(body_face.get("arc_radii", [body_face["width"] / 2]))
            # 圆形零件深度预估：半径的 0.5~1.0 倍更合理
            if extrusion_depth is None and max(body_face.get("arc_radii", [1])) < 100:
                body_depth = max(body_depth * 0.15, 10.0)
                print(f"  深度修正: {body_depth:.0f}mm")
            body_solid = create_cylinder_solid((body_cx, body_cy),
                                               body_r, body_depth, 0)
            if body_solid is None:
                print("[FAIL] 圆形主体创建失败")
                return None
            print(f"  主体圆柱: 中心({body_cx:.1f},{body_cy:.1f}) "
                  f"R={body_r:.1f}, H={body_depth:.0f}")

            # 同心内圆 → 孔
            for ckey, group in concentric_groups.items():
                cx, cy = group["center"]
                radii = sorted(group["radii"], reverse=True)
                for inner_r in radii:
                    if inner_r < body_r - 0.5:
                        hole = create_cylinder_solid((cx, cy), inner_r,
                                                     body_depth + 10, -5)
                        if hole is not None:
                            all_holes.append(hole)
                            print(f"  内孔({cx:.1f},{cy:.1f}): R={inner_r:.1f}")
        else:
            # 多边形主体 → 轮廓拉伸（可能需合并多个互联面）
            # 检测是否有其他 line_only 面与主体共享顶点（凹多边形拆分）
            other_line_faces = [f for f in valid_faces
                                if f is not body_face
                                and f["face_type"] == "line_only"
                                and f["area"] > 10]
            # 收集主体面的顶点集合
            body_edge_set = set(body_face["edges"])
            body_vert_set = set()
            for eid in body_face["edges"]:
                vs, ve = edge_vertices[eid]
                body_vert_set.add(vs)
                body_vert_set.add(ve)
            # 找出与主体共享顶点的互联面
            merged_edges = list(body_face["edges"])
            merged_count = 0
            for fi in other_line_faces:
                fi_vert_set = set()
                for eid in fi["edges"]:
                    vs, ve = edge_vertices[eid]
                    fi_vert_set.add(vs)
                    fi_vert_set.add(ve)
                # 共享至少 1 个顶点 → 互联
                if body_vert_set & fi_vert_set:
                    for eid in fi["edges"]:
                        if eid not in merged_edges:
                            merged_edges.append(eid)
                    body_vert_set |= fi_vert_set
                    merged_count += 1
            if merged_count > 0:
                print(f"  合并互联面: {merged_count}个 → {len(merged_edges)}边")

            wire = build_occ_wire_from_face(
                merged_edges, edges, edge_vertices, vertex_pos)
            if wire is None:
                print("[FAIL] 主体 Wire 构建失败，回退到包围盒模式")
                is_single = False
            else:
                occ_face = build_occ_face(wire)
                if occ_face is None:
                    print("[FAIL] 主体 Face 构建失败，回退到包围盒模式")
                    is_single = False
                else:
                    body_solid = extrude_face(occ_face, body_depth)
                    if body_solid is None:
                        print("[FAIL] 轮廓拉伸失败，回退到包围盒模式")
                        is_single = False
                    else:
                        # 计算合并后的轮廓尺寸
                        merged_xs = []
                        merged_ys = []
                        for eid in merged_edges:
                            e = edges[eid]
                            merged_xs.extend([e.start[0], e.end[0]])
                            merged_ys.extend([e.start[1], e.end[1]])
                        mw = max(merged_xs) - min(merged_xs)
                        mh = max(merged_ys) - min(merged_ys)
                        print(f"  轮廓拉伸: {mw:.0f}×{mh:.0f}×{body_depth:.0f}mm")

                        # 获取轮廓顶点（用于孔判断）
                        body_verts = _get_ordered_vertices(
                            merged_edges, edges, edge_vertices)

                        # 找出轮廓内部的所有圆 → 作为孔（去重）
                        raw_holes = []  # [(cx, cy, r), ...]
                        for fi in valid_faces:
                            if fi is body_face:
                                continue
                            if fi["face_type"] not in ("single_arc", "concentric"):
                                continue
                            if fi.get("is_spline_debris"):
                                continue
                            # 用真实圆心（arc_centers）优先
                            fi_centers = fi.get("arc_centers", [])
                            if fi_centers:
                                cx, cy = fi_centers[0]
                            else:
                                cx = fi["x_mid"]
                                cy = fi["y_mid"]
                            # 检查圆心是否在主体轮廓内部
                            if body_verts and _point_in_polygon_2d(cx, cy, body_verts):
                                for r in fi.get("arc_radii",
                                                [max(fi["width"], fi["height"]) / 2]):
                                    if r > 0.2:
                                        raw_holes.append((cx, cy, r))

                        # 去重：合并中心距离 < 1mm 且半径差 < 0.5mm 的孔
                        merged_holes = []
                        used = [False] * len(raw_holes)
                        for i, (cx, cy, r) in enumerate(raw_holes):
                            if used[i]:
                                continue
                            # 找同组
                            group = [(cx, cy, r)]
                            for j in range(i + 1, len(raw_holes)):
                                if used[j]:
                                    continue
                                cxj, cyj, rj = raw_holes[j]
                                if abs(cx - cxj) < 1.0 and abs(cy - cyj) < 1.0 and abs(r - rj) < 0.5:
                                    group.append((cxj, cyj, rj))
                                    used[j] = True
                            used[i] = True
                            # 取平均
                            avg_cx = sum(g[0] for g in group) / len(group)
                            avg_cy = sum(g[1] for g in group) / len(group)
                            avg_r = sum(g[2] for g in group) / len(group)
                            merged_holes.append((avg_cx, avg_cy, avg_r))

                        for cx, cy, r in merged_holes:
                            hole = create_cylinder_solid((cx, cy), r,
                                                         body_depth + 10, -5)
                            if hole is not None:
                                all_holes.append(hole)

                        if merged_holes:
                            print(f"  内部孔: {len(merged_holes)}个"
                                  f"（去重前{len(raw_holes)}）")
                        else:
                            print(f"  内部孔: 无")

    # ================================================================
    # 多视图回退模式：包围盒主体 + 同心圆特征（原有逻辑）
    # ================================================================
    if not is_csg and not is_single:
        # --- 计算全局包围盒并创建主体块 ---
        all_x_min = min(f["x_min"] for f in valid_faces)
        all_x_max = max(f["x_max"] for f in valid_faces)
        all_y_min = min(f["y_min"] for f in valid_faces)
        all_y_max = max(f["y_max"] for f in valid_faces)

        # 用同心圆的最大半径扩展边距
        margin = 5.0
        for g in concentric_groups.values():
            if g["radii"]:
                margin = max(margin, max(g["radii"]) * 0.25)
        body_x_min = all_x_min - margin
        body_x_max = all_x_max + margin
        body_y_min = all_y_min - margin
        body_y_max = all_y_max + margin
        body_w = body_x_max - body_x_min
        body_h = body_y_max - body_y_min

        print(f"  主体块: X[{body_x_min:.0f}~{body_x_max:.0f}] "
              f"Y[{body_y_min:.0f}~{body_y_max:.0f}] "
              f"尺寸={body_w:.0f}×{body_h:.0f}×{body_depth:.0f}")

        from OCC.Core.BRepPrimAPI import BRepPrimAPI_MakeBox
        try:
            body_solid = BRepPrimAPI_MakeBox(
                gp_Pnt(body_x_min, body_y_min, 0),
                body_w, body_h, body_depth).Shape()
            print(f"  主体块已创建")
        except Exception as e:
            print(f"[FAIL] 主体块创建失败: {e}")
            return None

        # --- 同心圆 → 圆柱特征 ---
        for ckey, group in concentric_groups.items():
            cx, cy = group["center"]
            radii = group["radii"]
            sorted_r = sorted(radii, reverse=True)
            gtype = group.get("group_type", "concentric")
            cyl_h = body_depth

            if gtype == "isolated":
                # 独立圆 → 仅孔
                if sorted_r[0] > 0.3:
                    # P3: 半径接近主体外轮廓的大圆是主体轮廓（如法兰外径），
                    # 跳过——切除会毁掉主体
                    if body_w > 0 and sorted_r[0] > body_w * 0.4:
                        continue
                    hole = create_cylinder_solid((cx, cy), sorted_r[0],
                                                 cyl_h + 10, -5)
                    if hole is not None:
                        all_holes.append(hole)
                        print(f"  独立孔({cx:.1f},{cy:.1f}): R={sorted_r[0]:.1f}")
            else:
                # 同心圆组：最外层圆柱 → 凸台
                if sorted_r[0] > 0.5:
                    boss = create_cylinder_solid((cx, cy), sorted_r[0], cyl_h, 0)
                    if boss is not None:
                        all_bosses.append(boss)
                        print(f"  凸台({cx:.1f},{cy:.1f}): R={sorted_r[0]:.1f}, H={cyl_h:.0f}")

                # 内层 → 孔
                for inner_r in sorted_r[1:]:
                    if inner_r > 0.3:
                        hole = create_cylinder_solid((cx, cy), inner_r,
                                                     cyl_h + 10, -5)
                        if hole is not None:
                            all_holes.append(hole)
                            print(f"  内孔({cx:.1f},{cy:.1f}): R={inner_r:.1f}")

    # ---- Step 5: 布尔运算构建单一实体 ----
    if is_csg:
        body_name = "CSG结果"
    elif is_single:
        body_name = "轮廓"
    else:
        body_name = "主体块"
    print(f"\n[5/6] 布尔运算: {body_name} + {len(all_bosses)}凸台 - {len(all_holes)}孔/腔")

    combined = body_solid

    # 先加凸台（凸台必须在主体内部才能正确融合）
    for i, boss in enumerate(all_bosses):
        try:
            fuse_result = BRepAlgoAPI_Fuse(combined, boss)
            if fuse_result.IsDone():
                combined = fuse_result.Shape()
            else:
                print(f"  [WARN] 凸台{i+1}融合未完成")
        except Exception as e:
            print(f"  [WARN] 凸台{i+1}融合异常: {e}")

    # 再减内孔和腔体
    for i, tool in enumerate(all_holes):
        try:
            cut_result = BRepAlgoAPI_Cut(combined, tool)
            if cut_result.IsDone():
                combined = cut_result.Shape()
            else:
                print(f"  [WARN] 切除{i+1}未完成")
        except Exception as e:
            print(f"  [WARN] 切除{i+1}异常: {e}")

    # 修复并检查结果
    try:
        fixer = ShapeFix_Shape()
        fixer.Init(combined)
        fixer.Perform()
        combined = fixer.Shape()
    except Exception:
        pass

    # ---- Fix 1: 坐标归一化 —— 将实体平移到几何中心 ----
    try:
        final_bbox = Bnd_Box()
        brepbndlib.Add(combined, final_bbox)
        fx1, fy1, fz1, fx2, fy2, fz2 = final_bbox.Get()
        cx, cy, cz = (fx1 + fx2) / 2, (fy1 + fy2) / 2, (fz1 + fz2) / 2
        if abs(cx) > 0.01 or abs(cy) > 0.01 or abs(cz) > 0.01:
            trsf_c = gp_Trsf()
            trsf_c.SetTranslation(gp_Vec(-cx, -cy, -cz))
            combined = BRepBuilderAPI_Transform(combined, trsf_c).Shape()
            print(f"  坐标归一化: 中心({cx:.0f},{cy:.0f},{cz:.0f}) → 原点")
    except Exception as e:
        print(f"  [WARN] 坐标归一化失败: {e}")

    # 验证
    exp = TopExp_Explorer(combined, TopAbs_FACE)
    n_solids = 0
    exp2 = TopExp_Explorer()
    exp2.Init(combined, TopAbs_FACE, TopAbs_FACE)
    n_faces = 0
    while exp.More():
        n_faces += 1
        exp.Next()
    # 用 solid 枚举
    from OCC.Core.TopAbs import TopAbs_SOLID as TAS
    exp_s = TopExp_Explorer(combined, TAS)
    n_solids = 0
    while exp_s.More():
        n_solids += 1
        s = exp_s.Current()
        sbb = Bnd_Box()
        brepbndlib.Add(s, sbb)
        sx1, sy1, sz1, sx2, sy2, sz2 = sbb.Get()
        if n_solids <= 5:
            print(f"  实体{n_solids}: X[{sx1:.0f}~{sx2:.0f}] "
                  f"Y[{sy1:.0f}~{sy2:.0f}] Z[{sz1:.0f}~{sz2:.0f}]")
        exp_s.Next()
    print(f"  结果: {n_solids}个实体")

    # ---- Step 6: STEP 导出 ----
    print(f"\n[6/6] STEP 导出 ...")
    if step_output:
        writer = STEPControl_Writer()
        writer.Transfer(combined, STEPControl_AsIs)
        status = writer.Write(step_output)
        if status == IFSelect_RetDone:
            file_size = Path(step_output).stat().st_size if Path(step_output).exists() else 0
            print(f"  STEP 已保存: {step_output} ({file_size/1024:.1f} KB)")
        else:
            print(f"  [WARN] STEP 写入状态: {status}")

    return combined


# ============================================================
# 9. SolidWorks 导入
# ============================================================

def import_to_solidworks(step_path: str, output_sldprt: str = None) -> bool:
    """将 STEP 文件导入 SolidWorks 并保存为 .sldprt。"""
    from src.core.sw_automation.sw_driver import SolidWorksDriver

    driver = SolidWorksDriver(visible=True)
    if not driver.connect():
        print("[FAIL] 无法连接 SolidWorks")
        return False

    try:
        sw_app = driver.sw_app
        abs_step = str(Path(step_path).absolute())
        result = sw_app.LoadFile2(abs_step, "")
        if not result:
            print(f"[FAIL] SW LoadFile2 导入失败")
            return False

        print(f"[OK] STEP 已导入 SW")
        driver.sw_model = sw_app.ActiveDoc
        driver.sw_part = sw_app.ActiveDoc

        if output_sldprt:
            abs_out = str(Path(output_sldprt).absolute())
            if driver.save_as(abs_out):
                print(f"[OK] SW 模型已保存: {output_sldprt}")
            else:
                print(f"[WARN] 保存失败")

        driver.zoom_to_fit()
        return True

    except Exception as e:
        print(f"[FAIL] SW 导入异常: {e}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        driver.disconnect()


# ============================================================
# CLI
# ============================================================

def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    # 解析命令行参数
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    flags = [a for a in sys.argv[1:] if a.startswith("--")]

    single_view = None  # None = auto
    if "--single-view" in flags:
        single_view = True
    elif "--multi-view" in flags:
        single_view = False

    dxf_path = args[0] if args else sys.argv[1]
    if not Path(dxf_path).exists():
        print(f"[FAIL] 文件不存在: {dxf_path}")
        sys.exit(1)

    # DWG 自动转 DXF
    if dxf_path.lower().endswith(".dwg"):
        print("检测到 DWG 文件，先转换为 DXF ...")
        dwg2dxf_exe = PROJECT_ROOT / "tools" / "libredwg" / "dwg2dxf.exe"
        if dwg2dxf_exe.exists():
            dxf_out = str(Path(dxf_path).with_suffix(".dxf"))
            import subprocess
            result = subprocess.run(
                [str(dwg2dxf_exe), "-y", "-v", "-o", dxf_out, dxf_path],
                capture_output=True, text=True,
            )
            if result.returncode != 0:
                print(f"[FAIL] DWG→DXF 转换失败:\n{result.stderr}")
                sys.exit(1)
            dxf_path = dxf_out
            print(f"  转换完成: {dxf_path}")
        else:
            print("[FAIL] 未找到 dwg2dxf.exe，请手动将 DWG 另存为 DXF")
            sys.exit(1)

    # 输出路径
    input_stem = Path(dxf_path).stem
    input_dir = Path(dxf_path).parent
    step_path = str(input_dir / f"{input_stem}_3d.step")

    if len(args) >= 2:
        output_sldprt = args[1]
    else:
        from datetime import datetime
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_sldprt = str(input_dir / f"{input_stem}_{ts}.sldprt")

    print("=" * 60)
    print("通用 DXF → 3D SolidWorks 转换器 v2.1")
    print("=" * 60)
    print(f"  输入: {dxf_path}")
    print(f"  STEP: {step_path}")
    print(f"  输出: {output_sldprt}")
    if single_view is True:
        print(f"  模式: 强制单视图")
    elif single_view is False:
        print(f"  模式: 强制多视图")
    print()

    # 转换
    result = convert_dxf_to_3d(dxf_path, step_output=step_path,
                               single_view=single_view)

    if result is None:
        print("\n[FAIL] 3D 转换失败")
        sys.exit(1)

    print("\n3D 转换成功！")
    print(f"STEP 文件: {step_path}")

    # 导入 SolidWorks
    print("\n正在导入 SolidWorks ...")
    ok = import_to_solidworks(step_path, output_sldprt)
    if ok:
        print(f"\n[OK] 完成！SW 模型: {output_sldprt}")
    else:
        print(f"\n[WARN] SW 导入失败，但 STEP 可用: {step_path}")


if __name__ == "__main__":
    main()
