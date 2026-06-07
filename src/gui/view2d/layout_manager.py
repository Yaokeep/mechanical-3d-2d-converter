# 机械三维二维图互转 — 2D 视图布局管理器

from PyQt6.QtCore import QRectF
from enum import Enum, auto


class ViewLayoutManager:
    """2D 工程图视图布局管理器

    负责在场景中按照标准工程图布局摆放各视图框架。
    支持三种布局：
    - 单视图：一个视图填满画布
    - 四视图：正视图 + 俯视图 + 右侧视图 + 轴测图（标准三视图 + 轴测）
    - 六视图：全部六个正交视图面
    """

    class LayoutType(Enum):
        """布局类型"""
        SINGLE = auto()        # 单视图
        FOUR_VIEW = auto()     # 标准四视图（三视图 + 轴测）
        SIX_VIEW = auto()      # 六视图

    # 布局参数
    VIEW_SPACING = 60          # 视图间距 (px)
    MARGIN = 40                # 页边距 (px)
    TITLE_HEIGHT = 24          # 标题栏高度 (px)

    # 视图标签
    LABELS_FRONT = "正视图"
    LABELS_TOP = "俯视图"
    LABELS_RIGHT = "右侧视图"
    LABELS_LEFT = "左侧视图"
    LABELS_BOTTOM = "仰视图"
    LABELS_BACK = "后视图"
    LABELS_ISO = "轴测图"

    def __init__(self):
        pass

    def arrange(self, layout_type: LayoutType, scene_rect: QRectF) -> dict[str, QRectF]:
        """按照指定布局类型计算各视图框架矩形

        Args:
            layout_type: 布局类型
            scene_rect: 场景可用范围

        Returns:
            视图名称 → 矩形 的映射
        """
        if layout_type == self.LayoutType.SINGLE:
            return self._arrange_single(scene_rect)
        elif layout_type == self.LayoutType.FOUR_VIEW:
            return self._arrange_four_view(scene_rect)
        elif layout_type == self.LayoutType.SIX_VIEW:
            return self._arrange_six_view(scene_rect)
        else:
            return {}

    def _arrange_single(self, rect: QRectF) -> dict[str, QRectF]:
        """单视图布局"""
        inner = rect.adjusted(self.MARGIN, self.MARGIN, -self.MARGIN, -self.MARGIN)
        return {self.LABELS_FRONT: inner}

    def _arrange_four_view(self, rect: QRectF) -> dict[str, QRectF]:
        """四视图布局（2×2 网格）

        ┌──────────┬──────────┐
        │  正视图   │  俯视图   │
        ├──────────┼──────────┤
        │ 右侧视图  │  轴测图   │
        └──────────┴──────────┘
        """
        inner = rect.adjusted(self.MARGIN, self.MARGIN, -self.MARGIN, -self.MARGIN)
        w = (inner.width() - self.VIEW_SPACING) / 2
        h = (inner.height() - self.VIEW_SPACING) / 2

        x0, y0 = inner.left(), inner.top()

        frames = {
            self.LABELS_FRONT: QRectF(x0, y0, w, h),
            self.LABELS_TOP: QRectF(x0 + w + self.VIEW_SPACING, y0, w, h),
            self.LABELS_RIGHT: QRectF(x0, y0 + h + self.VIEW_SPACING, w, h),
            self.LABELS_ISO: QRectF(x0 + w + self.VIEW_SPACING, y0 + h + self.VIEW_SPACING, w, h),
        }
        return frames

    def _arrange_six_view(self, rect: QRectF) -> dict[str, QRectF]:
        """六视图布局（2×3 网格）

        ┌──────┬──────┬──────┐
        │正视图 │俯视图 │后视图 │
        ├──────┼──────┼──────┤
        │右视图 │仰视图 │左视图 │
        └──────┴──────┴──────┘
        """
        inner = rect.adjusted(self.MARGIN, self.MARGIN, -self.MARGIN, -self.MARGIN)
        w = (inner.width() - 2 * self.VIEW_SPACING) / 3
        h = (inner.height() - self.VIEW_SPACING) / 2

        x0, y0 = inner.left(), inner.top()

        frames = {
            self.LABELS_FRONT: QRectF(x0, y0, w, h),
            self.LABELS_TOP: QRectF(x0 + w + self.VIEW_SPACING, y0, w, h),
            self.LABELS_BACK: QRectF(x0 + 2 * (w + self.VIEW_SPACING), y0, w, h),
            self.LABELS_RIGHT: QRectF(x0, y0 + h + self.VIEW_SPACING, w, h),
            self.LABELS_BOTTOM: QRectF(x0 + w + self.VIEW_SPACING, y0 + h + self.VIEW_SPACING, w, h),
            self.LABELS_LEFT: QRectF(x0 + 2 * (w + self.VIEW_SPACING), y0 + h + self.VIEW_SPACING, w, h),
        }
        return frames
