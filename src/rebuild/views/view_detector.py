# -*- coding: utf-8 -*-
"""视图分离（ARCHITECTURE §4.2、§6.1）。

两段式 1D 间隙聚类（沿用旧管线验证过的思路）：
先按 Y 把图面切成**行**，再在每行内按 X 切成**视图**。
视图之间的空白间隙是唯一可靠的分离信号 —— 不依赖图层或命名。

**只做分离与归属，不做定性**：视图类型由 ``view_typer.py`` 依据
标签/布局/投影制判定；本模块只回答两件事——

1. 哪些图元属于同一簇（``View.evidence``）
2. 文字/尺寸**归属**到哪一簇（``View.annotations`` / ``label_handle`` / ``cut``）

轴线（点划线）**不参与**包围盒计算 —— 中心线两端会伸出零件外，
计入会把视图包围盒撑大，进而算错期望尺寸。它们按自身中心点归属。

视图归属的真相只有一处：``View.evidence`` + ``View.annotations``，
反查走 ``Drawing.view_of()``。``Evidence`` 是 frozen 的、**不带** view 字段，
这样不存在"两个地方记着同一个事实然后对不上"的可能。
"""
from __future__ import annotations

from dataclasses import dataclass

from ..evidence.model import Dimension, Drawing, Evidence, Kind, Role, View
from ..evidence.text_parser import ParsedText, TextKind
from ..model.geom2d import BBox2, Point2


@dataclass
class DetectParams:
    """分离参数。

    gap_abs:  最小间隙绝对值（mm）—— 小于它的空隙不算视图分界
    gap_frac: 间隙占图面跨度的比例 —— 大图需要更大的绝对间隙
    实际阈值为两者的较大者（照旧管线 ``max(30, Y簇宽×20%)`` 的形式，
    但比例调小：那条经验值是针对 bracket 单张图调的，对多视图图纸会过度合并）
    """

    gap_abs: float = 8.0
    gap_frac: float = 0.04


def _cluster_1d(spans: list[tuple[float, float]], gap: float) -> list[list[int]]:
    """把一维区间聚类：空隙 > gap 即切开。

    Args:
        spans: [(lo, hi), ...]
    Returns:
        每组的索引列表，按位置升序
    """
    if not spans:
        return []
    order = sorted(range(len(spans)), key=lambda i: (spans[i][0], spans[i][1]))
    groups: list[list[int]] = [[order[0]]]
    cur_end = spans[order[0]][1]
    for i in order[1:]:
        lo, hi = spans[i]
        if lo - cur_end > gap:
            groups.append([i])
            cur_end = hi
        else:
            groups[-1].append(i)
            cur_end = max(cur_end, hi)
    return groups


def _bbox_of(items: list[Evidence]) -> BBox2:
    boxes = [e.exact_bbox for e in items]
    out = boxes[0]
    for b in boxes[1:]:
        out = out.union(b)
    return out


def _center(b: BBox2) -> Point2:
    return Point2((b.xmin + b.xmax) / 2.0, (b.ymin + b.ymax) / 2.0)


def _bbox_distance(b: BBox2, p: Point2) -> float:
    """点到包围盒的距离；点在盒内为 0。"""
    dx = max(b.xmin - p.x, 0.0, p.x - b.xmax)
    dy = max(b.ymin - p.y, 0.0, p.y - b.ymax)
    return (dx * dx + dy * dy) ** 0.5


def _nearest_view(views: list[View], p: Point2) -> View | None:
    """探针点归到最近的视图。

    先比"点到盒"的距离（盒内为 0），同距再比"点到盒心"——
    后者让落在两个视图之间的文字有一个确定的归属，而不是看遍历顺序。
    """
    best: View | None = None
    best_key: tuple[float, float] | None = None
    for v in views:
        if v.bbox is None:
            continue
        d_box = _bbox_distance(v.bbox, p)
        c = _center(v.bbox)
        d_ctr = ((c.x - p.x) ** 2 + (c.y - p.y) ** 2) ** 0.5
        key = (d_box, d_ctr)
        if best_key is None or key < best_key:
            best_key, best = key, v
    return best


def _probe_of_dim(dim: Dimension) -> Point2 | None:
    """尺寸标注的探针点：取被量两点的中点（最贴近它描述的位置）。"""
    if dim.p1 is not None and dim.p2 is not None:
        return Point2((dim.p1.x + dim.p2.x) / 2.0, (dim.p1.y + dim.p2.y) / 2.0)
    return dim.p3 or dim.p1 or dim.p2


