#!/usr/bin/env python
"""检查新 front 视图投影法兰带区域 (Z -26.5~-6.8)。"""
import sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
import importlib.util
spec = importlib.util.spec_from_file_location(
    'gen', r'E:\项目\机械三维二维图互转\CAD\temp_output\generate_engineering_drawing.py')
g = importlib.util.module_from_spec(spec)
spec.loader.exec_module(g)
from OCC.Core.STEPControl import STEPControl_Reader

STEP = r'E:\项目\机械三维二维图互转\CAD\temp_output\麒浚传动_PF60K-14-50-70-M4-L2-12_20260815_185358.step'
rd = STEPControl_Reader()
rd.ReadFile(STEP)
rd.TransferRoots()
shape = rd.Shape()
views = g.project_all_views(shape)
fl = views["front"]["lines"]

print('=== front 法兰带区域 (投影Y -27~-6) ===')
for x1, y1, x2, y2 in sorted(fl, key=lambda l: (min(l[1], l[3]), min(l[0], l[2]))):
    if -27 <= y1 <= -6 and -27 <= y2 <= -6:
        print(f'  ({x1:7.1f},{y1:7.1f}) -> ({x2:7.1f},{y2:7.1f})')
print()
print('=== X=±40 附近竖线 ===')
for x1, y1, x2, y2 in sorted(fl):
    if abs(x1) > 39 or abs(x2) > 39:
        print(f'  ({x1:7.1f},{y1:7.1f}) -> ({x2:7.1f},{y2:7.1f})')
print()
print('=== Y=-26.5 附近水平线 ===')
for x1, y1, x2, y2 in sorted(fl):
    if abs(y1 + 26.5) < 0.3 and abs(y2 + 26.5) < 0.3:
        print(f'  ({x1:7.1f},{y1:7.1f}) -> ({x2:7.1f},{y2:7.1f})')
