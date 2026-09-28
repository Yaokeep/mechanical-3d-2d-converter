# -*- coding: utf-8 -*-
"""【第 1 层】读符号通道 —— DXF → 证据模型。

只依赖 ezdxf（默认 python 环境即可跑）；不做几何解释，不做视图归属。
"""
from .dxf_reader import classify_role, read_dxf, read_dxf_safe
from .model import (
    Dimension,
    Drawing,
    Evidence,
    Kind,
    ProjectionMethod,
    Role,
    View,
    ViewType,
)
from .text_parser import CutSpec, ParsedText, TextKind, parse_text

__all__ = [
    "classify_role", "read_dxf", "read_dxf_safe",
    "Dimension", "Drawing", "Evidence", "Kind",
    "ProjectionMethod", "Role", "View", "ViewType",
    "CutSpec", "ParsedText", "TextKind", "parse_text",
]
