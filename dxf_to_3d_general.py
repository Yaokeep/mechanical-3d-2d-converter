#!/usr/bin/env python
"""通用 DXF 工程图 → 3D SolidWorks 模型转换器

将任意 2D CAD 工程图转换为 3D 实体模型。核心思路：
  1. 解析 LINE/ARC/CIRCLE → 统一边表示
  2. 端点合并（邻近容差）→ 建图
  3. 平面图面遍历 → 封闭轮廓
  4. 智能拉伸（按截面区域 + 几何类型）
  5. 布尔合并 → 单一实体
  6. STEP 导出 → SolidWorks COM 导入

用法:
    python dxf_to_3d_general.py <输入.dxf> [输出.sldprt]
    python dxf_to_3d_general.py CAD/reducer.dxf
"""

import math
import sys
import os
from pathlib import Path

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
    # 基础几何
    from OCC.Core.gp import (
        gp_Pnt, gp_Dir, gp_Ax1, gp_Ax2, gp_Vec,
        gp_Circ, gp_Trsf, gp_XYZ,
    )
    # 边/线框/面构建
    from OCC.Core.BRepBuilderAPI import (
        BRepBuilderAPI_MakeEdge,
        BRepBuilderAPI_MakeWire,
        BRepBuilderAPI_MakeFace,
        BRepBuilderAPI_Transform,
    )
    # 拉伸/旋转
    from OCC.Core.BRepPrimAPI import (
        BRepPrimAPI_MakePrism,
        BRepPrimAPI_MakeRevol,
        BRepPrimAPI_MakeCylinder,
    )
    # 布尔运算
    from OCC.Core.BRepAlgoAPI import (
        BRepAlgoAPI_Fuse,
        BRepAlgoAPI_Cut,
    )
    # 形状修复
    from OCC.Core.ShapeFix import ShapeFix_Face, ShapeFix_Wire
    # 拓扑类型
    from OCC.Core.TopoDS import TopoDS_Shape, TopoDS_Face, TopoDS_Wire
    # STEP 导出
    from OCC.Core.STEPControl import STEPControl_Writer, STEPControl_AsIs
    from OCC.Core.IFSelect import IFSelect_RetDone
    # 拓扑工具
    from OCC.Core.TopExp import TopExp_Explorer
    from OCC.Core.TopAbs import TopAbs_EDGE, TopAbs_WIRE, TopAbs_FACE
    from OCC.Core.BRepCheck import BRepCheck_Analyzer
    from OCC.Core.BRep import BRep_Builder
    from OCC.Core.BRepTools import breptools
    # 投影/分类
    from OCC.Core.BRepClass3d import BRepClass3d_SolidClassifier
    from OCC.Core.TopoDS import topods

    g = globals()
    g.update({
        "gp_Pnt": gp_Pnt, "gp_Dir": gp_Dir, "gp_Ax1": gp_Ax1,
        "gp_Ax2": gp_Ax2, "gp_Vec": gp_Vec, "gp_Circ": gp_Circ,
        "gp_Trsf": gp_Trsf, "gp_XYZ": gp_XYZ,
        "BRepBuilderAPI_MakeEdge": BRepBuilderAPI_MakeEdge,
        "BRepBuilderAPI_MakeWire": BRepBuilderAPI_MakeWire,
        "BRepBuilderAPI_MakeFace": BRepBuilderAPI_MakeFace,
        "BRepBuilderAPI_Transform": BRepBuilderAPI_Transform,
        "BRepPrimAPI_MakePrism": BRepPrimAPI_MakePrism,
        "BRepPrimAPI_MakeRevol": BRepPrimAPI_MakeRevol,
        "BRepPrimAPI_MakeCylinder": BRepPrimAPI_MakeCylinder,
        "BRepAlgoAPI_Fuse": BRepAlgoAPI_Fuse,
        "BRepAlgoAPI_Cut": BRepAlgoAPI_Cut,
        "ShapeFix_Face": ShapeFix_Face,
        "ShapeFix_Wire": ShapeFix_Wire,
        "STEPControl_Writer": STEPControl_Writer,
        "STEPControl_AsIs": STEPControl_AsIs,
        "IFSelect_RetDone": IFSelect_RetDone,
        "TopExp_Explorer": TopExp_Explorer,
        "TopAbs_EDGE": TopAbs_EDGE,
        "TopAbs_WIRE": TopAbs_WIRE,
        "TopAbs_FACE": TopAbs_FACE,
        "BRepCheck_Analyzer": BRepCheck_Analyzer,
        "BRep_Builder": BRep_Builder,
        "TopoDS_Shape": TopoDS_Shape,
        "TopoDS_Face": TopoDS_Face,
        "breptools": breptools,
        "BRepClass3d_SolidClassifier": BRepClass3d_SolidClassifier,
    })
    _OCC_LOADED = True


