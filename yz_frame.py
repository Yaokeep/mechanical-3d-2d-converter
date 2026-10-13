# -*- coding: utf-8 -*-
"""YZYX 零件系 ↔ 新框架发射系（图纸坐标系）刚性变换 —— yz_accept 三件套共用。

背景：三件套（27 点材料探针 / 五视图 HLR / 图纸对比评分）全部定义在 v15a
**零件系**（_yz_build.py 头注：X=Ø96.5 孔轴、Y=横向法兰 ±197.5、Z=上、
原点=结合面 z=0 ∩ 孔轴）；新框架 src/rebuild/ 发射的模型在**图纸坐标系**
（correspondence.py 约定：与图纸系同向，X=图纸横向、Z=图纸纵向、Y=第三向，
"只差一个平移，不需要旋转"）。两系之间是**纯平移**：

    part_x = model_x − 2650.80
    part_y = model_y − 3462.94
    part_z = model_z − 1541.25

三条偏移各取发射器"基准视图"的图纸锚点（对应关系为**已验证事实**，非拟合）：

  x: 发射器 V1(front) u=x、u_off=0、u_flip=False ⇒ model_x = 图纸 x(V1 列)；
     yz_match 已验证 图纸 x = part_x + 2650.80（TL su=+1，v15a 缺 0）。
  y: 发射器 V0(left) u=y、u_off=0、u_flip=False ⇒ model_y = 图纸 x(V0 列)；
     yz_match 已验证 图纸 x = part_y + 3462.94（TR su=+1 缺 0 / su=−1 缺 47）。
  z: 发射器 V1 v=z、v_off=0、v_flip=False ⇒ model_z = 图纸 y(V1 行)；
     yz_match 已验证 图纸 y = part_z + 1541.25（TL sv=+1，唯一候选）。

交叉印证（2026-10-13）：v15a 实体材料范围 x±172.5 / y±197.5 / z 0..187.5
与图纸三视图窗（V1 345.00×187.50、V0 395.00×187.50、V3 345.00×395.00）
逐边吻合到 0.005mm（bbox 中 y±202.53、z→202.95 的超出是无体积的杂散几何，
不参与材料——见 _probe_yz_zmax.py 实测）；发射器 V3 的 v_off=+2408.139 与
BL 侧偏移 +1054.798 之和 = 3462.937，与 y 偏移独立吻合。

自动识别：bbox 中心贴近零件系（|cx|,|cy| < 600）⇒ 原样；贴近图纸系
（cx≈2650.8、cy≈3462.94，容差 600）⇒ 平移进零件系；两者都不像 ⇒ 不猜，
按零件系原样处理并打印告警（可用 --frame 显式指定）。

用法（OCC 侧，需 cad-occt 解释器；三件套内部已自动接线）：
    from yz_frame import to_part_frame
    shape, used = to_part_frame(shape)            # 自动识别
    shape, used = to_part_frame(shape, "fw")      # 显式：图纸系 → 零件系
CLI（独立转换器）:
    $PY yz_frame.py <in.step> [out.step] [--to part|fw]
"""
import sys

from OCC.Core.Bnd import Bnd_Box
from OCC.Core.BRepBndLib import brepbndlib
from OCC.Core.BRepBuilderAPI import BRepBuilderAPI_Transform
from OCC.Core.gp import gp_Trsf, gp_Vec

#: 图纸锚点（零件原点在该轴上的图纸坐标）——零件系 = 图纸系 − OFF
OFF_X, OFF_Y, OFF_Z = 2650.80, 3462.94, 1541.25
OFF = (OFF_X, OFF_Y, OFF_Z)

#: 自动识别的参照中心与容差（mm）。零件系各轴都在 ±210 内、图纸系以
#: 图纸坐标计（>2000），两者相距 2000+，600 的容差绰绰有余。
_PART_REF = (0.0, 0.0)
_FW_REF = (OFF_X, OFF_Y)
_FRAME_TOL = 600.0


def bbox_of(shape) -> tuple[float, float, float, float, float, float]:
    """shape 的包围盒 (xmin, ymin, zmin, xmax, ymax, zmax)。"""
    b = Bnd_Box()
    brepbndlib.Add(shape, b)
    return b.Get()


