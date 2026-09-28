# -*- coding: utf-8 -*-
"""DXF → 证据模型（第 1 层入口）。

**只忠实记录，不做解释**：图元全部入账、角色只给可推翻的 Claim。
视图归属留给 views/view_detector.py（本模块 view 字段一律留空）。

依赖：仅 ezdxf —— 跑默认 python 即可，不需要 cad-occt
（ARCHITECTURE §5 解释器依赖分层）。
"""
from __future__ import annotations

import math
from pathlib import Path

import ezdxf

from ..model.claim import Claim, Tier
from ..model.geom2d import Arc2, Circle2, Line2, Point2
from ..model.ids import EvidenceRef
from .model import Dimension, Drawing, Evidence, Kind, Role
from .text_parser import parse_text

# ---- 角色判据词表 ----
# 判据来自**图层名 / 线型名**（制图约定的命名习惯），故 tier=CONVENTION。

_AXIS_WORDS = ("中心线", "中心", "轴线", "CENTER", "DASHDOT", "CTR")
_HIDDEN_WORDS = ("隐藏", "虚线", "HIDDEN", "DASHED", "DASH")
_HATCH_WORDS = ("剖面线", "填充", "HATCH", "SECTION_HATCH")
_BREAK_WORDS = ("波浪", "断裂", "BREAK")
_CUT_WORDS = ("剖切", "剖切线", "CUT")
_DIM_WORDS = ("标注", "尺寸", "DIM", "DIMENSION")

#: DIMENSION 的 dimtype 低 3 位 → 类型名
_DIMTYPE_NAMES = {
    0: "linear", 1: "aligned", 2: "angular",
    3: "diameter", 4: "radius", 5: "angular3p", 6: "ordinate",
}


def _match(words: tuple[str, ...], *haystacks: str) -> bool:
    """任一 haystack 含任一关键词（大小写不敏感）即真。"""
    for h in haystacks:
        if not h:
            continue
        up = h.upper()
        for w in words:
            if w.upper() in up:
                return True
    return False


def classify_role(layer: str, linetype: str, handle: EvidenceRef) -> Claim[Role]:
    """按图层名 / 线型名判定图元角色。

    返回的是 **Claim（tier=CONVENTION）** 而非硬结论 —— 后续若从几何形状
    得到更强依据（如"这条线正在某个被 HATCH 的闭合环上"），可以覆盖它。
    """
    ref = (handle,)
    if _match(_AXIS_WORDS, layer, linetype):
        return Claim(Role.AXIS, "convention:layer", Tier.CONVENTION, ref)
    if _match(_BREAK_WORDS, layer, linetype):
        return Claim(Role.BREAK_LINE, "convention:layer", Tier.CONVENTION, ref)
    if _match(_CUT_WORDS, layer, linetype):
        return Claim(Role.SECTION_CUT, "convention:layer", Tier.CONVENTION, ref)
    if _match(_DIM_WORDS, layer):
        # 尺寸线层上的几何是**标注的附属**（尺寸界线/箭头），不是零件轮廓：
        # 让它当可见轮廓会污染视图包围盒与轮廓环提取
        return Claim(Role.UNKNOWN, "convention:dim_layer", Tier.CONVENTION, ref)
    if _match(_HIDDEN_WORDS, layer, linetype):
        return Claim(Role.HIDDEN, "convention:linetype", Tier.CONVENTION, ref)
    return Claim(Role.VISIBLE, "default", Tier.GUESS, ref)


def _kind_of(role: Role) -> Kind:
    """角色 → 证据种类。

    ⚠️ 2026-09-28 修：本函数此前是**死代码** —— 三个几何循环把 ``Kind.EDGE``
    写死，从不问角色，于是 13 条中心线（图层"中心线层"）带着 ``kind=edge``
    进了视图包围盒与间隙聚类（``d.axes()`` 永远是空的）。

    正确的分工：**角色先判、种类跟着角色走**。中心线不是轮廓边
    （它的两端要伸出零件外），混进包围盒会把视图尺寸撑大 ——
    和 v0.6.15 剖切线撑大俯视图是同一类错。
    """
    if role == Role.AXIS:
        return Kind.AXIS
    if role == Role.BREAK_LINE:
        return Kind.BREAK
    return Kind.EDGE


