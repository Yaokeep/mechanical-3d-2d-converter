# -*- coding: utf-8 -*-
"""特征层（ARCHITECTURE §5 第 3 层）—— 证据 + 对应 + 约定 ⇒ 特征树。

    library.py     特征词典：参数契约（PARAMS/OPTIONAL_PARAMS）、轮廓基向量、
                   建造顺序、逐类型"该在各视图里长什么样"的预测
    recognizer.py  识别：把三路来源（剖面标题 / 跨视图对应 / 约定）装成 Part
    prior.py       标准值先验：图纸没写但标准里有的信息（R8 vs R8.5 的落点）
    solver.py      约束传播 + 一致性检查（合并带冲突检测、关系抽取）

依赖方向：``features → model, evidence, views, conventions``；
``features`` **不依赖** ``verify``/``emit``（发射器反过来依赖本层的参数契约）。
解释器：本层只需 ezdxf+numpy，**跑默认 python**。
"""
from __future__ import annotations

from . import library, prior, recognizer, solver
from .library import (
    LAYER, OPTIONAL_PARAMS, PARAMS, Prim3, build_order, ir_coords, ir_point,
    predict_in_view, profile_plane,
)
from .prior import (
    DRILL_D, PREFERRED_R, Snap, snap_claim, snap_diameter, snap_radius,
)
from .recognizer import RecognizeReport, recognize
from .solver import (
    Conflict, Refinement, SolveReport, merge_with_conflict, solve,
)

__all__ = [
    "Conflict", "DRILL_D", "LAYER", "OPTIONAL_PARAMS", "PARAMS", "PREFERRED_R",
    "Prim3", "RecognizeReport", "Refinement", "Snap", "SolveReport",
    "build_order", "ir_coords", "ir_point", "library", "merge_with_conflict",
    "predict_in_view", "prior", "profile_plane", "recognize", "recognizer",
    "snap_claim", "snap_diameter", "snap_radius", "solve", "solver",
]
