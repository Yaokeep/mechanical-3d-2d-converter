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

## 孔口（`_open_ends`）

剖面线只画到端面，而发射端的基体按视图 bbox 拉满 ⇒ 孔若严格按剖面读数
切，端面会留一层薄材料膜把孔口封死（20180425 实测：中心阶梯孔左端 1.6 /
右端 0.7mm、顶部竖孔 0.15mm——模型外表面一个孔口都看不见）。判据：端点
到边界 ≤ `OPEN_MAX_GAP` 且沿段轴线向外一路无材料 ⇒ 延伸到边界外
`OPEN_MARGIN`。

## 锥孔（`_taper_of` + `radius_top`）

桶聚类的段只保证半宽在 `SPREAD_TOL` 内，锥孔会被读成一条**平均半宽**的
直段（20180425 顶部锥孔 Ø11.6→Ø12.5 被读成 Ø11.83 直孔）。回到栅格沿轴
重采样 + 两端**细化扫描**（步 `GRID/6`——栅格半宽是 0.3 的整数倍，宽端会
被量化吃掉最多 0.15，实测 0.45 的锥度差读成 0.30）：两端差 ∈ [TAPER_MIN,
TAPER_MAX]、沿轴单调、无单步跳变（台阶不是锥）⇒ 记 `taper`，发射成
`radius`（起始端）+ `radius_top`（远端）两参数；OCC 用 MakeCone，SW 发射器
尚未支持、明确拒绝（不静默按直孔建）。
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
#: 孔口判据：段端点到视图边界的最大距离。剖面线只画到端面，发射端的基体
#: 却按视图 bbox 拉满 ⇒ 孔按剖面读数切会在端面外留一层薄材料膜把孔口封死
#: （实测中心阶梯孔左端 1.6mm / 右端 0.7mm、顶部竖孔 0.15mm——模型外表面
#: 一个孔口都看不见）。超过这个距离的端点不判开口：中间的空腔可能属于别的
#: 孔，延伸会切掉两者之间的真材料（Ø7 横孔左端到左端面 20mm，路过的全是
#: 别条孔的空腔，但中间夹着 1.3mm 真材料）。
OPEN_MAX_GAP = 3.0
#: 开口路径上的材料率上限（全空才判开口）
OPEN_FRAC = 0.1
#: 开口端向外多切的余量（切穿表面，不正好贴面）
OPEN_MARGIN = 0.05
#: 孔端吸附容差：栅格端点 = 空腔首末格 ± GRID/2（±0.15），叠上材料图在边界
#: 格的判定，实测 0.13~0.49（20180425 的 Ø7 孔端读成 152.31 对图纸 152.20；
#: Ø7 与 Ø10.7 之间 1.11 长的锥腔被读成 0.30 的平台阶 —— 孔里的一片薄膜）
END_SNAP_TOL = 2.0 * GRID
#: 壁线判据：沿轴走向的直线，另一坐标的端点差上限
WALL_LINE_TOL = 0.01
#: 壁线到段边界的距离容差。栅格读出的 center/half 各带 ±GRID/2 ⇒ 端点位置
#: 最多偏 GRID（0.3）；取 1.5 倍余量。再大就会把对面的壁也认进来（最小孔的
#: 两壁相距 2×MIN_HALF = 1.2）
WALL_MATCH_TOL = 1.5 * GRID
#: 锥面斜线端点与「段边界 ± 半宽」的匹配容差（center/half 的量化误差叠加）
CONE_LINE_TOL = 0.6
#: 相邻两段之间的最小间隙（更小是同一段的栅格裂缝，不是锥腔）
MIN_GAP = 0.02
#: 锥孔判据：段两端的半宽差下限（细化扫描仍有 GRID/6 步长噪声，留余量）。
#: 实测 A—A 顶部锥孔 Ø11.6（锥底，深 15）→ Ø12.5（顶面），半宽差 0.45
TAPER_MIN = 0.35
#: 锥孔两端半宽差上限（更大的是喇叭口/异形腔，不是直锥）
TAPER_MAX = 3.0

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
    # 锥段：沿轴两端的实测半宽 (lo 端, hi 端)；直段为 None。
    # ``half`` 此时 = 小端（用于与直径标注对账：图纸标锥底直径）。
    taper: tuple[float, float] | None = None


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
        lines = _view_lines(d, view)
        cands = [_snap_ends(c, _wall_ends(lines, c))
                 for c in _candidates(us, vs, mat)]
        keep = [c for c in cands
                if _wall_ok(fr, mm, c)
                and c.half < MAX_HALF_FRAC * _span_of(c.axis, us, vs)]
        keep += _bridge_cones(keep, lines)
        tapered: list[_Cand] = []
        for c in keep:
            tp = _taper_of(c, us, vs, mat, fr, mm)
            tapered.append(c if tp is None else _Cand(
                c.axis, c.center, min(tp), c.lo, c.hi, c.proof, c.tier, tp))
        picked = _prove(tapered, _dims_geom(d, conv, view, fr), fr)
        if not picked:
            if keep:
                rep.notes.append(
                    f"剖面孔：{vid} 读出 {len(keep)} 段恒定空腔，但没有直径标注"
                    f"或同轴证据 ⇒ 不建（原则二）")
            continue
        for c in picked:
            out.append(_make_hole(d, view, fr, c, p_axis, p_pos,
                                  mm=mm, bbox=view.bbox))
        rep.notes.append(
            f"剖面孔：{vid} 从剖面线读出 {len(picked)} 段阶梯孔/通道"
            f"（恒定空腔 + 两侧材料 + 直径标注/同轴；剖切面 {p_axis}={p_pos:.3f}）")
    return out


