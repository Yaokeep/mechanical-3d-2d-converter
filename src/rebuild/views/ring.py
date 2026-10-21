# -*- coding: utf-8 -*-
"""视图轮廓环提取 —— 2D 边图 → 单条闭合外轮廓（直线 + 精确圆弧）。

这是新框架的**独立证据通道**：轮廓环回答「基体外形是什么」（L 形？
台阶？臂端圆头？），与 features 层的特征识别分开（见 recognizer.py
模块注释的立场——基体不应只按视图包围盒近似）。

出身：旧管线 ``dxf_to_3d_general.py`` 的无合并环提取（:3641
``extract_outer_rings_no_merge`` / :3775 ``_extract_rings_impl``）、
微边链端点焊接（:3417 ``weld_chain_ends``）、微边链长表（:4983
``_micro_chain_lengths``）、覆盖率门控（:5626）。**只移植算法，
不共享代码**。移植过来的机制：

- 最左转（min-ccw）环遍历 + 最右转（max）兜底 + 左面遍历兜底，
  候选环按「顶点无重复（自交淘汰）+ 面积取大」选（:4341）
- **边交点拆分**（:681 ``split_edges_at_intersections``，旧管线调用点 :7903）：
  面遍历依赖端点共享；直线端点在另一条边的中段（T 型）、圆/弧被直线穿过
  等情形下，交点若不成为图顶点，闭合环无法闭合。实测 bracket 俯视图
  124 个直线端点精确落在弧几何上（d≤0.01mm）、且落在弧角跨度内部——
  而整圆只按 0°/180° 拆两半（``_arc``），这些端点全是度 1，全被修剪，
  凸台圆退化成 2 顶点分量被 ``len<3`` 守卫跳过 ⇒ 外环提不出来
  （移植时漏掉此步 ⇒ V0 覆盖率 0.06×0.12）
- 往返副本签名去重：同几何的 HLR 双副本视作一条（:3798 ``edge_sig``）
- 微边支路跳过（<0.3mm 抖动边）；长链微边（链长 ≥2mm 的碎段链）
  豁免——那是真实轮廓（:3865 ``_is_micro_edge``）
- 微边链端点焊接：只焊「微链自由端 → 长边度 1 端点 <0.3mm」，
  长-长绝不焊接（v15 教训：外环线端点与内圆弧端点 0.03mm 误焊）
- 两遍提取（raw / welded）取面积大者，规则记在 ``Ring.rule``
- 覆盖率门控：环顶点 bbox / 视图 bbox 双维 ≥0.75，不足视为非外轮廓
  （:5626，v0.6.20 口径 50%→75%）

**刻意不移植**（各有归属，不是漏）：

- v0.6.19「整圆附加环」——旧 CSG 的 Union 补丁；新框架由识别层
  对圆弧凸台单独处置
- top 视图 x 镜像检测——新框架由 ``ViewFrame.mirror_axes`` 承担
- ``arc_ring`` 的整圆合成（36 段折线）——新读取器已把 CIRCLE/整圆
  弧读成独立图元；纯圆视图返回 None + note，让位给回转体通道

依赖：``..evidence.model`` 与 ``..model.*``（纯数据），跑默认 python。

命令行冒烟（也是 selftest J 组的入口）::

    python -m src.rebuild.views.ring CAD/test_simple/l_bracket.dxf
"""
from __future__ import annotations

import math
import os
from collections import defaultdict, Counter
from dataclasses import dataclass, replace

from ..evidence.model import Drawing, Role, View
from ..model.geom2d import (
    Arc2, BBox2, Circle2, Line2, Point2, Polyline2, Profile2, ProfileSeg2,
)

__all__ = ["FaceRing", "Ring", "RingResult", "RingSeg",
           "extract_faces", "extract_ring"]

#: 参与环提取的角色。**只有可见轮廓** —— 与 view_detector 的口径
#: （含 HIDDEN/HATCH_BOUNDARY，视图包围盒理应计入全部图元）有意分歧：
#: 旧管线在 parse 阶段就把 HIDDEN/DASHED 线型与"隐藏线/中心线"图层
#: 整条丢弃（dxf_to_3d_general.SKIP_LINETYPES / SKIP_LAYER_KEYWORDS），
#: 隐藏线只被竖线对/腔盒/斜断面等专用扫描器消费；含 HIDDEN 会让
#: min-ccw 遍历在分叉处拐进隐藏线簇——实测 bracket 剖面图纸 V2
#: 拼出 1662.18 的伪缺口环（缺口横线 26 条中 21 条是 hidden），
#: 而四条真边界在全长上都是可见轮廓，正解是 2244 矩形。三视图_v4
#: 的 V2 同含缺口图元但图更干净，侥幸躲过——两文件同视图结果不同
#: 即是该差异的证据。
_PROFILE_ROLES = {Role.VISIBLE}

TAU = 2.0 * math.pi
SNAP = 0.01           # 端点网格吸附（旧管线 SNAP_TOL）
MICRO_DX = 0.3        # 微边判据：|dx|、|dy| 均 < 0.3mm
MICRO_EPS = 0.25      # 微边端点聚类半径
MICRO_CHAIN_MIN = 2.0  # 长链微边豁免：链长 ≥ 2mm 视为真实碎段轮廓
WELD_GAP = 0.3        # 微链自由端 → 长边端点的焊接距离上限
COVER_MIN = 0.75      # 覆盖率门控（旧管线 v0.6.20 口径）
AREA_FLOOR = 10.0     # 候选环最小面积 mm²（旧 keep_all=False 口径）

#: 第三遍「顶点胶合」参数（旧管线 :932 ``merge_close_vertices`` /
#: :979 ``merge_dangling_vertices`` 的口径，原样移植）。只在 raw/welded
#: 两遍都失败时作为兜底跑——HLR 长边端点间的 0.01mm 级微缝落在 SNAP
#: 网格两侧（D79307 V1：ARC 端点 (45.013,16.373) 与 LINE 端点
#: (45.011,16.375) 各吸附到 (45.01,16.37)/(45.01,16.38)），度 1 修剪
#: 会把整条底脚链删掉 ⇒ no_ring_found。``_weld`` 救不了（长-长绝不
#: 焊接，v15 误焊教训），故胶合必须是**独立兜底**、不与成功的环竞逐。
GLUE_CLOSE = 0.5      # 近邻顶点合并距离（含端点）
GLUE_GAP = 1.5        # 悬空顶点吸附到最近非悬空顶点的距离上限
#: 同一圆上弧端点的合并上限。弧是刚性几何：同一圆上两段弧的端点若相距
#: 超过图纸量化精度，它们之间隔着一段**真实弧长**——合并等于把那段弧
#: 塌掉，环会在该圆上折返（往返走出尖刺 ⇒ 自交，发射器 BRepCheck 判面
#: 无效）。5×SNAP 取的是「图纸量化 + 端点吸附」的合计口径，与发射器
#: ``ARC_END_SNAP`` 同量级。见 ``_glue`` 的 ``union``。
GLUE_COCIRC = 0.05

#: 置 RING_DBG=1 打印遍历决策 / =2 全步输出（排查用，对照旧管线 SLANT_DBG 先例）
_DBG = int(os.environ.get("RING_DBG") or 0)


#: 轮廓段类型已提升到 model 层（跨层契约：views 提取、emit 消费，
#: 发射器不依赖 views）——此处仅保留旧名别名，模块内引用不变。
RingSeg = ProfileSeg2


@dataclass(frozen=True)
class Ring:
    """一条视图外轮廓环（闭合、有序、纸面 CCW 正面积）。"""

    segs: tuple[RingSeg, ...]
    area: float                                # 顶点鞋带面积
    bbox: BBox2                                # 几何 bbox（含弧顶）
    rule: str                                  # "raw" | "welded" | "glued"
    coverage: tuple[float, float]              # (环/视图) 宽、高覆盖比
    n_edges: int                               # 视图参与提取的轮廓边数
    n_micro: int                               # 其中微边条数
    n_components: int                          # 含边的连通分量数

    def to_profile(self) -> Profile2:
        """转为发射器契约（Profile2）。段类型同构，零拷贝。"""
        return Profile2(self.segs)


@dataclass(frozen=True)
class RingResult:
    """提取结果：``ring`` 为通过门控的环；三遍诊断各自保留。

    ``glued`` 是第三遍（顶点胶合兜底）的诊断结果——只有 raw/welded 都
    失败时才会跑，故正常视图恒为 None。
    """

    ring: Ring | None
    raw: Ring | None
    welded: Ring | None
    note: str = ""
    glued: Ring | None = None


# ---------------------------------------------------------------------------
# 内部边模型（顶点索引化 + 弧参数）
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class _E:
    t: str                       # "L" | "A"
    vs: int                      # 起点顶点
    ve: int                      # 终点顶点
    cx: float = 0.0              # 弧：圆心
    cy: float = 0.0
    r: float = 0.0               # 弧：半径
    sa: float = 0.0              # 弧：CCW 起点角（弧度）
    ea: float = 0.0              # 弧：CCW 终点角（弧度）
    sa_v: int = -1               # 弧：sa 端顶点（直线不用）
    ea_v: int = -1               # 弧：ea 端顶点
    role: str = "visible"        # 来源证据角色（"visible"|"hidden"）


@dataclass(frozen=True)
class _Pass:
    ring: tuple[tuple[int, int, int], ...]     # (eid, from_v, to_v)
    area: float
    vbox: tuple[float, float, float, float]    # 顶点 bbox（门控用）
    n_comp: int


# ---------------------------------------------------------------------------
# 几何小工具
# ---------------------------------------------------------------------------

def _norm(a: float) -> float:
    """归一化到 (-π, π]。"""
    while a > math.pi:
        a -= TAU
    while a <= -math.pi:
        a += TAU
    return a


