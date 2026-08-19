#!/usr/bin/env python
"""通用 DXF 工程图 → SolidWorks 原生特征模型转换器 v0.6.13

与 dxf_to_3d_general.py 的关系:
  - 复用其 CSG 重建结果（精确实体 combined，体积误差 ~1%）
  - 本脚本对 combined 做 z 切片特征识别，用 SW COM 原生特征 API 重建，
    输出 .sldprt 含可编辑特征树（Boss-Extrude / Cut-Extrude / Revolve），
    区别于 STEP 导入产生的 Imported 哑几何（不可编辑）

核心算法链:
  CSG 实体 → z 切片(0.5mm)环提取(圆/线/弧分类) → 环轨迹跟踪
  → 分段(签名变化断开) → 段分类(常截面 / 锥面圆变径 / 兜底细分)
  → SW 特征建模(凸台序列自底向上 + 孔切除 + 锥面旋转凸台)

坐标系: 与 CSG 完全同轴 — CSG(x, y, z) → SW(x, y, z)。
  凸台/切除草图均在"前视基准面"的平行面上（世界 XY 面，法向 +Z），
  草图坐标 = CSG 截面 (x, y)，草图高度由基准面偏移承载：
  基准面偏移量 = CSG z + shift（shift = -zmin 抬高使底 → 0，避免
  InsertRefPlane 负偏移）。锥面 Revolve 草图在前视基准面，
  母线 (r, z+shift)，旋转轴沿草图 y 即 CSG z 轴。

用法（需 cad-occt 环境 + SolidWorks 2025 已启动）:
    /c/Users/yaoshuo/miniconda3/envs/cad-occt/python.exe dxf_to_sw_features.py CAD/reducer.dxf
    /c/Users/yaoshuo/miniconda3/envs/cad-occt/python.exe dxf_to_sw_features.py input.dxf output.sldprt
    --no-step: 跳过中间 STEP 导出（默认会导出供体积对比）

验证: 特征树特征数（SW COM FeatureManager 遍历）+ 体积对比
  （SW 导出 STEP → compare_models.py --dz 21.95 基准.step 重建.step）
"""

import math
import sys
from pathlib import Path

# 确保项目根目录和 src/ 在 sys.path 中
PROJECT_ROOT = Path(__file__).parent
SRC_PATH = PROJECT_ROOT / "src"
for p in [str(PROJECT_ROOT), str(SRC_PATH)]:
    if p not in sys.path:
        sys.path.insert(0, p)

from OCC.Core.BRepAlgoAPI import BRepAlgoAPI_Section
from OCC.Core.gp import gp_Pnt, gp_Dir, gp_Pln
from OCC.Core.TopExp import TopExp_Explorer
from OCC.Core.TopAbs import TopAbs_EDGE, TopAbs_IN
from OCC.Core.BRepAdaptor import BRepAdaptor_Curve
from OCC.Core.BRepClass3d import BRepClass3d_SolidClassifier
from OCC.Core.GeomAbs import GeomAbs_Circle, GeomAbs_Line
from OCC.Core.Bnd import Bnd_Box
from OCC.Core.BRepBndLib import brepbndlib

from dxf_to_3d_general import convert_dxf_to_3d
from src.core.sw_automation.sw_driver import SolidWorksDriver

SAMPLE_STEP = 0.5  # z 切片步长 (mm)
SIGN_ROUND = 1  # 签名坐标取整小数位 (0.1mm)


# ============================================================
# 环提取与分类
# ============================================================