# ---- 容差 ----
SNAP_TOL = 0.01  # 端点合并容差 (mm)


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
        self.etype = etype  # "LINE" | "ARC"
        self.start = start  # (x, y)
        self.end = end      # (x, y)
        self.center = center
        self.radius = radius
        self.start_angle = start_angle  # 度
        self.end_angle = end_angle      # 度
        self.clockwise = clockwise

    @property
    def length_2d(self):
        dx = self.end[0] - self.start[0]
        dy = self.end[1] - self.start[1]
        if self.etype == "LINE":
            return math.hypot(dx, dy)
        else:
            # 圆弧长度 = r * Δθ
            da = abs(self.end_angle - self.start_angle)
            if da > 180:
                da = 360 - da
            return self.radius * math.radians(da)

    def is_zero_length(self):
        return self.length_2d < SNAP_TOL


def parse_dxf_edges(dxf_path: str) -> tuple[list[Edge], dict]:
    """从 DXF 提取所有 LINE/ARC/CIRCLE 为统一边列表。

    返回 (edges, metadata)。
    - edges: Edge 列表
    - metadata: {bbox_min, bbox_max, entity_counts, layer_info}
    """
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
        # 计算起止点
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
        # 弧1: 0°→180°
        e1 = Edge(eid, "ARC",
                  (cx + r, cy), (cx - r, cy),
                  center=(cx, cy), radius=r,
                  start_angle=0, end_angle=180)
        eid += 1
        # 弧2: 180°→360°
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
        bulge = None
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
                # bulge = tan(θ/4), θ 为弧所对圆心角
                theta = 4 * math.atan(abs(bulge))
                chord = math.hypot(x2 - x1, y2 - y1)
                if chord < SNAP_TOL or theta < 1e-9:
                    continue
                r = chord / (2 * math.sin(theta / 2))
                # 弦中点
                mx, my = (x1 + x2) / 2, (y1 + y2) / 2
                # 弦方向
                dx, dy = x2 - x1, y2 - y1
                # 法向量（左侧）
                nx, ny = -dy / chord, dx / chord
                # 圆心偏移
                offset = r * math.cos(theta / 2)
                if bulge > 0:
                    cx = mx + nx * offset
                    cy = my + ny * offset
                else:
                    cx = mx - nx * offset
                    cy = my - ny * offset
                # 角度
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

    # SPLINE → 采样为 LINE 段
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
    xs = []
    ys = []
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


# ============================================================
# 2. 端点合并且建图
# ============================================================

def _key(pt, tol=SNAP_TOL):
    """将点坐标量化为网格键。"""
    return (round(pt[0] / tol) * tol, round(pt[1] / tol) * tol)


def build_vertex_map(edges: list[Edge]):
    """合并邻近端点，建立 vertex_id → (x, y) 映射与每条边的 vertex 端点。

    返回:
        vertex_pos: {vid: (x, y)}
        edge_vertices: [(vid_start, vid_end), ...] 与 edges 等长
    """
    # 收集所有端点
    points = []
    for e in edges:
        points.append(e.start)
        points.append(e.end)

    # 量化合并
    key_to_vid = {}
    vertex_pos = {}
    next_vid = 0

    for pt in points:
        k = _key(pt)
        if k not in key_to_vid:
            key_to_vid[k] = next_vid
            vertex_pos[next_vid] = k  # 使用量化后的坐标
            next_vid += 1

    # 建边-顶点映射
    edge_vertices = []
    for e in edges:
        vs = key_to_vid[_key(e.start)]
        ve = key_to_vid[_key(e.end)]
        edge_vertices.append((vs, ve))

    return vertex_pos, edge_vertices, next_vid


def build_adjacency(vertex_pos: dict, edge_vertices: list, edges: list[Edge],
                    num_vertices: int):
    """建立顶点邻接表，包含边角度信息。

    返回:
        adj: {vid: [(eid, other_vid, angle_at_vid), ...]}
    """
    adj = {v: [] for v in range(num_vertices)}

    for eid, (vs, ve) in enumerate(edge_vertices):
        edge = edges[eid]
        # 角度计算：在 vs 处，边的出方向
        if vs == ve:
            continue  # 跳过零长度边

        # 在 vs 处的切向角
        if edge.etype == "LINE":
            dx = vertex_pos[ve][0] - vertex_pos[vs][0]
            dy = vertex_pos[ve][1] - vertex_pos[vs][1]
        else:
            # ARC: 在起点 vs 处的切向
            cx, cy = edge.center
            sx, sy = vertex_pos[vs]
            # 径向向外
            rx, ry = sx - cx, sy - cy
            # 切向（逆时针旋转 90°）
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

    # 按角度排序（从 -π 到 π）
    for v in adj:
        adj[v].sort(key=lambda x: x[2])

    return adj


