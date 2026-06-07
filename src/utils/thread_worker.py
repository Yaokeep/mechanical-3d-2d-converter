# 机械三维二维图互转 — 后台工作线程

from PyQt6.QtCore import QObject, QThread, pyqtSignal, pyqtSlot


class ThreadWorker(QObject):
    """后台工作线程封装

    将耗时操作（文件 I/O、HLR 投影计算等）放入 QThread 执行，
    避免阻塞 GUI 主线程。通过信号报告进度和结果。

    使用方式：
        worker = ThreadWorker(long_running_function, arg1, arg2)
        worker.progress.connect(on_progress)
        worker.finished.connect(on_finished)
        worker.error.connect(on_error)
        worker.start()
    """

    # 信号
    progress = pyqtSignal(int)              # 进度 0-100
    finished = pyqtSignal(object)           # 计算结果
    error = pyqtSignal(str)                 # 错误信息

    def __init__(self, target_fn, *args, **kwargs):
        """
        Args:
            target_fn: 要在后台执行的函数
            *args: 函数位置参数
            **kwargs: 函数关键字参数
        """
        super().__init__()
        self._target_fn = target_fn
        self._args = args
        self._kwargs = kwargs
        self._thread: QThread | None = None
        self._is_running = False

    def start(self) -> None:
        """启动后台线程"""
        if self._is_running:
            return

        self._thread = QThread()
        self.moveToThread(self._thread)

        self._thread.started.connect(self._run)
        self._thread.finished.connect(self._thread.deleteLater)
        self._thread.finished.connect(lambda: setattr(self, "_is_running", False))

        self._is_running = True
        self._thread.start()

    @pyqtSlot()
    def _run(self) -> None:
        """线程执行体"""
        try:
            result = self._target_fn(*self._args, **self._kwargs)
            self.finished.emit(result)
        except Exception as e:
            self.error.emit(str(e))
        finally:
            if self._thread:
                self._thread.quit()

    def cancel(self) -> None:
        """取消线程（请求退出）"""
        if self._thread and self._thread.isRunning():
            self._thread.requestInterruption()
            self._thread.quit()
            self._thread.wait(1000)
        self._is_running = False

    @property
    def is_running(self) -> bool:
        """线程是否正在运行"""
        return self._is_running