def _dist2d(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


def _classify_edge(e):
    """OCC 截面边 → 字典（circle 圆 / line 线 / poly 采样折线兜底）。"""
    ac = BRepAdaptor_Curve(e)
    t = ac.GetType()
    if t == GeomAbs_Circle:
        c = ac.Circle()
        p = c.Location()
        r = c.Radius()
        t0, t1 = ac.FirstParameter(), ac.LastParameter()
        p0 = ac.Value(t0)
        p1 = ac.Value(t1)
        full = abs(abs(t1 - t0) - 2 * math.pi) < 0.05
        return {
            "type": "circle",
            "cx": p.X(),
            "cy": p.Y(),
            "r": r,
            "t0": t0,
            "t1": t1,
            "p0": (p0.X(), p0.Y()),
            "p1": (p1.X(), p1.Y()),
            "full": full,
        }
    if t == GeomAbs_Line:
        p0 = ac.Value(ac.FirstParameter())
        p1 = ac.Value(ac.LastParameter())
        return {"type": "line", "p0": (p0.X(), p0.Y()), "p1": (p1.X(), p1.Y())}
    # 其他曲线（理论不出现，CSG 由线/圆棱柱构成）: 采样折线兜底
    n = 24
    pts = [
        (
            ac.Value(
                ac.FirstParameter() + (ac.LastParameter() - ac.FirstParameter()) * i / n
            )
        )
        for i in range(n + 1)
    ]
    pts = [(p.X(), p.Y()) for p in pts]
    return {"type": "poly", "p0": pts[0], "p1": pts[-1], "pts": pts}


def _reverse_edge(e):
    if e["type"] == "circle":
        e = dict(e)
        e["t0"], e["t1"] = e["t1"], e["t0"]
        e["p0"], e["p1"] = e["p1"], e["p0"]
        return e
    e = dict(e)
    e["p0"], e["p1"] = e["p1"], e["p0"]
    if e["type"] == "poly":
        e["pts"] = list(reversed(e["pts"]))
    return e


def _assemble_loops(edges, ztol=0.25):
    """端点贪心匹配把边组装为闭合环列表（就地反转边方向）。"""
    loops = []
    unused = list(range(len(edges)))
    while unused:
        chain = [unused.pop(0)]
        changed = True
        while changed:
            changed = False
            for i in unused[:]:
                if _dist2d(edges[chain[0]]["p0"], edges[i]["p1"]) < ztol:
                    chain.insert(0, i)
                    unused.remove(i)
                    changed = True
                elif _dist2d(edges[chain[-1]]["p1"], edges[i]["p0"]) < ztol:
                    chain.append(i)
                    unused.remove(i)
                    changed = True
                elif _dist2d(edges[chain[-1]]["p1"], edges[i]["p1"]) < ztol:
                    edges[i] = _reverse_edge(edges[i])
                    chain.append(i)
                    unused.remove(i)
                    changed = True
                elif _dist2d(edges[chain[0]]["p0"], edges[i]["p0"]) < ztol:
                    edges[i] = _reverse_edge(edges[i])
                    chain.insert(0, i)
                    unused.remove(i)
                    changed = True
        if (
            _dist2d(edges[chain[0]]["p0"], edges[chain[-1]]["p1"]) < ztol
            and len(chain) >= 1
        ):
            loops.append([edges[i] for i in chain])
    return loops


def _slice_loops_at(shape, z, ztol=0.25):
    """z 平面截实体 → 环列表（每个环 = 有序边列表，首尾相接闭合）。"""
    plane = gp_Pln(gp_Pnt(0, 0, z), gp_Dir(0, 0, 1))
    sect = BRepAlgoAPI_Section(shape, plane)
    sect.Build()
    if not sect.IsDone():
        return []
    edges = []
    exp = TopExp_Explorer(sect.Shape(), TopAbs_EDGE)
    while exp.More():
        edges.append(_classify_edge(exp.Current()))
        exp.Next()
    if not edges:
        return []
    return _assemble_loops(edges, ztol)


def _has_dup_edges(loops):
    """检测退化切片: 环内存在重复边（含反转后重合，层落在面边界）。

    零面积假环不在此检测——键槽切穿凸台顶部时顶线+小弧假环是
    常态截面，由 _normalize_loops 跨环拼合处理。
    """
    for loop in loops:
        for i in range(len(loop)):
            for j in range(i + 1, len(loop)):
                a, b = loop[i], loop[j]
                if a["type"] != b["type"]:
                    continue
                d1 = _dist2d(a["p0"], b["p0"]) + _dist2d(a["p1"], b["p1"])
                d2 = _dist2d(a["p0"], b["p1"]) + _dist2d(a["p1"], b["p0"])
                if d1 < 2e-3 or d2 < 2e-3:
                    return True
    return False


def _arc_geom_span(e):
    """弧端点几何角度区间 [a0, a1]（a1 可 > 2π）。

    BRep 参数 t0/t1 在布尔拼接面上不可靠（各面片局部参数，
    4 条真实四分弧可能全报 t=[0,1.571]），几何端点角度才可靠。
    """
    cx, cy = e["cx"], e["cy"]
    a0 = math.atan2(e["p0"][1] - cy, e["p0"][0] - cx)
    a1 = math.atan2(e["p1"][1] - cy, e["p1"][0] - cx)
    if a1 < a0:
        a1 += 2 * math.pi
    return a0, a1


def _arc_dir(e):
    """弧绘制方向（SW CreateArc clockwise 参数）: 端点几何角度判定劣弧走向。"""
    cx, cy = e["cx"], e["cy"]
    a0 = math.atan2(e["p0"][1] - cy, e["p0"][0] - cx)
    a1 = math.atan2(e["p1"][1] - cy, e["p1"][0] - cx)
    delta = (a1 - a0) % (2 * math.pi)
    return delta > math.pi  # 顺时针劣弧


def _normalize_loops(loops, ztol=0.25):
    """层级归一化: 跨环拼合同圆心同半径弧（覆盖 2π 合成整圆）→
    剩余边重新组装 → 过滤零面积假环。

    CSG 布尔拼接面使 Section 把整圆拆成多条弧，甚至分属不同环
    （凸台被键槽切穿时外圆弧 + 顶部假环）；SW CreateArc 对弧-弧
    共享端点同样退化，合成整圆后改用 CreateCircleByRadius 单段绘制。
    """
    # 1) 收集全层 circle 边按 (cx, cy, r) 分组，去重 + 区间衔接合并
    groups = {}
    for loop in loops:
        for e in loop:
            if e["type"] == "circle":
                key = (round(e["cx"], 2), round(e["cy"], 2), round(e["r"], 2))
                groups.setdefault(key, []).append(e)
    merged = []  # 合成整圆边
    consumed = set()  # 被合成消耗的边 id（含重复边）
    for key, es in groups.items():
        if len(es) < 2:
            continue
        intervals = []
        for e in es:
            a0, a1 = _arc_geom_span(e)
            intervals.append((a0, a1, e))
        seen = set()
        uniq = []
        for iv in sorted(intervals, key=lambda x: (x[0], x[1])):
            k = (round(iv[0], 3), round(iv[1], 3))
            if k not in seen:
                seen.add(k)
                uniq.append(iv)
            else:
                consumed.add(id(iv[2]))
        if not uniq:
            continue
        chains = [[uniq[0][0], uniq[0][1], [uniq[0][2]]]]
        for t0, t1, e in uniq[1:]:
            # 链合并需角度连续 且 弧端点几何重合（整圆被布尔拼接拆分的
            # 弧首尾相接）。方∩圆轮廓（法兰盘 60×60 方 ∩ R40 圆角）的
            # 4 段弧被直线隔开，端点不重合、角度区间却伪连续（大弧
            # [48.7°,401.3°] 与小弧 [138.7°,491.3°] 重叠）——仅按角度
            # 判据会把方∩圆错误合成整圆、直线丢弃 → SW 拉伸成纯圆、
            # 多出 4 个弓形角（实测 +44,803 体积偏差主因）。
            prev_e = chains[-1][2][-1]
            endpoints_close = (
                min(
                    _dist2d(prev_e["p1"], e["p0"]),
                    _dist2d(prev_e["p1"], e["p1"]),
                    _dist2d(prev_e["p0"], e["p0"]),
                    _dist2d(prev_e["p0"], e["p1"]),
                )
                < 0.15
            )
            if t0 <= chains[-1][1] + 0.1 and endpoints_close:
                chains[-1][1] = max(chains[-1][1], t1)
                chains[-1][2].append(e)
            else:
                chains.append([t0, t1, [e]])
        for t0, t1, es2 in chains:
            if len(es2) < 2:
                continue
            if t1 - t0 >= 2 * math.pi - 0.05:
                e0 = es2[0]
                full = {
                    "type": "circle",
                    "cx": e0["cx"],
                    "cy": e0["cy"],
                    "r": e0["r"],
                    "t0": 0.0,
                    "t1": 2 * math.pi,
                    "p0": (e0["cx"] + e0["r"], e0["cy"]),
                    "p1": (e0["cx"] + e0["r"], e0["cy"]),
                    "full": True,
                }
                merged.append(full)
                for e in es2:
                    consumed.add(id(e))
    # 2) 剩余边重新组装（键槽矩形等被切开环恢复）
    rest = []
    for loop in loops:
        for e in loop:
            if id(e) not in consumed:
                rest.append(e)
    out = _assemble_loops(rest, ztol)
    # 3) 过滤单边/零面积假环（整圆单边环保留），追加合成整圆
    out = [
        l
        for l in out
        if (len(l) == 1 and l[0]["type"] == "circle" and l[0]["full"])
        or (len(l) >= 2 and abs(_loop_area(l)) >= 1.0)
    ]
    out.extend([c] for c in merged)
    return out


def _slice_loops(shape, z, ztol=0.25):
    """切片 + 退化检测重试 + 层级归一化。"""
    loops = _slice_loops_at(shape, z, ztol)
    if _has_dup_edges(loops):
        # 层恰好落在面边界产生退化 → 偏移半层重试
        loops = _slice_loops_at(shape, z + SAMPLE_STEP, ztol)
    return _normalize_loops(loops, ztol)


def _loop_area(loop):
    """环面积（圆 = πr²；poly/线环 = 鞋带公式；近似用于外环判定）。"""
    if len(loop) == 1 and loop[0]["type"] == "circle" and loop[0]["full"]:
        return math.pi * loop[0]["r"] ** 2
    pts = [e["p0"] for e in loop]
    s = 0.0
    for i in range(len(pts)):
        x1, y1 = pts[i]
        x2, y2 = pts[(i + 1) % len(pts)]
        s += x1 * y2 - x2 * y1
    return abs(s) / 2.0


def _loop_center(loop):
    """环中心（圆 = 圆心；其他 = 顶点均值）。"""
    if len(loop) == 1 and loop[0]["type"] == "circle":
        return (loop[0]["cx"], loop[0]["cy"])
    pts = [e["p0"] for e in loop]
    return (sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts))