# ============================================================
# 3. 平面图面遍历 — 找所有封闭环
# ============================================================

def find_all_faces(adj: dict, edges: list[Edge], edge_vertices: list):
    """使用平面图面遍历算法找到所有封闭环。

    对每条有向边 (u→v)，从 v 出发沿顺时针最靠近的边继续走，
    直到回到起点。每条无向边恰好被两个面使用（正反方向各一次）。

    返回:
        faces: [[eid1, eid2, ...], ...]  每个面是一组边的有序列表
    """
    num_edges = len(edges)
    if num_edges == 0:
        return []

    # 记录每条有向边是否已被使用
    # 键: (eid, from_vid, to_vid) — 每条无向边有两个有向键
    used = {}
    for eid, (vs, ve) in enumerate(edge_vertices):
        if vs != ve:
            used[(eid, vs, ve)] = False
            used[(eid, ve, vs)] = False

    faces = []

    for eid_start, (vs_start, ve_start) in enumerate(edge_vertices):
        if vs_start == ve_start:
            continue
        # 两个方向都要检查
        for u, v in [(vs_start, ve_start), (ve_start, vs_start)]:
            dkey = (eid_start, u, v)
            if dkey not in used:
                continue
            if used[dkey]:
                continue
            used[dkey] = True

            face_edges = [eid_start]
            cur_v = v
            prev_v = u
            closed = True
            max_steps = num_edges * 4  # 安全上限

            for _ in range(max_steps):
                if cur_v == u:
                    break

                # 在 cur_v 处，找到从 prev_v 来的那个入射边的角度
                # 入射边的方向是 prev_v→cur_v，在 cur_v 处的入射角
                incoming_angle = None
                for eid_in, other, ang in adj.get(cur_v, []):
                    if other == prev_v:
                        incoming_angle = ang
                        break

                if incoming_angle is None:
                    closed = False
                    break

                # 入射方向反向后即为 next 边的参考方向
                out_angle_ref = incoming_angle + math.pi
                if out_angle_ref > math.pi:
                    out_angle_ref -= 2 * math.pi

                # 在所有相邻边中找顺时针最近的下一条
                candidates = adj.get(cur_v, [])
                if len(candidates) <= 1:
                    closed = False
                    break

                # 从入射方向顺时针转，找到第一条未使用的出边
                best_eid = None
                best_next = None
                best_cw_angle = -float("inf")  # 顺时针最大负角 = 最近顺时针

                for eid_out, other_v, ang_out in candidates:
                    if other_v == cur_v:
                        continue
                    dk = (eid_out, cur_v, other_v)
                    if dk not in used:
                        continue
                    if used[dk]:
                        continue
                    # 计算从 out_angle_ref 顺时针到 ang_out 的角度
                    # 顺时针为正（角度减小），范围 [0, 2π)
                    cw_angle = out_angle_ref - ang_out
                    if cw_angle < -math.pi:
                        cw_angle += 2 * math.pi
                    if cw_angle < 0:
                        cw_angle += 2 * math.pi
                    # 取最大的顺时针角度（即最小的顺时针旋转）
                    # 等价于找最接近 out_angle_ref 顺时针方向的边
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
        # 旋转到最小边ID开头，同时尝试反向
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
# 4. 面 → OCC Face
# ============================================================

def edge_to_occ_edge(edge: Edge, vertex_pos: dict, edge_vertices: list, eid: int):
    """将一条 Edge 转为 OCC 边（TopoDS_Edge）。"""
    vs, ve = edge_vertices[eid]
    p1 = vertex_pos[vs]
    p2 = vertex_pos[ve]

    if edge.etype == "LINE":
        return BRepBuilderAPI_MakeEdge(
            gp_Pnt(p1[0], p1[1], 0),
            gp_Pnt(p2[0], p2[1], 0),
        ).Edge()
    else:
        cx, cy = edge.center
        # ARC: 需要确定圆弧方向与起止角度
        circ = gp_Circ(
            gp_Ax2(gp_Pnt(cx, cy, 0), gp_Dir(0, 0, 1)),
            edge.radius,
        )
        # 计算实际起止角（注意 OCC 的弧度制）
        a1 = math.radians(edge.start_angle)
        a2_val = math.radians(edge.end_angle)
        return BRepBuilderAPI_MakeEdge(circ, a1, a2_val).Edge()


def build_occ_face(face_edges: list[int], edges: list[Edge],
                   vertex_pos: dict, edge_vertices: list) -> object:
    """从面边列表构建 OCC TopoDS_Face。"""
    try:
        wire_builder = BRepBuilderAPI_MakeWire()
        for eid in face_edges:
            occ_edge = edge_to_occ_edge(edges[eid], vertex_pos,
                                        edge_vertices, eid)
            wire_builder.Add(occ_edge)
        wire = wire_builder.Wire()

        # 修复 wire
        fixer = ShapeFix_Wire()
        fixer.Load(wire)
        fixer.FixReorder()
        fixer.FixConnected()
        fixer.FixClosed()
        fixed_wire = fixer.Wire()

        face = BRepBuilderAPI_MakeFace(fixed_wire).Face()
        return face
    except Exception:
        return None


