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
    from OCC.Core.TopAbs import TopAbs_EDGE, TopAbs_WIRE, TopAbs_FACE
    from OCC.Core.BRepCheck import BRepCheck_Analyzer
    from OCC.Core.BRep import BRep_Builder
    from OCC.Core.BRepTools import breptools
    from OCC.Core.BRepClass3d import BRepClass3d_SolidClassifier
    from OCC.Core.Bnd import Bnd_Box
    from OCC.Core.BRepBndLib import brepbndlib

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
        ("TopAbs_FACE", TopAbs_FACE),
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


def parse_dxf_edges(dxf_path: str) -> tuple[list[Edge], dict]:
    """从 DXF 提取所有几何实体为统一边列表。"""
    doc = ezdxf.readfile(dxf_path)
    msp = doc.modelspace()

    edges = []
    eid = 0
    entity_counts = {}

    # LINE（跳过中心线、构造线等辅助线）
    for e in msp.query("LINE"):
        lt = ""
        try:
            lt = (e.dxf.linetype or "").upper()
        except Exception:
            pass
        # 过滤中心线和构造线
        if lt in ("CENTER", "CENTER2", "CENTERX2", "DASHDOT", "PHANTOM",
                   "CONSTRUCTION", "HIDDEN", "HIDDEN2"):
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
    for e in msp.query("CIRCLE"):
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


# ============================================================
# 2. 图构建
# ============================================================

def _key(pt, tol=SNAP_TOL):
    return (round(pt[0] / tol) * tol, round(pt[1] / tol) * tol)


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


def build_adjacency(vertex_pos: dict, edge_vertices: list, edges: list[Edge],
                    num_vertices: int):
    """建立顶点邻接表，包含边角度信息。"""
    adj = {v: [] for v in range(num_vertices)}

    for eid, (vs, ve) in enumerate(edge_vertices):
        edge = edges[eid]
        if vs == ve:
            continue

        # 在 vs 处的切向角
        if edge.etype == "LINE":
            dx = vertex_pos[ve][0] - vertex_pos[vs][0]
            dy = vertex_pos[ve][1] - vertex_pos[vs][1]
        else:
            cx, cy = edge.center
            sx, sy = vertex_pos[vs]
            rx, ry = sx - cx, sy - cy
            if edge.clockwise:
                dx, dy = -ry, rx
            else:
                dx, dy = ry, -rx
        angle_vs = math.atan2(dy, dx)
        adj[vs].append((eid, ve, angle_vs))

        # 在 ve 处的切向角（反向）
        if edge.etype == "LINE":
            dx = vertex_pos[vs][0] - vertex_pos[ve][0]
            dy = vertex_pos[vs][1] - vertex_pos[ve][1]
        else:
            cx, cy = edge.center
            ex, ey = vertex_pos[ve]
            rx, ry = ex - cx, ey - cy
            if edge.clockwise:
                dx, dy = ry, -rx
            else:
                dx, dy = -ry, rx
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
                face_edges.append(best_eid)
                prev_v = cur_v
                cur_v = best_next
                prev_eid = best_eid

            if closed and len(face_edges) >= 2:
                faces.append(face_edges)

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
        wire_builder = BRepBuilderAPI_MakeWire()
        for eid in face_eids:
            e = edges[eid]
            vs, ve = edge_vertices[eid]
            p1 = vertex_pos[vs]
            p2 = vertex_pos[ve]

            if e.etype == "LINE":
                occ_edge = BRepBuilderAPI_MakeEdge(
                    gp_Pnt(p1[0] * sf, p1[1] * sf, 0),
                    gp_Pnt(p2[0] * sf, p2[1] * sf, 0),
                ).Edge()
            else:
                circ = gp_Circ(
                    gp_Ax2(gp_Pnt(e.center[0] * sf, e.center[1] * sf, 0),
                           gp_Dir(0, 0, 1)),
                    e.radius * sf,
                )
                a1 = math.radians(e.start_angle)
                a2_val = math.radians(e.end_angle)
                occ_edge = BRepBuilderAPI_MakeEdge(circ, a1, a2_val).Edge()
            wire_builder.Add(occ_edge)

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

