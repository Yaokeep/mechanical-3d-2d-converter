# -*- coding: utf-8 -*-
"""图纸粗实线 vs 模型 HLR 可见轮廓：最近距离核对（无基准验收第二件后半）。

模型侧 = CAD/temp_output/_yz_hlr.json（yz_hlr.py 生成，原始 u,v）。
每视图自动搜索 (su, sv) 符号使"缺失"最少（消解镜像/方向歧义），然后列出：
  缺 = 图纸有、模型无（seg 的 7 采样点全部 > thresh）
  多 = 模型有、图纸无（反方向）
用法: python yz_match.py [thresh_mm] [视图名] [hlr.json]
总入口见 yz_accept.py（三件套一起跑 + 基线判红）。

v2（2026-10-04）：补 SPLINE / LWPOLYLINE 支持——此前只读 LINE/ARC/CIRCLE，
图纸腔底的样条（SPLINE 粗实线）完全不参与评分（"缺"判不出、v9 的样条
被误判为"多"）。SPLINE 用 flattening(0.5) 离散成短段；LWPOLYLINE 经
virtual_entities 分解（含 bulge 弧）。
"""
import sys
import json

import numpy as np
import ezdxf

COARSE = ("粗实线",)
# "多"参考集：细实线=过渡线；4虚线层=图纸虚线（隐藏边）——模型边与其中任一
# 重合即有图纸依据，不算"多"（图纸 TR 右半 +50 腔壁就是虚线画的）。
FINE = ("细实线", "4虚线层")

# 名: (su 候选, sv 候选, 偏移 ox oy, 窗口)
VIEWS = {
    "TL": ([(1, 2650.80)], [(1, 1541.25)], (2650.80, 1541.25), (2380, 2960, 1500, 1780)),
    "BL": ([(1, 2650.80), (-1, 2650.80)], [(1, 1054.80), (-1, 1054.80)],
           (2650.80, 1054.80), (2400, 2900, 830, 1280)),
    "TR": ([(1, 3462.94), (-1, 3462.94)], [(-1, 1541.25), (1, 1541.25)],
           (3462.94, 1541.25), (3255, 3690, 1500, 1780)),
    # C—C 反方向备选（yz_hlr.py 的 TRW 键）——只作评分对照
    "TRW": ([(1, 3462.94), (-1, 3462.94)], [(-1, 1541.25), (1, 1541.25)],
            (3462.94, 1541.25), (3255, 3690, 1500, 1780)),
    # DR = 右下大拱视图（从东 +X 看；HLR 投影 N=(1,0,0)/Vx=(0,1,0) 给 u=y, v=+z）
    "DR": ([(1, 3462.94), (-1, 3462.94)], [(1, 896.09), (-1, 896.09)],
           (3462.94, 896.09), (3240, 3690, 860, 1100)),
}