def _shoelace(pts: list[tuple[float, float]]) -> float:
    a = 0.0
    n = len(pts)
    for i in range(n):
        x1, y1 = pts[i]
        x2, y2 = pts[(i + 1) % n]
        a += x1 * y2 - x2 * y1
    return abs(a) / 2


# ---------------------------------------------------------------------------
# 边图构建（视图证据 → _E 列表 + 顶点表）
# ---------------------------------------------------------------------------

def _arc_prims(cx, cy, r, sa, ea):
    """弧 → 图元（整圆拆两半；一律 CCW 参数化，span 用模运算取正）。"""
    span = (ea - sa) % TAU
    if span < 1e-9:
        span = TAU                                # 整圆（|ea-sa| = 2π）
    if span > TAU - 1e-3:                         # 整圆拆两半（同旧 :289）
        mid = sa + math.pi
        return [("A", cx, cy, r, sa, mid), ("A", cx, cy, r, mid, sa + TAU)]
    return [("A", cx, cy, r, sa, sa + span)]


def _prim_from_geom(g):
    """视图几何 → 基本图元 [("L", x1,y1,x2,y2) | ("A", cx,cy,r,sa,ea)]。"""
    if isinstance(g, Line2):
        return [("L", g.start.x, g.start.y, g.end.x, g.end.y)]
    if isinstance(g, Arc2):
        return _arc_prims(g.center.x, g.center.y, g.radius,
                          g.start_angle, g.end_angle)
    if isinstance(g, Circle2):
        return _arc_prims(g.center.x, g.center.y, g.radius, 0.0, TAU)
    if isinstance(g, Polyline2):
        pts = g.points
        return [("L", p.x, p.y, q.x, q.y) for p, q in zip(pts, pts[1:])]
    return []


def _angle_in_arc(ang: float, sa: float, ea: float,
                  tol: float = 1e-4) -> bool:
    """角度（弧度）是否在弧参数范围内（含端点容差），弧按 CCW。"""
    span = (ea - sa) % TAU
    if span < 1e-9:
        span = TAU
    off = (ang - sa) % TAU
    return -tol <= off <= span + tol


#: 交点拆分参数域端点容差（交点恰在端点时不拆那一侧）
_SPLIT_EPS = 1e-6


def _split_primitives(prims: list, with_src: bool = False) -> list:
    """在边-边交点处拆分图元（旧 :681 ``split_edges_at_intersections`` 语义）。

    三种情形全拆：线∩线（T 型 / X 型，内部侧拆）、弧∩弧（双圆求交）、
    线∩弧（弧侧必拆、线侧仅内部拆）。相切交点（disc≈0）也要拆——
    浮点误差可能让 disc 成微负（旧 v0.6.3 教训：法兰叶片角直线与 r=30
    圆相切漏拆 ⇒ 外环断链）。

    ``with_src=True`` 时返回 ``(源图元下标, 拆分后图元)`` 二元组——
    全角色边图需要把拆分结果归回原证据角色（隐藏/可见）。
    """
    n = len(prims)
    if n < 2:
        return prims
    bb = []
    for p in prims:
        if p[0] == "L":
            _, x1, y1, x2, y2 = p
            bb.append((min(x1, x2), min(y1, y2), max(x1, x2), max(y1, y2)))
        else:
            _, cx, cy, r, _sa, _ea = p
            bb.append((cx - r, cy - r, cx + r, cy + r))

    cuts: list[list[float]] = [[] for _ in range(n)]
    EPS = _SPLIT_EPS
    for i in range(n):
        for j in range(i + 1, n):
            bxi, bxj = bb[i], bb[j]
            if bxi[2] < bxj[0] or bxj[2] < bxi[0] or \
                    bxi[3] < bxj[1] or bxj[3] < bxi[1]:
                continue
            pi, pj = prims[i], prims[j]
            if pi[0] == "L" and pj[0] == "L":
                x1, y1, x2, y2 = pi[1:]
                x3, y3, x4, y4 = pj[1:]
                d1x, d1y = x2 - x1, y2 - y1
                d2x, d2y = x4 - x3, y4 - y3
                den = d1x * d2y - d1y * d2x
                if abs(den) < 1e-12:
                    continue
                t = ((x3 - x1) * d2y - (y3 - y1) * d2x) / den
                s = ((x3 - x1) * d1y - (y3 - y1) * d1x) / den
                if -EPS <= t <= 1 + EPS and -EPS <= s <= 1 + EPS:
                    if EPS < t < 1 - EPS:         # T 型/X 型：内部侧才拆
                        cuts[i].append(t)
                    if EPS < s < 1 - EPS:
                        cuts[j].append(s)
            elif pi[0] == "A" and pj[0] == "A":
                _c1, c1x, c1y, r1, s1a, e1a = pi
                _c2, c2x, c2y, r2, s2a, e2a = pj
                dx, dy = c2x - c1x, c2y - c1y
                d = math.hypot(dx, dy)
                if d < 1e-9 or d > r1 + r2 or d < abs(r1 - r2):
                    continue
                a = (r1 * r1 - r2 * r2 + d * d) / (2 * d)
                h2 = r1 * r1 - a * a
                if h2 < 0:
                    continue
                h = math.sqrt(h2)
                bx, by = c1x + a * dx / d, c1y + a * dy / d
                for sign in (1.0, -1.0):
                    px = bx + sign * h * (-dy / d)
                    py = by + sign * h * (dx / d)
                    ang1 = math.atan2(py - c1y, px - c1x)
                    ang2 = math.atan2(py - c2y, px - c2x)
                    if _angle_in_arc(ang1, s1a, e1a):
                        cuts[i].append(ang1 % TAU)
                    if _angle_in_arc(ang2, s2a, e2a):
                        cuts[j].append(ang2 % TAU)
            else:
                if pi[0] == "A":
                    arc, line, arc_i, line_i = pi, pj, i, j
                else:
                    arc, line, arc_i, line_i = pj, pi, j, i
                _c, cx, cy, r, sa, ea = arc
                x1, y1, x2, y2 = line[1:]
                dx, dy = x2 - x1, y2 - y1
                fx, fy = x1 - cx, y1 - cy
                a = dx * dx + dy * dy
                if a < 1e-12:
                    continue
                b = 2 * (fx * dx + fy * dy)
                c = fx * fx + fy * fy - r * r
                disc = b * b - 4 * a * c
                if disc < -1e-9 * max(1.0, b * b, abs(4 * a * c)):
                    continue                      # 无交点（远离相切）
                disc = max(disc, 0.0)             # 相切浮点微负 → 夹到 0
                sq = math.sqrt(disc)
                for t in ((-b - sq) / (2 * a), (-b + sq) / (2 * a)):
                    if not (-EPS <= t <= 1 + EPS):
                        continue
                    px, py = x1 + t * dx, y1 + t * dy
                    ang = math.atan2(py - cy, px - cx)
                    if _angle_in_arc(ang, sa, ea):
                        cuts[arc_i].append(ang % TAU)  # 弧侧必拆
                        if EPS < t < 1 - EPS:
                            cuts[line_i].append(t)

    out: list = []
    for i, p in enumerate(prims):
        params = sorted(set(round(t, 9) for t in cuts[i]))
        sub: list = []
        if not params:
            sub.append(p)
        elif p[0] == "L":
            x1, y1, x2, y2 = p[1:]
            pts = [(x1, y1)]
            for t in params:
                pts.append((x1 + (x2 - x1) * t, y1 + (y2 - y1) * t))
            pts.append((x2, y2))
            for (ax, ay), (bx, by) in zip(pts, pts[1:]):
                if math.hypot(bx - ax, by - ay) > 1e-9:
                    sub.append(("L", ax, ay, bx, by))
        else:
            _c, cx, cy, r, sa, ea = p
            span = (ea - sa) % TAU
            if span < 1e-9:
                span = TAU
            # 拆分角度必须**解缠到 [sa, sa+span]**：``params`` 是
            # ``ang % TAU`` 的原始值，而 sa/sa+span 可能为负或超 TAU。
            # 直接混用会让跨 0/2π 缝的弧拆出 ``sa > ea`` 的段（实测
            # D79307-剖面 sa=-10.23° 的圆角弧拆出 sa=359.99° > ea=0°），
            # 破坏 ``_arc_prims`` 的「ea = sa + span」契约——下游按模运算
            # 把 0.013° 的微弧读成 359.987° 近整圆，剖面图基体自交。
            angs = []
            for a in params:
                off = (a - sa) % TAU
                if off > span:
                    off = span          # _angle_in_arc 端点容差 1e-4 的裁剪
                angs.append(sa + off)
            angs.sort()
            ordered = [sa] + angs + [sa + span]
            for a1, a2 in zip(ordered, ordered[1:]):
                if abs(a2 - a1) < 1e-9:
                    continue
                p1 = (cx + r * math.cos(a1), cy + r * math.sin(a1))
                p2 = (cx + r * math.cos(a2), cy + r * math.sin(a2))
                if math.hypot(p2[0] - p1[0], p2[1] - p1[1]) > 1e-9:
                    sub.append(("A", cx, cy, r, a1, a2))
        if with_src:
            out.extend((i, q) for q in sub)
        else:
            out.extend(sub)
    return out