# 多视图 → 3D 坐标映射
#   前视图 (Front, XY):  DXF_X→X, DXF_Y→Y, 拉伸方向 Z
#   俯视图 (Top, XZ):    DXF_X→X, DXF_Y→Z, 拉伸方向 Y
#   侧视图 (Side, YZ):   DXF_X→Z, DXF_Y→Y, 拉伸方向 X

def _get_view_transform(view_type):
    """返回 (rotation_axis, rotation_angle_rad, extrude_axis) 用于视图面变换。

    rotation_axis: 将 DXF XY 面旋转到目标平面的轴
    extrude_axis: 拉伸方向 (0=X, 1=Y, 2=Z)
    """
    if view_type == "front":
        return None, 0, 2       # 无需旋转，沿 Z 拉伸
    elif view_type == "top":
        return (1, 0, 0), -math.pi / 2, 1  # 绕 X 轴 -90° → XZ 面，沿 Y 拉伸
    elif view_type == "side":
        return (0, 1, 0), -math.pi / 2, 0  # 绕 Y 轴 -90° → ZY 面，沿 X 拉伸
    return None, 0, 2


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
        return BRepPrimAPI_MakePrism(occ_face, vecs[direction_axis]).Shape()
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


def _build_inner_cut_tool(face_info, view_type, edges, edge_vertices,
                          vertex_pos, scale_factor, extrude_half):
    """从内部面构建 3D 切割工具。

    将内部闭环拉伸为穿透整个 CSG 主体的棱柱，
    用于 BRepAlgoAPI_Cut 布尔减运算。

    extrude_half: 拉伸半长，确保工具完全穿透主体
    返回: TopoDS_Shape 或 None
    """
    eids = face_info.get("edges")
    if not eids:
        # 包围盒回退面没有边信息，跳过
        return None

    # 1) 构建 Wire → Face（DXF 坐标，应用缩放）
    wire = build_occ_wire_from_face(eids, edges, edge_vertices, vertex_pos,
                                    scale_factor)
    if wire is None:
        return None
    occ_face = build_occ_face(wire)
    if occ_face is None:
        return None

    # 2) 视图旋转变换（与外轮廓相同）
    rot_axis, rot_angle, extrude_axis = _get_view_transform(view_type)
    if rot_axis is not None:
        trsf = gp_Trsf()
        trsf.SetRotation(gp_Ax1(gp_Pnt(0, 0, 0), gp_Dir(*rot_axis)), rot_angle)
        occ_face = BRepBuilderAPI_Transform(occ_face, trsf).Shape()

    # 3) Z 对齐：非前视图需将旋转后面片的 Z_min 对齐到 Z=0
    #    （与外轮廓棱柱的构建逻辑一致，确保内外特征在同一坐标系）
    if view_type != "front":
        try:
            face_bbox = Bnd_Box()
            brepbndlib.Add(occ_face, face_bbox)
            _fx1, _fy1, fz_min, _fx2, _fy2, _fz2 = face_bbox.Get()
            if abs(fz_min) > 0.01:
                trsf_align = gp_Trsf()
                trsf_align.SetTranslation(gp_Vec(0, 0, -fz_min))
                occ_face = BRepBuilderAPI_Transform(occ_face, trsf_align).Shape()
        except Exception:
            pass

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

        # X 间隙阈值基于当前簇的 X 宽度（不是全局宽度）
        # 同一视图内的特征间隙不应触发拆分
        cluster_x_min = min(f["x_min"] for f in cluster)
        cluster_x_max = max(f["x_max"] for f in cluster)
        cluster_x_width = cluster_x_max - cluster_x_min
        x_gap_threshold = max(30.0, cluster_x_width * 0.30)

        # 按 X 坐标分组
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
                merged.extend(all_views[j])
                used.add(j)
        merged_views.append(merged)
        used.add(i)
    all_views = merged_views

    # --- 将跨越面分配到最匹配的最终视图 ---
    # （必须在合并之后，避免跨越面的 Y 范围导致错误合并）
    for sf in spanning_faces:
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
        # Y 最高的 → top（前提：显著高于其他视图）
        highest_y = y_ranks[0]
        second_y = y_ranks[1] if n > 1 else -1
        y_gap_views = (all_view_centers[highest_y][1]
                       - all_view_centers[second_y][1])
        if y_gap_views > total_y_range * 0.08:
            vtypes[highest_y] = "top"

        # X 最右的 → side（前提：显著右于其他视图，且不是 top）
        for xi in x_ranks:
            if vtypes[xi] != "front":
                continue
            # 检查是否显著偏右
            others_x = [all_view_centers[j][0] for j in range(n)
                        if j != xi and vtypes[j] != "top"]
            if others_x:
                avg_other_x = sum(others_x) / len(others_x)
                if all_view_centers[xi][0] > avg_other_x + total_x_range * 0.12:
                    vtypes[xi] = "side"
                    break

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