def replace_coaxial(part, feats: list[Feature], rep) -> int:
    """摘掉与剖面段同轴的旧 HOLE —— 剖面材料压过投影猜测。

    只摘 ``type`` 为 HOLE 且方法**不是** ``annotation:`` 的（孔标注是图上
    明写，比剖面更强）；BOSS 不动。``section:face_step_*`` 也豁免 —— 端面
    沉台与中心孔同轴是常态（20180425 的 Ø70×1 沉台包着 Ø36 阶梯孔），
    按共线摘掉会把"端面少 1mm"变成"整个中心钻穿"。返回摘掉的条数。
    """
    if not feats:
        return 0
    keep: list[Feature] = []
    gone: list[Feature] = []
    for f in part.features:
        if (f.type.value == FeatureType.HOLE.value
                and not f.type.method.startswith("annotation:")
                and not f.type.method.startswith("section:face_step")
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
# 孔端吸附（栅格量化 → 图纸精确端点）
# ---------------------------------------------------------------------------

def _view_lines(d, view) -> list[Line2]:
    """视图里的**可见**直线（视图系图纸坐标）。

    ``_Cand`` 的 lo/hi/center 也在视图系（``_scan`` 的栅格按 ``bbox`` 铺、
    只把点送进 ``mm()`` 时才经帧映射）⇒ 两者同一坐标系，镜像帧不需要额外
    处理。
    """
    by_h = {e.handle: e for e in d.evidence}
    out: list[Line2] = []
    for h in view.evidence:
        e = by_h.get(h)
        if e is None or e.role.value != Role.VISIBLE:
            continue
        if isinstance(e.geom, Line2):
            out.append(e.geom)
    return out


def _wall_ends(lines: list[Line2], c: _Cand) -> list[float]:
    """落在段两侧壁上的直线，其沿轴端点（视图系精确值）。

    栅格端点 = 空腔首末格 ± ``GRID/2``，叠上边界格的材料判定，实测偏
    0.13~0.49；孔壁线的端点就是图纸坐标。壁线判据：沿轴走向（另一坐标
    恒定，容 ``WALL_LINE_TOL``），且该坐标落在 ``center ± half`` 上
    （容 ``WALL_MATCH_TOL`` —— 栅格读出的 center/half 各带 ±GRID/2）。
    """
    out: list[float] = []
    for g in lines:
        if c.axis == "v":                 # 段沿 v ⇒ 壁是竖线
            if abs(g.start.x - g.end.x) > WALL_LINE_TOL:
                continue
            p = g.start.x
            ends = (g.start.y, g.end.y)
        else:
            if abs(g.start.y - g.end.y) > WALL_LINE_TOL:
                continue
            p = g.start.y
            ends = (g.start.x, g.end.x)
        if min(abs(p - (c.center - c.half)),
               abs(p - (c.center + c.half))) > WALL_MATCH_TOL:
            continue
        out.extend(ends)
    return out


def _snap_ends(c: _Cand, ends: list[float]) -> _Cand:
    """把段两端吸附到 ``END_SNAP_TOL`` 内最近的壁线端点。

    不吸附时的实测症状（20180425 A—A）：Ø7 孔端读成 152.31 而图纸 152.20
    ⇒ 与 z=148.71 的 Ø7 横孔之间留 0.10 的残层；Ø7→Ø10.7 之间的锥腔被读成
    0.30 的平台阶 ⇒ 孔里 0.30 的薄膜。吸附后两处残层归零。
    """
    lo, hi = c.lo, c.hi
    near = [t for t in ends if abs(t - lo) <= END_SNAP_TOL]
    if near:
        lo = min(near, key=lambda t: abs(t - lo))
    near = [t for t in ends if abs(t - hi) <= END_SNAP_TOL]
    if near:
        hi = min(near, key=lambda t: abs(t - hi))
    if hi - lo < MIN_SEG or (lo == c.lo and hi == c.hi):
        return c
    return _Cand(c.axis, c.center, c.half, lo, hi, c.proof, c.tier, c.taper)


def _has_line(lines: list[Line2], p1, p2, tol: float = CONE_LINE_TOL):
    """返回两端点分别落在 p1/p2（± tol，不限方向）的直线，没有则 None。"""
    for g in lines:
        s, e = (g.start.x, g.start.y), (g.end.x, g.end.y)
        for a, b in ((p1, p2), (p2, p1)):
            if (abs(s[0] - a[0]) <= tol and abs(s[1] - a[1]) <= tol
                    and abs(e[0] - b[0]) <= tol and abs(e[1] - b[1]) <= tol):
                return g
    return None


def _bridge_cones(cands: list[_Cand], lines: list[Line2]) -> list[_Cand]:
    """同轴相邻两段之间的**锥面**：两侧壁各有一条斜线 ⇒ 锥过渡段。

    栅格把短锥腔并进台阶，两段之间留出间隙；图纸在间隙里画的是两条斜线
    （20180425 的 Ø7→Ø10.7：z 220.569→221.680，r 3.5→5.35）。两条都找到
    才建 —— 只有一条是倒角/局部斜线，不是整周锥面。半径直接取斜线端点的
    实测值（栅格半宽有 ±GRID/2 量化）。
    """
    out: list[_Cand] = []
    for i, a in enumerate(cands):
        for j, b in enumerate(cands):
            if i == j or a.axis != b.axis:
                continue
            if abs(a.center - b.center) > AXIS_TOL:
                continue
            gap = b.lo - a.hi
            if not (MIN_GAP < gap <= TAPER_MAX):
                continue
            if abs(b.half - a.half) < TAPER_MIN:
                continue
            sides = []
            for sgn in (-1.0, 1.0):
                p1 = (a.center + sgn * a.half, a.hi)
                p2 = (b.center + sgn * b.half, b.lo)
                g = _has_line(lines, p1, p2)
                if g is not None:
                    sides.append(g)
            if len(sides) < 2:
                continue
            # 斜线端点 → 锥的精确两端（沿轴坐标与半宽）
            v_lo: list[float] = []
            v_hi: list[float] = []
            xs_lo: list[float] = []
            xs_hi: list[float] = []
            for g in sides:
                for p in (g.start, g.end):
                    t = p.y if a.axis == "v" else p.x
                    q = p.x if a.axis == "v" else p.y
                    if abs(t - a.hi) <= abs(t - b.lo):
                        v_lo.append(t)
                        xs_lo.append(q)
                    else:
                        v_hi.append(t)
                        xs_hi.append(q)
            if len(v_lo) < 2 or len(v_hi) < 2:
                continue
            lo, hi = sum(v_lo) / len(v_lo), sum(v_hi) / len(v_hi)
            r_lo = (max(xs_lo) - min(xs_lo)) / 2.0
            r_hi = (max(xs_hi) - min(xs_hi)) / 2.0
            cen_lo = (max(xs_lo) + min(xs_lo)) / 2.0
            cen_hi = (max(xs_hi) + min(xs_hi)) / 2.0
            if abs(cen_lo - cen_hi) > AXIS_TOL or abs(r_lo - r_hi) < TAPER_MIN:
                continue
            out.append(_Cand(a.axis, (cen_lo + cen_hi) / 2.0, min(r_lo, r_hi),
                             lo, hi, "coaxial:cone", Tier.PROJECTION,
                             (r_lo, r_hi)))
    return out


# ---------------------------------------------------------------------------
# 圆柱性证据
# ---------------------------------------------------------------------------

def dims_geom(d, conv, view, fr) -> list[tuple[float, tuple[float, float],
                                              tuple[float, float], str]]:
    """该视图的尺寸：``(值, 点1, 点2, 尺寸实体 handle)``，点已换到模型系。

    点之所以要留着，是因为**光看数值会把半径标注当成直径**：A—A 的 15 条
    全是 linear（图上 Ø 以线性距离量出），其中「32」是顶上通道的深度、
    「15」是螺纹深、「17」是某条宽度 —— 只按数值配对会让"Ø32 的孔"
    （实测半宽 16.20 的伪段）凭空冒出来。几何关系（两点在**垂直于段轴**
    方向的间距 = 值、且中点落在段轴上）才是"这是一个直径"的证据。

    handle 给下游当特征证据（``face_steps`` 的端面圆盘/直径对账）。
    """
    if conv is None:
        return []
    from ..conventions.registry import ConvKind
    raw = {x.handle: x for x in d.dimensions}
    out: list[tuple[float, tuple[float, float], tuple[float, float], str]] = []
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
                    (fr.u_to_model(r.p2.x), fr.v_to_model(r.p2.y)),
                    dc.dim_ref))
    return out


