#!/usr/bin/env python
"""闭环验证对比: 基准 STEP vs 重建 STEP 定量差异分析。

对比项:
  1. 体积 / bbox / 实体数（各自测量）
  2. 布尔差: 基准-重建（多余材料）与 重建-基准（缺失材料）的体积
  3. 重建相对基准的包容率: 交集体积 / 基准体积

用法:
    python compare_models.py 基准.step 重建.step
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
from OCC.Core.Interface import Interface_Static_SetCVal


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
    if len(sys.argv) < 3:
        print(__doc__)
        return 1
    base = _read(sys.argv[1])
    recon = _read(sys.argv[2])

    bv, bb, bn = _measure(base)
    rv, rb, rn = _measure(recon)
    print(f"基准 {sys.argv[1]}:")
    print(f"  体积={bv:.2f} bbox={tuple(f'{x:.2f}' for x in bb)} 实体={bn}")
    print(f"重建 {sys.argv[2]}:")
    print(f"  体积={rv:.2f} bbox={tuple(f'{x:.2f}' for x in rb)} 实体={rn}")
    print(f"  体积差 = {rv - bv:+.2f} ({(rv - bv) / bv * 100:+.2f}%)")

    # 布尔差
    extra = BRepAlgoAPI_Cut(recon, base); extra.Build()
    missing = BRepAlgoAPI_Cut(base, recon); missing.Build()
    common = BRepAlgoAPI_Common(base, recon); common.Build()
    ep = GProp_GProps(); brepgprop.VolumeProperties(extra.Shape(), ep)
    mp = GProp_GProps(); brepgprop.VolumeProperties(missing.Shape(), mp)
    cp = GProp_GProps(); brepgprop.VolumeProperties(common.Shape(), cp)
    print(f"  多余材料(重建-基准) = {ep.Mass():.2f}")
    print(f"  缺失材料(基准-重建) = {mp.Mass():.2f}")
    print(f"  交集体积 = {cp.Mass():.2f} (交集/基准 = {cp.Mass() / bv * 100:.1f}%)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
