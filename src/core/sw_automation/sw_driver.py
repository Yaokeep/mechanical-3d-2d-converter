# SolidWorks 2025 COM 驱动封装
#
# 使用 pywin32 (win32com.client) 直接驱动 SW 2025，替代 VBA 宏。
# 相较于 VBA 宏的优势：
#   - 无需启用宏安全设置
#   - Python 异常处理，调试更方便
#   - 可参数化驱动，可集成到主应用
#
# 所有 API 参数使用 米（meters），调用方负责 mm→m 转换。

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

try:
    from loguru import logger
except ImportError:
    # 回退到标准库 logging
    import logging
    logger = logging.getLogger("sw_automation")

from .sw_constants import (
    swDocPART,
    swEndCondBlind,
    swStartSketchPlane,
    swRefPlaneOffset,
    SW_FILLET_OPTIONS,
    swSaveAsCurrentVersion,
    swSaveAsOptions_Silent,
    SW_USER_PREF_UNIT_SYSTEM,
    swMMGS,
)


# ---------------------------------------------------------------------------
# 自定义异常
# ---------------------------------------------------------------------------

class SwError(Exception):
    """SolidWorks 自动化基础异常。"""
    pass


class SwConnectionError(SwError):
    """无法连接 SolidWorks。"""
    pass


class SwFeatureError(SwError):
    """特征创建失败。"""
    pass


# ---------------------------------------------------------------------------
# SolidWorksDriver
# ---------------------------------------------------------------------------

