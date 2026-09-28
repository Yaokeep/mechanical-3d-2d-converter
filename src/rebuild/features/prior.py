# -*- coding: utf-8 -*-
"""标准值先验 —— 图纸没写的信息，有一部分**在图纸之外**（ARCHITECTURE §3 原则一）。

## 这一层存在的理由：有些信息不在图上，但在标准里

CLAUDE.md 的"信息论局限"表里有一行：**R8 vs R8.5 凹槽半径差** ——
图纸只标 φ17，重建按标注走（⇒ r8.5），而真件是 R8。旧管线的判决是
"不可修复"，因为 φ17 确实就是图上的全部信息。

但这句话只对了一半：**图纸没写 ≠ 无从判断**。半径 8.5 不是优先数系里的
数（GB/T 321 R10/R20 都没有 8.5，而 8.0 是 R10 的项），而 φ8.5 恰恰是
标准麻花钻直径 —— 也就是说"用钻头直径去标注一个凹槽半径"这件事本身
就留下了痕迹。带标准值先验的读法会**同时给出**两个候选并说明各自依据，
让人一眼看出该按哪个走；不带先验的读法只能照抄标注。

所以本模块产出的是 tier=PRIOR 的 Claim（**比标注低一档，绝不覆盖标注**）：

- 值 = 最近的标准值
- 原值进 ``alternatives`` —— 歧义不消解（§3 原则二）
- ``is_guessed`` 为真 ⇒ 它一定会进报告的"待确认"清单

## 数据来源与取舍

- **R10/R20 优先数系**（GB/T 321）—— 长度/半径类尺寸的首选。圆角、凹槽、
  退刀槽半径按惯例取 R10 值（这也是 8.0 而非 8.5 的依据）
- **常用麻花钻直径**（GB/T 6135 常用段）—— 孔的**直径**按钻头走。注意它
  含 8.5（φ8.5 钻头），所以"φ17 孔"在直径维度上是标准值，在半径维度上
  不是 —— 这两张表分开正是因为它们说的是两件事

表是**有限子集**（1~100mm 常用段），超出范围一律返回"非标准"而不是硬套。
"""
from __future__ import annotations

from dataclasses import dataclass

from ..model.claim import Claim, Tier

#: R10/R20 优先数系（GB/T 321）常用段 —— 半径/长度类的标准值
PREFERRED_R: tuple[float, ...] = (
    0.5, 0.8, 1.0, 1.2, 1.6, 2.0, 2.5, 3.0, 4.0, 5.0, 6.0, 8.0, 10.0,
    12.0, 16.0, 20.0, 25.0, 32.0, 40.0, 50.0, 63.0, 80.0, 100.0,
)

#: 常用麻花钻直径（GB/T 6135 常用段）—— 孔的**直径**按钻头走
DRILL_D: tuple[float, ...] = (
    1.0, 1.5, 2.0, 2.5, 3.0, 3.3, 3.5, 4.0, 4.2, 4.5, 5.0, 5.5, 6.0, 6.5,
    6.8, 7.0, 7.5, 8.0, 8.5, 9.0, 9.5, 10.0, 10.5, 11.0, 11.5, 12.0, 12.5,
    13.0, 14.0, 15.0, 16.0, 17.0, 18.0, 19.0, 20.0, 21.0, 22.0, 23.0, 24.0,
    25.0, 26.0, 28.0, 30.0, 32.0, 34.0, 35.0, 36.0, 38.0, 40.0, 42.0, 45.0,
    48.0, 50.0, 55.0, 60.0, 65.0, 70.0, 75.0, 80.0, 85.0, 90.0, 95.0, 100.0,
)

#: 吸附容差：实测值偏离标准值多少以内就认为"它本来是标准值，只是测量/出图有误差"。
#: 6% 的依据：DXF 出图与几何量取的相对误差实测在 0.1% 级（见 verify 层），
#: 而相邻标准值的最小间距约 12%（R10 的公比 1.25，R20 约 1.12）——
#: 6% 卡在两者之间：大于噪声、小于"跳到隔壁标准值"的距离
SNAP_TOL = 0.06