# ============================================================
# 5. 智能拉伸
# ============================================================

def extrude_face(occ_face, depth: float) -> object:
    """沿 Z 轴拉伸一个面到给定深度。"""
    if depth <= 0:
        return None
    try:
        vec = gp_Vec(0, 0, depth)
        prism = BRepPrimAPI_MakePrism(occ_face, vec).Shape()
        return prism
    except Exception:
        return None


def revolve_circle_face(occ_face, edge_list: list[int], edges: list[Edge],
                         vertex_pos: dict, edge_vertices: list) -> object:
    """检测环形面并尝试旋转成圆柱/圆筒。"""
    # 判断是否为完整圆（所有边都是 ARC，且形成一个环）
    if len(edge_list) < 2:
        return None
    all_arc = all(edges[eid].etype == "ARC" for eid in edge_list)
    if not all_arc:
        return None
    # 检查圆心是否一致
    centers = set()
    for eid in edge_list:
        e = edges[eid]
        centers.add((round(e.center[0], 3), round(e.center[1], 3)))
    if len(centers) != 1:
        return None

    # 找最小半径（内孔）和最大半径（外径）
    min_r = min(edges[eid].radius for eid in edge_list)
    max_r = max(edges[eid].radius for eid in edge_list)
    cx, cy = edges[edge_list[0]].center

    # 创建圆柱体
    try:
        height = abs(max_r - min_r) * 5  # 经验高度
        if min_r < 0.1:
            # 实心圆柱
            cyl = BRepPrimAPI_MakeCylinder(
                gp_Ax2(gp_Pnt(cx, cy, 0), gp_Dir(0, 0, 1)),
                max_r, height,
            ).Shape()
            return cyl
        else:
            # 圆筒 = 大圆柱 - 小圆柱
            outer = BRepPrimAPI_MakeCylinder(
                gp_Ax2(gp_Pnt(cx, cy, 0), gp_Dir(0, 0, 1)),
                max_r, height,
            ).Shape()
            inner = BRepPrimAPI_MakeCylinder(
                gp_Ax2(gp_Pnt(cx, cy, 0), gp_Dir(0, 0, 1)),
                min_r, height + 1,  # 稍微长一点确保穿透
            ).Shape()
            from OCC.Core.BRepAlgoAPI import BRepAlgoAPI_Cut
            result = BRepAlgoAPI_Cut(outer, inner).Shape()
            return result
    except Exception:
        return None


def determine_extrusion_depth(face_edges: list[int], edges: list[Edge],
                              vertex_pos: dict, edge_vertices: list,
                              section_info: dict) -> float:
    """智能确定拉伸深度。

    策略：
    - 检测环的 Y 坐标范围 → 确定所在截面
    - 每个截面有不同的经验深度
    - 小圆/弧 → 可能代表轴，给较大深度
    - 大轮廓 → 可能代表壳体，给中等深度
    """
    # 计算环的 Y 范围
    y_vals = []
    for eid in face_edges:
        vs, ve = edge_vertices[eid]
        y_vals.append(vertex_pos[vs][1])
        y_vals.append(vertex_pos[ve][1])
    y_mid = (min(y_vals) + max(y_vals)) / 2

    # 计算环的包围盒面积
    x_vals = []
    for eid in face_edges:
        vs, ve = edge_vertices[eid]
        x_vals.append(vertex_pos[vs][0])
        x_vals.append(vertex_pos[ve][0])
        e = edges[eid]
        if e.etype == "ARC" and e.center:
            x_vals.append(e.center[0] - e.radius)
            x_vals.append(e.center[0] + e.radius)
    bb_area = (max(x_vals) - min(x_vals)) * (max(y_vals) - min(y_vals))

    # 所有边是否都是弧
    all_arc = all(edges[eid].etype == "ARC" for eid in face_edges)
    # 是否形成同心圆
    if all_arc:
        centers = set()
        for eid in face_edges:
            e = edges[eid]
            centers.add((round(e.center[0], 2), round(e.center[1], 2)))
        if len(centers) == 1:
            # 同心圆 → 齿轮/轴/轴承，深度较大
            return 20.0

    # 按 BB 面积确定深度
    if bb_area < 50:
        return 5.0   # 小特征
    elif bb_area < 500:
        return 10.0  # 中型特征
    elif bb_area < 5000:
        return 15.0  # 大型特征
    else:
        return 20.0  # 超大型/外轮廓


