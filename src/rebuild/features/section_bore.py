# -*- coding: utf-8 -*-
"""剖面材料通道 —— 剖面视图的 HATCH 空腔 ⇒ 沿轴阶梯孔 / 交叉孔 / 直通道。

## 为什么要有这条通道

`cylinder_features` 的入口是**圆柱提示**（正交视图里的圆）。沿视线方向的孔
才在正视图里成圆；**只有剖切面穿过零件内部才看得见**的孔，在任何正交视图里
都不出现圆 —— 实测 20180425 气缸前盖的 A—A 剖视：中心阶梯孔
（Ø36H7 − Ø42 环槽 − Ø36 − Ø40 环槽 − Ø36）、顶部 Ø10.7 螺纹底孔、
底部 Ø7 通道（接一段 Ø7 横孔）、z=148.68 的 Ø7 横孔、
孔壁向上钻的 Ø7 盲腔，`cylinder_features` 一条也看不见（它只看轮廓对/圆）。
`_rebut_by_section` 只能把"已读成凸台的圆"改判成孔，读不出没有圆的结构。

剖面图的地面真值在 HATCH：**打了剖面线的地方是材料，没打的是空腔**
（`features/material.material_map`）。沿剖面内的两个轴扫掠，空腔在垂直方向
上的恒定区间就是孔的截面。

## 判据（全部来自图纸，不按零件名/坐标写死）

沿轴 `a` 扫掠（a ∈ {视图 u, 视图 v}），对每个 t 求垂直轴 `p` 上的空腔区间
`[center−half, center+half]`，把 center/half 相近的沿 t 串成段，再逐段判：

1. **沿轴恒定**：段内 center/half 的极差 ≤ `BUCK_TOL`（锥口/台阶不是直孔）；
2. **两侧是材料**：段边界外 `WALL_PROBE` 处的材料率 ≥ `WALL_FRAC`
   （零件外的空气带在剖面里也是一段恒定区间 —— 实测左面 1mm 台阶外的
   空气给出一条 92.5 长的"通道"，只有这条判据能排除它）；
3. **不是整幅**：`half < MAX_HALF_FRAC ×` 垂直跨度（主体块不是孔）；
4. **圆柱性证据**（没有就只记账、不建，§3 原则二）：
   - `2·half` 与该视图一条尺寸标注值吻合（`DIM_TOL`）—— 图上写了 Ø36/Ø42/
     Ø40/Ø10.7/Ø7，这是"圆"而不是"矩形槽"的直接证据（几何上还要求标注的
     两点垂直段轴、中点落在段轴上，光数值相等不算 —— 见 `_dims_geom`）；
   - 或与**已确认**的段**同轴**（`AXIS_TOL`）—— 无标注的台阶段与有标注段
     共轴；同轴链一轮轮扩散直到不动；
5. **段长** ≥ `MIN_SEG`。

## 轴向定位

段的轴线在**剖切面法向**上的坐标 = 剖切线位置，**不能猜**：从其它视图里找
平行于切平面的**点画线**（剖切线是制图标准里的点画线，实测 A—A 的剖切线
3D47 在 x=291.976，恰好是零件中心平面）。唯一候选才采用；零/多候选 ⇒
整个剖面放弃（记账）。

## 发射与取代

每段一条 HOLE：`axial_at = lo`（图纸系读数）、`depth = hi − lo`、
`radius = half`、轴沿剖面内该轴、轴线位置如上。同一轴线上的旧 HOLE
（`cylinder_features` 按轮廓对猜的，如 #8 r19 通孔 / #9 r18 通孔）由
`replace_coaxial` 摘掉 —— 剖面材料是直接证据，压过投影猜测；带
`annotation:` 方法的（孔标注绑定）不动。
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from ..evidence.model import Role, ViewType
from ..model.claim import Claim, Tier
from ..model.feature_tree import Feature, FeatureType
from ..model.geom import Axis3, Point3, Vector3
from ..model.geom2d import Arc2, Line2, Point2
from ..model.ids import FeatureId
from .material import material_map

#: 栅格步长（mm）。A—A 33×115 ⇒ 111×385 点；实测每剖面 2~4 s（纯 Python 点判定）
GRID = 0.3
#: 最小半宽（更小的空腔是剖面线缝隙/刻线）
MIN_HALF = 0.6
#: 段最短长度。实测 A—A 最短的真段是 Ø36 的 1.5mm 台阶；
#: 零件**外**的空气带（左面台阶外 0.9 / 右面外 1.0）靠这条挡住
MIN_SEG = 1.2
#: center/half 聚类的桶容差（网格量化误差 ±GRID/2，留 1.5 倍余量）
BUCK_TOL = max(0.18, 1.5 * GRID)
#: 段内极差上限（相对桶容差）
SPREAD_TOL = 2.0 * BUCK_TOL
#: 材料探针步长与最远搜索距离
WALL_STEP = 0.15
WALL_SEARCH = 6.0
#: 材料率下限（**任一侧**满足即可 —— 真孔常与别的空腔相邻，或有一侧通到
#: 零件外：Ø10.7 通道经顶面出入、Ø7 横孔两端都在外表面上）。
#: 取 2/5 而非 4/5：Ø40 段的孔壁上，被 Ø7 横孔穿通的那 3 个采样点的外侧先是
#: 横腔、再往外是 1.1mm 薄壁岛（图上没 HATCH）⇒ 只有段两端两点能搜到材料；
#: 4/5 会把真段 Ø40 整个丢掉（实测）
WALL_FRAC = 0.4
#: 半宽上限（相对垂直方向跨度）—— 主体块/外部空气不是孔
MAX_HALF_FRAC = 0.35
#: 直径标注的**数值**匹配容差（栅格读出的直径有 ±GRID 量化误差；实测 Ø7
#: 读成 6.58/6.88、Ø10.7 读成 10.22）
DIM_TOL = 0.6
#: 标注中点偏离段轴的上限
DIM_CENTER_TOL = 0.5
#: 标注中点沿轴方向超出段跨度的上限
DIM_SPAN_TOL = 1.0
#: 同轴判定容差（轴线间距）
AXIS_TOL = 0.3
#: 断口填充：覆盖 run 与段区间的重叠比例下限
GAP_FILL = 0.5
#: 吸附到证据线的容差
SNAP_TOL = 0.6
#: 剖切线候选去重容差
CUT_TOL = 0.05

_DIRS = {"x": Vector3(1.0, 0.0, 0.0),
         "y": Vector3(0.0, 1.0, 0.0),
         "z": Vector3(0.0, 0.0, 1.0)}


@dataclass(frozen=True)
class _Cand:
    """一条候选圆柱段（视图系）。"""

    axis: str          # "u" / "v"：段沿哪条视图轴
    center: float      # 垂直轴上的中心（视图系）
    half: float        # 半宽
    lo: float          # 沿轴范围（视图系）
    hi: float
    proof: str = ""    # 圆柱性证据（"dim:42" / "coaxial:…"）
    tier: Tier = Tier.GUESS


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------

def section_bores(d, corr, conv, rep, mats: dict | None = None) -> list[Feature]:
    """剖面视图的 HATCH 空腔 ⇒ HOLE 特征（读不齐的候选只记账、不建）。"""
    if mats is None:
        mats = _section_materials(d, corr)
    out: list[Feature] = []
    for vid in sorted(mats):
        fr, mm, view = mats[vid]
        if view.bbox is None:
            continue
        cut = _cut_plane_pos(d, corr, view, fr)
        if cut is None:
            rep.notes.append(
                f"剖面孔：{vid} 的剖切面位置读不出（法向 {fr.p_axis} 上没有唯一"
                f"的剖切线）⇒ 该剖面的内部孔不建")
            continue
        p_axis, p_pos = cut
        us, vs, mat = _scan(fr, mm, view.bbox)
        cands = _candidates(us, vs, mat)
        keep = [c for c in cands
                if _wall_ok(fr, mm, c)
                and c.half < MAX_HALF_FRAC * _span_of(c.axis, us, vs)]
        picked = _prove(keep, _dims_geom(d, conv, view, fr), fr)
        if not picked:
            if keep:
                rep.notes.append(
                    f"剖面孔：{vid} 读出 {len(keep)} 段恒定空腔，但没有直径标注"
                    f"或同轴证据 ⇒ 不建（原则二）")
            continue
        for c in picked:
            out.append(_make_hole(d, view, fr, c, p_axis, p_pos))
        rep.notes.append(
            f"剖面孔：{vid} 从剖面线读出 {len(picked)} 段阶梯孔/通道"
            f"（恒定空腔 + 两侧材料 + 直径标注/同轴；剖切面 {p_axis}={p_pos:.3f}）")
    return out


def replace_coaxial(part, feats: list[Feature], rep) -> int:
    """摘掉与剖面段同轴的旧 HOLE —— 剖面材料压过投影猜测。

    只摘 ``type`` 为 HOLE 且方法**不是** ``annotation:`` 的（孔标注是图上
    明写，比剖面更强）；BOSS 不动。返回摘掉的条数。
    """
    if not feats:
        return 0
    keep: list[Feature] = []
    gone: list[Feature] = []
    for f in part.features:
        if (f.type.value == FeatureType.HOLE.value
                and not f.type.method.startswith("annotation:")
                and any(_collinear(f, nf) for nf in feats)):
            gone.append(f)
        else:
            keep.append(f)
    if gone:
        part.features[:] = keep
        rep.notes.append(
            "剖面孔：摘掉 " + "、".join(
                f"#{f.id}（{f.type.method}）" for f in gone)
            + " —— 与剖面读出的段同轴，由剖面取代")
    return len(gone)


# ---------------------------------------------------------------------------
# 剖切面位置
# ---------------------------------------------------------------------------

def _cut_plane_pos(d, corr, view, fr) -> tuple[str, float] | None:
    """剖面视图的切平面法向与位置。

    法向 = 视图帧的 ``p_axis``；位置从**其它**视图里读：剖切线是制图标准里
    的点画线（``Role.AXIS``），它在"含该法向轴的视图"里表现为一条**垂直于
    该轴**的直线（切平面边缘的投影）。唯一候选才采用。
    """
    p = fr.p_axis
    if p is None:
        return None
    by_h = {e.handle: e for e in d.evidence}
    cands: list[float] = []
    for w in d.views:
        wf = corr.frames.get(w.id)
        if wf is None or w.id == view.id or w.bbox is None:
            continue
        if p not in (wf.u_axis, wf.v_axis):
            continue
        for h in w.evidence:
            e = by_h.get(h)
            if e is None or e.role.value != Role.AXIS:
                continue
            g = e.geom
            if not isinstance(g, Line2):
                continue
            if wf.u_axis == p:
                if abs(g.start.x - g.end.x) > CUT_TOL:
                    continue
                pos = wf.u_to_model(g.start.x)
            else:
                if abs(g.start.y - g.end.y) > CUT_TOL:
                    continue
                pos = wf.v_to_model(g.start.y)
            cands.append(round(pos, 3))
    if not cands:
        return None
    uniq: list[float] = []
    for c in sorted(cands):
        if not uniq or abs(c - uniq[-1]) > CUT_TOL:
            uniq.append(c)
    if len(uniq) != 1:
        return None
    return p, uniq[0]


# ---------------------------------------------------------------------------
# 材料栅格与扫掠
# ---------------------------------------------------------------------------

def _section_materials(d, corr) -> dict:
    """剖视帧 → HATCH 材料判据（与 recognizer._section_materials 同判据）。"""
    out: dict = {}
    for fr in corr.frames.values():
        if fr.view_type != ViewType.SECTION:
            continue
        v = next((x for x in d.views if x.id == fr.view_id), None)
        if v is None or v.bbox is None:
            continue
        mm = material_map(d, fr, v.bbox)
        if getattr(mm, "has_hatch", False):
            out[fr.view_id] = (fr, mm, v)
    return out


def _scan(fr, mm, bbox):
    """视图系栅格材料图：(us, vs, mat[i][j])。"""
    nu = int(math.ceil((bbox.xmax - bbox.xmin) / GRID)) + 1
    nv = int(math.ceil((bbox.ymax - bbox.ymin) / GRID)) + 1
    nu, nv = max(nu, 2), max(nv, 2)
    us = [bbox.xmin + (bbox.xmax - bbox.xmin) * i / (nu - 1)
          for i in range(nu)]
    vs = [bbox.ymin + (bbox.ymax - bbox.ymin) * j / (nv - 1)
          for j in range(nv)]
    mat = [[mm(Point2(fr.u_to_model(u), fr.v_to_model(v))) for v in vs]
           for u in us]
    return us, vs, mat


def _runs(col) -> list[tuple[int, int]]:
    """布尔序列里连续 False（空腔）的区间索引。"""
    out: list[tuple[int, int]] = []
    n = len(col)
    j = 0
    while j < n:
        if not col[j]:
            k = j
            while k + 1 < n and not col[k + 1]:
                k += 1
            out.append((j, k))
            j = k + 1
        else:
            j += 1
    return out


def _span_of(axis: str, us, vs) -> float:
    return (us[-1] - us[0]) if axis == "v" else (vs[-1] - vs[0])


def _candidates(us, vs, mat) -> list[_Cand]:
    """沿两条轴扫掠 → 恒定空腔段。"""
    out: list[_Cand] = []
    for axis in ("u", "v"):
        if axis == "u":
            ts, ps = us, vs
            col_of = lambda i: [mat[i][j] for j in range(len(vs))]  # noqa: E731
        else:
            ts, ps = vs, us
            col_of = lambda j: [mat[i][j] for i in range(len(us))]  # noqa: E731
        per_t: list[list[tuple[float, float]]] = []
        for i in range(len(ts)):
            col = col_of(i)
            rr: list[tuple[float, float]] = []
            for a, b in _runs(col):
                p_lo, p_hi = ps[a], ps[b]
                if p_hi - p_lo < 2.0 * MIN_HALF:
                    continue
                rr.append(((p_lo + p_hi) / 2.0, (p_hi - p_lo) / 2.0))
            per_t.append(rr)
        # ---- 按 (center, half) 聚桶 ----
        buckets: list[dict] = []
        for i, rr in enumerate(per_t):
            for c, h in rr:
                for bk in buckets:
                    if (abs(bk["center"] - c) <= BUCK_TOL
                            and abs(bk["half"] - h) <= BUCK_TOL):
                        bk["pts"].append((i, c, h))
                        break
                else:
                    buckets.append({"center": c, "half": h,
                                    "pts": [(i, c, h)]})
        for bk in buckets:
            pts = sorted(bk["pts"])
            segs: list[list[tuple[int, float, float]]] = [[pts[0]]]
            for p in pts[1:]:
                gap = p[0] - segs[-1][-1][0]
                if gap <= 1:
                    segs[-1].append(p)
                elif _gap_covered(per_t, segs[-1][-1][0], p[0],
                                  bk["center"], bk["half"]):
                    segs[-1].append(p)      # 被更大的空腔横穿 —— 不是终止
                else:
                    segs.append([p])
            for sg in segs:
                i0, i1 = sg[0][0], sg[-1][0]
                lo = max(ts[i0] - GRID / 2.0, ts[0])
                hi = min(ts[i1] + GRID / 2.0, ts[-1])
                if hi - lo < MIN_SEG:
                    continue
                cs = [p[1] for p in sg]
                hs = [p[2] for p in sg]
                if (max(cs) - min(cs) > SPREAD_TOL
                        or max(hs) - min(hs) > SPREAD_TOL):
                    continue                # 锥口/过渡段：不是直孔
                out.append(_Cand(axis, sum(cs) / len(cs),
                                 sum(hs) / len(hs), lo, hi))
    return out


def _gap_covered(per_t, i0: int, i1: int, center: float,
                 half: float) -> bool:
    """断口 (i0, i1) 内的每个 t 都被**异轴**空腔横穿 ≥ GAP_FILL。

    两个条件缺一不可：

    - 覆盖 run 与段区间的重叠 ≥ ``GAP_FILL`` × 段宽（横穿得够宽才算真的
      "打断了这段"）；
    - 覆盖 run 的中心与段的中心**不同轴**（``AXIS_TOL`` 外）。同轴且更宽
      的 run 是**半径台阶**（bore 的 Ø36→Ø42 就是这种），它表示这一段到此
      为止，不是被别的东西横穿 —— 不加这条，Ø36 的桶会把整条 bore 连成一段
      （实测半宽 18.42、跨度 31.81，把 Ø42/Ø40/Ø48.78 全吞掉）。
    """
    w = 2.0 * half
    if w <= 0.0:
        return False
    for t in range(i0 + 1, i1):
        ok = False
        for c, h in per_t[t]:
            if abs(c - center) <= AXIS_TOL:
                continue                # 同轴更宽 ⇒ 台阶，不是横穿
            lo, hi = c - h, c + h
            ov = min(hi, center + half) - max(lo, center - half)
            if ov >= GAP_FILL * w:
                ok = True
                break
        if not ok:
            return False
    return True


def _wall_ok(fr, mm, c: _Cand) -> bool:
    """段边界往外**至少一侧**能找到材料（排除零件外的空气带）。

    沿垂直方向从段边界**向外**搜索 ``WALL_SEARCH``，找到材料即算这一侧成立。
    不要求在边界外 0.45 处立刻是材料，是因为真孔常与别的空腔贴邻：A—A 的
    Ø40 段在横孔跨度内的采样点外侧先穿过 Ø7 横腔，再往外是 1.1mm 薄壁岛
    （图上没打剖面线）——紧邻处一直是空的，材料在 4~5mm 外。
    只要求一侧，是因为孔也常有一侧通到零件外（Ø10.7 通道的顶部就在顶面上）。

    真正排除"零件外的空气带"的是这条 + ``MIN_SEG`` + ``MAX_HALF_FRAC`` 三条
    合起来：空气带要么贴着视图 bbox（两侧都搜不到材料），要么太短、太宽。
    """
    n = 5
    lo_side = hi_side = 0
    for k in range(n):
        t = c.lo + (c.hi - c.lo) * (k + 0.5) / n
        for sign, acc in ((-1.0, 0), (1.0, 1)):
            p = c.center + sign * (c.half + WALL_STEP)
            found = False
            while abs(p - c.center) <= c.half + WALL_SEARCH:
                u, v = (t, p) if c.axis == "u" else (p, t)
                if mm(Point2(fr.u_to_model(u), fr.v_to_model(v))):
                    found = True
                    break
                p += sign * WALL_STEP
            if found:
                if acc == 0:
                    lo_side += 1
                else:
                    hi_side += 1
    return max(lo_side, hi_side) >= WALL_FRAC * n


# ---------------------------------------------------------------------------
# 圆柱性证据
# ---------------------------------------------------------------------------

def _dims_geom(d, conv, view, fr) -> list[tuple[float, tuple[float, float],
                                                tuple[float, float]]]:
    """该视图的尺寸：``(值, 点1, 点2)``，点已换到模型系。

    点之所以要留着，是因为**光看数值会把半径标注当成直径**：A—A 的 15 条
    全是 linear（图上 Ø 以线性距离量出），其中「32」是顶上通道的深度、
    「15」是螺纹深、「17」是某条宽度 —— 只按数值配对会让"Ø32 的孔"
    （实测半宽 16.20 的伪段）凭空冒出来。几何关系（两点在**垂直于段轴**
    方向的间距 = 值、且中点落在段轴上）才是"这是一个直径"的证据。
    """
    if conv is None:
        return []
    from ..conventions.registry import ConvKind
    raw = {x.handle: x for x in d.dimensions}
    out: list[tuple[float, tuple[float, float], tuple[float, float]]] = []
    for c in conv.of_kind(ConvKind.DIMENSION):
        if c.view != view.id:
            continue
        dc = c.value
        if dc is None or dc.value is None:
            continue
        r = raw.get(dc.dim_ref)
        if r is None or r.p1 is None or r.p2 is None:
            continue
        out.append((float(dc.value),
                    (fr.u_to_model(r.p1.x), fr.v_to_model(r.p1.y)),
                    (fr.u_to_model(r.p2.x), fr.v_to_model(r.p2.y))))
    return out


def _dim_proof(c: _Cand, dims, fr) -> float | None:
    """段的直径标注（返回标注值；没有则 None）。

    判据（三条同时）：
    1. 两点在**垂直于段轴**方向的间距 ≈ 标注值（= 直径本身）；
    2. 标注值 ≈ 2 × 段半宽（段真的是这个直径）；
    3. 两点的中点落在**段轴**上（垂直方向，≤ ``DIM_CENTER_TOL``）、
       沿轴方向落在段的跨度内（≤ ``DIM_SPAN_TOL`` 外扩）。
    """
    if c.axis == "u":
        c_model = fr.v_to_model(c.center)
        lo, hi = sorted((fr.u_to_model(c.lo), fr.u_to_model(c.hi)))
    else:
        c_model = fr.u_to_model(c.center)
        lo, hi = sorted((fr.v_to_model(c.lo), fr.v_to_model(c.hi)))
    for val, p1, p2 in dims:
        a1, a2 = (p1[0], p2[0]) if c.axis == "u" else (p1[1], p2[1])
        q1, q2 = (p1[1], p2[1]) if c.axis == "u" else (p1[0], p2[0])
        if abs(abs(q2 - q1) - val) > DIM_TOL:
            continue
        if abs(val - 2.0 * c.half) > DIM_TOL:
            continue
        if abs((q1 + q2) / 2.0 - c_model) > DIM_CENTER_TOL:
            continue
        mid_a = (a1 + a2) / 2.0
        if not (lo - DIM_SPAN_TOL <= mid_a <= hi + DIM_SPAN_TOL):
            continue
        return val
    return None


def _prove(cands: list[_Cand], dims, fr) -> list[_Cand]:
    """直径标注 → 同轴链扩散 → 拿到证据的段。

    标注段用**标注值**当半径（栅格化读出的半宽有 ±GRID/2 的量化误差，
    实测 Ø7 读成 6.88/6.58；图上写死的数才是真值）；同轴段沿用实测半宽。
    """
    confirmed: list[_Cand] = []
    rest: list[_Cand] = []
    for c in cands:
        v = _dim_proof(c, dims, fr)
        if v is not None:
            confirmed.append(_Cand(c.axis, c.center, v / 2.0, c.lo, c.hi,
                                   f"dim:{v:g}", Tier.ANNOTATED))
        else:
            rest.append(c)
    changed = True
    while changed and rest:
        changed = False
        still: list[_Cand] = []
        for c in rest:
            mate = next((k for k in confirmed
                         if k.axis == c.axis
                         and abs(k.center - c.center) <= AXIS_TOL), None)
            if mate is not None:
                confirmed.append(_Cand(c.axis, c.center, c.half, c.lo, c.hi,
                                       f"coaxial:{mate.proof}", Tier.PROJECTION))
                changed = True
            else:
                still.append(c)
        rest = still
    return confirmed


# ---------------------------------------------------------------------------
# 发射
# ---------------------------------------------------------------------------

def _make_hole(d, view, fr, c: _Cand, p_axis: str,
               p_pos: float) -> Feature:
    dir_name = fr.u_axis if c.axis == "u" else fr.v_axis
    perp = fr.v_axis if c.axis == "u" else fr.u_axis
    # 垂直方向（视图系 center）→ 模型系
    if c.axis == "u":
        perp_m = fr.v_to_model(c.center)
        a0, a1 = fr.u_to_model(c.lo), fr.u_to_model(c.hi)
    else:
        perp_m = fr.u_to_model(c.center)
        a0, a1 = fr.v_to_model(c.lo), fr.v_to_model(c.hi)
    lo, hi = min(a0, a1), max(a0, a1)
    o = {"x": 0.0, "y": 0.0, "z": 0.0}
    o[p_axis] = p_pos
    o[perp] = perp_m
    origin = Point3(o["x"], o["y"], o["z"])
    ev = _segment_evidence(d, view, c)
    meth = "section:material_profile+" + c.proof.split(":", 1)[0]
    return Feature(
        id=FeatureId(-1),
        type=Claim(FeatureType.HOLE, meth, c.tier, ev),
        params={
            "radius": Claim(c.half, meth, c.tier, ev),
            "depth": Claim(hi - lo, f"{meth}_span", c.tier, ev),
            # HOLE 契约：axial_at = 孔口，轴向 = 钻入方向
            "axial_at": Claim(lo, f"{meth}_span", c.tier, ev),
        },
        axis=Claim(Axis3(origin, _DIRS[dir_name], None), meth, c.tier, ev),
        placement=Claim(origin, meth, c.tier, ev),
        source_view=view.id, evidence=list(ev),
    )


def _collinear(f: Feature, nf: Feature) -> bool:
    """两条 HOLE 的轴线是否共线（方向平行 + 轴距 ≤ AXIS_TOL）。"""
    if f.axis is None or f.axis.value is None or nf.axis is None:
        return False
    a, b = f.axis.value, nf.axis.value
    for name in ("x", "y", "z"):
        va = abs(getattr(a.direction, name))
        vb = abs(getattr(b.direction, name))
        if va > 0.999 and vb > 0.999:
            # 同向轴：比另外两轴的坐标
            d = 0.0
            for other in ("x", "y", "z"):
                if other == name:
                    continue
                d += (getattr(a.origin, other) - getattr(b.origin, other)) ** 2
            return math.sqrt(d) <= AXIS_TOL
    return False


def _segment_evidence(d, view, c: _Cand) -> tuple[str, ...]:
    """段 bbox（视图系）内的全部证据 handles。"""
    if c.axis == "u":
        x0, x1, y0, y1 = c.lo, c.hi, c.center - c.half, c.center + c.half
    else:
        x0, x1, y0, y1 = c.center - c.half, c.center + c.half, c.lo, c.hi
    out: list[str] = []
    for e in d.evidence:
        g = e.geom
        if isinstance(g, Line2):
            xs = [g.start.x, g.end.x]
            ys = [g.start.y, g.end.y]
        elif isinstance(g, Arc2):
            xs = [g.center.x - g.radius, g.center.x + g.radius]
            ys = [g.center.y - g.radius, g.center.y + g.radius]
        else:
            continue
        if max(xs) < x0 - SNAP_TOL or min(xs) > x1 + SNAP_TOL:
            continue
        if max(ys) < y0 - SNAP_TOL or min(ys) > y1 + SNAP_TOL:
            continue
        out.append(e.handle)
    return tuple(out)


__all__ = ["section_bores", "replace_coaxial"]
