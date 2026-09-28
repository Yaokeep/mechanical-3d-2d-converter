# -*- coding: utf-8 -*-
"""假设模型：Part / Feature / Constraint（docs/ARCHITECTURE.md §4.4、§4.5）。

与几何求解无关 —— 这一层只描述"零件是什么"。
`verify/predict.py` 靠它解析地预测每个特征该在各视图里长什么样，
因此 verify 不需要造几何、也不需要 OCC（ARCHITECTURE §5 依赖规则 2）。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from .claim import Claim, Tier
from .geom import Axis3, Point3, Vector3
from .ids import EvidenceRef, FeatureId


class FeatureType(StrEnum):
    """特征类型。类型本身也可能是假设 —— 注意 Claim[FeatureType]。

    典型歧义："这个圆是孔还是凸台"在俯视图里**完全同形**，
    要靠主视图的虚实线才能定（ARCHITECTURE §3 原则二）。
    """

    BASE = "base"        # 基体（拉伸 / 回转）
    BOSS = "boss"        # 凸台
    POCKET = "pocket"    # 腔
    HOLE = "hole"        # 孔（通孔 / 盲孔用 params 区分）
    SLOT = "slot"        # 槽
    REVOLVE = "revolve"  # 回转特征
    FILLET = "fillet"    # 圆角
    CHAMFER = "chamfer"  # 倒角
    PATTERN = "pattern"  # 阵列（含螺栓分布圆）


class ConstraintType(StrEnum):
    """约束类型（ARCHITECTURE §4.5）。

    设计判据：图纸是**示意精确**的 —— 两条线是否相切/平行/同心**可信**，
    距离**不可信**。所以先抽关系再用尺寸定距离，能大幅减少反推。
    """

    # 尺寸
    DIM_VALUE = "dim_value"    # 某参数 = 某值
    CHAIN = "chain"            # 尺寸链闭合：Σ链 = 总长
    # 几何关系（可信）
    COINCIDENT = "coincident"
    TANGENT = "tangent"
    PARALLEL = "parallel"
    PERPENDICULAR = "perpendicular"
    CONCENTRIC = "concentric"
    COLLINEAR = "collinear"
    SYMMETRIC = "symmetric"
    EQUAL_RADIUS = "equal_radius"
    # 投影
    PROJECTS_TO = "projects_to"  # 3D 点 → 某视图中的 2D 点


@dataclass(frozen=True)
class Constraint:
    """一条约束。参数以字符串名引用 Feature.params 的键。"""

    type: ConstraintType
    refs: tuple[tuple[FeatureId, str], ...] = ()   # (特征, 参数名)
    value: Claim[Any] | None = None
    evidence: tuple[EvidenceRef, ...] = ()

    def __str__(self) -> str:
        names = [f"#{fid}.{p}" for fid, p in self.refs]
        return f"{self.type.value}({', '.join(names)})"


class OpenQuestion(StrEnum):
    """欠定项的种类 —— 报告里要明确告诉用户"缺什么"（§2 目标 4）。"""

    MISSING_DIMENSION = "缺尺寸标注"
    MISSING_SECTION_POS = "缺剖切位置"
    AMBIGUOUS_FEATURE = "特征歧义未消解"    # value 与 alternatives 并存
    MISSING_VIEW = "缺视图"
    UNREADABLE_NOTE = "标注无法解析"
    UNKNOWN_PROJECTION = "投影制未确定"      # 第一角/第三角判不出
    OUT_OF_DOMAIN = "超出解释域"             # 自由曲面等（§12）


@dataclass
class Question:
    """一个具体的"待确认"条目。"""

    kind: OpenQuestion
    detail: str
    view: str = ""
    evidence: tuple[EvidenceRef, ...] = ()
    candidates: tuple[Any, ...] = ()

    def __str__(self) -> str:
        loc = f"[{self.view}] " if self.view else ""
        return f"{loc}{self.kind.value}: {self.detail}"


@dataclass
class SymmetryOp:
    """对称操作：镜像面法向 + 面上一点。"""

    normal: Vector3
    point: Point3


@dataclass
class Feature:
    """一个 3D 特征假设。

    Attributes:
        depends_on: 布尔序 —— SW `SetAddToDB` 那课的教训（CLAUDE.md
            "SetAddToDB 两面性"）：孔的草图必须不吸附、boss 草图必须吸附，
            顺序与依赖错则特征静默失败。所以依赖关系是一等公民。
        evidence:   这个特征的图纸依据。**空 evidence 的特征就是纯猜**，
                    进"待确认"。
    """

    id: FeatureId
    type: Claim[FeatureType]
    params: dict[str, Claim[Any]] = field(default_factory=dict)
    placement: Claim[Any] = field(
        default_factory=lambda: Claim(Point3(0.0, 0.0, 0.0), "default", Tier.GUESS)
    )
    axis: Claim[Axis3] | None = None
    depends_on: list[FeatureId] = field(default_factory=list)
    evidence: list[EvidenceRef] = field(default_factory=list)
    source_view: str = ""
    #: 由 verify/predict 回填：预测的 2D 图元在该视图里是否找到匹配
    verified: bool | None = None

    @property
    def is_hypothesis(self) -> bool:
        """类型本身还没定（孔 vs 凸台的歧义未消解）。"""
        return not self.type.is_settled

    def param(self, name: str) -> Claim[Any]:
        """取参数；不存在即报错（宁可炸也不要静默给出 0）。"""
        if name not in self.params:
            raise KeyError(f"特征 #{self.id} 没有参数 {name!r}（现有：{list(self.params)}）")
        return self.params[name]

    def __str__(self) -> str:
        t = self.type.value if self.type.is_settled else f"{self.type.value}|歧义"
        return f"#{self.id} {t} ({len(self.params)} 参数)"


@dataclass
class Part:
    """完整的零件假设。verify/gate 的输入。"""

    features: list[Feature] = field(default_factory=list)
    symmetry: list[Claim[SymmetryOp]] = field(default_factory=list)
    constraints: list[Constraint] = field(default_factory=list)
    questions: list[Question] = field(default_factory=list)

    def add(self, feature: Feature) -> Feature:
        self.features.append(feature)
        return feature

    def by_id(self, fid: FeatureId) -> Feature:
        for f in self.features:
            if f.id == fid:
                return f
        raise KeyError(f"没有特征 #{fid}")

    def next_id(self) -> FeatureId:
        return FeatureId(max((f.id for f in self.features), default=-1) + 1)

    # ---- gate 用的聚合查询（第 4 层就建在这些上面） ----

    def unresolved_features(self) -> list[Feature]:
        """类型或参数仍有歧义/纯猜的特征。"""
        out: list[Feature] = []
        for f in self.features:
            claims = [f.type, *f.params.values(), f.placement]
            if f.axis is not None:
                claims.append(f.axis)
            if any((not c.is_settled) or c.is_guessed or not c.evidence for c in claims):
                out.append(f)
        return out

    def unexplained_evidence(self, all_handles: set[str]) -> list[EvidenceRef]:
        """图纸里没有被任何特征解释的图元 —— 双向覆盖率的一半（§6.3）。"""
        used: set[str] = set()
        for f in self.features:
            used.update(f.evidence)
            for c in f.params.values():
                used.update(c.evidence)
        return [EvidenceRef(h) for h in sorted(all_handles - used)]
