# -*- coding: utf-8 -*-
"""标识类型（docs/ARCHITECTURE.md §4）。

约定：同一张图纸内 DXF handle 唯一，因此 provenance 锚点只需 handle。
"""
from __future__ import annotations

from typing import NewType

# 视图标识：由 views/view_detector.py 分配（如 "front" / "top" / "section:B"）
ViewId = NewType("ViewId", str)

# 特征标识：假设模型内的自增序号
FeatureId = NewType("FeatureId", int)


class EvidenceRef(str):
    """DXF 图元 handle —— provenance 的锚点。

    故意做成 str 子类：查 Evidence 表时可直接当字符串用，
    类型标注上又能与普通字符串区分开（防止某天把某段文字当成 handle）。
    """

    __slots__ = ()


class ConflictError(Exception):
    """约束系统过定（图纸自相矛盾）。

    这是**特性不是错误** —— 线框与标注不一致时用户必须知道，
    见 docs/ARCHITECTURE.md §6.2。
    """

    def __init__(self, message: str, refs: tuple[EvidenceRef, ...] = ()) -> None:
        super().__init__(message)
        self.refs = refs


class UnderDetermined(Exception):
    """约束系统欠定 —— 信息不足，应产出 OpenQuestion 而非硬猜。"""
