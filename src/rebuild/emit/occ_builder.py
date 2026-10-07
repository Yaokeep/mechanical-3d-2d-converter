# -*- coding: utf-8 -*-
"""特征树 → OCC B-rep（精确实体）（ARCHITECTURE §5 emit 层的 OCC 侧）。

    python -m src.rebuild.emit.occ_builder --demo    # 自证：建模 + 体积核对（需 cad-occt）

## 这一层是什么、不是什么

特征树是**符号层**（每个数字都是 `Claim`，每个特征都有依据与置信度），OCC 是
**几何层**。夹在中间的发射器只做一件事：把**已定型的** Claim 翻译成 OCC 的
"面 + 布尔"。因此本模块：

* **不做几何推理**，也不补默认值 —— `features/library.py` 的契约说"缺参数就报
  `KeyError`，绝不默认 0"，这里同样：缺参数、类型未定（孔/凸台歧义未消解）
  一律抛 `OccBuildError` **并指名特征 id**。
* **不静默跳过**任何特征。旧管线的病根之一正是静默（特征没建出来模型仍然
  "看着差不多"）；本模块每一步都验 `IsDone()` / `BRepCheck_Analyzer`，
  失败即炸，绝不继续往下堆。
* **不用整体 compound 布尔**：逐特征两两 `BRepAlgoAPI_Fuse/Cut`。
  `section_view.py` 的模块注释记着"多实体 compound 布尔静默部分失败"的教训。

## 与 sw_builder.py 的对齐（同一棵特征树，两条腿必须给出同一个零件）

| 项 | 约定 |
|---|---|
| 参数名 | 完全按 `features/library.py`，本模块不另起一套 |
| `axial_at` | HOLE = **孔口**；POCKET / SLOT = **槽/腔的底**；BOSS = 凸台起始处 |
| `edges` | IR 系（mm）的 `"x,y,z"` **棱上点**，**给棱中点、不给角点**，多条分开给 |
| 缺参数 | 抛错并指名特征 id（本模块的错是 `OccBuildError`，SW 侧是 `SwBuildError`） |
| SLOT 几何 | 以轴为中心：`length` 沿 b1、`width` 沿 b2、`depth` 沿轴（与 sw_builder 同） |
| PATTERN | 只支持圆形阵列，且靠**几何重发** child 实现（不用原生阵列特征） |

**坐标是 IR 系毫米，不做任何换算**（SW 侧那条 `IR→SW` 旋转是 SW 的视图约定，
OCC 没有"某个方向是前视图"这回事）。好处是 `edges` 里的坐标可以直接当 OCC
坐标用，`step_probe` / `compare_models` 量出来的也就是 IR 系的尺寸。

b1/b2 基向量：沿轴的正向坐标轴走**循环后继**（z→b1=x、x→b1=y、y→b1=z），
`b2 = dir × b1`（右手）。这张表与 `sw_builder._FRAMES` 逐位一致 ——
两个发射器必须把同一个 `profile` 放到同一个平面上，否则同一棵特征树会在
SW 与 OCC 里造出互相转 90° 的零件。非轴向（任意方向轴）只有本模块支持，
b1 取"与 z、x、y 依次叉积的第一个非退化方向"（同 `library._perp`）。

## 已实测的 OCC 7.7.2 行为（本模块全部假设的来源，均为探针实测）

| 项 | 实测结论 |
|---|---|
| **圆柱顶圆的 seam 顶点是"角点"** | 圆柱侧面的 seam 是一条**沿母线的直线棱**（角 0 处），它与端面整圆共用顶点 `(圆心+r, y_c, z_top)`。整圆本身是**一条 360° 的棱**（不是两段半圆），所以一个棱中点就够；但给 seam 那个顶点会同时命中"圆"与"seam 直线"两条棱 → 按"并列即歧义"被拒（实测距离都是 0.000000）。这正是"不给角点"规则要挡的东西 |
| **`BRepPrimAPI_MakeCylinder` 是惰性的** | 不先调 `.Shape()` 时 `IsDone()` **恒为 False** —— 照"先判后取"写会把一个完全正常的圆柱误判成"构造失败"。`MakePrism`/`MakeRevol` 没有这个问题，但统一按"先取形状、再判成败"写 |
| 布尔精度 | `BRepAlgoAPI_Fuse/Cut` 是**精确布尔**：16000+π·8²·10 一类算例与解析值相对误差 ~1e-13，不是网格近似 |
| 回转母线与轴共线 | 母线末端补的"回到轴"的边整段落在旋转轴上，`BRepPrimAPI_MakeRevol` 照样出合法实体（不需要离轴 ε，也不必怕退化） |
| 棱枚举 | `TopExp_Explorer` 会把共享棱**访问两次**（每条棱属于两个面），必须用 `topexp.MapShapes` + `TopTools_IndexedMapOfShape` 去重，否则同一条棱被 Add 两次 |
| `TopExp.MapShapes_s` | pythonocc 7.7 里没有这个名字，是 `topexp.MapShapes(shape, TopAbs_EDGE, map)`；map 用 `.Size()`（没有 `Extent` / `__len__`），`FindKey` **1 起** |
| `gp_Circ` | 要 `gp_Ax2`（不是 `gp_Ax1`）：`gp_Circ(gp_Ax2(点, 向), r)` |
| 圆角/倒角 | `BRepFilletAPI_MakeFillet/MakeChamfer(shape)` → 逐棱 `Add(...)` → `Build()`。棱必须**取自同一 shape 实例**（每次布尔后都要在新 shape 上重新定位） |
| **`BRepBndLib::Add` 的盒子会虚胖** | 朴素 `Add` 对**斜面/斜圆柱**取的是未裁剪曲面的外延：40×40×20 的板被一根斜孔（工具轴不平行于坐标轴）Cut 后，盒子报成 `(0,0,-2.801)-(44.715,40,20)` —— **比基体还大**，而体积精确（32000−152.641623）。报数/验收一律用 `AddOptimal(s, box, False, False)`（精确几何；实测与解析外形逐位一致，轴对齐时两者同值） |

## 已知契约缺口（不在本模块擅自拍板，见交付报告）

1. `edges` 的**权威格式**在 `library.OPTIONAL_PARAMS` 里写作"见 emit/occ_builder"，
   本模块与 `sw_builder` 现已对齐为"`"x,y,z"` 棱上点 + 分号/列表分隔"，
   但 library 里的那句话仍指向一个不存在的定义。
2. SLOT 的 `length` 方向：`library._predict_slot` 把 `length` 画在**轴**上，而两个
   发射器都把 `length` 放在面内、`depth` 才沿轴 —— 预测与发射互相矛盾。
3. PATTERN 线性阵列只有 `pitch` **没有方向**，无法确定往哪儿排 → 直接拒绝。
4. CHAMFER 的 `angle_deg` ≠ 45° 时，`AddDA` 需要指定"距离量在哪个相邻面上"，
   契约没给 → 只支持 45°（等距），其余角度拒绝。
"""
from __future__ import annotations

import math
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from OCC.Core.Bnd import Bnd_Box
from OCC.Core.BRepAlgoAPI import BRepAlgoAPI_Cut, BRepAlgoAPI_Fuse
from OCC.Core.BRepBndLib import brepbndlib
from OCC.Core.BRepBuilderAPI import (BRepBuilderAPI_MakeEdge,
                                     BRepBuilderAPI_MakeFace,
                                     BRepBuilderAPI_MakePolygon,
                                     BRepBuilderAPI_MakeVertex,
                                     BRepBuilderAPI_MakeWire)
from OCC.Core.BRepCheck import BRepCheck_Analyzer
from OCC.Core.BRepExtrema import BRepExtrema_DistShapeShape
from OCC.Core.BRepFilletAPI import BRepFilletAPI_MakeChamfer, BRepFilletAPI_MakeFillet
from OCC.Core.BRepGProp import brepgprop
from OCC.Core.BRepOffsetAPI import BRepOffsetAPI_ThruSections
from OCC.Core.BRepTools import breptools
from OCC.Core.BRepPrimAPI import (BRepPrimAPI_MakeCylinder, BRepPrimAPI_MakePrism,
                                  BRepPrimAPI_MakeRevol)
from OCC.Core.GC import GC_MakeArcOfCircle
from OCC.Core.GProp import GProp_GProps
from OCC.Core.STEPControl import (STEPControl_AsIs, STEPControl_Reader,
                                  STEPControl_Writer)
from OCC.Core.TopAbs import TopAbs_EDGE, TopAbs_SOLID
from OCC.Core.TopExp import TopExp_Explorer, topexp
from OCC.Core.TopTools import TopTools_IndexedMapOfShape
from OCC.Core.gp import gp_Ax1, gp_Ax2, gp_Dir, gp_Pnt, gp_Vec

from ..features import library
from ..model.claim import Claim, Tier
from ..model.feature_tree import Feature, FeatureType, Part
from ..model.geom import Axis3, Point3, Vector3
from ..model.geom2d import Point2, Profile2, ProfileSeg2
from ..model.ids import FeatureId

__all__ = ["OccBuildError", "OccUnavailable", "build_shape", "build_step",
           "main", "occ_available"]

#: IR 轴向名 → 单位向量
_DIRS: dict[str, Vector3] = {
    "x": Vector3(1.0, 0.0, 0.0),
    "y": Vector3(0.0, 1.0, 0.0),
    "z": Vector3(0.0, 0.0, 1.0),
}

#: 坐标轴的循环后继（右手系的"下一个"）。profile 的 b1 取它，两发射器共用同一约定。
_NEXT: dict[str, str] = {"x": "y", "y": "z", "z": "x"}

#: 切割余量（mm）：通孔两端各多切一点，避免工具面与零件面**恰好共面**。
#: 共面布尔是几何核的老坑（SW 侧直接失败）；OCC 一般能吃下，但多切 0.5mm 到空气里
#: 没有代价，所以照 sw_builder 取同一个值。
_EPS = 0.5

#: "棱上点"定位棱的距离容差（mm）。与 `sw_builder._EDGE_TOL` 同值同量级：
#: 宽到能容忍调用方把坐标舍到小数点后一位，又窄于任何有意义的几何间隔。
#: 容差内命中多条棱时**报歧义**，绝不赌一条。
_EDGE_TOL = 1e-3
#: 阵列"实例是否已被现有特征占掉"的判定容差（mm）。刻意比 `_EDGE_TOL` 松、与
#: `sw_builder._EDGE_TOL` 同值 0.1：两侧必须**同一判据**，否则 OCC 判"没占"照发、
#: SW 判"占"跳过，同一个零件在两个发射器里就差出一道薄片（图纸上孔位带 0.1mm
#: 级画图精度，见 CLAUDE.md 信息论局限表）。
_PATTERN_TOL = 0.1

