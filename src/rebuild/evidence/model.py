# -*- coding: utf-8 -*-
"""证据模型（docs/ARCHITECTURE.md §4.2）。

这一层的职责是**忠实于文件、不做解释**：图纸里有什么图元就记什么，
角色分类给出的是 Claim（带依据、可以被后续推翻），不是硬结论。
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from ..model.claim import Claim
from ..model.geom2d import Arc2, BBox2, Circle2, Line2, Point2
from ..model.ids import EvidenceRef

Geom2D = Line2 | Arc2 | Circle2


class Kind(StrEnum):
    """图元的证据种类。"""

    EDGE = "edge"              # 棱边（实线/虚线）
    HATCH = "hatch"            # 剖面填充
    AXIS = "axis"              # 点划线：轴线 / 对称面
    DIMENSION = "dimension"    # 尺寸标注
    NOTE = "note"              # 文字标注（含剖面标题）
    BREAK = "break"            # 波浪线：视图断裂


class Role(StrEnum):
    """图元在制图语义里的角色（ARCHITECTURE §4.2）。

    角色本身是 Claim —— 有些是从线型/图层直接读出的约定，
    有些是推出来的，都允许被更强依据推翻。
    """

    VISIBLE = "visible"                  # 粗实线：可见轮廓
    HIDDEN = "hidden"                    # 虚线：被遮挡
    AXIS = "axis"                        # 点划线：轴线 / 对称面
    HATCH_BOUNDARY = "hatch_boundary"    # 剖面线边界
    BREAK_LINE = "break_line"            # 波浪线 / 双折线：视图断裂
    SECTION_CUT = "section_cut"          # 剖切线（切平面所在位置的粗短线）
    UNKNOWN = "unknown"


class ViewType(StrEnum):
    FRONT = "front"
    TOP = "top"
    LEFT = "left"
    RIGHT = "right"
    BOTTOM = "bottom"
    REAR = "rear"
    #: 侧视图但**左右未定** —— 如标签只写 "SIDE VIEW"/"侧视图"。
    #: 由 views/view_typer.py 依据位置 + 投影制消解（§3 原则二：歧义不提前消解）。
    SIDE = "side"
    SECTION = "section"      # 剖视图
    AUXILIARY = "auxiliary"  # 斜视图
    DETAIL = "detail"        # 局部放大


class ProjectionMethod(StrEnum):
    """投影制。**判错会让整个零件镜像** —— 必须从标题栏符号读，
    不能靠"Y 最高→top"的启发式（ARCHITECTURE §4.2）。"""

    FIRST_ANGLE = "first_angle"    # 第一角（GB/ISO 常用）
    THIRD_ANGLE = "third_angle"    # 第三角（ANSI 常用）


@dataclass(frozen=True)
class Evidence:
    """一个 DXF 图元。**未做解释** —— 只记录 + 一个可被推翻的角色 Claim。"""

    handle: EvidenceRef
    kind: Kind
    geom: Geom2D
    role: Claim[Role]
    layer: str = ""
    linetype: str = ""
    view: str = ""     # 由 views/view_detector.py 回填；空 = 尚未归属
    pattern: str = ""  # HATCH 的填充图案名

    @property
    def bbox(self) -> BBox2:
        """图元的包围盒。注意：圆弧按**整圆**算会虚胖（见 section_view.bbox_2d 注释），
        需要精确 bbox 时用 exact_bbox。"""
        g = self.geom
        if isinstance(g, Line2):
            return BBox2.of_points([g.start, g.end])
        return self.exact_bbox

    @property
    def exact_bbox(self) -> BBox2:
        """精确包围盒：圆弧按其真实张角计算端点与象限点。"""
        g = self.geom
        if isinstance(g, Line2):
            return BBox2.of_points([g.start, g.end])
        if isinstance(g, Circle2):
            return BBox2(g.center.x - g.radius, g.center.y - g.radius,
                         g.center.x + g.radius, g.center.y + g.radius)
        # Arc2：端点 + 落在张角内的四个象限点
        pts = [
            Point2(g.center.x + g.radius * math.cos(a),
                   g.center.y + g.radius * math.sin(a))
            for a in (g.start_angle, g.end_angle)
        ]
        for q in (0.0, math.pi / 2, math.pi, 3 * math.pi / 2):
            if _angle_in_span(q, g.start_angle, g.end_angle):
                pts.append(Point2(g.center.x + g.radius * math.cos(q),
                                  g.center.y + g.radius * math.sin(q)))
        return BBox2.of_points(pts)


def _angle_in_span(a: float, start: float, end: float) -> bool:
    """角度 a 是否落在从 start 逆时针到 end 的弧内（全部归一化到 [0, 2π)）。"""
    tau = 2 * math.pi
    a = (a - start) % tau
    span = (end - start) % tau
    if span == 0.0:
        span = tau
    return a <= span + 1e-12


@dataclass
class Dimension:
    """一条尺寸标注 —— **第 1 层的核心**。

    价值不在数值本身（那可以从几何量），而在 `p1/p2` 给出了
    「这个值标在哪段几何上」—— 直接得到「尺寸 ↔ 几何锚点」配对，
    不必去猜它在标谁（ARCHITECTURE §4.3 对应关系的来源之一）。
    """

    handle: EvidenceRef
    dimtype: str                  # linear / aligned / angular / diameter / radius / ordinate
    value: float | None           # 实测值；None = 无法确定
    p1: Point2 | None = None      # 被量的第一点（defpoint2）
    p2: Point2 | None = None      # 被量的第二点（defpoint3）
    p3: Point2 | None = None      # 定义点（defpoint），角度/半径类用
    text_override: str = ""       # 图中覆盖显示的文字（"<>" = 用实测值）
    layer: str = ""
    view: str = ""

    @property
    def is_overridden(self) -> bool:
        """标注文字被手工覆盖 ⇒ 显示值与实测值可能不一致 —— 本身就是信号。"""
        return bool(self.text_override) and self.text_override.strip() not in ("", "<>")


@dataclass
class View:
    """一个视图。frame 是视图局部系 → 图纸系的映射，由 views 层填写。"""

    id: str
    type: Claim[ViewType]
    method: Claim[ProjectionMethod] | None = None
    evidence: list[EvidenceRef] = field(default_factory=list)
    bbox: BBox2 | None = None
    label_handle: EvidenceRef | None = None
    #: 剖视图专用：切平面信息（由剖面标题文字解析而来）
    cut: Any | None = None

    @property
    def is_section(self) -> bool:
        return bool(self.type.is_settled and self.type.value == ViewType.SECTION)


@dataclass
class Drawing:
    """一张图纸的全部证据。**不做解释的完整记录**。"""

    path: str
    evidence: list[Evidence] = field(default_factory=list)
    texts: list[Any] = field(default_factory=list)        # list[ParsedText]
    dimensions: list[Dimension] = field(default_factory=list)
    views: list[View] = field(default_factory=list)
    layers: list[str] = field(default_factory=list)

    # ---- 查询辅助 ----

    def by_handle(self, handle: str) -> Evidence | None:
        for e in self.evidence:
            if e.handle == handle:
                return e
        return None

    def handles(self) -> set[str]:
        return {e.handle for e in self.evidence}

    def edges(self) -> list[Evidence]:
        return [e for e in self.evidence if e.kind in (Kind.EDGE, Kind.BREAK)]

    def axes(self) -> list[Evidence]:
        return [e for e in self.evidence if e.kind == Kind.AXIS]

    def hatches(self) -> list[Evidence]:
        return [e for e in self.evidence if e.kind == Kind.HATCH]

    def bbox(self) -> BBox2:
        boxes = [e.exact_bbox for e in self.evidence]
        if not boxes:
            raise ValueError("图纸里没有任何图元")
        out = boxes[0]
        for b in boxes[1:]:
            out = out.union(b)
        return out

    def kind_counts(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for e in self.evidence:
            key = f"{e.kind.value}/{e.role.value}"
            out[key] = out.get(key, 0) + 1
        return dict(sorted(out.items()))
