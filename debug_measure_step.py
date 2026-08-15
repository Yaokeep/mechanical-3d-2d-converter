"""调试: 定量测量 STEP 文件（体积/bbox/实体数/面类型），P3 验证用。"""
import sys

from OCC.Core.STEPControl import STEPControl_Reader
from OCC.Core.GProp import GProp_GProps
from OCC.Core.BRepGProp import brepgprop
from OCC.Core.Bnd import Bnd_Box
from OCC.Core.BRepBndLib import brepbndlib
from OCC.Core.TopExp import TopExp_Explorer
from OCC.Core.TopAbs import TopAbs_SOLID, TopAbs_FACE
from OCC.Core.BRepAdaptor import BRepAdaptor_Surface

for path in sys.argv[1:]:
    r = STEPControl_Reader()
    if r.ReadFile(path) != 1:
        print(f"{path}: 读取失败")
        continue
    r.TransferRoots()
    shp = r.OneShape()
    props = GProp_GProps()
    brepgprop.VolumeProperties(shp, props)
    bb = Bnd_Box()
    brepbndlib.Add(shp, bb)
    x1, y1, z1, x2, y2, z2 = bb.Get()
    exp = TopExp_Explorer(shp, TopAbs_SOLID)
    ns = 0
    while exp.More():
        ns += 1
        exp.Next()
    expf = TopExp_Explorer(shp, TopAbs_FACE)
    ftypes = {}
    while expf.More():
        try:
            t = BRepAdaptor_Surface(expf.Current()).GetType()
            ftypes[t] = ftypes.get(t, 0) + 1
        except Exception:
            pass
        expf.Next()
    print(f"{path}:\n  体积={props.Mass():.2f} "
          f"bbox=({x2-x1:.2f},{y2-y1:.2f},{z2-z1:.2f}) "
          f"实体={ns} 面类型={ftypes}")