#: 体积相对误差的判据（demo 默认）。OCC 是精确布尔，实测相对误差 ~1e-13
#: 量级，1e-9 已经是"明显有问题才算超"的宽线。
_VOL_TOL = 1e-9


class OccBuildError(RuntimeError):
    """特征建模失败。消息里**必须带特征 id** —— 没有 id 的失败没法定位。"""


class OccUnavailable(OccBuildError):
    """OCC 不可用（没装 pythonocc，或几何核跑不起来）。"""


# ---------------------------------------------------------------------------
# 可用性探测
# ---------------------------------------------------------------------------

def occ_available() -> bool:
    """OCC 是否**真的能干活**。不抛异常，也**没有副作用**（不写文件、不起进程）。

    本模块顶部就 import OCC —— 能 import 到本模块，说明 pythonocc 至少在。
    所以这里不做"能不能 import"的重复判断（那个由 `emit/__init__.occ_available`
    的懒加载包装负责），而是再往前一步：**造一个 10mm 立方体量它的体积**。
    这样能挡住"包装在、DLL 缺、几何核起不来"这类只在真跑几何时才暴露的故障
    —— 探测函数的结论应该是"能用"，不是"看着装了"。
    """
    try:
        from OCC.Core.BRepPrimAPI import BRepPrimAPI_MakeBox
        box = BRepPrimAPI_MakeBox(10.0, 10.0, 10.0).Shape()
        return abs(volume_of(box) - 1000.0) < 1e-6
    except Exception:
        return False


def volume_of(shape: Any) -> float:
    """一个 shape 的体积（mm³）；多实体自动求和。"""
    props = GProp_GProps()
    brepgprop.VolumeProperties(shape, props)
    return props.Mass()


# ---------------------------------------------------------------------------
# IR 语义取值
# ---------------------------------------------------------------------------

def _param(f: Feature, name: str) -> Any:
    """取必需参数；缺了直接抛 —— 与 `features/library` 契约一致（不默认 0）。"""
    try:
        c = f.param(name)
    except KeyError as e:
        raise OccBuildError(f"特征 #{f.id}（{f.type.value}）缺必需参数 {name!r}") from e
    if c.value is None:
        raise OccBuildError(f"特征 #{f.id}（{f.type.value}）的参数 {name!r} 值为 None")
    return c.value


def _opt(f: Feature, name: str, default: Any = None) -> Any:
    """取可选参数；没有就给调用方**显式指定**的默认（不是默默给 0）。"""
    c = f.params.get(name)
    return default if c is None else c.value


def _axial_at(f: Feature) -> float:
    """特征沿轴的起点坐标（`library.OPTIONAL_PARAMS` 里那条 `axial_at`）。

    ⚠️ 缺参数时按 **0** 起 —— 但 **0 是默认值、不是图纸读数**，所以这里必须
    记账打一行（判据与 `sw_builder._axial_at` 同一份，两边刻意各留一个实现：
    `sw_builder` 不许 import OCC，`occ_builder` 也不许 import win32com）：基体
    低面不在 0 的零件（bracket 的基体自 z=2 起）会因此让凸台伸出基体之外 ——
    实测整件 z 向 bbox 46 而基准 44。识别层迟早要把这个数给出来，在那之前
    至少不静默（"系统里不存在裸数值"在发射器一侧同样成立）。
    """
    v = _opt(f, "axial_at", None)
    if v is None:
        print(f"[emit] 特征 #{f.id}（{f.type.value}）没有 axial_at ⇒ 沿轴按 0 起"
              f"（默认值，非图纸读数；基体不在 0 起时会伸出基体）")
        return 0.0
    return float(v)


def _origin_of(f: Feature) -> Point3:
    """特征在 IR 系里的位置：优先轴原点，退回 placement。"""
    if f.axis is not None and f.axis.value is not None:
        return f.axis.value.origin
    p = f.placement.value
    return p if isinstance(p, Point3) else Point3(0.0, 0.0, 0.0)


def _axis_of(f: Feature) -> tuple[Point3, Vector3]:
    """(原点, 单位方向)。方向取 `Feature.axis`，退回 `params['dir']` 的轴向名。

    与 `features/library._dir_of` 同语义（那里是私有的，故此处自备一份）。
    """
    if f.axis is not None and f.axis.value is not None:
        a: Axis3 = f.axis.value
        return a.origin, a.direction.normalized()
    name = _opt(f, "dir", "z")
    if isinstance(name, Vector3):
        return _origin_of(f), name.normalized()
    if name not in _DIRS:
        raise OccBuildError(
            f"特征 #{f.id}: 轴向名 {name!r} 不可识别（只认 x/y/z 或 Vector3）")
    return _origin_of(f), _DIRS[name]


def _named_axis(d: Vector3) -> str | None:
    """方向是否与某条坐标轴同向；不是则 None（**不猜、不近似到最近的轴**）。"""
    w = d.normalized()
    for name, v in _DIRS.items():
        if w.dot(v) > 0.9995:
            return name
    return None


def _perp(d: Vector3) -> Vector3:
    """与 d 垂直的任一单位向量（调用方保证 d 非零）。

    与 `library._perp` 取同一规则（依次与 z、x、y 叉积，取第一个非退化的），
    这样"任意方向的轴"在预测层与发射层落成同一个平面。
    """
    for c in (Vector3(0.0, 0.0, 1.0), Vector3(1.0, 0.0, 0.0), Vector3(0.0, 1.0, 0.0)):
        v = d.cross(c)
        if v.norm > 1e-9:
            return v.normalized()
    raise OccBuildError("零向量没有垂直方向")


def basis_of(d: Vector3) -> tuple[Vector3, Vector3]:
    """(b1, b2)：垂直于 d 的右手基，b1 × b2 = d。profile 的坐标 (a, b) 落在这上面。"""
    w = d.normalized()
    name = _named_axis(w)
    b1 = _DIRS[_NEXT[name]] if name is not None else _perp(w)
    return b1, w.cross(b1)


def _pnt(p: Point3) -> gp_Pnt:
    return gp_Pnt(p.x, p.y, p.z)


def _at(o: Point3, b1: Vector3, b2: Vector3, d: Vector3,
        a: float, b: float, t: float) -> Point3:
    """面内坐标 (a,b) + 沿轴坐标 t → IR 点。"""
    return o + b1 * a + b2 * b + d * t


# ---------------------------------------------------------------------------
# 体元构造（工具体：先造出来，再与累计 shape 布尔）
# ---------------------------------------------------------------------------

def _dedupe(pts: list[Point3], tol: float = 1e-9) -> list[Point3]:
    """去掉相邻重复点 —— 零长边会让 `MakePolygon`/`MakeFace` 直接退化。"""
    out: list[Point3] = []
    for p in pts:
        if not out or p.distance_to(out[-1]) > tol:
            out.append(p)
    if len(out) > 1 and out[0].distance_to(out[-1]) <= tol:
        out.pop()
    return out


def _polygon_face(pts: list[Point3], f: Feature, what: str):
    """由一串 IR 点造闭合平面 face（点必须共面，顺序即环序）。"""
    pts = _dedupe(pts)
    if len(pts) < 3:
        raise OccBuildError(f"特征 #{f.id}（{f.type.value}）{what}：有效点不足 3 个")
    poly = BRepBuilderAPI_MakePolygon()
    for p in pts:
        poly.Add(_pnt(p))
    poly.Close()
    if not poly.IsDone():
        raise OccBuildError(
            f"特征 #{f.id}（{f.type.value}）{what}：{len(pts)} 点环闭合失败")
    mk = BRepBuilderAPI_MakeFace(poly.Wire())
    if not mk.IsDone():
        raise OccBuildError(
            f"特征 #{f.id}（{f.type.value}）{what}：环共面性/自交导致建面失败")
    return mk.Face()


def _built(mk: Any, f: Feature, what: str) -> Any:
    """取构造器的结果并判成败。

    ⚠️ 必须先 `.Shape()` 再判 `IsDone()`：`BRepPrimAPI_MakeCylinder`（MakeOneAxis 系）
    是**惰性**的 —— 不取形状时 `IsDone()` 恒为 False，照"先判后取"的写法会把
    一个完全正常的圆柱误判成"构造失败"（实测）。MakePrism/MakeRevol 是急切的，
    但统一按这个顺序写，免得踩第二次。
    """
    shape = mk.Shape()
    if not mk.IsDone() or shape.IsNull():
        raise OccBuildError(f"特征 #{f.id}（{f.type.value}）{what}：构造失败")
    return shape


def _extrude(face: Any, d: Vector3, length: float, f: Feature, what: str):
    """把 face 沿 d 拉伸 length（mm）。"""
    if length <= 0.0:
        raise OccBuildError(f"特征 #{f.id}（{f.type.value}）{what}：拉伸长度必须为正，实得 {length}")
    return _built(
        BRepPrimAPI_MakePrism(face, gp_Vec(d.x * length, d.y * length, d.z * length)),
        f, what)


def _profile_face(f: Feature, profile: Any, t: float, what: str):
    """把 `profile` 在轴上坐标 t 处的平面内造成 face。

    两种契约：原始的 ``[(a, b), ...]`` 点列（多边形）与
    ``Profile2``（含圆弧段，views/ring 提取的环经 to_profile 而来）。
    """
    if isinstance(profile, Profile2):
        return _profile2_face(f, profile, t, what)
    if not isinstance(profile, (list, tuple)) or len(profile) < 3:
        raise OccBuildError(
            f"特征 #{f.id}（{f.type.value}）{what}：profile 需为 ≥3 点的点列，实得 {profile!r}")
    o, d = _axis_of(f)
    b1, b2 = basis_of(d)
    pts = [_at(o, b1, b2, d, float(a), float(b), t) for a, b in profile]
    return _polygon_face(pts, f, what)