def csg_reconstruct(views, edges, edge_vertices, vertex_pos, scale_factor=1.0):
    """CSG 体积求交法：各视图轮廓拉伸为棱柱 → 布尔交集 → 3D 实体。

    原理:
      3D实体 = 前视图棱柱 ∩ 俯视图棱柱 ∩ 侧视图棱柱
      前视图棱柱 = 前视图外轮廓 沿 Z 拉伸
      俯视图棱柱 = 俯视图外轮廓 沿 Y 拉伸（面在 XZ 平面）
      侧视图棱柱 = 侧视图外轮廓 沿 X 拉伸（面在 YZ 平面）

    scale_factor: DXF 坐标 → 实物尺寸的缩放因子

    Returns: (body_solid, hole_data) 或 (None, None)
    """
    if len(views) < 2:
        return None, None  # 单视图不用 CSG

    # 计算全局拉伸距离（已考虑比例）
    all_x = []
    all_y = []
    for v in views:
        all_x.extend([v["bbox"][0] * scale_factor, v["bbox"][2] * scale_factor])
        all_y.extend([v["bbox"][1] * scale_factor, v["bbox"][3] * scale_factor])
    max_dim = max(max(all_x) - min(all_x), max(all_y) - min(all_y))
    extrude_dist = max_dim * 5  # "无限"拉伸

    # ---- Fix 4: 前视图有效 Y 范围（用于 Z 深度估算，在裁剪后动态更新） ----
    front_y_range = None  # 裁剪后的前视图 Y 范围

    prisms = []
    hole_data = []  # 每个视图的内孔信息

    for v in views:
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
                # 找到紧邻的上方视图（Y 更大的视图）
                above_ymin = min(other_views_ymin)  # 最近的视图的 Y_min
                outer_y_span = outer_face["y_max"] - outer_face["y_min"]

                # 如果跨越面的 Y 范围显著超过了到上方视图的间隙
                if above_ymin < outer_face["y_max"] and outer_y_span > 50:
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

        # ---- Fix 4: 记录前视图裁剪后的 Y 范围，用于 Z 深度估算 ----
        if v["name"] == "front" and outer_face is not None:
            front_y_range = (outer_face["y_max"] - outer_face["y_min"]) * scale_factor

        if outer_face is None:
            print(f"  [WARN] 视图 '{v['name']}' 无有效外轮廓，跳过")
            continue

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

        # 视图 → 3D 坐标变换
        rot_axis, rot_angle, extrude_axis = _get_view_transform(v["view_type"])

        if rot_axis is not None:
            trsf = gp_Trsf()
            trsf.SetRotation(
                gp_Ax1(gp_Pnt(0, 0, 0), gp_Dir(*rot_axis)), rot_angle)
            occ_face = BRepBuilderAPI_Transform(occ_face, trsf).Shape()

        # 对齐：非前视图需将 Z_min 平移到 0（与正视图 Z=0 对齐）
        if v["view_type"] != "front":
            face_bbox = Bnd_Box()
            brepbndlib.Add(occ_face, face_bbox)
            fx1, fy1, fz1, fx2, fy2, fz2 = face_bbox.Get()
            trsf_align = gp_Trsf()
            trsf_align.SetTranslation(gp_Vec(0, 0, -fz1))
            occ_face = BRepBuilderAPI_Transform(occ_face, trsf_align).Shape()

        # 拉伸为棱柱
        prism = _extrude_face_dual(occ_face, extrude_axis, extrude_dist)
        if prism is None:
            print(f"  [WARN] 视图 '{v['name']}' 拉伸失败")
            continue

        prisms.append(prism)
        print(f"  视图 '{v['name']}'({v['view_type']}): "
              f"轮廓={outer_face['area']:.0f}mm2, "
              f"棱柱轴={['X','Y','Z'][extrude_axis]}, "
              f"长={extrude_dist:.0f}mm")

        # 存储外轮廓引用，供后续内部特征处理使用
        v["_outer_face"] = outer_face

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
    print(f"\n  CSG 求交: {len(prisms)} 个棱柱 → 交集")
    try:
        combined = prisms[0]
        for i, p in enumerate(prisms[1:], 1):
            fuse_op = BRepAlgoAPI_Common(combined, p)
            if fuse_op.IsDone():
                combined = fuse_op.Shape()
            else:
                print(f"  [WARN] 棱柱{i+1}交集失败")
    except Exception as e:
        print(f"  [FAIL] CSG 交集异常: {e}")
        return None, None

    # 修复
    try:
        fixer = ShapeFix_Shape()
        fixer.Init(combined)
        fixer.Perform()
        combined = fixer.Shape()
    except Exception:
        pass

    # ---- Fix 4: Z 深度修正 ----
    # 如果俯视图 Y 范围太小（<前视图 Y 的 50%），说明俯视图不代表真实深度
    # 使用前视图 Y 范围作为 Z 深度进行非均匀缩放
    if front_y_range is not None and front_y_range > 0:
        try:
            csg_bbox = Bnd_Box()
            brepbndlib.Add(combined, csg_bbox)
            cx1, cy1, cz1, cx2, cy2, cz2 = csg_bbox.Get()
            csg_z = cz2 - cz1

            if csg_z > 0 and front_y_range > 0 and csg_z < front_y_range * 0.5:
                z_scale = front_y_range / csg_z
                print(f"  [Fix] Z 深度修正: CSG Z={csg_z:.0f} → "
                      f"目标 Z={front_y_range:.0f} (×{z_scale:.2f})")

                # 用 gp_GTrsf 做非均匀 Z 缩放
                gtrsf = gp_GTrsf()
                # 设置矩阵：对角线 (1, 1, z_scale)，以底部中心为基准
                gtrsf.SetValue(1, 1, 1.0)  # X scale
                gtrsf.SetValue(2, 2, 1.0)  # Y scale
                gtrsf.SetValue(3, 3, z_scale)  # Z scale
                # 平移部分：缩放后需要补偿位移（以 Z_min 为基准）
                gtrsf.SetValue(1, 4, 0)
                gtrsf.SetValue(2, 4, 0)
                gtrsf.SetValue(3, 4, cz1 * (1 - z_scale))  # 保持底部不动

                combined = BRepBuilderAPI_GTransform(combined, gtrsf).Shape()

                # 验证
                csg_bbox2 = Bnd_Box()
                brepbndlib.Add(combined, csg_bbox2)
                _, _, _, _, _, nz2 = csg_bbox2.Get()
                print(f"  [Fix] 修正后 Z={(nz2 - cz1):.0f}mm")
        except Exception as e:
            print(f"  [WARN] Z 深度修正失败: {e}")

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
                if outer_face["area"] > 0 and f["area"] > outer_face["area"] * 0.25:
                    continue
                if not _is_face_inside(f, outer_face):
                    continue
                inner_faces.append(f)

            if not inner_faces:
                continue

            vt = v["view_type"]
            for fi in inner_faces:
                tool = _build_inner_cut_tool(
                    fi, vt, edges, edge_vertices, vertex_pos,
                    scale_factor, half_extrude)
                if tool is None:
                    continue

                try:
                    cut_op = BRepAlgoAPI_Cut(combined, tool)
                    if cut_op.IsDone():
                        combined = cut_op.Shape()
                        inner_cut_count += 1
                except Exception:
                    pass

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
    vertex_pos, edge_vertices, num_vertices = build_vertex_map(edges)
    adj = build_adjacency(vertex_pos, edge_vertices, edges, num_vertices)
    faces = find_all_faces(adj, edges, edge_vertices)
    print(f"  顶点: {num_vertices}, 封闭环: {len(faces)}")

    if not faces:
        print("[FAIL] 无封闭环")
        return None

    faces_info = [analyze_face(f_ids, edges, edge_vertices, vertex_pos)
                  for f_ids in faces]

    # 预检：是否为多视图图纸（Y 方向有明显间隙）
    total_h_pre = bbox_max[1] - bbox_min[1]
    y_gap_th_pre = max(15.0, total_h_pre * 0.08)
    sorted_by_y = sorted(faces_info, key=lambda f: f["y_mid"])
    y_gaps = []
    for i in range(1, len(sorted_by_y)):
        gap = sorted_by_y[i]["y_min"] - sorted_by_y[i-1]["y_max"]
        if gap > y_gap_th_pre:
            y_gaps.append(gap)
    has_multi_views = len(y_gaps) >= 1

    # 过滤边框面
    border_idx = set()
    # 标记"跨越面"（跨多个视图的边框），在多视图分离时忽略它们
    spanning_idx = set()
    if has_multi_views:
        spanning_idx = {i for i, fi in enumerate(faces_info)
                        if (fi["y_max"] - fi["y_min"] > total_h * 0.85
                            and fi["x_max"] - fi["x_min"] > total_w * 0.60
                            and fi["area"] > total_area * 0.60
                            and len(fi["edges"]) <= 6)}
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
            views, edges, edge_vertices, vertex_pos, scale_factor)

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
            boss_count = 0
            hole_count = 0
            for ckey, group in concentric_groups.items():
                if not group["radii"]:
                    continue
                cx, cy = group["center"]
                radii = sorted(group["radii"], reverse=True)
                gtype = group.get("group_type", "concentric")

                # 判断：如果圆心 Y > 200（在俯视图区域），则映射到 3D 顶部
                is_top_view_feature = (cy > 200)

                if is_top_view_feature:
                    # 俯视图特征：DXF Y → 3D Z，放在主体顶面
                    feat_3d_x = cx * sf
                    feat_3d_y = body_cy  # Y 居中于主体
                    feat_z_base = bz2    # 从主体顶面开始
                else:
                    # 前视图特征：DXF 坐标直接映射到 3D XY
                    feat_3d_x = cx * sf
                    feat_3d_y = cy * sf
                    feat_z_base = bz2

                if gtype == "concentric":
                    # 同心圆组：最外层 = 凸台，内层 = 孔
                    boss_r = radii[0] * sf
                    inner_radii = [r * sf for r in radii[1:]]

                    # 凸台
                    boss_h = boss_r * 0.6
                    boss = create_cylinder_solid((feat_3d_x, feat_3d_y), boss_r,
                                                 boss_h, feat_z_base)
                    if boss is not None:
                        all_bosses.append(boss)
                        boss_count += 1

                    # 孔：贯穿
                    for hole_r in inner_radii:
                        hole = create_cylinder_solid((feat_3d_x, feat_3d_y), hole_r,
                                                     body_z + boss_h + 10,
                                                     bz1 - 5)
                        if hole is not None:
                            all_holes.append(hole)
                            hole_count += 1

                elif gtype == "isolated":
                    # 独立圆：仅孔（安装孔等贯穿孔）
                    hole_r = radii[0] * sf
                    hole = create_cylinder_solid((feat_3d_x, feat_3d_y), hole_r,
                                                 body_z + 20, bz1 - 5)
                    if hole is not None:
                        all_holes.append(hole)
                        hole_count += 1
                        print(f"  独立孔({feat_3d_x:.0f},{feat_3d_y:.0f}): "
                              f"R={hole_r:.1f}")

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
