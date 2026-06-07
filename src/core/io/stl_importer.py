# 机械三维二维图互转 — STL 文件导入器

from src.core.io.registry import BaseImporter


class StlImporter(BaseImporter):
    """STL 网格文件导入器

    使用 OpenCASCADE 的 StlAPI_Reader 读取 STL 文件（ASCII 和二进制）。
    导入结果为三角网格（TopoDS_Compound of faces）。
    """

    FORMAT_NAME = "STL"
    EXTENSIONS = [".stl"]

    def import_file(self, path: str) -> "Document":
        from src.core.model.document import Document
        import os

        doc = Document()
        doc.file_path = path

        try:
            # TODO: 集成 PythonOCC
            # from OCC.Core.StlAPI import StlAPI_Reader
            # reader = StlAPI_Reader()
            # shape = reader.Read(path)
            # doc.add_shape(os.path.splitext(os.path.basename(path))[0], shape)

            name = os.path.splitext(os.path.basename(path))[0]
            doc.add_shape(name, None)
        except Exception as e:
            raise IOError(f"STL 导入失败: {e}")

        return doc
