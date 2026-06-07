# 机械三维二维图互转 — DXF 文件导入器

from src.core.io.registry import BaseImporter


class DxfImporter(BaseImporter):
    """DXF 二维工程图导入器

    使用 ezdxf 库读取 DXF 文件，提取 2D 几何实体（线段、圆弧、圆等），
    用于后续的 2D→3D 重建流程（拉伸/旋转建模）。
    """

    FORMAT_NAME = "DXF"
    EXTENSIONS = [".dxf"]

    def import_file(self, path: str, layer: str = "0") -> "Document":
        """导入 DXF 文件

        Args:
            path: DXF 文件路径
            layer: 目标图层名称

        Returns:
            包含提取的 2D 边数据的 Document
        """
        from src.core.model.document import Document
        import os

        doc = Document()
        doc.file_path = path

        try:
            # TODO: 集成 ezdxf
            # import ezdxf
            # dwg = ezdxf.readfile(path)
            # msp = dwg.modelspace()
            # edges = []
            # for entity in msp:
            #     if entity.dxf.layer != layer:
            #         continue
            #     if entity.dxftype() == 'LINE':
            #         edges.append(...)
            #     elif entity.dxftype() == 'ARC':
            #         edges.append(...)

            name = os.path.splitext(os.path.basename(path))[0]
            doc.add_shape(name, None)
        except Exception as e:
            raise IOError(f"DXF 导入失败: {e}")

        return doc
