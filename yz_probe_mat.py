# -*- coding: utf-8 -*-
"""YZYX 齿箱上盖材料探针（无 3D 基准靶子的定量验收第一件，验证制度化）。

逐点 BRepClass3d 分类 IN/OUT/ON，验证模型在关键位置的**实际材料分布**：
甲板区(z≈130..140) 应 IN / 槽腔(z 12..122) 应 OUT / 窗口口(贴 y=±75 内) 应 OUT /
浅腔平台(|y|60..75, z 60..100) 应 IN、其上下沿应 OUT。
27 点期望由 v13/v14/v15/v15a 四轮用户读法修复逐一定案（2026-10-02~06），
是"无基准件验收"里最接近金值的东西——**改动建模/重建后必须复跑**。

用法: PYTHONIOENCODING=utf-8 $PY yz_probe_mat.py [stepfile]
总入口见 yz_accept.py（三件套一起跑 + 基线判红）。
"""
import sys
from pathlib import Path

from OCC.Core.BRepClass3d import BRepClass3d_SolidClassifier
from OCC.Core.IFSelect import IFSelect_RetDone
from OCC.Core.STEPControl import STEPControl_Reader
from OCC.Core.TopAbs import TopAbs_IN, TopAbs_ON, TopAbs_OUT
from OCC.Core.gp import gp_Pnt

#: 27 点判据（名称, x, y, z, 期望）——零件系（原点=结合面 z=0 ∩ Ø96.5 孔轴）
PTS = [
    # 名称, x, y, z, 期望
    ("甲板 中 南",   -96.5, -70.0, 135.0, "IN"),
    ("甲板 中 北",   -96.5,  70.0, 135.0, "IN"),
    ("甲板 西端",    -140.0, -70.0, 135.0, "IN"),
    ("甲板 东端",    -53.0, -70.0, 130.0, "IN"),
    ("甲板 斜肩正上(−66)", -95.3, -65.9, 128.0, "IN"),
    ("用户点#1 正下方", -95.3, -65.9, 115.0, "OUT"),
    ("用户点#2 正下方", -94.2,  69.2, 115.0, "OUT"),
    ("槽腔 南 中部",  -96.5, -66.0,  60.0, "OUT"),
    ("槽腔 北 中部",  -96.5,  66.0,  60.0, "OUT"),
    ("窗口口 南(贴壁)", -96.5, -74.9,  60.0, "OUT"),
    ("窗口口 北(贴壁)", -96.5,  74.9,  60.0, "OUT"),
    ("窗外 南(体外)",  -96.5, -75.5,  60.0, "OUT"),
    ("深腔西外壁内 (−145)", -145.0, -70.0, 60.0, "IN"),
    ("深腔东壁内 x=−48 z=61", -48.0, -70.0, 61.0, "IN"),
    ("槽腔 南 −141 角旁", -141.0, -66.0, 60.0, "OUT"),
    ("槽腔 南 −52 角旁",  -52.0, -66.0, 60.0, "OUT"),
    # ---- v15 浅腔平台定点（平台 |y|60..75, z 60..100, x −51.5..−15.5；
    # v14 时该区 z<100 全材料——z=59.9 点即"多料 51,840"的直接判据）----
    ("平台下 z=59.9 (v15修)", -33.0, -70.0, 59.9, "OUT"),
    ("平台中 z=61",          -33.0, -70.0, 61.0, "IN"),
    ("平台顶内 z=99.9",      -33.0, -70.0, 99.9, "IN"),
    ("平台上方 z=100.1",     -33.0, -70.0, 100.1, "OUT"),
    ("平台内 y=74.9",        -33.0, -74.9, 80.0, "IN"),
    ("平台外 y=75.1",        -33.0, -75.1, 80.0, "OUT"),
    ("浅腔上方 z=120",       -33.0, -70.0, 120.0, "OUT"),
    # ---- v15a 两处圆角修复的直接验证点 ----
    ("(e)唇点 y=77.8 z=55.4 (v15a)", -3.0, -77.8, 55.4, "OUT"),   # 修前=唇 IN
    ("(b)垫心 y=64.5 z=16.5 (v15a)", -51.45, -64.5, 16.5, "OUT"),  # 修前=垫 IN
    ("(b)月牙 y=61 z=12.5 (v15a)",   -51.45, -61.0, 12.5, "IN"),   # 月牙本体应保留
    ("顶面上方 z=150",   -96.5, -70.0, 150.0, "OUT"),
]


def run_probe(src: str) -> tuple[int, int]:
    """逐点分类，打印 OK/!!。返回 (失败数, 总点数)。"""
    rd = STEPControl_Reader()
    if rd.ReadFile(src) != IFSelect_RetDone:
        raise RuntimeError(f"STEP 读取失败: {src}")
    rd.TransferRoots()
    shape = rd.OneShape()

    fails = 0
    for name, x, y, z, exp in PTS:
        c = BRepClass3d_SolidClassifier(shape, gp_Pnt(x, y, z), 1e-3)
        s = {TopAbs_IN: "IN", TopAbs_OUT: "OUT", TopAbs_ON: "ON"}.get(c.State(), "?")
        if s != exp:
            fails += 1
        mark = "OK " if s == exp else "!! "
        print(f"  {mark}{name:24s} ({x:8.1f},{y:7.1f},{z:6.1f})  {s:3s}  期望 {exp}")
    print(f"材料探针: {len(PTS) - fails}/{len(PTS)} 通过")
    return fails, len(PTS)


def main() -> int:
    src = sys.argv[1] if len(sys.argv) > 1 else "CAD/temp_output/_yz_3d.step"
    fails, total = run_probe(src)
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
