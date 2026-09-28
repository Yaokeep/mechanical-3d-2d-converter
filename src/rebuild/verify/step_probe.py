# -*- coding: utf-8 -*-
"""STEP 实测 —— 量出重建模型的三个方向的尺寸、体积、实体数。

**这是唯一允许 import OCC 的 verify 模块**（ARCHITECTURE §5 解释器依赖分层），
必须用 cad-occt 环境跑：

    /c/Users/yaoshuo/miniconda3/envs/cad-occt/python.exe -m src.rebuild.verify_legacy ...

## 为什么不用裸 Bnd_Box

`compare_models.py` 踩过的坑（CLAUDE.md 记着）：SW 导出的 STEP 会带
**零厚度悬挂面片/游离顶点**，裸 `Bnd_Box` 把它们算进去，bbox 会虚胖。
故本模块的主尺寸取**各 SOLID 包围盒的并集** —— 悬挂面片不属于任何 solid，
自然被排除。裸 bbox 一并返回，两者显著不一致本身就是"模型里有游离几何"的信号。
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from OCC.Core.Bnd import Bnd_Box
from OCC.Core.BRepBndLib import brepbndlib
from OCC.Core.BRepGProp import brepgprop
from OCC.Core.GProp import GProp_GProps
from OCC.Core.STEPControl import STEPControl_Reader
from OCC.Core.TopAbs import TopAbs_SOLID
from OCC.Core.TopExp import TopExp_Explorer


@dataclass(frozen=True)
class StepMeasure:
    """一个 STEP 的实测结果。纯数据 —— 不依赖 OCC 的类型（可跨环境传递）。"""

    path: str
    #: 实体域三向尺寸 (dx, dy, dz)。空模型为 None。
    extents: tuple[float, float, float] | None
    #: 裸 Bnd_Box 的三向尺寸 —— 与 extents 不一致即存在游离几何
    raw_extents: tuple[float, float, float] | None
    bbox_min: tuple[float, float, float] | None
    bbox_max: tuple[float, float, float] | None
    volume: float
    n_solids: int
    n_faces: int
    ok: bool = True
    error: str = ""

    @property
    def has_dangling(self) -> bool:
        """裸 bbox 明显大于实体域 bbox ⇒ 存在零厚度面片/游离顶点。"""
        if self.extents is None or self.raw_extents is None:
            return False
        return any(r - e > 0.5 for r, e in zip(self.raw_extents, self.extents))


def _size(box: Bnd_Box) -> tuple[float, float, float] | None:
    if box.IsVoid():
        return None
    x1, y1, z1, x2, y2, z2 = box.Get()
    return (x2 - x1, y2 - y1, z2 - z1)


def probe_step(path: str | Path) -> StepMeasure:
    """读取 STEP 并实测。读不了不抛异常 —— 返回 ``ok=False`` 的实测。"""
    p = str(path)
    r = STEPControl_Reader()
    if r.ReadFile(p) != 1:
        return StepMeasure(p, None, None, None, None, 0.0, 0, 0,
                           ok=False, error="STEP 读取失败")
    r.TransferRoots()
    shape = r.OneShape()
    if shape.IsNull():
        return StepMeasure(p, None, None, None, None, 0.0, 0, 0,
                           ok=False, error="STEP 为空形状")

    # 实体域 bbox：只并各 SOLID（排除悬挂面片/游离顶点）
    solids: list = []
    exp = TopExp_Explorer(shape, TopAbs_SOLID)
    while exp.More():
        solids.append(exp.Current())
        exp.Next()

    material = Bnd_Box()
    vol = 0.0
    for s in solids:
        brepbndlib.Add(s, material)
        props = GProp_GProps()
        brepgprop.VolumeProperties(s, props)
        vol += props.Mass()

    raw = Bnd_Box()
    brepbndlib.Add(shape, raw)

    mat_size = _size(material)
    if mat_size is None:
        # 没有实体（纯曲面/线框）—— 退回裸 bbox，但标记为"非实体模型"
        raw_size = _size(raw)
        lo = hi = None
        if raw_size is not None:
            x1, y1, z1, x2, y2, z2 = raw.Get()
            lo, hi = (x1, y1, z1), (x2, y2, z2)
        return StepMeasure(p, raw_size, raw_size, lo, hi, 0.0, 0, 0,
                           ok=False, error="STEP 里没有 SOLID（非实体模型）")

    x1, y1, z1, x2, y2, z2 = material.Get()
    return StepMeasure(
        path=p, extents=mat_size, raw_extents=_size(raw),
        bbox_min=(x1, y1, z1), bbox_max=(x2, y2, z2),
        volume=vol, n_solids=len(solids), n_faces=_count_faces(shape),
    )


def _count_faces(shape) -> int:
    from OCC.Core.TopAbs import TopAbs_FACE

    n = 0
    exp = TopExp_Explorer(shape, TopAbs_FACE)
    while exp.More():
        n += 1
        exp.Next()
    return n
