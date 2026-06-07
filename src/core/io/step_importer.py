# 机械三维二维图互转 — STEP 文件导入器

from src.core.io.registry import BaseImporter


class StepImporter(BaseImporter):
    """STEP 文件导入器（AP203 / AP214）

    使用 OpenCASCADE 的 STEPControl_Reader 读取 STEP 文件，
    自动处理坐标系转换和单位缩放。
    """

    FORMAT_NAME = "STEP"
    EXTENSIONS = [".step", ".stp"]

    def import_file(self, path: str) -> "Document":
        """导入 STEP 文件

        Args:
            path: STEP 文件路径

        Returns:
            包含导入模型的 Document 实例
        """
        from src.core.model.document import Document

        doc = Document()
        doc.file_path = path

        try:
            # TODO: 集成 PythonOCC
            # from OCC.Core.STEPControl import STEPControl_Reader
            # reader = STEPControl_Reader()
            # status = reader.ReadFile(path)
            # if status != 1:  # IFSelect_RetDone
            #     raise IOError(f"无法读取 STEP 文件: {path}")
            # reader.TransferRoots()
            # shape = reader.OneShape()
            # doc.add_shape("imported_model", shape)

            # 骨架阶段：创建占位节点
            import os
            name = os.path.splitext(os.path.basename(path))[0]
            doc.add_shape(name, None)
        except Exception as e:
            raise IOError(f"STEP 导入失败: {e}")

        return doc
