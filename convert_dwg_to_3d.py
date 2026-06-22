#!/usr/bin/env python
"""DWG/DXF 阶梯轴 → 3D STEP 模型转换器

将 2D 工程图中的阶梯轴转换为 3D 实体模型，导出为 STEP 格式。
STEP 可直接被 SolidWorks、CATIA、Fusion 360 等主流 CAD 软件导入。

用法:
    python convert_dwg_to_3d.py <输入.dxf> [输出.step]
"""

import math
import sys
import os
from pathlib import Path

import ezdxf

# OCC 导入延迟到 _ensure_occ() 中，避免仅需 DXF 解析时依赖 PythonOCC
_OCC_LOADED = False


def _ensure_occ():
    """延迟加载 PythonOCC 模块（仅在需要 3D 建模时）。"""
    global _OCC_LOADED
    if _OCC_LOADED:
        return
    from OCC.Core.BRepPrimAPI import BRepPrimAPI_MakeRevol, BRepPrimAPI_MakeBox
    from OCC.Core.BRepAlgoAPI import BRepAlgoAPI_Cut
    from OCC.Core.BRepBuilderAPI import (
        BRepBuilderAPI_MakeEdge, BRepBuilderAPI_MakeWire,
        BRepBuilderAPI_MakeFace, BRepBuilderAPI_Transform,
    )
    from OCC.Core.gp import gp_Pnt, gp_Dir, gp_Ax1, gp_Trsf
    from OCC.Core.BRepCheck import BRepCheck_Analyzer
    from OCC.Core.STEPControl import STEPControl_Writer, STEPControl_AsIs
    from OCC.Core.IFSelect import IFSelect_RetDone

    globals().update({
        "BRepPrimAPI_MakeRevol": BRepPrimAPI_MakeRevol,
        "BRepPrimAPI_MakeBox": BRepPrimAPI_MakeBox,
        "BRepAlgoAPI_Cut": BRepAlgoAPI_Cut,
        "BRepBuilderAPI_MakeEdge": BRepBuilderAPI_MakeEdge,
        "BRepBuilderAPI_MakeWire": BRepBuilderAPI_MakeWire,
        "BRepBuilderAPI_MakeFace": BRepBuilderAPI_MakeFace,
        "BRepBuilderAPI_Transform": BRepBuilderAPI_Transform,
        "gp_Pnt": gp_Pnt,
        "gp_Dir": gp_Dir,
        "gp_Ax1": gp_Ax1,
        "gp_Trsf": gp_Trsf,
        "BRepCheck_Analyzer": BRepCheck_Analyzer,
        "STEPControl_Writer": STEPControl_Writer,
        "STEPControl_AsIs": STEPControl_AsIs,
        "IFSelect_RetDone": IFSelect_RetDone,
    })
    _OCC_LOADED = True


# ---- 1. DXF 解析 ----

