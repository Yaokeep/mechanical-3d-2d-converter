#!/usr/bin/env python
"""简易 DXF→SVG 渲染（LINE/CIRCLE/ARC，按线型区分可见/隐藏线）。"""
import sys
import ezdxf
from ezdxf import bbox as bmod

doc = ezdxf.readfile(sys.argv[1])
msp = doc.modelspace()
xs, ys = [], []
for e in msp:
    try:
        b = bmod.extents([e], fast=True)
        xs += [b.extmin.x, b.extmax.x]
        ys += [b.extmin.y, b.extmax.y]
    except Exception:
        pass
xmin, xmax, ymin, ymax = min(xs), max(xs), min(ys), max(ys)
print(f"总bbox: ({xmin:.1f},{ymin:.1f})-({xmax:.1f},{ymax:.1f})")
W = xmax - xmin + 40
H = ymax - ymin + 40
ox, oy = xmin - 20, ymin - 20

def fmt(x):
    return f"{x:.2f}"

lines = []
for e in msp:
    lt = ""
    try:
        lt = (e.dxf.linetype or "").upper()
    except Exception:
        pass
    dash = lt and "HIDDEN" in lt
    color = "#5555cc" if dash else "#111111"
    sw = 0.6 if dash else 0.9
    if e.dxftype() == "LINE":
        s, t = e.dxf.start, e.dxf.end
        dash_attr = ' stroke-dasharray="4,3"' if dash else ""
        lines.append(f'<line x1="{fmt(s.x-ox)}" y1="{fmt(s.y-oy)}" '
                     f'x2="{fmt(t.x-ox)}" y2="{fmt(t.y-oy)}" '
                     f'stroke="{color}" stroke-width="{sw}"{dash_attr}/>')
    elif e.dxftype() == "CIRCLE":
        c, r = e.dxf.center, e.dxf.radius
        dash_attr = ' stroke-dasharray="4,3"' if dash else ""
        lines.append(f'<circle cx="{fmt(c.x-ox)}" cy="{fmt(c.y-oy)}" '
                     f'r="{fmt(r)}" fill="none" stroke="{color}" '
                     f'stroke-width="{sw}"{dash_attr}/>')
    elif e.dxftype() == "ARC":
        c, r = e.dxf.center, e.dxf.radius
        a1, a2 = e.dxf.start_angle, e.dxf.end_angle
        import math
        p1 = (c.x + r * math.cos(math.radians(a1)), c.y + r * math.sin(math.radians(a1)))
        p2 = (c.x + r * math.cos(math.radians(a2)), c.y + r * math.sin(math.radians(a2)))
        sweep = (a2 - a1) % 360
        large = 1 if sweep > 180 else 0
        lines.append(f'<path d="M {fmt(p1[0]-ox)} {fmt(p1[1]-oy)} '
                     f'A {fmt(r)} {fmt(r)} 0 {large} 0 {fmt(p2[0]-ox)} {fmt(p2[1]-oy)}" '
                     f'fill="none" stroke="{color}" stroke-width="{sw}"/>')

svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="{W*1.5}" height="{H*1.5}"
viewBox="0 0 {W} {H}" style="background:white">
<g transform="scale(1,-1) translate(0,-{H})">
{chr(10).join(lines)}
</g></svg>'''
out = sys.argv[2] if len(sys.argv) > 2 else sys.argv[1].replace(".dxf", ".svg")
with open(out, "w", encoding="utf-8") as f:
    f.write(svg)
print(f"SVG: {out} ({len(lines)} 实体)")
