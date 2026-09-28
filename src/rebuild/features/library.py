# -*- coding: utf-8 -*-
"""特征类型定义 + "该长什么样"的预测（ARCHITECTURE §4.4、§6.3）。

**本模块是特征树的词典**：每个 `FeatureType` 有哪些参数（`PARAMS`）、
这些参数在 3D 里怎么解释、以及它**投影到各视图该出现什么图元**
（`predict_in_view`）。

## 为什么预测放在 features 层而不是 verify 层

预测用的是特征自身的几何（半径、轴向、深度），与"视图怎么摆"无关 ——
把 3D 图元投到 2D 图纸坐标是 `verify/predict.py` 的事（那里才有 frame）。
这样分的好处：`features/` 不依赖 `views/`，符合 §5 的依赖方向，
且预测可以在没有图纸的情况下单测。

## 参数命名约定（emitters 按此消费，**不要各写一套**）

- 长度一律 mm，角度一律度（`*_deg`）
- 位置一律"沿轴自零件原点起"（`axial_at`），**不写绝对图纸坐标**
- `axis` 走 `Feature.axis`（`Claim[Axis3]`），不进 params
- `profile` 是闭合环 `list[(a, b)]`（mm），a/b 是垂直于 `dir` 的那个平面
  内的两个坐标，顺序沿右手法则为正
- 缺参数就报 `KeyError`，**绝不默认 0**（§3 原则一的反面：静默默认值
  正是旧管线 53.7% 空心体的成因）

## 与 `dxf_to_sw_features.py` 的关系

那份脚本的 `_segments`/`_sketch_loop`/`FeatureCut3` 是 SW 侧的**接口知识**
（哪些必须 no_snap、哪些必须吸附），`emit/sw_builder.py` 复用它；
本模块只负责"特征是什么"，两者不重叠。
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from ..model.claim import Claim, Tier
from ..model.feature_tree import Feature, FeatureType
from ..model.geom import Axis3, Point3, Vector3
from ..model.ids import FeatureId

#: 轴向名 → 单位向量（与 model/geom.AXIS_BY_NAME 同源，此处仅为方便）
_DIRS: dict[str, Vector3] = {
    "x": Vector3(1.0, 0.0, 0.0),
    "y": Vector3(0.0, 1.0, 0.0),
    "z": Vector3(0.0, 0.0, 1.0),
}

#: 沿某轴拉伸/切槽时，`profile` 的 (a, b) 坐标所在的两个基向量。
#: **右手约定：b1 × b2 = dir**（三条都成立）——
#:   dir=x → (y, z)   dir=y → (z, x)   dir=z → (x, y)
#: 这不是随手排的：发射器（`emit/sw_builder.py` 的 `_FRAMES`、`emit/occ_builder.py`）
#: 必须与识别器用**同一张表**，否则轮廓的 a/b 调换会造出"转 90° 的零件"而这种
#: 错是静默的（体积、bbox 都可能仍然自洽）。此处是唯一权威，改这里前先想清楚。
_PLANE: dict[str, tuple[Vector3, Vector3]] = {
    "x": (_DIRS["y"], _DIRS["z"]),
    "y": (_DIRS["z"], _DIRS["x"]),
    "z": (_DIRS["x"], _DIRS["y"]),
}


def profile_plane(dir_name: str) -> tuple[Vector3, Vector3]:
    """轮廓坐标 (a, b) 的两个基向量（右手：b1 × b2 = dir）。"""
    try:
        return _PLANE[dir_name]
    except KeyError:
        raise ValueError(f"未知拉伸轴向 {dir_name!r}（只有 x/y/z）") from None


def ir_point(o: Point3, dir_name: str, a: float, b: float, t: float) -> Point3:
    """轮廓点：原点 o + (a, b) 在基向量上的分量 + 沿轴的 t。"""
    b1, b2 = profile_plane(dir_name)
    d = _DIRS[dir_name]
    return o + b1 * a + b2 * b + d * t


def ir_coords(p: Point3, dir_name: str) -> tuple[float, float, float]:
    """IR 点 → 轮廓坐标 (a, b) 与沿轴的 t。

    **以零件原点为原点**：``ir_point`` 取 ``o = 原点`` 时二者才是互逆的。
    特征自己的 ``placement`` 另算 —— 例如基体的 origin 是它包围盒的角点，
    要拿它的轮廓坐标得先减掉 origin。
    """
    b1, b2 = profile_plane(dir_name)
    d = _DIRS[dir_name]
    v = p.as_vector
    return (v.dot(b1), v.dot(b2), v.dot(d))

#: 各特征类型的**必需参数**（emitters 与 recognizer 共同遵守的契约）。
PARAMS: dict[FeatureType, tuple[str, ...]] = {
    FeatureType.BASE: ("dir", "length", "profile"),
    FeatureType.REVOLVE: ("angle_deg", "radius_profile", "dir"),
    FeatureType.BOSS: ("radius", "height"),
    FeatureType.HOLE: ("radius", "through"),
    FeatureType.POCKET: ("profile", "depth"),
    FeatureType.SLOT: ("width", "length", "depth"),
    FeatureType.FILLET: ("radius",),
    FeatureType.CHAMFER: ("distance",),
    FeatureType.PATTERN: ("kind", "count"),
}

#: 可选参数 + 语义（供 emitters 识别"有就给、没有就按默认"）
OPTIONAL_PARAMS: dict[FeatureType, dict[str, str]] = {
    FeatureType.BASE: {"origin": "零件原点在图纸系的位置（mm）"},
    FeatureType.BOSS: {"axial_at": "凸台起始处沿轴的坐标（mm）"},
    FeatureType.HOLE: {"depth": "盲孔深度（mm）；through=True 时忽略",
                       "axial_at": "孔口沿轴的坐标（mm）",
                       "count": "同一轴上的孔数（0/1 = 单孔）"},
    FeatureType.SLOT: {"axial_at": "槽底沿轴的坐标（mm）"},
    FeatureType.POCKET: {"axial_at": "腔底沿轴的坐标（mm）"},
    FeatureType.FILLET: {"edges": "被圆角的棱（字符串标识，见 emit/occ_builder）"},
    FeatureType.CHAMFER: {"edges": "被倒角的棱", "angle_deg": "倒角角度，默认 45"},
    FeatureType.PATTERN: {"bc_radius": "圆形阵列的分布圆半径（mm）",
                          "pitch": "线性阵列的间距（mm）",
                          "center": "阵列中心 Point3",
                          "child": "被阵列的特征 id",
                          "start_deg": "起始角（度）"},
}


# ---- 预测用的 3D 图元 ----

@dataclass(frozen=True)
class Prim3:
    """特征**应该**在某视图里留下的图元（3D 描述）。

    `visible` 是制图语义的一部分：孔是"没有材料"，它从侧面看是**虚线**；
    凸台是"多了材料"，是**实线**。这条区分是"孔 vs 凸台"歧义唯一的消解依据
    （§3 原则二），所以它是预测的一等属性，不是渲染细节。
    """

    kind: str                       # "circle" | "segment" | "point"
    feature_id: FeatureId
    #: 圆的中心 / 线段中点
    center: Point3
    radius: float = 0.0
    start: Point3 | None = None
    end: Point3 | None = None
    #: 圆所在平面的法向（= 圆柱轴）；线段则为其方向
    direction: Vector3 = Vector3(0.0, 0.0, 1.0)
    visible: bool = True
    #: 该预测对应特征的哪个参数（报告里定位用）
    of_param: str = ""

    def __str__(self) -> str:
        c = f"@{self.center.x:.2f},{self.center.y:.2f},{self.center.z:.2f}"
        if self.kind == "circle":
            return f"#{self.feature_id} 圆 r{self.radius:.2f} {c} {'实' if self.visible else '虚'}"
        if self.kind == "segment" and self.start and self.end:
            return (f"#{self.feature_id} 线 ({self.start.x:.2f},{self.start.y:.2f})"
                    f"-({self.end.x:.2f},{self.end.y:.2f}) {'实' if self.visible else '虚'}")
        return f"#{self.feature_id} {self.kind} {c}"


def _num(f: Feature, name: str, default: float | None = None) -> float | None:
    c = f.params.get(name)
    if c is None or c.value is None:
        return default
    return float(c.value)


def _dir_of(f: Feature) -> Vector3:
    """特征的轴向单位向量：优先 Feature.axis，退回 params['dir']。"""
    if f.axis is not None and f.axis.value is not None:
        return f.axis.value.direction.normalized()
    d = f.params.get("dir")
    if d is not None and isinstance(d.value, str):
        return _DIRS.get(d.value, _DIRS["z"])
    if d is not None and isinstance(d.value, Vector3):
        return d.value.normalized()
    return _DIRS["z"]


def _origin_of(f: Feature) -> Point3:
    if f.axis is not None and f.axis.value is not None:
        return f.axis.value.origin
    p = f.placement.value
    if isinstance(p, Point3):
        return p
    return Point3(0.0, 0.0, 0.0)


# ---- 视图方向 ----

def view_dir(view_type: str) -> Vector3:
    """观察方向（**由观察者指向零件**）—— 主视看 −Y，俯视看 −Z，左视看 +X。

    与 CLAUDE.md 的图纸系一致：X 向右、Y 向里、Z 向上。
    """
    return {
        "front": Vector3(0.0, -1.0, 0.0),
        "rear": Vector3(0.0, 1.0, 0.0),
        "top": Vector3(0.0, 0.0, -1.0),
        "bottom": Vector3(0.0, 0.0, 1.0),
        "left": Vector3(1.0, 0.0, 0.0),
        "right": Vector3(-1.0, 0.0, 0.0),
    }.get(view_type, Vector3(0.0, -1.0, 0.0))


def is_along(view_type: str, axis_dir: Vector3) -> bool:
    """该视图是否**顺着**这条轴看（圆柱截成圆）。"""
    return abs(view_dir(view_type).normalized().dot(axis_dir.normalized())) > 0.99


def is_across(view_type: str, axis_dir: Vector3) -> bool:
    """该视图是否**横着**看这条轴（圆柱截成两条平行线）。"""
    return abs(view_dir(view_type).normalized().dot(axis_dir.normalized())) < 0.01


# ---- 逐类型的预测 ----

def predict_in_view(f: Feature, view_type: str) -> list[Prim3]:
    """特征在该视图里**应该**出现的图元（3D 描述）。

    只覆盖可解析预测的情形；预测不出的返回空表（不是错误 ——
    复杂轮廓交给 `verify/reproject` 用真 HLR 兜底，见 §6.3）。
    """
    t = f.type.value
    fn = _PREDICTORS.get(t)
    if fn is None:
        return []
    try:
        return fn(f, view_type)
    except (KeyError, ValueError):
        # 参数不全的特征预测不出 —— 让它进"未解释"清单，不要在这里炸
        return []


def _predict_cylindrical(f: Feature, view_type: str, visible: bool) -> list[Prim3]:
    """圆柱类（孔/凸台）的预测：顺轴看是圆，横着看是两条平行线。"""
    ax = _dir_of(f)
    o = _origin_of(f)
    r = _num(f, "radius")
    if r is None:
        return []
    if is_along(view_type, ax):
        return [Prim3("circle", f.id, o, radius=r, direction=ax, visible=visible,
                      of_param="radius")]
    if not is_across(view_type, ax):
        return []
    # 横着看：轮廓是两条与轴平行、距轴 r 的线 —— 长度取特征的"高度/深度"
    h = _num(f, "height")
    if h is None:
        h = _num(f, "depth")
    if h is None:
        h = _num(f, "length")
    if h is None:
        return []                       # 通孔的长度由基体决定，投影层按基体裁
    a0 = _num(f, "axial_at", 0.0) or 0.0
    perp = _perp(ax)
    out: list[Prim3] = []
    for sign in (1.0, -1.0):
        s = o + ax * a0 + perp * (r * sign)
        e = s + ax * h
        out.append(Prim3("segment", f.id, s + ax * (h / 2.0),
                         start=s, end=e, direction=ax, visible=visible,
                         of_param="radius"))
    return out


def _perp(d: Vector3) -> Vector3:
    """与 d 垂直的任一单位向量（取与坐标轴叉积里模最大的那个，避免退化）。"""
    for c in (Vector3(0.0, 0.0, 1.0), Vector3(1.0, 0.0, 0.0),
              Vector3(0.0, 1.0, 0.0)):
        v = d.cross(c)
        if v.norm > 1e-9:
            return v.normalized()
    raise ValueError("零向量没有垂直方向")


def _predict_hole(f: Feature, view_type: str) -> list[Prim3]:
    # 孔 = 没有材料 ⇒ 侧面轮廓是**虚线**（这正是孔/凸台歧义的消解依据）
    return _predict_cylindrical(f, view_type, visible=False)


def _predict_boss(f: Feature, view_type: str) -> list[Prim3]:
    return _predict_cylindrical(f, view_type, visible=True)


def _predict_slot(f: Feature, view_type: str) -> list[Prim3]:
    ax = _dir_of(f)
    o = _origin_of(f)
    w = _num(f, "width")
    ln = _num(f, "length")
    if w is None or ln is None:
        return []
    perp = _perp(ax)
    if is_along(view_type, ax):
        # 顺轴看：槽是两条平行线（宽 w、长 ln）
        half = ln / 2.0
        s = o - ax * half
        e = o + ax * half
        return [Prim3("segment", f.id, o + perp * (w / 2.0 * sg),
                      start=s + perp * (w / 2.0 * sg), end=e + perp * (w / 2.0 * sg),
                      direction=ax, visible=False, of_param="width")
                for sg in (1.0, -1.0)]
    return []


def _predict_pocket(f: Feature, view_type: str) -> list[Prim3]:
    ax = _dir_of(f)
    o = _origin_of(f)
    dir_name = _name_of_dir(ax)
    prof = f.params.get("profile")
    if prof is None or not isinstance(prof.value, (list, tuple)):
        return []
    pts = [ir_point(o, dir_name, float(p[0]), float(p[1]), 0.0) for p in prof.value]
    if is_along(view_type, ax):
        out = []
        for i, a in enumerate(pts):
            b = pts[(i + 1) % len(pts)]
            out.append(Prim3("segment", f.id, Point3((a.x + b.x) / 2, (a.y + b.y) / 2,
                                                     (a.z + b.z) / 2),
                             start=a, end=b, direction=ax, visible=False,
                             of_param="profile"))
        return out
    return []


def _predict_base(f: Feature, view_type: str) -> list[Prim3]:
    """基体：顺拉伸方向看 = 轮廓环；横着看 = 轮廓的包围矩形（4 条线）。

    轮廓 (a, b) 按 ``profile_plane(dir)`` 落到 3D —— **不能写死 (x, y)**：
    沿 Y 拉伸的板（本仓库大多数零件）轮廓在 (z, x) 面上，写死会把零件转 90°。
    """
    d = _dir_of(f)
    name = f.params.get("dir")
    dir_name = name.value if name is not None and isinstance(name.value, str) \
        else _name_of_dir(d)
    o = _origin_of(f)
    prof = f.params.get("profile")
    ln = _num(f, "length")
    if prof is None or not isinstance(prof.value, (list, tuple)) or ln is None:
        return []
    pts = [ir_point(o, dir_name, float(p[0]), float(p[1]), 0.0) for p in prof.value]
    if is_along(view_type, d):
        out = []
        for i, a in enumerate(pts):
            b = pts[(i + 1) % len(pts)]
            out.append(Prim3("segment", f.id, a + (b - a) * 0.5,
                             start=a, end=b, direction=d, visible=True,
                             of_param="profile"))
        return out
    if is_across(view_type, d):
        aa = [float(p[0]) for p in prof.value]
        bb = [float(p[1]) for p in prof.value]
        corners = [(min(aa), min(bb)), (max(aa), min(bb)),
                   (max(aa), max(bb)), (min(aa), max(bb))]
        pts3 = [ir_point(o, dir_name, a, b, 0.0) for a, b in corners]
        far = d * ln
        out = []
        for i, a in enumerate(pts3):
            b = pts3[(i + 1) % len(pts3)]
            out.append(Prim3("segment", f.id, a + (b - a) * 0.5, start=a, end=b,
                             direction=d, visible=True, of_param="profile"))
            out.append(Prim3("segment", f.id, a + far + (b - a) * 0.5,
                             start=a + far, end=b + far, direction=d,
                             visible=True, of_param="length"))
        return out
    return []


def _name_of_dir(d: Vector3) -> str:
    """单位向量 → 轴名（不在这三条轴上就报错，因为轮廓基向量只定义了三条）。"""
    for n, v in _DIRS.items():
        if max(abs(d.x - v.x), abs(d.y - v.y), abs(d.z - v.z)) < 1e-6:
            return n
    raise ValueError(f"拉伸方向 {d} 不在坐标轴上，轮廓基向量未定义")


def _predict_revolve(f: Feature, view_type: str) -> list[Prim3]:
    ax = _dir_of(f)
    o = _origin_of(f)
    prof = f.params.get("radius_profile")
    if prof is None or not isinstance(prof.value, (list, tuple)):
        return []
    out: list[Prim3] = []
    if is_along(view_type, ax):
        # 顺轴看：一圈同心圆（每个不同的半径一个）
        for i, pair in enumerate(prof.value):
            axpos, r = float(pair[0]), float(pair[1])
            if r <= 0:
                continue
            out.append(Prim3("circle", f.id, o + ax * axpos, radius=r,
                             direction=ax, visible=True,
                             of_param=f"radius_profile[{i}]"))
    elif is_across(view_type, ax):
        # 横着看：母线（台阶轮廓）+ 中心线
        prev: Point3 | None = None
        perp = _perp(ax)
        for i, pair in enumerate(prof.value):
            axpos, r = float(pair[0]), float(pair[1])
            p = o + ax * axpos + perp * r
            if prev is not None:
                out.append(Prim3("segment", f.id, prev, start=prev, end=p,
                                 direction=ax, visible=True, of_param="radius_profile"))
            prev = p
    return out


_PREDICTORS = {
    FeatureType.BASE: _predict_base,
    FeatureType.REVOLVE: _predict_revolve,
    FeatureType.BOSS: _predict_boss,
    FeatureType.HOLE: _predict_hole,
    FeatureType.POCKET: _predict_pocket,
    FeatureType.SLOT: _predict_slot,
}


# ---- 校验与描述 ----

def missing_params(f: Feature) -> list[str]:
    """必需参数是否齐 —— 缺了不许往下走（宁可拒绝也不要静默默认）。"""
    want = PARAMS.get(f.type.value, ())
    return [p for p in want if p not in f.params]


def validate(f: Feature) -> list[str]:
    """返回问题清单（空 = 合格）。"""
    out = [f"缺参数 {p}" for p in missing_params(f)]
    if not f.evidence:
        out.append("无图纸依据（纯猜）")
    return out


def describe(f: Feature, indent: str = "  ") -> str:
    """人读的特征描述（报告用）。"""
    t = f.type.value if f.type.is_settled else \
        f"{f.type.value}?（备选 {[a.value for a in f.type.alternatives]}）"
    lines = [f"{indent}#{f.id:<3} {t:10} 依据 {f.type.method} "
             f"<{f.type.tier.name}>"]
    if f.axis is not None and f.axis.value is not None:
        a = f.axis.value
        lines.append(f"{indent}    轴 过({a.origin.x:.2f},{a.origin.y:.2f},"
                     f"{a.origin.z:.2f}) 向({a.direction.x:.2f},"
                     f"{a.direction.y:.2f},{a.direction.z:.2f})")
    for k, c in f.params.items():
        alt = f"  备选{list(c.alternatives)}" if c.alternatives else ""
        lines.append(f"{indent}    {k:14} = {_fmt(c.value):>12}  "
                     f"<{c.tier.name}>{alt}")
    if f.depends_on:
        lines.append(f"{indent}    依赖 {[str(d) for d in f.depends_on]}")
    if f.evidence:
        lines.append(f"{indent}    图元 {', '.join(str(e) for e in f.evidence[:6])}"
                     + ("…" if len(f.evidence) > 6 else ""))
    for p in validate(f):
        lines.append(f"{indent}    ⚠ {p}")
    return "\n".join(lines)


def _fmt(v: Any) -> str:
    if isinstance(v, float):
        return f"{v:.3f}".rstrip("0").rstrip(".")
    if isinstance(v, (list, tuple)):
        return f"[{len(v)} 点]"
    return str(v)


def mk_claim(value: Any, method: str, tier: Tier,
             evidence: tuple = (), alternatives: tuple = ()) -> Claim:
    """构造 Claim 的便捷入口（记录默认 tier 用法，避免各处随手写 GUESS）。"""
    return Claim(value, method, tier, evidence=tuple(evidence),
                 alternatives=tuple(alternatives))


def axis_claim(origin: Point3, direction: Vector3, method: str, tier: Tier,
               evidence: tuple = (), radius: Claim[float] | None = None
               ) -> Claim[Axis3]:
    """造一条带依据的 3D 轴线 Claim。"""
    return Claim(Axis3(origin, direction.normalized(), radius), method, tier,
                 evidence=tuple(evidence))


def axis_from_point(origin: Point3, dir_name: str) -> Axis3:
    d = _DIRS.get(dir_name)
    if d is None:
        raise ValueError(f"未知轴向 {dir_name!r}")
    return Axis3(origin, d)


#: 特征树的"层"——同层可并行，跨层有依赖（emitters 按此排序，防布尔序错）
LAYER: dict[FeatureType, int] = {
    FeatureType.BASE: 0,
    FeatureType.REVOLVE: 0,
    FeatureType.PATTERN: 1,     # 阵列必须在其 child 之后
    FeatureType.BOSS: 2,
    FeatureType.POCKET: 3,
    FeatureType.HOLE: 3,
    FeatureType.SLOT: 3,
    FeatureType.FILLET: 4,      # 圆角/倒角最后
    FeatureType.CHAMFER: 4,
}


def build_order(features: list[Feature]) -> list[Feature]:
    """拓扑序：先基体，后材料岛，再切除，最后圆角/倒角。

    `depends_on` 优先于层号（显式依赖更可信），层号只作同层稳定排序。
    """
    done: list[Feature] = []
    remaining = list(features)

    def ready(f: Feature) -> bool:
        return all(any(d == g.id for g in done) for d in f.depends_on)

    guard = 0
    while remaining:
        cand = [f for f in remaining if ready(f)]
        if not cand:
            # 依赖成环：按层号强行打破，但要让调用方知道
            raise ValueError("特征依赖成环：" + ", ".join(str(f.id) for f in remaining))
        cand.sort(key=lambda f: (LAYER.get(f.type.value, 9), f.id))
        f = cand[0]
        done.append(f)
        remaining.remove(f)
        guard += 1
        if guard > 10000:
            raise RuntimeError("build_order 未收敛")
    return done


def normal_at(p: Point3, d: Vector3) -> Vector3:
    """给定点与轴，返回该点处垂直于轴的径向单位向量（测试与预测共用）。"""
    return _perp(d)


def radians(deg: float) -> float:
    return deg * math.pi / 180.0


__all__ = [
    "PARAMS", "OPTIONAL_PARAMS", "LAYER", "Prim3",
    "build_order", "describe", "is_across", "is_along", "missing_params",
    "normal_at", "predict_in_view", "validate", "view_dir",
    "axis_claim", "axis_from_point", "mk_claim",
]
