# -*- coding: utf-8 -*-
"""外表面开口 —— 可见开口面 × 孔提示 ⇒ 沿开口轴的 POCKET（异形孔/槽）。

## 为什么要有这条通道

``cylinder_features`` 把每个圆读成**圆柱**（孔/凸台）。但图纸上有的开口
不是圆孔：轮廓是「两个圆 + 直壁」的 stadium、或「圆 + 长颈 + 圆头」的
钥匙孔。这些开口的圆边照样进了 ``CylinderHint``（每个圆一条），于是
管道只按单圆切圆柱——腰部/颈部整块留着（实测 D79307：顶部 stadium 槽
两圆各切 Ø7，腰部 22.08 没切；贯通钥匙孔只按近壁那一个圆的 2.1mm 切，
多料 599.55）。

这类开口在**圆所在的视图**里有一个完整的**可见面**（``extract_faces``
的有界面）：边界上既有孔提示的圆边，又有**不属于该圆**的其它段
（直壁、另一个圆）。普通圆孔的盘面只有它自己的圆——一条"其它段"都
没有，故被下面的判据挡掉，留给圆柱通道。

## 判据（全部来自图纸，不按零件名/坐标写死）

1. **可见面**：面积 ≥ ``MIN_AREA``、小于主体块（``OUTER_AREA_FRAC``）。
   开口足迹是外表面上的可见轮廓；隐藏面是内腔（``inner_profiles`` 的
   地盘）。
2. **边界含孔提示的圆弧**（半径/圆心匹配 ``CylinderHint``、``solid``
   = False）：这条面必须由某个"孔"锚住，否则只是普通台阶面。
3. **边界含非本圆的其它段**：否则是普通孔口盘面（圆柱通道负责）。
4. **轴向范围**：由命中提示的**全部轮廓对区间**（``CylinderHint.spans``）
   读——
   - 区间并集**贴住基体材料区间的两端**（``THROUGH_TOL``）⇒ 贯通，
     切基体全长；
   - 否则所有区间**一致**（``SPAN_AGREE_TOL``）⇒ 按该区间切（盲槽）；
   - 否则（多个互不一致的区间，又都不贯通）⇒ **不建**（原则二：读不齐
     不替图纸拍板）。

## 轮廓修复（为什么需要）

第三遍胶合（``views.ring._glue``）把 0.5mm 内的顶点传递合并成簇，簇代表
位置与微链上各段真实位置可差数毫米——面上会出现**被拉长的直线段**
（D79307 钥匙孔：两条对角捷径顶掉了颈部 + 圆头，面积 106.96 vs 真值
≈159.4）。判据：长于 ``REPAIR_MIN`` 的直线段，若两端都找不到同端点的
原始 LINE 支撑，就在**原始图元边图**上求两端最短路径替换它。路径完全
由图纸上真实画出的线段/弧组成；求不到路径或路径绕远（``PATH_RATIO``）
就原样保留——修复是可选的增强，不做猜测。

## 消费关系

命中的提示从 ``cylinder_features`` 的 ``skip`` 里排除：它们的几何已被
这条 POCKET 覆盖，再切一遍是重复（SW 的切除不幂等，重复切会整单失败）。
"""
from __future__ import annotations

import heapq
import math
from collections import defaultdict
from dataclasses import replace

from ..evidence.model import Arc2, Kind, Line2
from ..model.claim import Claim, Tier
from ..model.feature_tree import Feature, FeatureType
from ..model.geom import Axis3, Point3, Vector3
from ..model.geom2d import BBox2, Point2, Profile2, ProfileSeg2
from ..model.ids import FeatureId
from ..views.correspondence import CorrespondenceResult, ViewFrame
from ..views.ring import FaceRing, extract_faces, extract_ring
from .inner_profiles import _PLANE_AXES, _map_face, _to_view

