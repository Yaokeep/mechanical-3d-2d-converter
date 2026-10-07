# -*- coding: utf-8 -*-
"""特征树 → SolidWorks 原生（可编辑）特征模型（ARCHITECTURE §5 emit 层的 SW 侧）。

    python -m src.rebuild.emit.sw_builder --demo      # 自证：建模 + 体积核对

## 这一层是什么、不是什么

特征树是**符号层**（每个数字都是 `Claim`，每个特征都有依据与置信度），
SW 是**几何层**。夹在中间的发射器只做一件事：把**已定型的** Claim 翻译成
SW 的"草图 + 特征调用"。因此本模块：

* **不做几何推理**，也不补默认值 —— `features/library.py` 的契约说"缺参数
  就报 KeyError，绝不默认 0"，这里同样：缺参数、类型未定（孔/凸台歧义未消解）
  一律抛 `SwBuildError` **并指名特征 id**。
* **不静默跳过**任何特征。旧管线的病根之一正是静默（特征没建出来、模型仍然
  "看着差不多"，错误要等到最后量体积才暴露）；本模块每个特征建完立刻验
  "SW 返回了非 None"，失败即炸，绝不继续往下堆。

## 已实测的 SW2025 行为（本模块全部假设的来源，均为探针实测，不是抄文档）

| 项 | 实测结论 | 探针 |
|---|---|---|
| 草图坐标语义 | **草图局部系**（不是模型系），单位 = **文档单位** | `_sw_probe_planes.py` |
| 文档单位 | `gb_part.prtdot` 模板 = MKS(米)，故草图坐标 = 米、特征深度 = 米 | 同上 + `sw_driver.new_part` 日志 |
| 基准面局部轴 | 前视(x=模型X, y=模型Y) / 上视(x=模型X, y=−模型Z) / 右视(x=−模型Z, y=模型Y) | `_sw_probe_planes.py` |
| 基准面法向 | 前视 +Z / 上视 +Y / 右视 +X | 同上 |
| `InsertRefPlane` 偏移 | +d 沿**法向正方向**（三个基准面一致） | `_sw_probe_build.py` |
| `FeatureExtrusion2` Flip=False | 沿**法向正方向**长材料 | `_sw_probe_build.py` |
| `FeatureCut3` Flip=False | 朝**法向反方向**切（与拉伸相反！） | `_sw_probe_cut2.py` 变体 C/H/L |
| `FeatureCut3` Flip=True | **在本机 Python COM 下恒返回 None**（不可用） | `_sw_probe_cut.py` 变体 I/J |
| `FeatureCut3` T1=1(完全贯穿) | **恒返回 None**（不可用）—— 通孔只能按"算出来的深度切穿" | `_sw_probe_cut2.py` 变体 G/K |
| 草图面与实体面共面 | 切除易失败/把实体切成两块（现役脚本亦记此坑） | 现役 `dxf_to_sw_features.py` 的 0.1mm 微缩注释 |
| 质量属性 | 晚期绑定下 `Body2.GetMassProperties(1)` 返回**元组**，`[3]` 才是体积 | `_sw_probe_vol.py` |
| 选棱（点选） | `SelectByID2(点, "Edge")` **不可靠**：点明明在棱上，却可能命中**面**(类型 2) 或**顶点**(3)，只有棱才是 1 | `_sw_probe_fillet8.py` |
| 选棱（精确） | `Body2.GetFaces` → `Face2.GetEdges` → `Edge.GetClosestPointOn(x,y,z)` 找最近棱 → `Edge.Select(True)` | `_sw_probe_edge.py` |
| 圆角选中的是**面**时 | `FeatureFillet3` 会把**该面整圈边界**都倒圆（实测：选竖棱误中面 → 4 条棱全被圆，减量 182.7 ≠ 19.3）——**静默错几何** | `_sw_probe_fillet8.py` |
| `FeatureFillet3` Options | 只有 **2** 与 **195** 能建出特征，0/1/4/8/16/32/64/128 全返回 None（195 = 2+64+128，多出的位不影响结果） | `_sw_probe_fillet7.py` |
| `InsertFeatureChamfer` 参数序 | `(1, 1, 距离m, 角度弧度, …)` —— **距离在前**。反过来（角度在前）不报错，但会把顶面**整层削掉**（实测减 2448 vs 正确 80） | `_sw_probe_edge.py` |

**由此推出的两条硬规则**（本模块所有特征都遵守）：

1. **拉伸/回转一律 Flip=False**，草图面放在区间的"法向较小"那一端，
   材料朝 +法向 长出来；
2. **切除一律 Flip=False**，草图面放在区间的"法向较大"那一端（即孔的**远端**、
   腔的**底**），朝 −法向 切回来。缺口方向靠**摆草图面的位置**解决，
   绝不靠 Flip —— 实测 Flip=True 根本不通。

图纸系（IR）与 SW 模型系的换算：IR 是"X 向右、Y 向里、Z 向上"的右手系，
SW 是"X 向右、Y 向上、Z 朝观察者"。两者差一个绕 X 轴 −90° 的旋转：

    SW(x, y, z) = IR(x, z, −y)      即 IR(x,y,z) → SW(x, z, −y)

于是 SW 的**前视图恰好是图纸主视图**（X 右、Z 上），用户打开模型看到的
朝向就跟他手上的图纸一致。

## 解释器与验收

`emit/sw_builder` 按 ARCHITECTURE §5 归在 cad-occt 环境（那里同时有 pywin32
和 OCC，能顺带做 STEP 体积复核）：

    /c/Users/yaoshuo/miniconda3/envs/cad-occt/python.exe -m src.rebuild.emit.sw_builder --demo

`--demo` 按铁律自证：真建模型 → SW 质量属性量体积 → （有 OCC 时）导出 STEP
再用 `brepgprop.VolumeProperties` 独立复核 → 与解析值比对。**只打印"成功"
不算通过**，体积不过容差就是失败（退出码非 0）。

## 与 `dxf_to_sw_features.py` 的关系

那份脚本是现役的"从 CSG 结果切片**反推**特征"实现，它的 SW 侧接口知识
（`FeatureCut3` 参数顺序、`SetAddToDB` 两面性、共享草图面会失败）在本模块
继续沿用；区别在于**输入**：那边喂的是 z 切片环，这边喂的是特征树。
"""
from __future__ import annotations

import math
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from ..features import library
from ..model.claim import Claim, Tier
from ..model.feature_tree import Feature, FeatureType, Part
from ..model.geom import Axis3, Point3, Vector3
from ..model.geom2d import Point2, Profile2, ProfileSeg2
from ..model.ids import FeatureId

__all__ = ["SwBuildError", "SwUnavailable", "PatternPlan", "active_doc", "build_part",
           "connect", "list_sw_features", "main", "measure_sw_volume_mm3",
           "pattern_plan", "sw_available"]

#: IR 轴向名 → 单位向量
_DIRS: dict[str, Vector3] = {
    "x": Vector3(1.0, 0.0, 0.0),
    "y": Vector3(0.0, 1.0, 0.0),
    "z": Vector3(0.0, 0.0, 1.0),
}

#: 通孔"切穿"的余量（mm）：草图面浮在材料外 ε、切除多切 ε。
#: 取 0.5 而不是 0.05 —— 草图面必须**明显离开**实体面，否则共面切除会失败或
#: 把实体切成两块（探针 4/5 与现役脚本的微缩注释都指向同一坑）。
_EPS = 0.5

#: 按"棱上一点"找棱的距离容差（mm）。0.1 与全项目其他判定阈值同量级：
#: 够宽以容忍调用方把坐标舍到小数点后一位，又窄于任何有意义的几何间隔；
#: 容差内出现多条棱时 `_select_edges` 会**报歧义**而不是赌一条。
_EDGE_TOL = 0.1


class SwBuildError(RuntimeError):
    """特征建模失败。消息里**必须带特征 id** —— 没有 id 的失败没法定位。"""


class SwUnavailable(SwBuildError):
    """SW 不可用（未运行 / 无 pywin32 / 模板缺失）。"""


# ---------------------------------------------------------------------------
# 可用性探测
# ---------------------------------------------------------------------------

def sw_available() -> bool:
    """SW 当前是否**在跑**。不抛异常，也**没有副作用**。

    两步判据（实测的必要性见下）：

    1. `GetActiveObject("SldWorks.Application")` 能拿到 → 在跑；
    2. 拿不到时退回**看进程**：SW 是由别的 COM 客户端 `Dispatch` 拉起来的场合，
       它的 ROT（运行对象表）登记随拉起进程退出而消失 —— 实测：SW 进程还在、
       `Dispatch` 也照样挂得上，但 `GetActiveObject` 报 MK_E_UNAVAILABLE。
       只认第 1 步会把"SW 明明开着"误判成不可用。

    刻意**不**用 `Dispatch` 做探测：SW 没跑时它会顺手拉起一个不可见的 SW 进程
    —— 探测函数不该有这种副作用（真要建模的 `_connect()` 才会这么干）。
    """
    try:
        import pythoncom
        import win32com.client
    except ImportError:
        return False
    try:
        pythoncom.CoInitialize()
        app = win32com.client.GetActiveObject("SldWorks.Application")
        if app is not None and app.RevisionNumber:
            return True
    except Exception:
        pass
    return _sldworks_process_running()


def _sldworks_process_running() -> bool:
    """任务列表里有没有 SLDWORKS.exe（Windows 专属，失败一律当"没在跑"）。"""
    try:
        import subprocess
        out = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq SLDWORKS.exe", "/NH"],
            capture_output=True, text=True, timeout=20,
        )
        return "SLDWORKS" in (out.stdout or "")
    except Exception:
        return False


def _connect(visible: bool = True) -> Any:
    """连上 SW 并返回 SolidWorksDriver（沿用 `src/core/sw_automation` 的封装）。"""
    try:
        from ...core.sw_automation.sw_driver import SolidWorksDriver
    except ImportError as e:            # 默认 python 没有 OCC 但**有** pywin32
        raise SwUnavailable(f"无法导入 SW 驱动（缺 pywin32？）: {e}") from e
    d = SolidWorksDriver(visible=visible)
    try:
        d.connect()
    except Exception as e:
        raise SwUnavailable(f"SW 连接失败: {e}") from e
    return d


def connect(visible: bool = True) -> Any:
    """连上正在运行的 SW（`_connect` 的公开入口，给 CLI / 验收脚本用）。

    ⚠️ 拿到 driver 后**只读不关**：建完的模型要留在 SW 里给人看，
    `driver.disconnect()` 会把活动文档一起关掉（`CLAUDE.md` 记着这个坑）。
    另注意这种"连上去看一眼"的 driver，`driver.sw_model` 是 **None** ——
    要问 `active_doc(driver)` 拿活动文档，别直接摸 `sw_model`。
    """
    return _connect(visible=visible)


# ---------------------------------------------------------------------------
# IR ↔ SW 坐标换算 + 草图局部系
# ---------------------------------------------------------------------------

