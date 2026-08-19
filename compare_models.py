#!/usr/bin/env python
"""闭环验证对比: 基准 STEP vs 重建 STEP 定量差异分析。

对比项:
  1. 体积 / bbox / 实体数（各自测量）
  2. 布尔差: 基准-重建（多余材料）与 重建-基准（缺失材料）的体积
  3. 重建相对基准的包容率: 交集体积 / 基准体积

用法:
    python compare_models.py 基准.step 重建.step
    python compare_models.py --dz 21.95 基准.step 重建.step           # z 平移对齐
    python compare_models.py --dz 21.95 --split -5,0,56.5 基准.step 重建.step  # 逐段拆分

健壮性说明（v0.6.10 后实测教训）:
  - bbox 测的是实体材料域（逐层 Common 扫描取并），不是原始 Bnd_Box。
    SW 导出 STEP 常含零厚度悬挂面片/游离顶点（PF60K 基准 bbox 80×80
    系此类伪影，实体域截面仅 60×60），原始 bbox 会虚胖。两者差异 >0.5mm
    时打印提示。
  - 主布尔差逐 solid 求交，IsDone 校验 + ShapeFix 重试一次，仍失败的
    个体跳过并警告（整体一次 Cut 对含退化子形状的复合体可能静默失败
    返回错误结果）。
  - SolidClassifier 对含退化拓扑的实体不可靠（锥面附近曾误报 IN），
    勿用于本工具的结构判定；逐层 Common 体积才是地面真值。
"""

import sys

from OCC.Core.STEPControl import STEPControl_Reader
from OCC.Core.GProp import GProp_GProps
from OCC.Core.BRepGProp import brepgprop
from OCC.Core.Bnd import Bnd_Box
from OCC.Core.BRepBndLib import brepbndlib
from OCC.Core.BRepAlgoAPI import BRepAlgoAPI_Cut, BRepAlgoAPI_Common, \
    BRepAlgoAPI_Fuse
from OCC.Core.BRepPrimAPI import BRepPrimAPI_MakeBox
from OCC.Core.BRep import BRep_Builder
from OCC.Core.TopoDS import TopoDS_Compound
from OCC.Core.gp import gp_Pnt
from OCC.Core.TopExp import TopExp_Explorer
from OCC.Core.TopAbs import TopAbs_SOLID
from OCC.Core.ShapeFix import ShapeFix_Shape


def _read(path):
    r = STEPControl_Reader()
    if r.ReadFile(path) != 1:
        raise RuntimeError(f"读取失败: {path}")
    r.TransferRoots()
    return r.OneShape()


def _solids(shape):
    """遍历 shape 内所有 SOLID（空/退化返回 []）。"""
    exp = TopExp_Explorer(shape, TopAbs_SOLID)
    out = []
    while exp.More():
        out.append(exp.Current())
        exp.Next()
    return out


def _fuse_all(shape):
    """所有 solid 求并集（Fuse 链）。

    重叠实体的 STEP（SW 导出同一模型拆成多个互相包含的 solid，bracket
    基准 solid1 完全在 solid0 内）直接逐 solid 布尔会产生双计伪值：
    Common 逐对总和可以大于单个输入的体积。并集是唯一真实的材料域。
    """
    ss = _solids(shape)
    if len(ss) <= 1:
        return shape
    acc = ss[0]
    for s in ss[1:]:
        op = BRepAlgoAPI_Fuse(acc, s)
        op.Build()
        if not op.IsDone():
            fx = ShapeFix_Shape(acc)
            fx.Perform()
            op = BRepAlgoAPI_Fuse(fx.Shape(), s)
            op.Build()
        if not op.IsDone():
            print("  [警告] 基准并集 Fuse 失败，保留未融合形状")
            return shape
        acc = op.Shape()
    return acc


def _solid_vol(shape):
    """逐 SOLID 统计体积：空 shape 与退化结果（非 solid）不计。"""
    v = 0.0
    for s in _solids(shape):
        p = GProp_GProps()
        brepgprop.VolumeProperties(s, p)
        v += p.Mass()
    return v


