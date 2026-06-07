# 机械三维二维图互转 — 线框→面生成器

from typing import Any


class FaceBuilder:
    """面生成器

    从闭合 TopoDS_Wire 创建平面 TopoDS_Face。
    使用 BRepBuilderAPI_MakeFace。
    """

    def build_face(self, wire) -> Any:
        """从闭合线框创建平面

        Args:
            wire: 闭合 TopoDS_Wire

        Returns:
            TopoDS_Face
        """
        # TODO: BRepBuilderAPI_MakeFace(wire).Face()
        return None

    def build_face_from_wires(self, outer_wire, inner_wires: list = None) -> Any:
        """从外轮廓和多个内轮廓创建带孔的面

        Args:
            outer_wire: 外轮廓线框
            inner_wires: 内轮廓线框列表（孔洞）

        Returns:
            TopoDS_Face
        """
        # TODO: BRepBuilderAPI_MakeFace(outer_wire)
        # for inner in inner_wires:
        #     builder.Add(inner)
        return None
