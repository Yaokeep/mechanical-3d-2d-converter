# 机械三维二维图互转 — 主窗口

import os
from PyQt6.QtWidgets import (
    QMainWindow, QSplitter, QMenuBar, QMenu, QToolBar,
    QStatusBar, QLabel, QDockWidget, QMessageBox,
    QFileDialog, QWidget, QVBoxLayout, QHBoxLayout,
    QTabWidget, QFrame,
)
from PyQt6.QtCore import Qt, QSize, pyqtSignal
from PyQt6.QtGui import QAction, QKeySequence, QIcon

from src.gui.view3d.view3d_widget import View3DWidget
from src.gui.view2d.view2d_widget import View2DWidget
from src.gui.dock_widgets.project_tree import ProjectTreeDock
from src.gui.dock_widgets.property_panel import PropertyPanelDock
from src.gui.dock_widgets.output_console import OutputConsoleDock


class MainWindow(QMainWindow):
    """主窗口：包含菜单栏、工具栏、状态栏、3D/2D 视口和 Dock 面板"""

    # 信号
    file_opened = pyqtSignal(str)  # 文件路径

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("机械三维二维图互转 v0.3.0")
        self.resize(1400, 900)
        self.setMinimumSize(1024, 600)

        # 初始化 UI 组件
        self._setup_menu_bar()
        self._setup_toolbar()
        self._setup_status_bar()
        self._setup_central_widget()
        self._setup_dock_widgets()

        # 连接信号
        self._connect_signals()

    # ------------------------- 菜单栏 -------------------------

    def _setup_menu_bar(self) -> None:
        """构建菜单栏"""
        menubar = self.menuBar()

        # ---- 文件菜单 ----
        self._file_menu = menubar.addMenu("文件(&F)")

        self._act_new = QAction("新建项目(&N)", self)
        self._act_new.setShortcut(QKeySequence.StandardKey.New)
        self._file_menu.addAction(self._act_new)

        self._act_open = QAction("打开模型(&O)...", self)
        self._act_open.setShortcut(QKeySequence.StandardKey.Open)
        self._file_menu.addAction(self._act_open)

        self._file_menu.addSeparator()

        self._act_save = QAction("保存(&S)", self)
        self._act_save.setShortcut(QKeySequence.StandardKey.Save)
        self._file_menu.addAction(self._act_save)

        self._act_save_as = QAction("另存为(&A)...", self)
        self._act_save_as.setShortcut(QKeySequence.StandardKey.SaveAs)
        self._file_menu.addAction(self._act_save_as)

        self._file_menu.addSeparator()

        self._act_import = QAction("导入 3D 模型(&I)...", self)
        self._act_import.setShortcut(QKeySequence("Ctrl+Shift+I"))
        self._file_menu.addAction(self._act_import)

        self._act_import_dxf = QAction("导入 DXF 工程图...", self)
        self._act_import_dxf.setToolTip("从 DXF 二维工程图导入截面轮廓用于 3D 重建")
        self._file_menu.addAction(self._act_import_dxf)

        self._file_menu.addSeparator()

        self._act_export = QAction("导出(&E)...", self)
        self._act_export.setShortcut(QKeySequence("Ctrl+Shift+E"))
        self._file_menu.addAction(self._act_export)

        self._file_menu.addSeparator()

        self._act_exit = QAction("退出(&X)", self)
        self._act_exit.setShortcut(QKeySequence.StandardKey.Quit)
        self._file_menu.addAction(self._act_exit)

        # ---- 视图菜单 ----
        self._view_menu = menubar.addMenu("视图(&V)")

        self._act_fit_all = QAction("适应全部(&F)", self)
        self._act_fit_all.setShortcut(QKeySequence("Ctrl+F"))
        self._view_menu.addAction(self._act_fit_all)

        self._view_menu.addSeparator()

        self._act_wireframe = QAction("线框模式(&W)", self)
        self._view_menu.addAction(self._act_wireframe)

        self._act_shaded = QAction("着色模式(&S)", self)
        self._view_menu.addAction(self._act_shaded)

        self._view_menu.addSeparator()

        self._act_toggle_grid = QAction("显示/隐藏网格(&G)", self)
        self._act_toggle_grid.setCheckable(True)
        self._act_toggle_grid.setChecked(True)
        self._view_menu.addAction(self._act_toggle_grid)

        # ---- 3D→2D 投影菜单 ----
        self._projection_menu = menubar.addMenu("3D→2D 投影(&P)")

        self._act_project_3view = QAction("生成三视图(&T)", self)
        self._act_project_3view.setShortcut(QKeySequence("Ctrl+T"))
        self._projection_menu.addAction(self._act_project_3view)

        self._act_project_isometric = QAction("生成轴测图(&I)", self)
        self._projection_menu.addAction(self._act_project_isometric)

        self._act_project_section = QAction("生成剖面图(&S)...", self)
        self._projection_menu.addAction(self._act_project_section)

        self._projection_menu.addSeparator()

        self._act_export_2d_dxf = QAction("导出二维工程图为 DXF...", self)
        self._projection_menu.addAction(self._act_export_2d_dxf)

        self._projection_menu.addSeparator()

        self._act_auto_dimension = QAction("自动标注(&D)", self)
        self._projection_menu.addAction(self._act_auto_dimension)

        # ---- 2D→3D 重建菜单 ----
        self._reconstruct_menu = menubar.addMenu("2D→3D 重建(&R)")

        self._act_extrude = QAction("拉伸建模(&E)...", self)
        self._reconstruct_menu.addAction(self._act_extrude)

        self._act_revolve = QAction("旋转建模(&R)...", self)
        self._reconstruct_menu.addAction(self._act_revolve)

        self._reconstruct_menu.addSeparator()

        self._act_import_dxf_section = QAction("从 DXF 导入截面(&D)...", self)
        self._act_import_dxf_section.setToolTip("导入 DXF 文件中的闭合轮廓作为拉伸/旋转截面")
        self._reconstruct_menu.addAction(self._act_import_dxf_section)

        # ---- 帮助菜单 ----
        self._help_menu = menubar.addMenu("帮助(&H)")

        self._act_about = QAction("关于(&A)", self)
        self._help_menu.addAction(self._act_about)

    # ------------------------- 工具栏 -------------------------

    def _setup_toolbar(self) -> None:
        """构建工具栏"""
        self._toolbar = QToolBar("主工具栏", self)
        self._toolbar.setMovable(False)
        self._toolbar.setIconSize(QSize(24, 24))
        self.addToolBar(Qt.ToolBarArea.TopToolBarArea, self._toolbar)

        # 文件操作
        self._toolbar.addAction(self._act_new)
        self._toolbar.addAction(self._act_open)
        self._toolbar.addAction(self._act_save)
        self._toolbar.addSeparator()

        # 视图操作
        self._toolbar.addAction(self._act_fit_all)
        self._toolbar.addAction(self._act_wireframe)
        self._toolbar.addAction(self._act_shaded)
        self._toolbar.addSeparator()

        # 3D→2D / 2D→3D 操作
        self._toolbar.addAction(self._act_project_3view)
        self._toolbar.addAction(self._act_extrude)

    # ------------------------- 状态栏 -------------------------

    def _setup_status_bar(self) -> None:
        """构建状态栏"""
        self._status_bar = QStatusBar(self)
        self.setStatusBar(self._status_bar)

        self._status_label = QLabel("就绪")
        self._status_bar.addWidget(self._status_label)

        self._coord_label = QLabel("X: 0.00  Y: 0.00  Z: 0.00  |  单位: mm")
        self._status_bar.addPermanentWidget(self._coord_label)

    # ------------------------- 中心区域 -------------------------

    def _setup_central_widget(self) -> None:
        """构建中心区域：左侧 3D 视口 + 右侧 2D 视口"""
        self._splitter = QSplitter(Qt.Orientation.Horizontal)

        # 左侧：3D 视口
        self._view3d_container = QWidget()
        layout_3d = QVBoxLayout(self._view3d_container)
        layout_3d.setContentsMargins(0, 0, 0, 0)

        self._view3d_label = QLabel("3D 模型视图")
        self._view3d_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._view3d_label.setStyleSheet(
            "color: #888; font-size: 14px; background-color: #f0f0f0;"
        )

        try:
            self._view3d = View3DWidget(self)
            layout_3d.addWidget(self._view3d)
            self._view3d_label.hide()
        except ImportError:
            layout_3d.addWidget(self._view3d_label)

        self._splitter.addWidget(self._view3d_container)

        # 右侧：2D 视口
        self._view2d_container = QWidget()
        layout_2d = QVBoxLayout(self._view2d_container)
        layout_2d.setContentsMargins(0, 0, 0, 0)

        self._view2d = View2DWidget(self)
        layout_2d.addWidget(self._view2d)

        self._splitter.addWidget(self._view2d_container)

        # 默认 3D 占 60%，2D 占 40%
        self._splitter.setSizes([840, 560])

        self.setCentralWidget(self._splitter)

    # ------------------------- Dock 面板 -------------------------

    def _setup_dock_widgets(self) -> None:
        """构建可停靠面板"""
        # 左侧：项目结构树
        self._project_tree_dock = ProjectTreeDock("项目结构", self)
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, self._project_tree_dock)

        # 右侧上下：属性面板 + 输出控制台
        self._property_dock = PropertyPanelDock("属性", self)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self._property_dock)

        self._console_dock = OutputConsoleDock("输出", self)
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, self._console_dock)

    # ------------------------- 信号连接 -------------------------

    def _connect_signals(self) -> None:
        """连接菜单和工具栏动作的信号槽"""
        self._act_exit.triggered.connect(self.close)
        self._act_open.triggered.connect(self._on_open_file)
        self._act_about.triggered.connect(self._on_about)

        # 视图信号转发
        self._act_fit_all.triggered.connect(self._on_fit_all)
        self._act_wireframe.triggered.connect(self._on_wireframe)
        self._act_shaded.triggered.connect(self._on_shaded)

        # 3D→2D 投影信号（骨架阶段打印日志）
        self._act_project_3view.triggered.connect(self._on_project_3view)
        self._act_project_isometric.triggered.connect(self._on_project_isometric)
        self._act_project_section.triggered.connect(self._on_project_section)
        self._act_auto_dimension.triggered.connect(self._on_auto_dimension)
        self._act_export_2d_dxf.triggered.connect(self._on_export_2d_dxf)

        # 2D→3D 重建信号（骨架阶段打印日志）
        self._act_extrude.triggered.connect(self._on_extrude)
        self._act_revolve.triggered.connect(self._on_revolve)

        # DXF 导入信号
        self._act_import_dxf.triggered.connect(self._on_import_dxf)
        self._act_import_dxf_section.triggered.connect(self._on_import_dxf_section)

    # ------------------------- 槽函数 -------------------------

    def _on_open_file(self) -> None:
        """打开 3D 模型文件"""
        path, _ = QFileDialog.getOpenFileName(
            self,
            "打开模型文件",
            "",
            "CAD 文件 (*.step *.stp *.iges *.igs *.stl *.brep *.dxf);;"
            "STEP 文件 (*.step *.stp);;"
            "IGES 文件 (*.iges *.igs);;"
            "STL 文件 (*.stl);;"
            "DXF 工程图 (*.dxf);;"
            "所有文件 (*.*)",
        )
        if path:
            ext = os.path.splitext(path)[1].lower()
            if ext == ".dxf":
                self._on_import_dxf(path)
            else:
                self._status_label.setText(f"已打开: {os.path.basename(path)}")
                self.file_opened.emit(path)

    def _on_fit_all(self) -> None:
        """适应全部视图"""
        if hasattr(self, "_view3d") and self._view3d:
            self._view3d.fit_all()
        self._status_label.setText("视图已适应")

    def _on_wireframe(self) -> None:
        """切换到线框模式"""
        if hasattr(self, "_view3d") and self._view3d:
            self._view3d.set_wireframe_mode()
        self._status_label.setText("线框模式")

    def _on_shaded(self) -> None:
        """切换到着色模式"""
        if hasattr(self, "_view3d") and self._view3d:
            self._view3d.set_shaded_mode()
        self._status_label.setText("着色模式")

    # ---- 3D→2D 投影槽函数 ----

    def _on_project_3view(self) -> None:
        """生成三视图（骨架）"""
        self._status_label.setText("三视图投影 — 功能开发中...")

    def _on_project_isometric(self) -> None:
        """生成轴测图（骨架）"""
        self._status_label.setText("轴测图投影 — 功能开发中...")

    def _on_project_section(self) -> None:
        """生成剖面图（骨架）"""
        self._status_label.setText("剖面图 — 功能开发中...")

    def _on_auto_dimension(self) -> None:
        """自动标注（骨架）"""
        self._status_label.setText("自动标注 — 功能开发中...")

    def _on_export_2d_dxf(self) -> None:
        """导出二维工程图为 DXF"""
        path, _ = QFileDialog.getSaveFileName(
            self, "导出二维工程图", "",
            "DXF 文件 (*.dxf);;所有文件 (*.*)",
        )
        if path:
            self._status_label.setText(f"导出工程图到: {os.path.basename(path)}")
            self._console_dock.info(f"DXF 导出 — 功能开发中: {path}")

    # ---- 2D→3D 重建槽函数 ----

    def _on_extrude(self) -> None:
        """拉伸建模（骨架）"""
        self._status_label.setText("拉伸建模 — 功能开发中...")

    def _on_revolve(self) -> None:
        """旋转建模（骨架）"""
        self._status_label.setText("旋转建模 — 功能开发中...")

    # ---- DXF 导入槽函数 ----

    def _on_import_dxf(self, path: str = None) -> None:
        """导入 DXF 二维工程图"""
        if path is None:
            path, _ = QFileDialog.getOpenFileName(
                self, "导入 DXF 工程图", "",
                "DXF 文件 (*.dxf);;所有文件 (*.*)",
            )
        if not path:
            return

        try:
            from src.core.io.dxf_importer import DxfImporter

            self._status_label.setText(f"正在导入 DXF: {os.path.basename(path)} ...")
            self._console_dock.info(f"开始导入 DXF: {path}")

            importer = DxfImporter()
            doc = importer.import_file(path)

            entity_count = len(doc.get_all_shapes())
            self._status_label.setText(
                f"DXF 导入完成: {os.path.basename(path)} ({entity_count} 个图元)"
            )
            self._console_dock.success(
                f"DXF 导入成功: {entity_count} 个图元"
            )
            self.file_opened.emit(path)

        except ImportError as e:
            self._console_dock.error(str(e))
            QMessageBox.warning(self, "缺少依赖", str(e))
        except Exception as e:
            self._console_dock.error(f"DXF 导入失败: {e}")
            QMessageBox.critical(self, "导入失败", str(e))

    def _on_import_dxf_section(self) -> None:
        """从 DXF 导入截面用于 2D→3D 重建（骨架）"""
        path, _ = QFileDialog.getOpenFileName(
            self, "从 DXF 导入截面轮廓", "",
            "DXF 文件 (*.dxf);;所有文件 (*.*)",
        )
        if not path:
            return
        self._status_label.setText(f"DXF 截面导入 — 功能开发中: {os.path.basename(path)}")

    def _on_about(self) -> None:
        """显示关于对话框"""
        QMessageBox.about(
            self,
            "关于 机械三维二维图互转",
            "<h3>机械三维二维图互转 v0.3.0</h3>"
            "<p>机械工程 3D ↔ 2D 双向互转桌面工具</p>"
            "<p>技术栈：PyQt6 + OpenCASCADE (PythonOCC)</p>"
            "<hr>"
            "<p>核心功能：</p>"
            "<p><b>3D → 2D</b>：三视图投影 · 轴测图 · 剖面图 · HLR 消隐 · DXF 导出</p>"
            "<p><b>2D → 3D</b>：DXF 截面导入 · 拉伸建模 · 旋转建模 · STEP/IGES 导出</p>"
            "<p>支持格式：STEP · IGES · STL · DXF</p>",
        )

    # ------------------------- 公共方法 -------------------------

    def get_view3d(self) -> View3DWidget | None:
        """获取 3D 视图组件"""
        return getattr(self, "_view3d", None)

    def get_view2d(self) -> View2DWidget | None:
        """获取 2D 视图组件"""
        return getattr(self, "_view2d", None)

    def set_status_message(self, message: str) -> None:
        """设置状态栏消息"""
        self._status_label.setText(message)

    def closeEvent(self, event) -> None:
        """窗口关闭事件"""
        event.accept()
