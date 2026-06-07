# 机械三维二维图互转 — STEP 文件导出器

from src.core.io.registry import BaseExporter


class StepExporter(BaseExporter):
    """STEP 文件导出器

    使用 OpenCASCADE 的 STEPControl_Writer 将模型导出为 STEP 格式。
    """

    FORMAT_NAME = "STEP"
    EXTENSIONS = [".step", ".stp"]

    def export(self, path: str, document: "Document", **kwargs) -> None:
        """导出为 STEP 文件

        Args:
            path: 目标文件路径
            document: 项目文档
        """
        try:
            # TODO: 集成 PythonOCC
            # from OCC.Core.STEPControl import STEPControl_Writer, STEPControl_AsIs
            # writer = STEPControl_Writer()
            # for node in document.get_all_shapes().values():
            #     if node.shape is not None:
            #         writer.Transfer(node.shape, STEPControl_AsIs)
            # writer.Write(path)
            pass
        except Exception as e:
            raise IOError(f"STEP 导出失败: {e}")
