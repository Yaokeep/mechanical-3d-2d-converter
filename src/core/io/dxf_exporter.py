# 机械三维二维图互转 — DXF 工程图导出器

from src.core.io.registry import BaseExporter


class DXFExporter(BaseExporter):
    """DXF 工程图导出器

    将 2D 投影数据导出为 DXF 格式，按图层组织：
    - "Visible"：可见轮廓（实线）
    - "Hidden"：隐藏轮廓（虚线）
    - "Center"：中心线（点划线）
    - "Dimension"：尺寸标注
    """

    FORMAT_NAME = "DXF 工程图"
    EXTENSIONS = [".dxf"]

    def export(self, path: str, projection_data=None, **kwargs) -> None:
        """导出 2D 投影为 DXF

        Args:
            path: 目标文件路径
            projection_data: ProjectionData 实例
        """
        try:
            # TODO: 使用 ezdxf 写入
            # import ezdxf
            # doc = ezdxf.new("R2010")
            # msp = doc.modelspace()
            #
            # # 创建图层
            # doc.layers.add("Visible", color=7, linetype="Continuous")
            # doc.layers.add("Hidden", color=8, linetype="Dashed")
            # doc.layers.add("Center", color=6, linetype="Center")
            # doc.layers.add("Dimension", color=1, linetype="Continuous")
            #
            # # 写入可见边
            # for edge in projection_data.visible_edges:
            #     msp.add_line(edge.start, edge.end, dxfattribs={"layer": "Visible"})
            #
            # # 写入隐藏边
            # for edge in projection_data.hidden_edges:
            #     msp.add_line(edge.start, edge.end, dxfattribs={"layer": "Hidden"})
            #
            # doc.saveas(path)
            pass
        except Exception as e:
            raise IOError(f"DXF 导出失败: {e}")
