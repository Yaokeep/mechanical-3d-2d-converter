# 机械三维二维图互转 — IGES 文件导入器

from src.core.io.registry import BaseImporter


class IgesImporter(BaseImporter):
    """IGES 文件导入器

    使用 OpenCASCADE 的 IGESControl_Reader 读取 IGES 文件（5.1 / 5.3）。
    """

    FORMAT_NAME = "IGES"
    EXTENSIONS = [".iges", ".igs"]

    def import_file(self, path: str) -> "Document":
        from src.core.model.document import Document
        import os

        doc = Document()
        doc.file_path = path

        try:
            # TODO: 集成 PythonOCC
            # from OCC.Core.IGESControl import IGESControl_Reader
            # reader = IGESControl_Reader()
            # status = reader.ReadFile(path)
            # reader.TransferRoots()
            # shape = reader.OneShape()

            name = os.path.splitext(os.path.basename(path))[0]
            doc.add_shape(name, None)
        except Exception as e:
            raise IOError(f"IGES 导入失败: {e}")

        return doc