def _profile_edges(d: Drawing, v: View, roles: set[str] | None = None):
    """视图轮廓类证据 → (edges: list[_E], vpos: dict[int, (x, y)])。

    ``roles`` 是**角色值**集合（``Role.value``），缺省只取可见轮廓
    （``_PROFILE_ROLES``）。内环/内腔通道传 ``{"visible", "hidden"}``：
    腔体边界在图纸上正是以隐藏线出现的（IMU 的两个角凹腔、D79307 的
    钥匙孔轴段），只要外轮廓环仍走缺省口径即可，互不影响。
    """
    roles = {r.value for r in _PROFILE_ROLES} if roles is None else set(roles)
    by_h = {e.handle: e for e in d.evidence}
    vpos: dict[int, tuple[float, float]] = {}
    key2id: dict[tuple[float, float], int] = {}

    def _vid(x: float, y: float) -> int:
        k = (round(x / SNAP) * SNAP, round(y / SNAP) * SNAP)
        i = key2id.get(k)
        if i is None:
            i = len(key2id)
            key2id[k] = i
            vpos[i] = k
        return i

    # 边表顺序 = 解析（文件）序，不是 v.evidence 序：v.evidence 是
    # 视图聚类检测顺序（按位置排序），走环平手（同切向数条候选）时的
    # 稳定排序会按此定胜负。旧管线 parse_dxf_edges 按文件序建表，
    # bracket V0 r3 圆处文件序 7A5 分段（[29.17..58.57]，正确续段）在
    # 7A8/7AA 重复副本之前 → 走通；聚类序把 7A8/7AA 排前面 → 走进
    # 49.20 死端（8-07 实测：welded 遍断在 (21.90,140.33)）。
    ev_order = {ev.handle: i for i, ev in enumerate(d.evidence)}
    prims: list = []
    roles_of: list[str] = []
    for h in sorted(v.evidence, key=lambda h: ev_order.get(h, 1 << 30)):
        ev = by_h.get(h)
        if ev is None or ev.role.value not in roles:
            continue
        for p in _prim_from_geom(ev.geom):
            prims.append(p)
            roles_of.append(ev.role.value)
    # 拆分保持来源角色（``with_src`` 返回 (src_index, prim)）
    parts = _split_primitives(prims, with_src=True)

    edges: list[_E] = []
    for src, p in parts:
        role = roles_of[src]
        if p[0] == "L":
            vs, ve = _vid(p[1], p[2]), _vid(p[3], p[4])
            if vs == ve:
                continue                          # 吸附后退化，静默丢弃
            edges.append(_E("L", vs, ve, role=role))
        else:
            _c, cx, cy, r, sa, ea = p
            x1, y1 = cx + r * math.cos(sa), cy + r * math.sin(sa)
            x2, y2 = cx + r * math.cos(ea), cy + r * math.sin(ea)
            vs, ve = _vid(x1, y1), _vid(x2, y2)
            if vs == ve:
                continue
            edges.append(_E("A", vs, ve, cx, cy, r, sa, ea, vs, ve, role=role))
    return edges, vpos


def _is_microg(x1, y1, x2, y2) -> bool:
    return abs(x1 - x2) < MICRO_DX and abs(y1 - y2) < MICRO_DX


def _micro_chain_lengths(edges: list[_E], vpos) -> dict[int, float]:
    """微边链长表 eid→链总长（旧管线 :4983 的移植）。

    HLR B 样条投影的离散碎段端点带 0.03~0.06mm 间隙，无合并图中互不
    邻接；真伪影（弧裁剪挂线）是孤立短微边，真实轮廓碎段连成长链。
    """
    micro_eids = [i for i, e in enumerate(edges)
                  if _is_microg(*vpos[e.vs], *vpos[e.ve])]
    result: dict[int, float] = {}
    if not micro_eids:
        return result
    ep = []                                       # (边序, 端点 0/1, x, y)
    for i, eid in enumerate(micro_eids):
        e = edges[eid]
        ep.append((i, 0, *vpos[e.vs]))
        ep.append((i, 1, *vpos[e.ve]))
    m = len(ep)
    buckets: dict[tuple[int, int], list[int]] = defaultdict(list)
    for i in range(m):
        buckets[(int(ep[i][2] / MICRO_EPS), int(ep[i][3] / MICRO_EPS))].append(i)
    par = list(range(m))

    def _find(i):
        while par[i] != i:
            par[i] = par[par[i]]
            i = par[i]
        return i

    for i in range(m):
        xa, ya = ep[i][2], ep[i][3]
        for bx in (-1, 0, 1):
            for by in (-1, 0, 1):
                for j in buckets.get((int(xa / MICRO_EPS) + bx,
                                      int(ya / MICRO_EPS) + by), []):
                    if j <= i:
                        continue
                    if math.hypot(ep[j][2] - xa, ep[j][3] - ya) < MICRO_EPS:
                        ri, rj = _find(i), _find(j)
                        if ri != rj:
                            par[ri] = rj
    edge_par = list(range(len(micro_eids)))

    def _efind(i):
        while edge_par[i] != i:
            edge_par[i] = edge_par[edge_par[i]]
            i = edge_par[i]
        return i

    for i in range(len(micro_eids)):
        r0, r1 = _find(2 * i), _find(2 * i + 1)
        for j in range(i + 1, len(micro_eids)):
            if _find(2 * j) in (r0, r1) or _find(2 * j + 1) in (r0, r1):
                ri, rj = _efind(i), _efind(j)
                if ri != rj:
                    edge_par[ri] = rj
    chain_len: dict[int, float] = {}
    for i, eid in enumerate(micro_eids):
        e = edges[eid]
        seg = math.hypot(vpos[e.ve][0] - vpos[e.vs][0],
                         vpos[e.ve][1] - vpos[e.vs][1])
        chain_len[_efind(i)] = chain_len.get(_efind(i), 0.0) + seg
    for i, eid in enumerate(micro_eids):
        result[eid] = chain_len[_efind(i)]
    return result


def _weld(edges: list[_E], vpos):
    """微边链端点焊接（旧管线 :3417 的移植）。返回 (vpos2, edges2)。

    范围：链自由端点（簇内度 1）与最近长边端点（<0.3mm）一对一；
    长边-长边绝不焊接（v15 教训：0.03mm 近邻误焊把内圆混进外环）。
    焊接目标限定长边度 1 端点——焊到碎段内点（度 2）会分裂顶点，
    破坏已闭合的环。
    """
    ep = []                                       # (vid, x, y, is_micro)
    for e in edges:
        x1, y1 = vpos[e.vs]
        x2, y2 = vpos[e.ve]
        vm = _is_microg(x1, y1, x2, y2)
        ep.append((e.vs, x1, y1, vm))
        ep.append((e.ve, x2, y2, vm))
    par: dict[int, int] = {}

    def _f(i):
        par.setdefault(i, i)
        while par[i] != i:
            par[i] = par[par[i]]
            i = par[i]
        return i

    def _u(i, j):
        ri, rj = _f(i), _f(j)
        if ri != rj:
            par[ri] = rj

    buckets: dict[tuple[int, int], list[int]] = defaultdict(list)
    for i, (vid, x, y, vm) in enumerate(ep):
        if vm:
            buckets[(int(x / MICRO_EPS), int(y / MICRO_EPS))].append(i)

    for i, (vid, x, y, vm) in enumerate(ep):
        if not vm:
            continue
        for bx in (-1, 0, 1):
            for by in (-1, 0, 1):
                for j in buckets.get((int(x / MICRO_EPS) + bx,
                                      int(y / MICRO_EPS) + by), []):
                    if j == i:
                        continue
                    vj, xj, yj, _ = ep[j]
                    if math.hypot(xj - x, yj - y) < MICRO_EPS:
                        _u(vid, vj)

    # 链自由端点（簇内微边端点度 1）→ 最近长边度 1 端点，<0.3mm
    long_deg = Counter(vid for vid, x, y, vm in ep if not vm)
    long_ep = [(i, vid, x, y) for i, (vid, x, y, vm) in enumerate(ep)
               if not vm and long_deg[vid] == 1]
    long_buckets: dict[tuple[int, int], list] = defaultdict(list)
    for i, vid, x, y in long_ep:
        long_buckets[(int(x / WELD_GAP), int(y / WELD_GAP))].append(
            (i, vid, x, y))
    deg = Counter(_f(vid) for vid, x, y, vm in ep if vm)
    for i, (vid, x, y, vm) in enumerate(ep):
        if not vm:
            continue
        if deg[_f(vid)] != 1:
            continue
        best = None
        for bx in (-1, 0, 1):
            for by in (-1, 0, 1):
                for j, vj, xj, yj in long_buckets.get(
                        (int(x / WELD_GAP) + bx, int(y / WELD_GAP) + by), []):
                    d = math.hypot(xj - x, yj - y)
                    if d < WELD_GAP and (best is None or d < best[0]):
                        best = (d, vj)
        if best is not None:
            _u(vid, best[1])

    # 簇 rep 位置：**弧端点优先**（弧是刚性几何，微链段是软证据）。
    # 微-微传递合并会沿链把弧端点卷进簇；若按"首见端点"取 rep，弧端点
    # 会被拖离圆——bracket V0 r3 实测被拖 0.955mm：弧真端点 (19.94,141.05)
    # 距心 2.995（在圆上），被链中间点 (19.28,141.74)（距心 3.744）顶替，
    # 环输出直线变斜线 + 弧起点离圆 0.74mm，发射器三点弧近共线（拟合
    # r≈15 vs 原 3）→ BRepCheck 判 B-rep 无效。
    rep_pos: dict[int, tuple[float, float]] = {}
    for vid, x, y, _vm in ep:
        rep_pos.setdefault(_f(vid), (x, y))
    anchor: dict[int, tuple[float, float]] = {}
    for e in edges:
        if e.t == "A" and e.r > 0.0:
            anchor.setdefault(_f(e.vs), vpos[e.vs])
            anchor.setdefault(_f(e.ve), vpos[e.ve])
    rep_pos.update(anchor)
    vpos2 = {v: rep_pos.get(_f(v), p) for v, p in vpos.items()}
    edges2 = [replace(e, vs=_f(e.vs), ve=_f(e.ve),
                      sa_v=_f(e.sa_v), ea_v=_f(e.ea_v)) for e in edges]
    return vpos2, edges2


