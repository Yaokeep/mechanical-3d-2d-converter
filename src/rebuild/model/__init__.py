# -*- coding: utf-8 -*-
"""中间表示（IR）—— 零依赖的纯数据层。

依赖规则（docs/ARCHITECTURE.md §5）：本包**不依赖任何其他包**，
保证 IR 可独立测试、可序列化、可 diff。
"""
from .claim import TIER_LABEL, Claim, Tier, merge
from .feature_tree import (
    Constraint,
    ConstraintType,
    Feature,
    FeatureType,
    OpenQuestion,
    Part,
    Question,
    SymmetryOp,
)
from .geom import AXIS_BY_NAME, AXIS_X, AXIS_Y, AXIS_Z, Axis3, Point3, Vector3
from .geom2d import Arc2, BBox2, Circle2, Line2, Point2
from .ids import ConflictError, EvidenceRef, FeatureId, UnderDetermined, ViewId

__all__ = [
    "TIER_LABEL", "Claim", "Tier", "merge",
    "Constraint", "ConstraintType", "Feature", "FeatureType",
    "OpenQuestion", "Part", "Question", "SymmetryOp",
    "AXIS_BY_NAME", "AXIS_X", "AXIS_Y", "AXIS_Z", "Axis3", "Point3", "Vector3",
    "Arc2", "BBox2", "Circle2", "Line2", "Point2",
    "ConflictError", "EvidenceRef", "FeatureId", "UnderDetermined", "ViewId",
]
