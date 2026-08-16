#!/usr/bin/env python
"""重新生成麒浚传动三视图 DXF（使用修复后的 supplement 逻辑）。"""
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
OUT = r'E:\项目\机械三维二维图互转\CAD\temp_output\麒浚传动_三视图_v6.dxf'
g.create_dxf_drawing(views, None, OUT)
print('已保存:', OUT)

# 打印 front 视图底部 (Y<30 区域) 的线段，验证法兰带
fl = views["front"]["lines"]
print('\n=== front 可见线 Y<30 区域 ===')
for x1, y1, x2, y2 in sorted(fl, key=lambda l: (min(l[1], l[3]), min(l[0], l[2]))):
    if max(y1, y2) < 30:
        print(f'  ({x1:7.1f},{y1:7.1f}) → ({x2:7.1f},{y2:7.1f})')