def classify_sections(edges: list[Edge], vertex_pos: dict,
                      edge_vertices: list) -> dict:
    """分析截面区域分布。

    返回 {section_name: (y_min, y_max, edge_count, ...)}
    """
    ys = []
    for eid, (vs, ve) in enumerate(edge_vertices):
        ys.append(vertex_pos[vs][1])
        ys.append(vertex_pos[ve][1])

    if not ys:
        return {"all": (0, 0)}

    y_min, y_max = min(ys), max(ys)
    total_span = y_max - y_min

    if total_span < 50:
        return {"all": (y_min, y_max)}

    # 寻找 Y 坐标间隙，用来自动分割截面
    from collections import Counter
    y_binned = Counter(round(y, 0) for y in ys)
    # 找 20mm 以上的间隙
    gaps = []
    prev_y = None
    for y in sorted(y_binned.keys()):
        if prev_y is not None and y - prev_y > 20:
            gaps.append((prev_y, y))
        prev_y = y

    sections = {"all": (y_min, y_max)}
    for i, (lo, hi) in enumerate(gaps):
        sections[f"section_{i+1}"] = (lo, hi)

    return sections


# ============================================================
# 6. 同心圆/弧聚类
# ============================================================

def cluster_concentric_arcs(valid_faces: list, edges: list[Edge],
                            edge_vertices: list, vertex_pos: dict,
                            tolerance: float = 0.5) -> dict:
    """将 ARC 边跨面按同心中心聚类。

    策略：
    1. 收集所有 ARC 边（不限面），计算其圆心
    2. 按圆心聚类（容差 tolerance）
    3. 每组输出：中心坐标、所有半径列表、涉及的面索引

    返回: {center_key: {"center": (cx,cy), "radii": [r1,r2,...],
           "face_indices": set(), "face_edges": [eid,...]}}
    """
    from collections import defaultdict

    # 第一步：按圆心聚类所有 ARC 边
    arc_by_center = defaultdict(list)  # center_key -> [(eid, radius, face_idx)]

    for fi, fi_data in enumerate(valid_faces):
        f_ids = fi_data["edges"]
        for eid in f_ids:
            e = edges[eid]
            if e.etype != "ARC":
                continue
            ckey = (round(e.center[0], 1), round(e.center[1], 1))
            arc_by_center[ckey].append({
                "eid": eid,
                "radius": e.radius,
                "face_idx": fi,
                "center": (e.center[0], e.center[1]),
            })

    # 第二步：合并相近的圆心
    # 将所有 center_key 按实际坐标聚类
    all_centers = sorted(arc_by_center.keys())
    merged = {}  # canonical_key -> [detail_keys...]
    used = set()

    for ck in all_centers:
        if ck in used:
            continue
        # 找所有 1mm 以内的圆心
        cluster = [ck]
        used.add(ck)
        for ck2 in all_centers:
            if ck2 in used:
                continue
            dist = math.hypot(ck[0] - ck2[0], ck[1] - ck2[1])
            if dist < 1.0:
                cluster.append(ck2)
                used.add(ck2)

        # 使用平均坐标作为规范键
        avg_x = sum(c[0] for c in cluster) / len(cluster)
        avg_y = sum(c[1] for c in cluster) / len(cluster)
        canon_key = (round(avg_x, 1), round(avg_y, 1))

        # 汇总
        all_radii = []
        all_face_indices = set()
        for c in cluster:
            for item in arc_by_center[c]:
                all_radii.append(item["radius"])
                all_face_indices.add(item["face_idx"])

        if len(all_face_indices) >= 1 and len(all_radii) >= 2:
            # 去重半径（容差 0.05mm）
            unique_radii = sorted(set(round(r * 20) / 20 for r in all_radii))
            merged[canon_key] = {
                "center": (avg_x, avg_y),
                "radii": unique_radii,
                "face_indices": all_face_indices,
                "count": len(all_radii),
            }

    return merged