def parse_shaft_from_dxf(dxf_path: str) -> dict:
    """从 DXF 中提取阶梯轴的几何参数

    策略：不依赖图层名称（编码问题），改用几何特征识别：
    - 中心线：最长的水平线
    - 轮廓线：图层中线数量最多的 = 粗实线层
    - 键槽线：轮廓层中不在主轮廓上的短水平线
    """
    doc = ezdxf.readfile(dxf_path)
    msp = doc.modelspace()

    # ---- 第 1 步：按图层分组所有图元 ----
    layer_entities = {}  # layer_name -> [(type, data), ...]
    for e in msp:
        layer = e.dxf.layer
        if layer not in layer_entities:
            layer_entities[layer] = []
        if e.dxftype() == "LINE":
            layer_entities[layer].append(("LINE", {
                "x1": e.dxf.start.x, "y1": e.dxf.start.y,
                "x2": e.dxf.end.x, "y2": e.dxf.end.y,
            }))
        elif e.dxftype() == "ARC":
            layer_entities[layer].append(("ARC", {
                "cx": e.dxf.center.x, "cy": e.dxf.center.y,
                "r": e.dxf.radius,
                "a1": e.dxf.start_angle, "a2": e.dxf.end_angle,
            }))

    # ---- 第 2 步：找中心线 ----
    # 中心线特征：所有 LINE 中最长的那条水平线
    centerline_y = None
    max_h_len = 0
    all_lines_flat = []
    for layer, ents in layer_entities.items():
        for etype, data in ents:
            if etype == "LINE":
                all_lines_flat.append((layer, data))
                dy = abs(data["y1"] - data["y2"])
                dx = abs(data["x1"] - data["x2"])
                if dy < 0.01 and dx > max_h_len:
                    max_h_len = dx
                    centerline_y = data["y1"]

    # 找粗实线层（包含 LINE 最多的图层，排除中心线图层）
    layer_line_counts = {}
    for layer, ents in layer_entities.items():
        layer_line_counts[layer] = sum(1 for t, _ in ents if t == "LINE")

    centerline_layer = None
    for layer, data in all_lines_flat:
        dy = abs(data["y1"] - data["y2"])
        if dy < 0.01 and abs(data["y1"] - centerline_y) < 0.01:
            centerline_layer = layer
            break

    # 粗实线层 = LINE 最多的非中心线图层
    sorted_layers = sorted(layer_line_counts.items(), key=lambda x: -x[1])
    contour_layer = None
    for layer, count in sorted_layers:
        if layer != centerline_layer:
            contour_layer = layer
            break

    print(f"识别到中心线图层: {contour_layer != centerline_layer}")
    print(f"粗实线图层: LINE {layer_line_counts.get(contour_layer, 0)} 条")
    print(f"中心线 Y = {centerline_y:.2f}")

    # ---- 第 3 步：提取轮廓线（只保留主视图区域的线，排除下方截面视图） ----
    contour_lines = []
    contour_arcs = []
    if contour_layer and contour_layer in layer_entities:
        for etype, data in layer_entities[contour_layer]:
            if etype == "LINE":
                # 排除截面视图区域的线（y < -50，即主视图下方很远的区域）
                y_avg = (data["y1"] + data["y2"]) / 2
                if y_avg > -50:
                    contour_lines.append(data)
            elif etype == "ARC":
                y_avg = data["cy"]
                if y_avg > -50:
                    contour_arcs.append(data)

    print(f"轮廓线: {len(contour_lines)} 条 LINE, {len(contour_arcs)} 条 ARC")

    # ---- 第 4 步：按水平线高度分组，识别阶梯轴的各段 ----
    # 策略：顶部水平线定义了每个截面段的 X 范围和 Y 高度
    # 阶梯轴在每次高度变化处过渡

    # 收集所有水平线 (|dy| < 0.1, dx > 1)
    h_lines_data = []
    for l in contour_lines:
        dx = abs(l["x1"] - l["x2"])
        dy = abs(l["y1"] - l["y2"])
        if dy < 0.1 and dx > 1:
            x1 = min(l["x1"], l["x2"])
            x2 = max(l["x1"], l["x2"])
            y = l["y1"]
            h_lines_data.append((x1, x2, y))

    # 分离顶部水平线 (y > centerline_y) 和底部水平线 (y < centerline_y)
    top_h = [(x1, x2, y) for x1, x2, y in h_lines_data if y > centerline_y]
    bot_h = [(x1, x2, y) for x1, x2, y in h_lines_data if y < centerline_y]

    # 按 x 左端点排序
    top_h.sort(key=lambda h: h[0])
    bot_h.sort(key=lambda h: h[0])

    print(f"顶部水平线: {len(top_h)} 条, 底部水平线: {len(bot_h)} 条")

    # ---- 第 5 步：用顶部水平线定义阶梯轴的各段 ----
    # 每个截面段由一条顶部水平线（和对应的底部水平线）定义
    sections_raw = []
    for tx1, tx2, ty in top_h:
        # 找匹配的底部水平线（X 范围最接近的）
        best_bot = None
        best_dist = float("inf")
        for bx1, bx2, by in bot_h:
            # 匹配标准：X 范围重叠度
            overlap_left = max(tx1, bx1)
            overlap_right = min(tx2, bx2)
            if overlap_right > overlap_left:
                dist = abs(tx1 - bx1) + abs(tx2 - bx2)
                if dist < best_dist:
                    best_dist = dist
                    best_bot = (bx1, bx2, by)

        if best_bot:
            bx1, bx2, by = best_bot
            # 截面 X 范围：取并集
            x_left = min(tx1, bx1)
            x_right = max(tx2, bx2)
            # Y 范围：各用各的
            sections_raw.append((x_left, x_right, by, ty))

    # ---- 第 6 步：合并相邻同高度的截面，拆开不同高度相邻截面 ----
    sections_raw.sort(key=lambda s: s[0])

    # 对于每个截面，检查是否与其他截面重叠（同高度合并，不同高度相邻保留）
    processed = []
    skip = set()
    for i in range(len(sections_raw)):
        if i in skip:
            continue
        xl, xr, by, ty = sections_raw[i]

        for j in range(i + 1, len(sections_raw)):
            if j in skip:
                continue
            xl2, xr2, by2, ty2 = sections_raw[j]

            # 同高度且 X 范围相邻或重叠 → 合并
            if abs(ty - ty2) < 1.0 and abs(by - by2) < 1.0:
                if xl2 <= xr or abs(xl2 - xr) < 5:
                    xr = max(xr, xr2)
                    xl = min(xl, xl2)
                    skip.add(j)

        processed.append((xl, xr, by, ty))

    sections_raw = processed
    sections_raw.sort(key=lambda s: s[0])

    # ---- 第 7 步：构建截面参数（过滤键槽伪截面） ----
    section_params = []
    for x_left, x_right, bot_y, top_y in sections_raw:
        radius = (top_y - centerline_y + centerline_y - bot_y) / 2
        # 验证对称性
        r_top = top_y - centerline_y
        r_bot = centerline_y - bot_y
        if abs(r_top - r_bot) > 3.0:
            continue
        section_params.append({
            "x_start": round(x_left, 3),
            "x_end": round(x_right, 3),
            "radius": round(radius, 3),
            "top_y": round(top_y, 3),
            "bottom_y": round(bot_y, 3),
        })

    # 过滤：移除完全被其他（更大半径）截面包含的截面（这些是键槽轮廓）
    filtered = []
    for i, si in enumerate(section_params):
        is_contained = False
        for j, sj in enumerate(section_params):
            if i == j:
                continue
            # 如果 sj 的 X 范围包含 si，且 sj 的半径更大 → si 是内部特征
            if (sj["x_start"] <= si["x_start"] and
                sj["x_end"] >= si["x_end"] and
                sj["radius"] > si["radius"] + 2):
                is_contained = True
                break
        if not is_contained:
            filtered.append(si)

    section_params = filtered
    section_params.sort(key=lambda s: s["x_start"])
    print(f"构建了 {len(section_params)} 个截面（过滤后）")

    # ---- 第 8 步：检测倒角 ----
    chamfers = []
    for l in contour_lines:
        dx = abs(l["x1"] - l["x2"])
        dy = abs(l["y1"] - l["y2"])
        if 0.5 < dx < 5 and 0.5 < dy < 5 and abs(dx - dy) < 0.5:
            mid_x = (l["x1"] + l["x2"]) / 2
            chamfers.append({
                "x": round(mid_x, 3),
                "size": round(dx, 3),
                "is_left": mid_x < -100,
            })

    # 倒角去重（同一端部有上下两条斜线）
    chamfers_dedup = []
    for ch in chamfers:
        found = False
        for existing in chamfers_dedup:
            if abs(ch["x"] - existing["x"]) < 3 and abs(ch["size"] - existing["size"]) < 0.5:
                found = True
                break
        if not found:
            chamfers_dedup.append(ch)
    chamfers = chamfers_dedup
    print(f"倒角线: {len(chamfers)} 条（去重后）")

    # ---- 第 9 步：检测键槽 ----
    # 键槽特征：不在主轮廓上的水平线对（位于截面轮廓内部）
    # 键槽可见于前视图中的上边（y>centerline）和下边（可能在任何位置）
    keyways = []

    # 收集所有非轮廓水平线（顶部+底部）
    all_non_contour = []
    for x1, x2, y in h_lines_data:
        is_contour = False
        for s in section_params:
            if abs(y - s["top_y"]) < 1.0 or abs(y - s["bottom_y"]) < 1.0:
                if abs(x1 - s["x_start"]) < 3 and abs(x2 - s["x_end"]) < 3:
                    is_contour = True
                    break
        if not is_contour:
            all_non_contour.append((x1, x2, y))

    # 配对：找 X 范围接近、Y 差 > 2mm 的水平线对
    for i in range(len(all_non_contour)):
        for j in range(i + 1, len(all_non_contour)):
            x1a, x2a, ya = all_non_contour[i]
            x1b, x2b, yb = all_non_contour[j]
            if (abs(x1a - x1b) < 3 and abs(x2a - x2b) < 3 and abs(ya - yb) > 2):
                kw_x1 = (x1a + x1b) / 2
                kw_x2 = (x2a + x2b) / 2
                kw_width = abs(ya - yb)
                kw_mid_y = (ya + yb) / 2
                kw_center_x = (kw_x1 + kw_x2) / 2
                for si, s in enumerate(section_params):
                    if s["x_start"] - 2 <= kw_center_x <= s["x_end"] + 2:
                        # 键槽深度：标准键槽深度 ≈ 宽度 × 0.5
                        kw_depth = round(kw_width * 0.5, 1)
                        keyways.append({
                            "x_start": round(min(kw_x1, kw_x2), 3),
                            "x_end": round(max(kw_x1, kw_x2), 3),
                            "width": round(kw_width, 3),
                            "depth": round(kw_depth, 3),
                            "section_index": si,
                            "shaft_radius": s["radius"],
                        })
                        break

    # ---- 第 10 步：检测圆角 ----
    fillet_radius = 1.2  # 默认
    for a in contour_arcs:
        if 0.5 < a["r"] < 3.0:
            fillet_radius = a["r"]
            break

    result = {
        "centerline_y": centerline_y,
        "sections": section_params,
        "fillet_radius": fillet_radius,
        "keyways": keyways,
        "chamfers": chamfers,
    }

    # 打印结果
    print(f"\n=== 解析结果 ===")
    print(f"截面数: {len(section_params)}")
    for i, s in enumerate(section_params):
        print(f"  段{i+1}: x=[{s['x_start']:.1f}, {s['x_end']:.1f}], "
              f"r={s['radius']:.1f}mm, 长度={s['x_end']-s['x_start']:.1f}mm")
    print(f"键槽数: {len(keyways)}")
    for i, k in enumerate(keyways):
        print(f"  键槽{i+1}: x=[{k['x_start']:.1f}, {k['x_end']:.1f}], "
              f"宽={k['width']:.1f}mm, 深={k['depth']:.1f}mm")
    print(f"圆角半径: R{fillet_radius}")
    print(f"倒角线: {len(chamfers)} 条")

    return result