def _loop_signature(loop):
    """环签名（用于跨层匹配与分段判定）。"""
    if len(loop) == 1 and loop[0]["type"] == "circle" and loop[0]["full"]:
        return (
            "circ",
            round(loop[0]["r"], 2),
            round(loop[0]["cx"], SIGN_ROUND),
            round(loop[0]["cy"], SIGN_ROUND),
        )
    pts = tuple(
        (round(e["p0"][0], SIGN_ROUND), round(e["p0"][1], SIGN_ROUND)) for e in loop
    )
    return ("poly", pts, tuple(e["type"] for e in loop))


def _inner_kinds(loops):
    """层内环语义: 同心包含链交替 → {id(loop): "cut"/"boss"}。

    外环=材料；被外环直接包含的内环=孔(cut)；被孔包含的环=材料岛
    (boss)；再内层又是孔…… 不同心的环（多孔布局）默认 cut。
    """
    by_area = sorted(loops, key=_loop_area, reverse=True)
    kinds = {id(by_area[0]): "outer"}
    for l in by_area[1:]:
        kinds[id(l)] = "cut"
        lr = l[0]["r"] if len(l) == 1 and l[0]["type"] == "circle" else None
        if lr is None:
            continue
        lc = _loop_center(l)
        parent = None
        parent_r = 1e9
        for p in by_area:
            if p is l:
                continue
            pr = p[0]["r"] if len(p) == 1 and p[0]["type"] == "circle" else None
            if pr is None or pr <= lr + 0.1 or pr >= parent_r:
                continue
            if _dist2d(lc, _loop_center(p)) < 1.0:
                parent, parent_r = p, pr
        if parent is not None:
            pk = kinds[id(parent)]
            kinds[id(l)] = "boss" if pk == "cut" else "cut"
    return kinds


# ============================================================
# 轨迹跟踪与分段
# ============================================================