def _profile2_face(f: Feature, profile: Profile2, t: float, what: str):
    """带圆弧的轮廓（``Profile2``）→ 轴上 t 处平面内的 face。

    弧段用**三点弧** ``GC_MakeArcOfCircle(P1, Pm, P2)`` 建棱：方向由
    三点顺序唯一决定，不依赖 ``gp_Circ`` 参数化朝向（``MakeEdge(circ,
    P1, P2)`` 在起点参数大于终点时会绕出补弧，朝向语义易错）。弧中点
    Pm 按 ``sa→ea``（``ccw`` 定方向）取跨度中角——与 views/ring.py 记
    角度同约定：``sa`` 恒为 ``p1`` 端角、``ea`` 恒为 ``p2`` 端角。

    ⚠️ 段序必须是**遍历序**（首尾相接的闭合链）：``MakeWire.Add`` 对乱序
    边会自动重排，产出的 face 有时面积对、拉伸后体积错（实测乱序 D 形
    面积 957.08 应为 557.08），故进门先用 ``Profile2.chain_break`` 验链。
    """
    o, d = _axis_of(f)
    b1, b2 = basis_of(d)
    segs = profile.segments
    if len(segs) < 2:
        raise OccBuildError(
            f"特征 #{f.id}（{f.type.value}）{what}：轮廓段数需 ≥2（两段弧可构成整圆），"
            f"实得 {len(segs)}")
    brk = profile.chain_break()
    if brk is not None:
        s0, s1 = segs[brk], segs[(brk + 1) % len(segs)]
        raise OccBuildError(
            f"特征 #{f.id}（{f.type.value}）{what}：轮廓段序断开——段 {brk} 止点 "
            f"({s0.p2.x:.3f},{s0.p2.y:.3f}) 与段 {(brk + 1) % len(segs)} 起点 "
            f"({s1.p1.x:.3f},{s1.p1.y:.3f}) 相距 {s0.p2.distance_to(s1.p1):.3f}mm"
            "（段序必须是遍历序）")
    mk = BRepBuilderAPI_MakeWire()
    for s in segs:
        p1 = _pnt(_at(o, b1, b2, d, s.p1.x, s.p1.y, t))
        p2 = _pnt(_at(o, b1, b2, d, s.p2.x, s.p2.y, t))
        if s.kind != "arc":
            if p1.Distance(p2) <= 1e-9:
                continue          # 零长段（焊接产物）：不贡献几何，跳过
            emk = BRepBuilderAPI_MakeEdge(p1, p2)
            if not emk.IsDone():
                raise OccBuildError(
                    f"特征 #{f.id}（{f.type.value}）{what}：直线段建棱失败 "
                    f"({s.p1.x:.3f},{s.p1.y:.3f})→({s.p2.x:.3f},{s.p2.y:.3f})")
            mk.Add(emk.Edge())
            continue
        if s.center is None or s.radius <= 0.0:
            raise OccBuildError(
                f"特征 #{f.id}（{f.type.value}）{what}：弧段缺圆心/半径")
        span = ((s.ea - s.sa) if s.ccw else (s.sa - s.ea)) % (2.0 * math.pi)
        if span <= 1e-9:
            continue
        thm = s.sa + span / 2.0 if s.ccw else s.sa - span / 2.0
        pm = _pnt(_at(o, b1, b2, d,
                      s.center.x + s.radius * math.cos(thm),
                      s.center.y + s.radius * math.sin(thm), t))
        amk = GC_MakeArcOfCircle(p1, pm, p2)
        if not amk.IsDone():
            raise OccBuildError(
                f"特征 #{f.id}（{f.type.value}）{what}：弧段建弧失败")
        emk = BRepBuilderAPI_MakeEdge(amk.Value())
        if not emk.IsDone():
            raise OccBuildError(
                f"特征 #{f.id}（{f.type.value}）{what}：弧段转棱失败")
        mk.Add(emk.Edge())
    if not mk.IsDone():
        raise OccBuildError(
            f"特征 #{f.id}（{f.type.value}）{what}：{len(segs)} 段轮廓串线失败"
            "（段间不连续？）")
    fmk = BRepBuilderAPI_MakeFace(mk.Wire())
    if not fmk.IsDone():
        raise OccBuildError(
            f"特征 #{f.id}（{f.type.value}）{what}：轮廓成环建面失败（共面性/自交）")
    return fmk.Face()


def _cylinder(f: Feature, r: float, t_lo: float, t_hi: float, what: str):
    """沿特征轴、从 t_lo 到 t_hi 的圆柱（孔/凸台共用）。"""
    if r <= 0.0:
        raise OccBuildError(f"特征 #{f.id}（{f.type.value}）{what}：半径必须为正，实得 {r}")
    if t_hi - t_lo <= 0.0:
        raise OccBuildError(
            f"特征 #{f.id}（{f.type.value}）{what}：轴向区间为空（{t_lo:g}→{t_hi:g}）")
    o, d = _axis_of(f)
    base = o + d * t_lo
    return _built(BRepPrimAPI_MakeCylinder(
        gp_Ax2(_pnt(base), gp_Dir(d.x, d.y, d.z)), r, t_hi - t_lo), f, what)


# ---------------------------------------------------------------------------
# 布尔 + 自检
# ---------------------------------------------------------------------------

def _solids_of(shape: Any) -> list[Any]:
    """shape 里的所有 SOLID（explorer 遍历，不要求去重：solid 不共享）。"""
    out: list[Any] = []
    exp = TopExp_Explorer(shape, TopAbs_SOLID)
    while exp.More():
        out.append(exp.Current())
        exp.Next()
    return out


def _bbox_of(shape: Any) -> tuple[tuple[float, float, float], tuple[float, float, float]] | None:
    """各 SOLID 包围盒的并集；没有实体则 None。

    只并 SOLID 而不是裸 bbox：`verify/step_probe.py` 记着 SW 导出的 STEP 会带
    零厚度悬挂面片/游离顶点，裸 bbox 会把它们算进去而虚胖。
    """
    solids = _solids_of(shape)
    if not solids:
        return None
    box = Bnd_Box()
    for s in solids:
        # AddOptimal 而不是 Add：朴素 Add 会把**未裁剪曲面**的参数域外延算进来，
        # 斜孔 Cut 出来的盒子能比基体本身还大（见模块 docstring 的实测行）。
        # 关掉 useTriangulation —— 本模块从不做网格，走精确几何才是真盒。
        brepbndlib.AddOptimal(s, box, False, False)
    if box.IsVoid():
        return None
    x1, y1, z1, x2, y2, z2 = box.Get()
    return (x1, y1, z1), (x2, y2, z2)


def _check(shape: Any, f: Feature, validate: bool) -> None:
    """建完一个特征立刻自检：没有实体、或 B-rep 无效，都点名报错。"""
    if shape is None or shape.IsNull():
        raise OccBuildError(f"特征 #{f.id}（{f.type.value}）建完后 shape 为空")
    if not _solids_of(shape):
        raise OccBuildError(
            f"特征 #{f.id}（{f.type.value}）建完后没有实体"
            f"（布尔把它整个切空了？）")
    if validate and not BRepCheck_Analyzer(shape).IsValid():
        raise OccBuildError(
            f"特征 #{f.id}（{f.type.value}）建完后 BRepCheck_Analyzer 判定 B-rep 无效")


def _boolean(op: Any, f: Feature, what: str, validate: bool) -> Any:
    """执行一次两两布尔并做自检。**不吞** `IsDone()==False` —— 那正是要报的错。"""
    if not op.IsDone():
        raise OccBuildError(f"特征 #{f.id}（{f.type.value}）布尔失败：{what}")
    shape = op.Shape()
    _check(shape, f, validate)
    return shape


def _fuse(shape: Any, tool: Any, f: Feature, validate: bool) -> Any:
    return _boolean(BRepAlgoAPI_Fuse(shape, tool), f, "Fuse（加材料）", validate)


def _cut(shape: Any, tool: Any, f: Feature, validate: bool) -> Any:
    return _boolean(BRepAlgoAPI_Cut(shape, tool), f, "Cut（去材料）", validate)


def _add_material(shape: Any, tool: Any, f: Feature, validate: bool) -> Any:
    """加材料：第一块就是它（基体），之后一律 Union（逐特征两两融合）。"""
    if shape is None:
        _check(tool, f, validate)
        return tool
    return _fuse(shape, tool, f, validate)


def _axial_max(shape: Any, o: Point3, d: Vector3) -> float:
    """材料沿 d 的最大坐标（相对 o）—— 通孔"切穿"要它的实测值。

    取包围盒 8 个角点在轴上的投影最大值：保守（宁可多切进空气，也不留皮）。
    """
    box = _bbox_of(shape)
    if box is None:
        raise OccBuildError("取包围盒失败（当前还没有实体？）")
    (x1, y1, z1), (x2, y2, z2) = box
    best: float | None = None
    for xi in (x1, x2):
        for yi in (y1, y2):
            for zi in (z1, z2):
                t = (Point3(xi, yi, zi) - o).dot(d)
                best = t if best is None else max(best, t)
    return float(best if best is not None else 0.0)


# ---------------------------------------------------------------------------
# 棱定位（圆角/倒角的 edges 契约）
# ---------------------------------------------------------------------------

def _edges_of(shape: Any) -> list[Any]:
    """shape 的所有棱，**去重**。

    不能直接用 `TopExp_Explorer`：每条棱属于两个相邻面，遍历会把同一条访问两次
    （`sw_builder` 的 `_find_edges` 也踩过同一坑，靠"最近点"当同一性判据去重）。
    这里用 `topexp.MapShapes` + `TopTools_IndexedMapOfShape`，按 IsSame 语义去重。
    """
    m = TopTools_IndexedMapOfShape()
    topexp.MapShapes(shape, TopAbs_EDGE, m)
    return [m.FindKey(i + 1) for i in range(m.Size())]


def _edge_points(f: Feature) -> list[Point3]:
    """解析 `edges` 参数 → 一组**棱上点**（IR mm）。

    格式（与 `sw_builder._edge_points` 逐字对齐，两个发射器必须认同一串东西）：
    整体是列表/元组，或一个用 `;` 分隔的字符串；每一项可以是 `Point3`、
    `(x, y, z)` 三元组、或 `"x,y,z"` 字符串。

    点的选取要求（由 `_select_edges` 的几何定位决定）：必须**落在棱上**
    （距棱 ≤ `_EDGE_TOL`），且**不要给角点/共点** —— 角点到多条棱的距离都是 0，
    会被判为歧义而拒绝（本模块的"整圆在 seam 处被劈成两段"是同一回事）。
    **给棱中点最稳。**
    """
    raw = _opt(f, "edges", None)
    if raw is None:
        raise OccBuildError(
            f"特征 #{f.id}（{f.type.value}）缺 `edges`：圆角/倒角必须指名被处理的棱"
            f"（不能默认「全部棱」—— 那是替用户做决定）"
        )
    items = raw if isinstance(raw, (list, tuple)) else str(raw).split(";")
    out: list[Point3] = []
    for it in items:
        if isinstance(it, Point3):
            out.append(it)
            continue
        if isinstance(it, (list, tuple)) and len(it) == 3:
            out.append(Point3(float(it[0]), float(it[1]), float(it[2])))
            continue
        try:
            xs = [float(v) for v in str(it).replace(" ", "").split(",")]
        except ValueError as e:
            raise OccBuildError(f"特征 #{f.id}: 棱标识 {it!r} 解不出坐标") from e
        if len(xs) != 3:
            raise OccBuildError(f"特征 #{f.id}: 棱标识 {it!r} 需要 3 个坐标")
        out.append(Point3(*xs))
    if not out:
        raise OccBuildError(f"特征 #{f.id}: `edges` 为空")
    return out