# ---- 2. 3D 建模 ----

def build_step_shaft(geometry: dict):
    """构建阶梯轴的 3D 实体 — 使用旋转体方法

    将半剖面轮廓线绕中心轴（X轴）旋转 360°，生成一整根光滑轴。
    """
    _ensure_occ()
    sections = geometry["sections"]
    fillet_r = geometry["fillet_radius"]
    chamfers = geometry["chamfers"]

    if not sections:
        raise ValueError("未检测到截面数据")

    print(f"\n=== 构建 3D 模型（旋转体方法）===")

    # ---- 第 1 步：构建 2D 半剖面轮廓 ----
    # 从 section 数据构建连续的上半剖面轮廓
    # 每个 section 贡献两个点：(x_start, r) 和 (x_end, r)
    # 相邻 section 之间通过垂直边连接

    # 收集所有截面按 X 排序的 (x, r) 点对
    top_pts = []
    for s in sections:
        top_pts.append((s["x_start"], s["radius"], "start"))
        top_pts.append((s["x_end"], s["radius"], "end"))
    top_pts.sort(key=lambda p: p[0])

    # 合并同 X 位置的点（取最大半径）
    merged = []
    i = 0
    while i < len(top_pts):
        x = top_pts[i][0]
        max_r = top_pts[i][1]
        j = i + 1
        while j < len(top_pts) and abs(top_pts[j][0] - x) < 0.5:
            max_r = max(max_r, top_pts[j][1])
            j += 1
        merged.append((x, max_r))
        i = j

    # 构建连续轮廓（处理半径变化的阶跃）
    profile = []
    for i, (x, r) in enumerate(merged):
        if i == 0:
            profile.append((x, r))
        else:
            prev_x, prev_r = profile[-1]
            if abs(r - prev_r) > 0.5:
                # 半径变化：先水平到当前 X，再垂直变化
                # 需要确定阶跃面在哪一侧
                if x > prev_x:
                    # 通常阶跃面在前一段的结束位置
                    profile.append((prev_x, r))  # 垂直边
                else:
                    profile.append((x, prev_r))  # 先水平
                profile.append((x, r))
            else:
                # 同高度，延伸水平线
                if x > prev_x:
                    profile.append((x, r))

    # 处理倒角
    left_chamfer = None
    right_chamfer = None
    for ch in chamfers:
        if ch["is_left"]:
            left_chamfer = ch
        else:
            right_chamfer = ch

    # 左端倒角：在第一个点之前插入
    if left_chamfer and profile:
        first_x, first_r = profile[0]
        ch_x = first_x - left_chamfer["size"]
        ch_r = first_r - left_chamfer["size"]
        if ch_r > 0.5:
            profile.insert(0, (ch_x, ch_r))
            profile.insert(0, (first_x, first_r))  # 保持原来的点
            # 修正：倒角在端面
            profile[0] = (ch_x, ch_r)
            # 第一个原来的点保留

    # 右端倒角：在最后一个点之后追加
    if right_chamfer and profile:
        last_x, last_r = profile[-1]
        ch_x = last_x + right_chamfer["size"]
        ch_r = last_r - right_chamfer["size"]
        if ch_r > 0.5:
            profile.append((ch_x, ch_r))

    # 确保 profile 按 X 递增
    profile.sort(key=lambda p: p[0])

    # 去重
    seen = set()
    unique_profile = []
    for pt in profile:
        key = (round(pt[0], 2), round(pt[1], 2))
        if key not in seen:
            seen.add(key)
            unique_profile.append(pt)
    profile = unique_profile

    print(f"  轮廓点数: {len(profile)}")
    for i, (x, y) in enumerate(profile):
        print(f"    P{i}: x={x:.1f}, r={y:.1f}")

    # ---- 第 2 步：构建闭合线框 → 创建面 → 旋转 360° ----
    if len(profile) < 2:
        raise ValueError("轮廓点数不足")

    leftmost_x = profile[0][0]
    rightmost_x = profile[-1][0]

    # 线框顶点序列（XY 平面，Y 为半径方向）
    # 从左端面底部开始，逆时针走一圈
    wire_pts = []

    # 1. 左端面底部（轴线上）
    wire_pts.append((leftmost_x, 0.0))
    # 2. 左端面顶部
    wire_pts.append((leftmost_x, profile[0][1]))
    # 3. 沿上表面从左到右（所有轮廓点）
    wire_pts.extend(profile)
    # 4. 右端面底部（轴线上）
    wire_pts.append((rightmost_x, 0.0))

    # 构建边
    edges = []
    for i in range(len(wire_pts) - 1):
        x1, y1 = wire_pts[i]
        x2, y2 = wire_pts[i + 1]
        # 跳过重合点
        if abs(x2 - x1) < 0.001 and abs(y2 - y1) < 0.001:
            continue
        e = BRepBuilderAPI_MakeEdge(
            gp_Pnt(x1, y1, 0), gp_Pnt(x2, y2, 0)
        ).Edge()
        edges.append(e)

    # 添加底部闭合边（沿轴线从右回到左）
    e = BRepBuilderAPI_MakeEdge(
        gp_Pnt(rightmost_x, 0, 0),
        gp_Pnt(leftmost_x, 0, 0),
    ).Edge()
    edges.append(e)

    # 组装线框
    wire_builder = BRepBuilderAPI_MakeWire()
    for e in edges:
        wire_builder.Add(e)
    wire = wire_builder.Wire()

    # 创建面并旋转
    face = BRepBuilderAPI_MakeFace(wire).Face()

    revolve_axis = gp_Ax1(gp_Pnt(0, 0, 0), gp_Dir(1, 0, 0))
    revolved = BRepPrimAPI_MakeRevol(face, revolve_axis, 2 * math.pi)

    if not revolved.IsDone():
        raise RuntimeError("旋转体构建失败")

    result = revolved.Shape()
    print(f"  旋转体构建成功 — 一整根光滑阶梯轴")

    # ---- 第 3 步：切割键槽 ----
    for i, kw in enumerate(geometry["keyways"]):
        print(f"  切割键槽{i+1}: x=[{kw['x_start']:.1f}, {kw['x_end']:.1f}], "
              f"宽={kw['width']:.1f}mm, 深={kw['depth']:.1f}mm")
        result = cut_keyway(result, kw)

    return result