def load_dwg(dwg_path: str):
    """读图纸模型空间 → (粗实线段集, 粗+细段集)。每段 (x0,y0,x1,y1)。"""
    msp = ezdxf.readfile(dwg_path).modelspace()
    dwg, dwg_all = [], []
    for e in msp:
        if e.dxf.layer not in COARSE + FINE:
            continue
        t = e.dxftype()
        try:
            if t == "LINE":
                s, q = e.dxf.start, e.dxf.end
                rec = (s.x, s.y, q.x, q.y)
                if e.dxf.layer in COARSE:
                    dwg.append(rec)
                dwg_all.append(rec)
            elif t in ("ARC", "CIRCLE"):
                c, r = e.dxf.center, e.dxf.radius
                if t == "ARC":
                    a0, a1 = e.dxf.start_angle, e.dxf.end_angle
                    # DXF 弧恒为逆时针 start->end：start>end 时补 360，
                    # 否则 linspace 会把 90° 弧错画成 270° 大弧
                    a1 = a0 + ((a1 - a0) % 360.0 or 360.0)
                else:
                    a0, a1 = 0.0, 360.0
                a = np.radians(np.linspace(a0, a1, 17))
                xs, ys = c.x + r * np.cos(a), c.y + r * np.sin(a)
                for i in range(len(xs) - 1):
                    rec = (xs[i], ys[i], xs[i + 1], ys[i + 1])
                    if e.dxf.layer in COARSE:
                        dwg.append(rec)
                    dwg_all.append(rec)
            elif t == "SPLINE":
                pts = [(p.x, p.y) for p in e.flattening(0.5)]
                for i in range(len(pts) - 1):
                    rec = (pts[i][0], pts[i][1], pts[i + 1][0], pts[i + 1][1])
                    if e.dxf.layer in COARSE:
                        dwg.append(rec)
                    dwg_all.append(rec)
            elif t == "LWPOLYLINE":
                # 分解为 LINE/ARC（virtual_entities 处理 bulge），逐段计入
                for sub in e.virtual_entities():
                    st = sub.dxftype()
                    if st == "LINE":
                        s, q = sub.dxf.start, sub.dxf.end
                        rec = (s.x, s.y, q.x, q.y)
                        if e.dxf.layer in COARSE:
                            dwg.append(rec)
                        dwg_all.append(rec)
                    elif st == "ARC":
                        c, r = sub.dxf.center, sub.dxf.radius
                        a0, a1 = sub.dxf.start_angle, sub.dxf.end_angle
                        a1 = a0 + ((a1 - a0) % 360.0 or 360.0)
                        a = np.radians(np.linspace(a0, a1, 17))
                        xs, ys = c.x + r * np.cos(a), c.y + r * np.sin(a)
                        for i in range(len(xs) - 1):
                            rec = (xs[i], ys[i], xs[i + 1], ys[i + 1])
                            if e.dxf.layer in COARSE:
                                dwg.append(rec)
                            dwg_all.append(rec)
        except Exception:
            pass
    return np.array(dwg), np.array(dwg_all)


def min_dist_pts(P, A, B, block=400):
    """P (N,2) 到线段集 A-B (M,2) 的最小距离，向量化分块。"""
    out = np.full(len(P), 1e9)
    AB = B - A
    L2 = (AB * AB).sum(-1)
    L2[L2 == 0] = 1e-12
    for i in range(0, len(P), block):
        Pb = P[i:i + block][:, None, :]
        t = ((Pb - A[None]) * AB[None]).sum(-1) / L2[None]
        t = np.clip(t, 0, 1)
        proj = A[None] + t[:, :, None] * AB[None]
        out[i:i + block] = np.sqrt(((Pb - proj) ** 2).sum(-1)).min(1)
    return out


def samples_of(segs, n=7):
    S = np.array(segs)
    return np.vstack([S[:, :2] + k * (S[:, 2:] - S[:, :2])
                      for k in np.linspace(0, 1, n)])


