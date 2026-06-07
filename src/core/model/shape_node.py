# 机械三维二维图互转 — 形状树节点

from dataclasses import dataclass, field
from typing import Optional, Any


@dataclass
class ShapeNode:
    """形状树节点

    封装一个 OpenCASCADE TopoDS_Shape，维护其在项目树中的父子关系。
    支持元数据扩展（颜色、材质、变换等）。
    """

    name: str                                   # 唯一名称
    shape: Any = None                            # TopoDS_Shape 实例
    parent: Optional["ShapeNode"] = None         # 父节点
    children: list["ShapeNode"] = field(default_factory=list)

    # 属性
    visible: bool = True
    color: tuple[float, float, float] = (0.7, 0.7, 0.7)  # RGB
    transparency: float = 0.0

    # 元数据
    metadata: dict = field(default_factory=dict)

    def add_child(self, child: "ShapeNode") -> None:
        """添加子节点"""
        child.parent = self
        self.children.append(child)

    def remove_child(self, child: "ShapeNode") -> None:
        """移除子节点"""
        if child in self.children:
            child.parent = None
            self.children.remove(child)

    def is_leaf(self) -> bool:
        """是否为叶节点"""
        return len(self.children) == 0

    def is_root(self) -> bool:
        """是否为根节点"""
        return self.parent is None

    def path(self) -> str:
        """获取从根到当前节点的路径字符串"""
        if self.parent and self.parent.shape is not None:
            return f"{self.parent.path()}/{self.name}"
        return self.name

    def depth(self) -> int:
        """获取在树中的深度"""
        if self.parent is None:
            return 0
        return self.parent.depth() + 1

    def __repr__(self) -> str:
        children_count = len(self.children)
        return f"ShapeNode(name={self.name!r}, children={children_count})"