def _ir_to_sw(p: Point3) -> Point3:
    """IR 点 → SW 模型点：SW(x,y,z) = IR(x, −z, y)。"""
    return Point3(p.x, p.z, -p.y)


def _vec_ir_to_sw(v: Vector3) -> Vector3:
    return Vector3(v.x, v.z, -v.y)


def _axis_name(v: Vector3) -> str:
    """轴向名（只认与坐标轴平行的轴）。不平行即抛 —— 不猜、不近似。"""
    w = v.normalized()
    for name, d in _DIRS.items():
        if w.dot(d) > 0.9995:
            return name
    raise SwBuildError(
        f"轴向 ({v.x:.3f},{v.y:.3f},{v.z:.3f}) 不与坐标轴平行；"
        f"sw_builder 目前只支持 X/Y/Z 轴向特征（任意轴的草图画法需要另一套参考几何）"
    )


def _param(f: Feature, name: str) -> Any:
    """取参数值；缺参数直接报 KeyError（与 `features/library` 契约一致）。"""
    return f.param(name).value


def _axial_at(f: Feature) -> float:
    """特征沿轴的起点坐标（`library.OPTIONAL_PARAMS` 里那条 `axial_at`）。

    ⚠️ 缺参数时按 **0** 起 —— 但 **0 是默认值、不是图纸读数**，所以这里必须
    记账打一行：基体低面不在 0 的零件（bracket 的基体自 z=2 起）会因此让凸台
    伸出基体之外。实测症状：bracket 的凸台全从 z=0 长出，整件 z 向 bbox 46
    而基准 44。识别层迟早要把这个数给出来（它本该是"凸台起始处沿轴的坐标"），
    在那之前至少不静默 —— "系统里不存在裸数值"这条在发射器一侧同样成立。
    """
    v = _opt(f, "axial_at", None)
    if v is None:
        print(f"[emit] 特征 #{f.id}（{f.type.value}）没有 axial_at ⇒ 沿轴按 0 起"
              f"（默认值，非图纸读数；基体不在 0 起时会伸出基体）")
        return 0.0
    return float(v)


def _opt(f: Feature, name: str, default: Any = None) -> Any:
    """取可选参数值；没有就给调用方指定的默认（**不是**默默给 0）。"""
    c = f.params.get(name)
    return default if c is None else c.value


def _origin_of(f: Feature) -> Point3:
    """特征在图纸系里的位置：优先轴原点，退回 placement。"""
    if f.axis is not None and f.axis.value is not None:
        return f.axis.value.origin
    p = f.placement.value
    return p if isinstance(p, Point3) else Point3(0.0, 0.0, 0.0)


def _axis_of(f: Feature) -> tuple[Point3, Vector3, str]:
    """(原点, 单位方向, 轴向名)。方向取自 `Feature.axis`，退回 `params['dir']`。

    与 `features/library._dir_of` 同语义（那里是私有的，故此处自备一份）。
    """
    if f.axis is not None and f.axis.value is not None:
        a = f.axis.value
        return a.origin, a.direction.normalized(), _axis_name(a.direction)
    name = _opt(f, "dir", "z")
    if not isinstance(name, str) or name not in _DIRS:
        raise SwBuildError(f"特征 #{f.id}: 轴向名 {name!r} 不可识别（只认 x/y/z）")
    return _origin_of(f), _DIRS[name], name


@dataclass(frozen=True)
class _Frame:
    """一个轴向对应的"草图载体"：基准面 + 面内坐标映射 + 法向符号。

    * `base`      SW 基准面名（法向见下表）
    * `b1` / `b2` 面内两个 IR 基向量，**右手**：b1 × b2 = dir
                  （profile 的 `(a, b)` 就是这两个基上的坐标）
    * `s`         法向符号：面法向 = s · dir（+1 = 同向，−1 = 反向）
    * `plane_axis` 把 IR 点换算成"沿法向的坐标"用的分量
    """

    name: str
    base: str
    dir: Vector3
    b1: Vector3
    b2: Vector3
    s: float

    def ir_point(self, o: Point3, a: float, b: float, t: float) -> Point3:
        """面内坐标 (a,b) + 沿轴的绝对坐标 t → IR 点。"""
        return o + self.b1 * a + self.b2 * b + self.dir * t

    def local(self, p: Point3) -> tuple[float, float]:
        """IR 点 → 草图局部 (x, y)。三条映射由探针 _sw_probe_planes.py 实测确定。"""
        if self.name == "z":
            return (p.x, p.y)
        if self.name == "x":
            return (p.y, p.z)
        return (p.x, p.z)

    def plane_offset(self, p: Point3) -> float:
        """IR 点所在"垂直面"相对基准面的偏移量（mm，署名带正负）。

        基准面法向：前视 +SW Z、上视 +SW Y、右视 +SW X；换算到 IR 分量后
        法向坐标 = s · (沿 dir 的轴上坐标)。
        """
        if self.name == "z":
            return p.z            # 法向 = +IR Z
        if self.name == "x":
            return p.x            # 法向 = +IR X
        return -p.y               # 法向 = +IR Z = −IR Y

    def normal_of(self, t: float) -> float:
        """沿轴的绝对坐标 t → 法向坐标。"""
        return self.s * t

    def axial_of(self, n: float) -> float:
        """法向坐标 → 沿轴的绝对坐标（s = ±1，故乘除同式）。"""
        return n * self.s


#: 三条轴向的载体面（表由 _sw_probe_planes.py 实测标定，改这里前先重跑探针）
#:   dir=Z → 上视基准面：局部 x=IR x, 局部 y=IR y，法向 +SW Y = +IR Z ⇒ s=+1
#:   dir=X → 右视基准面：局部 x=IR y, 局部 y=IR z，法向 +SW X = +IR X ⇒ s=+1
#:   dir=Y → 前视基准面：局部 x=IR x, 局部 y=IR z，法向 +SW Z = −IR Y ⇒ s=−1
_FRAMES: dict[str, _Frame] = {
    "z": _Frame("z", "上视基准面", _DIRS["z"], _DIRS["x"], _DIRS["y"], +1.0),
    "x": _Frame("x", "右视基准面", _DIRS["x"], _DIRS["y"], _DIRS["z"], +1.0),
    "y": _Frame("y", "前视基准面", _DIRS["y"], _DIRS["z"], _DIRS["x"], -1.0),
}


def _extrude_place(frame: _Frame, t_lo: float, t_hi: float) -> tuple[float, float]:
    """拉伸：返回 (草图面所在的轴上坐标, 深度)。材料朝 +法向 长出（实测）。"""
    n0, n1 = frame.normal_of(t_lo), frame.normal_of(t_hi)
    if n1 < n0:
        n0, n1 = n1, n0
    return frame.axial_of(n0), n1 - n0


def _cut_place(frame: _Frame, t_lo: float, t_hi: float) -> tuple[float, float]:
    """切除：返回 (草图面所在的轴上坐标, 切深)。切**朝 −法向**走（实测）。

    所以草图面摆在区间法向较大的那一端 —— 孔的远端 / 腔的底。
    """
    n0, n1 = frame.normal_of(t_lo), frame.normal_of(t_hi)
    if n1 < n0:
        n0, n1 = n1, n0
    return frame.axial_of(n1), n1 - n0


# ---------------------------------------------------------------------------
# 草图 / 特征基元
# ---------------------------------------------------------------------------

def _plane(driver: Any, frame: _Frame, offset_mm: float, tag: str) -> str:
    """取一个垂直于轴的草图载体面：偏移≈0 用基准面本身，否则建一个**独名**偏移面。

    ⚠️ 面上偏移量相同的面**不复用**：现役脚本记着"同名基准面重复创建会让
    SelectByID2 选错、同一基准面上第 3 个 FeatureCut3 起返回 None"。每个
    特征一张自己的面最省心（SW 里就是多几个参考面，不影响可编辑性）。
    """
    if abs(offset_mm) < 1e-6:
        return frame.base
    name = f"P{tag}_{offset_mm:.2f}"
    if not driver.create_ref_plane_offset(frame.base, offset_mm, name):
        raise SwBuildError(f"建偏移基准面失败（{frame.base} +{offset_mm:.2f}mm）")
    return name


def _sketch_polygon(driver: Any, pts: list[tuple[float, float]]) -> None:
    """画闭合折线（首尾自动相连）。

    普通模式（**不**用 SetAddToDB）：CLAUDE.md 记着 SetAddToDB 下线端点不自动
    合并，多线环会开环 → 拉伸静默失败。所以"少量线段组成的轮廓"必须走吸附模式。
    """
    if len(pts) < 3:
        raise SwBuildError(f"轮廓至少 3 点，实得 {len(pts)}")
    for i, (x1, y1) in enumerate(pts):
        x2, y2 = pts[(i + 1) % len(pts)]
        driver.draw_line(x1, y1, 0.0, x2, y2, 0.0)


def _profile_desc(profile: Any) -> str:
    """轮廓的描述串（点列 vs Profile2 两种契约的记账口径）。"""
    if isinstance(profile, Profile2):
        n_arc = sum(1 for s in profile.segments if s.kind == "arc")
        return f"{len(profile.segments)} 段轮廓（{n_arc} 弧）"
    return f"{len(profile)} 点轮廓"


def _sketch_profile(driver: Any, frame: _Frame, o: Point3, profile: Profile2,
                    f: Feature, what: str) -> None:
    """画带圆弧的闭合轮廓（``Profile2``，段序 = 遍历序）到活动草图。

    弧方向（``CreateArc`` 的 direction 参数）**必须在草图局部坐标里重判**：
    ``_Frame.local`` 对 z/x 轴是恒等映射，对 y 轴是把两个坐标对调（含反射），
    轮廓坐标里的 ``ccw`` 直传会在 y 轴上画成补弧。判据 = 弧中点两侧弦的叉积
    ``(pm−p1)×(p2−pm)`` 符号——映射含反射时符号自动翻转，一条式子覆盖三轴。
    段序连续性由 ``Profile2.chain_break`` 把关（SW 的草图比 OCC 的 MakeWire
    更不能容忍乱序：乱序边在草图里就是一堆断开的曲线，拉伸静默失败）。
    """
    segs = profile.segments
    if len(segs) < 2:
        raise SwBuildError(
            f"特征 #{f.id}（{f.type.value}）{what}：轮廓段数需 ≥2（两段弧可构成整圆），"
            f"实得 {len(segs)}")
    brk = profile.chain_break()
    if brk is not None:
        s0, s1 = segs[brk], segs[(brk + 1) % len(segs)]
        raise SwBuildError(
            f"特征 #{f.id}（{f.type.value}）{what}：轮廓段序断开——段 {brk} 止点 "
            f"({s0.p2.x:.3f},{s0.p2.y:.3f}) 与段 {(brk + 1) % len(segs)} 起点 "
            f"({s1.p1.x:.3f},{s1.p1.y:.3f}) 相距 {s0.p2.distance_to(s1.p1):.3f}mm"
            "（段序必须是遍历序）")

    def loc(a: float, b: float) -> tuple[float, float]:
        return frame.local(frame.ir_point(o, a, b, 0.0))

    for s in segs:
        x1, y1 = loc(s.p1.x, s.p1.y)
        x2, y2 = loc(s.p2.x, s.p2.y)
        if s.kind != "arc":
            if math.hypot(x2 - x1, y2 - y1) <= 1e-9:
                continue                      # 零长段（焊接产物）：不贡献几何
            driver.draw_line(x1, y1, 0.0, x2, y2, 0.0)
            continue
        if s.center is None or s.radius <= 0.0:
            raise SwBuildError(f"特征 #{f.id}（{f.type.value}）{what}：弧段缺圆心/半径")
        span = ((s.ea - s.sa) if s.ccw else (s.sa - s.ea)) % (2.0 * math.pi)
        if span <= 1e-9:
            continue                          # 零跨度退化弧：不贡献几何
        thm = s.sa + span / 2.0 if s.ccw else s.sa - span / 2.0
        xm, ym = loc(s.center.x + s.radius * math.cos(thm),
                     s.center.y + s.radius * math.sin(thm))
        cross = (xm - x1) * (y2 - ym) - (ym - y1) * (x2 - xm)
        if abs(cross) <= 1e-9 * max(1.0, s.radius):
            raise SwBuildError(
                f"特征 #{f.id}（{f.type.value}）{what}：弧段方向不可判"
                f"（弧中点两侧弦近共线，r={s.radius:g}）")
        cx, cy = loc(s.center.x, s.center.y)
        driver.draw_arc(cx, cy, 0.0, x1, y1, 0.0, x2, y2, 0.0, clockwise=cross < 0.0)