def _dims_geom(d, conv, view, fr) -> list[tuple[float, tuple[float, float],
                                                tuple[float, float]]]:
    """``dims_geom`` 去掉 handle（``_prove`` 只要几何）。"""
    return [(v, p1, p2) for v, p1, p2, _h in dims_geom(d, conv, view, fr)]


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


def _half_at(c: _Cand, t: float, us, vs, mat) -> float | None:
    """栅格在沿轴位置 t 处、覆盖段轴线（center）的空腔半宽。"""
    ts, ps = (us, vs) if c.axis == "u" else (vs, us)
    k = min(range(len(ts)), key=lambda q: abs(ts[q] - t))
    if c.axis == "u":
        col = [mat[k][j] for j in range(len(vs))]
    else:
        col = [mat[i][k] for i in range(len(us))]
    for a, b in _runs(col):
        p_lo, p_hi = ps[a], ps[b]
        if p_lo - BUCK_TOL <= c.center <= p_hi + BUCK_TOL:
            return (p_hi - p_lo) / 2.0
    return None


def _half_at_fine(c: _Cand, t: float, fr, mm) -> float | None:
    """沿垂直轴**细化扫描**（步 GRID/6）从段中心向两侧找材料边界。

    栅格半宽是 0.3 的整数倍，锥孔宽端会被量化吃掉最多 0.15——两端各吃一点
    就足以让锥度差掉到判据以下（实测 0.45 读成 0.30）。端点判锥用这条。
    """
    step = GRID / 6.0
    limit = MAX_HALF_FRAC * 120.0      # 扫描上限（视图跨度级）

    def is_mat(p: float) -> bool:
        u, v = (t, p) if c.axis == "u" else (p, t)
        return mm(Point2(fr.u_to_model(u), fr.v_to_model(v)))

    if is_mat(c.center):
        return None
    lo = hi = c.center
    while abs(lo - c.center) < limit:
        if is_mat(lo - step):
            break
        lo -= step
    while abs(hi - c.center) < limit:
        if is_mat(hi + step):
            break
        hi += step
    return (hi - lo) / 2.0


