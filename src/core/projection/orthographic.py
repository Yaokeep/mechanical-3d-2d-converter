# 机械三维二维图互转 — 正交投影（三视图）引擎

from src.core.projection.hlr_projector import HLRProjector, ProjectionResult
from src.core.model.projection_data import ProjectionData, ProjectionType, Edge2D


class OrthographicProjector:
    """正交投影引擎

    封装 HLRProjector，产生标准三视图：
    - 正视图 (Front)：观察方向 (0, -1, 0)，投影在 XZ 平面
    - 俯视图 (Top)：观察方向 (0, 0, -1)，投影在 XY 平面
    - 右侧视图 (Right)：观察方向 (1, 0, 0)，投影在 YZ 平面

    中国国标（第一角投影法）使用"人→物体→投影面"的顺序。
    """

    # 第一角投影法的标准方向
    VIEW_DIRECTIONS = {
        ProjectionType.FRONT:  (0, -1, 0),    # 从前向后看
        ProjectionType.TOP:    (0, 0, -1),    # 从上向下看
        ProjectionType.RIGHT:  (1, 0, 0),     # 从右向左看
        ProjectionType.LEFT:   (-1, 0, 0),    # 从左向右看
        ProjectionType.BOTTOM: (0, 0, 1),     # 从下向上看
        ProjectionType.BACK:   (0, 1, 0),     # 从后向前看
    }

    # 视图中文标签
    VIEW_LABELS = {
        ProjectionType.FRONT:  "正视图",
        ProjectionType.TOP:    "俯视图",
        ProjectionType.RIGHT:  "右侧视图",
        ProjectionType.LEFT:   "左侧视图",
        ProjectionType.BOTTOM: "仰视图",
        ProjectionType.BACK:   "后视图",
    }

    def __init__(self):
        self._hlr = HLRProjector()

    def project(self, shape, view_type: ProjectionType) -> ProjectionData:
        """对指定形状执行正交投影

        Args:
            shape: TopoDS_Shape
            view_type: 视图类型

        Returns:
            ProjectionData 投影结果
        """
        direction = self.VIEW_DIRECTIONS.get(view_type, (0, -1, 0))
        label = self.VIEW_LABELS.get(view_type, "未知视图")

        self._hlr.set_shape(shape)
        self._hlr.set_direction(direction)

        raw_result = self._hlr.compute()

        # 转换为 ProjectionData
        data = ProjectionData(
            source_shape_name="unknown",
            view_type=view_type,
            view_label=label,
            view_direction=direction,
        )

        # TODO: 从 raw_result 提取 Edge2D 列表
        # data.visible_edges = self._hlr.extract_visible_edges(raw_result)
        # data.hidden_edges = self._hlr.extract_hidden_edges(raw_result)

        return data

    def project_all(self, shape) -> dict[ProjectionType, ProjectionData]:
        """生成标准三视图（正视图 + 俯视图 + 右侧视图）

        Args:
            shape: TopoDS_Shape

        Returns:
            视图类型 → 投影数据 的映射
        """
        views = {}
        for view_type in [ProjectionType.FRONT, ProjectionType.TOP, ProjectionType.RIGHT]:
            views[view_type] = self.project(shape, view_type)
        return views

    def project_all_six(self, shape) -> dict[ProjectionType, ProjectionData]:
        """生成全部六视图"""
        views = {}
        for view_type in self.VIEW_DIRECTIONS:
            views[view_type] = self.project(shape, view_type)
        return views