def select_edges(shape: Any, f: Feature, tol: float = _EDGE_TOL) -> list[Any]:
    """按棱上点**几何定位**棱：点到棱的最小距离 ≤ tol 才算命中。

    为什么不用"按索引/按最近面"这类启发式：那类做法在棱被劈开（整圆 → 两段弧）
    时会静默只处理一半，体积偏一半还不报错。这里的判据只有真实距离：

    * 一条都没命中 → 报"找不到"，列出最近的距离供排查；
    * 命中 ≥2 条（并列）→ 报"歧义"，因为那意味着给的是**角点**（多条棱的公共端点，
      例如圆柱顶圆与柱面 seam 直线共用的那个顶点）—— 由调用方改给棱中点，
      本模块**绝不挑一条**。

    同一个点重复命中同一条棱（给了冗余输入）不算歧义，去重后照用。
    """
    pts = _edge_points(f)
    edges = _edges_of(shape)
    if not edges:
        raise OccBuildError(f"特征 #{f.id}（{f.type.value}）选棱失败：当前 shape 没有棱")
    selected: list[Any] = []
    redundant = 0
    for p in pts:
        v = BRepBuilderAPI_MakeVertex(_pnt(p)).Vertex()
        hits: list[tuple[float, Any]] = []
        nearest = (float("inf"), None)
        for e in edges:
            d = BRepExtrema_DistShapeShape(v, e)
            if not d.IsDone():
                raise OccBuildError(
                    f"特征 #{f.id}（{f.type.value}）选棱失败：点到棱的距离计算未完成")
            dist = float(d.Value())
            if dist < nearest[0]:
                nearest = (dist, e)
            if dist <= tol:
                hits.append((dist, e))
        if not hits:
            raise OccBuildError(
                f"特征 #{f.id}（{f.type.value}）选棱失败：模型上找不到 IR 点 "
                f"({p.x:g}, {p.y:g}, {p.z:g}) 附近 {tol:g}mm 内的棱"
                f"（最近的一条也有 {nearest[0]:.4f}mm）"
            )
        if len(hits) > 1:
            # 只按距离排序：TopoDS_Edge 之间没有序关系，直接 sorted(元组) 会 TypeError
            ds = "、".join(f"{d:.6f}" for d, _ in sorted(hits, key=lambda t: t[0])[:4])
            raise OccBuildError(
                f"特征 #{f.id}（{f.type.value}）选棱有歧义：IR 点 "
                f"({p.x:g}, {p.y:g}, {p.z:g}) {tol:g}mm 内命中 {len(hits)} 条棱"
                f"（距离 {ds}）—— 给的多半是**角点**（多条棱的公共端点，"
                f"如圆柱顶圆与柱面 seam 直线共用的顶点）；请改给**棱中点**"
            )
        e = hits[0][1]
        if any(e.IsSame(x) for x in selected):
            redundant += 1                     # 同一棱被重复指名：去重，但要说出来
        else:
            selected.append(e)
    if redundant:
        print(f"  [emit] 特征 #{f.id}：edges 里 {redundant} 个点指向已选中的棱，已去重")
    return selected


# ---------------------------------------------------------------------------
# 逐特征建模
# ---------------------------------------------------------------------------

def _profile_desc(profile: Any) -> str:
    """轮廓的描述串（点列 vs Profile2 两种契约的记账口径）。"""
    if isinstance(profile, Profile2):
        n_arc = sum(1 for s in profile.segments if s.kind == "arc")
        return f"{len(profile.segments)} 段轮廓（{n_arc} 弧）"
    return f"{len(profile)} 点轮廓"


def _profile_bbox_ab(profile: Any) -> tuple[float, float, float, float]:
    """轮廓在 (a, b) 系里的 bbox —— ``Profile2`` 含弧的四象限极值，点列取端点包围盒。"""
    if isinstance(profile, Profile2):
        bb = profile.bbox()
        return bb.xmin, bb.ymin, bb.xmax, bb.ymax
    xs = [float(p[0]) for p in profile]
    ys = [float(p[1]) for p in profile]
    return min(xs), min(ys), max(xs), max(ys)


def _scaled_profile(f: Feature, profile: Any, sa: float, sb: float,
                    what: str) -> Any | None:
    """轮廓相对 bbox 中心按 (sa, sb) 缩放；两轴都缩到 0 时返回 None（收敛成一点）。

    弧在**非等比**缩放下会变成椭圆（``ProfileSeg2`` 表达不了）⇒ 显式拒绝；
    等比缩放（sa == sb > 0）时半径与圆心同步缩放、角度与走向不变。
    """
    if sa < 0.0 or sb < 0.0:
        raise OccBuildError(
            f"特征 #{f.id}（{f.type.value}）{what}：锥化缩放系数不能为负"
            f"（({sa:g},{sb:g})；负系数 = 翻面镜像，不在契约内）")
    x0, y0, x1, y1 = _profile_bbox_ab(profile)
    ca, cb = (x0 + x1) / 2.0, (y0 + y1) / 2.0
    # ⚠️ 缩放系数是**无量纲**的，不能用 _EPS = 0.5（那是切割余量 mm）：
    # 0.3 的锥化在它眼里会变成"退化到一点"
    if abs(sa) < 1e-9 and abs(sb) < 1e-9:
        return None
    if isinstance(profile, Profile2):
        if abs(sa - sb) > 1e-9 and any(s.kind == "arc" for s in profile.segments):
            raise OccBuildError(
                f"特征 #{f.id}（{f.type.value}）{what}：含弧轮廓不支持非等比锥化"
                f"（({sa:g},{sb:g}) 会把弧缩成椭圆，轮廓契约表达不了）")
        out = []
        for s in profile.segments:
            c = s.center
            out.append(ProfileSeg2(
                s.kind,
                Point2(ca + sa * (s.p1.x - ca), cb + sb * (s.p1.y - cb)),
                Point2(ca + sa * (s.p2.x - ca), cb + sb * (s.p2.y - cb)),
                None if c is None else Point2(ca + sa * (c.x - ca),
                                              cb + sb * (c.y - cb)),
                s.radius * sa if s.kind == "arc" else 0.0,
                s.ccw, s.sa, s.ea))
        return Profile2(tuple(out))
    return [(ca + sa * (float(p[0]) - ca), cb + sb * (float(p[1]) - cb))
            for p in profile]


def _loft_taper(f: Feature, profile: Any, length: float,
                sa: float, sb: float) -> Any:
    """底面轮廓（t=0）+ 顶部缩放截面（t=length）放样成锥化体。

    两个截面走同一条 `BRepOffsetAPI_ThruSections`：顶面退化（sa=sb=0）时
    改喂 ``AddVertex``（实测：60×60 底 + 顶点 = 棱锥实体，体积与解析值
    逐位一致 72,000.0；截锥路径 126,000.0 亦为解析值）。
    """
    if length <= 0.0:
        raise OccBuildError(f"特征 #{f.id}（{f.type.value}）锥化拉伸长度必须为正，实得 {length}")
    o, d = _axis_of(f)
    b1, b2 = basis_of(d)
    bottom = _profile_face(f, profile, 0.0, "基体底面")
    bw = breptools.OuterWire(bottom)
    if bw.IsNull():
        raise OccBuildError(f"特征 #{f.id}（{f.type.value}）基体底面取外环失败")
    mk = BRepOffsetAPI_ThruSections(True, True)     # isSolid, ruled（直纹面）
    mk.AddWire(bw)
    top_profile = _scaled_profile(f, profile, sa, sb, "基体顶面")
    if top_profile is None:
        x0, y0, x1, y1 = _profile_bbox_ab(profile)
        apex = _at(o, b1, b2, d, (x0 + x1) / 2.0, (y0 + y1) / 2.0, length)
        mk.AddVertex(BRepBuilderAPI_MakeVertex(_pnt(apex)).Vertex())
    else:
        top = _profile_face(f, top_profile, length, "基体顶面")
        tw = breptools.OuterWire(top)
        if tw.IsNull():
            raise OccBuildError(f"特征 #{f.id}（{f.type.value}）基体顶面取外环失败")
        mk.AddWire(tw)
    return _built(mk, f, "锥化拉伸")


def _build_base(shape: Any, f: Feature, validate: bool) -> tuple[Any, str]:
    """BASE：闭合轮廓沿轴拉伸成基体（零件的第一块材料）。

    ``taper_scale``（可选）给顶部截面的缩放 (sa, sb)：缺省 / ``(1, 1)`` 走
    直棱柱（``_extrude``），否则走 ``_loft_taper`` 放样 —— ``(0, 0)`` 是
    收敛到一点的棱锥（``图形练习`` 的四棱锥）。
    """
    o, d = _axis_of(f)
    length = float(_param(f, "length"))
    profile = _param(f, "profile")
    taper = _opt(f, "taper_scale", None)
    if taper is not None and not (abs(float(taper[0]) - 1.0) < 1e-12
                                  and abs(float(taper[1]) - 1.0) < 1e-12):
        sa, sb = float(taper[0]), float(taper[1])
        tool = _loft_taper(f, profile, length, sa, sb)
        return _add_material(shape, tool, f, validate), \
            (f"base 锥化拉伸 {_profile_desc(profile)} h={length:g}mm "
             f"顶部缩放 ({sa:g},{sb:g}) 沿 ({d.x:g},{d.y:g},{d.z:g})")
    face = _profile_face(f, profile, 0.0, "基体轮廓")
    tool = _extrude(face, d, length, f, "基体拉伸")
    return _add_material(shape, tool, f, validate), \
        f"base 拉伸 {_profile_desc(profile)} h={length:g}mm 沿 ({d.x:g},{d.y:g},{d.z:g})"