# ---- 主入口 ----

def read_dxf(path: str | Path) -> Drawing:
    """读取 DXF，构建证据模型。"""
    p = Path(path)
    doc = ezdxf.readfile(str(p))
    msp = doc.modelspace()

    drawing = Drawing(path=str(p))
    drawing.layers = sorted(layer.dxf.name for layer in doc.layers)
    counter = 0

    def new_ref(e) -> EvidenceRef:
        """图元 handle；ezdxf 对无 handle 的合成实体返回 None，退化为自增号。"""
        nonlocal counter
        h = getattr(e.dxf, "handle", None)
        if h:
            return EvidenceRef(h)
        counter += 1
        return EvidenceRef(f"@{p.stem}:{counter}")

    def add_geom(e, geom, kind: Kind, layer: str, linetype: str,
                 role_override: Claim[Role] | None = None,
                 pattern: str = "") -> None:
        ref = new_ref(e)
        role = role_override or classify_role(layer, linetype, ref)
        drawing.evidence.append(Evidence(
            handle=ref, kind=kind, geom=geom, role=role,
            layer=layer, linetype=linetype, pattern=pattern,
        ))

    def add_edge(e, geom, layer: str, linetype: str) -> None:
        """轮廓类图元：**先判角色，再由角色定种类**（见 _kind_of 的说明）。"""
        ref = new_ref(e)
        role = classify_role(layer, linetype, ref)
        drawing.evidence.append(Evidence(
            handle=ref, kind=_kind_of(role.value), geom=geom, role=role,
            layer=layer, linetype=linetype,
        ))

    # ---- 直线 / 弧 / 圆 ----
    for e in msp.query("LINE"):
        add_edge(e, Line2(Point2(e.dxf.start.x, e.dxf.start.y),
                          Point2(e.dxf.end.x, e.dxf.end.y)),
                 e.dxf.layer, e.dxf.linetype)

    for e in msp.query("ARC"):
        add_edge(e, Arc2(Point2(e.dxf.center.x, e.dxf.center.y), e.dxf.radius,
                         _rad(e.dxf.start_angle), _rad(e.dxf.end_angle)),
                 e.dxf.layer, e.dxf.linetype)

    for e in msp.query("CIRCLE"):
        add_edge(e, Circle2(Point2(e.dxf.center.x, e.dxf.center.y), e.dxf.radius),
                 e.dxf.layer, e.dxf.linetype)

    # ---- 多段线：炸成 LINE/ARC（bulge 转弧由 ezdxf 负责） ----
    # 图纸大量使用 LWPOLYLINE 画轮廓，不展开等于漏掉主体几何
    for e in msp.query("LWPOLYLINE POLYLINE"):
        lay = e.dxf.layer
        lt = getattr(e.dxf, "linetype", "")
        try:
            for sub in e.virtual_entities():
                if sub.dxftype() == "LINE":
                    add_edge(sub, Line2(Point2(sub.dxf.start.x, sub.dxf.start.y),
                                        Point2(sub.dxf.end.x, sub.dxf.end.y)),
                             lay, lt)
                elif sub.dxftype() == "ARC":
                    add_edge(sub, Arc2(Point2(sub.dxf.center.x, sub.dxf.center.y),
                                       sub.dxf.radius,
                                       _rad(sub.dxf.start_angle),
                                       _rad(sub.dxf.end_angle)),
                             lay, lt)
        except Exception as exc:   # noqa: BLE001 —— 单条多段线坏掉不该毁掉整张图
            print(f"  [WARN] 多段线展开失败（handle={getattr(e.dxf, 'handle', '?')}）: {exc}")

    # ---- 剖面填充：HATCH 本身 + 其边界 ----
    for e in msp.query("HATCH"):
        ref = new_ref(e)
        pattern = ""
        try:
            pattern = e.dxf.pattern_name
        except Exception:  # noqa: BLE001
            pass
        drawing.evidence.append(Evidence(
            handle=ref, kind=Kind.HATCH, geom=_hatch_bbox_geom(e),
            role=Claim(Role.HATCH_FILL, "convention:hatch", Tier.CONVENTION, (ref,)),
            layer=e.dxf.layer, linetype="", pattern=pattern,
        ))
        # 边界边单独入账，kind=EDGE（它确实是边，要参与视图包围盒）——
        # 剖面材料信号来自这里（v0.6.15 的 HATCH 通道）
        for geom in _hatch_boundary_geoms(e):
            add_geom(e, geom, Kind.EDGE, e.dxf.layer, "",
                     role_override=Claim(Role.HATCH_BOUNDARY,
                                         "convention:hatch", Tier.CONVENTION, (ref,)))

    # ---- 块引用：**记录但标明未展开** ----
    # 不能假装没看见：INSERT 里可能有真几何（本项目 20160112 图上
    # 粗实线层就有 2 个块引用），静默丢弃正是旧管线的病根。
    # 展开需要递归处理块定义坐标变换，暂不做 —— 如实记一条 SUBGRAPH 证据，
    # 由覆盖率报告把它摆到台面上（"有多少图元我们没看懂"）。
    for e in msp.query("INSERT"):
        ref = new_ref(e)
        drawing.evidence.append(Evidence(
            handle=ref, kind=Kind.BLOCK, geom=_insert_bbox_geom(e),
            role=Claim(Role.UNKNOWN, "unexpanded:insert", Tier.GUESS, (ref,)),
            layer=e.dxf.layer, linetype="",
        ))

    # ---- 文字 ----
    for e in msp.query("TEXT MTEXT"):
        ref = new_ref(e)
        try:
            txt = e.text if e.dxftype() == "MTEXT" else e.dxf.text
            insert = e.dxf.insert
            drawing.texts.append(parse_text(
                txt or "", ref, insert.x, insert.y, e.dxf.layer))
        except Exception as exc:   # noqa: BLE001
            print(f"  [WARN] 文字解析失败（handle={ref}）: {exc}")

    # ---- 尺寸标注（第 1 层的核心资产） ----
    for e in msp.query("DIMENSION"):
        drawing.dimensions.append(_read_dimension(e, new_ref(e)))

    return drawing