#: 候选面最小面积（mm²）
MIN_AREA = 5.0
#: 候选面面积上限（相对外环面积）：主体块不是开口足迹
OUTER_AREA_FRAC = 0.9
#: 隐藏段**长度**占比上限：开口足迹是外表面上的可见轮廓；隐藏主导的面
#: 是内腔，归 ``inner_profiles``（两者互斥，见两个模块的判据表）
VISIBLE_FRAC = 0.5
#: 圆柱提示匹配容差（半径 / 圆心）——与 inner_profiles 同口径
HINT_R_TOL = 0.1
HINT_C_TOL = 0.5
#: 只有长于此的"无原始图元支撑"的直线段才修复
REPAIR_MIN = 2.0
#: 线段端点与原始 LINE 的匹配容差（mm）
SUPPORT_TOL = 0.05
#: 修复路径端点吸附到原始图元节点的容差（mm）
PATH_SNAP = 0.05
#: 修复路径长度 / 两端直距 的上限（钥匙孔实测 ≈8.8——直壁下行 + 圆头 +
#: 直壁上行，路径只能沿图上的真实边界走，绕远即说明接错了两端）
PATH_RATIO = 20.0
#: "贴着基体材料区间两端"的容差
THROUGH_TOL = 0.5
#: 多段 span 的"一致"容差
SPAN_AGREE_TOL = 0.1
#: 原始图节点取整精度
NODE_TOL = 1e-3


def opening_pockets(d, corr: CorrespondenceResult, base: Feature,
                    rep) -> tuple[list[Feature], set[int]]:
    """可见开口面 → POCKET 特征。返回 (特征列表, 被消费的提示 id 集合)。

    被消费的提示由调用方并入 ``cylinder_features`` 的 ``skip``（见模块
    文档"消费关系"）。
    """
    out: list[Feature] = []
    consumed: set[int] = set()
    params = base.params
    if base.type.value != FeatureType.BASE.value:
        return out, consumed
    if "dir" not in params or "profile" not in params:
        return out, consumed
    if "taper_scale" in params:
        return out, consumed           # 锥化基体：柱状假设不成立
    idx = {e.handle: e for e in d.evidence}
    #: 每个"孔"提示 + 它的圆所在视图（corr 的第一条 ref 就是圆边）
    hints: list[tuple[str, object, object]] = []
    for c in corr.cylinders():
        h = c.mapping.value
        if h.solid is not False or not c.views:
            continue
        hints.append((c.views[0], h, c))
    if not hints:
        return out, consumed

    for v in d.views:
        if v.is_section:
            continue
        fr = corr.frames.get(v.id)
        if fr is None:
            continue
        vh = [(h, c) for vid, h, c in hints if vid == v.id]
        if not vh:
            continue
        outer = extract_ring(d, v).ring
        outer_area = outer.area if outer is not None else 0.0
        seen: set[tuple] = set()
        for f in extract_faces(d, v, roles={"visible", "hidden"}):
            if f.area < MIN_AREA:
                continue
            if outer_area > 0.0 and f.area > OUTER_AREA_FRAC * outer_area:
                continue               # 主体块
            if f.hidden_frac >= VISIBLE_FRAC:
                continue               # 隐藏主导：内腔，inner_profiles 的地盘
            key = (round(f.area, 1), round(f.bbox.xmin * 2),
                   round(f.bbox.xmax * 2), round(f.bbox.ymin * 2),
                   round(f.bbox.ymax * 2))
            if key in seen:
                continue
            seen.add(key)
            matched = _matched_hints(fr, f, vh)
            if not matched:
                continue
            circs = [_hint_circle(fr, h) for h, _ in matched]
            if all(_on_hint_circle(s, circs) for s in f.segs):
                continue               # 普通孔口盘面 —— 圆柱通道负责
            axis = _axis_name(matched[0][0].axis.direction)
            if axis is None or any(_axis_name(h.axis.direction) != axis
                                   for h, _ in matched):
                continue
            spans = _hints_spans(matched)
            sel = _opening_span(spans, _base_range(base, axis))
            if sel is None:
                rep.notes.append(
                    f"开口：{v.id} 的可见面（面积 {f.area:.2f}，含 "
                    f"{len(matched)} 条孔提示圆边）沿 {axis} 的区间读不齐"
                    f"（{_fmt_spans(spans)}）⇒ 不建")
                continue
            segs = _repair_face(idx, v, f.segs)
            b1, b2 = _PLANE_AXES[axis]
            prof = _map_face(fr, segs, b1, b2)
            if prof is None:
                rep.notes.append(
                    f"开口：{v.id} 的可见面映射到 {b1}-{b2} 轮廓平面失败 ⇒ 不建")
                continue
            lo, hi = sel
            ev = tuple(dict.fromkeys(
                h for hh, _ in matched for h in hh.evidence))
            out.append(_make_opening(v, f, prof, lo, hi, axis, ev))
            consumed |= {id(h) for h, _ in matched}
    if out:
        rep.notes.append(
            f"开口：{len(out)} 个含孔圆的可见面建成 POCKET"
            f"（判据 可见面 + 孔提示弧 + 非本圆段；轴向按提示轮廓对："
            f"两端贴基体=贯通，一致=盲槽，否则不建）")
    return out, consumed


