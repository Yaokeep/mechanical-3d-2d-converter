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

        Args:
            sections: 轴段列表 [(x_start, x_end, radius_mm), ...]。
            keyways: 键槽列表 [(x_start, x_end, width, depth, shaft_radius), ...]。
            chamfer_mm: 端面倒角尺寸 (mm)。
            fillet_r_mm: 阶跃圆角半径 (mm)。
            progress_callback: 进度回调 (step_name, percent)。

        Returns:
            bool: 全部成功返回 True。
        """
        if sections is None:
            sections = DEFAULT_SECTIONS
        if keyways is None:
            keyways = DEFAULT_KEYWAYS

        left_x, _, left_r = sections[0]
        right_x, _, right_r = sections[-1]
        right_x = sections[-1][1]  # x_end of last section

        steps = [
            ("旋转基体", 0, 25, lambda: self.create_shaft_body(sections)),
            ("端面倒角", 25, 40, lambda: self._create_end_chamfers(
                left_x, left_r, right_x, right_r, chamfer_mm)),
            ("过渡圆角", 40, 55, lambda: self._create_step_fillets(
                sections, fillet_r_mm)),
            ("键槽", 55, 100, lambda: self._create_keyways(keyways)),
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
    # 端面倒角
    # ------------------------------------------------------------------

    def _create_end_chamfers(
        self,
        left_x: float,
        left_r: float,
        right_x: float,
        right_r: float,
        chamfer_mm: float,
    ) -> bool:
        """创建左右端面倒角。"""
        logger.info("--- 创建端面倒角 ---")
        lx_m = self._driver.mm_to_m(left_x)
        lr_m = self._driver.mm_to_m(left_r)
        rx_m = self._driver.mm_to_m(right_x)
        rr_m = self._driver.mm_to_m(right_r)

        ok1 = self._driver.feature_chamfer_edge(
            lx_m, lr_m, chamfer_mm, "Chamfer-LeftEnd"
        )
        ok2 = self._driver.feature_chamfer_edge(
            rx_m, rr_m, chamfer_mm, "Chamfer-RightEnd"
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
        """创建阶跃过渡圆角。"""
        logger.info("--- 创建过渡圆角 ---")
        edge_specs = []
        for i in range(len(sections) - 1):
            mid = (sections[i][1] + sections[i + 1][0]) / 2.0
            r_big = max(sections[i][2], sections[i + 1][2])
            mid_m = self._driver.mm_to_m(mid)
            r_big_m = self._driver.mm_to_m(r_big)
            edge_specs.append((mid_m, r_big_m))
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
        """创建所有键槽。"""
        logger.info("--- 创建键槽 ---")
        all_ok = True
        for i, (xs, xe, w, d, sr) in enumerate(keyways):
            cx = (xs + xe) / 2.0
            length = xe - xs
            hw = w / 2.0
            feat_name = f"Keyway-{i+1}"
            ok = self._create_single_keyway(cx, length, hw, sr, d, feat_name)
            if not ok:
                all_ok = False
        return all_ok

    def _create_single_keyway(
        self,
        cx_mm: float,
        length_mm: float,
        half_width_mm: float,
        shaft_r_mm: float,
        depth_mm: float,
        feat_name: str,
    ) -> bool:
        """创建单个键槽拉伸切除。

        方法:
          1. 从 Top Plane 偏移 shaftR 创建切线基准面
          2. 在基准面上绘制矩形草图
          3. 向下拉伸切除

        Args:
            cx_mm: 键槽中心 X 坐标 (mm)。
            length_mm: 键槽长度 (mm)。
            half_width_mm: 键槽半宽 (mm)。
            shaft_r_mm: 轴段半径 (mm) — 用于创建切线基准面。
            depth_mm: 键槽深度 (mm)。
            feat_name: 特征名称。

        Returns:
            bool: 成功返回 True。
        """
        y_tangent = shaft_r_mm  # 切线面 Y 坐标 (mm)

        x1 = cx_mm - length_mm / 2.0
        x2 = cx_mm + length_mm / 2.0
        z1 = -half_width_mm
        z2 = half_width_mm

        plane_name = feat_name + "-Plane"

        # A: 创建切线基准面 (InsertRefPlane 必须用中文基准面名!)
        if not self._driver.create_ref_plane_offset(
            "上视基准面", shaft_r_mm, plane_name
        ):
            return False

        # B: 绘制键槽矩形草图
        self._driver.exit_sketch()  # 确保在正确上下文
        if not self._driver.start_sketch(plane_name):
            return False

        # Note: 在新基准面上草图使用 mm 坐标
        # 前边 Z=-halfWidth
        self._driver.draw_line(x1, y_tangent, z1, x2, y_tangent, z1)
        # 右边 X=x2
        self._driver.draw_line(x2, y_tangent, z1, x2, y_tangent, z2)
        # 后边 Z=+halfWidth
        self._driver.draw_line(x2, y_tangent, z2, x1, y_tangent, z2)
        # 左边 X=x1
        self._driver.draw_line(x1, y_tangent, z2, x1, y_tangent, z1)

        # V45 规则: 不关闭草图，直接在打开状态下调用特征

        # C: 拉伸切除
        if not self._driver.feature_cut_extrude(depth_mm, feat_name):
            return False

        logger.success(
            f"  [OK] {feat_name} "
            f"(L={length_mm:.0f} W={half_width_mm*2:.0f} D={depth_mm:.0f})"
        )
        return True