def _rad(deg: float) -> float:
    return math.radians(deg)


def _insert_bbox_geom(e) -> Line2:
    """块引用的占位几何：其插入点/包围盒对角。

    只用来"知道它在图纸的哪个位置"（归属视图、算覆盖率），
    **不参与视图包围盒**（Kind.BLOCK 不在 view_detector 的轮廓白名单里）——
    否则一个跨越半张图的块会把视图撑变形。
    """
    try:
        ins = e.dxf.insert
        x, y = float(ins.x), float(ins.y)
    except Exception:      # noqa: BLE001
        return Line2(Point2(0.0, 0.0), Point2(0.0, 0.0))
    try:
        block = e.doc.blocks.get(e.dxf.name)
        bb = block.block.dxf.extents if block else None
        if bb is not None:
            return Line2(Point2(x + float(bb[0]), y + float(bb[1])),
                         Point2(x + float(bb[2]), y + float(bb[3])))
    except Exception:      # noqa: BLE001 —— 块定义查不到就退化为插入点
        pass
    return Line2(Point2(x, y), Point2(x, y))


def _hatch_bbox_geom(e) -> Line2:
    """HATCH 没有单一几何 —— 用一个退化 Line2 占位承载 provenance。

    真实形状在它的边界图元里（上面已单独入账）。占位值取填充范围对角，
    使 bbox 仍有意义。
    """
    pts: list[Point2] = []
    for path in e.paths:
        pts.extend(_path_points(path))
    if not pts:
        return Line2(Point2(0.0, 0.0), Point2(0.0, 0.0))
    return Line2(Point2(min(p.x for p in pts), min(p.y for p in pts)),
                 Point2(max(p.x for p in pts), max(p.y for p in pts)))


def _path_points(path) -> list[Point2]:
    """取一条边界路径的顶点/端点（仅用于求占位 bbox）。"""
    pts: list[Point2] = []
    for v in getattr(path, "vertices", None) or []:
        pts.append(Point2(float(v[0]), float(v[1])))
    for edge in getattr(path, "edges", None) or []:
        name = type(edge).__name__
        if name == "LineEdge":
            pts.append(Point2(float(edge.start.x), float(edge.start.y)))
            pts.append(Point2(float(edge.end.x), float(edge.end.y)))
        elif name == "ArcEdge":
            c = Point2(float(edge.center.x), float(edge.center.y))
            r = float(edge.radius)
            pts.append(Point2(c.x - r, c.y - r))
            pts.append(Point2(c.x + r, c.y + r))
    return pts


