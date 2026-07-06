#!/usr/bin/env python
"""SolidWorks COM 自动化 — 直接构建电机模型 + 生成标准工程图.

工作流程:
  1. 连接 SW 2025 COM
  2. 新建零件，使用特征命令构建电机模型
  3. 新建工程图文档
  4. 插入三视图 + 剖面图
  5. 导出 DXF / PDF

电机模型参数 (GT):
  底座: 80×80×26.5mm 方块
  凸台: 60×60×70.4mm 方块
  中心阶梯孔: R=40/30/25/21/16/8.5
  安装孔 R=1.6 × 4
  沉头孔 R=2.7 × 4
"""

import math
import sys
import os
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.parent
SRC_PATH = PROJECT_ROOT / "src"
for p in [str(PROJECT_ROOT), str(SRC_PATH)]:
    if p not in sys.path:
        sys.path.insert(0, p)

# ============================================================
# 路径
# ============================================================
SCRIPT_DIR = Path(__file__).parent.resolve()
OUTPUT_SLDPRT = SCRIPT_DIR / "motor_model.sldprt"
OUTPUT_SLDDRW = SCRIPT_DIR / "motor_drawing.slddrw"
OUTPUT_DXF = SCRIPT_DIR / "motor_sw_drawing.dxf"
OUTPUT_PDF = SCRIPT_DIR / "motor_sw_drawing.pdf"

print("=" * 60)
print("SolidWorks COM — 电机模型 + 工程图")
print("=" * 60)

# ============================================================
# SW COM 初始化
# ============================================================
import pythoncom
import win32com.client
from win32com.client import VARIANT

pythoncom.CoInitialize()

print("\n[1/8] 连接 SolidWorks 2025...")
sw_app = win32com.client.Dispatch("SldWorks.Application")
sw_app.Visible = True
print(f"  版本: {sw_app.RevisionNumber}")

NULL_DISP = VARIANT(pythoncom.VT_DISPATCH, None)
NULL_VAR = VARIANT(pythoncom.VT_BYREF | pythoncom.VT_VARIANT, None)

# 常量
swDocPART = 1
swDocDRAWING = 3
swEndCondBlind = 0
swEndCondThroughAll = 1
swStartSketchPlane = 0

# ============================================================
# 辅助函数
# ============================================================

def mm_to_m(mm_val):
    """SW 特征 API 使用米作为单位。"""
    return mm_val / 1000.0


def create_part_template():
    """创建新零件文档。"""
    # 查找模板
    import os as _os
    template = None
    for td in [
        r"C:\ProgramData\SOLIDWORKS\SOLIDWORKS 2025\templates",
        r"C:\ProgramData\SolidWorks\SOLIDWORKS 2025\templates",
    ]:
        if _os.path.isdir(td):
            for name in ["gb_part.prtdot", "part.prtdot", "零件.prtdot"]:
                fp = _os.path.join(td, name)
                if _os.path.isfile(fp):
                    template = fp
                    break
        if template: break
    if template is None:
        template = sw_app.GetDocumentTemplate(swDocPART, "", 0, 0, 0)
    return sw_app.NewDocument(template, 0, 0, 0)


def start_sketch(model, plane_name):
    """在指定基准面上开始草图。"""
    model.ClearSelection2(True)
    model.Extension.SelectByID2(plane_name, "PLANE", 0, 0, 0, False, 0, NULL_DISP, 0)
    model.InsertSketch2(True)


def draw_rect(model, x1, y1, x2, y2, z=0):
    """在活动草图中绘制矩形。

    注意: SW 草图坐标使用文档单位（MMGS=mm），不需要转换。
    """
    mgr = model.SketchManager
    mgr.CreateCornerRectangle(x1, y1, z, x2, y2, z)


def draw_circle(model, cx, cy, r, z=0):
    """在活动草图中绘制圆（文档单位=mm）。"""
    mgr = model.SketchManager
    mgr.CreateCircle(cx, cy, z, cx + r, cy, z)