@dataclass(frozen=True)
class Snap:
    """一次标准值吸附的结果。

    ``standard`` False 表示"附近没有标准值"—— 此时 ``value`` 原样返回，
    **不是**强行套一个标准值（硬套会造出错得看不出来的尺寸）。
    """

    value: float
    raw: float
    standard: bool
    source: str = ""                  # "R10" / "drill"
    delta_pct: float = 0.0            # 偏离标准值的百分比（0 = 本来就是）
    nearest: tuple[float, ...] = ()   # 原始值附近的标准值（供报告展示候选）

    @property
    def changed(self) -> bool:
        return abs(self.value - self.raw) > 1e-9

    def __str__(self) -> str:
        if not self.standard:
            return f"{self.raw:g}（非标准值，保留原值）"
        if not self.changed:
            return f"{self.raw:g}（{self.source} 标准值）"
        return (f"{self.raw:g} → {self.value:g}（{self.source} 标准值，"
                f"偏离 {self.delta_pct:.2f}%）")


def _snap(raw: float, table: tuple[float, ...], source: str,
          tol: float = SNAP_TOL) -> Snap:
    if raw <= 0:
        return Snap(raw, raw, False)
    near = tuple(v for v in table
                 if abs(v - raw) <= max(tol * raw, 1e-9))
    if not near:
        return Snap(raw, raw, False)
    best = min(near, key=lambda v: abs(v - raw))
    delta = abs(best - raw) / raw * 100.0
    return Snap(best, raw, True, source, delta, near)


def snap_radius(r: float, tol: float = SNAP_TOL) -> Snap:
    """半径按优先数系（R10/R20）吸附。

    这是 CLAUDE.md「R8 vs R8.5」那条的落点：``snap_radius(8.5)`` 会给出
    ``8.0（R10 标准值，偏离 5.88%）`` —— 即"真件多半是 R8"。
    """
    return _snap(r, PREFERRED_R, "R10", tol)


def snap_diameter(d: float, tol: float = SNAP_TOL) -> Snap:
    """直径按常用麻花钻直径吸附（孔是用钻头加工的，直径随钻头走）。"""
    return _snap(d, DRILL_D, "drill", tol)


def groove_radius_from_diameter(d: float) -> Snap:
    """把"标注成直径的凹槽"还原成半径，并带上标准值依据。

    专为 R8 vs R8.5 那条写：图纸标 φ17、真件是 R8。返回的 ``Snap`` 里
    ``value=8.0``（R10）、``raw=8.5`` 在 ``alternatives`` 之外由调用方
    保留 —— 标注值仍然是标注值，先验只是把它**标注成可疑**。
    """
    return snap_radius(d / 2.0)


def snap_claim(value: float, kind: str, *, method: str = "",
               evidence: tuple = (), tol: float = SNAP_TOL) -> Claim[float]:
    """把一个实测值变成"带先验依据的 Claim"。

    ``kind`` ∈ {"radius", "diameter"}。命中标准值 ⇒ ``tier=PRIOR``、
    原值进备选（**歧义不消解**）；没命中 ⇒ 原样返回 ``GUESS`` 级
    （调用方应当把实测值那条 Projection Claim 一起交给 ``merge``）。

    ``evidence`` 只在命中时给出：PRIOR 级按 Claim 的不变式**不需要**证据，
    但带上签名用的图元 handle 能让报告说清"是拿哪个尺寸去吸附的"。
    """
    table, source = ((PREFERRED_R, "R10") if kind == "radius"
                     else (DRILL_D, "drill"))
    s = _snap(value, table, source, tol)
    if not s.standard:
        return Claim(s.value, method or f"prior:{source}:无匹配", Tier.GUESS)
    alts = (s.raw,) if s.changed else ()
    return Claim(s.value, method or f"prior:{source}", Tier.PRIOR,
                 evidence=evidence, alternatives=alts)


def snap_note(claim: Claim[float], kind: str) -> str:
    """给一条半径/直径 Claim 写一句"离标准值多远"的报告用语。

    注意它**不改** Claim —— 报告与裁决分开：这里只说话，动不动由 gate 定。
    """
    s = snap_radius(claim.value) if kind == "radius" else snap_diameter(claim.value)
    if not s.standard:
        return f"{claim.value:g} 不在常用标准值表内"
    if not s.changed:
        return f"{claim.value:g} = {s.source} 标准值"
    return (f"{claim.value:g} 不是标准值，最近的是 {s.value:g}"
            f"（{s.source}，偏离 {s.delta_pct:.2f}%）")
