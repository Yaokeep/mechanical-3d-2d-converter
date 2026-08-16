#!/usr/bin/env python
"""调试: 分析三视图 DXF 中各视图的边/圆几何分布（按布局区域）。"""
import sys
import ezdxf

doc = ezdxf.readfile(sys.argv[1])
msp = doc.modelspace()

for e in msp:
    t = e.dxftype()
    lt = ""
    try:
        lt = (e.dxf.linetype or "").upper()
    except Exception:
        pass
    if t == "LINE":
        x1, y1 = e.dxf.start.x, e.dxf.start.y
        x2, y2 = e.dxf.end.x, e.dxf.end.y
        # 视图区域: front Y 0~97, top Y 147~227, side X 130~210
        if y1 >= 140 and y2 >= 140:
            region = "top"
        elif x1 >= 120 and x2 >= 120:
            region = "side"
        else:
            region = "front"
        print(f"{region} LINE({lt}) ({x1:.1f},{y1:.1f})->({x2:.1f},{y2:.1f})")
    elif t == "CIRCLE":
        cx, cy, r = e.dxf.center.x, e.dxf.center.y, e.dxf.radius
        if cy >= 140:
            region = "top"
        elif cx >= 120:
            region = "side"
        else:
            region = "front"
        print(f"{region} CIRCLE({lt}) c=({cx:.1f},{cy:.1f}) r={r:.2f}")
