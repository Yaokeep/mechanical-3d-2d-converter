# -*- coding: utf-8 -*-
"""文字/标注解析 —— 第 1 层"读符号通道"的核心。

## 为什么这个模块存在

CLAUDE.md 记着 bracket 剩余误差的抓手是"缺的是 B—B 圆心对齐的可靠基准
（俯视图圆组）"。而图纸的 TEXT 实体里明写着::

    'B—B  横剖 x=121.89（穿 r25.5 孔轴）'

**要找的信息一直在文件里。** 旧管线 `dxf_to_3d_general.py:618` 的正则
``^([A-Z])[-—–]\\1$`` 要求整串**恰好**是标签，带描述的标题落进 else 被整条
丢弃 —— 连 ``x=121.89`` 和 ``r25.5`` 一起。本模块按真实格式解析。

## 职责边界

只做**忠实抽取**：标签、剖切种类、参数名值对、半径/直径。
"r25.5 是哪个特征的、轴向朝哪"属于语义解释，是 views/conventions 层的事 ——
这里不猜，只把抽取结果带 tier 交给下游。
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum

from ..model.claim import Claim, Tier
from ..model.ids import EvidenceRef

# ---- 词表 ----

#: 视图标签 → ViewType.value。含常见别名（中英）。
#: ⚠ "SIDE"/"侧视图" 有意留作 "side"（左右未定）—— 由 views/view_typer.py
#: 依据**位置 + 投影制**消解，而不是在这里猜（ARCHITECTURE §3 原则二）。
VIEW_LABELS: dict[str, str] = {
    # 中文
    "主视图": "front", "正视图": "front", "前视图": "front",
    "俯视图": "top", "顶视图": "top", "平面图": "top",
    "仰视图": "bottom",
    "左视图": "left", "右视图": "right",
    "后视图": "rear",
    "侧视图": "side",
    "轴测图": "auxiliary", "斜视图": "auxiliary", "等轴测图": "auxiliary",
    "局部放大图": "detail",
    # 英文（本项目 CAD/test_simple/*.dxf 用的是这一套）
    "FRONT": "front", "FRONT VIEW": "front", "FRONTVIEW": "front",
    "TOP": "top", "TOP VIEW": "top", "PLAN": "top", "PLAN VIEW": "top",
    "BOTTOM": "bottom", "BOTTOM VIEW": "bottom",
    "LEFT": "left", "LEFT VIEW": "left", "LEFT SIDE VIEW": "left",
    "RIGHT": "right", "RIGHT VIEW": "right", "RIGHT SIDE VIEW": "right",
    "REAR": "rear", "REAR VIEW": "rear", "BACK VIEW": "rear",
    "SIDE": "side", "SIDE VIEW": "side",
    "ISO": "auxiliary", "ISO VIEW": "auxiliary", "ISOMETRIC": "auxiliary",
    "DETAIL": "detail", "DETAIL VIEW": "detail",
}


def _normalize_label(t: str) -> str:
    """标签归一化：大写、合并空白。中文不受影响。"""
    return " ".join(t.upper().split())


#: 投影制标志 → ProjectionMethod.value。
#: **判错会让整个零件镜像**（ARCHITECTURE §4.2），所以只认标题栏明写的符号，
#: 绝不靠"俯视图在上还是在下"反推（本仓库的出图脚本就是非标准布局，
#: 实测俯视图在主视图**上方**而左视图又放在主视图**右方**）。
PROJECTION_LABELS: dict[str, str] = {
    "第一角": "first_angle", "第一角画法": "first_angle", "第一角投影": "first_angle",
    "FIRST ANGLE": "first_angle", "FIRST-ANGLE": "first_angle",
    "第三角": "third_angle", "第三角画法": "third_angle", "第三角投影": "third_angle",
    "THIRD ANGLE": "third_angle", "THIRD-ANGLE": "third_angle",
}


def find_projection(text: str) -> str:
    """从文字里找投影制标志；找不到返回 ""。长标志优先（取最长匹配）。"""
    norm = _normalize_label(text)
    hit = ""
    for key in PROJECTION_LABELS:
        if key in norm and len(key) > len(hit):
            hit = key
    return PROJECTION_LABELS[hit] if hit else ""


#: 剖切种类关键词。长词在前 —— 匹配时按顺序试，避免"全剖"吃掉"纵向全剖"。
CUT_KINDS: tuple[str, ...] = (
    "纵向全剖", "横向全剖", "旋转剖", "阶梯剖", "复合剖", "斜剖",
    "半剖", "局部剖", "全剖", "横剖", "纵剖", "剖视", "剖面",
)

# ---- 正则 ----

#: AutoCAD 的 Unicode 转义 ``\U+XXXX``（4 位十六进制码点）—— 实测 YZYX
#: 孔标注的 ∅/× 全用这种写法；不解它 → 整串变 "U+220513" 的噪声
_UNICODE_ESCAPE_RE = re.compile(r"\\U\+([0-9A-Fa-f]{4})")

#: 剖面标签：B—B / A-A / C–C（破折号兼容 U+2014 / U+2013 / ASCII `-`）
#: 注意**不锚定结尾** —— 这正是旧管线丢掉信息的地方
_SECTION_LABEL_RE = re.compile(r"^\s*([A-Z])\s*[—–\-]\s*\1")

#: 向视图标题：「c 向」——**按箭头方向投射、位置自由的视图**（GB/T 4458.1
#: 的"向视图"），**不是**剖视图。YZYX 的「c 向」曾被读成剖面标题，Phase A
#: 证据推翻了它：该视图零剖面线（无 HATCH、无剖面线层 LINE）、带波浪断裂线、
#: 内容是 R30 弧 + 40/15/30 三个尺寸 —— 换成剖面读法只会产出三条"缺信息"
#: 阻塞疑问（剖切种类读不出/无剖面线/无切平面位置），全是伪的。
#: 「c 向剖视」这类**明写剖**的才仍按剖面标题解析（剖切种类留空，交
#: section.scope 几何推断）。锚定结尾：只认整串恰好是单字母+「向」的，
#: 防误吃「x 方向」这类描述文字
_DIRECTION_LABEL_RE = re.compile(r"^\s*([A-Za-z])\s*向\s*(?:剖视|剖面)?\s*$")

#: 名=值：x=121.89 / y=0.00 / z=-18.11
#: 左边界必需 —— 否则 "max=5" 里的 x 会被捕成 ("x", 5.0)
_KEY_VALUE_RE = re.compile(r"(?<![A-Za-z0-9])([A-Za-z])\s*=\s*(-?\d+(?:\.\d+)?)")

#: 直径符号 —— 四个来源都要认：
#:  - φ U+03C6 / Φ U+03A6 ：中文图纸常见写法（工程字 "%%c" 的 Unicode 对应）
#:  - ⌀ U+2300            ：直径符号
#:  - ∅ U+2205 / Ø U+00D8 ：AutoCAD 的 ``\U+2205`` 转义与 ``%%C`` 渲染出的字形
#:    （YZYX 实测：孔标注全部写成 ``8~\U+220513``，只认 φ/Φ/⌀ 时**整条读不出**）
_DIA_CHARS = "φΦ⌀∅Ø"

#: 直径：φ17 / Φ51 / ⌀10 / ∅13
_DIAMETER_RE = re.compile(rf"[{_DIA_CHARS}]\s*(\d+(?:\.\d+)?)")

#: 半径：r25.5 / R8（前后不得紧邻字母数字，避免误吃掉别的词）
_RADIUS_RE = re.compile(r"(?<![A-Za-z0-9])[Rr]\s*(\d+(?:\.\d+)?)(?![A-Za-z0-9])")

#: 数量×直径：4×φ10 / 6-φ8 / 8~∅13
#: 两条边界都是必需的：
#:  - 左边界：否则 "φ5.5×90°" 里 5.5 的第二个 5 会被当数量（n=5, φ=90）
#:  - φ 必需：否则零件名 "L-BRACKET 60x60x10" 会被读成"60 个 φ60 孔"
#: 分隔符含 `~`：YZYX 孔标注实测写作 ``8~∅13``（波浪线分隔，不是 ×）
_COUNT_DIA_RE = re.compile(
    rf"(?<![\d.])(\d+)\s*[×xX\-~]\s*[{_DIA_CHARS}]\s*(\d+(?:\.\d+)?)")

#: 角度：90° / 45°
_ANGLE_RE = re.compile(r"(-?\d+(?:\.\d+)?)\s*°")

#: 公差：±0.1 / +0.05/-0.02
_TOL_RE = re.compile(r"[±]\s*(\d+(?:\.\d+)?)")


class TextKind(StrEnum):
    VIEW_LABEL = "view_label"          # 主视图 / 俯视图 / …
    #: 向视图标题「c 向」（按箭头方向投射、位置自由）—— **不是剖视图**，
    #: 故不带 CutSpec；投射方向要从图上的箭头标记读（本层只记字母）
    DIRECTION_VIEW = "direction_view"
    SECTION_TITLE = "section_title"    # B—B 横剖 x=… （穿 r… 孔轴）
    SECTION_MARKER = "section_marker"  # 单个 "B—B"（剖切线两端的标记）
    PROJECTION = "projection"          # 第一角/第三角画法标志（标题栏）
    NOTE = "note"                      # 其它带数值的技术要求
    PLAIN = "plain"                    # 纯文字，无可抽取信息
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class CutSpec:
    """剖面标题的解析结果 —— **旧管线整条丢弃的那部分**。

    Attributes:
        cut_axis: 切平面的法向轴名（"x"/"y"/"z"）。"横剖 x=121.89" 意为
            切平面 x=121.89，其法向即 X 轴。
        cut_pos:  切平面位置。
        radius:   标题里提到的半径（``r25.5``）—— 这是定位该剖视图所描述的
            特征的关键线索，也是"可靠基准"的直接来源。
    """

    label: str
    kind: str = ""
    cut_axis: str = ""
    cut_pos: float | None = None
    radius: float | None = None
    diameter: float | None = None
    raw: str = ""

    @property
    def is_located(self) -> bool:
        """切平面位置是否已知 —— 未知则该剖视图不能用于裁材料。"""
        return self.cut_axis != "" and self.cut_pos is not None


@dataclass(frozen=True)
class ParsedText:
    """一条文字的解析结果。"""

    handle: EvidenceRef
    text: str
    x: float
    y: float
    layer: str = ""
    kind: TextKind = TextKind.UNKNOWN
    view_type: str = ""                      # VIEW_LABEL 时的 ViewType.value
    #: DIRECTION_VIEW 时的箭头字母（"C"）—— 与图上的箭头标记配对用
    direction_label: str = ""
    projection: str = ""                     # PROJECTION 时的 ProjectionMethod.value
    cut: CutSpec | None = None
    #: NOTE 时抽到的所有数值对：("φ", 17.0) / ("r", 8.0) / ("±", 0.1) / ("x", 121.89) …
    values: tuple[tuple[str, float], ...] = ()
    #: 未能解析的残料（供人工复核，不静默丢弃）
    leftover: str = ""

    @property
    def is_section(self) -> bool:
        return self.kind in (TextKind.SECTION_TITLE, TextKind.SECTION_MARKER)

    def as_claims(self) -> dict[str, Claim[float]]:
        """转成 Claim（tier=ANNOTATED —— 图上明标，最高档）。

        这样下游的多路推理里，"剖面标题写的切平面位置"会自动压过
        "从中心线推的位置"，正是 §4.1 的覆盖机制。
        """
        out: dict[str, Claim[float]] = {}
        if self.cut is not None:
            if self.cut.cut_pos is not None:
                out[f"cut_{self.cut.cut_axis}"] = Claim(
                    self.cut.cut_pos, "note:section_title",
                    Tier.ANNOTATED, evidence=(self.handle,),
                )
            if self.cut.radius is not None:
                out["r"] = Claim(
                    self.cut.radius, "note:section_title",
                    Tier.ANNOTATED, evidence=(self.handle,),
                )
            if self.cut.diameter is not None:
                out["d"] = Claim(
                    self.cut.diameter, "note:section_title",
                    Tier.ANNOTATED, evidence=(self.handle,),
                )
        for name, val in self.values:
            out.setdefault(name, Claim(
                val, "note:value", Tier.ANNOTATED, evidence=(self.handle,),
            ))
        return out


# ---- 解析 ----

def strip_mtext_codes(s: str) -> str:
    """去掉 MTEXT 的内联格式码 —— **先洗再解**。

    ezdxf 读出的 MTEXT 带原始内联码，实测本项目 20160112 图上
    每条标题栏文字都长这样：``\\T1.1;减速器Ⅰ轴`` / ``\\T1.1;F-F``。

    不洗的后果是**静默的**：剖面标题 ``\\T1.1;F-F`` 不匹配 ``^F-F$``，
    于是整条剖面信息丢掉（旧管线就是这么丢掉 `B—B 横剖 x=121.89` 的，
    见 CLAUDE.md 阶段 0 关键成果）。这里洗掉：

    - ``\\T<数字>;`` / ``\\A<数字>;`` / ``\\H<数字>;`` … 单字母+参数+分号
    - ``\\P`` 段落换行 → 空格
    - ``{\\... }`` 分组花括号
    - ``\\~`` 不换行空格 → 空格
    - ``\\U+XXXX`` → 该码点的字符（AutoCAD 的 Unicode 转义）。**必须在
      反斜杠清除之前解**，否则整串退化成 "U+220513" 这样的噪声文本 ——
      YZYX 的孔标注 ``8~\\U+220513`` 就因此一条都没读出来（∅ 是 U+2205）
    - ``%%d/%%p/%%c`` → °/±/φ（AutoCAD 老式转义，**大小写都认**：
      实测 YZYX 图纸一律写 ``%%C``/``%%D`` 大写，只认小写时 φ215 这类
      直径文字整条落进 PLAIN）
    """
    # %% 转义与 \U+XXXX 都不含花括号，先把这两种解掉（早退条件因此要给 "%%" 让路）
    if "\\" not in s and "{" not in s and "%%" not in s:
        return s
    s = _UNICODE_ESCAPE_RE.sub(lambda m: chr(int(m.group(1), 16)), s)
    s = re.sub(r"%%[cC]", "φ", s)
    s = re.sub(r"%%[dD]", "°", s)
    s = re.sub(r"%%[pP]", "±", s)
    if "\\" not in s and "{" not in s:
        return s.strip()
    # 字体规格码（\fFontName|b…|c…;）—— 名字可含 |, 比 \T1.1; 这类短码长得多，
    # 必须在短码正则**之前**洗：短码的 12 字符上限吃不下「\Fromans,gbcbig|c134;」
    # （YZYX 转换副本「c 向」标题实测即此形态，不洗掉它整条标题判成普通文字）
    out = re.sub(r"\\[Ff][^;\\{}]*;", "", s)
    out = re.sub(r"\\[A-Za-z][^;\\{}]{0,12};", "", out)   # \T1.1; \A2; …
    out = re.sub(r"\\P", " ", out)
    out = out.replace("\\~", " ")
    out = out.replace("\\", "")
    out = out.replace("{", "").replace("}", "")
    return out.strip()


def parse_text(
    text: str, handle: EvidenceRef, x: float, y: float, layer: str = ""
) -> ParsedText:
    """解析一条文字。**永不抛异常** —— 认不出就归 PLAIN/UNKNOWN 并留下残料。"""
    raw = text
    t = strip_mtext_codes((text or "").strip()).strip()
    if not t:
        return ParsedText(handle, raw, x, y, layer, TextKind.PLAIN)

    # 1) 视图标签（归一化后查表 —— 兼收中英、大小写、多空格）
    norm = _normalize_label(t)
    if norm in VIEW_LABELS:
        return ParsedText(handle, raw, x, y, layer,
                          TextKind.VIEW_LABEL, view_type=VIEW_LABELS[norm])

    # 2) 剖面标签（含带描述的标题）
    m = _SECTION_LABEL_RE.match(t)
    if m:
        label = m.group(1)
        rest = t[m.end():]
        # 没有描述、也没有数值 ⇒ 只是成对的短标记（剖切线两端各一个）
        if not rest.strip() or not _has_numbers(rest):
            return ParsedText(handle, raw, x, y, layer,
                              TextKind.SECTION_MARKER, leftover=rest.strip())
        cut = _parse_cut(label, rest, raw)
        return ParsedText(handle, raw, x, y, layer,
                          TextKind.SECTION_TITLE, cut=cut, leftover=cut.raw)

    # 2b) 「c 向」式标题 —— 「向」= 投射方向（向视图），**不是剖**：
    #     没有切平面、也没有剖面材料。只有明写「剖视/剖面」的才当剖面标题
    #     （剖切种类留空，由约定层 section.scope 从剖面线覆盖范围几何推断）
    m = _DIRECTION_LABEL_RE.match(t)
    if m:
        label = m.group(1).upper()
        if "剖" in t:
            cut = CutSpec(label=label, kind="", raw=t)
            return ParsedText(handle, raw, x, y, layer,
                              TextKind.SECTION_TITLE, cut=cut, leftover="")
        return ParsedText(handle, raw, x, y, layer,
                          TextKind.DIRECTION_VIEW, direction_label=label)

    # 3) 投影制标志（标题栏）—— 判错会让整个零件镜像，只认明写的符号
    proj = find_projection(t)
    if proj:
        return ParsedText(handle, raw, x, y, layer,
                          TextKind.PROJECTION, projection=proj)

    # 4) 其它带数值的文字 ⇒ NOTE
    values = _extract_values(t)
    if values:
        return ParsedText(handle, raw, x, y, layer, TextKind.NOTE, values=values)

    return ParsedText(handle, raw, x, y, layer, TextKind.PLAIN)


def _has_numbers(s: str) -> bool:
    return any(c.isdigit() for c in s)


def _parse_cut(label: str, rest: str, raw: str) -> CutSpec:
    """从剖面标题的描述部分抽取：剖切种类 + 切平面 + 半径/直径。"""
    kind = ""
    for k in CUT_KINDS:
        if k in rest:
            kind = k
            break

    kv = _extract_values(rest)
    by_name = dict(kv)

    # 切平面：优先取第一个轴向的 名=值（x/y/z）
    cut_axis, cut_pos = "", None
    for name in ("x", "y", "z"):
        if name in by_name:
            cut_axis, cut_pos = name, by_name[name]
            break

    radius = by_name.get("r")
    diameter = by_name.get("φ") or by_name.get("d")
    # 只给直径时补出半径，便于下游统一使用
    if radius is None and diameter is not None:
        radius = diameter / 2.0

    return CutSpec(label=label, kind=kind, cut_axis=cut_axis, cut_pos=cut_pos,
                   radius=radius, diameter=diameter, raw=rest.strip())


def _extract_values(s: str) -> tuple[tuple[str, float], ...]:
    """抽取一段文字里的全部数值对，按出现顺序返回。

    命名约定：名=值用其名（x/y/z/r…）；φ 记作 "φ"；单独的 R 记作 "r"；
    角度记作 "°"；公差记作 "±"；n×φd 记作 "φ"（取直径，数量另记 "n"）。
    """
    found: list[tuple[int, str, float]] = []   # (位置, 名, 值)

    for m in _COUNT_DIA_RE.finditer(s):
        found.append((m.start(), "n", float(m.group(1))))
        found.append((m.start(), "φ", float(m.group(2))))

    for m in _KEY_VALUE_RE.finditer(s):
        found.append((m.start(), m.group(1).lower(), float(m.group(2))))

    for m in _DIAMETER_RE.finditer(s):
        found.append((m.start(), "φ", float(m.group(1))))

    for m in _RADIUS_RE.finditer(s):
        found.append((m.start(), "r", float(m.group(1))))

    for m in _ANGLE_RE.finditer(s):
        found.append((m.start(), "°", float(m.group(1))))

    for m in _TOL_RE.finditer(s):
        found.append((m.start(), "±", float(m.group(1))))

    found.sort(key=lambda item: item[0])

    # 按 (名, 值) 全局去重：`4×φ10` 会被 _COUNT_DIA_RE 与 _DIAMETER_RE 双捕，
    # φ 会在不同位置各出现一次。值集合用于查表，去重无副作用。
    out: list[tuple[str, float]] = []
    seen: set[tuple[str, float]] = set()
    for _pos, name, val in found:
        key = (name, val)
        if key in seen:
            continue
        seen.add(key)
        out.append((name, val))
    return tuple(out)