def _taper_of(c: _Cand, us, vs, mat, fr=None, mm=None) -> tuple[float, float] | None:
    """段两端实测半宽：单调渐变且差值够大 ⇒ 锥段 (half_at_lo, half_at_hi)。

    桶聚类的段只保证"半宽在 SPREAD_TOL 内"，锥孔会被读成一条平均半宽的
    直段（实测顶部锥孔 Ø11.6→Ø12.5 被读成 Ø11.83 的直孔）。判据：两端
    **细化扫描**的半宽差 ≥ TAPER_MIN，且栅格沿轴的采样单调（容 GRID 噪声）。
    端点值按缩进实测线性外推到段端点。
    """
    span = c.hi - c.lo
    if span < 4.0 * GRID or fr is None or mm is None:
        return None
    inset = 1.5 * GRID
    h_lo = _half_at_fine(c, c.lo + inset, fr, mm)
    h_hi = _half_at_fine(c, c.hi - inset, fr, mm)
    if h_lo is None or h_hi is None:
        return None
    if not (TAPER_MIN <= abs(h_hi - h_lo) <= TAPER_MAX):
        return None
    n = 9
    t0, t1 = c.lo + GRID, c.hi - GRID
    hs: list[float] = []
    for k in range(n):
        h = _half_at(c, t0 + (t1 - t0) * k / (n - 1), us, vs, mat)
        if h is not None:
            hs.append(h)
    if len(hs) < 5:
        return None
    lo_h, hi_h = min(h_lo, h_hi), max(h_lo, h_hi)
    # 栅格半宽按 (末格−首格)×步长 计，系统性偏小最多一整格 ⇒ 容差取 2×GRID
    if any(h < lo_h - 2.0 * GRID or h > hi_h + 2.0 * GRID for h in hs):
        return None                    # 非单调 —— 台阶/异形，不是直锥
    jumps = [abs(b - a) for a, b in zip(hs, hs[1:])]
    if max(jumps) > max(TAPER_MIN, 0.4 * abs(h_hi - h_lo)):
        return None                    # 单步跳变 —— 是台阶不是锥面
    slope = (h_hi - h_lo) / (span - 2.0 * inset)
    return h_lo - slope * inset, h_hi + slope * inset