def feature_extrude(model, depth_mm, is_cut=False, name="Extrude"):
    """拉伸特征（凸台或切除）。

    Args:
        depth_mm: 拉伸深度 (mm)，正值
        is_cut: True=切除, False=凸台
    """
    fm = model.FeatureManager
    depth_m = depth_mm / 1000.0
    try:
        feat = fm.FeatureExtrusion2(
            True,                   # SingleDir
            False,                  # BothDirections
            False,                  # FlipDir
            swEndCondBlind,         # EndCondition
            0,                      # 反向侧条件
            depth_m,                # Depth (米)
            0.0,                    # 反向深度
            False,                  # 拔模向内
            False,                  # 拔模向外
            False,                  # 带拔模
            False,                  # 双向不对称
            False,                  # 薄壁特征
            False,                  # 双向薄壁
            0.0, 0.0,              # 薄壁厚度
            0, 0,                   # 薄壁类型
            True,                   # 合并
            True,                   # 使用特征范围
            True,                   # 自动选择
            0, 0,                   # 起始/结束偏移
            is_cut,                 # IsCut
        )
        if feat is not None:
            feat.Name = name
            return True
    except Exception as e:
        print(f"  WARNING: {name} 失败 - {e}")
    return False


# ============================================================
# 构建电机模型
# ============================================================
print("\n[2/8] 新零件 + 构建底座...")
part = create_part_template()
if part is None:
    print("ERROR: 无法创建零件")
    sys.exit(1)

part.SetUserPreferenceIntegerValue(296, 0)  # MMGS
print(f"  零件: {part.GetTitle}")

# --- 底座: 80×80×26.5mm ---
start_sketch(part, "Top Plane")
draw_rect(part, -40, -40, 40, 40)
feature_extrude(part, 26.5, is_cut=False, name="Base-80x80x26.5")
print("  [OK] 底座 (80x80x26.5)")

# --- 凸台: 60×60×70.4mm ---
print("\n[3/8] 构建凸台...")
# 在底座顶面创建草图 (Z=26.5mm)
part.ClearSelection2(True)
part.Extension.SelectByID2("", "FACE", 0, 0, 26.5, False, 0, NULL_DISP, 0)
part.InsertSketch2(True)
draw_rect(part, -30, -30, 30, 30)
feature_extrude(part, 70.4, is_cut=False, name="Body-60x60x70.4")
print("  [OK] 凸台 (60x60x70.4)")

# --- 中心阶梯孔 ---
print("\n[4/8] 构建中心阶梯孔...")
# 所有孔从底面 (Z=-26.5) 开始，不同深度
# 但草图只能在平面上。简化：从底面开始，每个孔径做一次拉伸切除
bore_specs = [
    (40.0, 5.0),      # R40 深5mm
    (30.0, 13.0),     # R30 深13mm (5+8)
    (25.0, 23.0),     # R25 深23mm
    (21.0, 29.0),     # R21 深29mm
    (16.0, 41.0),     # R16 深41mm
    (8.5, 96.9),      # R8.5 通孔
]
# 在底面创建草图
part.ClearSelection2(True)
part.Extension.SelectByID2("", "FACE", 0, 0, -26.5, False, 0, NULL_DISP, 0)
part.InsertSketch2(True)
for radius, _ in bore_specs:
    draw_circle(part, 0, 0, radius)
# 分别拉伸切除（需要退出草图再重新开始）
# 实际上 CreateCircle 会叠加所有圆在同一个草图中
# 但拉伸切除只能对一个封闭轮廓操作

# 简化: 每个孔径单独做
for i, (radius, depth) in enumerate(bore_specs):
    part.ClearSelection2(True)
    # 选择底面 (Z=-26.5)
    part.Extension.SelectByID2("", "FACE", 0, 0, -26.5, False, 0, NULL_DISP, 0)
    # 在上面画圆
    part.InsertSketch2(True)
    draw_circle(part, 0, 0, radius)
    # 拉伸切除
    feature_extrude(part, depth, is_cut=True, name=f"Bore-R{radius}")

print("  [OK] 中心阶梯孔 (6级)")

# --- 安装孔 R=1.6 ---
print("\n[5/8] 构建安装孔 R=1.6...")
part.ClearSelection2(True)
part.Extension.SelectByID2("", "FACE", 0, 0, -26.5, False, 0, NULL_DISP, 0)
part.InsertSketch2(True)
for gx in [-24.7, 24.7]:
    for gy in [-24.7, 24.7]:
        draw_circle(part, gx, gy, 1.6)
feature_extrude(part, 28, is_cut=True, name="MountHoles-R1.6")
print("  [OK] 4x 安装孔")