def _glue(edges: list[_E], vpos, *, cap: float | None = None):
    """顶点胶合第三遍（旧 :932/:979 两遍合并的移植）。返回 (vpos2, edges2)。

    与 ``_weld`` 的分工是**证据强度**：``_weld`` 只焊微边链自由端
    （长-长绝不焊接，v15 误焊教训），胶合放开到全部顶点——它消费的
    正是"长边端点之间 0.01~0.5mm 微缝落在网格两侧、SNAP 合并不上"的
    情形（D79307 V1 底脚链整条被度 1 修剪删掉即此）。因此胶合只作为
    raw/welded **都失败**时的兜底，不参与已成功视图的竞逐。

    ``cap`` 非 None 时启用**簇直径上限**（``cap`` mm）：0.5mm 近邻合并
    沿微线段链**传递**扩散，能把整段轮廓塌成一簇（簇代表位与链上真实
    位置差数毫米，环被一条拉长边顶替）。实测 D79307：有界胶合使
    V0 覆盖率 0.541×1.0 → 1.0×1.0、V1 环面积 270.1 → 262.0（金值
    剖面 263.6），三视图全面优于无界版；无界版仍是兜底（YZYX 等
    依赖链式合并救环的靶子只在有界版失败时才走它）。有界模式下
    近邻合并**不再要求"任一端为自由端"**——直径上限已经从结构上
    阻止了链式塌缩，无条件合并才能把两条微链之间的缝也合上。

    **边数/边序保持不变**：合并后退化成自环的边留在表里（``_one_pass``
    会跳过度 0 的边），这样 ``micro_len``（eid→链长）的下标依旧有效。

    ⚠️ 但"退化成自环"不许是**胶合自己造出来的**，且只保护**圆弧**：弧是
    刚性几何，两端点被并进同一簇等于整条弧抹掉（不是补缝）；直线微链的
    传递合并正是这一遍要的（D79307 V1 底脚链靠它救回），不能拦。实测
    D79307 V2 的 R1.75 圆头：两段圆弧的端点与微线段链落在同一片 0.5mm
    邻域里被传递合并，圆弧塌成零长（raw 1.32mm → 0.00），缺口处的微边被
    拉长 7.5mm 顶上，钥匙孔面于是沿对角线抄近路。故 union 带**弧禁并
    约束**：任一弧边的两个端点簇不得合并（弧邻接表随 union 维护）。
    """
    parent = {v: v for v in vpos}
    #: 弧的禁并邻接（根 → 因某条弧而不许合并的根）。只记弧边。
    arc_nb: dict[int, set[int]] = defaultdict(set)
    #: 每个顶点所属圆弧的「圆签名」（圆心+半径量化）——同一圆上**跨弧**
    #: 端点的禁并依据（``arc_nb`` 只管同一条弧的两端）。
    circ: dict[int, set[tuple[float, float, float]]] = defaultdict(set)
    for e in edges:
        if e.t == "A" and e.vs != e.ve:
            arc_nb[e.vs].add(e.ve)
            arc_nb[e.ve].add(e.vs)
        if e.t == "A" and e.r > 0.0:
            sig = (round(e.cx, 3), round(e.cy, 3), round(e.r, 3))
            circ[e.vs].add(sig)
            circ[e.ve].add(sig)

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    #: 簇成员（仅 ``cap`` 模式需要——用于判直径）；根 → 顶点集合
    members: dict[int, set[int]] = {v: {v} for v in vpos} if cap is not None else {}

    def union(a: int, b: int) -> bool:
        ra, rb = find(a), find(b)
        if ra == rb:
            return True
        if rb in arc_nb.get(ra, ()) or ra in arc_nb.get(rb, ()):
            return False              # 合并会把一条弧抹成自环
        if cap is not None:
            pts = members[ra] | members[rb]
            xs = [vpos[v][0] for v in pts]
            ys = [vpos[v][1] for v in pts]
            if max(xs) - min(xs) > cap or max(ys) - min(ys) > cap:
                return False          # 簇直径超限：合并会拉长边
            # 同一圆上的弧端点不许远距离合并（见 GLUE_COCIRC）：跨簇逐对查，
            # 任一对同圆端点相距 > GLUE_COCIRC 即拒绝——粘上会把两段弧之间
            # 的真实弧长塌成零，环在该圆上折返出尖刺。
            common = ({s for x in members[ra] for s in circ.get(x, ())}
                      & {s for y in members[rb] for s in circ.get(y, ())})
            if common:
                ma = [(x, [s for s in circ.get(x, ()) if s in common])
                      for x in members[ra]]
                mb = [(y, [s for s in circ.get(y, ()) if s in common])
                      for y in members[rb]]
                for x, sx in ma:
                    if not sx:
                        continue
                    for y, sy in mb:
                        if not sy or not set(sx) & set(sy):
                            continue
                        if math.hypot(vpos[x][0] - vpos[y][0],
                                      vpos[x][1] - vpos[y][1]) > GLUE_COCIRC:
                            return False
            members[rb] = pts
            del members[ra]
        parent[ra] = rb
        for x in tuple(arc_nb.pop(ra, ())):
            arc_nb[x].discard(ra)
            arc_nb[x].add(rb)
            arc_nb[rb].add(x)
        arc_nb[rb].discard(ra)
        return True

    # 1) 近邻顶点合并（旧 :932，0.5mm）。
    #    0.5mm 比 PDF 矢量化微线段本身（~0.04mm）大一个量级：无差别合并会把
    #    每条微边的两端并掉 ⇒ 整条链塌成一簇，簇代表位置（首见/弧端点）与
    #    链上各段真实位置可差数毫米，环/面在簇边缘就被一条**拉长的边**顶替
    #    （实测 D79307：V1 底脚 3.7mm 的斜线抄近路 +7.6mm²；V2 钥匙孔圆头
    #    两段对角捷径 −26% 面积）。``cap`` 模式靠**簇直径上限**从结构上
    #    拦住这类塌缩（链本身最长只有几 mm，不可能把整段轮廓并进一簇）；
    #    无界模式（``cap=None``，v0.6.44 兜底）保留原有语义。
    ids = list(vpos)
    grid: dict[tuple[int, int], list[int]] = defaultdict(list)
    for v in ids:
        x, y = vpos[v]
        grid[(int(x / GLUE_CLOSE), int(y / GLUE_CLOSE))].append(v)
    for v in ids:
        x, y = vpos[v]
        cx, cy = int(x / GLUE_CLOSE), int(y / GLUE_CLOSE)
        for bx in (-1, 0, 1):
            for by in (-1, 0, 1):
                for w in grid.get((cx + bx, cy + by), ()):
                    if w <= v:
                        continue
                    xw, yw = vpos[w]
                    if math.hypot(xw - x, yw - y) <= GLUE_CLOSE:
                        union(v, w)

    # 2) 悬空顶点吸附（旧 :979，1.5mm）到最近的非悬空顶点。
    #    度在合并后的簇上算：簇内端点已合并，度 1 才是真断口。
    deg: Counter = Counter()
    for e in edges:
        vs, ve = find(e.vs), find(e.ve)
        if vs != ve:
            deg[vs] += 1
            deg[ve] += 1
    dangling = [v for v, d in deg.items() if d == 1]
    if dangling:
        live = [v for v in deg if deg[v] > 1]
        live_grid: dict[tuple[int, int], list[int]] = defaultdict(list)
        for w in live:
            x, y = vpos[w]
            live_grid[(int(x / GLUE_GAP), int(y / GLUE_GAP))].append(w)
        for v in dangling:
            x, y = vpos[v]
            cx, cy = int(x / GLUE_GAP), int(y / GLUE_GAP)
            best, bd = None, GLUE_GAP
            for bx in (-1, 0, 1):
                for by in (-1, 0, 1):
                    for w in live_grid.get((cx + bx, cy + by), ()):
                        xw, yw = vpos[w]
                        d = math.hypot(xw - x, yw - y)
                        if d < bd:
                            bd, best = d, w
            if best is not None:
                union(v, best)

    # 簇代表位置：**弧端点优先**（同 ``_weld``——弧是刚性几何，
    # 被卷进簇的其他端点会把弧起点拖离圆）
    rep_pos: dict[int, tuple[float, float]] = {}
    for v in vpos:
        rep_pos.setdefault(find(v), vpos[v])
    anchor: dict[int, tuple[float, float]] = {}
    for e in edges:
        if e.t == "A" and e.r > 0.0:
            anchor.setdefault(find(e.vs), vpos[e.vs])
            anchor.setdefault(find(e.ve), vpos[e.ve])
    rep_pos.update(anchor)
    vpos2 = {v: rep_pos[find(v)] for v in vpos}
    edges2 = [replace(e, vs=find(e.vs), ve=find(e.ve),
                      sa_v=find(e.sa_v) if e.sa_v >= 0 else -1,
                      ea_v=find(e.ea_v) if e.ea_v >= 0 else -1)
              for e in edges]
    return vpos2, edges2


# ---------------------------------------------------------------------------
# 单遍提取（旧管线 _extract_rings_impl 的移植）
# ---------------------------------------------------------------------------

def _leave_angle(e: _E, v: int, vpos) -> float:
    """在顶点 v 处沿边 e 出发（朝另一端）的切向角。

    弧：θ ± π/2（θ 为该顶点极角）——CCW 起点端取 +，终点端取 −。
    """
    x, y = vpos[v]
    if e.t == "L":
        ox, oy = vpos[e.ve if v == e.vs else e.vs]
        return math.atan2(oy - y, ox - x)
    th = math.atan2(y - e.cy, x - e.cx)
    return th + math.pi / 2 if v == e.sa_v else th - math.pi / 2


def _sweep(e: _E, dep: int, arr: int, vpos) -> float:
    """沿边从 dep 顶点走到 arr 顶点时的切向转角（归一化到 (-π, π]）。

    弧上切向角 = 极角 ± π/2，两端 ± 号相同（同向）或相反（回头走），
    但两种情形下 ±90° 在差值里都对消——故转角 = 两端极角之差。
    """
    if e.t != "A":
        return 0.0
    xd, yd = vpos[dep]
    xa, ya = vpos[arr]
    return _norm(math.atan2(ya - e.cy, xa - e.cx)
                 - math.atan2(yd - e.cy, xd - e.cx))


