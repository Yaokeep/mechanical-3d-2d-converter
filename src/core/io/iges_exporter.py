# 机械三维二维图互转 — IGES 文件导出器

from src.core.io.registry import BaseExporter


class IgesExporter(BaseExporter):
    """IGES 文件导出器"""

    FORMAT_NAME = "IGES"
    EXTENSIONS = [".iges", ".igs"]

    def export(self, path: str, document: "Document", **kwargs) -> None:
        try:
            # TODO: IGESControl_Writer
            pass
        except Exception as e:
            raise IOError(f"IGES 导出失败: {e}")
