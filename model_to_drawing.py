#!/usr/bin/env python
"""STEP → 三视图 DXF（闭环验证：真实模型 → 图纸 → 重建对比）。

使用 PythonOCC HLR 隐藏线消除投影生成三视图，布局采用第三角投影
（top 上 / front 左下 / side 右下），与 dxf_to_3d_general.py 的
`_separate_views_2d` 视图识别逻辑匹配（Y 最高→top、X 最右→side、
X 与 top 对齐→front）。

只输出视图几何（无图框/标题栏/标注）。实体 linetype 显式设置
（CONTINUOUS / HIDDEN），模拟真实图纸的线型组织。

用法:
    python model_to_drawing.py input.step [output.dxf]
"""

import math
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent
CAD_TEMP = PROJECT_ROOT / "CAD" / "temp_output"
for p in [str(PROJECT_ROOT), str(CAD_TEMP)]:
    if p not in sys.path:
        sys.path.insert(0, p)

import ezdxf  # noqa: E402

# 复用 HLR 投影实现（该模块顶层无副作用）
from generate_engineering_drawing import (  # noqa: E402
    project_shape_to_2d,
    _bbox_all,
)

from OCC.Core.STEPControl import STEPControl_Reader  # noqa: E402

# 视图间隙（必须 > 分离算法的 X/Y 间隙阈值: max(30, Y簇宽×20%)）。
# 固定 50 在宽图上不够: bracket 图 front+side 簇宽 308 → 阈值 61.6 > 50
# → side 被并入 front（实测重建 X=51 vs 期望 184）。按 front 宽度 35%
# 动态取: 间隙 G 需 > (W_front+W_side+G)×0.20 → G > 0.25×(W_front+W_side)，
# 取 0.35×W_front 留余量，最小 50。
VIEW_GAP_MIN = 50.0


def load_step(step_path: Path):
    """读取 STEP 文件，返回 TopoDS_Shape。"""
    reader = STEPControl_Reader()
    if reader.ReadFile(str(step_path)) != 1:
        raise RuntimeError(f"STEP 读取失败: {step_path}")
    reader.TransferRoots()
    return reader.OneShape()


def project_all_views(shape):
    """三视图 HLR 投影。

    方向约定（与 CSG 重建 _get_view_transform 标准正交映射一致）:
      front: 沿 -Y 看, up=Z  →  DXF_X=3D_X, DXF_Y=3D_Z
      top:   沿 -Z 看, up=Y  →  DXF_X=-3D_X(镜像), DXF_Y=3D_Y
      right: 沿 +X 看, up=Z  →  DXF_X=3D_Y, DXF_Y=3D_Z
    """
    return {
        "front": project_shape_to_2d(shape, (0, -1, 0), (0, 0, 1)),
        "top":   project_shape_to_2d(shape, (0, 0, -1), (0, 1, 0)),
        "side":  project_shape_to_2d(shape, (1, 0, 0), (0, 0, 1)),
    }


def _draw_view_elements(msp, view_dict, ox, oy):
    """绘制一个视图的所有元素（linetype 显式设置）。

    circles/hidden_circles 元素为 (cx, cy, r, is_full, angles) 五元组：
    整圆画 CIRCLE，部分弧按角度段画 ARC（v0.6.3 修复：弧画整圆会
    放大假轮廓，见 generate_engineering_drawing.py 同函数）。

    线型约定（与 generate_engineering_drawing.py 完全一致）：实体只设
    layer、不设 linetype 属性（BYLAYER）。显式 "HIDDEN" 会让
    dxf_to_3d_general 的 CIRCLE 解析命中 SKIP_LINETYPES——该管线的
    v0.6.3 设计是隐藏层**整圆保留**（孔/台阶圆是 P0 切割刀具来源、
    外环恢复依据），显式 HIDDEN 会把 16 个隐藏圆全部跳过（实测闭环
    重建体积 +28.46%、CSG 60×60 丢法兰 φ80 的根因）。
    """
    for x1, y1, x2, y2 in view_dict["lines"]:
        msp.add_line((x1 + ox, y1 + oy), (x2 + ox, y2 + oy),
                     dxfattribs={"layer": "可见轮廓"})
    for cx, cy, r, is_full, angles in view_dict["circles"]:
        if is_full:
            msp.add_circle((cx + ox, cy + oy), r,
                           dxfattribs={"layer": "可见轮廓"})
        else:
            for a1, a2 in angles:
                msp.add_arc((cx + ox, cy + oy), r,
                            math.degrees(a1), math.degrees(a2),
                            dxfattribs={"layer": "可见轮廓"})
    for x1, y1, x2, y2 in view_dict["hidden_lines"]:
        msp.add_line((x1 + ox, y1 + oy), (x2 + ox, y2 + oy),
                     dxfattribs={"layer": "隐藏线"})
    for cx, cy, r, is_full, angles in view_dict["hidden_circles"]:
        if is_full:
            msp.add_circle((cx + ox, cy + oy), r,
                           dxfattribs={"layer": "隐藏线"})
        else:
            for a1, a2 in angles:
                msp.add_arc((cx + ox, cy + oy), r,
                            math.degrees(a1), math.degrees(a2),
                            dxfattribs={"layer": "隐藏线"})


