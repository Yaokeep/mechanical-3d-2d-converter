# -*- coding: utf-8 -*-
"""视图层 —— 分离、定性、跨视图对应（ARCHITECTURE §6.1）。

分离（view_detector）只看几何邻近；定性（view_typer）看标签与布局；
两者都只用 ezdxf 级依赖，跑默认 python。
"""
from .view_detector import DetectParams, detect_views
from .view_typer import describe_views, type_views

__all__ = ["DetectParams", "detect_views", "type_views", "describe_views"]