def detect_views(d: Drawing, params: DetectParams | None = None) -> list[View]:
    """把证据聚成视图，并把文字/尺寸/轴线归属到各视图。

    副作用：填充 ``Drawing.views``。返回同一列表。
    视图 id 形如 ``V0``/``V1``…，按**先上后下、先左后右**编号，跨次运行稳定。
    """
    p = params or DetectParams()

    # ---- 参与分离的几何：轮廓边与 HATCH 边界 ----
    # 排除三类，各有理由：
    #  - Kind.HATCH：本体的 geom 只是个占位对角线段（真实形状在它的边界图元里），
    #    让它参与会把视图包围盒撑成对角线
    #  - Role.SECTION_CUT：剖切线画在视图**外**（两端伸出并带箭头），
    #    实测把 bracket 俯视图的纵向尺寸从 51 撑到 67（+31%）
    #  - Kind.AXIS / Kind.BREAK：轴线的 kind 不是 EDGE，天然排除
    # 这些图元仍归属到视图（见 _assign），只是不参与定包围盒。
    geom = [e for e in d.evidence
            if e.kind == Kind.EDGE and e.role.value != Role.SECTION_CUT]
    if not geom:
        d.views = []
        return []

    boxes = [e.exact_bbox for e in geom]
    span_y = max(b.ymax for b in boxes) - min(b.ymin for b in boxes)
    span_x = max(b.xmax for b in boxes) - min(b.xmin for b in boxes)
    gap_y = max(p.gap_abs, span_y * p.gap_frac)
    gap_x = max(p.gap_abs, span_x * p.gap_frac)

    # ---- 第一段：按 Y 切行 ----
    rows = _cluster_1d([(b.ymin, b.ymax) for b in boxes], gap_y)

    # ---- 第二段：行内按 X 切视图 ----
    groups: list[list[int]] = []
    for row in rows:
        sub = [(boxes[i].xmin, boxes[i].xmax) for i in row]
        for col in _cluster_1d(sub, gap_x):
            groups.append([row[j] for j in col])

    # 按位置排序（先上后下、先左后右），使 id 稳定可预期
    groups.sort(key=lambda g: (-max(boxes[i].ymax for i in g),
                               min(boxes[i].xmin for i in g)))

    views: list[View] = []
    for n, g in enumerate(groups):
        members = [geom[i] for i in g]
        views.append(View(
            id=f"V{n}",
            # type 不传 —— 默认即"未定性"（tier=GUESS）。定性是 view_typer 的事；
            # 这里若顺手给个 FRONT，下游会误以为已知
            evidence=[m.handle for m in members],
            bbox=_bbox_of(members),
        ))

    _assign(d, views, clustered={m.handle for m in geom})

    d.views = views
    return views


def _assign(d: Drawing, views: list[View], clustered: set[str]) -> None:
    """把未参与聚类的图元归属到视图。

    归类：轴线 / 填充本体 / 剖切线 → ``evidence``；文字 / 尺寸 → ``annotations``。
    归属判据是**位置**（几何邻近），不是图层或命名 —— 与分离阶段同一套信号。
    """
    if not views:
        return

    # ---- 轴线、填充本体、剖切线：属于某个视图的图元 ----
    # 它们不参与聚类（会撑大包围盒或跨视图），故按自身几何中心就近归属
    for e in d.evidence:
        if e.handle in clustered:
            continue
        v = _nearest_view(views, _center(e.exact_bbox))
        if v is not None:
            v.evidence.append(e.handle)

    # ---- 文字 ----
    label_dist: dict[str, float] = {}
    for t in d.texts:
        pt = Point2(t.x, t.y)
        v = _nearest_view(views, pt)
        if v is None:
            continue
        v.annotations.append(t.handle)
        if t.kind == TextKind.VIEW_LABEL:
            _set_label(v, t, pt, label_dist)
        elif t.kind == TextKind.SECTION_TITLE and t.cut is not None:
            v.cut = t.cut

    # ---- 尺寸标注 ----
    for dim in d.dimensions:
        probe = _probe_of_dim(dim)
        if probe is None:
            continue
        v = _nearest_view(views, probe)
        if v is not None:
            v.annotations.append(dim.handle)


def _set_label(v: View, t: ParsedText, pt: Point2,
               dist: dict[str, float]) -> None:
    """给视图挂标签 handle —— 同一视图挂多个标签时取离包围盒最近的。

    视图标签通常紧贴视图下方/上方，但技术要求里也可能出现"主视图"字样，
    故取最近者而不是先到者。``dist`` 是本次调用的过程量，不进 IR。
    """
    d_new = _bbox_distance(v.bbox, pt) if v.bbox is not None else 0.0
    if v.label_handle is None or d_new < dist.get(v.id, float("inf")):
        v.label_handle = t.handle
        dist[v.id] = d_new