def create_dxf(views, output_path: Path):
    """生成只含视图几何的 DXF（第三角布局）。"""
    doc = ezdxf.new()
    for name, color, ltype in [
        ("可见轮廓", 7, "CONTINUOUS"),
        ("隐藏线", 5, "HIDDEN"),
    ]:
        ly = doc.layers.add(name, color=color)
        if ltype != "CONTINUOUS":
            try:
                ly.set_linetype(ltype)
            except Exception:
                pass
    doc.header["$MEASUREMENT"] = 1
    doc.header["$INSUNITS"] = 4  # mm
    msp = doc.modelspace()

    f_bb = _bbox_all(views["front"])
    t_bb = _bbox_all(views["top"])
    s_bb = _bbox_all(views["side"])
    gap = max(VIEW_GAP_MIN, (f_bb[2] - f_bb[0]) * 0.35)

    # 第三角布局: front@(0,0), top 在上, side 在右
    FX, FY = 0.0, 0.0
    TX = FX + (f_bb[2] - f_bb[0] - (t_bb[2] - t_bb[0])) / 2
    TY = FY + (f_bb[3] - f_bb[1]) + gap
    RX = FX + (f_bb[2] - f_bb[0]) + gap
    RY = FY + (f_bb[3] - f_bb[1] - (s_bb[3] - s_bb[1])) / 2

    def _off(bb, vx, vy):
        return vx - bb[0], vy - bb[1]

    _draw_view_elements(msp, views["front"], *_off(f_bb, FX, FY))
    _draw_view_elements(msp, views["top"], *_off(t_bb, TX, TY))
    _draw_view_elements(msp, views["side"], *_off(s_bb, RX, RY))

    doc.saveas(str(output_path))
    print(f"  DXF: {output_path}")
    for k in ("front", "top", "side"):
        v = views[k]
        print(f"  {k}: {len(v['lines'])}线 {len(v['circles'])}圆, "
              f"隐藏 {len(v['hidden_lines'])}线 {len(v['hidden_circles'])}圆")