# ---------------------------------------------------------------------------
# 面 ↔ 提示
# ---------------------------------------------------------------------------

def _hint_circle(fr: ViewFrame, h) -> tuple[float, float, float]:
    """提示在本视图系里的 (半径, 圆心u, 圆心v)（同 inner_profiles 口径）。"""
    o = h.axis.origin
    m = {fr.u_axis: getattr(o, fr.u_axis),
         fr.v_axis: getattr(o, fr.v_axis)}
    u = _to_view(m[fr.u_axis], fr.u_off, fr.u_flip, fr.u_span)
    v = _to_view(m[fr.v_axis], fr.v_off, fr.v_flip, fr.v_span)
    return h.radius, u, v


def _matched_hints(fr: ViewFrame, f: FaceRing, vh) -> list[tuple]:
    circs = [_hint_circle(fr, h) for h, _ in vh]
    out = []
    for (h, c), (r, cu, cv) in zip(vh, circs):
        for s in f.segs:
            if s.kind != "arc" or s.center is None or s.radius <= 0:
                continue
            if abs(s.radius - r) > HINT_R_TOL:
                continue
            if math.hypot(s.center.x - cu, s.center.y - cv) <= HINT_C_TOL:
                out.append((h, c))
                break
    return out


def _on_hint_circle(s: ProfileSeg2, circs) -> bool:
    """段是否"属于"某个命中提示的圆（弧在圆上；直线两端都在圆上）。"""
    for r, cu, cv in circs:
        if s.kind == "arc" and s.center is not None and s.radius > 0:
            if (abs(s.radius - r) <= HINT_R_TOL
                    and math.hypot(s.center.x - cu, s.center.y - cv)
                    <= HINT_C_TOL):
                return True
        else:
            d1 = math.hypot(s.p1.x - cu, s.p1.y - cv)
            d2 = math.hypot(s.p2.x - cu, s.p2.y - cv)
            if abs(d1 - r) <= HINT_R_TOL and abs(d2 - r) <= HINT_R_TOL:
                return True
    return False


def _axis_name(dv: Vector3) -> str | None:
    comps = {"x": abs(dv.x), "y": abs(dv.y), "z": abs(dv.z)}
    name = max(comps, key=comps.get)
    return name if comps[name] > 0.99 else None


def _hints_spans(matched) -> list[tuple[float, float]]:
    out: list[tuple[float, float]] = []
    for h, _ in matched:
        if h.spans:
            out.extend(h.spans)
        elif h.span is not None:
            out.append(h.span)
    return out


def _fmt_spans(spans) -> str:
    if not spans:
        return "无轮廓对"
    return "、".join(f"{a:.2f}..{b:.2f}" for a, b in spans)


# ---------------------------------------------------------------------------
# 轴向范围
# ---------------------------------------------------------------------------