def _track_segments(shape, zmin, zmax):
    """z 切片轨迹跟踪 → (外环段列表, 孔段列表)。

    每层切片视为高度带 [z, z+SAMPLE_STEP)，段 z_bot = 首层 z、
    z_top = 末层 z + SAMPLE_STEP（= 断段处当前层 z）。
    每段: {"z_bot", "z_top", "loop"}（loop 为 z_bot 层环，作草图）。
    """
    n_layers = int((zmax - zmin) / SAMPLE_STEP) + 1
    outer_track = []  # [(z, loop)] 当前外环段
    holes_active = {}  # hid → [(z, loop)] 当前孔段
    holes_kind = {}  # hid → "cut" / "boss"（同心包含链交替）
    outer_segs = []
    hole_segs = {}
    next_hid = 0

    def _close_outer(z_top):
        if len(outer_track) >= 1:
            outer_segs.append(
                {
                    "z_bot": outer_track[0][0],
                    "z_top": z_top,
                    "loop": outer_track[0][1],
                }
            )
        outer_track.clear()

    def _close_hole(hid, z_top):
        tr = holes_active.pop(hid)
        if len(tr) >= 1:
            seg = {
                "z_bot": tr[0][0],
                "z_top": z_top,
                "loop": tr[0][1],
            }
            if hid in holes_kind:
                seg["kind"] = holes_kind[hid]
            hole_segs.setdefault(hid, []).append(seg)
        # 跨段孔（台阶孔）保留同一 hid 便于统计，但新段需新轨迹
        holes_active[hid] = []

    zs = [zmin + i * SAMPLE_STEP for i in range(n_layers)]
    layers_cache = _slice_layers_repaired(shape, zs)
    for z in zs:
        loops = layers_cache[z]
        if not loops:
            _close_outer(z)
            for hid in list(holes_active):
                _close_hole(hid, z)
            continue
        loops.sort(key=_loop_area, reverse=True)
        outer = loops[0]
        inners = loops[1:]
        # 外环轨迹（含锥面渐变延续: 同中心整圆 |Δr|≤3.0/层 合并，
        # 渐变变平或反向时断段；台阶突变 R30→R25=5/层 照常断段）
        if outer_track:
            sa = _loop_signature(outer_track[-1][1])
            sb = _loop_signature(outer)
            if sa != sb:
                both_circ = (
                    sa[0] == "circ"
                    and sb[0] == "circ"
                    and sa[2] == sb[2]
                    and sa[3] == sb[3]
                )
                dr = sb[1] - sa[1] if both_circ else None
                if not both_circ or abs(dr) > 3.0:
                    _close_outer(z)
                elif abs(dr) < 0.02:
                    # 渐变变平（锥面→圆柱平段分界）
                    _close_outer(z)
        outer_track.append((z, outer))
        # 内环轨迹匹配（中心 + 半径），kind 按同心包含链交替
        kinds = _inner_kinds(loops)
        matched = set()
        for inner in inners:
            ic = _loop_center(inner)
            ir = None
            if len(inner) == 1 and inner[0]["type"] == "circle" and inner[0]["full"]:
                ir = inner[0]["r"]
            best = None
            best_d = 1.0
            for hid, tr in holes_active.items():
                if not tr or hid in matched:
                    continue
                tc = _loop_center(tr[-1][1])
                if _dist2d(ic, tc) > best_d:
                    continue
                tl = tr[-1][1]
                # 形状签名必须一致: φ12 孔与键槽相交后同一内环变成
                # 混合环（键槽 3 线 + r6 弧），若按中心匹配并入键槽
                # 矩形轨迹，段 loop 只保留首层矩形 → φ12 孔被漏切
                # （实测 -3,269 体积）。签名变化即断段，混合环独立成段。
                if _loop_signature(tl) != _loop_signature(inner):
                    continue
                tr_r = None
                if len(tl) == 1 and tl[0]["type"] == "circle" and tl[0]["full"]:
                    tr_r = tl[0]["r"]
                if ir is not None and tr_r is not None and abs(ir - tr_r) > 0.35:
                    continue
                best, best_d = hid, _dist2d(ic, tc)
            if best is not None:
                holes_active[best].append((z, inner))
                holes_kind[best] = kinds.get(id(inner), "cut")
                matched.add(best)
            else:
                holes_active[next_hid] = [(z, inner)]
                holes_kind[next_hid] = kinds.get(id(inner), "cut")
                matched.add(next_hid)
                next_hid += 1
        for hid in list(holes_active):
            if hid not in matched:
                _close_hole(hid, z)

    _close_outer(zmax)
    for hid in list(holes_active):
        _close_hole(hid, zmax)
    # 合并每个 hid 的段列表
    hole_seg_list = []
    for hid, segs in hole_segs.items():
        for s in segs:
            s["hid"] = hid
            hole_seg_list.append(s)
    # 凹口外环段（键槽切穿凸台 → 截面为线+弧混合环）→ 简化为整圆:
    # 混合环线端明显落在最大弧圆内（键槽壁线端距圆心 < r-0.3）即凹口；
    # 方∩圆法兰环线端在圆外（凸角）不简化。凹口由 cut 段加深补切。
    # 简化原因: 混合环线-弧端点有 0.2mm 组装间隙，SW 草图开环拉伸失败
    # （Boss9 实测 [FAIL]），整圆 + 键槽切穿等效且可靠。
    for seg in outer_segs:
        loop = seg["loop"]
        if (
            len(loop) <= 1
            or not any(e["type"] == "circle" for e in loop)
            or not any(e["type"] == "line" for e in loop)
        ):
            continue
        best = max((e for e in loop if e["type"] == "circle"), key=lambda e: e["r"])
        cx, cy, r = best["cx"], best["cy"], best["r"]
        recess = any(
            _dist2d((e["p0"][0], e["p0"][1]), (cx, cy)) < r - 0.3
            or _dist2d((e["p1"][0], e["p1"][1]), (cx, cy)) < r - 0.3
            for e in loop
            if e["type"] == "line"
        )
        if not recess:
            continue
        seg["loop"] = [
            {
                "type": "circle",
                "cx": cx,
                "cy": cy,
                "r": r,
                "t0": 0.0,
                "t1": 2 * math.pi,
                "p0": (cx + r, cy),
                "p1": (cx + r, cy),
                "full": True,
            }
        ]
        seg["recess"] = True
    # 凹口段对应的 cut 段深度延长到凹口段顶（键槽 z_top 与凹口段
    # z_bot 相接 → 键槽一次切穿凸台，弥补简化掉的凹口）
    for seg in hole_seg_list:
        if seg.get("kind") != "cut":
            continue
        for oseg in outer_segs:
            if oseg.get("recess") and abs(oseg["z_bot"] - seg["z_top"]) < 0.26:
                seg["z_top"] = oseg["z_top"]
                break
    return outer_segs, hole_seg_list


