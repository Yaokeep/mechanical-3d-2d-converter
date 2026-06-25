#!/usr/bin/env python
"""通用 DXF 工程图 → 3D SolidWorks 模型转换器 v2.0

核心改进（相比 v1.0）:
  1. 自动视图检测 — 基于文字标签 + 几何密度分析
  2. 主体优先 — 先识别最大非圆轮廓作为主体，再在其上加减特征
  3. 正确的圆柱体 — 同心圆弧 → 贯穿圆柱/孔
  4. SPLINE 智能处理 — 过滤采样产生的碎片面
  5. 剖面图支持 — 多剖面轮廓空间组合

用法:
    python dxf_to_3d_general.py <输入.dxf> [输出.sldprt]
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
        gp_Circ, gp_Trsf, gp_XYZ,
    )
    from OCC.Core.BRepBuilderAPI import (
        BRepBuilderAPI_MakeEdge, BRepBuilderAPI_MakeWire,
        BRepBuilderAPI_MakeFace, BRepBuilderAPI_Transform,
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
        ("gp_Trsf", gp_Trsf), ("gp_XYZ", gp_XYZ),
        ("BRepBuilderAPI_MakeEdge", BRepBuilderAPI_MakeEdge),
        ("BRepBuilderAPI_MakeWire", BRepBuilderAPI_MakeWire),
        ("BRepBuilderAPI_MakeFace", BRepBuilderAPI_MakeFace),
        ("BRepBuilderAPI_Transform", BRepBuilderAPI_Transform),
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

    # LINE
    for e in msp.query("LINE"):
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
        pts = list(e.vertices())
        if len(pts) < 2:
            continue
        for i in range(len(pts) - 1):
            x1, y1 = pts[i].dxf.location.x, pts[i].dxf.location.y
            x2, y2 = pts[i+1].dxf.location.x, pts[i+1].dxf.location.y
            try:
                bulge = pts[i].dxf.bulge
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
            closed = True

            for _ in range(num_edges * 4):
                if cur_v == u:
                    break

                incoming_angle = None
                for eid_in, other, ang in adj.get(cur_v, []):
                    if other == prev_v:
                        incoming_angle = ang
                        break

                if incoming_angle is None:
                    closed = False
                    break

                out_angle_ref = incoming_angle + math.pi
                if out_angle_ref > math.pi:
                    out_angle_ref -= 2 * math.pi

                candidates = adj.get(cur_v, [])
                if len(candidates) <= 1:
                    closed = False
                    break

                best_eid = None
                best_next = None
                best_cw_angle = -float("inf")

                for eid_out, other_v, ang_out in candidates:
                    if other_v == cur_v:
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

        # 需要至少 2 个不同半径才认为是同心圆组
        if len(all_radii) >= 2:
            merged[canon_key] = {
                "center": (avg_x, avg_y),
                "radii": sorted(all_radii),
                "face_indices": all_face_indices,
                "count": sum(len(arc_by_center[c]) for c in cluster),
            }

    return merged


# ============================================================
# 7. OCC 几何创建
# ============================================================

def build_occ_wire_from_face(face_eids, edges, edge_vertices, vertex_pos):
    """从面边列表构建 OCC Wire。"""
    try:
        wire_builder = BRepBuilderAPI_MakeWire()
        for eid in face_eids:
            e = edges[eid]
            vs, ve = edge_vertices[eid]
            p1 = vertex_pos[vs]
            p2 = vertex_pos[ve]

            if e.etype == "LINE":
                occ_edge = BRepBuilderAPI_MakeEdge(
                    gp_Pnt(p1[0], p1[1], 0),
                    gp_Pnt(p2[0], p2[1], 0),
                ).Edge()
            else:
                circ = gp_Circ(
                    gp_Ax2(gp_Pnt(e.center[0], e.center[1], 0), gp_Dir(0, 0, 1)),
                    e.radius,
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


def get_shape_bbox(shape) -> tuple:
    """获取 shape 的包围盒。"""
    bbox = Bnd_Box()
    brepbndlib.Add(shape, bbox)
    return bbox.Get()


# ============================================================
# 8. 主转换流程（全新设计）
# ============================================================

def convert_dxf_to_3d(dxf_path: str, step_output: str = None,
                      extrusion_depth: float = None) -> object:
    """通用 DXF → 3D 转换器 v2.0。

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
    print(f"[1/8] 解析 DXF: {dxf_path}")
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

    # ---- Step 2: 建图 ----
    print(f"\n[2/8] 建图 ...")
    vertex_pos, edge_vertices, num_vertices = build_vertex_map(edges)
    print(f"  顶点: {num_vertices}")
    adj = build_adjacency(vertex_pos, edge_vertices, edges, num_vertices)

    # ---- Step 3: 面遍历 ----
    print(f"\n[3/8] 面遍历 ...")
    faces = find_all_faces(adj, edges, edge_vertices)
    print(f"  封闭环: {len(faces)}")

    if not faces:
        print("[FAIL] 无封闭环")
        return None

    # ---- Step 4: 面分析 + 过滤 ----
    print(f"\n[4/8] 面分析与过滤 ...")
    faces_info = []
    for f_ids in faces:
        fi = analyze_face(f_ids, edges, edge_vertices, vertex_pos)
        faces_info.append(fi)

    # 过滤 1: 页面边框（面积 > 25% 总 bbox 且边的数量 ≤6）
    border_idx = set()
    for i, fi in enumerate(faces_info):
        if fi["area"] > total_area * 0.25 and len(fi["edges"]) <= 6:
            border_idx.add(i)
            print(f"  [过滤-边框] 环{i+1}: 面积={fi['area']:.0f}")

    # 过滤 2: SPLINE 碎片
    spline_idx = set()
    for i, fi in enumerate(faces_info):
        if fi["is_spline_debris"] and i not in border_idx:
            spline_idx.add(i)
    if spline_idx:
        print(f"  [过滤-SPLINE碎片] {len(spline_idx)} 个面")

    # 过滤 3: 过小面（< 中位面积的 0.05%）
    areas = [fi["area"] for i, fi in enumerate(faces_info)
             if i not in border_idx and i not in spline_idx]
    if areas:
        median_area = sorted(areas)[len(areas) // 2]
        min_area_threshold = max(0.5, median_area * 0.0005)
    else:
        min_area_threshold = 0.5

    tiny_idx = set()
    for i, fi in enumerate(faces_info):
        if i in border_idx or i in spline_idx:
            continue
        if fi["area"] < min_area_threshold:
            tiny_idx.add(i)

    # 有效面
    valid_indices = [i for i in range(len(faces_info))
                     if i not in border_idx
                     and i not in spline_idx
                     and i not in tiny_idx]
    valid_faces = [faces_info[i] for i in valid_indices]

    print(f"  有效环: {len(valid_faces)} (边框{len(border_idx)} "
          f"+ SPLINE碎片{len(spline_idx)} + 过小{len(tiny_idx)} 已过滤)")

    if not valid_faces:
        print("[FAIL] 所有面均被过滤")
        return None

    # ---- Step 5: 视图检测 ----
    print(f"\n[5/8] 视图检测 ...")
    view_info = detect_views(valid_faces, texts,
                             (bbox_min, bbox_max), total_area)
    view_regions = view_info["view_regions"]
    main_region = view_info.get("main_body_region")
    print(f"  检测到 {len(view_regions)} 个视图区域:")
    for item in view_regions:
        name, ylo, yhi = item[0], item[1], item[2]
        vtype = item[3] if len(item) >= 4 else "unknown"
        n_faces = sum(1 for f in valid_faces if ylo <= f["y_mid"] <= yhi)
        marker = " [主体]" if name == main_region else ""
        print(f"    {name}: Y={ylo:.0f}~{yhi:.0f}, {n_faces}个面, 类型={vtype}{marker}")

    # ---- Step 6: 按视图创建 3D 实体 ----
    print(f"\n[6/8] 按视图创建 3D 实体 ...")

    # 估算总体深度
    if extrusion_depth is not None:
        total_depth = extrusion_depth
    else:
        max_arc_r = 0
        for f in valid_faces:
            if f["arc_radii"]:
                max_arc_r = max(max_arc_r, max(f["arc_radii"]))
        if max_arc_r > 0:
            total_depth = max_arc_r * 4
        else:
            total_depth = part_scale * 0.3
    total_depth = max(total_depth, 10.0)

    n_regions = max(1, len(view_regions))
    # 每个区域的基本深度（总深度均分）
    base_d = total_depth / n_regions
    # 累计 Z 偏移（确保区域不重叠）
    cum_z = 0.0
    view_solids = []

    for region_idx, item in enumerate(view_regions):
        name, ylo, yhi = item[0], item[1], item[2]
        vtype = item[3] if len(item) >= 4 else "unknown"

        region_faces = [f for f in valid_faces
                        if ylo <= f["y_mid"] <= yhi
                        and not f["is_spline_debris"]]

        if not region_faces:
            continue

        # 视图深度：圆柱型贯穿全部，棱柱型按比例
        if vtype == "cylindrical":
            view_depth = total_depth  # 贯穿整个深度
        else:
            view_depth = base_d * 1.5
        view_depth = max(view_depth, 5.0)

        # Z 偏移 = 累计偏移（确保不重叠）
        z_offset = cum_z
        cum_z += view_depth  # 下一层从此层的顶部开始

        print(f"\n  {name} (Z={z_offset:.0f}~{z_offset+view_depth:.0f}): "
              f"{len(region_faces)}个面, 类型={vtype}")

        # 此视图的同心圆
        region_conc = cluster_concentric_arcs(
            region_faces, edges, edge_vertices, vertex_pos)
        conc_face_idx = set()
        for ckey, group in region_conc.items():
            conc_face_idx.update(group["face_indices"])

        if region_conc:
            print(f"    {len(region_conc)}组同心圆:")
            for ckey, group in sorted(region_conc.items(),
                                       key=lambda x: -x[1]["count"]):
                print(f"      中心({ckey[0]:.1f},{ckey[1]:.1f}): "
                      f"R={group['radii']}")

        region_add = []

        # 同心圆 → 贯穿圆柱（内孔先切削外层，深度贯穿整个零件）
        for ckey, group in region_conc.items():
            cx, cy = group["center"]
            radii = group["radii"]
            sorted_r = sorted(radii, reverse=True)
            # 圆柱体使用总深度（贯穿整个零件）
            cyl_height = total_depth
            cyl_z = 0  # 从 Z=0 开始

            if sorted_r[0] > 0.5:
                outer_cyl = create_cylinder_solid((cx, cy), sorted_r[0],
                                                   cyl_height, cyl_z)
                if outer_cyl is None:
                    continue

                current = outer_cyl
                for inner_r in sorted_r[1:]:
                    if inner_r > 0.3:
                        hole = create_cylinder_solid(
                            (cx, cy), inner_r, cyl_height + 10, cyl_z - 5)
                        if hole is not None:
                            try:
                                cut_result = BRepAlgoAPI_Cut(current, hole)
                                if cut_result.IsDone():
                                    current = cut_result.Shape()
                            except Exception:
                                pass

                region_add.append(current)
                print(f"    同心圆柱({cx:.1f},{cy:.1f}): "
                      f"R={sorted_r[0]:.1f}->{sorted_r[-1]:.1f}, "
                      f"H贯穿={cyl_height:.0f}")

        # 非圆轮廓 → 拉伸
        line_faces = [f for f in region_faces
                      if f["face_type"] == "line_only" and f["area"] > 5]
        line_faces_filt = [f for f in line_faces
                           if region_faces.index(f) not in conc_face_idx]
        line_faces_filt.sort(key=lambda f: -f["area"])

        if not line_faces_filt:
            continue

        body_face = line_faces_filt[0]
        body_area = body_face["area"]

        # 过滤：跳过完全在主体内部的面（剖面线区域，主体拉伸已覆盖）
        outer_faces = [body_face]
        for f in line_faces_filt[1:]:
            # 检查是否在主体轮廓内部
            inside_body = (
                f["x_min"] >= body_face["x_min"] - 0.5 and
                f["x_max"] <= body_face["x_max"] + 0.5 and
                f["y_min"] >= body_face["y_min"] - 0.5 and
                f["y_max"] <= body_face["y_max"] + 0.5
            )
            if not inside_body:
                outer_faces.append(f)
            # 内部面跳过（已被主体拉伸覆盖）

        for f in outer_faces:
            wire = build_occ_wire_from_face(
                f["edges"], edges, edge_vertices, vertex_pos)
            if wire is None:
                continue
            occ_face = build_occ_face(wire)
            if occ_face is None:
                continue

            # 主体用全深度
            local_d = view_depth if f is body_face else view_depth * 0.8
            local_d = max(local_d, 1.0)

            solid = extrude_face(occ_face, local_d)
            if solid is None:
                continue

            # 移动到 Z 位置
            try:
                trsf = gp_Trsf()
                trsf.SetTranslation(gp_Vec(0, 0, z_offset))
                solid = BRepBuilderAPI_Transform(solid, trsf, True).Shape()
            except Exception:
                pass

            region_add.append(solid)
            if f is body_face:
                print(f"    主体: 面积={f['area']:.0f}, {len(f['edges'])}边, "
                      f"深={local_d:.0f}")
            else:
                print(f"    外部特征: 面积={f['area']:.0f}, {len(f['edges'])}边, "
                      f"深={local_d:.0f}")

        # 合并此视图的所有加法特征（手动构建复合体避免 Fuse 丢实体）
        if region_add:
            if len(region_add) == 1:
                rc = region_add[0]
            else:
                from OCC.Core.BRep import BRep_Builder
                from OCC.Core.TopoDS import TopoDS_Compound
                builder = BRep_Builder()
                rc = TopoDS_Compound()
                builder.MakeCompound(rc)
                for s in region_add:
                    builder.Add(rc, s)
            view_solids.append((name, z_offset, rc))
            print(f"    视图实体已合并 ({len(region_add)}个特征)")

    if not view_solids:
        print("[FAIL] 无有效几何体")
        return None

    # ---- Step 7: 合并所有视图实体（手动构建复合体） ----
    print(f"\n[7/8] 合并所有视图 ... ({len(view_solids)}个)")
    from OCC.Core.BRep import BRep_Builder as BB2
    from OCC.Core.TopoDS import TopoDS_Compound as TC2
    builder = BB2()
    combined = TC2()
    builder.MakeCompound(combined)
    for name, z_off, solid in view_solids:
        builder.Add(combined, solid)
        print(f"  + {name} (Z={z_off:.0f})")
    print(f"  最终实体已创建 (类型={combined.ShapeType()})")

    # ---- Step 8: STEP 导出 ----
    print(f"\n[8/8] STEP 导出 ...")
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

    dxf_path = sys.argv[1]
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

    if len(sys.argv) >= 3:
        output_sldprt = sys.argv[2]
    else:
        from datetime import datetime
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_sldprt = str(input_dir / f"{input_stem}_{ts}.sldprt")

    print("=" * 60)
    print("通用 DXF → 3D SolidWorks 转换器 v2.0")
    print("=" * 60)
    print(f"  输入: {dxf_path}")
    print(f"  STEP: {step_path}")
    print(f"  输出: {output_sldprt}")
    print()

    # 转换
    result = convert_dxf_to_3d(dxf_path, step_output=step_path)

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