def _base_range(base: Feature, axis: str) -> tuple[float, float] | None:
    """基体材料在模型轴 ``axis`` 上的区间（绝对坐标）。

    基体 profile 是**相对 origin** 的局部 (a, b)（发射器按
    ``ir_point(origin, dir, a, b, t)`` 落位），a/b 分别对应
    ``_PLANE_AXES[dir]`` 的两轴且带正号——故绝对区间 = origin 分量 + 局部范围。
    """
    params = base.params
    prof = params["profile"].value
    origin = params["origin"].value if "origin" in params else Point3(0, 0, 0)
    dir_name = params["dir"].value
    b1, b2 = _PLANE_AXES[dir_name]
    if isinstance(prof, Profile2):
        bb = prof.bbox()
    else:
        xs = [float(p[0]) for p in prof]
        ys = [float(p[1]) for p in prof]
        bb = BBox2(min(xs), min(ys), max(xs), max(ys))
    if axis == b1:
        lo, hi = bb.xmin, bb.xmax
    elif axis == b2:
        lo, hi = bb.ymin, bb.ymax
    elif axis == dir_name:
        t = getattr(origin, dir_name)
        if "length" not in params:
            return None
        return (t, t + float(params["length"].value))
    else:
        return None
    o = getattr(origin, axis)
    return (o + lo, o + hi)


def _opening_span(spans: list[tuple[float, float]],
                  base_rng: tuple[float, float] | None
                  ) -> tuple[float, float] | None:
    """开口沿轴的范围：贯通 ⇒ 基体全长；一致 ⇒ 并集；否则不建。"""
    if not spans:
        return None
    lo = min(s[0] for s in spans)
    hi = max(s[1] for s in spans)
    if base_rng is not None:
        b_lo, b_hi = base_rng
        if lo <= b_lo + THROUGH_TOL and hi >= b_hi - THROUGH_TOL:
            return (b_lo, b_hi)
    if all(abs(a[0] - spans[0][0]) <= SPAN_AGREE_TOL
           and abs(a[1] - spans[0][1]) <= SPAN_AGREE_TOL for a in spans):
        return (lo, hi)
    return None


# ---------------------------------------------------------------------------
# 轮廓修复（胶合拉长边 → 原始图元路径）
# ---------------------------------------------------------------------------

def _repair_face(idx, view, segs: tuple[ProfileSeg2, ...]
                 ) -> tuple[ProfileSeg2, ...]:
    """把面上"无原始图元支撑"的长直线段替换为原始边图上的最短路径。"""
    lines = _raw_lines(idx, view)
    if not lines:
        return segs
    nodes, adj = _raw_graph(idx, view)
    if not adj:
        return segs
    cur = tuple(segs)
    for _ in range(4):                 # 一圈面通常只有一处捷径；设上界防环
        bad = [s.kind == "line" and _seg_len(s) >= REPAIR_MIN
               and not _supported(s, lines) for s in cur]
        runs = _runs_cyclic(bad)
        if not runs:
            break
        # 一次修最长的那一段（按坏段总长）
        runs.sort(key=lambda r: -sum(_seg_len(cur[i]) for i in r))
        run = runs[0]
        n = len(cur)
        p = (run[0] - 1) % n
        q = (run[-1] + 1) % n
        start_pt, end_pt = cur[p].p2, cur[q].p1
        src = _snap_nodes(nodes, start_pt)
        dst = _snap_nodes(nodes, end_pt)
        if not src or not dst:
            break
        steps = _dijkstra(adj, src, dst)
        if not steps:
            break
        path = _path_segs(steps, idx)
        if not path:
            break
        plen = sum(_seg_len(s) for s in path)
        direct = math.hypot(end_pt.x - start_pt.x, end_pt.y - start_pt.y)
        if direct > 1e-9 and plen > PATH_RATIO * direct:
            break                      # 绕远：接错了两端
        # 端点焊接：首/末段是直线就把它自己的端点挪到面端点；是弧则把
        # **邻段**端点挪到原始节点（弧端点必须留在圆上，交给 _snap_arc_ends）
        pre, post = cur[p], cur[q]
        if path[0].kind == "line":
            path[0] = replace(path[0], p1=start_pt)
        else:
            pre = replace(pre, p2=path[0].p1)
        if path[-1].kind == "line":
            path[-1] = replace(path[-1], p2=end_pt)
        else:
            post = replace(post, p1=path[-1].p2)
        # 旋转到 run 起点：rot = [坏段..., 后继, ..., 前驱]（前驱恒在末尾）。
        # 新环 = 前驱 → 路径 → 后继 → 其余 →（回到前驱），故末尾那个前驱
        # 不能再出现一次（否则边界段被复制、链在复制点断开）。
        rot = [cur[(run[0] + t) % n] for t in range(n)]
        m = len(run)
        cur = tuple([pre] + path + [post] + rot[m + 1:-1])
    return cur