# ============================================================
# 段分类
# ============================================================


def _slice_layers_repaired(shape, zs):
    """预切片缓存 + 退化层修复，返回 {z: 环列表}。

    采样点取层带中点 z+0.25（层=高度带语义下带中截面最能代表
    带主体，避开带底踩在特征顶面边界的退化）；两类退化层用
    上层截面替换:
    1. 缺外环: 下一层最大环面积 > 2×本层（本层落在顶面边界，
       Section 只产生孔环）
    2. 双外轮廓: 次大环非整圆（如台阶顶 + 凸台底方柱同层出现）
    """
    cache = {z: _slice_loops(shape, z + SAMPLE_STEP / 2) for z in zs}
    for i, z in enumerate(zs):
        loops = cache[z]
        if not loops:
            continue
        big2 = sorted((_loop_area(l) for l in loops), reverse=True)[:2]
        # 次大环非整圆 → 双外轮廓边界层（如台阶顶 + 凸台底方柱）
        boundary = False
        if len(big2) >= 2:
            second = sorted(loops, key=_loop_area, reverse=True)[1]
            boundary = big2[1] > 150 and not (
                len(second) == 1 and second[0]["type"] == "circle" and second[0]["full"]
            )
        # 缺外环退化: 下一层（向实体内部）明显更大
        shrink = False
        if i + 1 < len(zs) and cache[zs[i + 1]]:
            na = max(_loop_area(l) for l in cache[zs[i + 1]])
            if big2[0] * 2 < na:
                shrink = True
        if boundary or shrink:
            alt = zs[i + 1] if i + 1 < len(zs) else zs[i - 1]
            cache[z] = cache[alt] if alt in cache else loops
    return cache


def _layers_of(shape, z_bot, z_top):
    """段内每层环列表（供分类判定）。

    只采样 [z_bot, z_top) 段内层: z_top 层属于下一段
    （浮点累加误差下 z_top 层切片可能已进入下段形状）。
    """
    n = max(1, int(round((z_top - z_bot) / SAMPLE_STEP)))
    zs = [z_bot + i * SAMPLE_STEP for i in range(n)]
    cache = _slice_layers_repaired(shape, zs)
    return [(z, cache[z]) for z in zs]


def _classify_outer_seg(shape, seg):
    """外环段分类: const(常截面 Extrude) / cone(圆变径 Revolve) / vary(细分)。"""
    z_bot, z_top = seg["z_bot"], seg["z_top"]
    if z_top - z_bot < SAMPLE_STEP * 1.5:
        return "const"
    layers = _layers_of(shape, z_bot, z_top)
    # 全圆 → 检查线性变径（锥面）
    all_circ = True
    rs, zs_ = [], []
    for z, loops in layers:
        big = max(loops, key=_loop_area) if loops else None
        if (
            big is None
            or len(big) != 1
            or big[0]["type"] != "circle"
            or not big[0]["full"]
        ):
            all_circ = False
            break
        rs.append(big[0]["r"])
        zs_.append(z)
    if all_circ and len(rs) >= 3:
        # 线性拟合 r = a*z + b
        n = len(zs_)
        sz = sum(zs_)
        sr = sum(rs)
        szz = sum(z * z for z in zs_)
        szr = sum(z * r for z, r in zip(zs_, rs))
        den = n * szz - sz * sz
        a = (n * szr - sz * sr) / den if abs(den) > 1e-9 else 0.0
        b = (sr - a * sz) / n
        max_res = max(abs(r - (a * z + b)) for z, r in zip(zs_, rs))
        if max_res < 0.15:
            return "cone" if abs(a) > 0.02 else "const"
    # 层间签名全同 → 常截面
    sigs = set()
    for z, loops in layers:
        if not loops:
            return "vary"
        big = max(loops, key=_loop_area)
        sigs.add(_loop_signature(big))
        if len(sigs) > 1:
            return "vary"
    return "const"


# ============================================================
# SW 特征建模
# ============================================================


