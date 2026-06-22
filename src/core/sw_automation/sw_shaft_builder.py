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
        fillet_r_mm: float = DEFAULT_FILLET_R_MM,
        progress_callback: Callable[[str, int], None] | None = None,
    ) -> bool:
        """完整的阶梯轴建模流程。

        Python COM 只创建旋转基体（最可靠），倒角、圆角、键槽
        全部通过 VBA 巨集在 SW 进程内完成（避免外部 COM 限制）。
        """
        if sections is None:
            sections = DEFAULT_SECTIONS
        if keyways is None:
            keyways = DEFAULT_KEYWAYS

        steps = [
            ("旋转基体", 0, 20, lambda: self.create_shaft_body(sections)),
            ("VBA 巨集（倒角+圆角+键槽）", 20, 100,
             lambda: self._create_all_features_vba(sections, keyways, chamfer_mm, fillet_r_mm)),
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
        chamfer_mm: float,
        fillet_r_mm: float,
    ) -> bool:
        """生成综合 VBA 巨集并自动执行。

        倒角、圆角、键槽全部在 SW 进程内通过 VBA 完成，
        避免 Python COM 外部调用的 FeatureCut3=None 等问题。
        所有坐标统一使用米（MKS 文档单位）。
        """
        import os
        import subprocess
        import time
        from pathlib import Path

        logger.info("--- VBA 巨集（倒角 + 圆角 + 键槽）---")

        project_root = Path(os.path.dirname(os.path.abspath(__file__))).parent.parent.parent
        macro_dir = project_root / "CAD"
        macro_path = macro_dir / "PostRevolve.bas"

        vba = self._generate_post_revolve_vba(sections, keyways, chamfer_mm, fillet_r_mm)
        macro_path.write_text(vba, encoding="gbk", errors="replace")
        logger.info(f"  VBA 巨集已生成: {macro_path} ({len(vba)} 字节)")

        # 通过 VBScript 调用 RunMacro
        vbs_code = (
            'On Error Resume Next\r\n'
            'Dim swApp\r\n'
            'Set swApp = GetObject(, "SldWorks.Application")\r\n'
            'If Err.Number <> 0 Then\r\n'
            '    WScript.Echo "ERR: Cannot connect to SW"\r\n'
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
        vbs_path.write_text(vbs_code, encoding="gbk")

        try:
            result = subprocess.run(
                ["cscript", "//Nologo", str(vbs_path)],
                capture_output=True, text=True, timeout=60,
            )
            stdout = result.stdout.strip()
            logger.debug(f"  cscript: {stdout}")

            if result.returncode == 0 and "OK" in stdout:
                time.sleep(5)  # 等待 SW 内 VBA 完成
                try:
                    self._driver.sw_model.ForceRebuild3(True)
                    self._driver.sw_model.ViewZoomtofit2()
                except Exception:
                    pass
                logger.success("  [OK] VBA 巨集执行成功！")
                return True
            else:
                logger.warning(f"  VBA 巨集执行失败: {stdout}")
                logger.warning(f"  请在 SW 中手动运行: 工具→宏→运行→{macro_path}")
                return False
        except subprocess.TimeoutExpired:
            logger.warning("  VBA 巨集超时（可能是 SW 弹窗，请关闭弹窗后手动运行宏）")
            return False
        except Exception as e:
            logger.warning(f"  VBA 巨集异常: {e}")
            return False

    def _generate_post_revolve_vba(
        self,
        sections: list[tuple[float, float, float]],
        keyways: list[tuple[float, float, float, float, float]],
        chamfer_mm: float,
        fillet_r_mm: float,
    ) -> str:
        """生成完整 VBA 巨集：倒角 + 圆角 + 键槽。

        关键：所有坐标使用米（MKS 文档单位），mm 值 / 1000。
        Python COM 中 _to_doc() 在 MKS 下也除 1000，保持一致。
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
        lines.append("    Dim xv As Double, yv As Double, nSel As Long")
        lines.append("    Dim x1 As Double, x2 As Double, y As Double")
        lines.append("    Dim hw As Double, zNeg As Double, zPos As Double, dM As Double")
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
        # 1. 端面倒角
        # ============================================================
        left_x = sections[0][0]
        left_r = sections[0][2]
        right_x = sections[-1][1]
        right_r = sections[-1][2]

        lines.append("    ' ============================================")
        lines.append("    ' 端面倒角 C" + str(chamfer_mm))
        lines.append("    ' ============================================")
        lines.append("")

        for name, ex, er in [("LeftEnd", left_x, left_r), ("RightEnd", right_x, right_r)]:
            lines.append(f"    ' Chamfer-{name}")
            lines.append("    swModel.ClearSelection2 True")
            # SelectByID2 用米; Z=0.001m 偏移避开圆柱面
            lines.append(f"    swModel.Extension.SelectByID2 \"\", \"Edge\", "
                         f"{m(ex)}, {m(er)}, 0.001, True, 0, Nothing, 0")
            lines.append("    nSel = swSelMgr.GetSelectedObjectCount2(-1)")
            lines.append("    If nSel > 0 Then")
            lines.append(f"        Set swFeat = swFeatMgr.InsertFeatureChamfer(")
            lines.append(f"            1, 1, 0.785, {chamfer_m}#, 0, 0, 0, False)")
            lines.append(f"        If Not swFeat Is Nothing Then swFeat.Name = \"Chamfer-{name}\"")
            lines.append("    End If")
            lines.append("")

        # ============================================================
        # 2. 阶跃过渡圆角
        # ============================================================
        lines.append("    ' ============================================")
        lines.append("    ' 阶跃过渡圆角 R" + str(fillet_r_mm))
        lines.append("    ' ============================================")
        lines.append("    swModel.ClearSelection2 True")

        for i in range(len(sections) - 1):
            mid = (sections[i][1] + sections[i + 1][0]) / 2.0
            r_big = max(sections[i][2], sections[i + 1][2])
            lines.append(f"    ' Step {i+1}: X={m(mid)}, R={m(r_big)}")
            lines.append(f"    swModel.Extension.SelectByID2 \"\", \"Edge\", "
                         f"{m(mid)}, {m(r_big)}, 0.001, True, 1, Nothing, 0")

        lines.append("    nSel = swSelMgr.GetSelectedObjectCount2(-1)")
        lines.append("    If nSel > 0 Then")
        lines.append(f"        Set swFeat = swFeatMgr.FeatureFillet3(")
        lines.append(f"            195, {fillet_m}#, 0, 0, False, 0, False, False)")
        lines.append("        If Not swFeat Is Nothing Then swFeat.Name = \"Fillet-Transitions\"")
        lines.append("    End If")
        lines.append("")

        # ============================================================
        # 3. 键槽（相切参考面 + 拉伸切除）
        # ============================================================
        if keyways:
            lines.append("    ' ============================================")
            lines.append("    ' 键槽")
            lines.append("    ' ============================================")
            lines.append("")

        for kw_idx, (xs, xe, w, d, sr) in enumerate(keyways):
            n = kw_idx + 1
            cx = (xs + xe) / 2.0
            length = xe - xs
            hw_val = w / 2.0
            offset_m = sr / 1000.0
            depth_m = d / 1000.0

            lines.append(f"    ' Keyway {n}: Xc={cx:.2f}mm L={length:.0f}mm W={w:.0f}mm D={d:.0f}mm R={sr:.0f}mm")
            lines.append("")
            lines.append(f"    ' Step 1: 相切参考面（上视基准面偏移 R）")
            lines.append("    swModel.ClearSelection2 True")
            lines.append("    swModel.Extension.SelectByID2 \"上视基准面\", \"PLANE\", 0, 0, 0, True, 0, Nothing, 0")
            lines.append(f"    Set swFeat = swFeatMgr.InsertRefPlane(8, {offset_m}#, 0, 0, 0, 0)")
            lines.append(f"    If Not swFeat Is Nothing Then swFeat.Name = \"KeywayPlane-{n}\"")
            lines.append("")
            lines.append(f"    ' Step 2: 键槽轮廓（XZ 平面，Y=shaft_r）")
            lines.append("    swModel.ClearSelection2 True")
            lines.append(f"    swModel.Extension.SelectByID2 \"KeywayPlane-{n}\", \"PLANE\", 0, 0, 0, True, 0, Nothing, 0")
            lines.append("    swModel.InsertSketch2 True")
            lines.append(f"    x1 = {m(round(cx - length / 2.0, 6))}#")
            lines.append(f"    x2 = {m(round(cx + length / 2.0, 6))}#")
            lines.append(f"    y  = {m(sr)}#")
            lines.append(f"    hw = {m(hw_val)}#")
            lines.append("    zNeg = -hw : zPos = hw")
            lines.append("    swSketchMgr.CreateLine x1, y, zNeg, x2, y, zNeg")
            lines.append("    swSketchMgr.CreateLine x2, y, zNeg, x2, y, zPos")
            lines.append("    swSketchMgr.CreateLine x2, y, zPos, x1, y, zPos")
            lines.append("    swSketchMgr.CreateLine x1, y, zPos, x1, y, zNeg")
            lines.append("")
            lines.append(f"    ' Step 3: 拉伸切除（Flip=True 向 -Y 轴心）")
            lines.append(f"    dM = {depth_m}#")
            lines.append("    Set swFeat = swFeatMgr.FeatureCut3( True, True, False, False, 0, dM, False, 0, 0, False, False, 0, 0, False, False, False, False, False, True, True, True, False, 0, True, True, True )")
            lines.append(f"    If Not swFeat Is Nothing Then swFeat.Name = \"Keyway-{n}\"")
            lines.append("")

        lines.append("    ' --- 完成 ---")
        lines.append("    swModel.ForceRebuild3 False")
        lines.append("    swModel.ViewZoomtofit2")
        lines.append("End Sub")
        lines.append("")

        return "\r\n".join(lines)

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
        vbs_path.write_text(vbs_code, encoding="gbk")
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
        vbs_path.write_text(vbs_code, encoding="gbk")
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