def _seg_len(s: ProfileSeg2) -> float:
    return math.hypot(s.p2.x - s.p1.x, s.p2.y - s.p1.y)


def _raw_lines(idx, view) -> list[tuple[Point2, Point2]]:
    out = []
    for h in view.evidence:
        e = idx.get(h)
        if e is None or e.kind != Kind.EDGE or not isinstance(e.geom, Line2):
            continue
        if e.role.value not in ("visible", "hidden"):
            continue
        g = e.geom
        out.append((Point2(g.start.x, g.start.y), Point2(g.end.x, g.end.y)))
    return out


def _supported(s: ProfileSeg2, lines) -> bool:
    """该直线段是否有同端点的原始 LINE 支撑（双向都算）。"""
    for a, b in lines:
        if ((_near(s.p1, a) and _near(s.p2, b))
                or (_near(s.p1, b) and _near(s.p2, a))):
            return True
    return False


def _near(p: Point2, q: Point2) -> bool:
    return abs(p.x - q.x) <= SUPPORT_TOL and abs(p.y - q.y) <= SUPPORT_TOL


def _runs_cyclic(bad: list[bool]) -> list[list[int]]:
    n = len(bad)
    if n == 0 or all(bad):
        return []
    k0 = next(i for i, b in enumerate(bad) if not b)
    runs: list[list[int]] = []
    cur: list[int] = []
    for t in range(1, n):
        i = (k0 + t) % n
        if bad[i]:
            cur.append(i)
        elif cur:
            runs.append(cur)
            cur = []
    if cur:
        runs.append(cur)
    return runs


def _node_key(x: float, y: float) -> tuple[float, float]:
    return (round(x / NODE_TOL) * NODE_TOL, round(y / NODE_TOL) * NODE_TOL)


def _raw_graph(idx, view):
    """原始图元边图：节点 = 线段/弧端点（1e-3 取整），边权 = 弦长。"""
    adj: dict[tuple, list] = defaultdict(list)
    for h in view.evidence:
        e = idx.get(h)
        if e is None or e.kind != Kind.EDGE:
            continue
        if e.role.value not in ("visible", "hidden"):
            continue
        g = e.geom
        if isinstance(g, Line2):
            a = _node_key(g.start.x, g.start.y)
            b = _node_key(g.end.x, g.end.y)
            w = math.hypot(g.end.x - g.start.x, g.end.y - g.start.y)
        elif isinstance(g, Arc2) and not g.is_full_circle:
            a0 = g.start_angle
            a1 = g.end_angle
            p0 = (g.center.x + g.radius * math.cos(a0),
                  g.center.y + g.radius * math.sin(a0))
            p1 = (g.center.x + g.radius * math.cos(a1),
                  g.center.y + g.radius * math.sin(a1))
            a = _node_key(*p0)
            b = _node_key(*p1)
            w = math.hypot(p1[0] - p0[0], p1[1] - p0[1])
        else:
            continue
        if a == b:
            continue
        adj[a].append((b, w, h))
        adj[b].append((a, w, h))
    return adj.keys(), adj


def _snap_nodes(nodes, p: Point2) -> list[tuple[float, float]]:
    """``p`` 附近 ``PATH_SNAP`` 内的**全部**原始节点。

    收全部而不是最近一个：图纸上同一点常被画成两个相距几 µm 的顶点
    （墙线端点与弧端点各一个、互不相连——D79307 钥匙孔实测 3µm），胶合
    把它们并进同一簇，而原始图里只有其中一个接着我们要走的路。多源
    最短路从这组节点同时出发，能走的那条自然会赢。
    """
    near = [n for n in nodes
            if math.hypot(n[0] - p.x, n[1] - p.y) <= PATH_SNAP]
    if near:
        return near
    best, bd = None, 2.0 * PATH_SNAP
    for node in nodes:
        dd = math.hypot(node[0] - p.x, node[1] - p.y)
        if dd < bd:
            bd, best = dd, node
    return [best] if best is not None else []


