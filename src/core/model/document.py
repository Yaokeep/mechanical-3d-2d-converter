# 机械三维二维图互转 — 项目文档模型

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
from enum import Enum, auto


class DocumentState(Enum):
    """文档状态"""
    EMPTY = auto()           # 空文档
    MODIFIED = auto()        # 已修改（未保存）
    SAVED = auto()           # 已保存


@dataclass
class Document:
    """项目文档——内存中的模型容器

    管理所有导入的形状节点树，跟踪文件状态和修改标记。
    是核心数据模型的顶层容器。
    """

    name: str = "未命名项目"
    file_path: Optional[Path] = None
    state: DocumentState = DocumentState.EMPTY

    # 形状节点树（名称 → 节点）
    _shapes: dict[str, "ShapeNode"] = field(default_factory=dict)
    # 节点树根
    _root: Optional["ShapeNode"] = None

    # ------------------------- 形状管理 -------------------------

    def add_shape(self, name: str, shape, parent_name: Optional[str] = None) -> "ShapeNode":
        """添加一个形状到文档中

        Args:
            name: 形状唯一名称
            shape: TopoDS_Shape 实例
            parent_name: 父节点名称（None 表示加入根级别）

        Returns:
            创建的 ShapeNode
        """
        from src.core.model.shape_node import ShapeNode

        node = ShapeNode(name=name, shape=shape)

        if parent_name and parent_name in self._shapes:
            parent_node = self._shapes[parent_name]
            parent_node.add_child(node)
        else:
            if self._root is None:
                self._root = ShapeNode(name="root", shape=None)
            self._root.add_child(node)

        self._shapes[name] = node
        self._mark_modified()
        return node

    def remove_shape(self, name: str) -> bool:
        """移除指定形状

        Returns:
            是否成功移除
        """
        if name not in self._shapes:
            return False

        node = self._shapes.pop(name)
        if node.parent:
            node.parent.remove_child(node)
        self._mark_modified()
        return True

    def get_shape(self, name: str):
        """根据名称获取 TopoDS_Shape（可能为 None）"""
        node = self._shapes.get(name)
        return node.shape if node else None

    def get_node(self, name: str) -> Optional["ShapeNode"]:
        """根据名称获取 ShapeNode"""
        return self._shapes.get(name)

    def get_all_shapes(self) -> dict[str, "ShapeNode"]:
        """获取所有形状节点"""
        return dict(self._shapes)

    def clear(self) -> None:
        """清空文档"""
        self._shapes.clear()
        self._root = None
        self.state = DocumentState.EMPTY
        self.file_path = None

    # ------------------------- 状态管理 -------------------------

    def _mark_modified(self) -> None:
        """标记文档已修改"""
        self.state = DocumentState.MODIFIED

    def mark_saved(self, path: Optional[Path] = None) -> None:
        """标记文档已保存"""
        if path:
            self.file_path = path
        self.state = DocumentState.SAVED

    @property
    def is_modified(self) -> bool:
        """文档是否有未保存的修改"""
        return self.state == DocumentState.MODIFIED

    @property
    def is_empty(self) -> bool:
        """文档是否为空"""
        return len(self._shapes) == 0

    @property
    def shape_count(self) -> int:
        """文档中的形状数量"""
        return len(self._shapes)

    def __repr__(self) -> str:
        return f"Document(name={self.name!r}, shapes={self.shape_count}, state={self.state.name})"