def create_cylinders_from_group(center: tuple, radii: list,
                                height: float) -> list:
    """从一组同心半径创建阶梯圆柱体系列。

    从大到小处理：最大半径 → 实心圆柱，逐层减去内孔。
    返回: [solid_cylinders...] — 可直接合并的实体列表
    """
    if len(radii) < 1:
        return []

    cx, cy = center
    results = []

    # 排序：从大到小
    sorted_r = sorted(radii, reverse=True)

    try:
        # 最外层：实心圆柱
        outer_r = sorted_r[0]
        outer = BRepPrimAPI_MakeCylinder(
            gp_Ax2(gp_Pnt(cx, cy, 0), gp_Dir(0, 0, 1)),
            outer_r, height,
        ).Shape()

        if len(sorted_r) == 1:
            return [outer]

        # 逐层减内孔
        current = outer
        for inner_r in sorted_r[1:]:
            # 孔需要比外圆柱长以确保完全穿透
            hole = BRepPrimAPI_MakeCylinder(
                gp_Ax2(gp_Pnt(cx, cy, -1), gp_Dir(0, 0, 1)),
                inner_r, height + 2,
            ).Shape()
            current = BRepAlgoAPI_Cut(current, hole).Shape()

        results.append(current)

        # 为每个环带创建独立实体（用于展示）
        # 例如：R20-R12.5 齿轮环，R12.5-R10.5 辐板，R10.5-R3.5 轮毂
        for i in range(len(sorted_r) - 1):
            ring_outer_r = sorted_r[i]
            ring_inner_r = sorted_r[i + 1]
            if ring_outer_r - ring_inner_r < 0.1:
                continue
            ring_outer = BRepPrimAPI_MakeCylinder(
                gp_Ax2(gp_Pnt(cx, cy, 0), gp_Dir(0, 0, 1)),
                ring_outer_r, height,
            ).Shape()
            ring_inner = BRepPrimAPI_MakeCylinder(
                gp_Ax2(gp_Pnt(cx, cy, -0.5), gp_Dir(0, 0, 1)),
                ring_inner_r, height + 1,
            ).Shape()
            ring = BRepAlgoAPI_Cut(ring_outer, ring_inner).Shape()
            results.append(ring)

    except Exception:
        # 回退：只创建最外层圆柱
        try:
            fallback = BRepPrimAPI_MakeCylinder(
                gp_Ax2(gp_Pnt(cx, cy, 0), gp_Dir(0, 0, 1)),
                sorted_r[0], height,
            ).Shape()
            return [fallback]
        except Exception:
            return []

    return results


# ============================================================
# 7. 主流程
# ============================================================