class SolidWorksDriver:
    """SolidWorks 2025 COM 驱动封装。

    封装常用操作：连接/断开、文档创建、草图绘制、
    选择、特征（旋转、拉伸、倒角、圆角、切除）等。

    使用示例::

        driver = SolidWorksDriver(visible=True)
        if driver.connect():
            driver.new_part()
            driver.start_sketch("Front Plane")
            driver.draw_line(0, 0, 0, 0.05, 0.01, 0)
            driver.feature_revolve(360.0)
            driver.disconnect()
    """

    def __init__(self, visible: bool = True, timeout: float = 30.0):
        """初始化驱动。

        Args:
            visible: SolidWorks 窗口是否可见。
            timeout: 等待 SW 启动的超时秒数（暂未使用）。
        """
        self.visible = visible
        self.timeout = timeout
        self.sw_app: Any = None
        self.sw_model: Any = None
        self.sw_part: Any = None
        self.sw_feat_mgr: Any = None
        self.sw_sketch_mgr: Any = None

    # ------------------------------------------------------------------
    # 连接管理
    # ------------------------------------------------------------------

    def connect(self) -> bool:
        """连接到 SolidWorks 2025 COM 实例。

        Returns:
            bool: 连接成功返回 True，否则 False。
        """
        logger.info("正在连接 SolidWorks 2025 ...")
        try:
            import pythoncom
            import win32com.client

            pythoncom.CoInitialize()
            self.sw_app = win32com.client.Dispatch("SldWorks.Application")
        except ImportError as e:
            logger.error("缺少 pywin32 依赖，请运行: pip install pywin32")
            raise SwConnectionError(f"pywin32 未安装: {e}") from e
        except Exception:
            logger.warning("未找到运行中的 SolidWorks，尝试启动 ...")
            try:
                import pythoncom
                import win32com.client

                pythoncom.CoInitialize()
                self.sw_app = win32com.client.Dispatch("SldWorks.Application")
            except Exception as e:
                logger.error(f"无法连接 SolidWorks: {e}")
                raise SwConnectionError(
                    "无法连接 SolidWorks 2025。请确认:\n"
                    "  1. SolidWorks 2025 已安装\n"
                    "  2. 以管理员身份运行过一次 SW\n"
                    "  3. SW COM 组件已注册"
                ) from e

        if self.sw_app is None:
            logger.error("SolidWorks COM 对象为 None")
            return False

        self.sw_app.Visible = self.visible
        revision = self.sw_app.RevisionNumber
        logger.success(f"已连接 SolidWorks 2025 (版本 {revision})")
        return True

    def disconnect(self) -> None:
        """断开 COM 连接，释放引用。"""
        self.sw_model = None
        self.sw_part = None
        self.sw_feat_mgr = None
        self.sw_sketch_mgr = None
        self.sw_app = None
        logger.info("已断开 SolidWorks COM 连接")

    # ------------------------------------------------------------------
    # 文档操作
    # ------------------------------------------------------------------

    def new_part(self) -> bool:
        """创建新零件文档（MMGS 单位系统）。

        Returns:
            bool: 创建成功返回 True。
        """
        logger.info("创建新零件文档 ...")
        try:
            template = self.sw_app.GetDocumentTemplate(swDocPART, "", 0, 0, 0)
            self.sw_part = self.sw_app.NewDocument(template, 0, 0, 0)
            if self.sw_part is None:
                logger.error("无法创建新零件")
                return False
            self.sw_model = self.sw_part
            self.sw_feat_mgr = self.sw_model.FeatureManager
            self.sw_sketch_mgr = self.sw_model.SketchManager
            # 设置 MMGS 单位系统
            self.sw_model.SetUserPreferenceIntegerValue(
                SW_USER_PREF_UNIT_SYSTEM, swMMGS
            )
            self.sw_model.ShowNamedView2("*Isometric", -1)
            logger.success("新零件已创建 (MMGS 单位)")
            return True
        except Exception as e:
            logger.error(f"创建零件异常: {e}")
            return False

    def rebuild(self) -> None:
        """强制重建模型（Ctrl+Q）。"""
        if self.sw_model:
            self.sw_model.ForceRebuild3(False)

    def zoom_to_fit(self) -> None:
        """缩放到适应窗口。"""
        if self.sw_model:
            self.sw_model.ViewZoomtofit2()

    def save_as(self, filepath: str | Path) -> bool:
        """另存为 SLDPRT 文件。

        Args:
            filepath: 保存路径（.sldprt）。

        Returns:
            bool: 保存成功返回 True。
        """
        if self.sw_model is None:
            logger.error("无活动文档，无法保存")
            return False
        path = str(Path(filepath).absolute())
        logger.info(f"正在保存: {path}")
        try:
            self.sw_model.Extension.SaveAs(
                path, swSaveAsCurrentVersion, 0, None, "", swSaveAsOptions_Silent, 0
            )
            logger.success(f"已保存: {path}")
            return True
        except Exception as e:
            logger.error(f"保存失败: {e}")
            return False

    # ------------------------------------------------------------------
    # 单位转换（静态方法）
    # ------------------------------------------------------------------

    @staticmethod
    def mm_to_m(mm_val: float) -> float:
        """毫米 → 米（SW API 使用的单位）。"""
        return mm_val / 1000.0

    @staticmethod
    def deg_to_rad(deg_val: float) -> float:
        """度 → 弧度。"""
        return deg_val * math.pi / 180.0

    # ------------------------------------------------------------------
    # 选择操作
    # ------------------------------------------------------------------

    def clear_selection(self) -> None:
        """清除所有选择。"""
        if self.sw_model:
            self.sw_model.ClearSelection2(True)

    def selection_count(self) -> int:
        """获取当前选中对象数量。"""
        if self.sw_model:
            return self.sw_model.Extension.GetSelectionCount
        return 0

    def select_plane(self, name: str) -> bool:
        """按名称选择基准面。

        Args:
            name: 基准面名称，如 "Front Plane", "Top Plane", "Right Plane"。

        Returns:
            bool: 选择成功返回 True。
        """
        if self.sw_model is None:
            return False
        self.clear_selection()
        result = self.sw_model.Extension.SelectByID2(
            name, "PLANE", 0.0, 0.0, 0.0, False, 0, None, 0
        )
        return bool(result)

    def select_edge_by_point(
        self,
        x: float,
        y: float,
        z: float = 0.003,
    ) -> int:
        """用点选 + Z 偏移选中边缘（V45 验证可用）。

        SW2025 不支持 SelectByRay (Err=438)，改用 SelectByID2。
        Z 偏移避开圆柱面，确保选中的是 EDGE 而非 FACE。

        Args:
            x, y: 棱边 XY 坐标（米）。
            z: Z 偏移（米），默认 0.003 避免打到面上。

        Returns:
            int: 当前选中对象总数。
        """
        if self.sw_model is None:
            return 0
        self.sw_model.Extension.SelectByID2(
            "", "EDGE", x, y, z, True, 0, None, 0
        )
        return self.selection_count()

    # ------------------------------------------------------------------
    # 草图操作
    # ------------------------------------------------------------------

    def start_sketch(self, plane_name: str = "Front Plane") -> bool:
        """在指定基准面上打开草图。

        Args:
            plane_name: 基准面名称。

        Returns:
            bool: 成功返回 True。
        """
        if not self.select_plane(plane_name):
            logger.warning(f"无法选择基准面: {plane_name}")
            return False
        if self.sw_sketch_mgr is None:
            logger.error("SketchManager 未初始化")
            return False
        self.sw_sketch_mgr.InsertSketch2(True)
        logger.debug(f"草图已打开: {plane_name}")
        return True

    def exit_sketch(self) -> None:
        """退出当前草图（调用 InsertSketch2 切换状态）。

        ⚠️ V45 验证规则: 特征方法必须在草图打开状态下调用！
        不要在调用 feature_revolve / feature_cut_extrude 等特征方法前
        调用此方法，否则特征会静默失败（返回 None）。
        """
        if self.sw_sketch_mgr:
            self.sw_sketch_mgr.InsertSketch2(True)

    def draw_line(
        self,
        x1: float, y1: float, z1: float,
        x2: float, y2: float, z2: float,
    ) -> None:
        """在活动草图中绘制直线（mm 坐标）。

        SW2025 已重命名 CreateLine2 → CreateLine。

        Args:
            x1, y1, z1: 起点坐标 (mm)。
            x2, y2, z2: 终点坐标 (mm)。
        """
        if self.sw_sketch_mgr:
            self.sw_sketch_mgr.CreateLine(x1, y1, z1, x2, y2, z2)

    def draw_centerline(
        self,
        x1: float, y1: float, z1: float,
        x2: float, y2: float, z2: float,
    ) -> None:
        """在活动草图中绘制中心线（mm 坐标）。

        SW2025 已重命名 CreateCenterLine2 → CreateCenterLine。
        中心线通常用作旋转特征的旋转轴。
        """
        if self.sw_sketch_mgr:
            self.sw_sketch_mgr.CreateCenterLine(x1, y1, z1, x2, y2, z2)

    # ------------------------------------------------------------------
    # 特征操作
    # ------------------------------------------------------------------

    def feature_revolve(
        self,
        angle_deg: float = 360.0,
        is_cut: bool = False,
        feat_name: str = "Revolve",
    ) -> bool:
        """创建旋转特征（凸台或切除）。

        使用 IFeatureManager.FeatureRevolve2 — SW 2024/2025/2026 统一 20 参数签名。

        Args:
            angle_deg: 旋转角度（度），默认 360°。
            is_cut: True 为旋转切除，False 为旋转凸台。
            feat_name: 特征名称。

        Returns:
            bool: 成功返回 True。
        """
        angle_rad = self.deg_to_rad(angle_deg)
        try:
            feat = self.sw_feat_mgr.FeatureRevolve2(
                True,           # SingleDir
                True,           # IsSolid
                False,          # IsThin
                is_cut,         # IsCut — True=切除, False=凸台
                False,          # ReverseDir
                False,          # BothDirectionUpToSameEntity
                swEndCondBlind, # Dir1Type
                0,              # Dir2Type
                angle_rad,      # Dir1Angle (弧度)
                0.0,            # Dir2Angle
                False,          # OffsetReverse1
                False,          # OffsetReverse2
                0.01,           # OffsetDistance1
                0.01,           # OffsetDistance2
                0,              # ThinType
                0.0,            # ThinThickness1
                0.0,            # ThinThickness2
                True,           # Merge
                True,           # UseFeatScope
                True,           # UseAutoSelect
            )
            if feat is None:
                logger.error(f"{feat_name}: FeatureRevolve2 返回 None")
                return False
            feat.Name = feat_name
            logger.success(f"  [OK] {feat_name} ({angle_deg}° 旋转)")
            return True
        except Exception as e:
            logger.error(f"{feat_name}: 旋转特征异常 - {e}")
            raise SwFeatureError(f"旋转特征创建失败: {e}") from e

    def feature_chamfer_edge(
        self,
        edge_x: float,
        edge_y: float,
        size_mm: float,
        feat_name: str = "Chamfer",
    ) -> bool:
        """在指定边创建 45° 倒角（V45 验证: Type=1 角度-距离模式）。

        Args:
            edge_x, edge_y: 边缘拾取位置（米）。
            size_mm: 倒角尺寸（mm）。
            feat_name: 特征名称。

        Returns:
            bool: 成功返回 True。
        """
        size_m = self.mm_to_m(size_mm)
        self.clear_selection()
        count = self.select_edge_by_point(edge_x, edge_y)
        if count == 0:
            logger.warning(f"{feat_name}: 未找到边缘 (X={edge_x}, Y={edge_y})")
            return False

        try:
            feat = self.sw_feat_mgr.InsertFeatureChamfer(
                1,                      # Options = 1 (V45 验证)
                1,                      # ChamferType = 1 (角度-距离)
                0.785,                  # Width = 45° (弧度)
                size_m,                 # OtherDist = 倒角距离 (米)
                0.0, 0.0, 0.0,         # Vertex 距离 (未使用)
                False,                  # 最后一个参数
            )
            if feat is None:
                logger.error(f"{feat_name}: InsertFeatureChamfer 返回 None")
                return False
            feat.Name = feat_name
            logger.success(f"  [OK] {feat_name} (C{size_mm})")
            return True
        except Exception as e:
            logger.error(f"{feat_name}: InsertFeatureChamfer 异常 - {e}")
            raise SwFeatureError(f"倒角创建失败: {e}") from e

    def feature_fillet_edges(
        self,
        edge_specs: list[tuple[float, float]],
        radius_mm: float,
        feat_name: str = "Fillet",
    ) -> bool:
        """选中多条边后创建等半径圆角（V45 验证: Options=195）。

        Args:
            edge_specs: [(x, y), ...] 每条边的点选位置（米）。
            radius_mm: 圆角半径（mm）。
            feat_name: 特征名称。

        Returns:
            bool: 成功返回 True。
        """
        radius_m = self.mm_to_m(radius_mm)
        self.clear_selection()
        for ex, ey in edge_specs:
            self.select_edge_by_point(ex, ey)

        total = self.selection_count()
        expected = len(edge_specs)
        logger.debug(f"  圆角选边: {total}/{expected}")
        if total < expected:
            logger.warning(f"  仅选中 {total} 条边 (预期 {expected})，继续尝试...")

        try:
            feat = self.sw_feat_mgr.FeatureFillet3(
                SW_FILLET_OPTIONS,      # Options = 195 (V45 验证唯一可用值)
                radius_m,               # Radius (米)
                0,                      # SetbackDist
                0,                      # SetbackType
                False,                  # TangentPropagation (V45: False)
                0,                      # OverflowType
                False, False,           # FeatureScope, AutoSelect (V45: False)
            )
            if feat is None:
                logger.error(f"{feat_name}: FeatureFillet3 返回 None")
                return False
            feat.Name = feat_name
            logger.success(f"  [OK] {feat_name} (R{radius_mm}, {total} 条边)")
            return True
        except Exception as e:
            logger.error(f"{feat_name}: FeatureFillet3 异常 - {e}")
            raise SwFeatureError(f"圆角创建失败: {e}") from e

    def create_ref_plane_offset(
        self,
        base_plane_name: str,
        offset_mm: float,
        plane_name: str,
    ) -> bool:
        """从已有基准面创建偏移参考基准面。

        ⚠️ V45 验证: InsertRefPlane 必须使用中文基准面名!
           "上视基准面" ✅  "Top Plane" ❌

        Args:
            base_plane_name: 源基准面名称，如 "上视基准面"。
            offset_mm: 偏移距离（mm，正值向+方向偏移）。
            plane_name: 新基准面名称。

        Returns:
            bool: 成功返回 True。
        """
        offset_m = self.mm_to_m(offset_mm)
        self.clear_selection()
        if not self.select_plane(base_plane_name):
            logger.error(f"无法选择基准面: {base_plane_name}")
            return False

        try:
            plane = self.sw_feat_mgr.InsertRefPlane(
                swRefPlaneOffset,   # 约束类型 = 偏移距离
                offset_m,           # 距离 (米)
                0, 0, 0, 0,
            )
            if plane is None:
                logger.error(f"InsertRefPlane 返回 None (偏移={offset_mm}mm)")
                return False
            plane.Name = plane_name
            logger.success(f"  基准面已创建: {plane_name} (偏移 +{offset_mm}mm)")
            return True
        except Exception as e:
            logger.error(f"创建基准面 {plane_name} 异常: {e}")
            return False

    def feature_cut_extrude(
        self,
        depth_mm: float,
        feat_name: str = "CutExtrude",
    ) -> bool:
        """在当前草图上创建拉伸切除（FeatureCut3, 26 参数）。

        **注意**: 调用前需确保已在正确的基准面上打开草图。

        Args:
            depth_mm: 切除深度（mm）。
            feat_name: 特征名称。

        Returns:
            bool: 成功返回 True。
        """
        depth_m = self.mm_to_m(depth_mm)
        try:
            feat = self.sw_feat_mgr.FeatureCut3(
                True,           # Sd — 单方向
                False,          # Flip — 不翻转切除侧
                False,          # Dir — 不反向
                swEndCondBlind, # T1 = 盲孔
                0,              # T2 (未使用)
                depth_m,        # D1 深度 (米)
                depth_m,        # D2 (未使用)
                False,          # Dchk1 — 无拔模
                False,          # Dchk2
                False, False,   # Ddir1, Ddir2
                0.0, 0.0,       # Dang1, Dang2
                False, False,   # OffsetReverse
                False, False,   # TranslateSurface
                False,          # NormalCut
                True,           # UseFeatScope
                True,           # UseAutoSelect
                False, False, False,  # Assembly
                swStartSketchPlane,   # T0
                0.0,            # StartOffset
                False,          # FlipStartOffset
            )
            if feat is None:
                logger.error(f"{feat_name}: FeatureCut3 返回 None")
                return False
            feat.Name = feat_name
            logger.success(f"  [OK] {feat_name} (深度 {depth_mm}mm)")
            return True
        except Exception as e:
            logger.error(f"{feat_name}: FeatureCut3 异常 - {e}")
            raise SwFeatureError(f"拉伸切除创建失败: {e}") from e