def _hatch_boundary_geoms(e) -> list[Line2 | Arc2]:
    """把 HATCH 的边界路径展开成 LINE/ARC 图元。

    ezdxf 的 ``Hatch`` **没有** ``virtual_entities()``（只有 INSERT 那类有），
    必须手工走 ``.paths``：每条路径要么是 ``.edges``（LineEdge/ArcEdge/…），
    要么是多段线式 ``.vertices``（可能带 bulge，此处按直线段近似 ——
    bulge 弧在剖面边界上罕见，真出现时由下游覆盖率检查暴露）。
    """
    out: list[Line2 | Arc2] = []
    try:
        paths = e.paths
    except Exception:   # noqa: BLE001
        return out
    for path in paths:
        for edge in getattr(path, "edges", None) or []:
            name = type(edge).__name__
            if name == "LineEdge":
                out.append(Line2(Point2(float(edge.start.x), float(edge.start.y)),
                                 Point2(float(edge.end.x), float(edge.end.y))))
            elif name == "ArcEdge":
                out.append(Arc2(Point2(float(edge.center.x), float(edge.center.y)),
                                float(edge.radius),
                                _rad(float(edge.start_angle)),
                                _rad(float(edge.end_angle))))
            # EllipseEdge / SplineEdge 暂不展开：剖面边界极少出现，
            # 且展开需要采样，会引入近似误差 —— 留给覆盖率检查报告
        verts = getattr(path, "vertices", None) or []
        pts = [Point2(float(v[0]), float(v[1])) for v in verts]
        for a, b in zip(pts, pts[1:]):
            if a.distance_to(b) > 1e-9:
                out.append(Line2(a, b))
        # 闭合路径的收口段
        if len(pts) > 2 and pts[0].distance_to(pts[-1]) > 1e-9:
            out.append(Line2(pts[-1], pts[0]))
    return out


def _read_dimension(e, ref: EvidenceRef) -> Dimension:
    """解析一条 DIMENSION。

    ``defpoint2``/``defpoint3`` 是线性/对齐尺寸被量的两端 ——
    「尺寸 ↔ 几何锚点」的配对就靠它们（ARCHITECTURE §4.3）。

    ⚠️ 本项目现有测试图纸 DIMENSION 数为 0，本函数尚未在真实标注上验证；
    需要出图侧（model_to_drawing.py）先具备产标注能力才能端到端测。
    """
    dimtype_raw = int(getattr(e.dxf, "dimtype", 0))
    base = dimtype_raw & 7
    name = _DIMTYPE_NAMES.get(base, f"unknown({base})")

    p1 = p2 = p3 = None
    for attr, slot in (("defpoint", "p3"), ("defpoint2", "p1"), ("defpoint3", "p2")):
        v = getattr(e.dxf, attr, None)
        if v is None:
            continue
        pt = Point2(float(v.x), float(v.y))
        if slot == "p1":
            p1 = pt
        elif slot == "p2":
            p2 = pt
        else:
            p3 = pt

    value: float | None = None
    try:
        m = e.get_measurement()
        if isinstance(m, (int, float)):
            value = float(m)
    except Exception:  # noqa: BLE001 —— 部分类型 ezdxf 算不出，允许为 None
        value = None
    if value is None and p1 is not None and p2 is not None:
        value = p1.distance_to(p2) * getattr(e.dxf, "dimlfac", 1.0)

    text = ""
    try:
        text = e.dxf.text or ""
    except Exception:  # noqa: BLE001
        pass

    return Dimension(
        handle=ref, dimtype=name, value=value, p1=p1, p2=p2, p3=p3,
        text_override=text, layer=e.dxf.layer,
    )


def read_dxf_safe(path: str | Path) -> Drawing:
    """读图失败也返回（空）Drawing，把错误写进 stderr 而不是抛异常。

    供 inspect 这类"看一眼"的入口使用；需要严格报错的调用方请用 read_dxf。
    """
    import sys

    try:
        return read_dxf(path)
    except Exception as exc:  # noqa: BLE001
        print(f"[FAIL] 读取失败 {path}: {exc}", file=sys.stderr)
        return Drawing(path=str(path))
