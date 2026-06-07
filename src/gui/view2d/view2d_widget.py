# 机械三维二维图互转 — 2D 工程图视图组件

from PyQt6.QtWidgets import QWidget, QVBoxLayout, QGraphicsView
from PyQt6.QtCore import Qt, QRectF, pyqtSignal
from PyQt6.QtGui import QPainter, QTransform

from src.gui.view2d.view2d_scene import View2DScene
from src.gui.view2d.layout_manager import ViewLayoutManager


class View2DWidget(QWidget):
    """2D 工程图视图组件

    基于 QGraphicsView 的工程图显示区域，支持：
    - 多视图布局（单视图 / 四视图 / 六视图）
    - 缩放和平移
    - 工程图标注渲染
    """

    # 信号
    zoom_changed = pyqtSignal(float)       # 当前缩放比例
    view_selected = pyqtSignal(str)        # 被点击的视图名称

    def __init__(self, parent=None):
        super().__init__(parent)
        self._current_scale = 1.0
        self._grid_enabled = True
        self._current_layout = ViewLayoutManager.LayoutType.FOUR_VIEW

        self._setup_ui()

    def _setup_ui(self) -> None:
        """构建 UI 布局"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # 创建 QGraphicsScene
        self._scene = View2DScene(self)
        self._layout_mgr = ViewLayoutManager()

        # 创建 QGraphicsView
        self._graphics_view = QGraphicsView(self._scene)
        self._graphics_view.setRenderHints(
            QPainter.RenderHint.Antialiasing |
            QPainter.RenderHint.TextAntialiasing
        )
        self._graphics_view.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self._graphics_view.setTransformationAnchor(
            QGraphicsView.ViewportAnchor.AnchorUnderMouse
        )
        self._graphics_view.setResizeAnchor(
            QGraphicsView.ViewportAnchor.AnchorViewCenter
        )
        self._graphics_view.setViewportUpdateMode(
            QGraphicsView.ViewportUpdateMode.FullViewportUpdate
        )
        self._graphics_view.setBackgroundBrush(Qt.GlobalColor.white)

        # 设置场景范围
        self._scene.setSceneRect(QRectF(0, 0, 800, 600))

        layout.addWidget(self._graphics_view)

        # 绘制默认视图框架
        self._draw_default_frames()

    def _draw_default_frames(self) -> None:
        """绘制默认的视图框架网格"""
        scene_rect = self._scene.sceneRect()
        frames = self._layout_mgr.arrange(
            self._current_layout, scene_rect
        )
        for name, rect in frames.items():
            self._scene.add_view_frame(name, rect)

    # ------------------------- 公共接口 -------------------------

    def set_layout(self, layout_type) -> None:
        """设置视图布局类型"""
        self._current_layout = layout_type
        self._scene.clear()
        self._draw_default_frames()

    def clear_projections(self) -> None:
        """清除所有投影内容（保留视图框架）"""
        # TODO: 移除所有 EdgeItem / DimensionItem
        self._scene.clear()
        self._draw_default_frames()

    def render_projection(self, view_data) -> None:
        """渲染投影数据到 2D 视图"""
        # TODO: 根据 ProjectionData 创建 EdgeItem / DimensionItem
        pass

    def add_dimension(self, dim_data) -> None:
        """添加标注"""
        # TODO: 创建 DimensionItem
        pass

    def zoom_to_fit(self) -> None:
        """缩放以适应全部内容"""
        self._graphics_view.fitInView(
            self._scene.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio
        )

    def export_to_dxf(self, path: str) -> None:
        """导出当前 2D 视图为 DXF 文件"""
        # TODO: 使用 ezdxf 写入 DXF
        pass

    @property
    def scene(self) -> View2DScene:
        """获取 2D 场景"""
        return self._scene

    @property
    def graphics_view(self) -> QGraphicsView:
        """获取底层 QGraphicsView"""
        return self._graphics_view
