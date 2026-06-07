# 机械三维二维图互转 — 3D 视图鼠标/键盘交互控制器

from PyQt6.QtCore import QObject, pyqtSignal, Qt
from PyQt6.QtGui import QMouseEvent, QWheelEvent, QKeyEvent


class View3DController(QObject):
    """3D 视图交互控制器

    将 PyQt6 鼠标/键盘事件翻译为 3D 视图操作：
    - 鼠标左键拖拽 → 旋转
    - 鼠标中键拖拽 → 平移
    - 鼠标滚轮 → 缩放
    - 鼠标右键点击 → 上下文菜单
    - Shift + 左键 → 多选
    """

    # 信号
    shape_selected = pyqtSignal(object)      # 选中 TopoDS_Shape
    view_changed = pyqtSignal()              # 视角发生变化
    context_menu_requested = pyqtSignal(object)  # 请求上下文菜单 (QPoint)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._view_widget = None
        self._is_rotating = False
        self._is_panning = False
        self._last_mouse_pos = None

    def install(self, view_widget) -> None:
        """安装到指定的 View3DWidget"""
        self._view_widget = view_widget
        # 安装事件过滤器
        view_widget.installEventFilter(self)

    def eventFilter(self, obj, event) -> bool:
        """事件过滤器：拦截鼠标和键盘事件"""
        if obj is not self._view_widget:
            return super().eventFilter(obj, event)

        if isinstance(event, QWheelEvent):
            self._handle_wheel(event)
            return True

        if isinstance(event, QMouseEvent):
            if event.type() == QMouseEvent.Type.MouseButtonPress:
                self._handle_mouse_press(event)
            elif event.type() == QMouseEvent.Type.MouseMove:
                self._handle_mouse_move(event)
            elif event.type() == QMouseEvent.Type.MouseButtonRelease:
                self._handle_mouse_release(event)
            return True

        if isinstance(event, QKeyEvent):
            self._handle_key(event)
            return True

        return super().eventFilter(obj, event)

    def _handle_wheel(self, event: QWheelEvent) -> None:
        """滚轮缩放"""
        # TODO: 调用 PythonOCC view zoom
        self.view_changed.emit()

    def _handle_mouse_press(self, event: QMouseEvent) -> None:
        """鼠标按下"""
        self._last_mouse_pos = event.pos()
        if event.button() == Qt.MouseButton.LeftButton:
            self._is_rotating = True
        elif event.button() == Qt.MouseButton.MiddleButton:
            self._is_panning = True

    def _handle_mouse_move(self, event: QMouseEvent) -> None:
        """鼠标移动（拖拽）"""
        if self._last_mouse_pos is None:
            return
        delta = event.pos() - self._last_mouse_pos
        self._last_mouse_pos = event.pos()

        if self._is_rotating:
            # TODO: 调用 PythonOCC view rotation
            pass
        elif self._is_panning:
            # TODO: 调用 PythonOCC view pan
            pass

        self.view_changed.emit()

    def _handle_mouse_release(self, event: QMouseEvent) -> None:
        """鼠标释放"""
        self._is_rotating = False
        self._is_panning = False

    def _handle_key(self, event: QKeyEvent) -> None:
        """键盘事件"""
        key = event.key()
        if key == Qt.Key.Key_F:
            # F 键：适应全部
            if self._view_widget:
                self._view_widget.fit_all()
        elif key == Qt.Key.Key_Escape:
            # ESC：取消选择
            self.shape_selected.emit(None)

    def reset_view(self) -> None:
        """重置视角到默认"""
        # TODO: view.Reset()
        self.view_changed.emit()