def _one_pass(edges: list[_E], vpos, micro_len: dict[int, float]):
    """单遍提取（不焊接 / 已焊接边图各跑一遍）。返回 _Pass 或 None。"""
    adj: dict[int, list] = {v: [] for v in vpos}
    for eid, e in enumerate(edges):
        if e.vs == e.ve:
            continue
        adj[e.vs].append((eid, e.ve, _leave_angle(e, e.vs, vpos)))
        adj[e.ve].append((eid, e.vs, _leave_angle(e, e.ve, vpos)))
    for v in adj:
        adj[v].sort(key=lambda x: x[2])

    # 往返副本签名：同几何的 HLR 双副本视作一条（旧 :3798）
    sig: dict[int, tuple] = {}
    for eid, e in enumerate(edges):
        if e.t == "A" and e.r > 0:
            a1, a2 = round(math.degrees(e.sa), 1), round(math.degrees(e.ea), 1)
            sig[eid] = ("A", round(e.cx, 2), round(e.cy, 2), round(e.r, 2),
                        min(a1, a2), max(a1, a2))
        else:
            x1, y1 = vpos[e.vs]
            x2, y2 = vpos[e.ve]
            sig[eid] = ("L", round(min(x1, x2), 2), round(min(y1, y2), 2),
                        round(max(x1, x2), 2), round(max(y1, y2), 2))

    # 连通分量（修剪前，与旧同序）
    seen: set[int] = set()
    comps: list[list[int]] = []
    for v in vpos:
        if v in seen:
            continue
        stack = [v]
        seen.add(v)
        vs = []
        while stack:
            u = stack.pop()
            vs.append(u)
            for _eid, w, _ang in adj.get(u, []):
                if w not in seen:
                    seen.add(w)
                    stack.append(w)
        comps.append(vs)

    # 修剪度 1 悬边（迭代删除）：假轮廓挂线端点悬空会劫持面遍历
    changed = True
    while changed:
        changed = False
        for v in [v for v in adj if len(adj.get(v, [])) == 1]:
            if not adj.get(v):
                continue
            _eid, w, _ang = adj[v][0]
            del adj[v]
            adj[w] = [t for t in adj[w] if t[1] != v]
            changed = True

    def _is_micro_edge(eid: int) -> bool:
        e = edges[eid]
        if not _is_microg(*vpos[e.vs], *vpos[e.ve]):
            return False
        return micro_len.get(eid, 0.0) < MICRO_CHAIN_MIN

    def _arc_cont(prev_edge, incoming, eid, ang_out) -> int:
        """候选弧与来边同圆同向续段？0=是 1=否（旧 :4062）。"""
        if prev_edge is None:
            return 1
        pe, ce = edges[prev_edge], edges[eid]
        if pe.t != "A" or ce.t != "A":
            return 1
        if abs(pe.cx - ce.cx) > 0.1 or abs(pe.cy - ce.cy) > 0.1 \
                or abs(pe.r - ce.r) > 0.1:
            return 1
        if _is_micro_edge(eid):
            return 1
        return 0 if abs(_norm(ang_out - incoming)) < math.pi / 2 else 1

    def _advance(cur, incoming, used, used_sigs, prev_edge, rule):
        """按 rule（min=最左转 / max=最右转）选下一条边。"""
        # 掉头候选（ccw≈0）赋 2π 排最后（容差 5.7°：HLR 弧碎段切向抖动
        # 可达 2°）；直行（ccw≈π）归一——旧 :4112
        out_ref = incoming + math.pi
        if out_ref > math.pi:
            out_ref -= TAU
        cands = []
        for eid, other, ang in adj.get(cur, []):
            if eid in used or sig[eid] in used_sigs:
                if _DBG >= 3:
                    why = "已用" if eid in used else "签名重复"
                    print(f"[adv3] v{cur} 排除边 {eid}（{why}）sig={sig[eid]}")
                continue
            ccw = ang - out_ref
            if ccw < -math.pi:
                ccw += TAU
            if ccw < 0:
                ccw += TAU
            if ccw < 0.1 or ccw > TAU - 0.1:
                ccw = TAU
            elif abs(ccw - math.pi) < 0.1:
                ccw = math.pi
            cands.append((ccw, eid, other, ang))
        if not cands:
            if _DBG >= 3:
                for eid, other, ang in adj.get(cur, []):
                    st = ("已用" if eid in used else
                          "签名重复" if sig[eid] in used_sigs else "空闲")
                    print(f"[adv3] 断点 v{cur} @({vpos[cur][0]:.2f},"
                          f"{vpos[cur][1]:.2f}) 边{eid}→"
                          f"({vpos[other][0]:.2f},{vpos[other][1]:.2f}) "
                          f"[{st}] sig={sig[eid]}")
            return None
        # 微边支路跳过（伪影挂线）——仅在存在非微边候选时
        big = [c for c in cands if not _is_micro_edge(c[1])]
        if big:
            cands = big
        deg = len(adj.get(cur, []))
        tie_arc_first = deg <= 2
        # 弧优先只在度 ≤2 时生效；交点（度 >2）直线优先防自交（旧 v0.6.3）
        cands.sort(key=lambda c: (
            _arc_cont(prev_edge, incoming, c[1], c[3]) if deg <= 2 else 1,
            c[0] if rule == "min" else -((c[0] + 1e-6) % TAU),
            0 if (edges[c[1]].t == "A") == tie_arc_first else 1))
        return cands[0]

    def polyline_ring(vids, rule="min"):
        """最左转（min）/ 最右转（max）折线外环遍历（旧 :4090）。

        起点选最下顶点（y 最小）；初始移动方向 = 向东（外环底边向
        东、内部在上方）。回到起点即闭合；无候选返回 None。
        """
        v0 = min(vids, key=lambda v: (vpos[v][1], vpos[v][0]))
        if _DBG:
            print(f"[walk:{rule}] 组件 {len(vids)} 顶点，v0={v0} @ "
                  f"({vpos[v0][0]:.2f},{vpos[v0][1]:.2f}) deg={len(adj.get(v0, []))}")
        cur = v0
        incoming = 0.0
        used: set[int] = set()
        used_sigs: set[tuple] = set()
        ring: list[tuple[int, int, int]] = []
        prev_edge = None
        for it in range(10000):
            step = _advance(cur, incoming, used, used_sigs, prev_edge, rule)
            if step is None:
                if _DBG:
                    e = edges[prev_edge] if prev_edge is not None else None
                    print(f"[walk:{rule}] 断在第 {it} 步: cur={cur} "
                          f"({vpos[cur][0]:.2f},{vpos[cur][1]:.2f}) "
                          f"deg={len(adj.get(cur, []))} incoming={math.degrees(incoming):.1f}° "
                          f"last_edge={e.t if e else None} used={len(used)}")
                return None
            _ccw, eid, nxt, ang = step
            if _DBG and (it < 25 or it % 200 == 0 or _DBG >= 2):
                e = edges[eid]
                print(f"[walk:{rule}] {it:>5}: {vpos[cur][0]:7.2f},{vpos[cur][1]:7.2f}"
                      f" --{e.t}--> {vpos[nxt][0]:7.2f},{vpos[nxt][1]:7.2f}"
                      f"  ccw={math.degrees(_ccw):6.1f}° inc={math.degrees(incoming):6.1f}°")
            ring.append((eid, cur, nxt))
            used.add(eid)
            used_sigs.add(sig[eid])
            # 弧的到达切向 = 出发切向转过 sweep；归一化防累积误差
            incoming = _norm(ang + _sweep(edges[eid], cur, nxt, vpos))
            prev_edge = eid
            cur = nxt
            if cur == v0:
                if _DBG:
                    a = _shoelace([vpos[f] for _e, f, _t in ring])
                    print(f"[walk:{rule}] 闭合: {it + 1} 步 面积 {a:.2f} "
                          f"起点 ({vpos[v0][0]:.2f},{vpos[v0][1]:.2f})")
                return ring
        if _DBG:
            print(f"[walk:{rule}] 超 10000 步未闭合（起点 "
                  f"({vpos[v0][0]:.2f},{vpos[v0][1]:.2f})）")
        return None

    def face_ring_from_directed_edge(eid0, v_from, v_to):
        """无合并图左面遍历: 有向边 (v_from→v_to) 的面环（旧 :4197）。"""
        ang0 = None
        for eid, w, ang in adj.get(v_from, []):
            if eid == eid0 and w == v_to:
                ang0 = ang
                break
        if ang0 is None:
            return None
        ring: list[tuple[int, int, int]] = [(eid0, v_from, v_to)]
        used = {eid0}
        used_sigs = {sig[eid0]}
        incoming = ang0
        cur = v_to
        start_v = v_from
        prev_edge = eid0
        for _ in range(10000):
            step = _advance(cur, incoming, used, used_sigs, prev_edge, "max")
            if step is None:
                return None
            _ccw, eid, nxt, ang = step
            ring.append((eid, cur, nxt))
            used.add(eid)
            used_sigs.add(sig[eid])
            incoming = _norm(ang + _sweep(edges[eid], cur, nxt, vpos))
            prev_edge = eid
            cur = nxt
            if cur == start_v:
                return ring
        return None

    def _has_dup_vertex(r) -> bool:
        vc: set[int] = set()
        for _e, f, _t in r:
            if f in vc:
                return True
            vc.add(f)
        return False

    def face_rings_all(vids):
        """对分量内所有有向边做左面遍历 → 面积最大的**非自交**面环。

        与旧 :4292 的差异（先自交淘汰、再比面积）：旧版把最大面积环
        直接交给外层，外层再因自交否决——面遍历的最大环可能是绕
        桥边/伪影的自交大环（bracket 三视图_v4 side 视图中它的面积
        2588.92 > 真外环 2244），一否决整条面通道就丢，而面积第三、
        四位的干净环（真外环）从没进过比较。自交淘汰必须在同一层内
        做，否则是"先污染后过滤"。
        """
        vset = set(vids)
        best = None
        best_area = 0.0
        n_try = n_ok = 0
        closed: list = []                      # (面积, 段数, 自交) 诊断用
        seen_dirs: set[tuple] = set()
        for v in vids:
            for eid, w, _ang in adj.get(v, []):
                if w not in vset or (eid, v, w) in seen_dirs:
                    continue
                seen_dirs.add((eid, v, w))
                n_try += 1
                r = face_ring_from_directed_edge(eid, v, w)
                if r is None:
                    continue
                n_ok += 1
                a = _shoelace([vpos[f] for _e, f, _t in r])
                dup = _has_dup_vertex(r)
                if _DBG:
                    closed.append((a, len(r), dup))
                if not dup and a > best_area:
                    best_area = a
                    best = r
        if _DBG:
            print(f"[face] 有向边 {n_try}，闭合 {n_ok}，最大非自交面积 "
                  f"{best_area:.2f}（{len(best) if best else 0} 段）")
            tops = sorted(closed, key=lambda c: -c[0])[:8]
            for a, n, dup in tops:
                print(f"[face]   候选 面积 {a:>10.2f} / {n:>3} 段"
                      f"{'  [自交]' if dup else ''}")
        return best

    # 分量 → 候选环（min/max/面遍历）→ 自交淘汰 + 面积取大
    best_pass = None
    n_comp = 0
    for vs in sorted(comps, key=len, reverse=True):
        vs = [v for v in vs if v in adj]
        if len(vs) < 3:
            continue
        if any(adj.get(v) for v in vs):
            n_comp += 1
        cands = []
        for _lbl, r in (("poly-min", polyline_ring(vs, "min")),
                        ("poly-max", polyline_ring(vs, "max"))):
            if r is not None:
                cands.append(r)
        fr = face_rings_all(vs)
        if fr is not None:
            cands.append(fr)
        ring = None
        best_area = -1.0
        for r in cands:
            # 自交淘汰：绕内部孔全周的环重复访问顶点，面积虚高（旧 :4344）
            vc: set[int] = set()
            dup = False
            for _e, f, _t in r:
                if f in vc:
                    dup = True
                    break
                vc.add(f)
            if dup:
                continue
            a = _shoelace([vpos[f] for _e, f, _t in r])
            if a > best_area:
                best_area = a
                ring = r
        if ring is None:
            continue
        pts = [vpos[f] for _e, f, _t in ring]
        area = _shoelace(pts)
        if area < AREA_FLOOR:
            continue
        if best_pass is None or area > best_pass.area:
            xs = [p[0] for p in pts]
            ys = [p[1] for p in pts]
            best_pass = _Pass(tuple(ring), area,
                              (min(xs), min(ys), max(xs), max(ys)), 0)
    if best_pass is None:
        return None
    return _Pass(best_pass.ring, best_pass.area, best_pass.vbox, n_comp)