def _sketch_circles(driver: Any, circles: list[tuple[tuple[float, float], float]]) -> None:
    """画一个或多个整圆。

    整圆是**单实体、无端点**，捕捉不会把它拉畸变，因此不需要 SetAddToDB
    （现役脚本的整圆快速路径同样绕开了它）。
    """
    for (cx, cy), r in circles:
        if r <= 0.0:
            raise SwBuildError(f"圆半径必须为正，实得 {r}")
        driver.draw_circle(cx, cy, 0.0, r)


def _dangling_sketch(driver: Any) -> Any:
    """当前是否还开着一个**没被特征吃掉**的草图（ISketch 或 None）。

    ⚠️ 晚期绑定下 `GetActiveSketch2` 是**属性**：返回的 dynamic 对象一律
    callable，再加括号调用会抛 `找不到成员`（实测，别用 callable() 判）。
    """
    try:
        return driver.sw_model.GetActiveSketch2
    except Exception:                                       # noqa: BLE001
        return None


def _start_sketch(driver: Any, plane: str, f: Feature, what: str) -> None:
    """开草图前先清掉残留草图，再在 `plane` 上开。

    ⚠️ 实测（`_probe_sw_state.py`）：SW 里一次切除失败**不会**自动关草图，
    残留草图会让此后每次 `start_sketch`（InsertSketch2 是开关语义）变成
    "把上一张关掉"、`FeatureCut3` 一路返回 None —— **一处失败级联成整棵树
    失败**，真正的根因被后 10 条同样的报错埋掉。开图前清干净，失败才可定位。
    """
    if _dangling_sketch(driver) is not None:
        driver.exit_sketch()
    if not driver.start_sketch(plane):
        raise SwBuildError(f"特征 #{f.id}（{f.type.value}）{what}：无法在 {plane} 上开草图")


def _require(driver: Any, feat: Any, f: Feature, what: str) -> None:
    """SW 特征方法返回 None 即失败 —— 一律炸，绝不静默跳过。

    失败时先把残留草图关掉：报错归报错，别把 SW 留在"草图开着"的状态
    让后面的特征替它背锅（见 `_start_sketch` 的级联说明）。
    """
    if feat is None:
        if _dangling_sketch(driver) is not None:
            driver.exit_sketch()
        raise SwBuildError(f"特征 #{f.id}（{f.type.value}）{what} 返回 None（SW 拒绝该特征）")


# ---------------------------------------------------------------------------
# 逐特征建模
# ---------------------------------------------------------------------------

def _profile_bbox_ab(profile: Any) -> tuple[float, float, float, float]:
    """轮廓在 (a, b) 系里的 bbox（``Profile2`` 含弧的四象限极值；点列取端点盒）。"""
    if isinstance(profile, Profile2):
        bb = profile.bbox()
        return bb.xmin, bb.ymin, bb.xmax, bb.ymax
    xs = [float(p[0]) for p in profile]
    ys = [float(p[1]) for p in profile]
    return min(xs), min(ys), max(xs), max(ys)


def _boss_taper(driver: Any, f: Feature, profile: Any, depth_mm: float,
                sa: float, sb: float) -> None:
    """带拔模的凸台拉伸（草图上画的是**底面**轮廓，向内收锥）。

    SW 的拔模角对所有侧壁是**同一个值**，因此两个方向的锥角必须一致；
    不一致（两向异角的锥化）一个 `FeatureExtrusion2` 表达不了 ⇒ 直接拒绝，
    不做"取平均"之类的近似。实测（``_sw_probe_taper.py``）：``Dchk1=True``
    （拔模开）、``Ddir1=False``（向内）、``Dang1=atan((w/2)(1−s)/h)`` ——
    60×60 底、h=60、s=0 得体积 **72000.0 逐位**（向外那支 504,000，正是
    反面的读法）。含弧轮廓在非等比缩放下会变椭圆 ⇒ 同样拒绝。
    """
    if sa < 0.0 or sb < 0.0:
        raise SwBuildError(
            f"特征 #{f.id}（base）锥化缩放系数不能为负（({sa:g},{sb:g})）")
    if isinstance(profile, Profile2) and abs(sa - sb) > 1e-9 \
            and any(s.kind == "arc" for s in profile.segments):
        raise SwBuildError(
            f"特征 #{f.id}（base）含弧轮廓不支持非等比锥化（({sa:g},{sb:g})）")
    x0, y0, x1, y1 = _profile_bbox_ab(profile)
    wa, wb = x1 - x0, y1 - y0
    if wa <= 0.0 or wb <= 0.0:
        raise SwBuildError(f"特征 #{f.id}（base）轮廓空（{wa:g}×{wb:g}）")
    ang_a = math.atan2(0.5 * wa * (1.0 - sa), depth_mm)
    ang_b = math.atan2(0.5 * wb * (1.0 - sb), depth_mm)
    if abs(ang_a - ang_b) > 1e-6:
        raise SwBuildError(
            f"特征 #{f.id}（base）锥化两向异角（{math.degrees(ang_a):.3f}° vs "
            f"{math.degrees(ang_b):.3f}°）：SW 拔模对所有侧壁是同一个角，"
            "一次拉伸表达不了 —— 拒绝而不是取近似")
    feat = driver.sw_feat_mgr.FeatureExtrusion2(
        True, False, False,                       # Sd, Flip, Dir
        0, 0,                                     # T1 = 盲拉, T2
        driver.mm_to_m(depth_mm), driver.mm_to_m(depth_mm),
        True, False,                              # Dchk1 = 拔模开, Dchk2
        False, False,                             # Ddir1 = 不向外（向内收锥）
        ang_a, 0.0,                               # Dang1, Dang2（弧度）
        False, False, False, False,               # OffsetReverse1/2, TranslateSurface1/2
        True, True, True,                         # Merge, UseFeatScope, UseAutoSelect
        0, 0.0, False,                            # T0, StartOffset, FlipStartOffset
    )
    if feat is None:
        raise SwBuildError(
            f"特征 #{f.id}（base）拔模拉伸返回 None（锥角 "
            f"{math.degrees(ang_a):.3f}°、深度 {depth_mm:g}mm）")
    feat.Name = f"Base{f.id}"


def _build_base(driver: Any, f: Feature) -> str:
    """BASE：把闭合轮廓沿轴拉伸成基体（零件的第一块材料）。

    ``taper_scale``（可选）非 (1, 1) 时按**拔模拉伸**发射（见 ``_boss_taper``）：
    ``(0, 0)`` = 收敛到一点的棱锥（``图形练习`` 的四棱锥）。
    """
    o, d, name = _axis_of(f)
    frame = _FRAMES[name]
    length = float(_param(f, "length"))
    profile = _param(f, "profile")
    if length <= 0.0:
        raise SwBuildError(f"特征 #{f.id}（base）拉伸长度必须为正，实得 {length}")
    t0 = _opt(f, "axial_at", 0.0) or 0.0     # BASE 无此参数，留 0
    plane_t, depth = _extrude_place(frame, t0, t0 + length)
    offset = frame.plane_offset(frame.ir_point(o, 0.0, 0.0, plane_t))
    plane = _plane(driver, frame, offset, f"B{f.id}")
    _start_sketch(driver, plane, f, "拉伸基体")
    if isinstance(profile, Profile2):
        _sketch_profile(driver, frame, o, profile, f, "拉伸基体")
    else:
        # 轮廓坐标 (a,b) 是"垂直 dir 的平面内"的两个坐标 → 换算成 IR 点再取草图局部坐标
        pts = [frame.local(frame.ir_point(o, float(a), float(b), 0.0)) for a, b in profile]
        _sketch_polygon(driver, pts)
    taper = _opt(f, "taper_scale", None)
    if taper is not None and not (abs(float(taper[0]) - 1.0) < 1e-12
                                  and abs(float(taper[1]) - 1.0) < 1e-12):
        sa, sb = float(taper[0]), float(taper[1])
        _boss_taper(driver, f, profile, depth, sa, sb)
        return (f"base 锥化拉伸 {_profile_desc(profile)} h={depth:g}mm "
                f"顶部缩放 ({sa:g},{sb:g}) 于 {plane}")
    if not driver.feature_boss_extrude(depth, feat_name=f"Base{f.id}"):
        raise SwBuildError(f"特征 #{f.id}（base）拉伸失败（{_profile_desc(profile)}）")
    return f"base 拉伸 {_profile_desc(profile)} h={depth:g}mm 于 {plane}"