def _prove(cands: list[_Cand], dims, fr) -> list[_Cand]:
    """直径标注 → 同轴链扩散 → 拿到证据的段。

    标注段用**标注值**当半径（栅格化读出的半宽有 ±GRID/2 的量化误差，
    实测 Ø7 读成 6.88/6.58；图上写死的数才是真值）；同轴段沿用实测半宽。
    锥段用**小端**对账标注（图纸标的是锥底直径），``taper`` 原样传下去。
    """
    confirmed: list[_Cand] = []
    rest: list[_Cand] = []
    for c in cands:
        for_proof = c
        if c.taper is not None:
            small = min(c.taper)
            for_proof = _Cand(c.axis, c.center, small, c.lo, c.hi,
                              c.proof, c.tier, c.taper)
        v = _dim_proof(for_proof, dims, fr)
        if v is not None:
            taper = c.taper
            if taper is not None:
                # 标注值只钉小端；大端按实测的**半径差**跟着平移
                a, b = taper
                delta = abs(b - a)
                taper = ((v / 2.0, v / 2.0 + delta) if a <= b
                         else (v / 2.0 + delta, v / 2.0))
            confirmed.append(_Cand(c.axis, c.center, v / 2.0, c.lo, c.hi,
                                   f"dim:{v:g}", Tier.ANNOTATED, taper))
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
                                       f"coaxial:{mate.proof}", Tier.PROJECTION,
                                       c.taper))
                changed = True
            else:
                still.append(c)
        rest = still
    return confirmed


# ---------------------------------------------------------------------------
# 发射
# ---------------------------------------------------------------------------

def _open_ends(fr, mm, bbox, c: _Cand) -> tuple[float, float]:
    """段两端是否通到视图边界（⇒ 孔口，需要切穿端面），返回延伸后的范围。

    剖面线只覆盖到端面；基体按视图 bbox 拉伸，孔若严格按剖面读数切，
    端面会留一层薄材料膜把孔口封死（实测 0.15~1.6mm）。判据两条同时满足：
    端点到边界 ≤ ``OPEN_MAX_GAP``，且沿段轴线（固定垂直坐标 = 段中心）向外
    一路无材料 —— 中途遇到材料就说明路径被真材料隔断，延伸会切掉它。
    """
    lo, hi = c.lo, c.hi
    for to_hi in (False, True):
        end = hi if to_hi else lo
        if c.axis == "u":
            lim = bbox.xmax if to_hi else bbox.xmin
        else:
            lim = bbox.ymax if to_hi else bbox.ymin
        dist = abs(lim - end)
        if dist > OPEN_MAX_GAP:
            continue
        n = max(int(math.ceil(dist / GRID)), 1)
        solid = 0
        for k in range(n + 1):
            t = end + (lim - end) * k / n
            if c.axis == "u":
                p = Point2(fr.u_to_model(t), fr.v_to_model(c.center))
            else:
                p = Point2(fr.u_to_model(c.center), fr.v_to_model(t))
            solid += 1 if mm(p) else 0
        if solid > OPEN_FRAC * (n + 1):
            continue
        if to_hi:
            hi = lim + OPEN_MARGIN
        else:
            lo = lim - OPEN_MARGIN
    return lo, hi