def _build_revolve(shape: Any, f: Feature, validate: bool) -> tuple[Any, str]:
    """REVOLVE：母线 `radius_profile = [(沿轴坐标, 半径)]` 绕轴回转。

    母线要**闭合成环**：末点 → 轴上垂足 → 沿轴回到首点垂足 → 首点。
    落在轴上的点（半径 0）与垂足重合，去重后自动省掉零长边 ——
    实测 `MakeRevol` 吃"闭合环含轴段"毫无问题，不需要偷偷离轴 ε
    （旧管线 `_tor9` 的 53.7% 空心体正是"把边画在旋转轴上"另加了一套错误的
    保护体补丁造成的，那是补丁的错，不是核的错）。
    """
    o, d = _axis_of(f)
    ang = float(_param(f, "angle_deg"))
    profile = _param(f, "radius_profile")
    if not isinstance(profile, (list, tuple)) or len(profile) < 2:
        raise OccBuildError(
            f"特征 #{f.id}（revolve）母线至少 2 点，实得 {profile!r}")
    if ang <= 0.0:
        raise OccBuildError(f"特征 #{f.id}（revolve）回转角必须为正，实得 {ang}")
    b1, b2 = basis_of(d)
    # 母线点：(沿轴 t, 半径 r) → o + b1·r + d·t。径向取 b1（不是 b2）——
    # 回转体是绕轴的，径向取哪条都一样，但取 b1 与 `profile` 的 (a,b) 约定同源。
    pts = [_at(o, b1, b2, d, float(r), 0.0, float(t)) for t, r in profile]
    # 闭合成环：末点 → 轴上垂足 → 沿轴 → 首点的轴上垂足 → 首点（端点 r=0 时自动重合）
    face = _polygon_face(pts + [_at(o, b1, b2, d, 0.0, 0.0, (p - o).dot(d))
                                for p in (pts[-1], pts[0])], f, "回转母线")
    tool = _built(BRepPrimAPI_MakeRevol(
        face, gp_Ax1(_pnt(o), gp_Dir(d.x, d.y, d.z)), library.radians(ang)),
        f, f"回转（{len(profile)} 点母线）")
    return _add_material(shape, tool, f, validate), \
        f"revolve {len(profile)} 点母线 {ang:g}° 绕 ({d.x:g},{d.y:g},{d.z:g})"


def _build_boss(shape: Any, f: Feature, validate: bool) -> tuple[Any, str]:
    """BOSS：圆柱凸台，自 `axial_at` 沿轴长出 `height`。"""
    r = float(_param(f, "radius"))
    h = float(_param(f, "height"))
    if h <= 0.0:
        raise OccBuildError(f"特征 #{f.id}（boss）高度必须为正，实得 {h}")
    t0 = _axial_at(f)
    tool = _cylinder(f, r, t0, t0 + h, "凸台")
    return _add_material(shape, tool, f, validate), f"boss Ø{2 * r:g}×{h:g} 自 {t0:g}"


def _build_hole(shape: Any, f: Feature, validate: bool) -> tuple[Any, str]:
    """HOLE：圆柱切除。`through=True` 切穿材料（按实测算深度，不用贯穿条件）。"""
    o, d = _axis_of(f)
    r = float(_param(f, "radius"))
    through = bool(_param(f, "through"))
    count = int(_opt(f, "count", 0) or 0)
    if count > 1:
        # 契约只说"同一轴上的孔数"，没给分布（间距/阵列）—— 按 1 个孔建就是**少建**，
        # 静默少建正是旧管线的病，故宁可拒绝（与 sw_builder 同判）。
        raise OccBuildError(
            f"特征 #{f.id}（hole）count={count} > 1：契约未定义这些孔如何分布"
            f"（间距/角度均缺），无法忠实发射；请改用 PATTERN 或补齐分布参数"
        )
    if shape is None:
        raise OccBuildError(f"特征 #{f.id}（hole）没有基体可切")
    t0 = _axial_at(f)                               # 契约：HOLE 的 axial_at = 孔口
    # 方向约定（两个发射器一致）：**轴向 = 钻入方向**，孔自孔口朝 +轴向 延伸。
    # 于是"自上而下钻盲孔"要写成轴指向 −z（而不是把 axial_at 填成孔底）——
    # 通孔那支也依赖同一约定（材料必须在孔口的 +轴向 一侧），两处自洽。
    if through:
        t_hi = _axial_max(shape, o, d) + _EPS
        t_lo = min(t0, t_hi - _EPS) - _EPS
        how = "通孔"
    else:
        depth = float(_param(f, "depth"))           # 契约：through=True 时忽略 depth
        t_lo, t_hi = t0, t0 + depth
        how = f"盲孔深{depth:g}（自 {t0:g} 朝 +轴向）"
    tool = _cylinder(f, r, t_lo, t_hi, how)
    return _cut(shape, tool, f, validate), f"cut Ø{2 * r:g} {how}"


def _build_pocket(shape: Any, f: Feature, validate: bool) -> tuple[Any, str]:
    """POCKET：闭合轮廓腔。契约里 `axial_at` = **腔底**，故自底向上挖 depth。"""
    profile = _param(f, "profile")
    depth = float(_param(f, "depth"))
    if depth <= 0.0:
        raise OccBuildError(f"特征 #{f.id}（pocket）深度必须为正，实得 {depth}")
    t_bot = _axial_at(f)
    o, d = _axis_of(f)
    face = _profile_face(f, profile, t_bot, "腔轮廓")
    tool = _extrude(face, d, depth, f, "腔拉伸")
    if shape is None:
        raise OccBuildError(f"特征 #{f.id}（pocket）没有基体可切")
    return _cut(shape, tool, f, validate), \
        f"cut 腔 {_profile_desc(profile)} 深{depth:g} 底 {t_bot:g}"


def _build_slot(shape: Any, f: Feature, validate: bool) -> tuple[Any, str]:
    """SLOT：矩形槽，以轴为中心，`length` 沿 b1 × `width` 沿 b2 × `depth` 沿轴。

    ⚠️ 契约缺口（见模块 docstring 第 2 条）：`library._predict_slot` 把 `length`
    画在**轴**上，与本约定（及 `sw_builder`）冲突。两个发射器先对齐同一套，
    预测层那条另案处理。
    """
    width = float(_param(f, "width"))
    length = float(_param(f, "length"))
    depth = float(_param(f, "depth"))
    for label, v in (("width", width), ("length", length), ("depth", depth)):
        if v <= 0.0:
            raise OccBuildError(f"特征 #{f.id}（slot）{label} 必须为正，实得 {v}")
    t_bot = _axial_at(f)                             # 契约：SLOT 的 axial_at = 槽底
    hw, hl = width / 2.0, length / 2.0
    face = _profile_face(f, [(-hl, -hw), (hl, -hw), (hl, hw), (-hl, hw)],
                         t_bot, "槽轮廓")
    o, d = _axis_of(f)
    tool = _extrude(face, d, depth, f, "槽拉伸")
    if shape is None:
        raise OccBuildError(f"特征 #{f.id}（slot）没有基体可切")
    return _cut(shape, tool, f, validate), \
        f"cut 槽 {length:g}×{width:g} 深{depth:g} 底 {t_bot:g}"


def _build_fillet(shape: Any, f: Feature, validate: bool) -> tuple[Any, str]:
    """FILLET：等半径圆角，棱由 `params["edges"]` 的棱上点定位。"""
    r = float(_param(f, "radius"))
    if r <= 0.0:
        raise OccBuildError(f"特征 #{f.id}（fillet）半径必须为正，实得 {r}")
    if shape is None:
        raise OccBuildError(f"特征 #{f.id}（fillet）没有基体可倒圆")
    edges = select_edges(shape, f)
    mk = BRepFilletAPI_MakeFillet(shape)
    for e in edges:
        mk.Add(r, e)
    mk.Build()
    if not mk.IsDone():
        raise OccBuildError(
            f"特征 #{f.id}（fillet）R{r:g} 建失败（{len(edges)} 条棱 —— "
            f"半径过大/相邻圆角干涉时核会拒绝）")
    out = mk.Shape()
    _check(out, f, validate)
    return out, f"fillet R{r:g} × {len(edges)} 棱"


def _build_chamfer(shape: Any, f: Feature, validate: bool) -> tuple[Any, str]:
    """CHAMFER：等距倒角（45°），棱由 `params["edges"]` 的棱上点定位。

    ⚠️ 契约缺口（见模块 docstring 第 4 条）：`angle_deg ≠ 45` 时 OCC 要用
    `AddDA(d1, d2, E, F)`，其中 F 是"距离 d1 量在哪个相邻面"的参考面 ——
    契约没给这个信息，两个选择会给出**不同**的几何。宁可拒绝也不替用户拍板。
    """
    dist = float(_param(f, "distance"))
    ang = float(_opt(f, "angle_deg", 45.0) or 45.0)
    if dist <= 0.0:
        raise OccBuildError(f"特征 #{f.id}（chamfer）倒角距离必须为正，实得 {dist}")
    if abs(ang - 45.0) > 1e-6:
        raise OccBuildError(
            f"特征 #{f.id}（chamfer）角度 {ang:g}° 暂不支持：契约未定义"
            f"「距离量在哪个相邻面上」（OCC 的 AddDA 必须指定参考面，"
            f"两个选择几何不同）。只支持 45° 等距倒角。"
        )
    if shape is None:
        raise OccBuildError(f"特征 #{f.id}（chamfer）没有基体可倒角")
    edges = select_edges(shape, f)
    mk = BRepFilletAPI_MakeChamfer(shape)
    for e in edges:
        mk.Add(dist, e)
    mk.Build()
    if not mk.IsDone():
        raise OccBuildError(
            f"特征 #{f.id}（chamfer）C{dist:g} 建失败（{len(edges)} 条棱）")
    out = mk.Shape()
    _check(out, f, validate)
    return out, f"chamfer C{dist:g} × {len(edges)} 棱"


