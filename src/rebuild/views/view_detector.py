# -*- coding: utf-8 -*-
"""视图分离（ARCHITECTURE §4.2、§6.1）。

**递归 XY 切分**（1D 间隙聚类，交替按 Y/按 X）：空隙 > 阈值即切开，
切完的每一半递归再切，直至两向都切不动 —— 那一块就是一个视图。
视图之间的空白间隙是唯一可靠的分离信号 —— 不依赖图层或命名。

**为什么不是"先切行、再在行内切列"的两段式**（2026-10-12，YZYX 齿箱上盖）：
两段式在"同列内上下堆叠、且与邻列视图在 y 上重叠"的布局上**结构性失效**——
YZYX 右列的「c 向」局部视图（y[1194.3,1315.3]）与下方大拱视图（y[896.1,1083.6]）
之间空着 110.7mm（阈值才 34.9），却因为左列俯视图的 y 跨度盖住了这个区间，
两视图被提前并进同一**行**；行内按 X 切时两者 x 完全重合（同列），y 信息
已被丢弃 ⇒ 永远切不开。递归切分在每个子块上重新问"还有没有 y 向空隙"，
故 5 个视图逐层切出（切法见 ``_xy_cut`` 注释）。

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


def _xy_cut(idx: list[int], boxes: list[BBox2],
            gap_x: float, gap_y: float) -> list[list[int]]:
    """递归 XY 切分：每一块上先试 y 向空隙、再试 x 向，切不动即为一个视图。

    ``idx`` 是 ``boxes`` 的下标子集；返回的每组的元素是**原下标**。

    先 y 后 x（而非"取最大空隙"）：与两段式时代的切分顺序一致，
    使存量靶子的行列归属不变（递归只在"行内列上还能再切 y"时才是新行为）。

    YZYX 的切法：整图 y 上有 225.9mm 空隙 ⇒ {TL,TR} / {BL,mid,DR}；
    上块再按 x 切成 TL、TR；下块 y 向切不动（俯视图盖住），按 x 切成
    BL / {mid,DR}；``{mid,DR}`` 上重问 y —— 110.7mm 空隙在此切开。
    """
    if len(idx) <= 1:
        return [list(idx)]
    rows = _cluster_1d([(boxes[i].ymin, boxes[i].ymax) for i in idx], gap_y)
    if len(rows) > 1:
        out: list[list[int]] = []
        for r in rows:
            out.extend(_xy_cut([idx[j] for j in r], boxes, gap_x, gap_y))
        return out
    cols = _cluster_1d([(boxes[i].xmin, boxes[i].xmax) for i in idx], gap_x)
    if len(cols) > 1:
        out = []
        for c in cols:
            out.extend(_xy_cut([idx[j] for j in c], boxes, gap_x, gap_y))
        return out
    return [list(idx)]


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


_FRAME_TOL = 0.5          # 边框线到图面外沿的容差（mm）
_FRAME_SIDE_FRAC = 0.95   # 边框边必须覆盖该侧 ≥95% 的长度
_FRAME_SPAN_FRAC = 0.8    # 长线门限：至少覆盖图面该向跨度的 80%
_FRAME_MIN_VIEW_ELEMS = 8 # 框内"够一个视图"的图元数下限
_FRAME_MIN_VIEWS = 2      # 框内至少要有这么多个"视图量级"的簇


def _inside(outer: BBox2, b: BBox2) -> bool:
    """b 完全落在 outer 内（含容差）。"""
    return (b.xmin >= outer.xmin - _FRAME_TOL
            and b.xmax <= outer.xmax + _FRAME_TOL
            and b.ymin >= outer.ymin - _FRAME_TOL
            and b.ymax <= outer.ymax + _FRAME_TOL)


def _outside(outer: BBox2, b: BBox2) -> bool:
    """b 与 outer 完全不相交（框外家具的判据）。"""
    return (b.xmax < outer.xmin - _FRAME_TOL
            or b.xmin > outer.xmax + _FRAME_TOL
            or b.ymax < outer.ymin - _FRAME_TOL
            or b.ymin > outer.ymax + _FRAME_TOL)


def _view_sized_clusters(elems: list[Evidence], gap_x: float, gap_y: float,
                         min_elems: int) -> int:
    """数出这些图元里有多少个"视图量级"（≥min_elems 图元）的簇。

    簇的定义与 ``detect_views`` 同源（同一个 ``_xy_cut``）—— 两处若各用一套，
    "框内够两个视图"这条护栏就会与真正的分离结果对不上。
    """
    if not elems:
        return 0
    boxes = [e.exact_bbox for e in elems]
    return sum(1 for g in _xy_cut(list(range(len(boxes))), boxes, gap_x, gap_y)
               if len(g) >= min_elems)


def _frame_by_long_lines(geom: list[Evidence], gap_x: float, gap_y: float
                         ) -> tuple[set[str], BBox2] | None:
    """长线成矩 + 框内数得出 ≥2 个视图 ⇒ 图纸外框（**不必落在图面外沿**）。

    判据演变（2026-10-12，YZYX 齿箱上盖图纸）：原判据要求边框边正好落在
    图面**最外沿**（±0.5mm）——对 `图形练习`/`法兰练习` 够用，那两张图的
    边框就是最外沿。但正式生产图纸在边框外还画着**对中符号、装订边刻度、
    图幅分区标记**（YZYX 共 12 条，把图面外沿撑出 30~75mm），"最外沿"判据
    随即失效：边框四条长线把全图**桥接**成一个簇（实测 259 图元 → 1 个
    1782×1260 的"视图"、特征树 0 条）。

    故补一条不依赖外沿的判据。三条护栏把它与"方形零件自己的轮廓"分开
    ——零件的轮廓同样能凑出长线矩形，误判等于把零件删掉：
    ① 四条边要**正好**是矩形边长（伸出矩形外的不算：L 形零件的长短边
       凑不出严格矩形）；
    ② 框内要数得出 ≥`_FRAME_MIN_VIEWS` 个 ≥`_FRAME_MIN_VIEW_ELEMS` 图元的
       簇——视图是几十上百图元的，零件内部的孔只有 1~4 图元；
    ③ 排除四边后仍剩 ≥3 图元。
    """
    if len(geom) < 5:
        return None
    boxes = [e.exact_bbox for e in geom]
    span_x = max(b.xmax for b in boxes) - min(b.xmin for b in boxes)
    span_y = max(b.ymax for b in boxes) - min(b.ymin for b in boxes)

    hs: list[tuple[Evidence, BBox2]] = []
    vs: list[tuple[Evidence, BBox2]] = []
    for e, b in zip(geom, boxes):
        if b.ymax - b.ymin <= _FRAME_TOL:
            if b.xmax - b.xmin >= _FRAME_SPAN_FRAC * span_x:
                hs.append((e, b))
        elif b.xmax - b.xmin <= _FRAME_TOL:
            if b.ymax - b.ymin >= _FRAME_SPAN_FRAC * span_y:
                vs.append((e, b))
    if len(hs) < 2 or len(vs) < 2:
        return None

    h_lo = min(hs, key=lambda t: t[1].ymin)     # 下边
    h_hi = max(hs, key=lambda t: t[1].ymax)     # 上边
    v_lo = min(vs, key=lambda t: t[1].xmin)     # 左边
    v_hi = max(vs, key=lambda t: t[1].xmax)     # 右边
    rect = BBox2(v_lo[1].xmin, h_lo[1].ymin, v_hi[1].xmax, h_hi[1].ymax)

    # ① 四边正好是矩形的边 —— 伸出去/缩进去都不算（护栏，不是尺度判断）
    if any(abs(b.xmin - rect.xmin) > _FRAME_TOL
           or abs(b.xmax - rect.xmax) > _FRAME_TOL for _, b in (h_lo, h_hi)):
        return None
    if any(abs(b.ymin - rect.ymin) > _FRAME_TOL
           or abs(b.ymax - rect.ymax) > _FRAME_TOL for _, b in (v_lo, v_hi)):
        return None

    frame = {t[0].handle for t in (h_lo, h_hi, v_lo, v_hi)}
    rest = [e for e in geom if e.handle not in frame]
    if len(rest) < 3:
        return None                              # ③ 排除后没东西了 ⇒ 那是零件
    inside = [e for e in rest if _inside(rect, e.exact_bbox)]
    if _view_sized_clusters(inside, gap_x, gap_y,
                            _FRAME_MIN_VIEW_ELEMS) < _FRAME_MIN_VIEWS:
        return None                              # ② 框内凑不出两个视图
    return frame, rect


def _frame_by_outer_edge(geom: list[Evidence]) -> tuple[set[str], BBox2] | None:
    """边框正好落在**图面最外沿**的图纸外框（原判据，保留作为退路）。

    外框是视图分离的头号干扰源：它的四条边横跨整张图，二维间隙聚类
    看到的是"所有图元都在它里面" ⇒ 整张图被聚成**一簇**，视图定性随之
    全线失败。实测 `CAD/图形练习.dxf`：A4 外框 + 俯视图（正方形带对角线）
    + 两个三角形视图被并成一个 256×297 的"视图"，而它其实是标准三视图。

    判据（要求四侧俱全，避免把"零件本身就是个矩形"误判成外框）：
    图面外沿的每一侧都有一条与之重合、且覆盖该侧 ≥95% 的**轴对齐直线**。
    再加两道护栏：排除后必须还剩 ≥3 个图元；且外框内必须真圈着东西。
    """
    if len(geom) < 5:
        return None
    boxes = [e.exact_bbox for e in geom]
    gx0 = min(b.xmin for b in boxes)
    gx1 = max(b.xmax for b in boxes)
    gy0 = min(b.ymin for b in boxes)
    gy1 = max(b.ymax for b in boxes)

    out: set[str] = set()
    # 四侧：(是否水平, 该侧所在的坐标, 该侧沿线方向的区间)
    sides = ((True, gy0, (gx0, gx1)), (True, gy1, (gx0, gx1)),
             (False, gx0, (gy0, gy1)), (False, gx1, (gy0, gy1)))
    for horiz, at, (s_lo, s_hi) in sides:
        best: tuple[float, str] | None = None
        for e, b in zip(geom, boxes):
            if horiz:
                flat = b.ymax - b.ymin <= _FRAME_TOL and \
                    abs((b.ymin + b.ymax) / 2.0 - at) <= _FRAME_TOL
                span = (b.xmin, b.xmax)
            else:
                flat = b.xmax - b.xmin <= _FRAME_TOL and \
                    abs((b.xmin + b.xmax) / 2.0 - at) <= _FRAME_TOL
                span = (b.ymin, b.ymax)
            if not flat:
                continue
            if span[0] - s_lo > _FRAME_TOL or s_hi - span[1] > _FRAME_TOL:
                continue                                   # 没铺满这一侧
            if (span[1] - span[0]) < _FRAME_SIDE_FRAC * (s_hi - s_lo):
                continue
            if best is None or (span[1] - span[0]) > best[0]:
                best = (span[1] - span[0], e.handle)
        if best is not None:
            out.add(best[1])

    if len(out) < 4:
        return None                                        # 四侧不齐 ⇒ 不是外框
    rest = [e for e in geom if e.handle not in out]
    if len(rest) < 3:
        return None                                        # 排除后没东西了 ⇒ 那是零件
    inside = any(gx0 < (b.xmin + b.xmax) / 2.0 < gx1
                 and gy0 < (b.ymin + b.ymax) / 2.0 < gy1 for b in
                 [e.exact_bbox for e in rest])
    if not inside:
        return None                                        # 框里得真圈着东西
    return out, BBox2(gx0, gy0, gx1, gy1)


def _sheet_frame(geom: list[Evidence], gap_x: float, gap_y: float
                 ) -> tuple[set[str], BBox2 | None]:
    """识别图纸**外框与框外家具**，返回 ``(要排除的 handle 集合, 外框矩形)``。

    两条判据依次尝试，都不成则返回 ``(set(), None)``：

    1. `_frame_by_long_lines` —— 长线成矩 + 框内数得出 ≥2 个视图。
       **不要求框在图面外沿**，故正式图纸在框外画了家具也照样认得出。
    2. `_frame_by_outer_edge` —— 边框正好落在图面最外沿（原判据，留作退路）。

    外框一旦定出，**框外的一切都是图纸家具**（对中符号、装订边刻度、图幅
    分区标记）——它们不属于任何视图；留着会变成 1~5 图元的假视图，把视图
    间的对齐关系搅乱，主视图随之定不下来（实测 YZYX：6 个视图带双伙伴，
    而判据要求恰好 1 个 ⇒ 全表 UNKNOWN ⇒ 特征树 0 条）。

    家具判据取**"不完全落在框内"**而非"与框不相交"：对中符号是**跨着框线**
    画的（实测 13E6 从 x=2168 伸进框内 15mm），要求"不相交"会把它留下。

    嵌套外框（图纸边界 + 图框两道）最多剥 3 层：剥掉外层后内层仍是长线成矩，
    不剥它照样桥接。
    """
    out: set[str] = set()
    rect: BBox2 | None = None
    rest = list(geom)
    for _ in range(3):
        got = _frame_by_long_lines(rest, gap_x, gap_y)
        if got is None:
            break
        handles, rect = got
        out |= handles
        rest = [e for e in rest if e.handle not in handles]

    if rect is None:
        got = _frame_by_outer_edge(geom)
        if got is None:
            return set(), None
        handles, rect = got
        out |= handles

    for e in geom:
        if e.handle not in out and not _inside(rect, e.exact_bbox):
            out.add(e.handle)          # 判据是"不完全落在框内"，不是"与框不相交"
    return out, rect


def detect_views(d: Drawing, params: DetectParams | None = None) -> list[View]:
    """把证据聚成视图，并把文字/尺寸/轴线归属到各视图。

    副作用：填充 ``Drawing.views``。返回同一列表。
    视图 id 形如 ``V0``/``V1``…，按**先上后下、先左后右**编号，跨次运行稳定。
    """
    p = params or DetectParams()

    # ---- 参与分离的几何：**只认轮廓**（白名单，不是黑名单） ----
    # 三类进得来：可见轮廓、隐藏线、剖面线边界 —— 它们才是"零件在该视图里
    # 占多大地方"的依据。其余一律排除，各有理由：
    #  - Role.SECTION_CUT：剖切线画在视图**外**（两端伸出并带箭头），
    #    实测把 bracket 俯视图的纵向尺寸从 51 撑到 67（+31%）
    #  - Role.AXIS（kind=AXIS）：中心线两端伸出零件外，同理
    #  - Role.UNKNOWN（尺寸线层上的界线/箭头）
    #  - Kind.BLOCK：未展开的块引用，占位几何可能跨半张图
    #  - Kind.HATCH：本体的 geom 只是个占位对角线段（真实形状在它的边界图元里）
    # 用白名单而非黑名单：以后新增角色时默认**不参与**，宁可漏算也不虚胖
    # （虚胖是静默的：它只让尺寸偏大，不报错）。
    # 这些图元仍归属到视图（见 _assign），只是不参与定包围盒。
    _PROFILE_ROLES = {Role.VISIBLE, Role.HIDDEN, Role.HATCH_BOUNDARY}
    geom = [e for e in d.evidence
            if e.kind == Kind.EDGE and e.role.value in _PROFILE_ROLES]
    if not geom:
        d.views = []
        return []

    # 图纸外框先摘掉再聚类 —— 否则它一条边横跨全图，一切都被聚成一簇。
    # 框检测自己要用间隙参数，故先按**未摘框**的跨度算一版（摘框后重算，
    # 两份只在框比内容大很多时才不同）。
    boxes_all = [e.exact_bbox for e in geom]
    gap_y0 = max(p.gap_abs, (max(b.ymax for b in boxes_all)
                             - min(b.ymin for b in boxes_all)) * p.gap_frac)
    gap_x0 = max(p.gap_abs, (max(b.xmax for b in boxes_all)
                             - min(b.xmin for b in boxes_all)) * p.gap_frac)

    frame, frame_rect = _sheet_frame(geom, gap_x0, gap_y0)
    if frame:
        d.sheet_frame = sorted(frame)
        geom = [e for e in geom if e.handle not in frame]

    boxes = [e.exact_bbox for e in geom]
    span_y = max(b.ymax for b in boxes) - min(b.ymin for b in boxes)
    span_x = max(b.xmax for b in boxes) - min(b.xmin for b in boxes)
    gap_y = max(p.gap_abs, span_y * p.gap_frac)
    gap_x = max(p.gap_abs, span_x * p.gap_frac)

    # ---- 递归 XY 切分 ----
    groups = _xy_cut(list(range(len(geom))), boxes, gap_x, gap_y)

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

    _assign(d, views, clustered={m.handle for m in geom}, excluded=frame,
            furniture=frame_rect)

    d.views = views
    return views


def _assign(d: Drawing, views: list[View], clustered: set[str],
            excluded: set[str] | None = None,
            furniture: BBox2 | None = None) -> None:
    """把未参与聚类的图元归属到视图。

    归类：轴线 / 填充本体 / 剖切线 → ``evidence``；文字 / 尺寸 → ``annotations``。
    归属判据是**位置**（几何邻近），不是图层或命名 —— 与分离阶段同一套信号。
    ``excluded`` 是已判定为图纸外框/家具的 handle，**不**归属任何视图（否则
    外框会以"离谁近算谁的"落到某个视图的 evidence 里，再次污染它的包围盒）。
    ``furniture`` 是外框矩形：**框外的文字与尺寸**（图幅分区字母、装订边
    标记的编号）同样不归属——它们不是任何视图的标注。
    """
    if not views:
        return
    excluded = excluded or set()

    def _is_furniture(x: float, y: float) -> bool:
        return furniture is not None and _outside(
            furniture, BBox2(x, y, x, y))

    # ---- 轴线、填充本体、剖切线：属于某个视图的图元 ----
    # 它们不参与聚类（会撑大包围盒或跨视图），故按自身几何中心就近归属
    for e in d.evidence:
        if e.handle in clustered or e.handle in excluded:
            continue
        v = _nearest_view(views, _center(e.exact_bbox))
        if v is not None:
            v.evidence.append(e.handle)

    # ---- 文字 ----
    label_dist: dict[str, float] = {}
    for t in d.texts:
        pt = Point2(t.x, t.y)
        if _is_furniture(pt.x, pt.y):
            continue
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
        if probe is None or _is_furniture(probe.x, probe.y):
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