def create_full_drawing(views, sections, output_path: Path, hatch_scale=2.0):
    """完整图纸：三视图 + 剖面图 + 剖切线标记。

    与 `create_dxf` 的三视图输出分开成两个文件，因为本文件含 HATCH 和
    剖切线，而 dxf_to_3d_general 的闭环重建把 HATCH 当剖面材料信号
    （P2b）、把多余视图簇当独立视图——混在一起会破坏重建。
    """
    import section_view as sv

    doc = ezdxf.new()
    sv.setup_layers(doc)
    doc.header["$MEASUREMENT"] = 1
    doc.header["$INSUNITS"] = 4
    msp = doc.modelspace()

    # 排版用准确 bbox：_bbox_all 对弧按整圆算，bracket top 视图会虚胖
    # 6mm（见 section_view.bbox_2d 注释）。闭环链的 create_dxf 不动。
    f_bb = sv.bbox_2d(views["front"])
    t_bb = sv.bbox_2d(views["top"])
    s_bb = sv.bbox_2d(views["side"])
    fw, fh = f_bb[2] - f_bb[0], f_bb[3] - f_bb[1]
    gap = max(VIEW_GAP_MIN, fw * 0.35)

    FX, FY = 0.0, 0.0
    TX = FX + (fw - (t_bb[2] - t_bb[0])) / 2
    TY = FY + fh + gap
    RX = FX + fw + gap
    RY = FY + (fh - (s_bb[3] - s_bb[1])) / 2

    def _off(bb, vx, vy):
        return vx - bb[0], vy - bb[1]

    f_off = _off(f_bb, FX, FY)
    t_off = _off(t_bb, TX, TY)
    s_off = _off(s_bb, RX, RY)
    _draw_view_elements(msp, views["front"], *f_off)
    _draw_view_elements(msp, views["top"], *t_off)
    _draw_view_elements(msp, views["side"], *s_off)

    sv.draw_label(msp, "主视图", FX + fw / 2, FY - 14)
    sv.draw_label(msp, "俯视图", TX + (t_bb[2] - t_bb[0]) / 2, TY - 14)
    sv.draw_label(msp, "左视图", RX + (s_bb[2] - s_bb[0]) / 2, RY - 14)

    # --- 剖面图：主视图下方依次排开 ---
    cur_y = FY - 60.0
    n_hatch = 0
    for sec in sections:
        bb = sv.bbox_2d(sec["view"])
        w, h = bb[2] - bb[0], bb[3] - bb[1]
        ox, oy = FX - bb[0], cur_y - h - bb[1]
        _draw_view_elements(msp, sec["view"], ox, oy)
        n_hatch += sv.draw_hatch(msp, sec["hatch"], ox, oy, scale=hatch_scale)
        sv.draw_label(msp, f"{sec['label']}  {sec['desc']}",
                      FX + w / 2, cur_y - h - 16)
        # 剖切线标在能看出剖切位置的父视图上（俯视图同时含 X 和 Y）
        sv.draw_cut_marker(msp, sec["spec"], "top", t_off[0], t_off[1],
                           t_bb, mirror_x=True)
        cur_y -= h + 55.0

    doc.saveas(str(output_path))
    print(f"  图纸: {output_path}")
    print(f"         三视图 3 个 + 剖面 {len(sections)} 个 + "
          f"HATCH {n_hatch} 块")


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    flags = [a for a in sys.argv[1:] if a.startswith("--")]
    if not args:
        print(__doc__)
        return 1

    step_path = Path(args[0])
    out_path = Path(args[1]) if len(args) > 1 else \
        CAD_TEMP / f"{step_path.stem}_三视图.dxf"
    no_section = "--no-section" in flags

    import section_view as sv

    shape = load_step(step_path)

    # ---- 闭环链用的三视图：**不融合**，用原始 shape ----
    # 融合会抹掉重叠实体的交界线，而那些线正是 CSG 重建的特征信号
    # （隐藏竖线 = 孔壁/台阶壁，见 dxf_to_3d_general v0.6.8）。
    # 实测 bracket（CSG_WELD=1，同环境对照）：
    #   原始 shape 出图 → 重建 191,598.0（−389.8 / −0.20%），
    #                     与 v0.6.14 记录基线 −389.77 逐位复现
    #   融合后出图     → 重建 201,631.3（+9,643.5 / +5.02%），明显回归
    views = project_all_views(shape)
    create_dxf(views, out_path)

    if no_section:
        return 0

    # ---- 图纸/剖面用的形状：**必须融合** ----
    # 多实体 compound 直接做布尔会静默部分失败（CLAUDE.md v0.6.14 根因），
    # 剖切结果会缺块；且重叠实体体积重复计数（bracket 275,548 vs 真实
    # 191,988），截面自检也会失真。
    fused, _ = sv.fuse_solids(shape)
    info = sv.analyze_structure(fused)
    if not info["has_internal"]:
        print("  [剖面] 未检出内部结构，跳过剖面图")
        return 0

    specs = sv.suggest_sections(info)
    sections = [sv.generate_section(fused, s) for s in specs]
    # 图纸上的三视图也用融合形状：重叠体内部交界线在图纸上是不存在的
    # 假线，读图时是干扰（闭环链另走上面未融合那份）
    sheet_views = project_all_views(fused)
    sec_path = out_path.with_name(out_path.stem + "_剖面图.dxf")
    create_full_drawing(sheet_views, sections, sec_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