def _make_hole(d, view, fr, c: _Cand, p_axis: str,
               p_pos: float, mm=None, bbox=None) -> Feature:
    if mm is not None and bbox is not None:
        c = _Cand(c.axis, c.center, c.half, *_open_ends(fr, mm, bbox, c),
                  c.proof, c.tier, c.taper)
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
    params = {
        "radius": Claim(c.half, meth, c.tier, ev),
        "depth": Claim(hi - lo, f"{meth}_span", c.tier, ev),
        # HOLE 契约：axial_at = 孔口，轴向 = 钻入方向
        "axial_at": Claim(lo, f"{meth}_span", c.tier, ev),
    }
    if c.taper is not None:
        # 锥孔：radius = 起始端（模型系 lo 端）；radius_top = 远端（lo+depth 处）。
        # 视图系 lo/hi 经 u_to_model/v_to_model 后可能翻转，按实际端点对齐。
        r_view_lo, r_view_hi = c.taper
        r_lo, r_hi = (r_view_lo, r_view_hi) if a0 <= a1 \
            else (r_view_hi, r_view_lo)
        params["radius"] = Claim(r_lo, meth + "_taper", c.tier, ev)
        params["radius_top"] = Claim(r_hi, meth + "_taper", c.tier, ev)
    return Feature(
        id=FeatureId(-1),
        type=Claim(FeatureType.HOLE, meth, c.tier, ev),
        params=params,
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


# ---------------------------------------------------------------------------
# 无定位剖面的深度通道（展开剖）
# ---------------------------------------------------------------------------

#: 剖面段半宽 ↔ 既有 HOLE 半径的匹配容差。标注段取的是**标注值**（`_prove`
#: 用 dim 值钉半径），与投影读出的半径只差字面取整（Ø14 → r=7.00 对 r=6.98）。
BIND_R = 0.4
#: 剖面材料沿某轴的全局跨度 ↔ 基体轴向跨度的匹配容差。栅格量化 ±GRID（0.3），
#: 端面台阶还有 1mm（凸台）—— 实测 V2 的 v 跨度 32.70 对「基体 32 + 凸台 1」。
EXT_TOL = 1.6
#: 「段的这一端是孔口」判据：到材料全局边界的距离上限（实测 V2 的 Ø14 开口端
#: 落在 v=57.87 = 全局最小；远端 Ø9 到 89.87，与全局最大 90.87 差的是 1mm 凸台）
MOUTH_TOL = 1.6
#: 盲孔判据：段长比本轴材料跨度短至少这么多。差得少的就是通孔（展开剖里
#: 通孔的两端都落在材料边界上），投影读成通孔本来就是对的。
MIN_BLIND = 1.5


def _named_axis(vec: Vector3) -> str | None:
    """方向向量的主分量轴名（不与任何坐标轴平行 ⇒ None）。"""
    ax = max(("x", "y", "z"), key=lambda k: abs(getattr(vec, k)))
    return ax if abs(getattr(vec, ax)) > 0.999 else None


def _span_of_feature(f) -> tuple[float, float] | None:
    """特征沿自身轴的区间（模型系，按 ``origin + dir·t`` 换算）。"""
    if f.axis is None or f.axis.value is None:
        return None
    o, d = f.axis.value.origin, f.axis.value.direction
    ax = _named_axis(d)
    if ax is None:
        return None
    if f.type.value == FeatureType.BASE.value:
        t0, t1 = 0.0, float(f.params["length"].value)
    elif f.type.value == FeatureType.BOSS.value:
        #: `axial_at` 在契约里是可选（缺省按 0 起，见 library.OPTIONAL_PARAMS）
        at = f.params.get("axial_at")
        t0 = float(at.value) if at is not None else 0.0
        t1 = t0 + float(f.params["height"].value)
    else:
        return None
    p = getattr(o, ax) + getattr(d, ax) * t0
    q = getattr(o, ax) + getattr(d, ax) * t1
    return min(p, q), max(p, q)


def axial_extent(part) -> tuple[str, float, float] | None:
    """基体的拉伸轴与它沿该轴的总跨度（含向外凸出的凸台）。

    基体区间复用 `recognizer._base_emit_range`（BASE 棱柱的 ``origin`` 与
    REVOLVE 回转体两种口径都在那里收过口）；再把 BOSS 区间并进来 —— 切除
    伸不到基体外面，凸台会（20180425 右端 Ø75×1 凸台 ⇒ 32 → 33）。剖面上
    读到的孔深要跟这条跨度比，才判得出通/盲。
    """
    from .recognizer import _axis_name, _base_emit_range

    base = next((f for f in part.features
                 if f.type.value in (FeatureType.BASE.value,
                                     FeatureType.REVOLVE.value)), None)
    if base is None:
        return None
    if base.type.value == FeatureType.REVOLVE.value:
        ax3 = base.axis.value if base.axis is not None else None
        if ax3 is None or _axis_name(ax3.direction)[:1] not in "+−":
            return None
        ax = _axis_name(ax3.direction)[-1].lower()
    else:
        dirn = base.params.get("dir")
        if dirn is None:
            return None
        ax = str(dirn.value)
    span = _base_emit_range(base, ax)
    if span is None:
        return None
    lo, hi = span
    for f in part.features:
        if (f.type.value != FeatureType.BOSS.value
                or f.axis is None or f.axis.value is None
                or _named_axis(f.axis.value.direction) != ax):
            continue
        sp = _span_of_feature(f)
        if sp is not None:
            lo, hi = min(lo, sp[0]), max(hi, sp[1])
    return ax, lo, hi


def _material_extent(axis: str, us, vs, mat) -> tuple[float, float]:
    """材料沿某轴的全局跨度（该轴任一垂直列有材料即算）。"""
    ts = us if axis == "u" else vs
    have: list[float] = []
    for k, t in enumerate(ts):
        col = ([mat[k][j] for j in range(len(vs))] if axis == "u"
               else [mat[i][k] for i in range(len(us))])
        if any(col):
            have.append(t)
    return (min(have), max(have)) if have else (0.0, 0.0)


def _hole_entry(f, ax: str) -> float:
    """HOLE 的孔口在轴 ``ax`` 上的模型坐标（``origin + dir·axial_at``）。

    ``axial_at`` 在契约里可选（缺省 0 起，与两个发射器的静默默认一致）。
    """
    o, d = f.axis.value.origin, f.axis.value.direction
    at = f.params.get("axial_at")
    return getattr(o, ax) + getattr(d, ax) * (float(at.value) if at else 0.0)


def bind_section_depths(d, corr, conv, part, rep) -> int:
    """无定位剖面的**深度**通道：剖面读出的孔深压过投影猜的「通孔」。

    展开剖（B—B/C—C 这类沿弯折剖切线展开的剖视）**没有可用视图帧**：水平轴
    是沿剖切线的展开长度，不对应任何模型轴 ⇒ `corr.frames` 里没有它，
    `section_bores` 整条跳过。代价是 20180425 的「6×Ø14 深 9 + Ø9 通」被投影
    读成 Ø14 通孔 —— 孔被钻穿，肉眼一眼可见。

    但空腔沿另一条视图轴（v）的**长度与位置无关**，材料图的**整体跨度**又能
    认出哪条轴是基体轴向（V2 的 v 跨度 32.70 ≈ 基体 32 + 凸台 1 = 33；V3 的
    v 跨度 45.34 对不上 ⇒ 不参与）。于是：

    1. 恒等帧（不平移、不翻面）扫掠 —— 材料图的分割对纯平移不变，
       同一套 `_candidates` / `_prove` 直接可用，坐标留在视图系；
    2. 只认**轴向对得上**的候选段（另一条轴是展开长度，不是深度）；
    3. 段两端里落在材料全局边界上的那端是**孔口**；
    4. 正反两种映射（v 与模型轴同向 / 反向）只有一种能把孔口对到既有 HOLE 的
       `axial_at`（正交视图的孔口证据，另一条证据通道）——都对不上或都对得上
       （对称件）就记账不动（原则二：歧义不提前消解）；
    5. 半径吻合、且段长比本轴跨度短 `MIN_BLIND` 的既有**通孔**改成盲孔，
       `depth = 段长`。展开剖只画一个代表（它穿过两个同构孔），同一批同直径
       孔按「同阵列同构」一起改（CONVENTION）。

    只**改既有孔的深度**，不新建特征：展开剖的水平轴不是模型坐标，新建一条孔
    需要的轴线位置没有任何证据。
    """
    ext = axial_extent(part)
    if ext is None or conv is None:
        return 0
    ax_name, ext_lo, ext_hi = ext
    ext_len = ext_hi - ext_lo
    if ext_len <= 0.0:
        return 0
    holes = [f for f in part.features
             if f.type.value == FeatureType.HOLE.value
             and f.axis is not None and f.axis.value is not None
             and _named_axis(f.axis.value.direction) == ax_name
             and bool(f.params.get("through")
                      and f.params["through"].value)]
    if not holes:
        return 0
    from ..views.correspondence import ViewFrame

    n = 0
    for view in d.views:
        if view.type.value != ViewType.SECTION.value or view.bbox is None:
            continue
        if view.id in corr.frames:
            continue                       # 有帧的剖面由 section_bores 读
        #: 恒等帧：u/v 都不平移不翻面 —— 本通道**不需要**模型坐标，只需要
        #: 材料图在视图系里的分割（深度是长度，平移不变）。
        idfr = ViewFrame(view.id, ViewType.SECTION, "u", "v", "w")
        mm = material_map(d, idfr, view.bbox)
        if not getattr(mm, "has_hatch", False):
            continue
        us, vs, mat = _scan(idfr, mm, view.bbox)
        lines = _view_lines(d, view)
        cands = [_snap_ends(c, _wall_ends(lines, c))
                 for c in _candidates(us, vs, mat)]
        keep = [c for c in cands
                if _wall_ok(idfr, mm, c)
                and c.half < MAX_HALF_FRAC * _span_of(c.axis, us, vs)]
        keep += _bridge_cones(keep, lines)
        picked = _prove(keep, _dims_geom(d, conv, view, idfr), idfr)
        for axis in ("u", "v"):
            lo_v, hi_v = _material_extent(axis, us, vs, mat)
            if hi_v - lo_v <= 0.0:
                continue
            if abs((hi_v - lo_v) - ext_len) > EXT_TOL:
                rep.notes.append(
                    f"剖面孔：{view.id} 的 {axis} 向材料跨度 {hi_v - lo_v:.2f} 与"
                    f"基体轴向跨度 {ext_len:.2f} 不符 ⇒ 该轴不是孔深方向（展开剖"
                    f"的展开长度），不参与深度绑定")
                continue
            segs = [c for c in picked if c.axis == axis]
            if segs:
                n += _bind_axis(d, view, rep, segs, lo_v, hi_v,
                                ax_name, ext_lo, ext_hi, holes)
    return n


def _bind_axis(d, view, rep, segs: list[_Cand], lo_v: float, hi_v: float,
               ax_name: str, ext_lo: float, ext_hi: float,
               holes: list) -> int:
    """一条轴上的全部段 ↔ 既有通孔的深度绑定（判据见 `bind_section_depths`）。

    方向（v 与模型轴同向 / 反向）是**整张剖面共享**的，不能逐段各选一个 ——
    逐段选会把「Ø14 的孔口在低端面」与「Ø9 的出口在高端面」这两种端点各配
    一个方向，得到自相矛盾的深度。故先用「近端到孔口面的距离」投票定方向：
    真正贴着孔口的那一段距离近乎 0（20180425 实测 0.001，另一端 0.70），
    两种方向接近（比值 < 3）就是对称件、无证据，不绑（原则二）。
    """
    span = hi_v - lo_v
    # 每段能匹配上的既有通孔（半径），半径对不上就不参与本视图
    match: dict[int, list[_Cand]] = {}
    for c in segs:
        hit = [f for f in holes
               if abs(float(f.params["radius"].value) - c.half) <= BIND_R]
        for f in hit:
            match.setdefault(f.id, []).append(c)
    if not match:
        return 0

    # ---- 方向投票：对每个候选孔口面，取「各段近端到它」的最小误差 ----
    best: tuple[float, str, float, float] | None = None    # (err, tag, v_mouth, y_open)
    scored: list[tuple[float, str, float, float]] = []
    for tag, flip in (("同向", False), ("反向", True)):
        for f in holes:
            if f.id not in match:
                continue
            y_open = _hole_entry(f, ax_name)
            v_mouth = (hi_v - (y_open - ext_lo) if flip
                       else lo_v + (y_open - ext_lo))
            if not (lo_v - MOUTH_TOL <= v_mouth <= hi_v + MOUTH_TOL):
                continue
            err = min(min(abs(c.lo - v_mouth), abs(c.hi - v_mouth))
                      for c in match[f.id])
            if err > MOUTH_TOL:
                continue
            scored.append((err, tag, v_mouth, y_open))
            if best is None or err < best[0]:
                best = (err, tag, v_mouth, y_open)
    if best is None:
        rep.notes.append(
            f"剖面孔：{view.id} 无定位剖面，读出 {len(match)} 组同直径段，但两种"
            f"孔口映射都对不上既有通孔的孔口（{ax_name} 向）⇒ 不绑深度（原则二）")
        return 0
    err, tag, v_mouth, _ = best
    rival = sorted(s[0] for s in scored if s[1] != tag)
    if rival and rival[0] < 3.0 * max(err, 1e-6):
        rep.notes.append(
            f"剖面孔：{view.id} 的同向/反向孔口映射误差相近"
            f"（{err:.2f} vs {rival[0]:.2f} mm）⇒ 正反方向分不清，不绑深度（原则二）")
        return 0

    # ---- 逐孔绑定：depth = 从孔口面量到该段远端；≈整幅的保持通孔 ----
    n = 0
    for f in holes:
        if f.id not in match:
            continue
        cur = f.params.get("through")
        if not (cur and cur.value):
            continue                        # 已被别的视图/通道定过，不覆盖
        depths = []
        for c in match[f.id]:
            near = c.lo if abs(c.lo - v_mouth) <= abs(c.hi - v_mouth) else c.hi
            far = c.hi if near == c.lo else c.lo
            depths.append(abs(far - v_mouth))
        if max(depths) - min(depths) > 0.5:
            rep.notes.append(
                f"剖面孔：{view.id} 的 Ø{2 * f.params['radius'].value:g} 段给出"
                f"不相同的深度 {['%.2f' % x for x in depths]} ⇒ 分不清哪个实例，"
                f"不绑（原则二）")
            continue
        depth = sum(depths) / len(depths)
        if depth >= span - MIN_BLIND:
            continue                        # 段通到对面 ⇒ 就是通孔，投影读对了
        ev: tuple = ()
        for c in match[f.id]:
            ev += _segment_evidence(d, view, c)
        if not ev:
            ev = tuple(f.evidence[:1])   # CONVENTION 级必须带证据（Claim 不变式）
        f.params["depth"] = Claim(depth, "section:depth_profile",
                                  Tier.CONVENTION, ev)
        f.params["through"] = Claim(False, "section:depth_profile",
                                    Tier.CONVENTION, ev)
        n += 1
        rep.notes.append(
            f"剖面孔：{view.id} 无定位剖面（展开剖），孔深可读 —— "
            f"Ø{2 * float(f.params['radius'].value):g} 深 {depth:.2f}"
            f"（孔口面 v={v_mouth:.2f} 按{tag}映射 → {ax_name}="
            f"{_hole_entry(f, ax_name):.3f}，与投影孔口一致）；"
            f"特征 #{f.id} 由通孔改为盲孔")
    return n


__all__ = ["bind_section_depths", "section_bores", "replace_coaxial"]
