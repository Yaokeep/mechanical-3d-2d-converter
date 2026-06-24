# SolidWorks 阶梯轴参数化建模
#
# 使用 SolidWorksDriver 在 SW 2025 中一键生成完整阶梯轴模型。
# 特征树（按顺序）:
#   1. Revolve-ShaftBody   — 360° 旋转基体
#   2. Chamfer-LeftEnd     — 左端面倒角
#   3. Chamfer-RightEnd    — 右端面倒角
#   4. Fillet-Transitions  — 阶跃过渡圆角
#   5. Keyway-N            — 键槽（可多个）

from __future__ import annotations

from typing import Callable

try:
    from loguru import logger
except ImportError:
    import logging
    logger = logging.getLogger("sw_automation")

from .sw_driver import SolidWorksDriver

# ---------------------------------------------------------------------------
# 默认阶梯轴参数（单位: mm）
# ---------------------------------------------------------------------------

DEFAULT_SECTIONS = [
    # (x_start, x_end, radius_mm)
    (-233.066, -158.466, 16.0),
    (-157.266, -108.466, 18.5),
    (-107.266,  -85.466, 20.0),
    ( -84.266,   79.534, 23.0),
    (  80.734,   86.734, 25.0),
    (  87.934,  171.734, 21.5),
    ( 172.934,  221.734, 20.0),
]

DEFAULT_KEYWAYS = [
    # (x_start, x_end, width_mm, depth_mm, shaft_radius_mm)
    (-216.266, -176.266, 10.0, 5.0, 16.0),
    ( 110.734,  148.734, 12.0, 6.0, 21.5),
]

DEFAULT_CHAMFER_MM = 1.2   # C1.2
DEFAULT_FILLET_R_MM = 1.2  # R1.2


# ---------------------------------------------------------------------------
# ShaftBuilder
# ---------------------------------------------------------------------------

