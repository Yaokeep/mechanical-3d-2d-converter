# 机械三维二维图互转 — SolidWorks 阶梯轴建模对话框

from __future__ import annotations

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout,
    QGroupBox, QTableWidget, QTableWidgetItem,
    QDoubleSpinBox, QPushButton, QLabel,
    QDialogButtonBox, QHeaderView, QMessageBox,
    QFileDialog, QProgressBar, QTextEdit,
)
from PyQt6.QtCore import pyqtSignal
from PyQt6.QtGui import QFont

from src.utils.thread_worker import ThreadWorker


# ---------------------------------------------------------------------------
# 默认参数
# ---------------------------------------------------------------------------

DEFAULT_SECTIONS = [
    (-233.066, -158.466, 16.0),
    (-157.266, -108.466, 18.5),
    (-107.266,  -85.466, 20.0),
    ( -84.266,   79.534, 23.0),
    (  80.734,   86.734, 25.0),
    (  87.934,  171.734, 21.5),
    ( 172.934,  221.734, 20.0),
]

DEFAULT_KEYWAYS = [
    (-216.266, -176.266, 10.0, 5.0, 16.0),
    ( 110.734,  148.734, 12.0, 6.0, 21.5),
]

DEFAULT_CHAMFER = 1.2
DEFAULT_FILLET = 1.2


# ---------------------------------------------------------------------------
# SW 后台执行函数（在 QThread 中运行）
# ---------------------------------------------------------------------------

def _sw_build_shaft(
    sections: list,
    keyways: list,
    chamfer_mm: float,
    fillet_r_mm: float,
    save_path: str | None,
    progress_signal,
) -> str:
    """在后台线程中执行 SW 建模。

    Args:
        sections: 轴段列表。
        keyways: 键槽列表。
        chamfer_mm: 倒角尺寸。
        fillet_r_mm: 圆角半径。
        save_path: 保存路径（None 则不保存）。
        progress_signal: 进度信号（用于 emit 进度）。

    Returns:
        str: 结果消息。
    """
    from src.core.sw_automation import (
        SolidWorksDriver, ShaftBuilder, SwConnectionError, SwFeatureError,
    )

    driver = SolidWorksDriver(visible=True)
    try:
        progress_signal.emit("正在连接 SolidWorks 2025 ...", 5)
        if not driver.connect():
            return "[FAIL] 无法连接 SolidWorks 2025"

        progress_signal.emit("正在创建新零件 ...", 10)
        if not driver.new_part():
            return "[FAIL] 无法创建新零件"

        builder = ShaftBuilder(driver)

        def on_progress(name: str, pct: int):
            progress_signal.emit(f"正在执行: {name} ...", pct)

        progress_signal.emit("开始建模 ...", 15)
        ok = builder.build(sections, keyways, chamfer_mm, fillet_r_mm,
                           progress_callback=on_progress)

        if ok:
            driver.rebuild()
            driver.zoom_to_fit()

            if save_path:
                progress_signal.emit(f"正在保存: {save_path}", 95)
                driver.save_as(save_path)

            progress_signal.emit("建模完成！", 100)

            msg = "✅ 阶梯轴建模成功！\n\n特征树:\n"
            msg += "  1. Revolve-ShaftBody (旋转基体)\n"
            msg += f"  2. Chamfer-LeftEnd (左端倒角 C{chamfer_mm})\n"
            msg += f"  3. Chamfer-RightEnd (右端倒角 C{chamfer_mm})\n"
            msg += f"  4. Fillet-Transitions (过渡圆角 R{fillet_r_mm})\n"
            for i, kw in enumerate(keyways):
                msg += f"  {5+i}. Keyway-{i+1} (键槽 {kw[2]:.0f}×{kw[3]:.0f}mm)\n"
            if save_path:
                msg += f"\n已保存: {save_path}"
            return msg
        else:
            return "[WARN] 部分步骤未成功，请检查 SolidWorks 特征树"
    except SwConnectionError as e:
        return f"[FAIL] 连接错误: {e}\n请确认:\n  1. SolidWorks 2025 已安装\n  2. pip install pywin32"
    except SwFeatureError as e:
        return f"[FAIL] 特征创建错误: {e}"
    except ImportError as e:
        return f"[FAIL] 缺少依赖: {e}\n请运行: pip install pywin32"
    except Exception as e:
        import traceback
        return f"[FAIL] 未预期错误: {e}\n{traceback.format_exc()}"
    finally:
        driver.disconnect()


# ---------------------------------------------------------------------------
# SwShaftDialog
# ---------------------------------------------------------------------------