def _sketch_loop(driver, loop, no_snap=False):
    """在活动草图中绘制闭合环。

    草图平面为偏移基准面（XY 平行面），草图坐标直接使用 CSG 截面
    (x, y)——z 方向的 shift 抬高只通过基准面偏移实现，不得加到草图 y
    （实测: 加 shift 导致整个挤压/切除实体沿 y 偏移 48.5mm，与锥面
    Revolve 段错位、模型分离）。

    SW2025 实测规则: CreateArc 的端点与已有草图实体（线）端点重合时
    弧会退化为无效段（GetType=0）导致草图开环、拉伸失败；
    而线端点与已有弧端点重合无此问题。
    因此分两遍绘制: 先画所有弧（弧端点互不重合），再画所有线。

    no_snap=True 时线/弧绘制用 SetAddToDB 绕过草图推理捕捉
    （实测 SW2025）: 键槽矩形角部距 r8.5 截面圆边仅 0.04mm，落在
    捕捉范围内，线端点被吸附到圆边 → 草图环畸变 → FeatureCut3 返回
    None（圆草图无端点、不受影响）。SetAddToDB 直接写数据库、坐标
    精确；退出草图时 SW 求解器自动合并重合端点（实测切除体积
    ΔV=10.07 vs 理论 10.08）。
    ⚠️ SetAddToDB 模式线端点不自动合并，多线环会开环 → 拉伸失败
    （Boss2-5 八边环实测），因此 boss 草图必须保持 no_snap=False。
    """
    if len(loop) == 1 and loop[0]["type"] == "circle" and loop[0]["full"]:
        c = loop[0]
        driver.draw_circle(c["cx"], c["cy"], 0.0, c["r"])
        return

    def _draw():
        # 第一遍: 弧
        for e in loop:
            if e["type"] == "circle":
                # 非整圆弧: CreateArc 圆心+起止点+方向（劣弧，方向由几何端点判定）
                clockwise = _arc_dir(e)
                driver.draw_arc(
                    e["cx"],
                    e["cy"],
                    0.0,
                    e["p0"][0],
                    e["p0"][1],
                    0.0,
                    e["p1"][0],
                    e["p1"][1],
                    0.0,
                    clockwise,
                )
        # 第二遍: 线（含 poly 采样折线兜底）
        for e in loop:
            if e["type"] == "line":
                driver.draw_line(
                    e["p0"][0], e["p0"][1], 0.0, e["p1"][0], e["p1"][1], 0.0
                )
            elif e["type"] == "poly":
                for i in range(len(e["pts"]) - 1):
                    driver.draw_line(
                        e["pts"][i][0],
                        e["pts"][i][1],
                        0.0,
                        e["pts"][i + 1][0],
                        e["pts"][i + 1][1],
                        0.0,
                    )

    if no_snap:
        driver.sw_model.SetAddToDB(True)
        try:
            _draw()
        finally:
            driver.sw_model.SetAddToDB(False)
    else:
        _draw()


def _seg_bottom_in_solid(shape, seg, probe=0.15):
    """孔段底部下方 0.15mm 处中心点是否在 CSG 实体内。

    用于区分盲孔(孔底在实体内, 微缩防分离)与台阶孔链
    (孔底下方是空腔, 微超打开孔口)。BRepClass3d_SolidClassifier
    直接对 3D 实体分类, 不受截面环材料性歧义影响。
    """
    loop = seg["loop"]
    if len(loop) == 1 and loop[0]["type"] == "circle":
        cx, cy = loop[0]["cx"], loop[0]["cy"]
    else:
        pts = [e["p0"] for e in loop if e["type"] != "circle"]
        if not pts:
            return False
        cx = sum(p[0] for p in pts) / len(pts)
        cy = sum(p[1] for p in pts) / len(pts)
    cls = BRepClass3d_SolidClassifier(shape)
    cls.Perform(gp_Pnt(cx, cy, seg["z_bot"] - probe), 1e-4)
    return cls.State() == TopAbs_IN