def _build_pattern(shape: Any, f: Feature, part: Part, built: set[FeatureId],
                   validate: bool, allow_guess: bool = False) -> tuple[Any, str]:
    """PATTERN：目前只支持**圆形阵列**（把 child 的几何绕阵列轴复制后重发一遍）。

    为什么不用 OCC 的原生阵列：同 `sw_builder` 的取舍 —— 几何重发让每个副本
    都是**独立可核查**的一步（每步都过 BRepCheck），失败模式不再静默。
    ⚠️ 契约缺口：线性阵列只有 `pitch`、**没有方向**，无法确定往哪儿排 → 拒绝。
    """
    kind = str(_param(f, "kind"))
    count = int(_param(f, "count"))
    # 阵列中心 = 特征的 `placement`（与其它特征同一约定：位置只记一处）；
    # `center` 参数是可选的历史写法，给了才压过 placement。识别层挂的就是
    # placement（`pattern_features` 的 `center3`），早期版本只认 params 会
    # 误报"缺 center"，把一条本来完备的阵列挡在门外（flange_d80/法兰练习/PF60K）。
    center = _opt(f, "center", None)
    if center is None and f.placement is not None:
        center = f.placement.value
    child_id = _opt(f, "child", None)
    if kind != "circular":
        raise OccBuildError(
            f"特征 #{f.id}（pattern）kind={kind!r} 暂不支持"
            f"（线性阵列契约缺方向参数 —— 只有 pitch 无法确定往哪儿排）")
    if count < 2:
        raise OccBuildError(f"特征 #{f.id}（pattern）count={count} < 2 不构成阵列")
    if not isinstance(center, Point3):
        raise OccBuildError(f"特征 #{f.id}（pattern）缺 `center`（圆形阵列的分布圆圆心）")
    if child_id is None:
        raise OccBuildError(f"特征 #{f.id}（pattern）缺 `child`（被阵列的特征 id）")
    try:
        child = part.by_id(FeatureId(int(child_id)))
    except KeyError as e:
        raise OccBuildError(f"特征 #{f.id}（pattern）的 child={child_id!r} 不在特征树里") from e
    if child.id not in built:
        # 依赖没写在 depends_on 里就会走到这 —— 不报的话 child 会被建两次
        # （阵列一次 + 它自己一次），孔数凭空多一个，妥妥的静默错几何。
        raise OccBuildError(
            f"特征 #{f.id}（pattern）的 child=#{child.id} 尚未建出："
            f"`depends_on` 里必须列它（否则容器顺序会让 child 被建两次）")
    if child.type.value in (FeatureType.FILLET.value, FeatureType.CHAMFER.value):
        raise OccBuildError(
            f"特征 #{f.id}（pattern）的 child=#{child.id} 是 {child.type.value}："
            f"圆角/倒角不是「轴向工具体」，无法按几何重发阵列")
    co, cd = _axis_of(child)
    bc = _opt(f, "bc_radius", None)
    if bc is not None:
        r_now = ((co - center).cross(cd.normalized())).norm
        if abs(float(bc) - r_now) > 1e-3:
            raise OccBuildError(
                f"特征 #{f.id}（pattern）的 bc_radius={float(bc):g} 与"
                f"child 实际所在半径 {r_now:g} 不符 —— 阵列只会绕 center 复制"
                f"child 的现位置，两者不一致时发出来的分布圆是错的")
    start = float(_opt(f, "start_deg", 0.0) or 0.0)
    # 阵列实例位置**已被其它特征占掉**的就不重发（判据与 `sw_builder.pattern_plan` 同）：
    # 识别器会同时产出"逐个孔各是一个特征"与"这些孔构成阵列"，位置逐个重合。
    # OCC 侧重复发射几何上无害（同处再切一刀/再并一块，结果不变），跳过是为了
    # 少做一次布尔、也避免共面布尔留下可疑面 —— 但**记账**必须做：跳过意味着
    # 那个实例是靠别的 IR 特征建的，验收核"特征数一致"时要认这笔账。
    sibs = [g for g in part.features
            if g.id != f.id and g.id != child.id
            and g.type.value == child.type.value]
    r_child = _opt(child, "radius", None)
    out: list[str] = []
    skipped: list[str] = []
    for i in range(1, count):                     # 第 0 个 = child 自身
        deg = start + i * 360.0 / count
        p = _rotate_about(co, center, cd, deg)
        hit = _twin_at(sibs, p, r_child)
        if hit is not None:
            skipped.append(str(hit.id))
            continue
        ghost = _clone_at(child, p, cd)
        # built 原样透传：ghost 是**已建好的子树**的副本，它眼里的"已建"应与原件
        # 一致；把 child.id 抠掉只会让嵌套阵列（child 本身又是阵列）误报"尚未建出"
        shape, info = _dispatch(shape, ghost, part, built, validate, allow_guess)
        out.append(f"{deg:g}°")
    tail = f"（副本 {', '.join(out)}）" if out else "（无需新建几何）"
    if skipped:
        tail += f"；{len(skipped)} 处实例已由 IR #{'、#'.join(skipped)} 建出，不重复发射"
    return shape, f"circular pattern × {count}{tail}"


def _twin_at(sibs: list[Feature], p: Point3, r_ref: Any) -> Feature | None:
    """在 `sibs` 里找"轴心落在 p（容差 `_PATTERN_TOL`）"的特征（没有则 None）。

    半径也差不多一致才算同一个孔：两个不同直径的同心孔不该互相顶掉。
    """
    for g in sibs:
        o, _d = _axis_of(g)
        if abs(o.x - p.x) > _PATTERN_TOL or abs(o.y - p.y) > _PATTERN_TOL \
                or abs(o.z - p.z) > _PATTERN_TOL:
            continue
        r_g = _opt(g, "radius", None)
        if r_ref is not None and r_g is not None and abs(float(r_ref) - float(r_g)) > 0.05:
            continue
        return g
    return None


def _clone_at(f: Feature, origin: Point3, direction: Vector3) -> Feature:
    """复制一个特征，把它的轴平移到 origin（阵列重发用）。"""
    return Feature(
        id=f.id, type=f.type, params=dict(f.params), placement=f.placement,
        axis=Claim(Axis3(origin, direction), "pattern:rotate", Tier.GUESS),
        depends_on=list(f.depends_on), evidence=list(f.evidence),
        source_view=f.source_view,
    )


def _rotate_about(p: Point3, axis_pt: Point3, axis_dir: Vector3, deg: float) -> Point3:
    """绕 (axis_pt, axis_dir) 把点 p 旋转 deg 度（Rodrigues）。"""
    k = axis_dir.normalized()
    v = p - axis_pt
    th = library.radians(deg)
    c, s = math.cos(th), math.sin(th)
    return axis_pt + v * c + k.cross(v) * s + k * (k.dot(v) * (1.0 - c))


#: 特征类型 → 建模函数。签名分两种：pattern 要多几个上下文参数。
_BUILDERS: dict[FeatureType, Callable[..., tuple[Any, str]]] = {
    FeatureType.BASE: _build_base,
    FeatureType.REVOLVE: _build_revolve,
    FeatureType.BOSS: _build_boss,
    FeatureType.HOLE: _build_hole,
    FeatureType.POCKET: _build_pocket,
    FeatureType.SLOT: _build_slot,
    FeatureType.FILLET: _build_fillet,
    FeatureType.CHAMFER: _build_chamfer,
}


def _dispatch(shape: Any, f: Feature, part: Part, built: set[FeatureId],
              validate: bool, allow_guess: bool = False) -> tuple[Any, str]:
    """按类型发一个特征；类型未定/缺参数/无实现一律点名报错。

    ``allow_guess`` 是**调用方的决定**，不是发射器的：发射器只负责把
    "这个类型是猜的"如实报出来，该不该照样建由上游（``pipeline.rebuild``
    的 ``force``）说了算。默认 False —— 歧义未消解就发射，等于替用户拍板。
    """
    if f.is_hypothesis:
        if not allow_guess:
            raise OccBuildError(
                f"特征 #{f.id} 的类型仍未定（{f.type.value}，备选 "
                f"{[a.value for a in f.type.alternatives]}）：歧义未消解就发射，等于替用户拍板"
            )
        print(f"  [GUESS] #{f.id} 类型 {f.type.value} 是**猜的**"
              f"（备选 {[a.value for a in f.type.alternatives]}）—— "
              "调用方给了 allow_guess，照主值建")
    t = FeatureType(f.type.value)
    missing = library.missing_params(f)
    if missing:
        raise OccBuildError(f"特征 #{f.id}（{t.value}）缺必需参数 {missing}（不默认 0）")
    if t is FeatureType.PATTERN:
        return _build_pattern(shape, f, part, built, validate, allow_guess)
    fn = _BUILDERS.get(t)
    if fn is None:
        raise OccBuildError(f"特征 #{f.id} 的类型 {t.value} 尚无 OCC 发射实现")
    return fn(shape, f, validate)


# ---------------------------------------------------------------------------
# 建模主流程
# ---------------------------------------------------------------------------

def build_shape(part: Part, *, validate: bool = True,
                allow_guess: bool = False) -> Any:
    """把特征树建成一个 OCC 实体（`TopoDS_Shape`）。

    顺序由 `features/library.build_order` 定（先基体 → 凸台 → 切除 → 圆角/倒角；
    显式 `depends_on` 优先于层号），**不按 features 列表的书写顺序建** ——
    布尔序错在 SW 会静默失败，在 OCC 会造出错误的形状。

    `validate=True` 时每条特征建完做一次 `BRepCheck_Analyzer`，不通过即抛
    `OccBuildError` 并指名特征 id（不做"先建完再统一检查"—— 那样报不出是谁坏的）。

    `allow_guess` 见 `_dispatch`：默认拒绝发射任何**类型未定**的特征（那是在
    替用户拍板）；置 True 时按主值建并在 stdout 打 `[GUESS]` 记账 ——
    它的用途只有一个：拿"歧义未消解"的树去和旧管线基线做**可比性**测量。
    """
    features = list(part.features)
    try:
        order = library.build_order(features)
    except ValueError as e:                          # 依赖成环
        raise OccBuildError(f"特征树拓扑排序失败: {e}") from e
    if not order:
        raise OccBuildError("特征树是空的，没有可建的特征")
    kinds = {FeatureType(f.type.value) for f in order
             if f.type.is_settled or allow_guess}
    if not kinds & {FeatureType.BASE, FeatureType.REVOLVE}:
        raise OccBuildError(
            "特征树里没有基体（BASE/REVOLVE）：没有第一块材料，后续凸台/切除都无处安放")
    bad = [(f, library.missing_params(f)) for f in order if library.missing_params(f)]
    if bad:
        raise OccBuildError(
            "以下特征缺必需参数，拒绝建模（宁可拒绝，也不静默建出个错的）："
            + "; ".join(f"#{f.id} 缺{m}" for f, m in bad))

    print(f"[emit] 建模顺序: {[f'#{f.id}:{f.type.value}' for f in order]}")
    shape: Any = None
    built: set[FeatureId] = set()
    for f in order:
        try:
            shape, info = _dispatch(shape, f, part, built, validate, allow_guess)
        except OccBuildError:
            raise
        except Exception as e:                       # OCC 异常也要带上特征 id
            raise OccBuildError(f"特征 #{f.id}（{f.type.value}）建模抛异常: {e}") from e
        built.add(f.id)
        print(f"  [OK] #{f.id:<3} {f.type.value:8} {info}")
    if shape is None:
        raise OccBuildError("建模结束但没有任何实体")
    return shape