# ---------------------------------------------------------------------------
# 提取入口
# ---------------------------------------------------------------------------

def _seg_signed_area(segs: tuple[RingSeg, ...]) -> float:
    """有符号面积（顶点鞋带）——算法单源在 ``Profile2.signed_area``。"""
    return Profile2(tuple(segs)).signed_area()


def _reverse_segs(segs: tuple[RingSeg, ...]) -> tuple[RingSeg, ...]:
    out = []
    for s in reversed(segs):
        if s.kind == "line":
            out.append(RingSeg("line", s.p2, s.p1))
        else:
            out.append(RingSeg("arc", s.p2, s.p1, s.center, s.radius,
                               not s.ccw, s.ea, s.sa))
    return tuple(out)


def _geom_bbox(segs: tuple[RingSeg, ...]) -> BBox2:
    """几何 bbox 含弧顶（旧 :3502 ``_ring_geom_bbox``）——算法单源在 ``Profile2.bbox``。"""
    return Profile2(tuple(segs)).bbox()


def _to_ring(p: _Pass, edges: list[_E], vpos, rule: str,
             view_bbox: BBox2 | None, n_edges: int, n_micro: int) -> Ring:
    segs: list[RingSeg] = []
    for eid, f, t in p.ring:
        e = edges[eid]
        x1, y1 = vpos[f]
        x2, y2 = vpos[t]
        if e.t == "L":
            segs.append(RingSeg("line", Point2(x1, y1), Point2(x2, y2)))
        else:
            if f == e.sa_v:
                sa, ea, ccw = e.sa, e.ea, True
            else:
                sa, ea, ccw = e.ea, e.sa, False
            segs.append(RingSeg("arc", Point2(x1, y1), Point2(x2, y2),
                                Point2(e.cx, e.cy), e.r, ccw, sa, ea))
    segs_t = tuple(segs)
    # 统一为纸面 CCW（正面积）——profile 契约（右手法则为正）的前提
    if _seg_signed_area(segs_t) < 0:
        segs_t = _reverse_segs(segs_t)
    cov = (1.0, 1.0)
    if view_bbox is not None:
        vw = view_bbox.width
        vh = view_bbox.height
        # ⚠️ 必须用**含弧顶的几何 bbox**，不能只用顶点 bbox（p.vbox）：
        # 外轮廓由大弧构成时，弧顶可能显著伸出两端顶点之外。20180425
        # 气缸前盖的 φ155 双平边盘实测——两段 r77.5 弧的顶点落在 x
        # 240.0/343.9，弧顶却鼓到 214.5/369.5，顶点 bbox 宽只有 103.9，
        # 覆盖率算成 0.67 被门控误杀。旧管线用顶点 bbox 是因为它把弧
        # 已离散成折线（顶点即极值点）；新框架保存真弧，口径要跟着换
        gb = _geom_bbox(segs_t)
        rw = gb.width
        rh = gb.height
        if vw > 0 and vh > 0:
            cov = (rw / vw, rh / vh)
    return Ring(segs_t, p.area, _geom_bbox(segs_t), rule, cov,
                n_edges, n_micro, p.n_comp)


# ---------------------------------------------------------------------------
# 内界面提取（全角色边图 → 所有有界面）
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class FaceRing:
    """视图边图中的一个**有界面**（闭合、简单、纸面 CCW 正面积）。

    与外环 ``Ring`` 的分工：``Ring`` 回答"这个视图的零件外轮廓是什么"，
    ``FaceRing`` 回答"这个视图把平面切成了哪些块"。图纸上的孔/槽/腔
    边界（可见或隐藏）都会把视图平面切成至少两块——内腔通道消费除
    **主体块**（覆盖率接近 1 的那块）以外的面，再用垂直视图的证据
    裁决它是"切除"还是"凸出"。
    """

    segs: tuple[RingSeg, ...]
    area: float
    bbox: BBox2
    coverage: tuple[float, float]
    n_boundary: int                        # 边界段数（拆分后）
    n_hidden: int                          # 其中来源角色为 hidden 的段数
    n_visible: int
    rule: str                              # "raw" | "glued"
    #: 隐藏段**长度**占比（0..1）。内腔判据用它而不是段数占比：PDF
    #: 矢量化图纸的腔体边界是碎段链，段数会被比例尺无关的短段放大。
    hidden_frac: float = 0.0

    def to_profile(self) -> Profile2:
        return Profile2(self.segs)