def _build_sw_model(driver, shape, outer_segs, hole_segs, shift):
    """SW 特征建模: 凸台序列自底向上 → 孔切除。返回特征计数统计。

    seg["kind"] 由主流程预计算缓存: const / cone / vary。
    """
    feat_stats = {"boss": 0, "cut": 0, "revolve": 0}
    # 偏移基准面缓存: 同一 (基准面, 偏移量) 只创建一次。
    # SW 同名基准面重复创建会导致 SelectByID2 选择错乱、FeatureCut3 返回
    # None（实测: 第 3 个同名 PH10.0 上切除失败），必须复用。
    plane_cache = {}

    def _get_plane(driver, offset, name):
        key = round(offset, 2)
        if key in plane_cache:
            return plane_cache[key]
        if not driver.create_ref_plane_offset("前视基准面", offset, name):
            return None
        plane_cache[key] = name
        return name

    def _boss_seg(seg, idx):
        """单个凸台段: 锥面 Revolve / 常截面 Extrude / vary 细分。"""
        z_bot, z_top, loop = seg["z_bot"], seg["z_top"], seg["loop"]
        h = z_top - z_bot
        if h <= 0.01:
            return True
        kind = seg.get("kind", "const")
        if kind == "cone":
            # 锥面旋转凸台: 前视基准面母线草图（环为圆，半径线性变化）
            r_bot, r_top = seg["r_bot"], seg["r_top"]
            if not driver.start_sketch("前视基准面"):
                return False
            driver.draw_centerline(0.0, z_bot + shift, 0.0, 0.0, z_top + shift, 0.0)
            driver.draw_line(r_bot, z_bot + shift, 0.0, r_top, z_top + shift, 0.0)
            driver.draw_line(r_top, z_top + shift, 0.0, 0.0, z_top + shift, 0.0)
            driver.draw_line(0.0, z_top + shift, 0.0, 0.0, z_bot + shift, 0.0)
            driver.draw_line(0.0, z_bot + shift, 0.0, r_bot, z_bot + shift, 0.0)
            if not driver.feature_revolve(
                360.0, is_cut=False, feat_name=f"Revolve-Cone{idx}"
            ):
                return False
            feat_stats["revolve"] += 1
            print(
                f"  锥面旋转凸台 z[{z_bot:.1f}~{z_top:.1f}] r[{r_bot:.1f}→{r_top:.1f}]"
            )
            return True
        if kind == "vary":
            # 兜底: 逐层薄拉伸（0.5mm 台阶近似过渡段）
            print(
                f"  [WARN] 过渡段 z[{z_bot:.1f}~{z_top:.1f}] 签名渐变，"
                f"细分 {int(round(h / SAMPLE_STEP))} 层薄拉伸"
            )
            n = max(1, int(round(h / SAMPLE_STEP)))
            for i in range(n):
                zb = z_bot + i * SAMPLE_STEP
                zt = min(z_bot + (i + 1) * SAMPLE_STEP, z_top)
                loops = _slice_loops(shape, zb)
                if not loops:
                    continue
                lay_loop = max(loops, key=_loop_area)
                if not _boss_extrude(
                    driver, zb, zt, lay_loop, shift, idx, feat_stats, sub=i
                ):
                    return False
            return True
        return _boss_extrude(driver, z_bot, z_top, loop, shift, idx, feat_stats)

    def _boss_extrude(driver, z_bot, z_top, loop, shift, idx, stats, sub=None):
        """常截面拉伸凸台: 偏移基准面(z_bot)草图 + FeatureExtrusion2。"""
        h = z_top - z_bot
        name = f"BossExtrude{idx}" + (f"_{sub}" if sub is not None else "")
        plane = _get_plane(driver, z_bot + shift, f"PZ{z_bot + shift:.1f}")
        if not plane or not driver.start_sketch(plane):
            return False
        _sketch_loop(driver, loop)
        if not driver.feature_boss_extrude(h, feat_name=name):
            return False
        stats["boss"] += 1
        print(
            f"  凸台拉伸 {name} z[{z_bot:.1f}~{z_top:.1f}] h={h:.2f}mm ({len(loop)} 边)"
        )
        return True

    # 凸台段按 z_bot 升序
    for i, seg in enumerate(sorted(outer_segs, key=lambda s: s["z_bot"])):
        if not _boss_seg(seg, i + 1):
            return None

    # 孔段处理: cut 草图在 z_top 平面向下切（含 0.1mm 微余量）；
    # boss（材料岛）草图在 z_bot 平面向上拉。
    # ⚠️ SW 限制（实测）: 同一基准面上第 3 个 FeatureCut3 起返回 None，
    # 因此同 z_top 的连续 cut 段必须合并为一个多轮廓草图一次切除。
    segs = sorted(hole_segs, key=lambda s: s["z_top"])
    feat_idx = 0
    i = 0
    while i < len(segs):
        seg = segs[i]
        z_bot, z_top, loop = seg["z_bot"], seg["z_top"], seg["loop"]
        depth = z_top - z_bot
        if depth <= 0.01:
            i += 1
            continue
        if seg.get("kind") == "boss":
            feat_idx += 1
            plane = _get_plane(driver, z_bot + shift, f"PB{z_bot + shift:.1f}")
            if not plane or not driver.start_sketch(plane):
                return None
            _sketch_loop(driver, loop)
            if not driver.feature_boss_extrude(depth, feat_name=f"Island{feat_idx}"):
                return None
            feat_stats["boss"] += 1
            print(
                f"  材料岛 Island{feat_idx} z[{z_bot:.1f}~{z_top:.1f}] "
                f"h={depth:.1f}mm (环 {len(loop)} 边)"
            )
            i += 1
            continue
        # 收集同 z_top 的连续 cut 段 → 合并多轮廓草图
        batch = [seg]
        j = i + 1
        while (
            j < len(segs)
            and segs[j].get("kind") != "boss"
            and abs(segs[j]["z_top"] - z_top) < 0.26
        ):
            batch.append(segs[j])
            j += 1
        feat_idx += 1
        plane = _get_plane(driver, z_top + shift, f"PH{z_top + shift:.1f}")
        if not plane or not driver.start_sketch(plane):
            return None
        for s in batch:
            # 孔切除草图必须 no_snap（键槽矩形近截面边会被捕捉畸变）
            _sketch_loop(driver, s["loop"], no_snap=True)
        depth = max(s["z_top"] - s["z_bot"] for s in batch)
        # ⚠️ flip 必须为 False（实测 SW2025 面级验证）:
        #   flip=True 时 SW 会把「实体截面轮廓」与草图圆组合成异常轮廓
        #   （同心 → 切环带 r孔~r体；包含 → 切截面盘挖孔），切除量远超
        #   预期（法兰孔切除把整个法兰盘切空）。
        #   flip=False 向下切、只切草图轮廓，行为正确。
        # ⚠️ 孔深微缩 0.1mm: SW 实测孔底与特征接触面共面(或微越界)时
        # 会把合并实体切成分离块（顶段 4 孔深 9.1 → 实体 1→2），
        # 微缩使孔底高于接触面规避共面切除。
        # ⚠️ 孔底开口判据（三种情况）:
        #   (1) 通孔(孔底 = 实体底面): 微超 0.05mm 切穿 — 微缩会让
        #       通孔底部留 0.1mm 皮，把底面开口(r25 中心孔、4 定位
        #       角孔)整个封住。贯穿切除 SW 自动截断到实体边界。
        #   (2) 台阶孔链(孔底下方是空腔): 微超 0.05mm 打开孔口 —
        #       r21 孔底落在 r25 孔腔顶台阶面上、孔口朝外，微缩
        #       会在台阶面上留 0.1mm 皮把下一级圆环结构封住
        #       （用户验收: "还有一个面封着"）。
        #   (3) 盲孔(孔底在实体内): 保持微缩防共面分离，皮在
        #       实体内部不可见。
        zmin_csg = -shift
        if all(s["z_bot"] <= zmin_csg + 0.05 for s in batch):
            cut_depth = depth + 0.05
        elif all(_seg_bottom_in_solid(shape, s) for s in batch):
            cut_depth = depth - 0.1
        else:
            cut_depth = depth + 0.05
        if not driver.feature_cut_extrude(
            cut_depth, feat_name=f"CutExtrude{feat_idx}", flip=False
        ):
            return None
        feat_stats["cut"] += 1
        print(
            f"  孔切除 CutExtrude{feat_idx} z[~{z_top:.1f}] "
            f"d={depth:.1f}mm ({len(batch)} 轮廓)"
        )
        i = j
    return feat_stats