class SwShaftDialog(QDialog):
    """SolidWorks 阶梯轴参数化建模对话框。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("SolidWorks 2025 — 阶梯轴参数化建模")
        self.setMinimumSize(700, 600)
        self.resize(750, 650)
        self._setup_ui()

    def _setup_ui(self) -> None:
        """构建对话框 UI。"""
        layout = QVBoxLayout(self)

        # ---- 轴段参数 ----
        sections_group = QGroupBox("轴段参数 (mm)")
        sections_layout = QVBoxLayout()

        # 工具栏
        toolbar = QHBoxLayout()
        self._btn_add_section = QPushButton("+ 添加轴段")
        self._btn_del_section = QPushButton("- 删除选中")
        self._btn_add_section.clicked.connect(self._on_add_section)
        self._btn_del_section.clicked.connect(self._on_del_section)
        toolbar.addWidget(self._btn_add_section)
        toolbar.addWidget(self._btn_del_section)
        toolbar.addStretch()
        sections_layout.addLayout(toolbar)

        # 表格
        self._section_table = QTableWidget(0, 3)
        self._section_table.setHorizontalHeaderLabels(
            ["起点 X", "终点 X", "半径"]
        )
        self._section_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        sections_layout.addWidget(self._section_table)
        sections_group.setLayout(sections_layout)
        layout.addWidget(sections_group)

        # ---- 键槽参数 ----
        keyways_group = QGroupBox("键槽参数 (mm)")
        keyways_layout = QVBoxLayout()

        kw_toolbar = QHBoxLayout()
        self._btn_add_keyway = QPushButton("+ 添加键槽")
        self._btn_del_keyway = QPushButton("- 删除选中")
        self._btn_add_keyway.clicked.connect(self._on_add_keyway)
        self._btn_del_keyway.clicked.connect(self._on_del_keyway)
        kw_toolbar.addWidget(self._btn_add_keyway)
        kw_toolbar.addWidget(self._btn_del_keyway)
        kw_toolbar.addStretch()
        keyways_layout.addLayout(kw_toolbar)

        self._keyway_table = QTableWidget(0, 5)
        self._keyway_table.setHorizontalHeaderLabels(
            ["起点 X", "终点 X", "宽度", "深度", "轴半径"]
        )
        self._keyway_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        keyways_layout.addWidget(self._keyway_table)
        keyways_group.setLayout(keyways_layout)
        layout.addWidget(keyways_group)

        # ---- 细节参数 ----
        detail_group = QGroupBox("细节参数")
        detail_layout = QHBoxLayout()

        form1 = QFormLayout()
        self._chamfer_spin = QDoubleSpinBox()
        self._chamfer_spin.setRange(0.1, 10.0)
        self._chamfer_spin.setValue(DEFAULT_CHAMFER)
        self._chamfer_spin.setSingleStep(0.1)
        self._chamfer_spin.setSuffix(" mm")
        form1.addRow("倒角尺寸 C:", self._chamfer_spin)

        form2 = QFormLayout()
        self._fillet_spin = QDoubleSpinBox()
        self._fillet_spin.setRange(0.1, 20.0)
        self._fillet_spin.setValue(DEFAULT_FILLET)
        self._fillet_spin.setSingleStep(0.1)
        self._fillet_spin.setSuffix(" mm")
        form2.addRow("圆角半径 R:", self._fillet_spin)

        detail_layout.addLayout(form1)
        detail_layout.addLayout(form2)
        detail_layout.addStretch()

        detail_group.setLayout(detail_layout)
        layout.addWidget(detail_group)

        # ---- 保存路径 ----
        save_layout = QHBoxLayout()
        self._save_path_label = QLabel("保存路径: (不保存)")
        self._save_path_label.setStyleSheet("color: #888;")
        self._btn_choose_path = QPushButton("选择保存路径...")
        self._btn_choose_path.clicked.connect(self._on_choose_save_path)
        save_layout.addWidget(self._save_path_label, 1)
        save_layout.addWidget(self._btn_choose_path)
        layout.addLayout(save_layout)

        # ---- 进度条 ----
        self._progress_bar = QProgressBar()
        self._progress_bar.setVisible(False)
        layout.addWidget(self._progress_bar)

        # ---- 输出日志 ----
        self._log_text = QTextEdit()
        self._log_text.setReadOnly(True)
        self._log_text.setMaximumHeight(120)
        self._log_text.setFont(QFont("Consolas", 9))
        layout.addWidget(self._log_text)

        # ---- 底部按钮 ----
        bottom_layout = QHBoxLayout()
        self._btn_check = QPushButton("测试连接")
        self._btn_check.clicked.connect(self._on_check_connection)
        self._btn_build = QPushButton("一键建模")
        self._btn_build.setStyleSheet(
            "QPushButton { font-weight: bold; min-height: 28px; }"
        )
        self._btn_build.clicked.connect(self._on_build)

        btn_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        btn_box.rejected.connect(self.reject)

        bottom_layout.addWidget(self._btn_check)
        bottom_layout.addWidget(self._btn_build)
        bottom_layout.addStretch()
        bottom_layout.addWidget(btn_box)
        layout.addLayout(bottom_layout)

        # ---- 初始化数据 ----
        self._save_path: str | None = None
        self._populate_sections(DEFAULT_SECTIONS)
        self._populate_keyways(DEFAULT_KEYWAYS)

    # ------------------------------------------------------------------
    # 数据填充
    # ------------------------------------------------------------------

    def _populate_sections(self, sections: list) -> None:
        """填充轴段表格。"""
        self._section_table.setRowCount(len(sections))
        for i, (xs, xe, r) in enumerate(sections):
            self._section_table.setItem(i, 0, QTableWidgetItem(str(xs)))
            self._section_table.setItem(i, 1, QTableWidgetItem(str(xe)))
            self._section_table.setItem(i, 2, QTableWidgetItem(str(r)))

    def _populate_keyways(self, keyways: list) -> None:
        """填充键槽表格。"""
        self._keyway_table.setRowCount(len(keyways))
        for i, (xs, xe, w, d, sr) in enumerate(keyways):
            self._keyway_table.setItem(i, 0, QTableWidgetItem(str(xs)))
            self._keyway_table.setItem(i, 1, QTableWidgetItem(str(xe)))
            self._keyway_table.setItem(i, 2, QTableWidgetItem(str(w)))
            self._keyway_table.setItem(i, 3, QTableWidgetItem(str(d)))
            self._keyway_table.setItem(i, 4, QTableWidgetItem(str(sr)))

    def _read_sections(self) -> list:
        """从表格读取轴段参数。"""
        sections = []
        for i in range(self._section_table.rowCount()):
            try:
                xs = float(self._section_table.item(i, 0).text())
                xe = float(self._section_table.item(i, 1).text())
                r = float(self._section_table.item(i, 2).text())
                sections.append((xs, xe, r))
            except (ValueError, AttributeError):
                self._log("读取轴段行 %d 失败，已跳过", i + 1)
        return sections

    def _read_keyways(self) -> list:
        """从表格读取键槽参数。"""
        keyways = []
        for i in range(self._keyway_table.rowCount()):
            try:
                xs = float(self._keyway_table.item(i, 0).text())
                xe = float(self._keyway_table.item(i, 1).text())
                w = float(self._keyway_table.item(i, 2).text())
                d = float(self._keyway_table.item(i, 3).text())
                sr = float(self._keyway_table.item(i, 4).text())
                keyways.append((xs, xe, w, d, sr))
            except (ValueError, AttributeError):
                self._log("读取键槽行 %d 失败，已跳过", i + 1)
        return keyways

    # ------------------------------------------------------------------
    # 表格操作
    # ------------------------------------------------------------------

    def _on_add_section(self) -> None:
        """添加轴段行。"""
        row = self._section_table.rowCount()
        self._section_table.insertRow(row)
        self._section_table.setItem(row, 0, QTableWidgetItem("0"))
        self._section_table.setItem(row, 1, QTableWidgetItem("50"))
        self._section_table.setItem(row, 2, QTableWidgetItem("20"))

    def _on_del_section(self) -> None:
        """删除选中轴段行。"""
        rows = set()
        for item in self._section_table.selectedItems():
            rows.add(item.row())
        for row in sorted(rows, reverse=True):
            self._section_table.removeRow(row)

    def _on_add_keyway(self) -> None:
        """添加键槽行。"""
        row = self._keyway_table.rowCount()
        self._keyway_table.insertRow(row)
        self._keyway_table.setItem(row, 0, QTableWidgetItem("0"))
        self._keyway_table.setItem(row, 1, QTableWidgetItem("40"))
        self._keyway_table.setItem(row, 2, QTableWidgetItem("10"))
        self._keyway_table.setItem(row, 3, QTableWidgetItem("5"))
        self._keyway_table.setItem(row, 4, QTableWidgetItem("20"))

    def _on_del_keyway(self) -> None:
        """删除选中键槽行。"""
        rows = set()
        for item in self._keyway_table.selectedItems():
            rows.add(item.row())
        for row in sorted(rows, reverse=True):
            self._keyway_table.removeRow(row)

    # ------------------------------------------------------------------
    # 保存路径
    # ------------------------------------------------------------------

    def _on_choose_save_path(self) -> None:
        """选择保存路径。"""
        path, _ = QFileDialog.getSaveFileName(
            self, "保存阶梯轴模型", "shaft.sldprt",
            "SolidWorks 零件 (*.sldprt);;所有文件 (*.*)",
        )
        if path:
            self._save_path = path
            self._save_path_label.setText(f"保存路径: {path}")
            self._save_path_label.setStyleSheet("color: #000;")

    # ------------------------------------------------------------------
    # 操作按钮
    # ------------------------------------------------------------------

    def _on_check_connection(self) -> None:
        """测试 SW 连接。"""
        self._log("正在测试 SolidWorks 连接 ...")
        self._set_buttons_enabled(False)
        self._progress_bar.setVisible(True)
        self._progress_bar.setValue(0)

        # 在后台线程中执行连接检查
        self._worker = ThreadWorker(self._do_check_connection)
        self._worker.finished.connect(self._on_check_finished)
        self._worker.error.connect(self._on_worker_error)
        self._worker.start()

    def _do_check_connection(self) -> str:
        """后台执行连接检查。"""
        from src.core.sw_automation import SolidWorksDriver

        # check_sw_connection 内部使用 loguru，我们改用直接检查
        driver = SolidWorksDriver(visible=True)
        try:
            if driver.connect():
                revision = driver.sw_app.RevisionNumber
                return f"✅ 连接成功！SolidWorks 版本: {revision}"
            else:
                return "❌ 连接失败：COM 对象为 None"
        except Exception as e:
            return f"❌ 连接失败: {e}"
        finally:
            driver.disconnect()

    def _on_check_finished(self, result: str) -> None:
        """连接检查完成。"""
        self._log(result)
        self._progress_bar.setValue(100)
        self._progress_bar.setVisible(False)
        self._set_buttons_enabled(True)

    def _on_build(self) -> None:
        """一键建模。"""
        sections = self._read_sections()
        if len(sections) < 1:
            QMessageBox.warning(self, "参数错误", "至少需要 1 个轴段！")
            return

        keyways = self._read_keyways()
        chamfer = self._chamfer_spin.value()
        fillet = self._fillet_spin.value()

        self._log("=" * 50)
        self._log("开始 SolidWorks 阶梯轴建模 ...")
        self._log(f"  轴段: {len(sections)} 段")
        self._log(f"  键槽: {len(keyways)} 个")
        self._log(f"  倒角: C{chamfer}, 圆角: R{fillet}")
        if self._save_path:
            self._log(f"  保存: {self._save_path}")

        self._set_buttons_enabled(False)
        self._progress_bar.setVisible(True)
        self._progress_bar.setValue(0)

        # 后台线程执行
        self._worker_progress.connect(self._on_progress_update)
        self._worker = ThreadWorker(
            _sw_build_shaft,
            sections, keyways, chamfer, fillet, self._save_path,
            self._worker_progress,
        )
        self._worker.finished.connect(self._on_build_finished)
        self._worker.error.connect(self._on_worker_error)
        self._worker.start()

    _worker_progress = pyqtSignal(str, int)

    def _on_progress_update(self, message: str, percent: int) -> None:
        """更新进度条和日志。"""
        self._progress_bar.setValue(percent)
        self._log(message)

    def _on_build_finished(self, result: str) -> None:
        """建模完成。"""
        self._log(result)
        self._progress_bar.setValue(100)
        self._progress_bar.setVisible(False)
        self._set_buttons_enabled(True)

        if "✅" in result:
            QMessageBox.information(self, "建模完成", result)

    def _on_worker_error(self, error_msg: str) -> None:
        """后台线程出错。"""
        self._log(f"❌ 错误: {error_msg}")
        self._progress_bar.setVisible(False)
        self._set_buttons_enabled(True)
        QMessageBox.critical(self, "执行错误", error_msg)

    # ------------------------------------------------------------------
    # 辅助
    # ------------------------------------------------------------------

    def _log(self, fmt: str, *args) -> None:
        """追加日志到文本区域。"""
        if args:
            text = fmt % args
        else:
            text = fmt
        self._log_text.append(text)

    def _set_buttons_enabled(self, enabled: bool) -> None:
        """批量设置按钮状态。"""
        self._btn_check.setEnabled(enabled)
        self._btn_build.setEnabled(enabled)
        self._btn_add_section.setEnabled(enabled)
        self._btn_del_section.setEnabled(enabled)
        self._btn_add_keyway.setEnabled(enabled)
        self._btn_del_keyway.setEnabled(enabled)
        self._btn_choose_path.setEnabled(enabled)

    # ------------------------------------------------------------------
    # 公共接口
    # ------------------------------------------------------------------

    def get_sections(self) -> list:
        """获取当前轴段参数。"""
        return self._read_sections()

    def get_keyways(self) -> list:
        """获取当前键槽参数。"""
        return self._read_keyways()

    def set_sections(self, sections: list) -> None:
        """设置轴段参数。"""
        self._populate_sections(sections)

    def set_keyways(self, keyways: list) -> None:
        """设置键槽参数。"""
        self._populate_keyways(keyways)
