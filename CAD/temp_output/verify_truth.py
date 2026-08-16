#!/usr/bin/env python
"""验证: 重建 STEP 关键点竖直线材料段 vs 基准真值表（STEP 输出系）。"""
import sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
from OCC.Core.gp import gp_Pnt
from OCC.Core.STEPControl import STEPControl_Reader
from OCC.Core.BRepClass3d import BRepClass3d_SolidClassifier
from OCC.Core.TopExp import TopExp_Explorer
from OCC.Core.TopAbs import TopAbs_SOLID
from OCC.Core.GProp import GProp_GProps
from OCC.Core.BRepGProp import brepgprop
from OCC.Core.Bnd import Bnd_Box
from OCC.Core.BRepBndLib import brepbndlib

STEP = r'E:\项目\机械三维二维图互转\CAD\temp_output\麒浚传动_三视图_v4_3d.step'
rd = STEPControl_Reader()
st = rd.ReadFile(STEP)
rd.TransferRoots()
shape = rd.Shape()

bb = Bnd_Box()
brepbndlib.Add(shape, bb)
x1, y1, z1, x2, y2, z2 = bb.Get()
print(f'bbox: X[{x1:.1f}~{x2:.1f}] Y[{y1:.1f}~{y2:.1f}] Z[{z1:.1f}~{z2:.1f}]')
ex = TopExp_Explorer(shape, TopAbs_SOLID)
tv = 0.0
ns = 0
while ex.More():
    ns += 1
    p = GProp_GProps()
    brepgprop.VolumeProperties(ex.Current(), p)
    tv += p.Mass()
    ex.Next()
print(f'实体数={ns} 总体积={tv:.0f} (基准 261936)')

# 基准真值表: 点 -> [(z1,z2), ...] 材料段（STEP 输出系）
# 底沉腔 r<25 全空（[−46.5,−41.5] 无材料）、φ42 环槽 r[7,21] 空、
# 顶沉槽 r[8.5,25] 空 [46.6,49.6]、φ5.5 凸台为凸起（重建缺失，已知）
TRUTH = {
    (0, 0): [(-40.5, -14.95), (22.5, 50.5)],
    (20, 0): [(-23.0, 46.6)],
    (12, 0): [(-23.0, 46.6)],
    (28, 0): [(-46.5, 36.6)],
    (35, 0): [(-46.5, 41.6)],
    (25, 25): [(-36.4, 42.0)],
    (25, 0): [(-46.5, 36.6)],
}

for (cx, cy), expect in TRUTH.items():
    sols = []
    ex = TopExp_Explorer(shape, TopAbs_SOLID)
    while ex.More():
        sols.append(ex.Current())
        ex.Next()
    segs = []
    last = None
    for z in [x * 0.25 - 52.5 for x in range(430)]:
        inside = False
        for s in sols:
            sc = BRepClass3d_SolidClassifier(s)
            sc.Perform(gp_Pnt(cx, cy, z), 0.01)
            if sc.State() in (0, 2):
                inside = True
                break
        if inside and not last:
            segs.append([z])
        elif not inside and last and segs:
            segs[-1].append(z)
        last = inside
    got = [(round(a, 1), round(b, 1)) for a, b in segs]
    ok = True
    for a, b in expect:
        hit = any(abs(a - ga) < 1.0 and abs(b - gb) < 1.0 for ga, gb in got)
        if not hit:
            ok = False
    for a, b in got:
        hit = any(abs(a - ea) < 1.0 and abs(b - eb) < 1.0 for ea, eb in expect)
        if not hit:
            ok = False
    print(f'({cx:2d},{cy:2d}): 实际={got} 期望={expect} {"OK" if ok else "✗✗✗"}')