def cut_keyway(shape, keyway_params):
    """在轴上切割键槽

    键槽是一个矩形槽，沿轴的顶部纵向切割。
    使用长方体布尔减操作实现。
    """
    _ensure_occ()
    x_start = keyway_params["x_start"]
    x_end = keyway_params["x_end"]
    kw_width = keyway_params["width"]
    kw_depth = keyway_params.get("depth", kw_width / 2)
    shaft_r = keyway_params["shaft_radius"]

    kw_len = x_end - x_start
    kw_center_x = (x_start + x_end) / 2

    # 键槽长方体：从轴表面到键槽底部
    # 轴表面在 Y 方向 = shaft_r，键槽底部 = shaft_r - kw_depth
    kw_bottom = shaft_r - kw_depth

    # 创建一个比键槽稍大的长方体，确保完整切割
    kw_box = BRepPrimAPI_MakeBox(
        gp_Pnt(-kw_len / 2, kw_bottom, -kw_width / 2),
        gp_Pnt(kw_len / 2, shaft_r + 2, kw_width / 2),
    ).Shape()

    # 平移到键槽位置
    trsf = gp_Trsf()
    trsf.SetTranslation(gp_Pnt(0, 0, 0), gp_Pnt(kw_center_x, 0, 0))
    brep_trsf = BRepBuilderAPI_Transform(kw_box, trsf)
    kw_positioned = brep_trsf.Shape()

    # 布尔减
    cut_op = BRepAlgoAPI_Cut(shape, kw_positioned)
    cut_op.Build()
    if cut_op.IsDone():
        return cut_op.Shape()
    else:
        print(f"    键槽切割失败")
        return shape