def _material_bbox(shape, step=0.5):
    """实体材料域 bbox：逐层 Common 扫描后取并。

    原始 Bnd_Box 会把零厚度悬挂面片/游离顶点计入（SW 导出 STEP 伪影），
    逐层 Common 只保留实体材料，故以各层材料 bbox 的并集为准。
    返回 (材料域 bbox, 原始 bbox)，无实体材料时材料域为 None。
    """
    raw = Bnd_Box()
    brepbndlib.Add(shape, raw)
    if raw.IsVoid():
        return None, raw
    x1, y1, z1, x2, y2, z2 = raw.Get()
    bb = Bnd_Box()
    for s in _solids(shape):
        z0 = z1
        while z0 < z2 - 1e-9:
            box = BRepPrimAPI_MakeBox(
                gp_Pnt(x1 - 1, y1 - 1, z0),
                gp_Pnt(x2 + 1, y2 + 1, min(z0 + step, z2)),
            ).Shape()
            op = BRepAlgoAPI_Common(s, box)
            op.Build()
            if op.IsDone() and _solid_vol(op.Shape()) > 1e-6:
                brepbndlib.Add(op.Shape(), bb)
            z0 += step
    if bb.IsVoid():
        return None, raw
    return bb, raw


def _bbox_str(bb):
    if bb is None:
        return None
    x1, y1, z1, x2, y2, z2 = bb.Get()
    return tuple(f"{v:.2f}" for v in (x2 - x1, y2 - y1, z2 - z1))


def _measure(shape):
    props = GProp_GProps()
    brepgprop.VolumeProperties(shape, props)
    bb, raw = _material_bbox(shape)
    return props.Mass(), bb, raw, len(_solids(shape))


def _try_bool(a_solid, b_solid, cut, label):
    """solid×solid 布尔：IsDone 校验 + ShapeFix 重试一次。

    返回结果 solid 列表；失败返回 None（跳过并警告）。
    """
    op = (BRepAlgoAPI_Cut if cut else BRepAlgoAPI_Common)(a_solid, b_solid)
    op.Build()
    if not op.IsDone():
        fx = ShapeFix_Shape(a_solid)
        fx.Perform()
        op = (BRepAlgoAPI_Cut if cut else BRepAlgoAPI_Common)(fx.Shape(), b_solid)
        op.Build()
    if not op.IsDone():
        print(f"  [警告] {label}: 实体布尔运算失败已跳过")
        return None
    return _solids(op.Shape())


def _bool_shape(a, b, cut, label):
    """a 与 b 的布尔结果，合并为 compound。

    cut=True: a - b（a 各 solid 依次被 b 各 solid 切——多实体 compound
      整体作为刀具会静默失效，PF60K 实测剩 65,677 假多余）；cut=False:
      a ∩ b（两两求交取并）。
    全部 solid×solid 求交，IsDone 校验 + ShapeFix 重试一次。
    """
    builder = BRep_Builder()
    compound = TopoDS_Compound()
    builder.MakeCompound(compound)
    b_solids = _solids(b)
    for s in _solids(a):
        if cut:
            cur = [s]
            for bt in b_solids:
                nxt = []
                for cs in cur:
                    res = _try_bool(cs, bt, True, label)
                    if res is not None:
                        nxt.extend(res)
                cur = nxt
                if not cur:
                    break
            for cs in cur:
                builder.Add(compound, cs)
        else:
            for bt in b_solids:
                res = _try_bool(s, bt, False, label)
                if res is not None:
                    for r in res:
                        builder.Add(compound, r)
    return compound