def measure_shape(shape: Any) -> tuple[float, tuple[float, float, float] | None, int]:
    """(体积 mm³, 逐轴 bbox (dx,dy,dz) 或 None, 实体数)。

    bbox 取**各 SOLID 包围盒的并集**（同 `verify/step_probe.py`）：悬挂面片
    不属于任何 solid，自然被排除。
    """
    box = _bbox_of(shape)
    ext = None if box is None else (box[1][0] - box[0][0], box[1][1] - box[0][1],
                                    box[1][2] - box[0][2])
    return volume_of(shape), ext, len(_solids_of(shape))


def write_step(shape: Any, path: Path) -> Path:
    """把一个 OCC shape 写成 STEP（`STEPControl_AsIs`，单位随内核 = mm）。"""
    p = Path(path)
    if p.parent and str(p.parent) not in ("", "."):
        p.parent.mkdir(parents=True, exist_ok=True)
    w = STEPControl_Writer()
    # 写 STEP 时内核会往 stdout 直接打统计块（C++ 侧），而 Python 的 stdout 是
    # 带缓冲的 —— 不先 flush 的话重定向到文件时这批统计会跑到我们自己的打印**前面**。
    sys.stdout.flush()
    if w.Transfer(shape, STEPControl_AsIs) != 1:
        raise OccBuildError(f"STEP Transfer 失败: {p}")
    if w.Write(str(p)) != 1:
        raise OccBuildError(f"STEP 写出失败: {p}")
    sys.stdout.flush()
    return p


def build_step(part: Part, path: Path, *, validate: bool = True,
               allow_guess: bool = False) -> Path:
    """特征树 → STEP 文件。返回**实际写入**的路径（本函数不改名、不加时间戳 ——

    SW 侧之所以要时间戳后缀，是因为 SW 进程会锁住文件导致保存失败；STEP 是
    普通文件写，调用方想覆盖就覆盖。**文件名由调用方负责唯一**。
    """
    return write_step(build_shape(part, validate=validate,
                                  allow_guess=allow_guess), Path(path))


def read_step_volume(path: Path) -> tuple[float, int]:
    """读回 STEP 量 (体积, 实体数) —— 导出后的独立复核用（demo 里跑）。"""
    r = STEPControl_Reader()
    if r.ReadFile(str(path)) != 1:
        raise OccBuildError(f"STEP 读取失败: {path}")
    r.TransferRoots()
    shape = r.OneShape()
    if shape.IsNull():
        raise OccBuildError(f"STEP 内容为空: {path}")
    return volume_of(shape), len(_solids_of(shape))


# ---------------------------------------------------------------------------
# 自证 demo
# ---------------------------------------------------------------------------

def _claim(v: Any) -> Claim[Any]:
    """手工构造用的 Claim（**没有图纸依据**，故只能是 guess —— 它就该被报出来）。"""
    return Claim(v, "demo:handmade", Tier.GUESS)


@dataclass(frozen=True)
class _Scenario:
    """一个自证场景：解析真值 + 期望（正例核对体积，负例核对报错）。"""

    name: str
    make: Callable[[], Part]
    volume: float = 0.0
    extents: tuple[float, float, float] = (0.0, 0.0, 0.0)
    #: 非空 = **负例**：期待建模抛 OccBuildError 且消息里含这段文字
    expect_error: str = ""
    note: str = ""


def _demo_plate_hole() -> Part:
    """100×60×20 板 + Ø10 通孔。

    解析体积 = 100·60·20 − π·5²·20 = 120000 − 1570.796327 = 118429.203673 mm³
    """
    p = Part()
    p.add(Feature(
        id=FeatureId(0), type=_claim(FeatureType.BASE),
        params={"dir": _claim("z"), "length": _claim(20.0),
                "profile": _claim([(0.0, 0.0), (100.0, 0.0), (100.0, 60.0), (0.0, 60.0)])},
        axis=_claim(Axis3(Point3(0.0, 0.0, 0.0), _DIRS["z"])),
    ))
    p.add(Feature(
        id=FeatureId(1), type=_claim(FeatureType.HOLE),
        params={"radius": _claim(5.0), "through": _claim(True), "axial_at": _claim(0.0)},
        axis=_claim(Axis3(Point3(50.0, 30.0, 0.0), _DIRS["z"])),
        depends_on=[FeatureId(0)],
    ))
    return p


def _demo_shaft() -> Part:
    """三段阶梯轴（Ø20/Ø12/Ø8 各长 20）+ Ø6 轴向通孔。

    解析体积 = π(10²+6²+4²)·20 − π·3²·60 = 3040π − 540π = 2500π = 7853.981634 mm³
    """
    p = Part()
    p.add(Feature(
        id=FeatureId(0), type=_claim(FeatureType.REVOLVE),
        params={"angle_deg": _claim(360.0), "dir": _claim("z"),
                "radius_profile": _claim([(0.0, 10.0), (20.0, 10.0), (20.0, 6.0),
                                          (40.0, 6.0), (40.0, 4.0), (60.0, 4.0)])},
        axis=_claim(Axis3(Point3(0.0, 0.0, 0.0), _DIRS["z"])),
    ))
    p.add(Feature(
        id=FeatureId(1), type=_claim(FeatureType.HOLE),
        params={"radius": _claim(3.0), "through": _claim(True), "axial_at": _claim(0.0)},
        axis=_claim(Axis3(Point3(0.0, 0.0, 0.0), _DIRS["z"])),
        depends_on=[FeatureId(0)],
    ))
    return p


def _demo_plate_boss() -> Part:
    """40×40×10 板 + Ø16×10 凸台 + 板四竖棱 R3 圆角 + 凸台顶圆 C2 倒角。

    解析体积 = 16000 + π·8²·10 − 4·(3² − π·3²/4)·10 − [π·8²·2 − (π·2/3)(8²+8·6+6²)]
            = 16000 + 2010.619298 − 77.256660 − 92.153386 = 17841.209252 mm³
    （倒角那一项用 Pappus 独立验过：(r,z) 半平面里被削掉的三角形
      (8,18)-(8,20)-(6,20)，面积 2、形心半径 22/3 ⇒ 2π·2·(22/3) = 88π/3 = 92.153386）

    **edges 是本场景的重点**：凸台顶面那条棱是**一条 360° 的整圆**（不是两段半圆），
    所以一个棱中点就够 —— 取角 90° 的 (20,28,20)（避开它的两个端点）。
    若图省事给 seam 顶点 (28,20,20)：它同时落在"顶圆"与"柱面 seam 直线"上，
    距离并列 → 按"并列即歧义"被拒（见负例场景 reject_corner）。
    """
    p = Part()
    p.add(Feature(
        id=FeatureId(0), type=_claim(FeatureType.BASE),
        params={"dir": _claim("z"), "length": _claim(10.0),
                "profile": _claim([(0.0, 0.0), (40.0, 0.0), (40.0, 40.0), (0.0, 40.0)])},
        axis=_claim(Axis3(Point3(0.0, 0.0, 0.0), _DIRS["z"])),
    ))
    p.add(Feature(
        id=FeatureId(1), type=_claim(FeatureType.BOSS),
        params={"radius": _claim(8.0), "height": _claim(10.0), "axial_at": _claim(10.0)},
        axis=_claim(Axis3(Point3(20.0, 20.0, 0.0), _DIRS["z"])),
        depends_on=[FeatureId(0)],
    ))
    p.add(Feature(
        id=FeatureId(2), type=_claim(FeatureType.CHAMFER),
        params={"distance": _claim(2.0), "angle_deg": _claim(45.0),
                "edges": _claim("20,28,20")},
        depends_on=[FeatureId(1)],
    ))
    p.add(Feature(
        id=FeatureId(3), type=_claim(FeatureType.FILLET),
        params={"radius": _claim(3.0),
                "edges": _claim(["0,0,5", "40,0,5", "40,40,5", "0,40,5"])},
        depends_on=[FeatureId(0)],
    ))
    return p


def _demo_plate_pocket_slot() -> Part:
    """100×60×20 板 + 盲孔 + 腔 + 槽（三个切除特征互不重叠）。

    解析体积 = 120000 − π·5²·6 − 30·20·5 − 8·20·4
            = 120000 − 471.238898 − 3000 − 640 = 115888.761102 mm³

    这一场是给 HOLE(through=False) / POCKET / SLOT 三条 builder 用的：
    `axial_at` 的三套语义（孔口 / 腔底 / 槽底）只有真建出来量体积才验得了。
    腔与槽的轮廓都**不碰板的侧面**（共面切除是几何核的老坑）。
    """
    p = Part()
    p.add(Feature(
        id=FeatureId(0), type=_claim(FeatureType.BASE),
        params={"dir": _claim("z"), "length": _claim(20.0),
                "profile": _claim([(0.0, 0.0), (100.0, 0.0), (100.0, 60.0), (0.0, 60.0)])},
        axis=_claim(Axis3(Point3(0.0, 0.0, 0.0), _DIRS["z"])),
    ))
    p.add(Feature(                                  # 盲孔：口在 z=20，自上而下钻 6
        # 轴向 = 钻入方向，所以轴指向 −z、axial_at=0（= 轴原点处 = 顶面）。
        # 写成 dir=+z 而 axial_at=20 的话孔会朝 z=26 钻进空气里 —— 那是调用方
        # 把"孔口"错当成"孔底"了，本模块按约定忠实发射（不替调用方纠正方向）。
        id=FeatureId(1), type=_claim(FeatureType.HOLE),
        params={"radius": _claim(5.0), "through": _claim(False), "depth": _claim(6.0),
                "axial_at": _claim(0.0)},
        axis=_claim(Axis3(Point3(15.0, 15.0, 20.0), Vector3(0.0, 0.0, -1.0))),
        depends_on=[FeatureId(0)],
    ))
    p.add(Feature(                                  # 腔：底 z=15、往上 5
        id=FeatureId(2), type=_claim(FeatureType.POCKET),
        params={"profile": _claim([(-15.0, -10.0), (15.0, -10.0), (15.0, 10.0), (-15.0, 10.0)]),
                "depth": _claim(5.0), "axial_at": _claim(15.0)},
        axis=_claim(Axis3(Point3(50.0, 45.0, 0.0), _DIRS["z"])),
        depends_on=[FeatureId(0)],
    ))
    p.add(Feature(                                  # 槽：底 z=16、往上 4，20×8
        id=FeatureId(3), type=_claim(FeatureType.SLOT),
        params={"width": _claim(8.0), "length": _claim(20.0), "depth": _claim(4.0),
                "axial_at": _claim(16.0)},
        axis=_claim(Axis3(Point3(15.0, 45.0, 0.0), _DIRS["z"])),
        depends_on=[FeatureId(0)],
    ))
    return p