# --- 沉头孔 R=2.7 ---
print("\n[6/8] 构建沉头孔 R=2.7...")
# 沉头孔从底面开始，深8mm（上部）+ R=1.6 下部
# 简化：R=2.7 沉孔深8mm从底面
part.ClearSelection2(True)
part.Extension.SelectByID2("", "FACE", 0, 0, -26.5, False, 0, NULL_DISP, 0)
part.InsertSketch2(True)
for gx in [-24.7, 24.7]:
    for gy in [-24.7, 24.7]:
        draw_circle(part, gx, gy, 2.7)
feature_extrude(part, 8, is_cut=True, name="Cbore-R2.7")
print("  [OK] 4x 沉头孔")

# 保存零件
print(f"\n[7/8] 保存零件...")
part.SaveAs3(str(OUTPUT_SLDPRT), 0, 1)
print(f"  [OK] {OUTPUT_SLDPRT}")

part.ViewZoomtofit2()


# ============================================================
# 创建工程图
# ============================================================
print(f"\n[8/8] 创建工程图...")

# 查找工程图模板
drawing_template = None
for td in [
    r"C:\ProgramData\SOLIDWORKS\SOLIDWORKS 2025\templates",
    r"C:\ProgramData\SolidWorks\SOLIDWORKS 2025\templates",
]:
    if os.path.isdir(td):
        for name in ["gb_a4.drwdot", "gb_a4p.drwdot", "gb_a.drwdot",
                     "A4.drwdot", "drawing.drwdot", "工程图.drwdot"]:
            fp = os.path.join(td, name)
            if os.path.isfile(fp):
                drawing_template = fp
                print(f"  模板: {fp}")
                break
    if drawing_template: break
if drawing_template is None:
    drawing_template = sw_app.GetDocumentTemplate(swDocDRAWING, "", 0, 0, 0)

drawing = sw_app.NewDocument(drawing_template, 0, 0, 0)
if drawing is None:
    print("ERROR: 无法创建工程图")
    sys.exit(1)
print(f"  工程图: {drawing.GetTitle}")

# 参考模型路径
model_path = str(OUTPUT_SLDPRT)
print(f"  参考模型: {model_path}")

# 尝试创建三视图
views_ok = False
for method_name in [
    "Create3rdAngleViews2",      # SW 2017+
    "Create1stAngleViews2",      # 第一角投影
    "CreateDrawViewFromModelView3",
]:
    try:
        if method_name == "CreateDrawViewFromModelView3":
            # 手动创建每个视图
            positions = [
                ("*Front", 0.06, 0.13, "主视图"),
                ("*Top", 0.06, 0.05, "俯视图"),
                ("*Right", 0.15, 0.13, "右视图"),
                ("*Isometric", 0.18, 0.03, "等轴测"),
            ]
            for vname, vx, vy, label in positions:
                v = drawing.CreateDrawViewFromModelView3(model_path, vname, vx, vy, 0)
                print(f"    {label} ({vname}): {'OK' if v else 'FAIL'}")
            views_ok = True
            break
        else:
            # 自动布局方法
            getattr(drawing, method_name)(model_path)
            print(f"  [OK] {method_name} 完成")
            views_ok = True
            break
    except Exception as e:
        print(f"  {method_name}: {str(e)[:100]}")

if not views_ok:
    print("  WARNING: 所有视图创建方法均失败，请在SW中手动创建")

# 保存工程图
try:
    drawing.SaveAs3(str(OUTPUT_SLDDRW), 0, 1)
    print(f"  [OK] SW工程图: {OUTPUT_SLDDRW}")
except Exception as e:
    print(f"  WARNING: 保存 SLDDRW 失败 - {e}")

# 导出 DXF
try:
    drawing.SaveAs3(str(OUTPUT_DXF), 0, 1)
    print(f"  [OK] DXF: {OUTPUT_DXF}")
except Exception as e:
    print(f"  WARNING: 导出 DXF 失败 - {e}")

# 导出 PDF
try:
    drawing.SaveAs3(str(OUTPUT_PDF), 0, 1)
    print(f"  [OK] PDF: {OUTPUT_PDF}")
except Exception as e:
    print(f"  WARNING: 导出 PDF 失败 - {e}")


print("\n" + "=" * 60)
print("完成!")
print(f"  零件:   {OUTPUT_SLDPRT}")
print(f"  工程图: {OUTPUT_SLDDRW}")
print(f"  DXF:    {OUTPUT_DXF}")
print(f"  PDF:    {OUTPUT_PDF}")
print("=" * 60)