def _dijkstra(adj, sources, targets):
    """多源最短路径 → [(u, v, handle), ...]（按遍历序）；不可达返回 None。"""
    src = set(sources)
    dst = set(targets)
    if src & dst:
        return []
    inf = float("inf")
    dist = {s: 0.0 for s in src}
    prev: dict = {}
    pq = [(0.0, s) for s in src]
    heapq.heapify(pq)
    hit = None
    while pq:
        du, u = heapq.heappop(pq)
        if u in dst:
            hit = u
            break
        if du > dist.get(u, inf):
            continue
        for v, w, h in adj.get(u, ()):
            nd = du + max(w, 1e-6)
            if nd < dist.get(v, inf):
                dist[v] = nd
                prev[v] = (u, h)
                heapq.heappush(pq, (nd, v))
    if hit is None:
        return None
    out = []
    cur = hit
    while cur not in src:
        u, h = prev[cur]
        out.append((u, cur, h))
        cur = u
    out.reverse()
    return out


def _path_segs(steps, idx) -> list[ProfileSeg2]:
    out: list[ProfileSeg2] = []
    for u, v, h in steps:
        e = idx.get(h)
        if e is None:
            return []
        g = e.geom
        if isinstance(g, Line2):
            p0 = Point2(g.start.x, g.start.y)
            p1 = Point2(g.end.x, g.end.y)
            if _closer(p0, u, v):
                out.append(ProfileSeg2("line", p0, p1))
            else:
                out.append(ProfileSeg2("line", p1, p0))
        elif isinstance(g, Arc2) and not g.is_full_circle:
            a0, a1 = g.start_angle, g.end_angle
            p0 = Point2(g.center.x + g.radius * math.cos(a0),
                        g.center.y + g.radius * math.sin(a0))
            p1 = Point2(g.center.x + g.radius * math.cos(a1),
                        g.center.y + g.radius * math.sin(a1))
            c = Point2(g.center.x, g.center.y)
            if _closer(p0, u, v):
                out.append(ProfileSeg2("arc", p0, p1, c, g.radius, True,
                                       a0, a1))
            else:
                out.append(ProfileSeg2("arc", p1, p0, c, g.radius, False,
                                       a1, a0))
        else:
            return []
    return out


def _closer(p: Point2, u, v) -> bool:
    du = math.hypot(p.x - u[0], p.y - u[1])
    dv = math.hypot(p.x - v[0], p.y - v[1])
    return du <= dv


# ---------------------------------------------------------------------------
# 特征
# ---------------------------------------------------------------------------

def _dir_vec(name: str) -> Vector3:
    return {"x": Vector3(1.0, 0.0, 0.0),
            "y": Vector3(0.0, 1.0, 0.0),
            "z": Vector3(0.0, 0.0, 1.0)}[name]


def _make_opening(view, face: FaceRing, prof: Profile2,
                  lo: float, hi: float, axis: str,
                  ev: tuple[str, ...]) -> Feature:
    meth = "projection:opening_face"
    o = Point3(0.0, 0.0, 0.0)
    return Feature(
        id=FeatureId(-1),
        type=Claim(FeatureType.POCKET, meth, Tier.PROJECTION, ev),
        params={
            "profile": Claim(prof, meth, Tier.PROJECTION, ev),
            "depth": Claim(hi - lo, f"{meth}_span", Tier.PROJECTION, ev),
            # POCKET 契约：axial_at = **腔底**，自底向上挖 depth
            "axial_at": Claim(lo, f"{meth}_span", Tier.PROJECTION, ev),
        },
        axis=Claim(Axis3(o, _dir_vec(axis), None), meth,
                   Tier.PROJECTION, ev),
        placement=Claim(o, meth, Tier.PROJECTION, ev),
        source_view=view.id, evidence=list(ev),
    )
