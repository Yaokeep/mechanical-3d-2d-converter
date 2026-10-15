# -*- coding: utf-8 -*-
"""孔标注约定 —— 「n~∅d 深h」这类**孔组标注** ⇒ 直径/数量/深度/通盲的证据。

## 为什么非有不可

YZYX 齿箱上盖的 4×Ø10H7 深25 在图上只有 V3 的四个圆：左视图 V0 是**半剖**，
半外形那一侧按简化画法省掉了孔壁轮廓 ⇒ 投影侧永远量不到轴向长度、也判不出
孔还是凸台（`correspondence` 报「找不到间距 2r 的轮廓对」）。而**标注是图上
明写的**（tier=ANNOTATED）：`4~∅10-7H 深25` 一句话就补齐了投影侧读不出的
全部三件事 —— 直径、数量、深度（通/盲是深度的函数）。

本规则只做**忠实读取**：文字 ⇒ 结构化的 HoleCallout，不负责"这个标注指的是
哪个圆"（那是特征层 `features/callouts.py` 的绑定，需要圆的位置）。

## 只认"孔标注"，不认光秃秃的直径

`φ96.5` / `φ215` / `R15` / `1.5×45°` 这些是**零件/倒角尺寸**，不是孔标注；
混进来会把轴颈读成孔。故一条文字必须**命中至少一个孔特征**才产出
HoleCallout（``matched`` 记下命中的是哪条，供报告与自检）：

  · 数量前缀 ``8~∅13`` / ``4×φ10`` / ``2~M16`` —— 裸 ``φ10`` 没有数量前缀，
    是尺寸；而 "n 个孔" 的数量本来就是孔组才有的说法
  · 深度 ``深25`` —— 只有孔才标深度
  · 孔类关键词：锥销孔 / 锥孔 / 销孔 / 通孔 / 螺孔 / 沉孔 / 锪平 / 配作 / 配钻
  · 螺纹代号 ``M16`` / ``Tr20`` —— M 只用于螺纹孔

实测（YZYX：15 条 NOTE + 1 条 PLAIN 里）6 条命中孔标注（8~∅13 /
4~∅10-7H 深25 / 3~∅10-7H 深20 / 2~∅6锥销孔 / ∅16锥孔 / 2~M16-7H），
其余（技术要求、1×45°、R15、φ96.5、φ160、φ215、φ150、φ210）全部落空。
``2~M16-7H (通孔)`` 在文本层是 **PLAIN**（M16 里的数字不被抽成数值），
所以本规则扫**全部文字**、不只扫 NOTE。

## 通/盲：未注深度 = 通孔

中文制图惯例：孔标注不写深度就是通孔（写上「通孔」是显式冗余）。故
``depth is None ⇒ through=True``，两个字段都留在结论里（下游能看出来
"通"是推的还是写的）。数量缺省 = 1。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, replace

from ..evidence.text_parser import (TextKind, _DIA_CHARS, strip_mtext_codes)
from ..model.claim import Claim, Tier
from ..model.ids import EvidenceRef
from .registry import Convention, ConvKind, RuleCtx, register

#: 数量前缀：8~∅13 / 4×φ10 / 2~M16 / 6-φ8
#: 两条边界与 ``text_parser._COUNT_DIA_RE`` 同宽：左边界防 `φ5.5×90°` 的第二个
#: 5 被当数量，右边界（必须紧跟直径或螺纹代号）防 `1.5×45°` 被当"1.5 个孔"
_COUNT_RE = re.compile(
    rf"(?<![\d.])(\d+)\s*[×xX~\-]\s*(?=[{_DIA_CHARS}]|M\s*\d|Tr\s*\d)")

#: 直径：φ13 / ∅10 / ⌀6
_DIA_RE = re.compile(rf"[{_DIA_CHARS}]\s*(\d+(?:\.\d+)?)")

#: 公制/梯形螺纹代号：M16 / Tr20（大径即名义直径）
_THREAD_RE = re.compile(r"(?<![A-Za-z0-9])(M|Tr)\s*(\d+(?:\.\d+)?)")

#: 深度：深25 / 深度25
_DEPTH_RE = re.compile(r"深(?:度)?\s*(\d+(?:\.\d+)?)")

#: 通孔：显式"通孔"，或括号注写的（通）
_THROUGH_RE = re.compile(r"通孔|[(（]\s*通\s*[)）]")

#: 公差代号：`∅10-7H` / `M16-7H` ⇒ 7H（孔的公差带，信息性字段）
_TOL_CLASS_RE = re.compile(r"[-–—]\s*(\d{1,2}[A-Z]{1,2})(?![A-Za-z0-9])")

#: 孔类关键词 ⇒ (命中的词, 孔的种类)。顺序有意义：先长词后短词。
_HOLE_KW: tuple[tuple[str, str], ...] = (
    ("锥销孔", "taper_pin_hole"),
    ("锥孔", "taper_hole"),
    ("销孔", "pin_hole"),
    ("螺纹孔", "threaded_hole"),
    ("螺孔", "threaded_hole"),
    ("沉孔", "counterbore"),
    ("锪平", "counterbore"),
    ("通孔", "hole"),
    ("配作", "hole"),          # 与配偶件配作 —— 仍是本零件上的孔
    ("配钻", "hole"),
)

#: 不参与孔标注解析的文字种类：视图/剖视标题与投影标志（它们说的是**视图**
#: 不是孔；剖面标题里的"穿 r25.5 孔轴"曾经差点被当成孔标注）
_SKIP_KINDS = (TextKind.VIEW_LABEL, TextKind.DIRECTION_VIEW,
               TextKind.SECTION_TITLE, TextKind.SECTION_MARKER,
               TextKind.PROJECTION)


@dataclass(frozen=True)
class HoleCallout:
    """一条孔组标注的读取结果（``ConvKind.CALLOUT`` 的 value）。

    ``diameter`` 是**图上标注的名义直径**（螺纹写大径，如 M16 ⇒ 16）；
    ``depth`` 为 None 表示图上没标深度，按制图惯例即通孔（``through``）；
    ``matched`` 记命中的孔特征（"count" / "depth" / "kw:锥销孔" / "thread"），
    ``text`` 是洗净 MTEXT 转义后的原文 —— 报告里直接给人看。
    """

    text_ref: EvidenceRef
    text: str
    count: int
    diameter: float
    matched: tuple[str, ...]
    depth: float | None = None
    through: bool = True
    kind: str = "hole"
    thread: str = ""
    tolerance: str = ""
    #: 标注所属视图（按文字位置就近归属，见 :func:`owner_view`）
    view: str = ""

    @property
    def radius(self) -> float:
        """名义半径 —— 圆边按它配对（Δr 容差见 features/callouts）。"""
        return self.diameter / 2.0


def parse_callout(handle: EvidenceRef, raw: str) -> HoleCallout | None:
    """一条文字 ⇒ HoleCallout（不是孔标注返回 None）。独立函数便于自检直测。"""
    s = strip_mtext_codes(raw).strip()
    if not s:
        return None
    matched: list[str] = []
    m = _COUNT_RE.search(s)
    count = int(m.group(1)) if m else 1
    if m:
        matched.append(f"count:{count}")
    thread = ""
    tm = _THREAD_RE.search(s)
    diameter: float | None = None
    if tm:
        thread = f"{tm.group(1)}{tm.group(2)}"
        diameter = float(tm.group(2))
        matched.append("thread")
    dm = _DIA_RE.search(s)
    if dm:
        # 直径字符比螺纹代号更明确；两者同时出现（`2~M16-7H 底孔∅14`）时
        # 取直径，螺纹代号仍留在 thread 里
        diameter = float(dm.group(1))
        matched.append("dia")
    if diameter is None:
        return None                       # 没有直径也没有螺纹 ⇒ 不可能是孔标注
    depth = None
    dpm = _DEPTH_RE.search(s)
    if dpm:
        depth = float(dpm.group(1))
        matched.append(f"depth:{depth:g}")
    kind = "hole"
    for kw, k in _HOLE_KW:
        if kw in s:
            matched.append(f"kw:{kw}")
            if kind == "hole":
                kind = k
    # 门：数量前缀 / 深度 / 关键词 —— 三者一个都没有的，是零件尺寸或倒角
    # （`φ96.5`、`1×45°`），不是孔标注。螺纹代号**单独不算**门：`M16`
    # 也可能是轴的螺纹段尺寸，须再命中 count/深度/关键词之一。
    if not any(x.startswith(("count", "depth", "kw:")) for x in matched):
        return None
    if thread:
        kind = "threaded_hole"
    tol = _TOL_CLASS_RE.search(s)
    return HoleCallout(
        text_ref=handle, text=s, count=count, diameter=diameter,
        matched=tuple(matched), depth=depth, through=depth is None,
        kind=kind, thread=thread,
        tolerance=tol.group(1) if tol else "",
        view="",
    )


def owner_view(d, x: float, y: float) -> str:
    """标注文字**就近**归属到某个视图（文字通常落在视图 bbox 之外的边上）。

    孔标注与圆之间没有引线（YZYX 实测：LEADER 全部配给形位公差 TOLERANCE），
    所以"这条标注说的是哪个视图"只能按位置判 —— 到视图 bbox 的最近距离。
    实测恰好干净：6 条标注各归到唯一视图（∅16锥孔 96mm vs 1359mm、
    2~M16-7H 139mm vs 1400mm，没有并列）。
    """
    best, best_d = "", None
    for v in d.views:
        b = v.bbox
        if b is None:
            continue
        dx = max(b.xmin - x, 0.0, x - b.xmax)
        dy = max(b.ymin - y, 0.0, y - b.ymax)
        dist = (dx * dx + dy * dy) ** 0.5
        if best_d is None or dist < best_d:
            best, best_d = v.id, dist
    return best


@register("callout.hole_groups")
def hole_groups(ctx: RuleCtx) -> list[Convention]:
    """孔组标注（``n~∅d 深h``）⇒ 直径/数量/深度/通盲 + 就近归属的视图。"""
    out: list[Convention] = []
    for t in ctx.d.texts:
        if t.kind in _SKIP_KINDS:
            continue
        hc = parse_callout(t.handle, t.text)
        if hc is None:
            continue
        view = owner_view(ctx.d, t.x, t.y)
        hc = replace(hc, view=view)
        out.append(Convention(
            rule="callout.hole_groups", kind=ConvKind.CALLOUT, view=view,
            value=hc,
            claim=Claim(hc, "annotation:hole_callout", Tier.ANNOTATED,
                        evidence=(t.handle,)),
            note=_callout_note(hc),
            evidence=(t.handle,),
        ))
    return out


def _callout_note(hc: HoleCallout) -> str:
    body = f"「{hc.text}」⇒ {hc.count}×φ{hc.diameter:g}"
    if hc.thread:
        body += f"（{hc.thread}"
        if hc.tolerance:
            body += f"-{hc.tolerance}"
        body += "）"
    elif hc.tolerance:
        body += f"（{hc.tolerance}）"
    body += f"，深{hc.depth:g}" if hc.depth is not None else "，未注深度⇒通孔"
    if hc.kind != "hole":
        body += f"，{hc.kind}"
    return body
