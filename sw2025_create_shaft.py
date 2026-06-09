#!/usr/bin/env python
"""SolidWorks 2025 Python COM 驱动 — 阶梯轴参数化建模。

使用 pywin32 (win32com.client) 直接驱动 SolidWorks，替代 VBA 宏。
优势:
  - 无需启用宏安全设置
  - Python 异常处理，调试更方便
  - 可直接读取 DXF/参数文件
  - 可集成到主应用

用法:
    # 使用内置参数创建阶梯轴
    python sw2025_create_shaft.py

    # 指定 DXF 文件提取参数
    python sw2025_create_shaft.py --dxf CAD/xxx.dxf

    # 仅验证 SolidWorks 连接，不创建模型
    python sw2025_create_shaft.py --check

环境要求:
    pip install pywin32
    SolidWorks 2025 已安装
"""

import argparse
import math
import sys
import traceback
from pathlib import Path

# ============================================================================
# 阶梯轴参数（默认值，可被 DXF 覆盖）
# ============================================================================
SHAFT_SECTIONS = [
    # x_start, x_end, radius (mm)
    (-233.066, -158.466, 16.0),
    (-157.266, -108.466, 18.5),
    (-107.266,  -85.466, 20.0),
    ( -84.266,   79.534, 23.0),
    (  80.734,   86.734, 25.0),
    (  87.934,  171.734, 21.5),
    ( 172.934,  221.734, 20.0),
]

KEYWAYS = [
    # x_start, x_end, width, depth, shaft_radius (mm)
    (-216.266, -176.266, 10.0, 5.0, 16.0),
    ( 110.734,  148.734, 12.0, 6.0, 21.5),
]

CHAMFER_MM = 1.2   # C1.2
FILLET_R_MM = 1.2  # R1.2


# ============================================================================
# SolidWorks 2025 枚举常量
# ============================================================================
swDocPART = 1
swEndCondBlind = 0
swEndCondThroughAll = 1
swStartSketchPlane = 0
swChamferDistanceDistance = 2
swRefPlaneOffset = 8
swFeatureFilletSimple = 0
swSelectType_EDGES = 2