def _build_revolve(driver: Any, f: Feature) -> str:
    """REVOLVE：母线（radius_profile = [(轴上坐标, 半径)]）绕轴回转。

    草图必须**包含**回转轴，所以这里不用 `_FRAMES` 的垂直面，改用"含轴面"
    （前视/上视，二者本就在 IR 的坐标面内）：
      轴 = IR Z → 前视面，局部 (x=半径, y=轴向)
      轴 = IR X → 上视面，局部 (x=轴向, y=半径)
      轴 = IR Y → 上视面，局部 (x=半径, y=轴向)
    """
    o, d, name = _axis_of(f)
    ang = float(_param(f, "angle_deg"))
    profile = _param(f, "radius_profile")
    if len(profile) < 2:
        raise SwBuildError(f"特征 #{f.id}（revolve）母线至少 2 点，实得 {len(profile)}")

    def gen(axpos: float, r: float) -> tuple[float, float]:
        """(轴上坐标, 半径) → 草图局部 (x, y)，并给出轴线的局部坐标轴位置。"""
        if name == "z":                      # 前视：x = IR x, y = IR z
            return (o.x + r, o.z + axpos)
        if name == "x":                      # 上视：x = IR y, y = IR z（轴向在 x）
            return (o.x + axpos, o.y + r)
        return (o.x + r, o.y + axpos)        # name == "y"：上视，轴向在 y

    base = {"z": "前视基准面", "x": "上视基准面", "y": "上视基准面"}[name]
    axis_local = gen(0.0, 0.0)
    # 含轴面相对基准面的偏移：把"过轴的那张面"摆正
    if name == "z":
        offset = -o.y                        # 前视法向 = −IR Y
    else:
        offset = o.z                         # 上视法向 = +IR Z
    if abs(offset) < 1e-6:
        plane = base
    else:
        plane = f"R{f.id}_{offset:.2f}"
        if not driver.create_ref_plane_offset(base, offset, plane):
            raise SwBuildError(f"特征 #{f.id}（revolve）建含轴基准面失败")
    _start_sketch(driver, plane, f, "回转")

    # 中心线 = 回转轴（现役脚本的锥面回转路径同法，V45 验证可用）
    lo = min(float(p[0]) for p in profile)
    hi = max(float(p[0]) for p in profile)
    span = max(hi - lo, 1.0)
    c0, c1 = gen(lo - 0.1 * span, 0.0), gen(hi + 0.1 * span, 0.0)
    driver.draw_centerline(c0[0], c0[1], 0.0, c1[0], c1[1], 0.0)

    # 母线 + 回到轴的闭合边：末点 → 其轴上垂足 → 沿轴 → 首点垂足 → 首点。
    # 落轴上的点与垂足重合，去重后自动省掉零长边（半径 0 的端点即此情形）。
    pts = [gen(float(a), float(r)) for a, r in profile]
    for i in range(len(pts) - 1):
        driver.draw_line(pts[i][0], pts[i][1], 0.0, pts[i + 1][0], pts[i + 1][1], 0.0)
    chain = [pts[-1], (axis_local[0], pts[-1][1]),
             (axis_local[0], pts[0][1]), pts[0]]
    for a, b in zip(chain, chain[1:]):
        if abs(a[0] - b[0]) > 1e-9 or abs(a[1] - b[1]) > 1e-9:
            driver.draw_line(a[0], a[1], 0.0, b[0], b[1], 0.0)
    if not driver.feature_revolve(ang, is_cut=False, feat_name=f"Revolve{f.id}"):
        raise SwBuildError(f"特征 #{f.id}（revolve）回转失败（{len(profile)} 点母线）")
    return f"revolve {len(profile)} 点母线 {ang:g}° 于 {plane}"


def _build_boss(driver: Any, f: Feature) -> str:
    """BOSS：圆柱凸台（半径 + 高度），沿轴从 `axial_at` 长出。"""
    o, d, name = _axis_of(f)
    frame = _FRAMES[name]
    radius = float(_param(f, "radius"))
    height = float(_param(f, "height"))
    if radius <= 0.0 or height <= 0.0:
        raise SwBuildError(f"特征 #{f.id}（boss）半径/高度必须为正，实得 r={radius} h={height}")
    t0 = _axial_at(f)
    center = frame.local(frame.ir_point(o, 0.0, 0.0, t0))
    plane_t, depth = _extrude_place(frame, t0, t0 + height)
    offset = frame.plane_offset(frame.ir_point(o, 0.0, 0.0, plane_t))
    plane = _plane(driver, frame, offset, f"T{f.id}")
    _start_sketch(driver, plane, f, "凸台拉伸")
    _sketch_circles(driver, [(center, radius)])
    if not driver.feature_boss_extrude(depth, feat_name=f"Boss{f.id}"):
        raise SwBuildError(f"特征 #{f.id}（boss）拉伸失败（r={radius:g} h={height:g}）")
    return f"boss Ø{2 * radius:g}×{height:g} 于 {plane}"


def _build_hole(driver: Any, f: Feature) -> str:
    """HOLE：圆柱切除。`through=True` 时切穿整个材料（按实测算深度，不用贯穿条件）。"""
    o, d, name = _axis_of(f)
    frame = _FRAMES[name]
    radius = float(_param(f, "radius"))
    through = bool(_param(f, "through"))
    if radius <= 0.0:
        raise SwBuildError(f"特征 #{f.id}（hole）半径必须为正，实得 {radius}")
    count = int(_opt(f, "count", 0) or 0)
    if count > 1:
        # 契约只说"同一轴上的孔数"，没给分布（间距/阵列）—— 按 1 个孔建就是**少建**，
        # 静默少建正是旧管线的病，故宁可拒绝。
        raise SwBuildError(
            f"特征 #{f.id}（hole）count={count} > 1：契约未定义这些孔如何分布"
            f"（间距/角度均缺），无法忠实发射；请改用 PATTERN 或补齐分布参数"
        )
    t0 = _axial_at(f)                               # 孔口（契约：HOLE 的 axial_at = 孔口）
    if through:
        t_far = _axial_max(driver, o, d) + _EPS
        t_lo, t_hi = t0 - _EPS, t_far
        how = "通孔"
    else:
        depth = float(_param(f, "depth"))           # 契约：through 时忽略 depth
        if depth <= 0.0:
            raise SwBuildError(f"特征 #{f.id}（hole）盲孔深度必须为正，实得 {depth}")
        t_lo, t_hi = t0, t0 + depth
        how = f"盲孔深{depth:g}"
    center = frame.local(frame.ir_point(o, 0.0, 0.0, 0.0))
    plane_t, cut_depth = _cut_place(frame, t_lo, t_hi)
    offset = frame.plane_offset(frame.ir_point(o, 0.0, 0.0, plane_t))
    plane = _plane(driver, frame, offset, f"H{f.id}")
    _start_sketch(driver, plane, f, "孔切除")
    _sketch_circles(driver, [(center, radius)])
    return _cut(driver, f, cut_depth, plane, f"Ø{2 * radius:g} {how}")


def _build_pocket(driver: Any, f: Feature) -> str:
    """POCKET：闭合轮廓腔。契约里 `axial_at` = **腔底**，故往上挖 depth。"""
    o, d, name = _axis_of(f)
    frame = _FRAMES[name]
    profile = _param(f, "profile")
    depth = float(_param(f, "depth"))
    if depth <= 0.0:
        raise SwBuildError(f"特征 #{f.id}（pocket）深度必须为正，实得 {depth}")
    t_bot = _axial_at(f)
    plane_t, cut_depth = _cut_place(frame, t_bot, t_bot + depth)
    offset = frame.plane_offset(frame.ir_point(o, 0.0, 0.0, plane_t))
    plane = _plane(driver, frame, offset, f"C{f.id}")
    _start_sketch(driver, plane, f, "腔切除")
    if isinstance(profile, Profile2):
        _sketch_profile(driver, frame, o, profile, f, "腔切除")
    else:
        pts = [frame.local(frame.ir_point(o, float(a), float(b), 0.0)) for a, b in profile]
        _sketch_polygon(driver, pts)
    return _cut(driver, f, cut_depth, plane, f"腔 {_profile_desc(profile)} 深{depth:g}")


def _build_slot(driver: Any, f: Feature) -> str:
    """SLOT：矩形槽，沿轴深 `depth`，面内 `length`(沿 b1) × `width`(沿 b2)，居中于轴。

    ⚠️ 契约缺项（详见交付报告）：`library` 只给了 width/length/depth，
    **没说槽形**（直槽/腰形槽）、也没说 length 与 width 各朝哪个方向、
    槽是否以轴为中心。此处取"以轴为中心的矩形槽、length 沿 b1、width 沿 b2、
    depth 沿轴"这一组约定；`library._predict_slot` 的预测里 length 是沿**轴**的，
    与本约定冲突 —— 两边必须先对齐，否则发射出来的槽方向就是错的。
    """
    o, d, name = _axis_of(f)
    frame = _FRAMES[name]
    width = float(_param(f, "width"))
    length = float(_param(f, "length"))
    depth = float(_param(f, "depth"))
    for label, v in (("width", width), ("length", length), ("depth", depth)):
        if v <= 0.0:
            raise SwBuildError(f"特征 #{f.id}（slot）{label} 必须为正，实得 {v}")
    t_bot = _axial_at(f)
    hw, hl = width / 2.0, length / 2.0
    pts = [(-hl, -hw), (hl, -hw), (hl, hw), (-hl, hw)]
    local = [frame.local(frame.ir_point(o, a, b, 0.0)) for a, b in pts]
    plane_t, cut_depth = _cut_place(frame, t_bot, t_bot + depth)
    offset = frame.plane_offset(frame.ir_point(o, 0.0, 0.0, plane_t))
    plane = _plane(driver, frame, offset, f"S{f.id}")
    _start_sketch(driver, plane, f, "槽切除")
    _sketch_polygon(driver, local)
    return _cut(driver, f, cut_depth, plane, f"槽 {length:g}×{width:g} 深{depth:g}")


def _cut(driver: Any, f: Feature, depth: float, plane: str, what: str) -> str:
    """统一的切除调用（FeatureCut3 26 参数，与 V45 验证签名逐位对齐）。

    三处**实测得出的**取舍都写在这里，别照抄文档改：
    * `Flip=False`：Flip=True 在本机恒失败（探针 4/5）；
    * `T1=0`（盲切）：完全贯穿 T1=1 恒失败，通孔靠"算准深度"切穿；
    * `AutoSelect=False`：现役脚本记着 True 会把别的草图的轮廓也拉进切除集
      （法兰孔切除把整个法兰盘切空）。
    """
    feat = driver.sw_feat_mgr.FeatureCut3(
        True, False, False, False,
        0, driver.mm_to_m(depth),
        False, 0, 0.0, False,
        False, 0.0, 0.0, False, False, False, False, False,
        True, True, True, False, 0.0,
        True, True, False,
    )
    _require(driver, feat, f, f"切除（{what}，于 {plane}）")
    _name_feature(feat, f, "Cut")
    return f"cut {what} 于 {plane}"


def _is_clone(f: Feature) -> bool:
    """是否是阵列重发时造的**几何克隆**（`_clone_at` 的产物）。

    判据是轴上的来源标记 `"pattern:rotate"` —— 本模块自己写的标签，
    特征树里只有克隆带它。
    """
    return f.axis is not None and f.axis.method == "pattern:rotate"


def _name_feature(feat: Any, f: Feature, kind: str) -> None:
    """给 SW 特征起自述名（`Cut3`/`Fillet2`…），让 SW 树能与特征树逐条对。

    这是阶段 4 验收"特征数与特征模型一致"的**可核查**那一半：SW 默认名
    （`切除-拉伸7`）对不上 IR 的 id，数得清也对不上号。

    ⚠️ 改名**绝不允许**影响几何成败：SW 对重名自行加后缀或干脆拒绝，任何
    异常都在这里吞掉、只打一行日志 —— 名字是给人看的，不是验收项。
    """
    tag = f"{kind}{f.id}" + ("p" if _is_clone(f) else "")
    try:
        feat.Name = tag
    except Exception as e:                                  # noqa: BLE001
        print(f"[emit] 特征改名 {tag} 失败（不影响几何）: {str(e)[:60]}")