def main() -> int:
    # 参数: [--dz <毫米>] [--dx <毫米>] [--dy <毫米>] [--split <z1,z2,...>] 基准.step 重建.step
    args = sys.argv[1:]
    dz = 0.0
    dx = 0.0
    dy = 0.0
    split_zs = None
    while args and args[0].startswith("--"):
        flag = args.pop(0)
        if flag == "--dz":
            dz = float(args.pop(0))
        elif flag == "--dx":
            dx = float(args.pop(0))
        elif flag == "--dy":
            dy = float(args.pop(0))
        elif flag == "--split":
            split_zs = [float(v) for v in args.pop(0).split(",")]
        else:
            print(__doc__)
            return 1
    if len(args) < 2:
        print(__doc__)
        return 1
    base_raw = _read(args[0])
    recon_raw = _read(args[1])
    # v0.6.14: 重叠实体并集归一——逐 solid 布尔对重叠基准双计
    # （bracket 基准 3 solid 相互包含，Common 总和 > 重建体积）
    base = _fuse_all(base_raw)
    recon = _fuse_all(recon_raw)
    _bn_raw = len(_solids(base_raw))
    if _bn_raw > 1 and _bn_raw != len(_solids(base)):
        print(f"[提示] 基准 {_bn_raw} 实体已并集归一（含重叠，逐 solid 布尔会双计）")
    _rn_raw = len(_solids(recon_raw))
    if _rn_raw > 1 and _rn_raw != len(_solids(recon)):
        print(f"[提示] 重建 {_rn_raw} 实体已并集归一")

    bv, bb, braw, bn = _measure(base)
    rv, rb, rraw, rn = _measure(recon)
    print(f"基准 {args[0]}:")
    print(f"  体积={bv:.2f} bbox={_bbox_str(bb)} 实体={bn}")
    print(f"重建 {args[1]} (平移 dx={dx:+.2f} dy={dy:+.2f} dz={dz:+.2f} 对齐):")
    print(f"  体积={rv:.2f} bbox={_bbox_str(rb)} 实体={rn}")
    for name, mat, raw in (("基准", bb, braw), ("重建", rb, rraw)):
        if mat is not None and raw is not None:
            m = _bbox_str(mat)
            r = _bbox_str(raw)
            if any(abs(float(a) - float(c)) > 0.5 for a, c in zip(m, r)):
                print(f"  [提示] {name} 原始 bbox={r} 含零厚度悬挂面片/游离顶点伪影，材料域 bbox={m}")
    print(f"  体积差 = {rv - bv:+.2f} ({(rv - bv) / bv * 100:+.2f}%)")

    # z 平移对齐（重建系 → 基准系）
    from OCC.Core.gp import gp_Trsf, gp_Vec
    from OCC.Core.TopLoc import TopLoc_Location

    trsf = gp_Trsf()
    trsf.SetTranslation(gp_Vec(dx, dy, dz))
    recon_t = recon.Moved(TopLoc_Location(trsf))

    # 布尔差（逐 solid + IsDone 校验；零厚度伪影不贡献体积，无需预清理）
    extra = _bool_shape(recon_t, base, True, "多余材料")
    missing = _bool_shape(base, recon_t, True, "缺失材料")
    common = _bool_shape(base, recon_t, False, "交集体积")
    ev = _solid_vol(extra)
    mv = _solid_vol(missing)
    cv = _solid_vol(common)
    print(f"  多余材料(重建-基准) = {ev:.2f}")
    print(f"  缺失材料(基准-重建) = {mv:.2f}")
    print(f"  交集体积 = {cv:.2f} (交集/基准 = {cv / bv * 100:.1f}%)")

    # 按 z 段拆分多余/缺失材料（z 为基准系坐标）
    if split_zs:
        bx = bb if bb is not None else braw
        x1, y1, z1, x2, y2, z2 = bx.Get()
        print("\n逐段对比 (z 基准系):")
        edges = [z1] + sorted(split_zs) + [z2]
        for i in range(len(edges) - 1):
            box = BRepPrimAPI_MakeBox(
                gp_Pnt(x1 - 1, y1 - 1, edges[i]),
                gp_Pnt(x2 + 1, y2 + 1, edges[i + 1]),
            ).Shape()
            # 逐 solid 求交：Common 对含退化子形状的复合体可能失败
            # 并原样返回 box（体积 = box 全域）——IsDone 校验 +
            # 体积上限兜底归零；失败个体经 ShapeFix 重试一次
            box_vol = (x2 - x1 + 2) * (y2 - y1 + 2) * (edges[i + 1] - edges[i])

            def _seg_vol(shape):
                if shape.IsNull():
                    return 0.0
                total = 0.0
                for s in _solids(shape):
                    op = BRepAlgoAPI_Common(s, box)
                    op.Build()
                    if not op.IsDone():
                        fx = ShapeFix_Shape(s)
                        fx.Perform()
                        op = BRepAlgoAPI_Common(fx.Shape(), box)
                        op.Build()
                    if op.IsDone():
                        v = _solid_vol(op.Shape())
                        if v < box_vol * 0.999:
                            total += v
                return total

            ev2 = _seg_vol(extra)
            mv2 = _seg_vol(missing)
            print(f"  z[{edges[i]:8.2f}, {edges[i + 1]:8.2f}]: 多余={ev2:+9.1f}  缺失={mv2:+9.1f}  净={ev2 - mv2:+9.1f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