class SolidWorksDriver:
    """SolidWorks 2025 COM 驱动封装。"""

    def __init__(self, visible: bool = True, timeout: float = 30.0):
        self.visible = visible
        self.timeout = timeout
        self.sw_app = None
        self.sw_model = None
        self.sw_part = None
        self.sw_feat_mgr = None
        self.sw_sketch_mgr = None

    # ----- 连接管理 -----

    def connect(self) -> bool:
        """连接到 SolidWorks 2025 COM 实例。"""
        import pythoncom
        import win32com.client

        print("正在连接 SolidWorks 2025 ...")
        try:
            # 先尝试获取已运行的实例
            pythoncom.CoInitialize()
            self.sw_app = win32com.client.Dispatch("SldWorks.Application")
        except Exception:
            print("  未找到运行中的 SolidWorks，尝试启动 ...")
            try:
                self.sw_app = win32com.client.Dispatch("SldWorks.Application")
            except Exception as e:
                print(f"  [FAIL] 无法连接 SolidWorks: {e}")
                return False

        if self.sw_app is None:
            print("  [FAIL] SolidWorks COM 对象为 None")
            return False

        # 设置可见性
        self.sw_app.Visible = self.visible
        print(f"  [OK] 已连接到 SolidWorks 2025 (版本 {self.sw_app.RevisionNumber})")
        return True

    def disconnect(self):
        """断开 COM 连接。"""
        self.sw_model = None
        self.sw_part = None
        self.sw_app = None
        print("已断开 SolidWorks COM 连接")

    # ----- 文档操作 -----

    def new_part(self) -> bool:
        """创建新零件文档。"""
        print("创建新零件文档 ...")
        try:
            template = self.sw_app.GetDocumentTemplate(swDocPART, "", 0, 0, 0)
            self.sw_part = self.sw_app.NewDocument(template, 0, 0, 0)
            if self.sw_part is None:
                print("  [FAIL] 无法创建新零件")
                return False
            self.sw_model = self.sw_part
            self.sw_feat_mgr = self.sw_model.FeatureManager
            self.sw_sketch_mgr = self.sw_model.SketchManager
            self.sw_model.SetUserPreferenceIntegerValue(296, 0)  # MMGS 单位
            self.sw_model.ShowNamedView2("*Isometric", -1)
            print("  [OK] 新零件已创建")
            return True
        except Exception as e:
            print(f"  [FAIL] 创建零件异常: {e}")
            return False

    # ----- 坐标转换辅助 -----

    @staticmethod
    def mm_to_m(mm: float) -> float:
        """毫米 → 米（SW API 使用的单位）。"""
        return mm / 1000.0

    @staticmethod
    def deg_to_rad(deg: float) -> float:
        """度 → 弧度。"""
        return deg * math.pi / 180.0

    # ----- 选择操作 -----

    def clear_selection(self):
        """清除所有选择。"""
        self.sw_model.ClearSelection2(True)

    def select_plane(self, name: str) -> bool:
        """按名称选择基准面。"""
        self.clear_selection()
        return self.sw_model.Extension.SelectByID2(
            name, "PLANE", 0.0, 0.0, 0.0, False, 0, None, 0
        )

    def select_edge_by_ray(self, x: float, y: float, z_start: float = -0.001,
                           z_end: float = 0.001, tolerance: float = 0.0001) -> int:
        """用射线选择边缘。返回选择数量。"""
        result = self.sw_model.Extension.SelectByRay(
            x, y, z_start, x, y, z_end, tolerance, 2, True, 0, None
        )
        return self.sw_model.Extension.GetSelectionCount

    # ----- 草图操作 -----

    def start_sketch(self, plane_name: str = "Front Plane") -> bool:
        """在指定基准面上开始草图。"""
        if not self.select_plane(plane_name):
            print(f"  [WARN] 无法选择基准面: {plane_name}")
            return False
        self.sw_sketch_mgr.InsertSketch2(True)
        return True

    def exit_sketch(self):
        """退出当前草图。"""
        self.sw_sketch_mgr.InsertSketch2(True)

    def draw_line(self, x1: float, y1: float, z1: float,
                  x2: float, y2: float, z2: float):
        """在草图中绘制直线（mm 坐标）。"""
        self.sw_sketch_mgr.CreateLine2(x1, y1, z1, x2, y2, z2)

    def draw_centerline(self, x1: float, y1: float, z1: float,
                        x2: float, y2: float, z2: float):
        """绘制中心线（旋转轴）。"""
        self.sw_sketch_mgr.CreateCenterLine2(x1, y1, z1, x2, y2, z2)

    # ----- 特征操作 -----

    def feature_revolve(self, angle_deg: float = 360.0) -> bool:
        """创建 360° 旋转凸台特征。
        使用 IFeatureManager.FeatureRevolve2 — SW 2024/2025/2026 统一 20 参数签名。
        """
        angle_rad = self.deg_to_rad(angle_deg)
        try:
            feat = self.sw_feat_mgr.FeatureRevolve2(
                True,          # SingleDir
                True,          # IsSolid
                False,         # IsThin
                False,         # IsCut
                False,         # ReverseDir
                False,         # BothDirectionUpToSameEntity
                0,             # Dir1Type = swEndCondBlind
                0,             # Dir2Type
                angle_rad,     # Dir1Angle (radians)
                0.0,           # Dir2Angle
                False,         # OffsetReverse1
                False,         # OffsetReverse2
                0.01,          # OffsetDistance1
                0.01,          # OffsetDistance2
                0,             # ThinType
                0.0,           # ThinThickness1
                0.0,           # ThinThickness2
                True,          # Merge
                True,          # UseFeatScope
                True,          # UseAutoSelect
            )
            if feat is None:
                print("  [FAIL] FeatureRevolve2 返回 None")
                return False
            feat.Name = "Revolve-ShaftBody"
            print(f"  [OK] Revolve-ShaftBody ({angle_deg}° 旋转)")
            return True
        except Exception as e:
            print(f"  [FAIL] 旋转特征异常: {e}")
            return False

    def feature_chamfer_edge(self, edge_x: float, edge_y: float,
                             size_mm: float, feat_name: str) -> bool:
        """用 InsertFeatureChamfer 创建倒角。"""
        size_m = self.mm_to_m(size_mm)
        self.clear_selection()
        count = self.select_edge_by_ray(edge_x, edge_y)
        if count == 0:
            print(f"  [WARN] {feat_name}: 未找到边缘 (X={edge_x}, Y={edge_y})")
            return False

        try:
            feat = self.sw_feat_mgr.InsertFeatureChamfer(
                0,          # Options
                2,          # ChamferType = swChamferDistanceDistance
                0.0,        # Width (unused for dist-dist)
                0.0,        # Angle (unused for dist-dist)
                size_m,     # OtherDist = 等距倒角 (米)
                0.0, 0.0, 0.0,
            )
            if feat is None:
                print(f"  [FAIL] {feat_name}: InsertFeatureChamfer 返回 None")
                return False
            feat.Name = feat_name
            print(f"  [OK] {feat_name} (C{size_mm})")
            return True
        except Exception as e:
            print(f"  [FAIL] {feat_name}: {e}")
            return False

    def feature_fillet_edges(self, edge_specs: list, radius_mm: float,
                             feat_name: str = "Fillet-Transitions") -> bool:
        """选中多条边，创建等半径圆角。"""
        radius_m = self.mm_to_m(radius_mm)
        self.clear_selection()
        for ex, ey in edge_specs:
            self.select_edge_by_ray(ex, ey)

        total = self.sw_model.Extension.GetSelectionCount
        expected = len(edge_specs)
        print(f"  圆角选边: {total}/{expected}")
        if total < expected:
            print(f"  [WARN] 仅选中 {total} 条边 (预期 {expected})")
            # 继续尝试，因为有些边可能已被选中

        try:
            feat = self.sw_feat_mgr.FeatureFillet3(
                0,             # Options = swFeatureFilletSimple
                radius_m,      # Radius (米)
                0.0,           # SetbackDist
                0,             # SetbackType
                True,          # TangentPropagation
                0,             # OverflowType
                True, True,    # FeatureScope, AutoSelect
            )
            if feat is None:
                print(f"  [FAIL] {feat_name}: FeatureFillet3 返回 None")
                return False
            feat.Name = feat_name
            print(f"  [OK] {feat_name} (R{radius_mm}, {total} edges)")
            return True
        except Exception as e:
            print(f"  [FAIL] {feat_name}: {e}")
            return False

    def feature_cut_keyway(self, cx_mm: float, length_mm: float,
                           half_width_mm: float, shaft_r_mm: float,
                           depth_mm: float, feat_name: str) -> bool:
        """创建键槽拉伸切除。

        方法:
          1. 从 Top Plane 偏移 shaftR 创建切线基准面
          2. 绘制矩形
          3. 向下拉伸切除
        """
        offset_m = self.mm_to_m(shaft_r_mm)
        depth_m = self.mm_to_m(depth_mm)
        y_tangent = shaft_r_mm  # 切线面 Y 坐标 (mm)

        x1 = cx_mm - length_mm / 2.0
        x2 = cx_mm + length_mm / 2.0
        z1 = -half_width_mm
        z2 = half_width_mm

        plane_name = feat_name + "-Plane"

        # A: 创建切线基准面
        self.clear_selection()
        if not self.select_plane("Top Plane"):
            print(f"  [FAIL] {feat_name}: 无法选择 Top Plane")
            return False

        try:
            plane = self.sw_feat_mgr.InsertRefPlane(
                8,          # swRefPlaneOffset
                offset_m,   # 偏移距离 (米)
                0, 0, 0, 0,
            )
            if plane is None:
                print(f"  [FAIL] {feat_name}: InsertRefPlane 返回 None")
                return False
            plane.Name = plane_name
            print(f"  [INFO] {feat_name}: 基准面已创建 (偏移 +{shaft_r_mm}mm)")
        except Exception as e:
            print(f"  [FAIL] {feat_name}: 创建基准面异常 - {e}")
            return False

        # B: 绘制键槽矩形
        self.exit_sketch()  # 确保在正确的草图上下文中
        self.sw_sketch_mgr.InsertSketch2(True)

        self.draw_line(x1, y_tangent, z1, x2, y_tangent, z1)  # 前边
        self.draw_line(x2, y_tangent, z1, x2, y_tangent, z2)  # 右边
        self.draw_line(x2, y_tangent, z2, x1, y_tangent, z2)  # 后边
        self.draw_line(x1, y_tangent, z2, x1, y_tangent, z1)  # 左边

        self.exit_sketch()

        # C: 拉伸切除
        try:
            feat = self.sw_feat_mgr.FeatureCut3(
                True,          # Sd — 单方向
                False,         # Flip — 不翻转切除侧
                False,         # Dir — 不反向
                0,             # T1 = swEndCondBlind
                0,             # T2 (未使用)
                depth_m,       # D1 深度 (米)
                depth_m,       # D2 (未使用)
                False,         # Dchk1 — 无拔模
                False,         # Dchk2
                False, False,  # Ddir1, Ddir2
                0.0, 0.0,      # Dang1, Dang2
                False, False,  # OffsetReverse
                False, False,  # TranslateSurface
                False,         # NormalCut
                True,          # UseFeatScope
                True,          # UseAutoSelect
                False, False, False,  # Assembly
                0,             # T0 = swStartSketchPlane
                0.0,           # StartOffset
                False,         # FlipStartOffset
            )
            if feat is None:
                print(f"  [FAIL] {feat_name}: FeatureCut3 返回 None")
                return False
            feat.Name = feat_name
            print(f"  [OK] {feat_name} (L={length_mm:.0f} W={half_width_mm*2:.0f} D={depth_mm:.0f})")
            return True
        except Exception as e:
            print(f"  [FAIL] {feat_name}: FeatureCut3 异常 - {e}")
            return False

    # ----- 高级操作 -----

    def create_shaft_body(self, sections: list) -> bool:
        """从轴段参数创建旋转基体草图并生成特征。"""
        print("--- 创建旋转基体 ---")
        left_x = sections[0][0]
        left_r = sections[0][2]
        right_x = sections[-1][1]
        right_r = sections[-1][2]

        # 计算阶跃面 X 坐标
        step_x = []
        for i in range(len(sections) - 1):
            mid = (sections[i][1] + sections[i + 1][0]) / 2.0
            step_x.append(mid)

        # 开始草图
        if not self.start_sketch("Front Plane"):
            return False

        # 绘制半剖面轮廓
        lines = []
        # 左端面
        lines.append((left_x, 0.0, left_x, left_r))
        # 各段
        for i, (xs, xe, r) in enumerate(sections):
            if i == 0:
                lines.append((left_x, r, xe, r))
            else:
                ps = step_x[i - 1]
                pr = sections[i - 1][2]
                lines.append((ps, pr, ps, r))
                lines.append((ps, r, xe, r))
            if i < len(sections) - 1:
                lines.append((xe, r, step_x[i], r))
        # 右端面
        lines.append((right_x, right_r, right_x, 0.0))
        # 底部闭合
        lines.append((right_x, 0.0, left_x, 0.0))

        for x1, y1, x2, y2 in lines:
            self.draw_line(x1, y1, 0.0, x2, y2, 0.0)

        # 中心线
        self.draw_centerline(left_x, 0.0, 0.0, right_x, 0.0, 0.0)

        # 退出草图
        self.exit_sketch()
        print(f"  草图: {len(lines)} 条轮廓线, {len(step_x)} 个阶跃")

        # 旋转特征
        if not self.feature_revolve(360.0):
            return False

        return True

    def create_end_chamfers(self, left_x: float, left_r: float,
                            right_x: float, right_r: float,
                            chamfer_mm: float) -> bool:
        """创建左右端面倒角。"""
        print("--- 创建端面倒角 ---")
        ok1 = self.feature_chamfer_edge(left_x, left_r, chamfer_mm, "Chamfer-LeftEnd")
        ok2 = self.feature_chamfer_edge(right_x, right_r, chamfer_mm, "Chamfer-RightEnd")
        return ok1 and ok2

    def create_step_fillets(self, sections: list, fillet_r_mm: float) -> bool:
        """创建阶跃过渡圆角。"""
        print("--- 创建过渡圆角 ---")
        edge_specs = []
        for i in range(len(sections) - 1):
            mid = (sections[i][1] + sections[i + 1][0]) / 2.0
            r_big = max(sections[i][2], sections[i + 1][2])
            edge_specs.append((mid, r_big))
            print(f"  阶跃 {i+1}: X={mid:.1f}, R={r_big:.1f}")

        return self.feature_fillet_edges(edge_specs, fillet_r_mm)

    def create_keyways(self, keyways: list) -> list:
        """创建所有键槽。返回 (成功数, 总数)。"""
        print("--- 创建键槽 ---")
        results = []
        for i, (xs, xe, w, d, sr) in enumerate(keyways):
            cx = (xs + xe) / 2.0
            length = xe - xs
            hw = w / 2.0
            feat_name = f"Keyway-{i + 1}"
            ok = self.feature_cut_keyway(cx, length, hw, sr, d, feat_name)
            results.append(ok)
        return sum(results), len(results)