# ============================================================
# 主流程
# ============================================================


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    flags = [a for a in sys.argv[1:] if a.startswith("--")]
    if not args:
        print(__doc__)
        sys.exit(1)
    dxf_path = args[0]
    if not Path(dxf_path).exists():
        print(f"[FAIL] 文件不存在: {dxf_path}")
        sys.exit(1)

    input_dir = Path(dxf_path).parent
    input_stem = Path(dxf_path).stem
    step_path = str(input_dir / f"{input_stem}_3d.step")
    no_step = "--no-step" in flags
    if len(args) >= 2:
        output_sldprt = args[1]
    else:
        from datetime import datetime

        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_sldprt = str(input_dir / f"{input_stem}_features_{ts}.sldprt")

    print("=" * 60)
    print("通用 DXF → SW 原生特征模型转换器 v0.6.13")
    print("=" * 60)
    print(f"  输入: {dxf_path}")
    print(f"  输出: {output_sldprt}")

    # ---- 第 1 阶段: 复用 CSG 重建得到精确实体 ----
    print("\n[1/3] CSG 重建（复用 dxf_to_3d_general）...")
    combined = convert_dxf_to_3d(dxf_path, step_output=None if no_step else step_path)
    if combined is None:
        print("[FAIL] CSG 重建失败")
        sys.exit(1)

    # ---- 第 2 阶段: z 切片特征识别 ----
    print(f"\n[2/3] z 切片特征识别（步长 {SAMPLE_STEP}mm）...")
    bb = Bnd_Box()
    brepbndlib.Add(combined, bb)
    x1, y1, z1, x2, y2, z2 = bb.Get()
    print(
        f"  实体 bbox: X[{x1:.1f}~{x2:.1f}] Y[{y1:.1f}~{y2:.1f}] Z[{z1:.1f}~{z2:.1f}]"
    )
    outer_segs, hole_segs = _track_segments(combined, z1, z2)
    print(f"  外环段: {len(outer_segs)} 个")
    for s in outer_segs:
        print(
            f"    z[{s['z_bot']:8.1f}~{s['z_top']:8.1f}] "
            f"h={s['z_top'] - s['z_bot']:5.1f}mm 边数={len(s['loop'])}"
        )
    print(f"  孔段: {len(hole_segs)} 个")
    for s in hole_segs:
        print(
            f"    z[{s['z_bot']:8.1f}~{s['z_top']:8.1f}] "
            f"h={s['z_top'] - s['z_bot']:5.1f}mm 边数={len(s['loop'])}"
        )

    # 段分类预计算（缓存 seg["kind"]，锥段补 r_bot/r_top）
    for seg in outer_segs:
        kind = _classify_outer_seg(combined, seg)
        seg["kind"] = kind
        if kind == "cone":
            layers = _layers_of(combined, seg["z_bot"], seg["z_top"])
            rs = [max(ls, key=_loop_area)[0]["r"] for _, ls in layers if ls]
            seg["r_bot"] = rs[0]
            seg["r_top"] = rs[-1]

    # ---- 第 3 阶段: SW 特征建模 ----
    print("\n[3/3] SW 特征建模 ...")
    shift = -z1  # 抬高使底 = 0
    driver = SolidWorksDriver()
    try:
        driver.connect()
        if not driver.new_part():
            print("[FAIL] SW 新建零件失败")
            sys.exit(1)
        stats = _build_sw_model(driver, combined, outer_segs, hole_segs, shift)
        if stats is None:
            print("[FAIL] 特征建模失败")
            sys.exit(1)
        driver.rebuild()
        driver.zoom_to_fit()
        if not driver.save_as(output_sldprt):
            print("[FAIL] 保存失败")
            sys.exit(1)
    finally:
        driver.disconnect()

    print("\n" + "=" * 60)
    print(f"[OK] 特征模型完成: {output_sldprt}")
    print(
        f"  特征统计: 凸台拉伸 {stats['boss']} / 旋转凸台 "
        f"{stats['revolve']} / 切除 {stats['cut']} "
        f"(共 {sum(stats.values())} 个可编辑特征)"
    )
    print("  对比验证: SW 中打开该模型确认特征树;")
    if not no_step:
        print(f"  STEP 基准: {step_path}")
    print("=" * 60)


if __name__ == "__main__":
    main()