def convert_dxf_to_3d(dxf_path: str, step_output: str = None,
                      extrusion_depth: float = None) -> object:
    """主转换函数 — 智能识别几何特征并创建 3D 实体。

    策略:
    1. 过滤页面边框（面积 > 总 bbox 面积 30% 的矩形）
    2. 按 Y 坐标分组截面，分别处理
    3. 同心圆弧 → 圆柱/圆筒
    4. 非圆弧封闭轮廓 → 拉伸
    5. 截面间实体按合理 Z 偏移放置
    6. 布尔合并为单一实体

    参数:
        dxf_path: 输入 DXF 路径
        step_output: 可选 STEP 输出路径
        extrusion_depth: 统一拉伸深度（None=自动检测）

    返回:
        OCC 组合实体 (TopoDS_Shape)，失败返回 None
    """
    _ensure_occ()

    print(f"[1/6] 解析 DXF 边: {dxf_path}")
    edges, metadata = parse_dxf_edges(dxf_path)
    print(f"  提取 {len(edges)} 条边")
    for etype, count in metadata["entity_counts"].items():
        print(f"    {etype}: {count}")

    if len(edges) < 3:
        print("[FAIL] 边数量不足，无法构成封闭轮廓")
        return None

    bbox_min = metadata["bbox_min"]
    bbox_max = metadata["bbox_max"]
    total_bbox_area = (bbox_max[0] - bbox_min[0]) * (bbox_max[1] - bbox_min[1])

    print(f"\n[2/6] 建图 ...")
    vertex_pos, edge_vertices, num_vertices = build_vertex_map(edges)
    print(f"  {num_vertices} 个顶点")
    adj = build_adjacency(vertex_pos, edge_vertices, edges, num_vertices)

    print(f"\n[3/6] 面遍历 ...")
    faces = find_all_faces(adj, edges, edge_vertices)
    print(f"  找到 {len(faces)} 个封闭环")

    if not faces:
        print("[FAIL] 未找到任何封闭环")
        return None

    # 分析每个面（正确处理 ARC 几何范围）
    face_info = []
    for f_ids in faces:
        xs, ys = [], []
        for eid in f_ids:
            e = edges[eid]
            vs, ve = edge_vertices[eid]
            xs.extend([vertex_pos[vs][0], vertex_pos[ve][0]])
            ys.extend([vertex_pos[vs][1], vertex_pos[ve][1]])
            # 对于 ARC，还要包含圆心及其在弧上的极值点
            if e.etype == "ARC" and e.center:
                cx, cy = e.center
                r = e.radius
                # 圆弧跨越的角度范围
                a1 = math.radians(e.start_angle)
                a2 = math.radians(e.end_angle)
                # 处理角度跨越（从 a1 到 a2 逆时针）
                if a2 < a1:
                    a2 += 2 * math.pi
                # 关键角度：0, π/2, π, 3π/2
                for key_angle in [0, math.pi/2, math.pi, 3*math.pi/2]:
                    # 检查 key_angle 是否在弧的范围内
                    a = key_angle
                    if a < a1:
                        a += 2 * math.pi
                    if a1 <= a <= a2:
                        xs.append(cx + r * math.cos(key_angle))
                        ys.append(cy + r * math.sin(key_angle))
                # 始终包含圆心（安全起见）
                xs.append(cx)
                ys.append(cy)
        bb_area = (max(xs) - min(xs)) * (max(ys) - min(ys))
        y_mid = (max(ys) + min(ys)) / 2
        x_min = min(xs)
        y_min = min(ys)
        x_max = max(xs)
        y_max = max(ys)
        face_info.append({
            "edges": f_ids,
            "area": bb_area,
            "y_mid": y_mid,
            "x_min": x_min, "y_min": y_min,
            "x_max": x_max, "y_max": y_max,
        })

    # ---- 过滤页面边框 ----
    # 条件：面积超过总 bbox 的 30% 且接近矩形（4条LINE边）
    page_border_indices = set()
    for i, fi in enumerate(face_info):
        if fi["area"] > total_bbox_area * 0.25:
            # 检查是否为外边框（4条边且面积接近 bbox）
            etypes = set(edges[eid].etype for eid in fi["edges"])
            if len(fi["edges"]) <= 6 and "LINE" in etypes:
                page_border_indices.add(i)
                print(f"  [跳过] 环{i+1}: 页面边框 (面积={fi['area']:.0f}mm^2)")

    # 过滤小面
    if face_info:
        areas = [fi["area"] for fi in face_info]
        median_area = sorted(areas)[len(areas) // 2]
        min_area = max(0.5, median_area * 0.0005)
    else:
        min_area = 0.5

    # 应用过滤
    valid_faces = [fi for i, fi in enumerate(face_info)
                   if i not in page_border_indices and fi["area"] >= min_area]

    print(f"\n[4/6] 截面分析与特征识别 ({len(valid_faces)} 个有效环)")

    # ---- 同心圆检测 ----
    concentric_groups = cluster_concentric_arcs(
        valid_faces, edges, edge_vertices, vertex_pos)
    processed_face_indices = set()
    for ck, group in concentric_groups.items():
        processed_face_indices.update(group["face_indices"])

    print(f"  检测到 {len(concentric_groups)} 组同心圆弧")
    for ck, group in concentric_groups.items():
        print(f"    中心({ck[0]:.1f},{ck[1]:.1f}): {len(group['radii'])}个半径 "
              f"{group['radii']}, {group['count']}条ARC边, "
              f"{len(group['face_indices'])}个面")

    # ---- 按 Y 坐标分组截面 ----
    # 统计 Y 分布找截面边界
    from collections import Counter
    all_ys = []
    for fi in valid_faces:
        all_ys.append(fi["y_mid"])
    if all_ys:
        y_counter = Counter(round(y, 0) for y in all_ys)
        sorted_ys = sorted(y_counter.keys())
        # 找 >30mm 的间隙
        section_gaps = []
        prev = sorted_ys[0] if sorted_ys else 0
        for y in sorted_ys[1:]:
            if y - prev > 30:
                section_gaps.append((prev, y))
            prev = y

    # 自动确定截面区间
    if section_gaps and len(section_gaps) >= 1:
        # 使用第一个大间隙（通常是标题栏和图纸主体之间）
        # 以及后续间隙来分割
        pass

    y_min_all = min(fi["y_min"] for fi in valid_faces)
    y_max_all = max(fi["y_max"] for fi in valid_faces)

    # 手动定义截面（基于之前的分析）
    section_ranges = [
        ("标题栏/说明区", 5, 90, 0.0),
        ("主视图区", 90, 145, 5.0),
        ("D-D剖面(箱体)", 145, 175, 15.0),
        ("E-E剖面(齿轮)", 175, 235, 25.0),
        ("F-F剖面(轴系)", 235, 292, 10.0),
    ]

    # 按截面对面分组
    section_faces = {name: [] for name, _, _, _ in section_ranges}
    for fi in valid_faces:
        y = fi["y_mid"]
        assigned = False
        for name, ylo, yhi, depth in section_ranges:
            if ylo <= y <= yhi:
                section_faces[name].append((fi, depth))
                assigned = True
                break
        if not assigned:
            # 分配到最近的截面
            best_name = min(section_ranges,
                          key=lambda s: min(abs(y - s[1]), abs(y - s[2])))[0]
            section_faces[best_name].append((fi, 10.0))

    # 打印各截面信息
    for name, ylo, yhi, depth in section_ranges:
        count = len(section_faces[name])
        area_sum = sum(fi["area"] for fi, _ in section_faces[name])
        print(f"  {name} (Y{ylo}~{yhi}): {count}个环, 总面积{area_sum:.0f}mm^2, 拉伸深度{depth:.0f}mm")

    # ---- 创建 3D 实体 ----
    print(f"\n[5/6] 创建 3D 实体 ...")
    all_solids = []

    # 先处理同心圆组（创建圆柱体）
    for ckey, group in concentric_groups.items():
        cx, cy = group["center"]
        radii = group["radii"]

        # 找这个组所在的截面深度
        y_mid = cy
        for name, ylo, yhi, section_depth in section_ranges:
            if ylo <= y_mid <= yhi:
                height = section_depth
                break
        else:
            height = 20.0
        height = max(height, max(radii) * 2)

        cyl_list = create_cylinders_from_group((cx, cy), radii, height)
        if cyl_list:
            all_solids.extend(cyl_list)
            print(f"  同心圆组 中心({cx:.1f},{cy:.1f}): "
                  f"{len(radii)}个半径={radii}, H={height:.0f}mm -> {len(cyl_list)}个圆柱体")

    # 处理剩余的非圆弧轮廓（拉伸）
    for section_name, ylo, yhi, section_depth in section_ranges:
        section_solids = []
        for fi, depth in section_faces[section_name]:
            # 跳过已处理的同心圆面
            fi_idx = valid_faces.index(fi) if fi in valid_faces else -1
            if fi_idx in processed_face_indices:
                continue

            # 全部是 ARC 且 >= 2 边 → 可能是未聚类的圆弧组，尝试作为圆柱
            f_ids = fi["edges"]
            all_arc = all(edges[eid].etype == "ARC" for eid in f_ids)
            if all_arc and len(f_ids) >= 2:
                centers = []
                radii = []
                for eid in f_ids:
                    e = edges[eid]
                    centers.append((e.center[0], e.center[1]))
                    radii.append(e.radius)
                cx_avg = sum(c[0] for c in centers) / len(centers)
                cy_avg = sum(c[1] for c in centers) / len(centers)
                max_dev = max(math.hypot(c[0] - cx_avg, c[1] - cy_avg) for c in centers)
                if max_dev < 0.5:
                    max_r = max(radii)
                    min_r = min(radii)
                    height = max(section_depth, max_r * 2)
                    cyl = create_cylinder_from_arcs((cx_avg, cy_avg), max_r, min_r, height)
                    if cyl is not None:
                        section_solids.append(cyl)
                        continue

            # 普通拉伸
            use_depth = depth if extrusion_depth is None else extrusion_depth
            occ_face = build_occ_face(f_ids, edges, vertex_pos, edge_vertices)
            if occ_face is not None:
                solid = extrude_face(occ_face, use_depth)
                if solid is not None:
                    section_solids.append(solid)

        if section_solids:
            # 合并截面内实体
            section_combined = section_solids[0]
            for s in section_solids[1:]:
                try:
                    section_combined = BRepAlgoAPI_Fuse(section_combined, s).Shape()
                except Exception:
                    pass
            all_solids.append(section_combined)
            print(f"  {section_name}: {len(section_solids)} 个实体已合并")

    print(f"  总共 {len(all_solids)} 个截面实体")

    if not all_solids:
        print("[FAIL] 无法创建任何 3D 实体")
        return None

    # ---- 布尔合并 ----
    print(f"\n[6/6] 最终合并 + STEP 导出 ...")
    combined = all_solids[0]
    for i, s in enumerate(all_solids[1:], 1):
        try:
            combined = BRepAlgoAPI_Fuse(combined, s).Shape()
        except Exception:
            print(f"  警告: 截面实体{i}合并失败")

    # 修复最终形状
    from OCC.Core.ShapeFix import ShapeFix_Shape
    fixer = ShapeFix_Shape()
    fixer.Init(combined)
    fixer.Perform()
    combined = fixer.Shape()

    # STEP 导出
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
# 7. SolidWorks 导入
# ============================================================

def import_to_solidworks(step_path: str, output_sldprt: str = None) -> bool:
    """将 STEP 文件导入 SolidWorks 并保存为 .sldprt。"""
    from src.core.sw_automation.sw_driver import SolidWorksDriver

    driver = SolidWorksDriver(visible=True)
    if not driver.connect():
        print("[FAIL] 无法连接 SolidWorks")
        return False

    try:
        # 使用 SW COM 导入 STEP
        sw_app = driver.sw_app
        abs_step = str(Path(step_path).absolute())

        # LoadFile2(FileName, ImportType) — ImportType="" 让 SW 自动检测
        result = sw_app.LoadFile2(abs_step, "")
        if not result:
            print(f"[FAIL] SW LoadFile2 导入失败")
            return False

        print(f"[OK] STEP 已导入 SW")

        # 更新驱动的活动模型引用
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
        # 尝试用 LibreDWG
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

    # 确定输出路径
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
    print("通用 DXF → 3D SolidWorks 转换器")
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
        print(f"\n[WARN] SW 导入失败，但 STEP 文件可用: {step_path}")


if __name__ == "__main__":
    main()
