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

__all__ = ["Ring", "RingResult", "RingSeg", "extract_ring"]

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
    rule: str                                  # "raw" | "welded"
    coverage: tuple[float, float]              # (环/视图) 宽、高覆盖比
    n_edges: int                               # 视图参与提取的轮廓边数
    n_micro: int                               # 其中微边条数
    n_components: int                          # 含边的连通分量数

    def to_profile(self) -> Profile2:
        """转为发射器契约（Profile2）。段类型同构，零拷贝。"""
        return Profile2(self.segs)


@dataclass(frozen=True)
class RingResult:
    """提取结果：``ring`` 为通过门控的环；``raw``/``welded`` 为两遍诊断。"""

    ring: Ring | None
    raw: Ring | None
    welded: Ring | None
    note: str = ""


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

def _profile_edges(d: Drawing, v: View):
    """视图轮廓类证据 → (edges: list[_E], vpos: dict[int, (x, y)])。"""
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

    edges: list[_E] = []

    def _line(x1, y1, x2, y2) -> None:
        vs, ve = _vid(x1, y1), _vid(x2, y2)
        if vs == ve:
            return                                # 吸附后退化，静默丢弃
        edges.append(_E("L", vs, ve))

    def _arc(cx, cy, r, sa, ea) -> None:
        span = (ea - sa) % TAU
        if span < 1e-9:
            span = TAU                            # 整圆（|ea-sa| = 2π）
        if span > TAU - 1e-3:                     # 整圆拆两半（端点须相异）
            mid = sa + math.pi
            _arc(cx, cy, r, sa, mid)
            _arc(cx, cy, r, mid, sa + TAU)
            return
        x1, y1 = cx + r * math.cos(sa), cy + r * math.sin(sa)
        x2, y2 = cx + r * math.cos(ea), cy + r * math.sin(ea)
        vs, ve = _vid(x1, y1), _vid(x2, y2)
        if vs == ve:
            return
        edges.append(_E("A", vs, ve, cx, cy, r, sa, ea, vs, ve))

    for h in v.evidence:
        ev = by_h.get(h)
        if ev is None or ev.role.value not in _PROFILE_ROLES:
            continue
        g = ev.geom
        if isinstance(g, Line2):
            _line(g.start.x, g.start.y, g.end.x, g.end.y)
        elif isinstance(g, Arc2):
            _arc(g.center.x, g.center.y, g.radius, g.start_angle, g.end_angle)
        elif isinstance(g, Circle2):
            _arc(g.center.x, g.center.y, g.radius, 0.0, TAU)
        elif isinstance(g, Polyline2):
            pts = g.points
            for p, q in zip(pts, pts[1:]):
                _line(p.x, p.y, q.x, q.y)

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

    rep_pos: dict[int, tuple[float, float]] = {}
    for vid, x, y, _vm in ep:
        rep_pos.setdefault(_f(vid), (x, y))
    vpos2 = {v: rep_pos.get(_f(v), p) for v, p in vpos.items()}
    edges2 = [replace(e, vs=_f(e.vs), ve=_f(e.ve),
                      sa_v=_f(e.sa_v), ea_v=_f(e.ea_v)) for e in edges]
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
        rw = p.vbox[2] - p.vbox[0]
        rh = p.vbox[3] - p.vbox[1]
        if vw > 0 and vh > 0:
            cov = (rw / vw, rh / vh)
    return Ring(segs_t, p.area, _geom_bbox(segs_t), rule, cov,
                n_edges, n_micro, p.n_comp)


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
    if not pool:
        return RingResult(None, r_raw, r_welded, "no_ring_found")
    chosen = max(pool, key=lambda r: r.area)
    cw, ch = chosen.coverage
    if cw < COVER_MIN or ch < COVER_MIN:
        return RingResult(None, r_raw, r_welded,
                          f"coverage({cw:.2f}×{ch:.2f})<{COVER_MIN}")
    return RingResult(chosen, r_raw, r_welded, "")


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