def _edge_points(f: Feature) -> list[Point3]:
    """解析 `edges` 参数 → 一组**棱上点**（IR mm）。

    ⚠️ 契约缺项：`library.OPTIONAL_PARAMS` 只写"字符串标识，见 emit/occ_builder"，
    而 occ_builder 尚未落地 —— 棱的标识格式**没有权威定义**。本模块自定：
    每条棱用"棱上一个点"标定，写法 `"x,y,z"`（IR mm，逗号分隔），
    多条棱用列表或多个分号隔开。`occ_builder` 落地后必须与此对齐。

    点的选取要求（由 `_select_edges` 的几何定位决定）：必须**落在棱上**
    （距棱 ≤ `_EDGE_TOL`），且**不要给角点** —— 角点到多条棱的距离都是 0，
    会被判为歧义而拒绝。**给棱中点**最稳。
    """
    raw = _opt(f, "edges", None)
    if raw is None:
        raise SwBuildError(
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
            raise SwBuildError(f"特征 #{f.id}: 棱标识 {it!r} 解不出坐标") from e
        if len(xs) != 3:
            raise SwBuildError(f"特征 #{f.id}: 棱标识 {it!r} 需要 3 个坐标")
        out.append(Point3(*xs))
    if not out:
        raise SwBuildError(f"特征 #{f.id}: `edges` 为空")
    return out


def _member(obj: Any, name: str) -> Any:
    """晚期绑定下取成员：可能是**方法**（要调用）也可能是**属性**（加括号报错）。

    实测两类都存在：`Body2.GetFaces`/`Face2.GetEdges` 是方法（不加括号拿到的是
    method 对象，迭代它直接 TypeError），而 `ISldWorks.GetDocuments` 是属性
    （加括号报 `'NoneType' object is not callable`）。这里统一"先当方法试"。
    """
    v = getattr(obj, name)
    if callable(v):
        try:
            return v()
        except TypeError:
            return v
    return v


def _find_edges(driver: Any, p: Point3, tol_mm: float = _EDGE_TOL) -> list[tuple[float, Any]]:
    """找"最近点落在 IR 点 p 附近"的棱，返回 [(距离mm, IEdge)] 按距离升序。

    为什么不用 `driver.select_edge_by_point`（现役脚本的招）：SW 的点选是**命中级
    启发式**，实测同一个"棱上的点"可能命中**面**或**顶点** —— 而 `FeatureFillet3`
    拿到一个**面**会把该面整圈边界都倒圆（见模块顶部行为表），于是几何静默错掉，
    体积偏 9 倍还不报错。这里改成**几何定位**：遍历实体的面→棱，用
    `Edge.GetClosestPointOn` 量到给定点的真实距离，命中与否由距离说了算。
    """
    model = driver.sw_model
    xyz = (p.x / 1000.0, p.y / 1000.0, p.z / 1000.0)     # 米（OCC/SW 长度单位）
    found: dict[tuple[float, float, float], tuple[float, Any]] = {}
    for body in model.GetBodies2(0, True):
        for face in (_member(body, "GetFaces") or []):
            for edge in (_member(face, "GetEdges") or []):
                cp = list(edge.GetClosestPointOn(*xyz))
                dist = math.dist(cp[:3], xyz) * 1000.0
                if dist > tol_mm:
                    continue
                # 一条棱会被相邻两个面各列一次 → 用"最近点"当同一性判据去重
                key = (round(cp[0], 6), round(cp[1], 6), round(cp[2], 6))
                hit = found.get(key)
                if hit is None or dist < hit[0]:
                    found[key] = (dist, edge)
    return sorted(found.values(), key=lambda t: t[0])


def _select_edges(driver: Any, f: Feature) -> int:
    """按棱上点逐条精确定位并选中；找不到、或有歧义、或选中数不足，一律抛。"""
    pts = _edge_points(f)
    driver.clear_selection()
    for p in pts:
        sw = _ir_to_sw(p)
        hits = _find_edges(driver, sw)
        if not hits:
            raise SwBuildError(
                f"特征 #{f.id}（{f.type.value}）选棱失败：模型上找不到 IR 点 "
                f"({p.x:g}, {p.y:g}, {p.z:g}) 附近 {_EDGE_TOL}mm 内的棱"
                f"（SW 坐标 {sw.x:g}, {sw.y:g}, {sw.z:g}）"
            )
        if len(hits) > 1:
            raise SwBuildError(
                f"特征 #{f.id}（{f.type.value}）选棱有歧义：IR 点 "
                f"({p.x:g}, {p.y:g}, {p.z:g}) {_EDGE_TOL}mm 内命中 {len(hits)} 条棱"
                f"（最近 {hits[0][0]:.4f}mm / 次近 {hits[1][0]:.4f}mm）—— "
                f"多半给的是角点，请改给**棱中点**"
            )
        hits[0][1].Select(True)                          # True = Append
    got = driver.selection_count()
    if got < len(pts):
        raise SwBuildError(
            f"特征 #{f.id}（{f.type.value}）选棱失败：只选中 {got}/{len(pts)} 条"
            f"（棱上点 {[tuple(round(v, 2) for v in (p.x, p.y, p.z)) for p in pts]}）"
        )
    return got


def _build_fillet(driver: Any, f: Feature) -> str:
    """FILLET：等半径圆角（Options=195 与 `sw_driver.feature_fillet_edges` 一致）。

    Options 实测只有 2 与 195 能建出特征，其余取值一律静默返回 None；
    两个值的几何结果相同，沿用驱动里的 195。

    ⚠️ 圆角是**按选中棱**做的 —— 但如果选中的是**面**，SW 会把该面整圈边界
    都倒圆（`_select_edges` 因此改用几何定位，见其 docstring）。
    """
    from ...core.sw_automation.sw_constants import SW_FILLET_OPTIONS

    radius = float(_param(f, "radius"))
    if radius <= 0.0:
        raise SwBuildError(f"特征 #{f.id}（fillet）半径必须为正，实得 {radius}")
    n = _select_edges(driver, f)
    feat = driver.sw_feat_mgr.FeatureFillet3(
        SW_FILLET_OPTIONS, driver.mm_to_m(radius),
        0, 0, False, 0, False, False,
    )
    _require(driver, feat, f, f"圆角 R{radius:g}（{n} 条棱）")
    _name_feature(feat, f, "Fillet")
    return f"fillet R{radius:g} × {n} 棱"


def _build_chamfer(driver: Any, f: Feature) -> str:
    """CHAMFER：等距倒角（Type=1 角度-距离，默认 45°）。

    ⚠️ 参数序是**距离在前、角度在后**（`CLAUDE.md` 那句"与直觉相反"就是这个）：

        InsertFeatureChamfer(Options, ChamferType, 距离m, 角度弧度, 0,0,0, False)

    `sw_driver.feature_chamfer_edge` 里写的是 `(0.785, 距离)`，实测**不报错**却把
    顶面整整削掉一层（40×40 板上减 2448 mm³，正确值 80）—— 静默错几何，正是
    本框架要消灭的那类。这里按键序改正；驱动那边属既有文件，本任务不动它。
    """
    dist = float(_param(f, "distance"))
    ang = float(_opt(f, "angle_deg", 45.0) or 45.0)
    if dist <= 0.0:
        raise SwBuildError(f"特征 #{f.id}（chamfer）倒角距离必须为正，实得 {dist}")
    n = _select_edges(driver, f)
    feat = driver.sw_feat_mgr.InsertFeatureChamfer(
        1, 1, driver.mm_to_m(dist), library.radians(ang), 0.0, 0.0, 0.0, False,
    )
    _require(driver, feat, f, f"倒角 C{dist:g}（{n} 条棱）")
    _name_feature(feat, f, "Chamfer")
    return f"chamfer C{dist:g} × {n} 棱"


@dataclass(frozen=True)
class PatternPlan:
    """一个圆形阵列的**发射计划**：要新建哪几个实例、哪几处已被现有特征占掉。

    "被占掉"这件事必须显式记账，因为：
      * SW 里同一位置**再切一刀什么都切不掉**，`FeatureCut3` 返回 None
        —— 不是警告，是整棵树发射失败（flange_d80 实测死在这）；
      * 验收要核"特征数与特征模型一致"，口径得**只有一处**：
        发射器建了几个、报数报几个，共用这一个函数，免得两边各算各的。
    """

    count: int
    child: Feature
    axis_pt: Point3
    axis_dir: Vector3
    #: 待新建的实例位置（不含 child 自身那一处）
    positions: list[Point3]
    #: 已被现有 IR 特征覆盖的实例 → 那些特征的 id（发射时不再重复建）
    covered: list[str]


def pattern_plan(f: Feature, part: Part) -> PatternPlan:
    """校验阵列契约 → 算出发射计划。契约不合就抛（宁可拒绝，不静默少建）。

    ⚠️ 为什么要"覆盖判据"：识别器会**同时**产出"每个孔各是一个特征"与
    "这几个孔构成一个阵列"（前者来自视图中逐个圆，后者来自图纸的均布约定），
    于是阵列实例位置常常与那些孔**逐个重合**。照着契约硬克隆，就等于把同一处
    材料切两遍。
    """
    kind = str(_param(f, "kind"))
    count = int(_param(f, "count"))
    # 阵列中心 = `placement`，`center` 参数给了才压过它（与 occ_builder 同口径）
    center = _opt(f, "center", None)
    if center is None and f.placement is not None:
        center = f.placement.value
    child_id = _opt(f, "child", None)
    if kind != "circular":
        raise SwBuildError(
            f"特征 #{f.id}（pattern）kind={kind!r} 暂不支持"
            f"（线性阵列契约缺方向参数 `pitch` 的方向，无法忠实发射）"
        )
    if count < 2:
        raise SwBuildError(f"特征 #{f.id}（pattern）count={count} < 2 不构成阵列")
    if not isinstance(center, Point3):
        raise SwBuildError(f"特征 #{f.id}（pattern）缺 `center`（圆形阵列的分布圆圆心）")
    if child_id is None:
        raise SwBuildError(f"特征 #{f.id}（pattern）缺 `child`（被阵列的特征 id）")
    try:
        child = part.by_id(FeatureId(int(child_id)))
    except KeyError as e:
        raise SwBuildError(f"特征 #{f.id}（pattern）的 child={child_id!r} 不在特征树里") from e
    start = float(_opt(f, "start_deg", 0.0) or 0.0)
    co, cd, _ = _axis_of(child)
    # 阵列轴：过 center、方向取 child 自身轴向（螺栓分布圆的标准情形）
    sibs = [g for g in part.features
            if g.id != f.id and g.id != child.id
            and g.type.value == child.type.value]
    positions: list[Point3] = []
    covered: list[str] = []
    for i in range(1, count):                     # 第 0 个 = child 自身
        p = _rotate_about(co, center, cd, start + i * 360.0 / count)
        hit = _twin_at(sibs, p, child)
        if hit is None:
            positions.append(p)
        else:
            covered.append(str(hit.id))
    return PatternPlan(count, child, center, cd, positions, covered)


def _twin_at(sibs: list[Feature], p: Point3, ref: Feature) -> Feature | None:
    """在 `sibs` 里找"与 `ref` 同型同尺寸、轴心落在 p"的特征（没有则 None）。

    容差用 `_EDGE_TOL`（0.1mm，与全项目判定同量级）；半径差另给 0.05mm ——
    两个不同直径的同心孔不该互相顶掉。
    """
    r_ref = _opt(ref, "radius", None)
    for g in sibs:
        if g.axis is None or g.axis.value is None:
            continue
        o = g.axis.value.origin
        if abs(o.x - p.x) > _EDGE_TOL or abs(o.y - p.y) > _EDGE_TOL \
                or abs(o.z - p.z) > _EDGE_TOL:
            continue
        r_g = _opt(g, "radius", None)
        if r_ref is not None and r_g is not None and abs(float(r_ref) - float(r_g)) > 0.05:
            continue
        return g
    return None


def _build_pattern(driver: Any, f: Feature, part: Part,
                   allow_guess: bool = False) -> str:
    """PATTERN：目前只支持**圆形阵列**（把 child 的几何绕阵列轴复制后重发一遍）。

    为什么不用 SW 的原生阵列特征：那要选"种子特征 + 方向参考"，在晚期绑定下
    依赖选择状态，失败模式又回到静默（返回 None）。这里改成几何重发 ——
    每个孔都是**独立的可编辑特征**，模型等价、可编辑性不差，且每步都能验。

    ⚠️ 只补**没被现有特征占掉**的实例位置（`pattern_plan`），否则就是同一处
    材料切两遍 —— SW 拒收，整棵树发射失败。

    ⚠️ 契约缺项：线性阵列只有 `pitch`、**没有方向**，无法确定往哪儿排 → 直接拒绝。
    """
    plan = pattern_plan(f, part)
    out = []
    for p in plan.positions:
        ghost = _clone_at(plan.child, p, plan.axis_dir)
        out.append(_dispatch(driver, ghost, part, allow_guess))
    note = ""
    if plan.covered:
        note = (f"；{len(plan.covered)} 处实例已由 IR "
                f"#{'、#'.join(plan.covered)} 建出，不重复发射")
    built = "；".join(out) if out else "无需新建几何"
    return f"circular pattern × {plan.count}（{built}）{note}"


def _clone_at(f: Feature, origin: Point3, direction: Vector3) -> Feature:
    """复制一个特征，把它的轴平移到 origin（阵列重发用）。"""
    g = Feature(
        id=f.id, type=f.type, params=dict(f.params), placement=f.placement,
        axis=Claim(Axis3(origin, direction), "pattern:rotate", Tier.GUESS),
        depends_on=list(f.depends_on), evidence=list(f.evidence),
        source_view=f.source_view,
    )
    return g


def _rotate_about(p: Point3, axis_pt: Point3, axis_dir: Vector3, deg: float) -> Point3:
    """绕 (axis_pt, axis_dir) 把点 p 旋转 deg 度（Rodrigues）。"""
    k = axis_dir.normalized()
    v = p - axis_pt
    th = library.radians(deg)
    c, s = math.cos(th), math.sin(th)
    return axis_pt + v * c + k.cross(v) * s + k * (k.dot(v) * (1.0 - c))


#: 特征类型 → 建模函数。签名分两种：pattern 要 part 才能找 child。
_BUILDERS: dict[FeatureType, Callable[..., str]] = {
    FeatureType.BASE: _build_base,
    FeatureType.REVOLVE: _build_revolve,
    FeatureType.BOSS: _build_boss,
    FeatureType.HOLE: _build_hole,
    FeatureType.POCKET: _build_pocket,
    FeatureType.SLOT: _build_slot,
    FeatureType.FILLET: _build_fillet,
    FeatureType.CHAMFER: _build_chamfer,
    FeatureType.PATTERN: _build_pattern,
}


def _dispatch(driver: Any, f: Feature, part: Part,
              allow_guess: bool = False) -> str:
    """按类型发一个特征；类型未定/无实现一律点名报错。

    `allow_guess` 与 `occ_builder._dispatch` 同义同默认（见那里的 docstring）：
    该不该照样建由上游 `pipeline.rebuild(force=...)` 决定，发射器只如实记账。
    """
    if f.is_hypothesis:
        if not allow_guess:
            raise SwBuildError(
                f"特征 #{f.id} 的类型仍未定（{f.type.value}，备选 "
                f"{[a.value for a in f.type.alternatives]}）：歧义未消解就发射，等于替用户拍板"
            )
        print(f"  [GUESS] #{f.id} 类型 {f.type.value} 是**猜的**"
              f"（备选 {[a.value for a in f.type.alternatives]}）—— "
              "调用方给了 allow_guess，照主值建")
    t = FeatureType(f.type.value)
    fn = _BUILDERS.get(t)
    if fn is None:
        raise SwBuildError(f"特征 #{f.id} 的类型 {t.value} 尚无 SW 发射实现")
    missing = library.missing_params(f)
    if missing:
        raise SwBuildError(f"特征 #{f.id}（{t.value}）缺必需参数 {missing}（不默认 0）")
    if t is FeatureType.PATTERN:
        return _build_pattern(driver, f, part, allow_guess)
    return fn(driver, f)


# ---------------------------------------------------------------------------
# 建模主流程
# ---------------------------------------------------------------------------

def _close_stale_docs(app: Any, keep: str) -> None:
    """关掉"不是本次构建"的旧文档（CLAUDE.md：SW 里只留一个模型）。

    只关**已保存**的文档：API 的 `CloseDoc` 不弹对话框、直接丢弃改动，
    对一个有未保存改动的文档动手就是毁用户的工作。有改动的只警告、不动。
    """
    try:
        # ⚠️ 实测：ISldWorks.GetDocuments 在晚期绑定下是**属性**不是方法 ——
        #    加括号会得到 `'NoneType' object is not callable`（探针实测），
        #    且该属性返回的是 COM 对象元组，可直接迭代。
        docs = app.GetDocuments
    except Exception as e:
        print(f"[emit] 枚举旧文档失败（跳过清理）: {e}")
        return
    for doc in docs or []:
        try:
            title = doc.GetTitle
            if title == keep:
                continue
            if doc.GetSaveFlag:
                print(f"[emit] 旧文档 {title!r} 有未保存改动，保留不动（请自行关闭）")
                continue
            app.CloseDoc(title)
            print(f"[emit] 已关闭上一个模型: {title}")
        except Exception as e:
            print(f"[emit] 关闭旧文档异常（忽略）: {e}")


def _axial_max(driver: Any, origin: Point3, direction: Vector3) -> float:
    """材料沿 `direction` 的最大坐标（相对 origin 沿轴）—— 通孔"切穿"要它的实测值。

    取 8 个包围盒角点在轴上的投影最大值（保守：宁可多切到空气里，也不能留皮）。
    """
    box = driver.sw_model.GetPartBox(True)          # True = 系统单位（米）
    if box is None:
        raise SwBuildError("取零件包围盒失败（还没有实体？）")
    lo = [v * 1000.0 for v in box[:3]]
    hi = [v * 1000.0 for v in box[3:]]
    o_sw, d_sw = _ir_to_sw(origin), _vec_ir_to_sw(direction)
    best = None
    for xi in (lo[0], hi[0]):
        for yi in (lo[1], hi[1]):
            for zi in (lo[2], hi[2]):
                p = Point3(xi, yi, zi) - o_sw
                t = p.x * d_sw.x + p.y * d_sw.y + p.z * d_sw.z
                best = t if best is None else max(best, t)
    return float(best if best is not None else 0.0)


def _timestamped(save_to: Path) -> Path:
    """时间戳文件名。**从不覆盖**已存在的文件（SW 占用目标文件时保存会失败）。"""
    save_to = Path(save_to)
    stem, suffix = save_to.stem, save_to.suffix or ".sldprt"
    parent = save_to.parent if str(save_to.parent) else Path(".")
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    cand = parent / f"{stem}_{ts}{suffix}"
    n = 1
    while cand.exists():                            # 同一秒内连建两次也不撞
        cand = parent / f"{stem}_{ts}_{n}{suffix}"
        n += 1
    return cand


def build_part(part: Part, save_to: Path, *, visible: bool = True,
               allow_guess: bool = False) -> Path:
    """把特征树建成 SW 原生特征模型并存盘，返回**实际**保存的路径。

    顺序由 `features/library.build_order` 定（先基体 → 凸台 → 切除 → 圆角/倒角；
    显式 `depends_on` 优先于层号），**不按 features 列表的书写顺序建** ——
    布尔序错会让 SW 静默失败（CLAUDE.md 的 `SetAddToDB` 那课）。

    建完**不关**这个模型：留给用户看（CLAUDE.md：SW 同时只保留一个模型，
    下一个重建开始时由 `_close_stale_docs` 收尾）。
    """
    return _build_in(_connect(visible=visible), part, save_to,
                     allow_guess=allow_guess)


def _build_in(driver: Any, part: Part, save_to: Path, *,
              allow_guess: bool = False) -> Path:
    """`build_part` 的实体（driver 由调用方给 —— demo 要复用同一个连接接着量体积）。"""
    try:
        order = library.build_order(list(part.features))
    except ValueError as e:                         # 依赖成环
        raise SwBuildError(f"特征树拓扑排序失败: {e}") from e
    if not order:
        raise SwBuildError("特征树是空的，没有可建的特征")
    kinds = {FeatureType(f.type.value) for f in order
             if f.type.is_settled or allow_guess}
    if not kinds & {FeatureType.BASE, FeatureType.REVOLVE}:
        raise SwBuildError(
            "特征树里没有基体（BASE/REVOLVE）：没有第一块材料，后续凸台/切除都无处安放"
        )
    bad = [f for f in order if library.missing_params(f)]
    if bad:
        raise SwBuildError(
            "以下特征缺必需参数，拒绝建模（宁可拒绝，也不静默建出个错的）："
            + "; ".join(f"#{f.id} 缺{library.missing_params(f)}" for f in bad)
        )

    app = driver.sw_app
    target = _timestamped(save_to)
    target.parent.mkdir(parents=True, exist_ok=True)
    print(f"[emit] 目标文件: {target}")
    print(f"[emit] 建模顺序: {[f'#{f.id}:{f.type.value}' for f in order]}")

    _close_stale_docs(app, keep="")                 # 上一次的模型在这里收尾
    if not driver.new_part():
        raise SwBuildError("SW 新建零件失败")
    print(f"[emit] 新零件: {driver.sw_model.GetTitle}")

    done: list[str] = []
    for f in order:
        try:
            info = _dispatch(driver, f, part, allow_guess)
        except SwBuildError:
            raise
        except Exception as e:                      # COM 异常也要带上特征 id
            raise SwBuildError(f"特征 #{f.id}（{f.type.value}）建模抛异常: {e}") from e
        done.append(info)
        print(f"  [OK] #{f.id:<3} {f.type.value:8} {info}")

    driver.rebuild()
    driver.zoom_to_fit()
    if not driver.save_as(str(target)):
        raise SwBuildError(f"保存失败: {target}（文件被占用？）")
    print(f"[emit] 已保存 {len(order)} 个特征: {target}")
    # 刻意**不**调 driver.disconnect()：它收尾会关活动文档，把刚建好的模型也关掉
    # （现役脚本踩过，_sw_show.py 也为此绕开）。旧文档的清理在下次建模开头做。
    return target


# ---------------------------------------------------------------------------
# 实测：SW 质量属性 + STEP/OCC 独立复核
# ---------------------------------------------------------------------------

def active_doc(driver: Any) -> Any:
    """当前活动文档：driver 自己记的，没有就问 SW 要（`sw_app.ActiveDoc`，**属性**）。

    为什么要有它：`measure_sw_volume_mm3` / `list_sw_features` 这类**只读**核对
    工具经常在"不是刚建模型的那个 driver 实例"上调用（回归脚本、探针都是
    `_connect()` 之后直接量刚建好的文档），那种 driver 的 `sw_model` 是 None，
    直接 `driver.sw_model.GetBodies2` 会炸在 `'NoneType' has no attribute` 上
    —— 报错长得像"没有实体"，其实是找错了文档。
    """
    doc = getattr(driver, "sw_model", None)
    if doc is not None:
        return doc
    d = getattr(driver.sw_app, "ActiveDoc", None)
    if d is None or isinstance(d, (str, int, float, bool)):
        raise SwBuildError(f"SW 里没有活动文档（ActiveDoc = {d!r}）")
    if not hasattr(d, "GetTitle"):                  # 是方法而非属性 → 调一次
        try:
            d = d()
        except Exception as e:                      # noqa: BLE001
            raise SwBuildError(f"取活动文档失败: {str(e)[:80]}") from e
    return d


def measure_sw_volume_mm3(driver: Any) -> float:
    """SW 质量属性的体积（mm³）。

    晚期绑定下 `Body2.GetMassProperties(1)` 返回的是**元组**而不是对象
    （探针 `_sw_probe_vol.py` 用 20×20×5 的板标定过：`[3]` 就是体积，
    文档为 MKS 时单位是 m³）。
    """
    bodies = active_doc(driver).GetBodies2(0, True)     # 0 = swSolidBody
    if not bodies:
        raise SwBuildError("模型里没有实体（特征全失败或全被切除？）")
    total = 0.0
    scale = 1.0 if getattr(driver, "_doc_unit_is_mm", False) else 1e9
    for b in bodies:
        mp = b.GetMassProperties(1)
        if mp is None or len(mp) < 4:
            raise SwBuildError(f"GetMassProperties 返回值异常: {mp!r}")
        total += float(mp[3]) * scale
    return total


#: 本模块给 SW 特征起的名字前缀（`_name_feature` + 各 builder 里的 feat_name）。
#: `list_sw_features(only_built=True)` 与验收脚本共用这一张表 —— 免得
#: "数出来几个"两边各算各的。
_BUILT_PREFIXES = ("Base", "Boss", "Cut", "Revolve", "Fillet", "Chamfer")


def list_sw_features(doc: Any, only_built: bool = False) -> list[str]:
    """SW 特征树里的特征名（自顶向下），用于核对"特征数与特征模型一致"。

    `only_built=True` 只留**本次建模建出来的**特征（`_BUILT_PREFIXES`），
    滤掉 SW 的样板节点（收藏/历史记录/传感器/注解…）、基准面与草图 —— 那些
    不是"步骤"，数进去就无法与特征树逐条对了。SW 的默认名（`切除-拉伸7`）
    同样不匹配，所以**发射器必须给特征起名**才数得准（见 `_name_feature`）。

    这是阶段 4 验收里"SW 特征树可编辑"的**可核查**那一半：几何量（体积）
    对得上还不够 —— 一个用拉伸基体+切除拼出来的等价模型体积也准，但它不是
    特征树。数一数 SW 里真有几步特征，才能说特征模型确实被发射成了原生特征。

    晚期绑定下的踩坑记录：SW 的成员是"属性"还是"方法"同一个 SW 版本里也不统一
    —— `GetDocuments`/`GetSketchSegments`/`GetActiveSketch2` 是属性，
    `InsertRefPlane`/`FeatureCut3` 是方法。**别用 `callable()` 判**：win32com 的
    dynamic 对象一律 callable，把属性值再调一次会抛 `(-2147352573, '找不到成员')`
    （2026-09-28 实测，两个探针都栽在这上面）。判据改用"值本身像不像 SW 对象"
    （都带 `Name`），见 `_sw_member`。
    """
    out: list[str] = []
    f = _sw_member(doc, "FirstFeature")
    while f is not None:
        out.append(str(_sw_member(f, "Name")))
        f = _sw_member(f, "GetNextFeature")
    if only_built:
        out = [n for n in out if n.startswith(_BUILT_PREFIXES)]
    return out


def _sw_member(obj: Any, name: str) -> Any:
    """读 SW 对象的成员，兼容晚期绑定下"属性/方法"两种形态。

    先按**属性**读；读出来是个带 `Name` 的 COM 对象（Feature/Plane/Sketch 都带）
    就当成值返回；否则当成方法调一次。两者都失败就抛 —— 猜错形态比报错更贵。
    """
    v = getattr(obj, name)
    if v is None or isinstance(v, (str, int, float, bool, tuple, list)):
        return v
    try:
        getattr(v, "Name")
        return v
    except Exception:                                       # noqa: BLE001
        pass
    try:
        return v()
    except Exception as e:                                  # noqa: BLE001
        raise SwBuildError(f"读取 SW 成员 {name!r} 失败（属性/方法两种形态都不通）: "
                           f"{str(e)[:80]}") from e


def _measure_step_volume_mm3(path: Path) -> tuple[float, int, str]:
    """用 OCC 量 STEP 的体积/实体数（需 cad-occt 环境）。

    刻意**不** import `verify/step_probe`：emit 层的依赖方向只允许指向 `model`
    （ARCHITECTURE §5），而且这里只要一个体积。完整版（含悬挂面片判据）在
    `src/rebuild/verify/step_probe.py`。
    """
    from OCC.Core.BRepGProp import brepgprop
    from OCC.Core.GProp import GProp_GProps
    from OCC.Core.STEPControl import STEPControl_Reader
    from OCC.Core.TopAbs import TopAbs_SOLID
    from OCC.Core.TopExp import TopExp_Explorer

    r = STEPControl_Reader()
    if r.ReadFile(str(path)) != 1:
        raise SwBuildError(f"STEP 读取失败: {path}")
    r.TransferRoots()
    shape = r.OneShape()
    if shape.IsNull():
        raise SwBuildError(f"STEP 内容为空: {path}")
    n, vol = 0, 0.0
    exp = TopExp_Explorer(shape, TopAbs_SOLID)
    while exp.More():
        props = GProp_GProps()
        brepgprop.VolumeProperties(exp.Current(), props)
        vol += props.Mass()
        n += 1
        exp.Next()
    return vol, n, ""


def _export_step_copy(driver: Any, step_path: Path) -> Path | None:
    """另存一份 STEP 副本供独立复核，**不改**活动文档的路径。失败返回 None。

    ⚠️ 不能用 `model.SaveAs3`：它会把活动文档的路径改成 .step（模型就跟 .sldprt
    脱钩了，后续保存都按 STEP 走）。`Extension.SaveAs` 是"另存副本、文档不变"，
    参数个数在 SW 各版本间有 6/7 两个版本，故逐个试；都失败则退回
    SaveAs3 到 STEP 再 SaveAs3 回 .sldprt（把路径改回来）。

    ⚠️⚠️ **路径必须绝对**（探针实测的坑，卡了半天）：传相对路径时
    `Extension.SaveAs` 静默返回 **False**、文件不会出现，而 `SaveAs3` 更阴——
    返回"成功"但文件同样不存在。原因是 SW 进程按**它自己的工作目录**解析相对
    路径（不是调用方的 cwd）。两条修复腿都统一 `resolve()`。
    """
    step_path = Path(step_path).resolve()
    try:
        import pythoncom
        from win32com.client import VARIANT

        errs = VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
        warns = VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
        null_disp = VARIANT(pythoncom.VT_DISPATCH, None)
        ext = driver.sw_model.Extension
        # ⚠️ 实测（探针）：SW2025 晚期绑定下 **6 参数** 形式可用
        #    `Extension.SaveAs(路径, 0, 0, NULLDISP, errs, warns) -> True`，
        #    导出后活动文档仍是 .SLDPRT（路径不变）；7 参数形式报"类型不匹配"。
        #    这里先 6 后 7 逐个试，并把每次失败的原因打出来——STEP 复核是可选
        #    增强，静默跳过等于把"没核对"伪装成"核对通过"。
        attempts = (("6 参数", (str(step_path), 0, 0, null_disp, errs, warns)),
                    ("7 参数", (str(step_path), 0, 0, null_disp, null_disp,
                                errs, warns)))
        for label, args in attempts:
            try:
                ok = ext.SaveAs(*args)
                if ok and step_path.exists():
                    return step_path
                print(f"[emit] Extension.SaveAs({label}) -> {ok!r}，"
                      f"文件存在={step_path.exists()}")
            except Exception as e:
                print(f"[emit] Extension.SaveAs({label}) 异常: {e}")
    except Exception as e:
        print(f"[emit] Extension.SaveAs 不可用: {e}")

    sldprt = driver.sw_model.GetPathName
    try:                                            # 兜底：SaveAs3 往返，路径改回来
        driver.sw_model.SaveAs3(str(step_path), 0, 0)
        if step_path.exists():
            print("[emit] 已用 SaveAs3 导出 STEP（随后把活动文档路径改回 .sldprt）")
            if sldprt:
                driver.sw_model.SaveAs3(sldprt, 0, 0)
            return step_path
        print(f"[emit] SaveAs3 返回了但文件不存在: {step_path}")
    except Exception as e:
        print(f"[emit] STEP 导出失败（不影响建模，OCC 复核跳过）: {e}")
    return None


# ---------------------------------------------------------------------------
# 自证 demo
# ---------------------------------------------------------------------------

def _claim(v: Any) -> Claim[Any]:
    """手工构造用的 Claim（**没有图纸依据**，故只能是 guess —— 它就该被报出来）。"""
    return Claim(v, "demo:handmade", Tier.GUESS)


def _demo_plate_hole() -> tuple[Part, float, tuple[float, float, float]]:
    """100×60×20 板 + Ø10 通孔。解析体积 118429.204 mm³。"""
    p = Part()
    p.add(Feature(
        id=FeatureId(0),
        type=_claim(FeatureType.BASE),
        params={
            "dir": _claim("z"),
            "length": _claim(20.0),
            "profile": _claim([(0.0, 0.0), (100.0, 0.0), (100.0, 60.0), (0.0, 60.0)]),
        },
        axis=_claim(Axis3(Point3(0.0, 0.0, 0.0), _DIRS["z"])),
    ))
    p.add(Feature(
        id=FeatureId(1),
        type=_claim(FeatureType.HOLE),
        params={
            "radius": _claim(5.0), "through": _claim(True), "axial_at": _claim(0.0),
        },
        axis=_claim(Axis3(Point3(50.0, 30.0, 0.0), _DIRS["z"])),
    ))
    vol = 100.0 * 60.0 * 20.0 - math.pi * 25.0 * 20.0
    return p, vol, (20.0, 60.0, 100.0)


def _demo_shaft() -> tuple[Part, float, tuple[float, float, float]]:
    """三段阶梯轴（Ø20/Ø12/Ø8 各长 20）+ Ø6 轴向通孔。

    解析体积 = π(10²+6²+4²)·20 − π·3²·60 = 7853.98 mm³。
    """
    gen = [(0.0, 10.0), (20.0, 10.0), (20.0, 6.0), (40.0, 6.0), (40.0, 4.0), (60.0, 4.0)]
    p = Part()
    p.add(Feature(
        id=FeatureId(0),
        type=_claim(FeatureType.REVOLVE),
        params={"angle_deg": _claim(360.0), "radius_profile": _claim(gen),
                "dir": _claim("z")},
        axis=_claim(Axis3(Point3(0.0, 0.0, 0.0), _DIRS["z"])),
    ))
    p.add(Feature(
        id=FeatureId(1),
        type=_claim(FeatureType.HOLE),
        params={"radius": _claim(3.0), "through": _claim(True),
                "axial_at": _claim(0.0)},
        axis=_claim(Axis3(Point3(0.0, 0.0, 0.0), _DIRS["z"])),
    ))
    vol = math.pi * (10.0 ** 2 + 6.0 ** 2 + 4.0 ** 2) * 20.0 - math.pi * 9.0 * 60.0
    return p, vol, (20.0, 20.0, 60.0)


def _demo_plate_boss() -> tuple[Part, float, tuple[float, float, float]]:
    """40×40×10 板 + Ø16×10 凸台 + 板四竖棱 R3 圆角 + 凸台顶圆 C2 倒角。

    解析体积 = 16000 + π·8²·10 − 4·(3² − π·3²/4)·10 − [π·8²·2 − (π·2/3)(8²+8·6+6²)]
            = 16000 + 2010.619298 − 77.256660 − 92.153386 = 17841.209252 mm³

    这条场景是给 BOSS / FILLET / CHAMFER 三条 builder 用的 —— 它们恰恰是最容易
    **静默错几何**的地方（圆角误选中面 → 整圈被倒圆；倒角参数序错 → 削掉一层），
    所以必须进自证链：解析值对得上才算过。
    """
    p = Part()
    p.add(Feature(
        id=FeatureId(0),
        type=_claim(FeatureType.BASE),
        params={"dir": _claim("z"), "length": _claim(10.0),
                "profile": _claim([(0.0, 0.0), (40.0, 0.0), (40.0, 40.0), (0.0, 40.0)])},
        axis=_claim(Axis3(Point3(0.0, 0.0, 0.0), _DIRS["z"])),
    ))
    p.add(Feature(
        id=FeatureId(1),
        type=_claim(FeatureType.BOSS),
        params={"radius": _claim(8.0), "height": _claim(10.0),
                "axial_at": _claim(10.0)},
        axis=_claim(Axis3(Point3(20.0, 20.0, 0.0), _DIRS["z"])),
        depends_on=[FeatureId(0)],
    ))
    p.add(Feature(
        id=FeatureId(2),
        type=_claim(FeatureType.CHAMFER),
        params={"distance": _claim(2.0), "angle_deg": _claim(45.0),
                "edges": _claim("28,20,20")},           # 凸台顶圆上一点（IR mm）
        depends_on=[FeatureId(1)],
    ))
    p.add(Feature(
        id=FeatureId(3),
        type=_claim(FeatureType.FILLET),
        params={"radius": _claim(3.0),
                "edges": _claim(["0,0,5", "40,0,5", "40,40,5", "0,40,5"])},
        depends_on=[FeatureId(0)],
    ))
    r = 3.0
    fillet_cut = 4.0 * (r ** 2 - math.pi * r ** 2 / 4.0) * 10.0
    rad = 8.0
    cham_cut = (math.pi * rad ** 2 * 2.0
                - math.pi * 2.0 / 3.0 * (rad ** 2 + rad * (rad - 2.0) + (rad - 2.0) ** 2))
    vol = 40.0 * 40.0 * 10.0 + math.pi * rad ** 2 * 10.0 - fillet_cut - cham_cut
    return p, vol, (20.0, 40.0, 40.0)


def _arc_end_part(dir_name: str) -> tuple[Part, float, tuple[float, float, float]]:
    """80×40×15 板 + 右端 R20 半圆头（D 形，弧段在**基体轮廓**里）。

    解析体积 = (80×40 + π·20²/2)·15 = 57424.777961 mm³。
    专给 Profile2 弧段 sketch 路径：SW ``CreateArc`` 方向参数错了会**静默**
    画出补弧（特征照样建成、体积对不上），所以必须进自证链量体积。
    轮廓：底边 → 右端凸半圆（(80,0)→(80,40) 经 (100,20)）→ 顶边 → 左边。
    """
    prof = Profile2((
        ProfileSeg2("line", Point2(0.0, 0.0), Point2(80.0, 0.0)),
        ProfileSeg2("arc", Point2(80.0, 0.0), Point2(80.0, 40.0),
                    Point2(80.0, 20.0), 20.0, True, -math.pi / 2, math.pi / 2),
        ProfileSeg2("line", Point2(80.0, 40.0), Point2(0.0, 40.0)),
        ProfileSeg2("line", Point2(0.0, 40.0), Point2(0.0, 0.0)),
    ))
    p = Part()
    p.add(Feature(
        id=FeatureId(0),
        type=_claim(FeatureType.BASE),
        params={"dir": _claim(dir_name), "length": _claim(15.0), "profile": _claim(prof)},
        axis=_claim(Axis3(Point3(0.0, 0.0, 0.0), _DIRS[dir_name])),
    ))
    vol = (80.0 * 40.0 + math.pi * 400.0 / 2.0) * 15.0
    return p, vol, (100.0, 40.0, 15.0)


def _demo_arc_end() -> tuple[Part, float, tuple[float, float, float]]:
    """arc_end：轴向 z（上视基准面，局部映射为恒等）。"""
    return _arc_end_part("z")


def _demo_arc_end_y() -> tuple[Part, float, tuple[float, float, float]]:
    """arc_end_y：同轮廓、轴向 y（前视基准面）——``_Frame.local`` 在此把
    两个坐标**对调**（含反射），专测 `_sketch_profile` 弧方向"在局部坐标
    里重判叉积"那条式子；沿轮廓 ``ccw`` 直传会在这帧上画成补弧。"""
    return _arc_end_part("y")


_DEMOS: dict[str, Callable[[], tuple[Part, float, tuple[float, float, float]]]] = {
    "plate_hole": _demo_plate_hole,
    "shaft": _demo_shaft,
    "plate_boss": _demo_plate_boss,
    "arc_end": _demo_arc_end,
    "arc_end_y": _demo_arc_end_y,
}


def _run_demo(driver: Any, name: str, out_dir: Path, tol: float,
              with_step: bool) -> bool:
    """建一个 demo 模型并**核对体积**（不过容差即失败）。返回是否通过。"""
    part, expect_vol, expect_ext = _DEMOS[name]()
    print("\n" + "=" * 72)
    print(f"[demo] {name}  解析体积 = {expect_vol:.3f} mm³  解析外形 = {expect_ext}")
    print("=" * 72)
    path = _build_in(driver, part, out_dir / f"rebuild_{name}")
    doc = driver.sw_model                        # 刚建好的那个（全程没换活动文档）

    ok = True
    sw_vol = measure_sw_volume_mm3(driver)
    dev = (sw_vol - expect_vol) / expect_vol * 100.0
    print(f"[demo] SW 质量属性体积 = {sw_vol:.3f} mm³  "
          f"偏差 {dev:+.4f}%  {'PASS' if abs(dev) <= tol else 'FAIL'}")
    ok &= abs(dev) <= tol

    box = doc.GetPartBox(True)
    if box:
        ext = tuple(sorted(round((box[i + 3] - box[i]) * 1000.0, 3) for i in range(3)))
        same = all(abs(a - b) < 0.05 for a, b in zip(ext, sorted(expect_ext)))
        print(f"[demo] 实测外形 = {ext}（解析 {tuple(sorted(expect_ext))}）  "
              f"{'PASS' if same else 'FAIL'}")
        ok &= same

    if with_step:
        step = path.with_suffix(".step")
        if _export_step_copy(driver, step) is not None:
            try:
                vol, n, _ = _measure_step_volume_mm3(step)
                dev2 = (vol - expect_vol) / expect_vol * 100.0
                print(f"[demo] OCC 读回 STEP 体积 = {vol:.3f} mm³（{n} 个实体）"
                      f"  偏差 {dev2:+.4f}%  {'PASS' if abs(dev2) <= tol else 'FAIL'}")
                ok &= abs(dev2) <= tol
            except ImportError:
                print("[demo] 无 OCC（当前解释器不是 cad-occt），跳过 STEP 复核")
            except Exception as e:
                print(f"[demo] STEP 复核失败: {e}")
                ok = False
    return ok


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or "--help" in argv or "-h" in argv:
        print(__doc__)
        print("用法:")
        print("  python -m src.rebuild.emit.sw_builder --demo"
              " [--scenario plate_hole|shaft|plate_boss|all]"
              " [--out DIR] [--tol 0.5] [--no-step]")
        return 0 if argv else 2

    out_dir = Path("CAD/temp_output")
    tol = 0.5
    with_step = "--no-step" not in argv
    scen = "all"
    if "--out" in argv:
        out_dir = Path(argv[argv.index("--out") + 1])
    if "--tol" in argv:
        tol = float(argv[argv.index("--tol") + 1])
    if "--scenario" in argv:
        scen = argv[argv.index("--scenario") + 1]

    if "--demo" not in argv:
        print("只支持 --demo（发射器的输入是特征树，命令行没有别的入口）")
        return 2
    if not sw_available():
        print("[demo] SW 不在运行 —— 请先启动 SolidWorks 2025（本 demo 要真建模型）")
        return 3

    names = list(_DEMOS) if scen == "all" else [scen]
    for n in names:
        if n not in _DEMOS:
            print(f"[demo] 未知场景 {n!r}（可选 {list(_DEMOS)}）")
            return 2
    driver = _connect(visible=True)
    overall = True
    for n in names:
        overall &= _run_demo(driver, n, out_dir, tol, with_step)

    print("\n" + "=" * 72)
    print("[demo] 总结:", "全部通过" if overall else "有失败项（见上）")
    print("=" * 72)
    return 0 if overall else 1


if __name__ == "__main__":
    raise SystemExit(main())