# ============================================================================
# 主流程
# ============================================================================

def build_stepped_shaft(driver: SolidWorksDriver,
                        sections: list = None,
                        keyways: list = None,
                        chamfer_mm: float = CHAMFER_MM,
                        fillet_r_mm: float = FILLET_R_MM) -> bool:
    """完整的阶梯轴建模流程。"""

    if sections is None:
        sections = SHAFT_SECTIONS
    if keyways is None:
        keyways = KEYWAYS

    left_x, _, left_r = sections[0]
    right_x, _, right_r = sections[-1]
    right_x = sections[-1][1]

    steps = [
        ("旋转基体", lambda: driver.create_shaft_body(sections)),
        ("端面倒角", lambda: driver.create_end_chamfers(
            left_x, left_r, right_x, right_r, chamfer_mm)),
        ("过渡圆角", lambda: driver.create_step_fillets(sections, fillet_r_mm)),
        ("键槽", lambda: driver.create_keyways(keyways)),
    ]

    all_ok = True
    for name, func in steps:
        try:
            ok = func()
            if not ok:
                print(f"  [WARN] '{name}' 步骤未完全成功，继续后续步骤")
                all_ok = False
        except Exception as e:
            print(f"  [FAIL] '{name}' 步骤异常: {e}")
            traceback.print_exc()
            all_ok = False

    return all_ok


