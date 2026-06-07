# 机械三维二维图互转 — 剖面视图投影引擎

from src.core.projection.hlr_projector import HLRProjector
from src.core.model.projection_data import ProjectionData, ProjectionType


class SectionViewProjector:
    """剖面视图投影引擎

    生成剖面（剖切）视图：
    1. 使用 BRepAlgoAPI_Section 计算剖切平面与模型的交线
    2. 在剖切面上生成剖面填充（截面线 hatch）
    3. 叠加 HLR 投影产生完整剖面视图
    """

    def __init__(self):
        self._hlr = HLRProjector()

    def create_section(
        self,
        shape,
        cut_plane_origin: tuple[float, float, float],
        cut_plane_normal: tuple[float, float, float],
        view_direction: tuple[float, float, float],
    ) -> ProjectionData:
        """创建剖面视图

        Args:
            shape: TopoDS_Shape 源形状
            cut_plane_origin: 剖切平面上一点 (x, y, z)
            cut_plane_normal: 剖切平面法向 (nx, ny, nz)
            view_direction: 观察方向

        Returns:
            包含剖面信息的 ProjectionData
        """
        # TODO: 集成 PythonOCC 剖面功能
        # from OCC.Core.BRepAlgoAPI import BRepAlgoAPI_Section
        # from OCC.Core.GP import gp_Pln, gp_Pnt, gp_Dir
        #
        # cut_plane = gp_Pln(gp_Pnt(*cut_plane_origin), gp_Dir(*cut_plane_normal))
        # section = BRepAlgoAPI_Section(shape, cut_plane)
        # section.Build()
        # section_shape = section.Shape()

        data = ProjectionData(
            source_shape_name="unknown",
            view_type=ProjectionType.SECTION,
            view_label=f"剖面图 A-A",
            view_direction=view_direction,
        )

        # TODO: 提取剖面边 + 添加 hatch 填充图案
        return data