class ShaftBuilder:
    """阶梯轴参数化建模构建器。

    使用 SolidWorksDriver 在 SW 2025 中创建完整阶梯轴模型。

    使用示例::

        driver = SolidWorksDriver(visible=True)
        if driver.connect() and driver.new_part():
            builder = ShaftBuilder(driver)
            builder.build(DEFAULT_SECTIONS, DEFAULT_KEYWAYS)
            driver.save_as("my_shaft.sldprt")
        driver.disconnect()
    """

    def __init__(self, driver: SolidWorksDriver):
        """初始化构建器。

        Args:
            driver: 已连接的 SolidWorksDriver 实例（需要已创建新零件）。
        """
        self._driver = driver

    # ------------------------------------------------------------------
    # 主构建流程
    # ------------------------------------------------------------------

    def build(
        self,
        sections: list[tuple[float, float, float]] | None = None,
        keyways: list[tuple[float, float, float, float, float]] | None = None,
        chamfer_mm: float = DEFAULT_CHAMFER_MM,
        left_chamfer_mm: float | None = None,
        right_chamfer_mm: float | None = None,
        fillet_r_mm: float = DEFAULT_FILLET_R_MM,
        progress_callback: Callable[[str, int], None] | None = None,
    ) -> bool:
        """完整的阶梯轴建模流程。

        Python COM 只创建旋转基体（最可靠），倒角、圆角、键槽
        全部通过 VBScript 在 SW 进程内完成。

        Args:
            sections: 轴段列表 [(x_start, x_end, radius_mm), ...]。
            keyways: 键槽列表 [(xs, xe, w, d, sr), ...]。
            chamfer_mm: 左右端统一倒角（left/right_chamfer_mm 未指定时使用）。
            left_chamfer_mm: 左端倒角尺寸（None=使用 chamfer_mm，0=跳过）。
            right_chamfer_mm: 右端倒角尺寸（None=使用 chamfer_mm，0=跳过）。
            fillet_r_mm: 阶跃过渡圆角半径。
        """
        if sections is None:
            sections = DEFAULT_SECTIONS
        if keyways is None:
            keyways = DEFAULT_KEYWAYS
        if left_chamfer_mm is None:
            left_chamfer_mm = chamfer_mm
        if right_chamfer_mm is None:
            right_chamfer_mm = chamfer_mm

        steps = [
            ("旋转基体", 0, 20, lambda: self.create_shaft_body(sections)),
            ("VBScript（倒角+圆角+键槽）", 20, 100,
             lambda: self._create_all_features_vba(
                 sections, keyways,
                 left_chamfer_mm, right_chamfer_mm, fillet_r_mm)),
        ]

        all_ok = True
        for name, pct_start, pct_end, func in steps:
            if progress_callback:
                progress_callback(name, pct_start)
            try:
                ok = func()
                if not ok:
                    logger.warning(f"'{name}' 步骤未完全成功，继续后续步骤")
                    all_ok = False
            except Exception as e:
                logger.error(f"'{name}' 步骤异常: {e}")
                all_ok = False
            if progress_callback:
                progress_callback(name, pct_end)

        return all_ok

    # ------------------------------------------------------------------
    # 旋转基体
    # ------------------------------------------------------------------

    def create_shaft_body(
        self,
        sections: list[tuple[float, float, float]],
    ) -> bool:
        """从轴段参数创建旋转基体。

        在前视基准面上绘制半剖面轮廓，然后 360° 旋转。

        Args:
            sections: 轴段列表。

        Returns:
            bool: 成功返回 True。
        """
        logger.info("--- 创建旋转基体 ---")
        left_x = sections[0][0]
        left_r = sections[0][2]
        right_x = sections[-1][1]
        right_r = sections[-1][2]

        # 计算阶跃面 X 坐标
        step_x = []
        for i in range(len(sections) - 1):
            mid = (sections[i][1] + sections[i + 1][0]) / 2.0
            step_x.append(mid)

        # 开始草图（前视基准面）
        if not self._driver.start_sketch("前视基准面"):
            return False

        # 绘制半剖面轮廓
        lines = []
        # 左端面: 中心线 → 顶部
        lines.append((left_x, 0.0, left_x, left_r))
        # 各段上表面 + 阶跃
        for i, (xs, xe, r) in enumerate(sections):
            if i == 0:
                lines.append((left_x, r, xe, r))
            else:
                ps = step_x[i - 1]
                pr = sections[i - 1][2]
                lines.append((ps, pr, ps, r))   # 阶跃上升
                lines.append((ps, r, xe, r))    # 段顶面
            if i < len(sections) - 1:
                lines.append((xe, r, step_x[i], r))  # 段尾
        # 右端面: 顶部 → 中心线
        lines.append((right_x, right_r, right_x, 0.0))
        # 底部闭合: 中心线返回
        lines.append((right_x, 0.0, left_x, 0.0))

        for x1, y1, x2, y2 in lines:
            self._driver.draw_line(x1, y1, 0.0, x2, y2, 0.0)

        # 旋转中心线
        self._driver.draw_centerline(left_x, 0.0, 0.0, right_x, 0.0, 0.0)

        # V45 规则: 草图必须保持打开状态调用特征方法！
        # 不要在此处调用 exit_sketch()
        logger.info(f"  草图: {len(lines)} 条轮廓线, {len(step_x)} 个阶跃面")

        if not self._driver.feature_revolve(360.0, is_cut=False,
                                             feat_name="Revolve-ShaftBody"):
            return False

        return True

    # ------------------------------------------------------------------
    # 综合 VBA 巨集（倒角 + 圆角 + 键槽）
    # ------------------------------------------------------------------

    def _create_all_features_vba(
        self,
        sections: list[tuple[float, float, float]],
        keyways: list[tuple[float, float, float, float, float]],
        left_chamfer_mm: float,
        right_chamfer_mm: float,
        fillet_r_mm: float,
    ) -> bool:
        """通过 VBScript 直接 COM 创建倒角+圆角+键槽。

        VBScript 与 VBA 共用同一 OLE Automation 引擎，不受 Python COM
        的草图平面限制（FeatureCut3 在参考面上可用）。

        不再保存 .bas 文件（SW VBA IDE 可能尝试编译导致弹窗）。
        """
        import os
        import subprocess
        import time
        from pathlib import Path

        logger.info("--- VBScript 直接 COM（倒角 + 圆角 + 键槽）---")

        project_root = Path(os.path.dirname(os.path.abspath(__file__))).parent.parent.parent
        macro_dir = project_root / "CAD"

        vbs_code = self._generate_post_revolve_vbs(
            sections, keyways, left_chamfer_mm, right_chamfer_mm, fillet_r_mm)
        vbs_path = macro_dir / "PostRevolve.vbs"
        # GBK 编码：cscript.exe 使用系统 ANSI 代码页 (CP936) 读取 .vbs 文件
        vbs_path.write_text(vbs_code, encoding="gbk")
        logger.info(f"  VBScript: {vbs_path} ({len(vbs_code)} 字节)")

        try:
            result = subprocess.run(
                ["cscript", "//Nologo", str(vbs_path)],
                capture_output=True, text=True, timeout=300,
            )
            stdout = result.stdout.strip()
            stderr = result.stderr.strip()
            logger.debug(f"  cscript stdout: {stdout}")
            if stderr:
                logger.debug(f"  cscript stderr: {stderr}")

            if result.returncode == 0 and "OK" in stdout:
                time.sleep(3)
                try:
                    self._driver.sw_model.ForceRebuild3(True)
                    self._driver.sw_model.ViewZoomtofit2()
                except Exception:
                    pass
                logger.success("  [OK] VBScript（倒角+圆角）完成！")

                # 键槽通过 Python COM FeatureCut4 创建
                # （VBScript COM 不支持 FeatureCut3，返回 Nothing）
                if keyways:
                    kw_ok = self._create_keyways_python(keyways)
                    if not kw_ok:
                        logger.warning("  键槽创建部分失败，请检查 SW 特征树")
                        return False
                return True
            else:
                logger.warning(f"  VBScript 失败: stdout={stdout}, stderr={stderr}")
                return False
        except subprocess.TimeoutExpired:
            logger.warning("  VBScript 超时（可能是 SW 弹窗阻塞）")
            return False
        except Exception as e:
            logger.warning(f"  VBScript 异常: {e}")
            return False

    def _generate_post_revolve_vba(
        self,
        sections: list[tuple[float, float, float]],
        keyways: list[tuple[float, float, float, float, float]],
        chamfer_mm: float,
        fillet_r_mm: float,
    ) -> str:
        """生成完整 VBA 巨集：倒角 + 圆角 + 键槽。

        关键：
        - 所有坐标使用米（MKS 文档单位），mm 值 / 1000。
        - 平面名称使用 SW API 内部英文名（Front Plane / Top Plane），
          避免 GBK 编码损坏中文名称。
        - 键槽采用前视基准面 + FeatureExtrusion2 双向 Z 轴拉伸
          （SW 自动判断为切除），替代 FeatureCut3（参考面上不可用）。
        """
        def m(mm_val: float) -> str:
            return f"{mm_val / 1000.0}"

        lines = []
        lines.append("Option Explicit")
        lines.append("")
        lines.append("' PostRevolve.bas - Chamfers + Fillets + Keyways")
        lines.append("' All units in METERS (MKS document)")
        lines.append("")
        lines.append("Sub main()")
        lines.append("    Dim swApp As Object, swModel As Object")
        lines.append("    Dim swFeatMgr As Object, swSketchMgr As Object")
        lines.append("    Dim swFeat As Object, swSelMgr As Object")
        lines.append("    Dim nSel As Long, i As Long")
        lines.append("    Dim x1 As Double, x2 As Double, y1 As Double, y2 As Double")
        lines.append("    Dim halfW As Double, halfL As Double, dM As Double")
        lines.append("")
        lines.append("    Set swApp = Application.SldWorks")
        lines.append("    Set swModel = swApp.ActiveDoc")
        lines.append("    If swModel Is Nothing Then")
        lines.append("        MsgBox \"No active document!\", vbCritical")
        lines.append("        Exit Sub")
        lines.append("    End If")
        lines.append("    Set swFeatMgr = swModel.FeatureManager")
        lines.append("    Set swSketchMgr = swModel.SketchManager")
        lines.append("    Set swSelMgr = swModel.SelectionManager")
        lines.append("")

        chamfer_m = chamfer_mm / 1000.0
        fillet_m = fillet_r_mm / 1000.0

        # ============================================================
        # 1. 端面倒角 — 选中端面外圆边，InsertFeatureChamfer
        # ============================================================
        left_x = sections[0][0]
        left_r = sections[0][2]
        right_x = sections[-1][1]
        right_r = sections[-1][2]

        lines.append("    ' ============================================")
        lines.append(f"    ' End Chamfers C{chamfer_mm}")
        lines.append("    ' ============================================")
        lines.append("")

        for name, ex, er in [("LeftEnd", left_x, left_r), ("RightEnd", right_x, right_r)]:
            lines.append(f"    ' Chamfer-{name}")
            lines.append("    swModel.ClearSelection2 True")
            # 端面圆边经过 (ex, er, 0)，Z=0 精确落在边上
            lines.append(f"    swModel.Extension.SelectByID2 \"\", \"Edge\", "
                         f"{m(ex)}, {m(er)}, 0.0, True, 0, Nothing, 0")
            lines.append("    nSel = swSelMgr.GetSelectedObjectCount2(-1)")
            lines.append("    If nSel > 0 Then")
            lines.append(f"        Set swFeat = swFeatMgr.InsertFeatureChamfer(")
            lines.append(f"            1, 1, {chamfer_m}#, 0.7853981633974483#, 0, 0, 0, False)")
            lines.append(f"        If Not swFeat Is Nothing Then swFeat.Name = \"Chamfer-{name}\"")
            lines.append("    End If")
            lines.append("")

        # ============================================================
        # 2. 阶跃过渡圆角 — 多选阶跃边，FeatureFillet3 (Options=195)
        # ============================================================
        lines.append("    ' ============================================")
        lines.append(f"    ' Step Fillets R{fillet_r_mm}")
        lines.append("    ' ============================================")
        lines.append("    swModel.ClearSelection2 True")

        for i in range(len(sections) - 1):
            mid = (sections[i][1] + sections[i + 1][0]) / 2.0
            r_big = max(sections[i][2], sections[i + 1][2])
            lines.append(f"    ' Step {i+1}: X={m(mid)}, R={m(r_big)}")
            # 阶跃边也在 Z=0 平面上
            lines.append(f"    swModel.Extension.SelectByID2 \"\", \"Edge\", "
                         f"{m(mid)}, {m(r_big)}, 0.0, True, 1, Nothing, 0")

        lines.append("    nSel = swSelMgr.GetSelectedObjectCount2(-1)")
        lines.append(f"    If nSel >= {len(sections) - 1} Then")
        lines.append(f"        Set swFeat = swFeatMgr.FeatureFillet3(")
        lines.append(f"            195, {fillet_m}#, 0, 0, False, 0, False, False)")
        lines.append("        If Not swFeat Is Nothing Then swFeat.Name = \"Fillet-Transitions\"")
        lines.append("    End If")
        lines.append("")

        # ============================================================
        # 3. 键槽 — 前视基准面 + FeatureExtrusion2 双向 Z 轴拉伸
        #    （Python COM FeatureCut3 参考面限制的变通方案）
        #    SW 自动判断为切除（已有实体时默认为 Cut）
        # ============================================================
        if keyways:
            lines.append("    ' ============================================")
            lines.append("    ' Keyways (Front Plane + FeatureExtrusion2)")
            lines.append("    ' ============================================")
            lines.append("")

        for kw_idx, (xs, xe, w, d, sr) in enumerate(keyways):
            n = kw_idx + 1
            length = xe - xs
            half_w = w / 2.0
            # 键槽深度方向: 从 shaft_radius 向下挖 depth
            y_top = sr                      # 轴表面 Y 坐标 (mm)
            y_bot = sr - d                  # 键槽底部 Y 坐标 (mm)

            lines.append(f"    ' Keyway {n}: X=[{xs:.1f},{xe:.1f}] W={w:.0f} D={d:.0f} R={sr:.0f}")
            lines.append("")
            lines.append(f"    ' Step 1: Sketch on Front Plane")
            lines.append("    swModel.ClearSelection2 True")
            # 使用 SW API 内部英文名称，避免 GBK 编码问题
            lines.append("    swModel.Extension.SelectByID2 \"Front Plane\", \"PLANE\", 0, 0, 0, True, 0, Nothing, 0")
            lines.append("    swModel.InsertSketch2 True")
            lines.append("")
            lines.append(f"    ' Keyway profile (XY plane, extrude along Z)")
            lines.append(f"    x1 = {m(xs)}#")
            lines.append(f"    x2 = {m(xe)}#")
            lines.append(f"    y1 = {m(y_bot)}#")
            lines.append(f"    y2 = {m(y_top)}#")
            lines.append("    swSketchMgr.CreateCornerRectangle x1, y1, 0, x2, y2, 0")
            lines.append("")
            lines.append(f"    ' Step 2: FeatureExtrusion2 bidirectional Z")
            lines.append(f"    halfW = {m(half_w)}#")
            lines.append("    Set swFeat = swFeatMgr.FeatureExtrusion2(True, False, False, 0, 0, halfW, halfW, False, False, False, False, 0, 0, False, False, False, False, True, True, True, 0, 0, False)")
            lines.append(f"    If Not swFeat Is Nothing Then")
            lines.append(f"        swFeat.Name = \"Keyway-{n}\"")
            lines.append("    End If")
            lines.append("")

        lines.append("    ' --- Done ---")
        lines.append("    swModel.ForceRebuild3 False")
        lines.append("    swModel.ViewZoomtofit2")
        lines.append("End Sub")
        lines.append("")

        return "\r\n".join(lines)

    # ------------------------------------------------------------------
    # VBScript 直接 COM 生成（替代 RunMacro，避免 SW2025 挂死）
    # ------------------------------------------------------------------

    def _generate_post_revolve_vbs(
        self,
        sections: list[tuple[float, float, float]],
        keyways: list[tuple[float, float, float, float, float]],
        left_chamfer_mm: float,
        right_chamfer_mm: float,
        fillet_r_mm: float,
    ) -> str:
        """生成 VBScript 直接操作 SW COM。

        特性:
        - 倒角: 按 DXF 检测的左右端独立尺寸（0=跳过该端）
        - 圆角: 多选阶跃边 + FeatureFillet3 (Options=195, SW2025 验证值)
        - 键槽: 上视基准面偏移→相切参考面→草图矩形→FeatureCut3 向下切除

        VBS 语法限制: 无 # 类型后缀、无 _ 续行符、函数调用必须单行。
        """
        def m(mm_val: float) -> str:
            return f"{mm_val / 1000.0}"

        lines = []
        lines.append("' PostRevolve.vbs - Direct COM post-revolve features")
        lines.append("Option Explicit")
        lines.append("")
        lines.append("Dim swApp, swModel, swFeatMgr, swSketchMgr, swSelMgr, swFeat")
        lines.append("Dim nSel, i, dM, hw")
        lines.append("")
        lines.append("' --- Connect to SW ---")
        lines.append("Set swApp = GetObject(, \"SldWorks.Application\")")
        lines.append("If swApp Is Nothing Then")
        lines.append("    WScript.Echo \"ERR: Cannot connect to SW\"")
        lines.append("    WScript.Quit 1")
        lines.append("End If")
        lines.append("Set swModel = swApp.ActiveDoc")
        lines.append("If swModel Is Nothing Then")
        lines.append("    WScript.Echo \"ERR: No active document\"")
        lines.append("    WScript.Quit 1")
        lines.append("End If")
        lines.append("Set swFeatMgr = swModel.FeatureManager")
        lines.append("Set swSketchMgr = swModel.SketchManager")
        lines.append("Set swSelMgr = swModel.SelectionManager")
        lines.append("")

        fillet_m = fillet_r_mm / 1000.0

        # ================================================================
        # 1. 端面倒角 — 按 DXF 检测的独立左右尺寸
        # ================================================================
        left_x = sections[0][0]
        left_r = sections[0][2]
        right_x = sections[-1][1]
        right_r = sections[-1][2]

        chamfer_list = [
            ("LeftEnd", left_x, left_r, left_chamfer_mm),
            ("RightEnd", right_x, right_r, right_chamfer_mm),
        ]
        active_chamfers = [(n, ex, er, sz) for n, ex, er, sz in chamfer_list if sz > 0]

        if active_chamfers:
            lines.append("' ============================================")
            lines.append(f"' 1. End Chamfers")
            lines.append("' ============================================")

        for name, ex, er, ch_size in active_chamfers:
            ch_m = ch_size / 1000.0
            lines.append(f"' Chamfer-{name}: X={ex:.1f}mm R={er:.1f}mm C{ch_size:.1f}")
            lines.append("swModel.ClearSelection2 True")
            lines.append(f"swModel.Extension.SelectByID2 \"\", \"Edge\", "
                         f"{m(ex)}, {m(er)}, 0.0, True, 0, Nothing, 0")
            lines.append("nSel = swSelMgr.GetSelectedObjectCount2(-1)")
            lines.append("If nSel > 0 Then")
            lines.append(f"    Set swFeat = swFeatMgr.InsertFeatureChamfer("
                         f"1, 1, {ch_m}, 0.7853981633974483, 0, 0, 0, False)")
            lines.append(f"    If Not swFeat Is Nothing Then swFeat.Name = \"Chamfer-{name}\"")
            lines.append("End If")

        if active_chamfers:
            lines.append("")

        # ================================================================
        # 2. 阶跃过渡圆角
        # ================================================================
        lines.append("' ============================================")
        lines.append(f"' 2. Step Fillets R{fillet_r_mm}")
        lines.append("' ============================================")
        lines.append("swModel.ClearSelection2 True")
        for i in range(len(sections) - 1):
            mid = (sections[i][1] + sections[i + 1][0]) / 2.0
            r_big = max(sections[i][2], sections[i + 1][2])
            lines.append(f"swModel.Extension.SelectByID2 \"\", \"Edge\", "
                         f"{m(mid)}, {m(r_big)}, 0.0, True, 1, Nothing, 0")
        lines.append("nSel = swSelMgr.GetSelectedObjectCount2(-1)")
        lines.append(f"If nSel >= {len(sections) - 1} Then")
        lines.append(f"    Set swFeat = swFeatMgr.FeatureFillet3("
                     f"195, {fillet_m}, 0, 0, False, 0, False, False)")
        lines.append("    If Not swFeat Is Nothing Then swFeat.Name = \"Fillet-Transitions\"")
        lines.append("End If")
        lines.append("")

        # ================================================================
        # 3. 键槽 — 由 Python COM FeatureCut4 处理（VBScript 中跳过）
        #    VBScript COM 接口不支持 FeatureCut3（返回 Nothing），
        #    而 Python COM FeatureCut4 在前视基准面上可用 (V45 验证)。
        # ================================================================
        if keyways:
            lines.append("' ============================================")
            lines.append("' 3. Keyways — skipped (handled by Python COM)")
            lines.append("' ============================================")

        lines.append("")
        lines.append("' --- Done ---")
        lines.append("swModel.ForceRebuild3 False")
        lines.append("swModel.ViewZoomtofit2")
        lines.append("WScript.Echo \"OK\"")
        lines.append("")

        return "\r\n".join(lines)

    # ------------------------------------------------------------------
    # Python COM 键槽创建 (FeatureCut4, SW2025)
    # ------------------------------------------------------------------

    def _create_keyways_python(
        self,
        keyways: list[tuple[float, float, float, float, float]],
    ) -> bool:
        """通过 Python COM FeatureCut4 创建键槽切除。

        V45 验证: FeatureCut3/4 在 Python COM 中前视基准面上可用。
        VBScript COM 接口 FeatureCut3 返回 Nothing（接口限制）。

        每个键槽:
          1. 前视基准面 + 草图矩形（Z=0, Y 跨轴表面）
          2. FeatureCut4 双向 Z 轴切除（深度=键槽半宽）
        """
        logger.info("--- Python COM 键槽切除 ---")
        all_ok = True
        for kw_idx, (xs, xe, w, d, sr) in enumerate(keyways):
            n = kw_idx + 1
            hw = w / 2.0  # 键槽半宽 = Z 方向切除深度
            y_bot = sr - d  # 键槽底部 Y (mm)
            y_top = sr      # 轴表面 Y (mm)

            logger.info(f"  键槽{n}: X=[{xs:.1f},{xe:.1f}] W={w:.0f} D={d:.0f} R={sr:.0f}")

            # 前视基准面草图（必须中文名称）
            if not self._driver.start_sketch("前视基准面"):
                logger.error(f"  键槽{n}: 无法打开前视基准面草图")
                all_ok = False
                continue

            # 矩形轮廓（Z=0 必须）
            z = 0.0
            self._driver.draw_line(xs, y_bot, z, xe, y_bot, z)
            self._driver.draw_line(xe, y_bot, z, xe, y_top, z)
            self._driver.draw_line(xe, y_top, z, xs, y_top, z)
            self._driver.draw_line(xs, y_top, z, xs, y_bot, z)

            # FeatureCut3 双向 Z 轴切除 (V45 验证 26 参数)
            ok = self._driver.feature_cut3_bidir(
                depth1_mm=hw,
                depth2_mm=hw,
                feat_name=f"Keyway-{n}",
            )
            if ok:
                logger.success(f"  [OK] Keyway-{n}")
            else:
                logger.error(f"  [FAIL] Keyway-{n}: FeatureCut4 返回 None")
                all_ok = False

        return all_ok

    # ------------------------------------------------------------------
    # 以下为旧版方法（不再由 build() 调用，保留作为参考/手动使用）
    # ------------------------------------------------------------------

    def _create_end_chamfers(
        self,
        left_x: float,
        left_r: float,
        right_x: float,
        right_r: float,
        chamfer_mm: float,
    ) -> bool:
        """创建左右端面倒角。

        ⚠️ 边缘坐标使用 mm（SelectByID2 使用文档单位），
        倒角尺寸在 feature_chamfer_edge 内部转为米。
        """
        logger.info("--- 创建端面倒角 ---")
        ok1 = self._driver.feature_chamfer_edge(
            left_x, left_r, chamfer_mm, "Chamfer-LeftEnd"
        )
        ok2 = self._driver.feature_chamfer_edge(
            right_x, right_r, chamfer_mm, "Chamfer-RightEnd"
        )
        return ok1 and ok2

    # ------------------------------------------------------------------
    # 阶跃过渡圆角
    # ------------------------------------------------------------------

    def _create_step_fillets(
        self,
        sections: list[tuple[float, float, float]],
        fillet_r_mm: float,
    ) -> bool:
        """创建阶跃过渡圆角。

        ⚠️ 边缘坐标使用 mm（SelectByID2 使用文档单位），
        圆角半径在 feature_fillet_edges 内部转为米。
        """
        logger.info("--- 创建过渡圆角 ---")
        edge_specs = []
        for i in range(len(sections) - 1):
            mid = (sections[i][1] + sections[i + 1][0]) / 2.0
            r_big = max(sections[i][2], sections[i + 1][2])
            edge_specs.append((mid, r_big))
            logger.debug(f"  阶跃 {i+1}: X={mid:.1f}, R={r_big:.1f}")

        return self._driver.feature_fillet_edges(
            edge_specs, fillet_r_mm, "Fillet-Transitions"
        )

    # ------------------------------------------------------------------
    # 键槽
    # ------------------------------------------------------------------

    def _create_keyways(
        self,
        keyways: list[tuple[float, float, float, float, float]],
    ) -> bool:
        """自动创建键槽切除。

        策略（按优先级尝试）:
          1. VBScript 直接 COM（与 VBA 同源 OLE 引擎，FeatureCut3 可用）
          2. VBScript 调用 VBA 宏（RunMacro）
          3. PowerShell COM interop
          4. 手动运行 VBA 宏

        正确 CAD 建模方式：
          1. 创建与柱面相切的参考面（上视基准面偏移 shaft_radius）
          2. 在参考面上绘制键槽轮廓（矩形）
          3. FeatureCut3(Flip=True) 向轴心方向拉伸切除
        """
        logger.info("--- 键槽切除（相切参考面 + 自动执行）---")
        if not keyways:
            logger.info("  无键槽参数，跳过")
            return True

        import os
        from pathlib import Path

        project_root = Path(os.path.dirname(os.path.abspath(__file__))).parent.parent.parent
        macro_dir = project_root / "CAD"
        macro_path = macro_dir / "KeywayCut.bas"

        # 保存 VBA 宏作为兜底方案
        vba = self._generate_keyway_cut_vba(keyways)
        macro_path.write_text(vba, encoding="gbk", errors="replace")
        logger.info(f"  VBA 宏（兜底）: {macro_path}")

        # --- 自动执行 ---
        import time
        success = self._try_vbscript_direct_com(keyways)
        if not success:
            success = self._try_vbscript_run_macro(macro_path)
        if not success:
            success = self._try_powershell_run_macro(macro_path)

        if success:
            # RunMacro 在 SW2025 中可能是异步的，等待 VBA 完成
            logger.info("  等待 VBA 宏完成 (5s)...")
            time.sleep(5)
            try:
                self._driver.sw_model.ForceRebuild3(True)
                self._driver.sw_model.ViewZoomtofit2()
            except Exception:
                pass
            logger.success("  键槽切除已完成！")
        else:
            logger.warning(
                "  自动执行失败，请在 SW 中手动运行: "
                "工具→宏→运行→选择 CAD/KeywayCut.bas"
            )
        return success

    # ------------------------------------------------------------------
    # 方法 1: VBScript 直接 COM（最优方案）
    # ------------------------------------------------------------------

    def _try_vbscript_direct_com(self, keyways) -> bool:
        """VBScript 直接通过 COM 创建键槽（不使用 VBA 中间层）。

        VBScript 与 VBA 使用相同的 OLE Automation COM 引擎，
        FeatureCut3 在 VBScript 中应该可用（不像 Python COM 那样受限）。
        """
        import subprocess
        from pathlib import Path
        import tempfile
        logger.info("  方法1: VBScript 直接 COM 创建键槽...")

        vbs_code = self._generate_keyway_vbscript(keyways)
        vbs_path = Path(tempfile.gettempdir()) / "sw_keyway_cut.vbs"
        vbs_path.write_text(vbs_code, encoding="utf-8")
        logger.debug(f"  VBScript: {vbs_path}")

        try:
            result = subprocess.run(
                ["cscript", "//Nologo", str(vbs_path)],
                capture_output=True, text=True, timeout=60,
            )
            stdout = result.stdout.strip()
            stderr = result.stderr.strip()
            logger.debug(f"  stdout: {stdout}")
            if stderr:
                logger.debug(f"  stderr: {stderr}")
            if result.returncode == 0 and "OK" in stdout:
                logger.success("  [OK] VBScript 直接 COM 成功")
                return True
            else:
                logger.warning(f"  VBScript COM 失败: {stdout} {stderr}")
                return False
        except subprocess.TimeoutExpired:
            logger.warning("  VBScript COM 超时（可能是 SW 弹窗阻塞）")
            return False
        except FileNotFoundError:
            logger.warning("  cscript.exe 未找到")
            return False
        except Exception as e:
            logger.warning(f"  VBScript COM 异常: {e}")
            return False

    def _generate_keyway_vbscript(self, keyways) -> str:
        """生成直接创建键槽的 VBScript 代码。

        与 VBA 宏等效，但通过 cscript.exe 执行，使用原生 OLE COM。
        """
        lines = []
        lines.append("' KeywayCut.vbs - Direct COM keyway creation")
        lines.append("' Uses VBScript OLE Automation (same engine as VBA)")
        lines.append("Option Explicit")
        lines.append("")
        lines.append("Dim swApp, swModel, swFeatMgr, swSketchMgr, swFeat")
        lines.append("Dim x1, x2, y, hw, zNeg, zPos, depthM")
        lines.append("Dim result")
        lines.append("")
        lines.append("' --- Connect to SolidWorks ---")
        lines.append("On Error Resume Next")
        lines.append("Set swApp = GetObject(, \"SldWorks.Application\")")
        lines.append("If Err.Number <> 0 Then")
        lines.append("    WScript.Echo \"ERR: Cannot connect to SolidWorks. Is it running?\"")
        lines.append("    WScript.Quit 1")
        lines.append("End If")
        lines.append("On Error GoTo 0")
        lines.append("")
        lines.append("Set swModel = swApp.ActiveDoc")
        lines.append("If swModel Is Nothing Then")
        lines.append("    WScript.Echo \"ERR: No active document in SolidWorks\"")
        lines.append("    WScript.Quit 1")
        lines.append("End If")
        lines.append("")
        lines.append("Set swFeatMgr = swModel.FeatureManager")
        lines.append("Set swSketchMgr = swModel.SketchManager")
        lines.append("")

        for i, (xs, xe, w, d, sr) in enumerate(keyways):
            cx = (xs + xe) / 2.0
            length = xe - xs
            hw = w / 2.0
            n = i + 1
            x1_val = round(cx - length / 2.0, 6)
            x2_val = round(cx + length / 2.0, 6)
            offset_m = sr / 1000.0
            depth_m = d / 1000.0

            lines.append(f"' ==========================================")
            lines.append(f"' Keyway {n}: Xc={cx:.2f} L={length:.0f} W={w:.0f} D={d:.0f} R={sr:.0f}")
            lines.append(f"' ==========================================")
            lines.append("")
            lines.append(f"' --- Step 1: Create tangent reference plane ---")
            lines.append("swModel.ClearSelection2 True")
            lines.append("swModel.Extension.SelectByID2 \"上视基准面\", \"PLANE\", 0, 0, 0, True, 0, Nothing, 0")
            lines.append(f"Set swFeat = swFeatMgr.InsertRefPlane(8, {offset_m}, 0, 0, 0, 0)")
            lines.append("If swFeat Is Nothing Then")
            lines.append(f"    WScript.Echo \"ERR: InsertRefPlane failed for Keyway {n}\"")
            lines.append("    WScript.Quit 1")
            lines.append("End If")
            lines.append(f"swFeat.Name = \"KeywayPlane-{n}\"")
            lines.append("")
            lines.append(f"' --- Step 2: Sketch keyway profile ---")
            lines.append("swModel.ClearSelection2 True")
            lines.append(f"swModel.Extension.SelectByID2 \"KeywayPlane-{n}\", \"PLANE\", 0, 0, 0, True, 0, Nothing, 0")
            lines.append("swModel.InsertSketch2 True")
            lines.append("")
            lines.append(f"x1 = {x1_val}")
            lines.append(f"x2 = {x2_val}")
            lines.append(f"y = {sr}")
            lines.append(f"hw = {hw}")
            lines.append("zNeg = -hw")
            lines.append("zPos = hw")
            lines.append("")
            lines.append("' Rectangle profile (counter-clockwise)")
            lines.append("swSketchMgr.CreateLine x1, y, zNeg, x2, y, zNeg  ' P1->P2 bottom")
            lines.append("swSketchMgr.CreateLine x2, y, zNeg, x2, y, zPos  ' P2->P3 right")
            lines.append("swSketchMgr.CreateLine x2, y, zPos, x1, y, zPos  ' P3->P4 top")
            lines.append("swSketchMgr.CreateLine x1, y, zPos, x1, y, zNeg  ' P4->P1 left")
            lines.append("")
            lines.append(f"' --- Step 3: Cut extrude (Flip=True toward shaft center) ---")
            lines.append(f"depthM = {depth_m}")
            lines.append(f"Set swFeat = swFeatMgr.FeatureCut3( True, True, False, False, 0, depthM, False, 0, 0, False, False, 0, 0, False, False, False, False, False, True, True, True, False, 0, True, True, True )")
            lines.append("If swFeat Is Nothing Then")
            lines.append(f"    WScript.Echo \"ERR: FeatureCut3 failed for Keyway {n} (VBScript COM has same limitation as Python)\"")
            lines.append("    WScript.Quit 1")
            lines.append("End If")
            lines.append(f"swFeat.Name = \"Keyway-{n}\"")
            lines.append("")

        lines.append("' --- Done ---")
        lines.append("swModel.ForceRebuild3 False")
        lines.append("swModel.ViewZoomtofit2")
        lines.append("WScript.Echo \"OK\"")
        lines.append("")

        return "\r\n".join(lines)

    # ------------------------------------------------------------------
    # 方法 2: VBScript 调用 VBA 宏
    # ------------------------------------------------------------------

    def _try_vbscript_run_macro(self, macro_path) -> bool:
        """通过 VBScript 调用 SW RunMacro 执行 .bas 文件。"""
        import subprocess
        logger.info("  方法2: VBScript 调用 VBA 宏...")

        vbs_code = (
            'On Error Resume Next\r\n'
            'Dim swApp\r\n'
            'Set swApp = GetObject(, "SldWorks.Application")\r\n'
            'If Err.Number <> 0 Then\r\n'
            '    WScript.Echo "ERR: Cannot connect to SolidWorks"\r\n'
            '    WScript.Quit 1\r\n'
            'End If\r\n'
            f'swApp.RunMacro "{macro_path}", "main", 0\r\n'
            'If Err.Number <> 0 Then\r\n'
            '    WScript.Echo "ERR: " & Err.Description\r\n'
            '    WScript.Quit 1\r\n'
            'End If\r\n'
            'WScript.Echo "OK"\r\n'
        )

        vbs_path = macro_path.with_suffix('.vbs')
        vbs_path.write_text(vbs_code, encoding="utf-8")
        logger.debug(f"  VBScript: {vbs_path}")

        try:
            result = subprocess.run(
                ["cscript", "//Nologo", str(vbs_path)],
                capture_output=True, text=True, timeout=30,
            )
            vbs_path.unlink(missing_ok=True)
            stdout = result.stdout.strip()
            if result.returncode == 0 and "OK" in stdout:
                logger.success("  [OK] VBScript RunMacro 成功")
                return True
            else:
                logger.warning(f"  VBScript RunMacro 失败: {stdout}")
                return False
        except subprocess.TimeoutExpired:
            logger.warning("  VBScript RunMacro 超时")
            return False
        except Exception as e:
            logger.warning(f"  VBScript RunMacro 异常: {e}")
            return False

    # ------------------------------------------------------------------
    # 方法 3: PowerShell COM interop
    # ------------------------------------------------------------------

    def _try_powershell_run_macro(self, macro_path) -> bool:
        """通过 PowerShell 调用 COM RunMacro。"""
        import subprocess
        logger.info("  方法3: PowerShell COM interop...")

        ps_cmd = (
            'powershell -NoProfile -NonInteractive -Command "'
            f'$macroPath = \'{macro_path}\'; '
            'try {{ '
            '$sw = [System.Runtime.InteropServices.Marshal]::GetActiveObject'
            '(\'SldWorks.Application\'); '
            '$sw.RunMacro($macroPath, \'main\', 0) | Out-Null; '
            'Write-Output \'OK\' '
            '}} catch {{ '
            'Write-Output \\"ERR: $($_.Exception.Message)\\" '
            '}}"'
        )

        try:
            result = subprocess.run(
                ps_cmd, capture_output=True, text=True, timeout=30, shell=True,
            )
            stdout = result.stdout.strip()
            if "OK" in stdout and "ERR" not in stdout:
                logger.success("  [OK] PowerShell 成功")
                return True
            else:
                logger.warning(f"  PowerShell 失败: {stdout}")
                return False
        except Exception as e:
            logger.warning(f"  PowerShell 异常: {e}")
            return False

    # ------------------------------------------------------------------
    # VBA 宏生成
    # ------------------------------------------------------------------

    def _generate_keyway_cut_vba(
        self,
        keyways: list[tuple[float, float, float, float, float]],
    ) -> str:
        """生成完整的键槽切除 VBA 宏代码。

        每个键槽:
          1. 从上视基准面偏移 shaft_radius 创建相切参考面
          2. 在参考面上绘制键槽轮廓（矩形 + 端部半圆弧）
          3. 调用 FeatureCut3 向轴心切除

        Args:
            keyways: 键槽列表 [(x_start, x_end, width, depth, shaft_r), ...]

        Returns:
            str: VBA 宏代码（.bas 文件内容）。
        """
        # 计算参数
        kw_params = []
        for i, (xs, xe, w, d, sr) in enumerate(keyways):
            cx = (xs + xe) / 2.0
            length = xe - xs
            kw_params.append({
                'n': i + 1,
                'cx': cx,
                'length': length,
                'width': w,
                'depth': d,
                'shaft_r': sr,
                'hw': w / 2.0,
            })

        lines = []
        lines.append("Option Explicit")
        lines.append("")
        lines.append("' KeywayCut.bas — 键槽切除宏")
        lines.append("' 使用相切参考面 + 拉伸切除的正确 CAD 建模方式")
        lines.append("' 由 ShaftBuilder 自动生成")
        lines.append("")
        lines.append("Sub main()")
        lines.append("    Dim swApp As Object")
        lines.append("    Dim swModel As Object")
        lines.append("    Dim swFeatMgr As Object")
        lines.append("    Dim swSketchMgr As Object")
        lines.append("    Dim swFeat As Object")
        lines.append("    Dim x1 As Double, x2 As Double, y As Double")
        lines.append("    Dim hw As Double, zNeg As Double, zPos As Double")
        lines.append("    Dim depthM As Double")
        lines.append("")
        lines.append("    Set swApp = Application.SldWorks")
        lines.append("    Set swModel = swApp.ActiveDoc")
        lines.append("    If swModel Is Nothing Then")
        lines.append("        MsgBox \"No active document!\", vbCritical")
        lines.append("        Exit Sub")
        lines.append("    End If")
        lines.append("    Set swFeatMgr = swModel.FeatureManager")
        lines.append("    Set swSketchMgr = swModel.SketchManager")
        lines.append("")

        for kw in kw_params:
            n = kw['n']
            lines.append(f"    ' ============================================")
            lines.append(f"    ' Keyway {n}: Xc={kw['cx']:.2f}, L={kw['length']:.0f}, "
                         f"W={kw['width']:.0f}, D={kw['depth']:.0f}, R={kw['shaft_r']:.0f}")
            lines.append(f"    ' ============================================")
            lines.append(f"")
            lines.append(f"    ' --- Step 1: 创建相切参考面（从上视基准面偏移 shaft_radius）---")
            lines.append(f"    swModel.ClearSelection2 True")
            lines.append(f"    swModel.Extension.SelectByID2 \"上视基准面\", \"PLANE\", 0, 0, 0, True, 0, Nothing, 0")
            lines.append(f"    Set swFeat = swFeatMgr.InsertRefPlane(8, {kw['shaft_r'] / 1000.0}#, 0, 0, 0, 0)")
            lines.append(f"    If swFeat Is Nothing Then")
            lines.append(f"        MsgBox \"Failed to create reference plane for Keyway {n}!\", vbCritical")
            lines.append(f"        Exit Sub")
            lines.append(f"    End If")
            lines.append(f"    swFeat.Name = \"KeywayPlane-{n}\"")
            lines.append(f"")
            lines.append(f"    ' --- Step 2: 在参考面上绘制键槽轮廓 ---")
            lines.append(f"    ' 参考面位于 Y=shaft_r，平行于 XZ 平面")
            lines.append(f"    ' 键槽轮廓：矩形 （x1~x2）×（zNeg~zPos）")
            lines.append(f"    swModel.ClearSelection2 True")
            lines.append(f"    swModel.Extension.SelectByID2 \"KeywayPlane-{n}\", \"PLANE\", 0, 0, 0, True, 0, Nothing, 0")
            lines.append(f"    swModel.InsertSketch2 True")
            lines.append(f"")
            lines.append(f"    x1 = {round(kw['cx'] - kw['length'] / 2.0, 6)}#")
            lines.append(f"    x2 = {round(kw['cx'] + kw['length'] / 2.0, 6)}#")
            lines.append(f"    y = {round(kw['shaft_r'], 6)}#")
            lines.append(f"    hw = {round(kw['hw'], 6)}#")
            lines.append(f"    zNeg = -hw")
            lines.append(f"    zPos = hw")
            lines.append(f"")
            lines.append(f"    ' 矩形轮廓（逆时针闭合）")
            lines.append(f"    swSketchMgr.CreateLine x1, y, zNeg, x2, y, zNeg  ' P1→P2 底边")
            lines.append(f"    swSketchMgr.CreateLine x2, y, zNeg, x2, y, zPos  ' P2→P3 右边")
            lines.append(f"    swSketchMgr.CreateLine x2, y, zPos, x1, y, zPos  ' P3→P4 顶边")
            lines.append(f"    swSketchMgr.CreateLine x1, y, zPos, x1, y, zNeg  ' P4→P1 左边")
            lines.append(f"")
            lines.append(f"    ' --- Step 3: 拉伸切除（向轴心方向 -Y，Flip=True）---")
            lines.append(f"    depthM = {kw['depth'] / 1000.0}#")
            lines.append(f"    ' FeatureCut3(Sd=True,Flip=True 翻转向-Y切除,Dir=False,T1Both=False,T1=0=Blind,D1=depth,...)")
            lines.append(f"    Set swFeat = swFeatMgr.FeatureCut3( True, True, False, False, 0, depthM, False, 0, 0, False, False, 0, 0, False, False, False, False, False, True, True, True, False, 0, True, True, True )")
            lines.append(f"    If swFeat Is Nothing Then")
            lines.append(f"        MsgBox \"FeatureCut3 failed for Keyway {n}!\", vbCritical")
            lines.append(f"        Exit Sub")
            lines.append(f"    End If")
            lines.append(f"    swFeat.Name = \"Keyway-{n}\"")
            lines.append(f"")

        lines.append("    ' --- 完成（成功时不弹窗，避免阻塞自动化）---")
        lines.append("    swModel.ForceRebuild3 False")
        lines.append("    swModel.ViewZoomtofit2")
        lines.append(f"    swModel.SetStatusBarText \"KeywayCut: {len(kw_params)} keyway(s) created\"")
        lines.append("End Sub")
        lines.append("")

        return "\r\n".join(lines)