def detect_frame(shape) -> str:
    """按包围盒中心判断坐标系：'part' / 'fw' / '?'（都不像 ⇒ 不猜）。"""
    x0, y0, z0, x1, y1, z1 = bbox_of(shape)
    cx, cy = (x0 + x1) / 2.0, (y0 + y1) / 2.0
    d_part = max(abs(cx - _PART_REF[0]), abs(cy - _PART_REF[1]))
    d_fw = max(abs(cx - _FW_REF[0]), abs(cy - _FW_REF[1]))
    if d_fw <= _FRAME_TOL and d_fw < d_part:
        return "fw"
    if d_part <= _FRAME_TOL:
        return "part"
    return "?"


def _translate(shape, dx: float, dy: float, dz: float):
    t = gp_Trsf()
    t.SetTranslation(gp_Vec(dx, dy, dz))
    return BRepBuilderAPI_Transform(shape, t, False).Shape()


def to_part_frame(shape, frame: str = "auto") -> tuple[object, str]:
    """把模型搬到零件系。返回 (shape, used)；used ∈ 'part'/'fw'/'?'。

    frame='auto' 时按 bbox 自动识别；'?' 不猜——原样返回，由调用方告警。
    """
    used = detect_frame(shape) if frame == "auto" else frame
    if used == "fw":
        return _translate(shape, -OFF_X, -OFF_Y, -OFF_Z), "fw"
    return shape, used


def to_fw_frame(shape, frame: str = "auto") -> tuple[object, str]:
    """把零件系模型搬到发射系（图纸系）——做"假 fw"对照/往返验证用。"""
    used = detect_frame(shape) if frame == "auto" else frame
    if used == "part":
        return _translate(shape, OFF_X, OFF_Y, OFF_Z), "part"
    return shape, used


def frame_note(used: str) -> str:
    """三件套打印用的单行人话。"""
    if used == "fw":
        return (f"[frame] 识别为发射器（图纸）坐标系 ⇒ 已平移进零件系 "
                f"(−{OFF_X:.2f}, −{OFF_Y:.2f}, −{OFF_Z:.2f})")
    if used == "part":
        return "[frame] 零件坐标系（无需变换）"
    return ("[frame] 坐标系无法自动识别（既不似零件系也不似图纸系）"
            "⇒ 按零件系原样处理；可用 --frame 显式指定")


def pop_frame_argv(argv: list[str], default: str = "auto") -> str:
    """从 argv 里取出 `--frame X`（弹出两元素），供三个脚本共用。"""
    if "--frame" in argv:
        i = argv.index("--frame")
        if i + 1 >= len(argv):
            raise SystemExit("--frame 后面缺参数（auto/part/fw）")
        val = argv[i + 1]
        del argv[i:i + 2]
        return val
    return default


def main(argv: list[str]) -> int:
    """CLI 转换器：STEP 进、STEP 出（默认 --to part：图纸系 → 零件系）。"""
    from OCC.Core.IFSelect import IFSelect_RetDone
    from OCC.Core.STEPControl import STEPControl_Reader, STEPControl_Writer, STEPControl_AsIs

    to = "part"
    if "--to" in argv:
        i = argv.index("--to")
        to = argv[i + 1]
        del argv[i:i + 2]
    if not argv[1:]:
        print(__doc__)
        return 1
    src = argv[1]
    dst = argv[2] if len(argv) > 2 else f"{src.rsplit('.', 1)[0]}_{to}.step"

    rd = STEPControl_Reader()
    if rd.ReadFile(src) != IFSelect_RetDone:
        raise RuntimeError(f"STEP 读取失败: {src}")
    rd.TransferRoots()
    shape = rd.OneShape()
    x0, y0, z0, x1, y1, z1 = bbox_of(shape)
    print(f"[in ] bbox x[{x0:.2f},{x1:.2f}] y[{y0:.2f},{y1:.2f}] z[{z0:.2f},{z1:.2f}]"
          f"  检测={detect_frame(shape)}")
    shape, used = (to_part_frame(shape, "auto") if to == "part"
                   else to_fw_frame(shape, "auto"))
    print(frame_note(used))
    wr = STEPControl_Writer()
    wr.Transfer(shape, STEPControl_AsIs)
    if wr.Write(dst) != IFSelect_RetDone:
        raise RuntimeError(f"STEP 写出失败: {dst}")
    x0, y0, z0, x1, y1, z1 = bbox_of(shape)
    print(f"[out] bbox x[{x0:.2f},{x1:.2f}] y[{y0:.2f},{y1:.2f}] z[{z0:.2f},{z1:.2f}]")
    print(f"-> {dst}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