def check_sw_connection():
    """验证 SolidWorks 2025 连接。"""
    print("=" * 60)
    print("SolidWorks 2025 连接诊断")
    print("=" * 60)
    driver = SolidWorksDriver(visible=True)
    if not driver.connect():
        print("\n[FAIL] 无法连接 SolidWorks")
        print("请检查:")
        print("  1. SolidWorks 2025 是否已安装?")
        print("  2. 是否已注册 COM 组件?")
        print("  3. 尝试以管理员身份运行 SolidWorks 一次")
        return False

    print(f"\nSolidWorks 版本: {driver.sw_app.RevisionNumber}")
    print("连接正常！")

    # 尝试获取模板
    try:
        template = driver.sw_app.GetDocumentTemplate(swDocPART, "", 0, 0, 0)
        print(f"零件模板: {template}")
    except Exception as e:
        print(f"模板获取异常: {e}")

    driver.disconnect()
    return True


def main():
    parser = argparse.ArgumentParser(
        description="SolidWorks 2025 Python COM 驱动 — 阶梯轴建模"
    )
    parser.add_argument("--check", action="store_true",
                        help="仅验证 SW 连接")
    parser.add_argument("--dxf", type=str, default=None,
                        help="从 DXF 文件提取参数")
    parser.add_argument("--no-save", action="store_true",
                        help="不弹出保存对话框")
    parser.add_argument("--output", type=str, default=None,
                        help="保存路径 (.sldprt)")
    args = parser.parse_args()

    if args.check:
        ok = check_sw_connection()
        sys.exit(0 if ok else 1)

    # 如果有 DXF，提取参数
    sections = SHAFT_SECTIONS
    keyways = KEYWAYS
    if args.dxf:
        # TODO: 实现 DXF 参数提取
        print(f"[WARN] DXF 参数提取尚未实现，使用默认参数")
        # from convert_dwg_to_3d import extract_shaft_params
        # sections, keyways = extract_shaft_params(args.dxf)

    # 连接 SolidWorks
    driver = SolidWorksDriver(visible=True)
    if not driver.connect():
        sys.exit(1)

    try:
        # 创建新零件
        if not driver.new_part():
            sys.exit(1)

        # 构建阶梯轴
        ok = build_stepped_shaft(driver, sections, keyways)

        # 完成
        driver.sw_model.ForceRebuild3(False)
        driver.sw_model.ViewZoomtofit2()

        if ok:
            print("\n" + "=" * 60)
            print("阶梯轴建模成功！")
            print("特征树:")
            print("  1. Revolve-ShaftBody (旋转基体)")
            print(f"  2. Chamfer-LeftEnd (左端倒角 C{CHAMFER_MM})")
            print(f"  3. Chamfer-RightEnd (右端倒角 C{CHAMFER_MM})")
            print(f"  4. Fillet-Transitions (过渡圆角 R{FILLET_R_MM})")
            for i, kw in enumerate(KEYWAYS):
                print(f"  {5+i}. Keyway-{i+1} (键槽 {kw[2]:.0f}×{kw[3]:.0f}mm)")
            print("=" * 60)
        else:
            print("\n[WARN] 部分步骤未成功，请检查 SolidWorks 特征树")

        # 保存
        if args.output:
            save_path = str(Path(args.output).absolute())
            print(f"\n正在保存到: {save_path}")
            try:
                # swSaveAsCurrentVersion = 0, swSaveAsOptions_Silent = 1
                driver.sw_model.Extension.SaveAs(
                    save_path, 0, 0, None, "", 1, 0
                )
                print(f"[OK] 已保存: {save_path}")
            except Exception as e:
                print(f"[WARN] 保存失败: {e}")
                print("请手动执行 文件 → 另存为")

    except Exception as e:
        print(f"\n[FAIL] 未预期的异常: {e}")
        traceback.print_exc()
        sys.exit(1)
    finally:
        driver.disconnect()


if __name__ == "__main__":
    main()
