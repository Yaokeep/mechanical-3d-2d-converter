# 机械三维二维图互转 — 3D 视图组件（PythonOCC 封装）

from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel
from PyQt6.QtCore import Qt


class View3DWidget(QWidget):
    """3D 模型视图组件

    封装 PythonOCC 的 3D 显示窗口，支持旋转、缩放、平移等交互。
    当前为骨架实现，后续将集成 pythonocc-core 的 Display3D。
    """

    # 显示模式
    MODE_WIREFRAME = 0
    MODE_SHADED = 1
    MODE_SHADED_WITH_EDGES = 2

    def __init__(self, parent=None):
        super().__init__(parent)
        self._display_mode = self.MODE_SHADED

        self._setup_ui()
        self._setup_occ_viewer()

    def _setup_ui(self) -> None:
        """构建 UI 布局"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # 占位标签（后续将被 PythonOCC viewer 替换）
        self._placeholder = QLabel("3D 视图\n\n需安装 pythonocc-core 以启用 3D 渲染")
        self._placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._placeholder.setStyleSheet(
            "color: #999; font-size: 13px; background-color: #e8e8e8;"
        )
        layout.addWidget(self._placeholder)

        # 设置最小尺寸
        self.setMinimumSize(300, 300)

    def _setup_occ_viewer(self) -> None:
        """初始化 PythonOCC 3D 观察器（延迟加载）"""
        # TODO: 集成 PythonOCC 的 Display3D
        # 当 pythonocc-core 可用时，创建 V3d_Viewer 和 AIS_InteractiveContext
        # 替换 _placeholder 标签
        self._occ_ready = False
        try:
            # from OCC.Display.backend import load_backend
            # load_backend("pyqt6")
            # from OCC.Display.qtDisplay import qtViewer3d
            # self._occ_ready = True
            pass
        except ImportError:
            pass

    # ------------------------- 公共接口 -------------------------

    def display_shape(self, shape, color=None, transparency: float = 0.0) -> None:
        """在视图中显示一个 TopoDS_Shape"""
        # TODO: 创建 AIS_Shape 并添加到 context
        pass

    def erase_all(self) -> None:
        """清除视图中所有形状"""
        # TODO: context.RemoveAll(True)
        pass

    def fit_all(self) -> None:
        """适应全部——将视图调整至显示所有对象"""
        if self._occ_ready:
            # self._view.ZFitAll()
            pass

    def set_wireframe_mode(self) -> None:
        """切换到线框渲染模式"""
        self._display_mode = self.MODE_WIREFRAME
        # TODO: context.SetDisplayMode(AIS_WireFrame, True)

    def set_shaded_mode(self) -> None:
        """切换到着色渲染模式"""
        self._display_mode = self.MODE_SHADED
        # TODO: context.SetDisplayMode(AIS_Shaded, True)

    def export_screenshot(self, path: str) -> None:
        """导出当前视图截图"""
        # TODO: self._view.Dump(path)
        pass

    @property
    def is_occ_ready(self) -> bool:
        """PythonOCC 是否已成功加载"""
        return self._occ_ready