# ---- 3. STEP 导出 ----

def export_step(shape, output_path: str) -> bool:
    """将 TopoDS_Shape 导出为 STEP 文件"""
    _ensure_occ()
    print(f"\n=== 导出 STEP ===")

    # 检查模型有效性
    analyzer = BRepCheck_Analyzer(shape)
    if not analyzer.IsValid():
        print("  警告: 模型存在几何问题")

    writer = STEPControl_Writer()
    status = writer.Transfer(shape, STEPControl_AsIs)

    if status != IFSelect_RetDone:
        print(f"  STEP 转换失败: {status}")
        return False

    result = writer.Write(str(output_path))
    if result != IFSelect_RetDone:
        print(f"  STEP 写入失败")
        return False

    file_size = os.path.getsize(output_path)
    print(f"  导出成功: {output_path}")
    print(f"  文件大小: {file_size / 1024:.1f} KB")
    return True


# ---- 主流程 ----

def main():
    if len(sys.argv) < 2:
        dxf_path = "CAD/20160112-181116-09933.dxf"
    else:
        dxf_path = sys.argv[1]

    if len(sys.argv) < 3:
        # 默认输出路径
        base = os.path.splitext(os.path.basename(dxf_path))[0]
        output_path = f"CAD/{base}_3d.step"
    else:
        output_path = sys.argv[2]

    # 确保路径正确
    if not os.path.isabs(dxf_path):
        dxf_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), dxf_path
        )
    if not os.path.isabs(output_path):
        output_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), output_path
        )

    print(f"=" * 60)
    print(f"DWG/DXF → 3D STEP 转换器")
    print(f"=" * 60)
    print(f"输入: {dxf_path}")
    print(f"输出: {output_path}")

    if not os.path.exists(dxf_path):
        print(f"\n错误: 文件不存在 - {dxf_path}")
        sys.exit(1)

    # Step 1: 解析 DXF
    print(f"\n[1/3] 解析 DXF 几何...")
    geometry = parse_shaft_from_dxf(dxf_path)

    # Step 2: 构建 3D 模型
    print(f"\n[2/3] 构建 3D 模型...")
    try:
        shape = build_step_shaft(geometry)
    except Exception as e:
        print(f"\n错误: 3D 建模失败 - {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

    # Step 3: 导出 STEP
    print(f"\n[3/3] 导出 STEP 文件...")
    success = export_step(shape, output_path)

    if success:
        print(f"\n{'=' * 60}")
        print(f"转换完成！")
        print(f"输出文件: {output_path}")
        print(f"可直接导入 SolidWorks: 文件 → 打开 → 选择 .step 文件")
        print(f"{'=' * 60}")
    else:
        print(f"\n转换失败！")
        sys.exit(1)


if __name__ == "__main__":
    main()