# ---------------------------------------------------------------------------
# 便捷函数
# ---------------------------------------------------------------------------

def check_sw_connection(visible: bool = True) -> bool:
    """验证 SolidWorks 2025 连接。

    诊断用函数，打印连接信息。

    Args:
        visible: 是否显示 SW 窗口。

    Returns:
        bool: 连接成功返回 True。
    """
    logger.info("=" * 60)
    logger.info("SolidWorks 2025 连接诊断")
    logger.info("=" * 60)

    driver = SolidWorksDriver(visible=visible)
    try:
        if not driver.connect():
            logger.error("无法连接 SolidWorks")
            logger.info("请检查:")
            logger.info("  1. SolidWorks 2025 是否已安装?")
            logger.info("  2. 是否以管理员身份运行过 SW?")
            return False

        logger.info(f"SolidWorks 版本: {driver.sw_app.RevisionNumber}")
        logger.info("连接正常！")

        # 尝试验证模板可用性
        try:
            template = driver.sw_app.GetDocumentTemplate(swDocPART, "", 0, 0, 0)
            logger.info(f"零件模板: {template}")
        except Exception as e:
            logger.warning(f"模板获取异常: {e}")

        return True
    except SwConnectionError as e:
        logger.error(f"连接失败: {e}")
        return False
    finally:
        driver.disconnect()