def _enum_faces(edges: list[_E], vpos, micro_len: dict[int, float]):
    """枚举边图全部**有界面**（左面遍历 + 去重）。

    返回 ``[(signed_area, ring, comp_index)]``，``ring`` 为
    ``(eid, from_v, to_v)`` 序列。只保留**正面积**（CCW 简单环）：
    左面遍历对无界面/外表面给出负面积或自交环，两者都不是"图纸上的
    一块材料/空腔"。微边（PDF 矢量化碎段）必须全部参与——隐藏腔体的
    边界正是碎段链（IMU V1 的角凹腔实测）。
    """
    adj: dict[int, list] = {v: [] for v in vpos}
    for eid, e in enumerate(edges):
        if e.vs == e.ve:
            continue
        adj[e.vs].append((eid, e.ve, _leave_angle(e, e.vs, vpos)))
        adj[e.ve].append((eid, e.vs, _leave_angle(e, e.ve, vpos)))
    for v in adj:
        adj[v].sort(key=lambda x: x[2])

    # 修剪度 1 悬边（同 ``_one_pass``）
    changed = True
    while changed:
        changed = False
        for v in [v for v in adj if len(adj.get(v, [])) == 1]:
            if not adj.get(v):
                continue
            _eid, w, _ang = adj[v][0]
            del adj[v]
            adj[w] = [t for t in adj[w] if t[1] != v]
            changed = True

    # 往返副本签名（同 ``_one_pass``）
    sig: dict[int, tuple] = {}
    for eid, e in enumerate(edges):
        if e.t == "A" and e.r > 0:
            a1, a2 = round(math.degrees(e.sa), 1), round(math.degrees(e.ea), 1)
            sig[eid] = ("A", round(e.cx, 2), round(e.cy, 2), round(e.r, 2),
                        min(a1, a2), max(a1, a2))
        else:
            x1, y1 = vpos[e.vs]
            x2, y2 = vpos[e.ve]
            sig[eid] = ("L", round(min(x1, x2), 2), round(min(y1, y2), 2),
                        round(max(x1, x2), 2), round(max(y1, y2), 2))

    def _is_micro_edge(eid: int) -> bool:
        e = edges[eid]
        if not _is_microg(*vpos[e.vs], *vpos[e.ve]):
            return False
        return micro_len.get(eid, 0.0) < MICRO_CHAIN_MIN

    def _arc_cont(prev_edge, incoming, eid, ang_out) -> int:
        if prev_edge is None:
            return 1
        pe, ce = edges[prev_edge], edges[eid]
        if pe.t != "A" or ce.t != "A":
            return 1
        if abs(pe.cx - ce.cx) > 0.1 or abs(pe.cy - ce.cy) > 0.1 \
                or abs(pe.r - ce.r) > 0.1:
            return 1
        if _is_micro_edge(eid):
            return 1
        return 0 if abs(_norm(ang_out - incoming)) < math.pi / 2 else 1

    def _advance(cur, incoming, used, used_sigs, prev_edge):
        out_ref = incoming + math.pi
        if out_ref > math.pi:
            out_ref -= TAU
        cands = []
        for eid, other, ang in adj.get(cur, []):
            if eid in used or sig[eid] in used_sigs:
                continue
            ccw = ang - out_ref
            if ccw < -math.pi:
                ccw += TAU
            if ccw < 0:
                ccw += TAU
            if ccw < 0.1 or ccw > TAU - 0.1:
                ccw = TAU
            elif abs(ccw - math.pi) < 0.1:
                ccw = math.pi
            cands.append((ccw, eid, other, ang))
        if not cands:
            return None
        big = [c for c in cands if not _is_micro_edge(c[1])]
        if big:
            cands = big
        deg = len(adj.get(cur, []))
        tie_arc_first = deg <= 2
        cands.sort(key=lambda c: (
            _arc_cont(prev_edge, incoming, c[1], c[3]) if deg <= 2 else 1,
            -((c[0] + 1e-6) % TAU),
            0 if (edges[c[1]].t == "A") == tie_arc_first else 1))
        return cands[0]

    # 连通分量（修剪后）
    seen: set[int] = set()
    comps: list[list[int]] = []
    for v in vpos:
        if v in seen or v not in adj:
            continue
        stack = [v]
        seen.add(v)
        vs = []
        while stack:
            u = stack.pop()
            vs.append(u)
            for _eid, w, _ang in adj.get(u, []):
                if w not in seen:
                    seen.add(w)
                    stack.append(w)
        comps.append(vs)

    def _signed(pts) -> float:
        a = 0.0
        n = len(pts)
        for i in range(n):
            x1, y1 = pts[i]
            x2, y2 = pts[(i + 1) % n]
            a += x1 * y2 - x2 * y1
        return a / 2.0

    faces = []
    seen_faces: set[frozenset] = set()
    for ci, vs in enumerate(comps):
        if len(vs) < 3:
            continue
        vset = set(vs)
        for v0 in vs:
            for eid0, w0, ang0 in adj.get(v0, []):
                if w0 not in vset:
                    continue
                ring = [(eid0, v0, w0)]
                used = {eid0}
                used_sigs = {sig[eid0]}
                incoming = ang0
                cur, prev = w0, eid0
                closed = False
                for _ in range(4000):
                    step = _advance(cur, incoming, used, used_sigs, prev)
                    if step is None:
                        break
                    _ccw, eid, nxt, ang = step
                    ring.append((eid, cur, nxt))
                    used.add(eid)
                    used_sigs.add(sig[eid])
                    incoming = _norm(ang + _sweep(edges[eid], cur, nxt, vpos))
                    prev = eid
                    cur = nxt
                    if cur == v0:
                        closed = True
                        break
                if not closed:
                    continue
                key = frozenset(e for e, _f, _t in ring)
                if key in seen_faces:
                    continue
                pts = [vpos[f] for _e, f, _t in ring]
                a = _signed(pts)
                if a <= 0.0:
                    continue                # 外表面/顺时针 = 不是有界面
                # 简单性：顶点不得重复（绕孔全周的环面积虚高）
                vc: set[int] = set()
                dup = False
                for _e, f, _t in ring:
                    if f in vc:
                        dup = True
                        break
                    vc.add(f)
                if dup:
                    continue
                seen_faces.add(key)
                faces.append((a, ring, ci, len(vs)))
    return faces


def _enum_faces_dcel(edges: list[_E], vpos, micro_len: dict[int, float]):
    """DCEL 标准左面遍历 —— 切线折返处也能走，``_enum_faces`` 的补充。

    ``_enum_faces`` 在顶点处把「与入边几乎共线」的候选归一成 TAU 并优先
    直行；**腔口与轮廓相切**的地方因此走不进去（IMU V1 的 L 形角缺口：
    缺口腔壁与外轮廓的 r2 圆角相切），整块腔体面丢失。这里改用 DCEL 的
    定义——「从 twin（入边反向）起顺时针最近的出边」：候选按
    ``(twin_eff − eff) mod TAU`` 排序，其中 ``eff = 角 + bend·ε``，
    ``bend`` 取弧的弯曲方向（CCW +1 / CW −1 / 直线 0）。同角时由曲率
    决定谁在谁的顺时针侧，切向折返成为合法选择而不是退化。

    返回 ``[(signed_area, ring, 0)]``，``ring`` 为 ``(eid, from_v, to_v)``；
    只保留正面积简单环（与 ``_enum_faces`` 同口径）。实测覆盖 IMU V1 的
    两个角缺口腔 + 槽腔，``_enum_faces`` 只给出主体块。
    """
    ang_eps = 1e-7

    def _bend(eid: int, dep: int) -> int:
        e = edges[eid]
        if e.t != "A":
            return 0
        return 1 if dep == e.sa_v else -1

    adj: dict[int, list] = {v: [] for v in vpos}
    for eid, e in enumerate(edges):
        if e.vs == e.ve:
            continue
        adj[e.vs].append((eid, e.ve, _leave_angle(e, e.vs, vpos),
                          _bend(eid, e.vs)))
        adj[e.ve].append((eid, e.vs, _leave_angle(e, e.ve, vpos),
                          _bend(eid, e.ve)))
    for v in adj:
        adj[v].sort(key=lambda x: (x[2], x[3]))

    # 修剪度 1 悬边（同 ``_enum_faces``）
    changed = True
    while changed:
        changed = False
        for v in [v for v in adj if len(adj.get(v, [])) == 1]:
            if not adj.get(v):
                continue
            _eid, w, _ang, _b = adj[v][0]
            del adj[v]
            adj[w] = [t for t in adj[w] if t[1] != v]
            changed = True

    # 往返副本签名（同 ``_enum_faces``）
    sig: dict[int, tuple] = {}
    for eid, e in enumerate(edges):
        if e.t == "A" and e.r > 0:
            a1, a2 = round(math.degrees(e.sa), 1), round(math.degrees(e.ea), 1)
            sig[eid] = ("A", round(e.cx, 2), round(e.cy, 2), round(e.r, 2),
                        min(a1, a2), max(a1, a2))
        else:
            x1, y1 = vpos[e.vs]
            x2, y2 = vpos[e.ve]
            sig[eid] = ("L", round(min(x1, x2), 2), round(min(y1, y2), 2),
                        round(max(x1, x2), 2), round(max(y1, y2), 2))

    def _is_micro_edge(eid: int) -> bool:
        e = edges[eid]
        if not _is_microg(*vpos[e.vs], *vpos[e.ve]):
            return False
        return micro_len.get(eid, 0.0) < MICRO_CHAIN_MIN

    def _key(c, twin_ang: float, twin_bend: int):
        """候选离「twin 顺时针方向」的距离键（带曲率扰动）。

        δ = (twin_eff − eff) mod TAU，eff = ang + bend·ε：
        b + bend < 0 ⇒ 紧贴 twin 顺时针侧（最小）；= 0 ⇒ 完全重合的
        折返（退化，不可选）；> 0 ⇒ 逆时针侧（排在所有普通候选后）。
        """
        ang, bend = c[2], c[3]
        raw = (twin_ang - ang) % TAU
        s = twin_bend - bend
        if raw < ang_eps:
            if s == 0:
                return None
            return (0, s) if s > 0 else (2, s)
        return (1, round(raw, 9), s)

    def _advance(cur, incoming, twin_bend, used, used_sigs):
        twin_ang = incoming + math.pi
        cands = []
        for eid, other, ang, bend in adj.get(cur, []):
            if eid in used or sig[eid] in used_sigs:
                continue
            cands.append((eid, other, ang, bend))
        if not cands:
            return None
        big = [c for c in cands if not _is_micro_edge(c[0])]
        if big:
            cands = big
        best = None
        for c in cands:
            k = _key(c, twin_ang, twin_bend)
            if k is None:
                continue
            if best is None or k < best[0]:
                best = (k, c)
        if best is None:
            return None
        return best[1]

    # 连通分量（同 ``_enum_faces``）
    seen: set[int] = set()
    comps: list[list[int]] = []
    for v in vpos:
        if v in seen or v not in adj:
            continue
        stack = [v]
        seen.add(v)
        vs: list[int] = []
        while stack:
            u = stack.pop()
            vs.append(u)
            for _eid, w, _ang, _b in adj.get(u, []):
                if w not in seen:
                    seen.add(w)
                    stack.append(w)
        comps.append(vs)

    def _signed(pts) -> float:
        a = 0.0
        n = len(pts)
        for i in range(n):
            x1, y1 = pts[i]
            x2, y2 = pts[(i + 1) % n]
            a += x1 * y2 - x2 * y1
        return a / 2.0

    faces = []
    seen_faces = set()
    for ci, vs in enumerate(comps):
        if len(vs) < 3:
            continue
        vset = set(vs)
        for v0 in vs:
            for eid0, w0, ang0, b0 in adj.get(v0, []):
                if w0 not in vset:
                    continue
                ring = [(eid0, v0, w0)]
                used = {eid0}
                used_sigs = {sig[eid0]}
                incoming = ang0
                twin_bend = -b0
                cur = w0
                closed = False
                for _ in range(8000):
                    step = _advance(cur, incoming, twin_bend, used, used_sigs)
                    if step is None:
                        break
                    eid, nxt, ang, bend = step
                    ring.append((eid, cur, nxt))
                    used.add(eid)
                    used_sigs.add(sig[eid])
                    incoming = _norm(ang + _sweep(edges[eid], cur, nxt, vpos))
                    twin_bend = -bend
                    cur = nxt
                    if cur == v0:
                        closed = True
                        break
                if not closed:
                    continue
                key = frozenset(e for e, _f, _t in ring)
                if key in seen_faces:
                    continue
                pts = [vpos[f] for _e, f, _t in ring]
                a = _signed(pts)
                if a <= 0.0:
                    continue
                vc: set[int] = set()
                dup = False
                for _e, f, _t in ring:
                    if f in vc:
                        dup = True
                        break
                    vc.add(f)
                if dup:
                    continue
                seen_faces.add(key)
                faces.append((a, ring, ci, len(vs)))
    return faces