def run_match(thresh: float = 2.0, only: str | None = None,
              hlr_json: str = "CAD/temp_output/_yz_hlr.json",
              dwg_path: str = "CAD/temp_output/_yz.dxf",
              verbose: bool = True) -> dict:
    """对比 HLR JSON 与图纸 → {视图名: (缺段数, 多段数)}。"""
    hlr = json.load(open(hlr_json, encoding="utf-8"))
    dwg, dwg_all = load_dwg(dwg_path)
    if verbose:
        print(f"图纸粗实线 {len(dwg)} 段（离散后）；粗+细 {len(dwg_all)} 段")

    result = {}
    for name, (sus, svs, (ox, oy), W) in VIEWS.items():
        if only and name != only:
            continue
        # 图纸窗口内段
        cx = (dwg[:, 0] + dwg[:, 2]) / 2
        cy = (dwg[:, 1] + dwg[:, 3]) / 2
        sel = (cx >= W[0]) & (cx <= W[1]) & (cy >= W[2]) & (cy <= W[3])
        d = dwg[sel]
        if len(d) == 0:
            if verbose:
                print(f"[{name}] 窗口内无粗实线")
            result[name] = (0, 0)
            continue
        dsmp = samples_of(d)
        # "多"判据参照集：粗+细（窗口内）
        cxa = (dwg_all[:, 0] + dwg_all[:, 2]) / 2
        cya = (dwg_all[:, 1] + dwg_all[:, 3]) / 2
        sela = (cxa >= W[0]) & (cxa <= W[1]) & (cya >= W[2]) & (cya <= W[3])
        da = dwg_all[sela]
        if len(da) == 0:
            da = dwg_all

        best = None
        for su, ou in sus:
            for sv, ov in svs:
                # 模型段（映射到图纸坐标）
                msegs = []
                for poly in hlr[name]:
                    # 过滤人为切面边：TR 四分之一切除在 y=0 留下的切口轮廓（非零件特征）
                    if name == "TR" and all(abs(p[0]) < 0.02 for p in poly):
                        continue
                    pu = [su * p[0] + ou for p in poly]
                    pv = [sv * p[1] + ov for p in poly]
                    for i in range(len(poly) - 1):
                        msegs.append((pu[i], pv[i], pu[i + 1], pv[i + 1]))
                # 去重（HLR 同一条棱可能同时进 VCompound 与 OutLineVCompound）
                seen, mm = set(), []
                for s in msegs:
                    k = tuple(round(v, 2) for v in s)
                    if k in seen or (k[2], k[3], k[0], k[1]) in seen:
                        continue
                    seen.add(k)
                    mm.append(s)
                msegs = mm
                if not msegs:
                    continue
                MA = np.array([(s[0], s[1]) for s in msegs])
                MB = np.array([(s[2], s[3]) for s in msegs])
                mis = min_dist_pts(dsmp, MA, MB).reshape(7, len(d)).max(0)
                msmp = samples_of(msegs)
                ext = min_dist_pts(msmp, da[:, :2], da[:, 2:]).reshape(7, len(msegs)).max(0)
                nm, ne = int((mis > thresh).sum()), int((ext > thresh).sum())
                if verbose:
                    print(f"  [{name}] su={su} sv={sv}: 缺 {nm}/{len(d)}  多 {ne}/{len(msegs)}")
                key = (nm, ne)
                if best is None or key < best[0]:
                    best = (key, su, sv, msegs, mis, ne, ext, MA, MB)
        if best is None:
            result[name] = (0, 0)
            continue
        (nm, ne), su, sv, msegs, mis, ne2, ext, MA, MB = best
        result[name] = (nm, ne2)
        if verbose:
            print(f"[{name}] 选定 su={su} sv={sv}：缺 {nm} / 多 {ne2}")
            _show(d, mis, "缺", ox, oy, thresh)
            _show(msegs, ext, "多", ox, oy, thresh, topn=25)
    return result


def _show(segs, dist, label, ox, oy, thresh, topn=40):
    """打印超阈值段（连通合并成组），坐标换算到视图原点。"""
    bad = np.where(dist > thresh)[0]
    used = np.zeros(len(segs), bool)
    groups = []
    for i in bad:
        if used[i]:
            continue
        grp = [i]
        used[i] = True
        grown = True
        while grown:
            grown = False
            e1 = np.array([(segs[j][0], segs[j][1]) for j in grp] +
                          [(segs[j][2], segs[j][3]) for j in grp])
            for j in bad:
                if used[j]:
                    continue
                s = segs[j]
                e2 = np.array([(s[0], s[1]), (s[2], s[3])])
                dd = np.sqrt(((e1[:, None, :] - e2[None, :, :]) ** 2)
                             .sum(-1)).min()
                if dd < 1.0:
                    grp.append(j)
                    used[j] = True
                    grown = True
        groups.append(grp)
    for g in groups[:topn]:
        x0, y0 = segs[g[0]][0], segs[g[0]][1]
        x1, y1 = segs[g[-1]][2], segs[g[-1]][3]
        dm = max(dist[j] for j in g)
        print(f"  {label} ({x0 - ox:.2f},{y0 - oy:.2f})->({x1 - ox:.2f},{y1 - oy:.2f}) "
              f"{len(g)}段 maxd={dm:.1f}")
    if len(groups) > topn:
        print(f"  {label} ... 共 {len(groups)} 组")


def main() -> int:
    argv = sys.argv[1:]
    out_json = None
    if "--json" in argv:  # 机器可读输出 {视图: [缺, 多]}（yz_accept 两段式用）
        i = argv.index("--json")
        out_json = argv[i + 1]
        argv = argv[:i] + argv[i + 2:]
    thresh = float(argv[0]) if argv else 2.0
    only = argv[1] if len(argv) > 1 else None
    hlr_json = argv[2] if len(argv) > 2 else "CAD/temp_output/_yz_hlr.json"
    res = run_match(thresh, only, hlr_json, verbose=out_json is None)
    if out_json:
        json.dump(res, open(out_json, "w", encoding="utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