def _demo_flange_bolt_circle() -> Part:
    """Ø100×10 圆盘 + Ø20 中心通孔 + Ø8 螺栓孔 ×6（分布圆 Ø70）。

    解析体积 = π·50²·10 − π·10²·10 − 6·π·4²·10
            = 25000π − 1000π − 960π = 23040π = 72382.294739 mm³

    这一场是给 REVOLVE + PATTERN 用的：阵列靠"几何重发 child"实现，
    child 的位置已经在 Ø70 分布圆上，阵列绕 `center` 旋转复制。
    """
    p = Part()
    p.add(Feature(
        id=FeatureId(0), type=_claim(FeatureType.REVOLVE),
        params={"angle_deg": _claim(360.0), "dir": _claim("z"),
                "radius_profile": _claim([(0.0, 50.0), (10.0, 50.0)])},
        axis=_claim(Axis3(Point3(0.0, 0.0, 0.0), _DIRS["z"])),
    ))
    p.add(Feature(
        id=FeatureId(1), type=_claim(FeatureType.HOLE),
        params={"radius": _claim(10.0), "through": _claim(True), "axial_at": _claim(0.0)},
        axis=_claim(Axis3(Point3(0.0, 0.0, 0.0), _DIRS["z"])),
        depends_on=[FeatureId(0)],
    ))
    p.add(Feature(                                  # 第 1 个螺栓孔（阵列的 child）
        id=FeatureId(2), type=_claim(FeatureType.HOLE),
        params={"radius": _claim(4.0), "through": _claim(True), "axial_at": _claim(0.0)},
        axis=_claim(Axis3(Point3(35.0, 0.0, 0.0), _DIRS["z"])),
        depends_on=[FeatureId(0)],
    ))
    p.add(Feature(
        id=FeatureId(3), type=_claim(FeatureType.PATTERN),
        params={"kind": _claim("circular"), "count": _claim(6),
                "bc_radius": _claim(35.0), "center": _claim(Point3(0.0, 0.0, 0.0)),
                "child": _claim(2), "start_deg": _claim(0.0)},
        depends_on=[FeatureId(2)],
    ))
    return p


def _demo_reject_corner() -> Part:
    """**负例**：把倒角的棱点给成 seam 上的角点 (28,20,20) —— 必须被拒。

    这一场不核对体积，核对的是"**绝不静默挑一条**"这条硬规则真的在生效：
    该点同时落在"顶圆"与"柱面 seam 直线"上（距离并列，实测都是 0.000000），
    按启发式随便挑一条就会得到"只在 seam 附近倒一小段"的几何
    —— 与"整圈都倒"差着一整圈的材料，而没有任何报错。
    """
    p = _demo_plate_boss()
    p.by_id(FeatureId(2)).params["edges"] = _claim("28,20,20")
    return p


#: 场景表。`volume` / `extents` 是**解析真值**（公式写在各自 docstring 里）。
_SCENARIOS: dict[str, _Scenario] = {
    "plate_hole": _Scenario(
        "plate_hole", _demo_plate_hole,
        volume=100.0 * 60.0 * 20.0 - math.pi * 25.0 * 20.0,
        extents=(20.0, 60.0, 100.0),
        note="100×60×20 板 + Ø10 通孔"),
    "shaft": _Scenario(
        "shaft", _demo_shaft,
        volume=math.pi * (10.0 ** 2 + 6.0 ** 2 + 4.0 ** 2) * 20.0 - math.pi * 9.0 * 60.0,
        extents=(20.0, 20.0, 60.0),
        note="三段阶梯轴（REVOLVE）+ Ø6 通孔"),
    "plate_boss": _Scenario(
        "plate_boss", _demo_plate_boss,
        volume=(40.0 * 40.0 * 10.0 + math.pi * 64.0 * 10.0
                - 4.0 * (9.0 - math.pi * 9.0 / 4.0) * 10.0
                - (math.pi * 64.0 * 2.0 - math.pi * 2.0 / 3.0 * (64.0 + 48.0 + 36.0))),
        extents=(20.0, 40.0, 40.0),
        note="板 + 凸台 + R3 圆角×4 + C2 倒角（edges 定位实测）"),
    "plate_pocket_slot": _Scenario(
        "plate_pocket_slot", _demo_plate_pocket_slot,
        volume=120000.0 - math.pi * 25.0 * 6.0 - 30.0 * 20.0 * 5.0 - 8.0 * 20.0 * 4.0,
        extents=(20.0, 60.0, 100.0),
        note="板 + 盲孔 + 腔 + 槽（axial_at 三套语义）"),
    "flange_bolt_circle": _Scenario(
        "flange_bolt_circle", _demo_flange_bolt_circle,
        volume=math.pi * 2500.0 * 10.0 - math.pi * 100.0 * 10.0 - 6.0 * math.pi * 16.0 * 10.0,
        extents=(10.0, 100.0, 100.0),
        note="Ø100 圆盘（REVOLVE）+ Ø20 中心孔 + Ø8 螺栓孔 ×6（PATTERN）"),
    "reject_corner": _Scenario(
        "reject_corner", _demo_reject_corner,
        expect_error="选棱有歧义",
        note="负例：棱点给成 seam 角点，必须报歧义而不是挑一条"),
}


def _timestamped(dir_: Path, name: str) -> Path:
    """时间戳文件名，同一秒内连跑两次也不撞（STEP 是普通文件写，不怕覆盖，
    这里只是让每次 demo 的产物都能留痕对比）。"""
    dir_.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    cand = dir_ / f"_occ_{name}_{ts}.step"
    n = 1
    while cand.exists():
        cand = dir_ / f"_occ_{name}_{ts}_{n}.step"
        n += 1
    return cand


def _run_scenario(sc: _Scenario, out_dir: Path, tol_rel: float,
                  with_step: bool) -> bool:
    """跑一个场景并按解析真值判定。返回是否通过。"""
    print("\n" + "=" * 78)
    print(f"[demo] {sc.name}  — {sc.note}")
    if sc.expect_error:
        print(f"[demo] 负例：期待报错含 {sc.expect_error!r}")
    else:
        print(f"[demo] 解析体积 = {sc.volume:.6f} mm³   解析外形 = {sc.extents}")
    print("=" * 78)

    part = sc.make()
    if sc.expect_error:
        try:
            build_shape(part)
        except OccBuildError as e:
            ok = sc.expect_error in str(e)
            print(f"[demo] 上报错: {e}")
            print(f"[demo] 拒绝生效 {'PASS' if ok else 'FAIL'}"
                  f"（消息里{'含' if ok else '不含'} {sc.expect_error!r}）")
            return ok
        print("[demo] FAIL —— 该被拒绝的输入竟然建出来了（静默挑了一条棱？）")
        return False

    shape = build_shape(part)
    vol, ext, n_solids = measure_shape(shape)
    dev = (vol - sc.volume) / sc.volume if sc.volume else 0.0
    ok = abs(dev) <= tol_rel
    print(f"[demo] OCC 实测体积 = {vol:.6f} mm³  相对误差 {dev:+.3e}"
          f"  {'PASS' if ok else 'FAIL'}")
    if ext is not None:
        same = all(abs(a - b) < 1e-6
                   for a, b in zip(sorted(ext), sorted(sc.extents)))
        print(f"[demo] 逐轴 bbox = (dx={ext[0]:.6f}, dy={ext[1]:.6f}, dz={ext[2]:.6f})"
              f"（解析三向 {tuple(sorted(sc.extents))}）  {'PASS' if same else 'FAIL'}")
        ok &= same
    else:
        print("[demo] 逐轴 bbox = None  FAIL")
        ok = False
    print(f"[demo] 实体数 = {n_solids}  {'PASS' if n_solids == 1 else 'FAIL'}")
    ok &= (n_solids == 1)

    if with_step:
        step = write_step(shape, _timestamped(out_dir, sc.name))
        rvol, rn = read_step_volume(step)
        rdev = (rvol - sc.volume) / sc.volume
        rok = abs(rdev) <= tol_rel and rn == 1
        print(f"[demo] STEP 读回 {step.name}: 体积 {rvol:.6f} mm³（{rn} 实体）"
              f"  相对误差 {rdev:+.3e}  {'PASS' if rok else 'FAIL'}")
        ok &= rok
    return ok


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or "--help" in argv or "-h" in argv:
        print(__doc__)
        print("用法:")
        print("  python -m src.rebuild.emit.occ_builder --demo"
              " [--scenario plate_hole|shaft|plate_boss|plate_pocket_slot|"
              "flange_bolt_circle|reject_corner|all]"
              " [--out DIR] [--tol 1e-9] [--no-step]")
        print("  （--scenario 可单独给，等价于 --demo --scenario …）")
        return 0 if argv else 2

    out_dir = Path("CAD/temp_output")
    tol_rel = _VOL_TOL
    with_step = "--no-step" not in argv
    scen = "all"
    for flag, need in (("--out", "目录"), ("--tol", "相对误差"), ("--scenario", "场景名")):
        # 少给值就报用法，别让它掉进 IndexError 的栈里（CLI 的错也得说人话）
        if flag in argv and argv.index(flag) + 1 >= len(argv):
            print(f"{flag} 后面要跟{need}")
            return 2
    if "--out" in argv:
        out_dir = Path(argv[argv.index("--out") + 1])
    if "--tol" in argv:
        tol_rel = float(argv[argv.index("--tol") + 1])
    if "--scenario" in argv:
        scen = argv[argv.index("--scenario") + 1]

    if "--demo" not in argv and "--scenario" not in argv:
        print("只支持 --demo（发射器的输入是特征树，命令行没有别的入口）")
        return 2

    names = list(_SCENARIOS) if scen == "all" else [scen]
    for n in names:
        if n not in _SCENARIOS:
            print(f"[demo] 未知场景 {n!r}（可选 {list(_SCENARIOS)}）")
            return 2
    if not occ_available():
        print("[demo] OCC 不可用 —— 请用 cad-occt 环境跑（本 demo 要真建几何）")
        return 3

    overall = True
    for n in names:
        overall &= _run_scenario(_SCENARIOS[n], out_dir, tol_rel, with_step)

    print("\n" + "=" * 78)
    print("[demo] 总结:", "全部通过" if overall else "有失败项（见上）")
    print("=" * 78)
    return 0 if overall else 1


if __name__ == "__main__":
    raise SystemExit(main())
