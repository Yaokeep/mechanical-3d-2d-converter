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
"""

import sys

from OCC.Core.STEPControl import STEPControl_Reader
from OCC.Core.GProp import GProp_GProps
from OCC.Core.BRepGProp import brepgprop
from OCC.Core.Bnd import Bnd_Box
from OCC.Core.BRepBndLib import brepbndlib
from OCC.Core.BRepAlgoAPI import BRepAlgoAPI_Cut, BRepAlgoAPI_Common
from OCC.Core.TopExp import TopExp_Explorer
from OCC.Core.TopAbs import TopAbs_SOLID


def _read(path):
    r = STEPControl_Reader()
    if r.ReadFile(path) != 1:
        raise RuntimeError(f"读取失败: {path}")
    r.TransferRoots()
    return r.OneShape()


def _measure(shape):
    props = GProp_GProps()
    brepgprop.VolumeProperties(shape, props)
    bb = Bnd_Box()
    brepbndlib.Add(shape, bb)
    x1, y1, z1, x2, y2, z2 = bb.Get()
    exp = TopExp_Explorer(shape, TopAbs_SOLID)
    ns = 0
    while exp.More():
        ns += 1
        exp.Next()
    return props.Mass(), (x2 - x1, y2 - y1, z2 - z1), ns


def main() -> int:
    # 参数: [--dz <毫米>] [--split <z1,z2,...>] 基准.step 重建.step
    args = sys.argv[1:]
    dz = 0.0
    split_zs = None
    while args and args[0].startswith("--"):
        flag = args.pop(0)
        if flag == "--dz":
            dz = float(args.pop(0))
        elif flag == "--split":
            split_zs = [float(v) for v in args.pop(0).split(",")]
        else:
            print(__doc__)
            return 1
    if len(args) < 2:
        print(__doc__)
        return 1
    base = _read(args[0])
    recon = _read(args[1])

    bv, bb, bn = _measure(base)
    rv, rb, rn = _measure(recon)
    print(f"基准 {args[0]}:")
    print(f"  体积={bv:.2f} bbox={tuple(f'{x:.2f}' for x in bb)} 实体={bn}")
    print(f"重建 {args[1]} (z 平移 {dz:+.2f} 对齐):")
    print(f"  体积={rv:.2f} bbox={tuple(f'{x:.2f}' for x in rb)} 实体={rn}")

    # z 平移对齐（重建系 → 基准系）
    from OCC.Core.gp import gp_Trsf, gp_Vec
    from OCC.Core.TopLoc import TopLoc_Location

    trsf = gp_Trsf()
    trsf.SetTranslation(gp_Vec(0, 0, dz))
    recon_t = recon.Moved(TopLoc_Location(trsf))
    print(f"  体积差 = {rv - bv:+.2f} ({(rv - bv) / bv * 100:+.2f}%)")

    def _cut(a, b):
        op = BRepAlgoAPI_Cut(a, b)
        op.Build()
        return op.Shape()

    def _vol(s):
        p = GProp_GProps()
        brepgprop.VolumeProperties(s, p)
        return p.Mass()

    # 布尔差
    extra = _cut(recon_t, base)
    missing = _cut(base, recon_t)
    common = BRepAlgoAPI_Common(base, recon_t)
    common.Build()
    print(f"  多余材料(重建-基准) = {_vol(extra):.2f}")
    print(f"  缺失材料(基准-重建) = {_vol(missing):.2f}")
    print(f"  交集体积 = {_vol(common.Shape()):.2f} (交集/基准 = {_vol(common.Shape()) / bv * 100:.1f}%)")

    # 按 z 段拆分多余/缺失材料（z 为基准系坐标）
    if split_zs:
        from OCC.Core.BRepPrimAPI import BRepPrimAPI_MakeBox
        from OCC.Core.Bnd import Bnd_Box as _Bnd
        from OCC.Core.BRepBndLib import brepbndlib as _bl
        from OCC.Core.gp import gp_Pnt

        # 只统计 SOLID 体积：空 shape 与 Common 退化时返回的 box
        # 全域面（非 solid）不计入，防止逐段体积泄漏
        def _solid_vol(s):
            exp = TopExp_Explorer(s, TopAbs_SOLID)
            v = 0.0
            while exp.More():
                p = GProp_GProps()
                brepgprop.VolumeProperties(exp.Current(), p)
                v += p.Mass()
                exp.Next()
            return v

        bx = _Bnd()
        _bl.Add(base, bx)
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
                exp = TopExp_Explorer(shape, TopAbs_SOLID)
                while exp.More():
                    s = exp.Current()
                    op = BRepAlgoAPI_Common(s, box)
                    op.Build()
                    if not op.IsDone():
                        from OCC.Core.ShapeFix import ShapeFix_Shape

                        fixer = ShapeFix_Shape(s)
                        fixer.Perform()
                        op = BRepAlgoAPI_Common(fixer.Shape(), box)
                        op.Build()
                    if op.IsDone():
                        v = _solid_vol(op.Shape())
                        if v < box_vol * 0.999:
                            total += v
                    exp.Next()
                return total

            ev = _seg_vol(extra)
            mv = _seg_vol(missing)
            print(f"  z[{edges[i]:8.2f}, {edges[i + 1]:8.2f}]: 多余={ev:+9.1f}  缺失={mv:+9.1f}  净={ev - mv:+9.1f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
