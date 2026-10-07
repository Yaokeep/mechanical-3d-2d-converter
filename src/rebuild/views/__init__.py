# -*- coding: utf-8 -*-
"""视图层 —— 分离、定性、跨视图对应（ARCHITECTURE §6.1）。

分离（view_detector）只看几何邻近；定性（view_typer）看标签与布局；
对应（correspondence）把各视图的 2D 证据拼成 3D 位置/轴线。
三者都只用 ezdxf 级依赖，跑默认 python。
"""
from .correspondence import (
    CorrKind, Correspondence, CorrespondenceResult, CylinderHint, ViewFrame,
    build_correspondence, describe,
)
from .ring import Ring, RingResult, RingSeg, extract_ring
from .view_detector import DetectParams, detect_views
from .view_typer import describe_views, type_views

__all__ = [
    "CorrKind", "Correspondence", "CorrespondenceResult", "CylinderHint",
    "DetectParams", "Ring", "RingResult", "RingSeg", "ViewFrame",
    "build_correspondence", "describe", "describe_views", "detect_views",
    "extract_ring", "type_views",
]