def extract_faces(d: Drawing, v: View,
                  roles: set[str] | None = None,
                  min_area: float = AREA_FLOOR) -> list[FaceRing]:
    """提取视图的全部有界面（除主体块外的都是内环候选）。

    ``roles`` 缺省为 ``{visible, hidden}``：内腔边界在图纸上是隐藏线。
    返回按面积降序排列的 ``FaceRing``；剖视图不参与（剖面材料由
    ``conventions.section`` 负责）。
    """
    if v.is_section:
        return []
    if roles is None:
        roles = {"visible", "hidden"}
    edges, vpos = _profile_edges(d, v, roles=roles)
    if not edges:
        return []
    micro_len = _micro_chain_lengths(edges, vpos)
    # 两种遍历都跑：``_enum_faces`` 是旧管线的规范化左转，``_enum_faces_dcel``
    # 是 DCEL 标准顺时针后继——后者能走进前者在切向折返处走不进的腔体面
    # （IMU V1 角缺口）。同一几何面两边可能各枚举一次（绕向/起点不同），
    # 下面的 segs 键去重会合并。
    passes = [("raw", edges, vpos,
               _enum_faces(edges, vpos, micro_len)
               + _enum_faces_dcel(edges, vpos, micro_len))]
    # 顶点胶合兜底：PDF 矢量化图纸的端点常差 0.01~1.5mm，face 遍历对
    # 断口比外环更敏感（内腔边界整条由短碎段组成）。raw 结果**原样保留**，
    # 胶合结果按几何去重后追加——胶合若改变主体环，内环通道仍能工作。
    gv, ge = _glue(edges, vpos)
    passes.append(("glued", ge, gv,
                   _enum_faces(ge, gv, micro_len)
                   + _enum_faces_dcel(ge, gv, micro_len)))
    out: list[FaceRing] = []
    seen: set[tuple] = set()
    for rule, es, vp, faces in passes:
        for area, ring, _ci, _nv in faces:
            segs = []
            for eid, f, t in ring:
                e = es[eid]
                x1, y1 = vp[f]
                x2, y2 = vp[t]
                if e.t == "L":
                    segs.append(RingSeg("line", Point2(x1, y1), Point2(x2, y2)))
                else:
                    if f == e.sa_v:
                        sa, ea, ccw = e.sa, e.ea, True
                    else:
                        sa, ea, ccw = e.ea, e.sa, False
                    segs.append(RingSeg("arc", Point2(x1, y1), Point2(x2, y2),
                                        Point2(e.cx, e.cy), e.r, ccw, sa, ea))
            segs_t = tuple(segs)
            if _seg_signed_area(segs_t) < 0:
                segs_t = _reverse_segs(segs_t)
            key = tuple(sorted((round(s.p1.x, 3), round(s.p1.y, 3),
                                round(s.p2.x, 3), round(s.p2.y, 3),
                                s.kind, round(s.radius, 3))
                               for s in segs_t))
            if key in seen:
                continue
            geo_area = abs(Profile2(segs_t).signed_area())
            if geo_area < min_area:
                continue
            seen.add(key)
            bb = _geom_bbox(segs_t)
            cov = (1.0, 1.0)
            if v.bbox is not None and v.bbox.width > 0 and v.bbox.height > 0:
                cov = (bb.width / v.bbox.width, bb.height / v.bbox.height)
            n_h = sum(1 for eid, _f, _t in ring
                      if es[eid].role == "hidden")

            def _elen(eid, f, t) -> float:
                return math.hypot(vp[f][0] - vp[t][0], vp[f][1] - vp[t][1])

            hid_len = sum(_elen(eid, f, t) for eid, f, t in ring
                          if es[eid].role == "hidden")
            tot_len = sum(_elen(eid, f, t) for eid, f, t in ring)
            hf = hid_len / tot_len if tot_len > 0.0 else 0.0
            out.append(FaceRing(segs_t, geo_area, bb, cov,
                                len(ring), n_h, len(ring) - n_h, rule, hf))
    out.sort(key=lambda f: -f.area)
    return out


def extract_ring(d: Drawing, v: View) -> RingResult:
    """从视图 ``v`` 的轮廓证据提取外环。

    返回 ``RingResult``：``ring`` 为通过门控的结果（失败为 None +
    ``note`` 说明原因）；``raw``/``welded`` 为两遍诊断（可能为 None）。
    """
    if v.is_section:
        # 剖视图的包围边界是剖切轮廓，不是投影外轮廓——不参与本通道
        return RingResult(None, None, None, "section_view")
    edges, vpos = _profile_edges(d, v)
    if not edges:
        return RingResult(None, None, None, "no_profile_edges")
    micro_len = _micro_chain_lengths(edges, vpos)
    n_micro = len(micro_len)
    raw = _one_pass(edges, vpos, micro_len)
    welded = None
    welded_edges = None
    welded_vpos = None
    if micro_len:
        welded_vpos, welded_edges = _weld(edges, vpos)
        welded = _one_pass(welded_edges, welded_vpos, micro_len)
    has_lines = any(e.t == "L" for e in edges)

    def _mk(p, es, vp, rule):
        return _to_ring(p, es, vp, rule, v.bbox, len(edges), n_micro) \
            if p is not None else None

    r_raw = _mk(raw, edges, vpos, "raw")
    r_welded = _mk(welded, welded_edges, welded_vpos, "welded")
    if not has_lines:
        # 纯圆/纯弧视图：外轮廓 = 回转体截面，让位给 REVOLVE 通道。
        # 次序有意放在 pool 空判定之前——纯圆视图里每个圆是 2 顶点组件
        # （被 len<4 守卫跳过 ⇒ 候选池必为空），次序颠倒会让所有纯圆
        # 视图错报 no_ring_found（flange_d80 / 法兰练习 V0 实测）
        return RingResult(None, r_raw, r_welded, "circles_only_view")
    pool = [r for r in (r_raw, r_welded) if r is not None]
    chosen = max(pool, key=lambda r: r.area) if pool else None
    if chosen is not None:
        cw, ch = chosen.coverage
        if cw >= COVER_MIN and ch >= COVER_MIN:
            return RingResult(chosen, r_raw, r_welded, "")

    # 第三遍：顶点胶合兜底（见 ``_glue``）。只在 raw/welded 都没给出
    # 过门环时跑——已成功的视图结果逐位不变（v15 误焊教训的边界）。
    # 先试**有界胶合**（簇直径 ≤ GLUE_CLOSE，防微链传递塌缩），不过门
    # 再回落无界胶合（v0.6.44 语义，YZYX 等靠链式合并救环的靶子）。
    glued_vpos, glued_edges = _glue(edges, vpos, cap=GLUE_CLOSE)
    glued = _one_pass(glued_edges, glued_vpos, micro_len)
    r_glued = _mk(glued, glued_edges, glued_vpos, "glued")
    if r_glued is not None:
        gw, gh = r_glued.coverage
        if gw >= COVER_MIN and gh >= COVER_MIN:
            return RingResult(r_glued, r_raw, r_welded, "", r_glued)
    glued_vpos, glued_edges = _glue(edges, vpos)
    glued = _one_pass(glued_edges, glued_vpos, micro_len)
    r_glued2 = _mk(glued, glued_edges, glued_vpos, "glued")
    if r_glued2 is not None:
        gw, gh = r_glued2.coverage
        if gw >= COVER_MIN and gh >= COVER_MIN:
            return RingResult(r_glued2, r_raw, r_welded, "", r_glued2)
    if r_glued2 is not None and (r_glued is None or r_glued2.area > r_glued.area):
        r_glued = r_glued2

    if chosen is None:
        return RingResult(None, r_raw, r_welded, "no_ring_found", r_glued)
    cw, ch = chosen.coverage
    return RingResult(None, r_raw, r_welded,
                      f"coverage({cw:.2f}×{ch:.2f})<{COVER_MIN}", r_glued)


# ---------------------------------------------------------------------------
# 命令行冒烟 / 目视
# ---------------------------------------------------------------------------

def _main(argv: list[str]) -> int:
    from ..evidence import read_dxf
    from .view_detector import detect_views
    from .view_typer import type_views
    if not argv:
        print("用法: python -m src.rebuild.views.ring <图纸.dxf>")
        return 2
    d = read_dxf(argv[0])
    detect_views(d)
    # section 守卫依赖 is_section ⇔ 定性结果（type.is_settled）——
    # 冒烟必须与管线同序（分离→定性→提环），否则剖视图会当作
    # 普通视图参与提取（V3/V4/V5 实测会被提出"看似正常"的环）
    type_views(d)
    for v in d.views:
        r = extract_ring(d, v)
        tag = f"V{v.id}" if not str(v.id).startswith("V") else str(v.id)
        if r.ring is not None:
            ring = r.ring
            print(f"{tag:<4} {ring.n_edges:>3} 边  {ring.n_micro:>3} 微边  "
                  f"{ring.n_components:>2} 分量  {ring.rule}: "
                  f"面积 {ring.area:>12.4f} / {len(ring.segs)} 段  "
                  f"bbox {ring.bbox.width:.2f}×{ring.bbox.height:.2f}  "
                  f"coverage ({ring.coverage[0]:.2f},{ring.coverage[1]:.2f}) "
                  f"→ PASS(rule={ring.rule})")
        else:
            print(f"{tag:<4} → 无环（{r.note or 'unknown'}）")
    return 0


if __name__ == "__main__":
    import sys
    raise SystemExit(_main(sys.argv[1:]))
