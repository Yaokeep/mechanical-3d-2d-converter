# -*- coding: utf-8 -*-
"""缺陷盒/点断言 —— 把"用户目视发现的缺陷"变成每次验收自动复核的回归断言。

验证制度化（2026-10-11，ASSESSMENT_20261006.md §D）：自动指标（体积/bbox/重合率）
到 99.5%+ 时局部可见缺陷仍零命中（bracket 三缺陷、YZYX 五处标记全靠用户目视）。
本模块把已定位缺陷转成两类断言，挂进 `run_rebuild_acceptance.py` 的 PROBES 表：

  * **盒断言** —— 缺陷区域立方盒内的材料体积 vs 金值（基准 STEP 实测，
    2026-10-11 定标）。局部缺料/多料/错位直接体现在盒体积差上。
  * **点断言** —— 关键点 IN/OUT 分类 vs 期望（基准实测分类）。槽腔圆心、
    缝隙点这类"应该是空的"位置由它管——**分类一致才是断言，不是一律 IN**。

坐标口径：盒/点一律**基准系**；重建 STEP 在图纸系，由调用方给出 shift
（= 基准min − 重建min，按靶子实测）平移后再量。**shift 硬编码是特性不是
缺陷**：识别/视图检测改动导致重建整体重定位时，所有盒断言会红——这正是
重定位回归的哨兵，重标定 shift 即可。

⚠️ 依赖 OCC：与 `step_probe` 同纪律，**不得被 `verify/__init__.py` 导出**
（selftest E 组会拉这条——默认 python 没有 OCC）。调用方在函数体内按需 import。
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from OCC.Core.BRepAlgoAPI import BRepAlgoAPI_Common
from OCC.Core.BRepBuilderAPI import BRepBuilderAPI_Transform
from OCC.Core.BRepClass3d import BRepClass3d_SolidClassifier
from OCC.Core.BRepGProp import brepgprop
from OCC.Core.BRepPrimAPI import BRepPrimAPI_MakeBox
from OCC.Core.GProp import GProp_GProps
from OCC.Core.STEPControl import STEPControl_Reader
from OCC.Core.TopAbs import TopAbs_IN, TopAbs_ON, TopAbs_OUT
from OCC.Core.gp import gp_Pnt, gp_Trsf, gp_Vec

#: 盒规格：(标签, x0, x1, y0, y1, z0, z1) —— 基准系
BoxSpec = tuple[str, float, float, float, float, float, float]
#: 点规格：(标签, x, y, z, 期望 "IN"/"OUT") —— 基准系
PointSpec = tuple[str, float, float, float, str]


@dataclass(frozen=True)
class BoxResult:
    """一个盒的断言结果。纯数据 —— 不依赖 OCC 类型。"""

    label: str
    gold: float  # 基准实测体积（定标值）
    meas: float  # 重建（shift 后）实测体积
    tol: float

    @property
    def delta(self) -> float:
        return self.meas - self.gold

    @property
    def passed(self) -> bool:
        return abs(self.delta) <= self.tol


@dataclass(frozen=True)
class PointResult:
    """一个点的断言结果。"""

    label: str
    expect: str  # 基准实测分类
    meas: str

    @property
    def passed(self) -> bool:
        return self.expect == self.meas


@dataclass
class ProbeReport:
    """一次探针检查的全部结果。读不了不抛异常 —— ``ok=False``。"""

    path: str
    boxes: list[BoxResult] = field(default_factory=list)
    points: list[PointResult] = field(default_factory=list)
    ok: bool = True
    error: str = ""

    @property
    def passed(self) -> bool:
        return self.ok and all(r.passed for r in self.boxes + self.points)

    def lines(self) -> list[str]:
        """人读行（对齐验收表输出）。"""
        if self.error:
            return [f"探针读不回：{self.error}"]
        out = []
        for b in self.boxes:
            mark = "OK " if b.passed else "!! "
            out.append(f"盒 {mark}{b.label:<14} {b.gold:>8.1f} → {b.meas:>8.1f} "
                       f"差 {b.delta:+.1f}（容差 {b.tol:.1f}）")
        for p in self.points:
            mark = "OK " if p.passed else "!! "
            out.append(f"点 {mark}{p.label:<14} 期望 {p.expect} 实测 {p.meas}")
        return out

    def to_json(self) -> str:
        return json.dumps({
            "path": self.path, "ok": self.ok, "error": self.error,
            "boxes": [{"label": b.label, "gold": b.gold, "meas": b.meas,
                       "tol": b.tol, "delta": b.delta, "passed": b.passed}
                      for b in self.boxes],
            "points": [{"label": p.label, "expect": p.expect, "meas": p.meas,
                        "passed": p.passed} for p in self.points],
        }, ensure_ascii=False, indent=2)


def _read_step(path: str):
    r = STEPControl_Reader()
    if r.ReadFile(path) != 1:
        raise RuntimeError(f"STEP 读取失败: {path}")
    r.TransferRoots()
    return r.OneShape()


def _vol_in_box(shape, b: tuple[float, ...]) -> float:
    """shape ∩ 盒 的材料体积。交为空/布尔失败 → 0（与 _probe_boxes 口径一致）。"""
    box = BRepPrimAPI_MakeBox(gp_Pnt(b[0], b[2], b[4]),
                              gp_Pnt(b[1], b[3], b[5])).Shape()
    com = BRepAlgoAPI_Common(shape, box)
    com.Build()
    if not com.IsDone() or com.Shape().IsNull():
        return 0.0
    props = GProp_GProps()
    brepgprop.VolumeProperties(com.Shape(), props)
    return props.Mass()


def _classify(shape, x: float, y: float, z: float) -> str:
    cl = BRepClass3d_SolidClassifier(shape, gp_Pnt(x, y, z), 1e-3)
    return {TopAbs_IN: "IN", TopAbs_OUT: "OUT", TopAbs_ON: "ON"}.get(cl.State(), "?")


def probe_checks(
    path: str | Path,
    shift: tuple[float, float, float],
    boxes: list[BoxSpec],
    golds: dict[str, float],
    tol,  # gold(mm³) → 容差(mm³)
    points: list[PointSpec],
) -> ProbeReport:
    """读重建 STEP → shift 平移 → 逐盒/逐点断言。

    :param shift: 图纸系 → 基准系平移（基准min − 重建min，按靶子实测）；
    :param golds: 标签 → 基准盒体积（定标值）；
    :param points: 期望取**基准实测分类**（不是"应 IN"——见模块 docstring）。
    """
    rep = ProbeReport(path=str(path))
    try:
        shape = _read_step(str(path))
    except Exception as exc:  # 读不了不抛——与 probe_step 同口径
        rep.ok, rep.error = False, str(exc)
        return rep
    t = gp_Trsf()
    t.SetTranslation(gp_Vec(*shift))
    shape = BRepBuilderAPI_Transform(shape, t, True).Shape()
    for label, *b in boxes:
        rep.boxes.append(BoxResult(label, golds[label],
                                   _vol_in_box(shape, b), tol(golds[label])))
    for label, x, y, z, exp in points:
        rep.points.append(PointResult(label, exp, _classify(shape, x, y, z)))
    return rep
