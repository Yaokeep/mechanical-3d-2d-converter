# -*- coding: utf-8 -*-
"""阶段 0 自检 —— 锁定 IR 不变式与文字解析行为。

    python -m src.rebuild.selftest

本项目三个环境都没装 pytest（CLAUDE.md 环境表），故按 `run_simple_regression.py`
的先例做成可直接运行的脚本，退出码 0 = 全过。

覆盖三类：
  A. Claim 不变式（第 4 层 gate 的地基，坏了不会报错只会静默给出错结论）
  B. 文字解析（含**误报防线** —— 误报比漏报危险，会污染下游尺寸表）
  C. 读取器在真实靶子上的图元计数（必须与 ezdxf 普查逐位相等）
"""
from __future__ import annotations

import json
import math
import re
import sys
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.rebuild.evidence.dxf_reader import (                            # noqa: E402
    classify_role,
    read_dxf,
)
from src.rebuild.evidence.model import Role, View, ViewType              # noqa: E402
from src.rebuild.evidence.text_parser import (                           # noqa: E402
    TextKind,
    find_projection,
    parse_text,
)
from src.rebuild.conventions import (                                    # noqa: E402
    BrokenView,
    ConvKind,
    Conventions,
    Pattern,
    RuleCtx,
    ThreadSpec,
    run_rules,
)
from src.rebuild.conventions import registry as REG                      # noqa: E402
from src.rebuild.conventions.section import _classify                    # noqa: E402
from src.rebuild.model import (                                          # noqa: E402
    Claim,
    OpenQuestion,
    QuestionList,
    Tier,
    merge,
)
from src.rebuild.model.feature_tree import (                             # noqa: E402
    ConstraintType,
    Feature,
    FeatureType,
    Part,
)
from src.rebuild.model.geom import Axis3, Point3, Vector3                # noqa: E402
from src.rebuild.model.geom2d import BBox2, profile_span                 # noqa: E402
from src.rebuild.model.ids import FeatureId                              # noqa: E402
from src.rebuild.features import (                                       # noqa: E402
    PARAMS,
    ir_coords,
    ir_point,
    merge_with_conflict,
    predict_in_view,
    profile_plane,
    recognize,
    snap_claim,
    snap_diameter,
    snap_radius,
)
from src.rebuild.views import (                                          # noqa: E402
    CorrKind,
    build_correspondence,
    detect_views,
    extract_ring,
    type_views,
)
from src.rebuild.views.view_detector import _cluster_1d, _xy_cut         # noqa: E402
from src.rebuild.views.view_typer import (                               # noqa: E402
    _extent_score,
    _partners,
    _pick_front_by_extent,
)
from src.rebuild.pipeline import rebuild, understand                     # noqa: E402

ROOT = Path(__file__).resolve().parents[2]

_passed = 0
_failed: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    global _passed
    if cond:
        _passed += 1
    else:
        _failed.append(f"{name}{('  — ' + detail) if detail else ''}")


def section(name: str) -> None:
    print(f"\n--- {name} ---")


# ============ A. Claim 不变式 ============

def test_claim() -> None:
    section("A. Claim 不变式")

    # 无证据不许高 tier
    try:
        Claim(1.0, "fake", Tier.ANNOTATED)
        check("无依据不许 ANNOTATED", False, "竟然构造成功")
    except ValueError:
        check("无依据不许 ANNOTATED", True)

    # PRIOR/GUESS 允许无证据
    c = Claim(8.0, "prior:series", Tier.PRIOR)
    check("PRIOR 允许无依据", c.tier == Tier.PRIOR)
    check("PRIOR 记为'我猜的'", c.is_guessed)

    # ANNOTATED 压过 PROJECTION
    hi = Claim(25.5, "note:section_title", Tier.ANNOTATED, evidence=("H1",))
    lo = Claim(25.0, "projection:circle", Tier.PROJECTION, evidence=("H2",))
    check("best() 取高 tier", Claim.best([lo, hi]) is hi)
    m = merge([lo, hi])
    check("merge 保留低 tier 为备选", 25.0 in m.alternatives)
    check("merge 后仍未定", not m.is_settled)

    # value 不应同时出现在备选里
    try:
        Claim(1.0, "x", Tier.GUESS, alternatives=(1.0,))
        check("value 不许重复进备选", False, "竟然构造成功")
    except ValueError:
        check("value 不许重复进备选", True)

    # is_trusted 的门槛
    check("CONVENTION 且已定 = 可信",
          Claim(1.0, "m", Tier.CONVENTION, evidence=("H",)).is_trusted)
    check("PROJECTION 不算可信",
          not Claim(1.0, "m", Tier.PROJECTION, evidence=("H",)).is_trusted)


# ============ B. 文字解析 ============

def test_text_parser() -> None:
    section("B. 文字解析")

    def p(t: str):
        return parse_text(t, "H1", 0.0, 0.0, "标注")

    # B1 真实剖面标题（旧管线正则整条丢弃的那三条）
    real = {
        "A—A  纵向全剖 y=0.00（中截面）": ("A", "y", 0.0, None),
        "B—B  横剖 x=121.89（穿 r25.5 孔轴）": ("B", "x", 121.89, 25.5),
        "C—C  横剖 x=-18.11（穿 r20.0 孔轴）": ("C", "x", -18.11, 20.0),
    }
    for text, (label, axis, pos, rad) in real.items():
        r = p(text)
        c = r.cut
        check(f"剖面标题 {label}: 归类",
              r.kind == TextKind.SECTION_TITLE, r.kind.value)
        check(f"剖面标题 {label}: 标签", c is not None and c.label == label)
        check(f"剖面标题 {label}: 切平面轴",
              c is not None and c.cut_axis == axis, getattr(c, "cut_axis", "?"))
        check(f"剖面标题 {label}: 切平面位置",
              c is not None and c.cut_pos == pos, str(getattr(c, "cut_pos", None)))
        check(f"剖面标题 {label}: 半径",
              c is not None and c.radius == rad, str(getattr(c, "radius", None)))
        check(f"剖面标题 {label}: 可定位",
              c is not None and c.is_located)

    # B2 剖面标题转 Claim 后是 ANNOTATED（应压过投影推出的位置）
    claims = p("B—B  横剖 x=121.89（穿 r25.5 孔轴）").as_claims()
    check("剖面标题 → Claim 为 ANNOTATED",
          claims["cut_x"].tier == Tier.ANNOTATED)
    check("剖面标题 → r 值带出", claims["r"].value == 25.5)

    # B3 孤立短标记不是标题
    check("孤立 B—B = marker", p("B—B").kind == TextKind.SECTION_MARKER)

    # B4 视图标签（中英，含 SIDE 的左右未定）
    labels = {
        "主视图": "front", "俯视图": "top", "左视图": "left",
        "FRONT VIEW": "front", "TOP VIEW": "top", "SIDE VIEW": "side",
        "  right side view ": "right",
    }
    for text, want in labels.items():
        r = p(text)
        check(f"视图标签 {text!r}",
              r.kind == TextKind.VIEW_LABEL and r.view_type == want,
              f"{r.kind.value}/{r.view_type}")

    # B5 误报防线 —— 误报比漏报危险（会污染下游尺寸表）
    r = p("L-BRACKET 60x60x10")
    check("零件名 60x60x10 不得读成孔组",
          not any(n == "n" for n, _ in r.values), str(r.values))
    r = p("沉头 φ5.5×90° 深 3")
    check("沉头 φ5.5×90° 不产生 n",
          not any(n == "n" for n, _ in r.values), str(r.values))
    check("沉头 φ5.5×90° 抽到 φ5.5",
          ("φ", 5.5) in r.values, str(r.values))
    check("沉头 φ5.5×90° 抽到 90°",
          ("°", 90.0) in r.values, str(r.values))
    r = p("max=5")
    check("max=5 不得读成 x=5",
          not any(n == "x" for n, _ in r.values), str(r.values))

    # B6 正常孔组仍要读出来
    r = p("4×φ10 均布")
    check("4×φ10 均布 → n=4", ("n", 4.0) in r.values, str(r.values))
    check("4×φ10 均布 → φ=10", ("φ", 10.0) in r.values, str(r.values))
    r = p("未注圆角 R2")
    check("未注圆角 R2 → r=2", ("r", 2.0) in r.values, str(r.values))

    # B7 空/无数字不炸
    check("空文字不炸", p("").kind == TextKind.PLAIN)
    check("无数字文字", p("技术要求").kind == TextKind.PLAIN)

    # B8 「c 向」= **向视图**标题（YZYX 实测形态：MTEXT 带字体规格码）。
    #    v0.6.29 更正：它曾被读成剖面标题，Phase A 证据推翻了这一读法 ——
    #    该视图零剖面线、带波浪断裂线、内容是 R30 弧 + 40/15/30 尺寸，
    #    剖面读法只会产出三条"缺信息"的伪阻塞疑问
    r = p("c   {\\Fromans,gbcbig|c134;向}")
    check("带字体码的「c 向」洗成向视图标题",
          r.kind == TextKind.DIRECTION_VIEW and r.direction_label == "C"
          and r.cut is None, str(r))
    check("纯文本「c 向」同样是向视图标题",
          p("c 向").kind == TextKind.DIRECTION_VIEW)
    check("「c 向」不得产出 CutSpec（没有切平面、没有剖面材料）",
          p("c 向").cut is None)
    check("明写「剖」的「c 向剖视」仍按剖面标题解析（种类留空 ⇒ 几何推断入口）",
          p("c 向剖视").kind == TextKind.SECTION_TITLE
          and p("c 向剖视").cut is not None
          and not p("c 向剖视").cut.kind)
    check("「x 方向」两个都不是（锚定结尾，防误吃描述文字）",
          p("x 方向").kind not in (TextKind.SECTION_TITLE,
                                   TextKind.DIRECTION_VIEW))
    check("「按 C 向视图旋转」也不是（不锚定整串）",
          p("按 C 向视图旋转").kind not in (TextKind.SECTION_TITLE,
                                           TextKind.DIRECTION_VIEW))

    # B9 AutoCAD 转义：\U+XXXX 码点 + %%C/%%D/%%P（大小写都认）。
    #    实测 YZYX 孔标注写作 ``8~\U+220513``、直径文字写 ``%%C215`` ——
    #    两者此前都被洗成噪声文本 ⇒ 整条标注读不出（Phase D 的前提修复）
    r = p("8~\\U+220513")
    check("\\U+2205 解成 ∅ 且「8~∅13」读出 n=8、φ=13",
          ("n", 8.0) in r.values and ("φ", 13.0) in r.values, str(r.values))
    # 注意 ParsedText.text 存的是**原始串**（忠实抽取契约），洗净结果体现在
    # values/kind 上 —— 所以这里断言抽出的数值而非文本
    r = p("1{\\fSimSun|b0|i0|c0|p2;\\U+00D7}45%%D")
    check("\\U+00D7 解成 ×、45%%D 解成 °（1×45° 读得出角度）",
          r.kind == TextKind.NOTE and ("°", 45.0) in r.values
          and ("n", 1.0) not in r.values, str(r.values))
    r = p("\\pt32;1.5{\\fSimSun|b0|i0|c134|p2;×}45%%D")
    check("大写 %%D 解成 °（1.5×45°）",
          ("°", 45.0) in r.values and ("n", 1.0) not in r.values, str(r.values))
    r = p("%%C215")
    check("大写 %%C 解成 φ（φ215 不再落进 PLAIN）",
          ("φ", 215.0) in r.values and r.kind == TextKind.NOTE, str(r))
    check("小写 %%c/%%d/%%p 仍照旧",
          ("φ", 8.0) in p("4%%c8").values
          and ("°", 90.0) in p("90%%d").values
          and ("±", 0.1) in p("±0.1").values)
    r = p("4~\\U+220510-7H\\P{\\Fromans,gbcbig|c134;深25}")
    check("「4~∅10-7H 深25」读出 n=4、φ=10，且保留 7H/深25 原文",
          ("n", 4.0) in r.values and ("φ", 10.0) in r.values
          and "7H" in r.text and "深25" in r.text, str(r.text))
    check("「\\U+220516锥孔」单独一条也读出 φ16（无数量）",
          ("φ", 16.0) in p("\\U+220516{\\Fromans,gbcbig|c134;锥孔，与\\P齿箱壳配作}").values)


# ============ C. 读取器在真实靶子上 ============

def test_reader() -> None:
    section("C. 读取器 / 真实靶子")
    tmp = ROOT / "CAD" / "temp_output"
    simple = ROOT / "CAD" / "test_simple"

    targets = [
        (tmp / "bracket_angker_三视图_v4.dxf", 4388, 0, 0),
        (tmp / "bracket_angker_图纸_20260922_剖面图.dxf", 6605, 12, 3),
    ]
    for path, n_ev, n_txt, n_cut in targets:
        if not path.exists():
            check(f"{path.name} 存在", False, "靶子缺失")
            continue
        d = read_dxf(path)
        check(f"{path.name} 图元数", len(d.evidence) == n_ev,
              f"{len(d.evidence)} != {n_ev}")
        check(f"{path.name} 文字数", len(d.texts) == n_txt,
              f"{len(d.texts)} != {n_txt}")
        n = sum(1 for t in d.texts if t.cut is not None)
        check(f"{path.name} 剖面标题数", n == n_cut, f"{n} != {n_cut}")

    # 简单用例：只验不炸 + 英文标签被识别
    for f in ("block_3view", "flange_d80", "l_bracket", "plate_100x60"):
        path = simple / f"{f}.dxf"
        if not path.exists():
            continue
        d = read_dxf(path)
        check(f"{f} 读到图元", len(d.evidence) > 0)
    d = read_dxf(simple / "block_3view.dxf")
    kinds = {t.view_type for t in d.texts if t.view_type}
    check("block_3view 英文视图标签被识别",
          {"front", "top"} <= kinds, str(kinds))

    # 剖面标题的切平面必须来自图上文字（不是猜的）
    d = read_dxf(tmp / "bracket_angker_图纸_20260922_剖面图.dxf")
    titles = {t.cut.label: t.cut for t in d.texts if t.cut is not None}
    check("B—B 切平面 = x=121.89",
          titles["B"].cut_axis == "x" and titles["B"].cut_pos == 121.89)
    check("B—B 半径 = 25.5", titles["B"].radius == 25.5)

    # ---- C8 角色 → 种类：修复前 _kind_of 是死代码，中心线带 kind=edge 进包围盒 ----
    deg = read_dxf(simple / "block_3view.dxf")
    check("block_3view 中心线 6 条以 kind=AXIS 入账", len(deg.axes()) == 6,
          str(len(deg.axes())))
    check("中心线不再混作 EDGE（角色 AXIS ⇒ 种类 AXIS）",
          all(e.kind.value == "axis" for e in deg.evidence
              if e.role.value.value == "axis"),
          str([(e.handle, e.kind.value) for e in deg.evidence
               if e.role.value.value == "axis"][:4]))
    d12 = read_dxf(ROOT / "CAD" / "20160112-181116-09933.dxf")
    check("20160112 中心线层 13 条 ⇒ 13 条 AXIS", len(d12.axes()) == 13,
          str(len(d12.axes())))
    check("20160112 轴线全在中心线层",
          {e.layer for e in d12.evidence if e.kind.value == "axis"}
          == {"中心线层"})

    # ---- C9 未展开的块引用如实入账（不许静默丢弃） ----
    blocks = [e for e in d12.evidence if e.kind.value == "block"]
    check("20160112 的 24 个块引用全部入账", len(blocks) == 24, str(len(blocks)))
    check("块引用标明「未展开」",
          all(e.role.method == "unexpanded:insert" for e in blocks),
          str({e.role.method for e in blocks}))

    # ---- C10 MTEXT 内联码**先洗后解**：不洗则标题整条丢掉（旧管线的病根） ----
    fmark = [t for t in d12.texts if t.text.endswith("F-F")]
    check("20160112 的 `\\T1.1;F-F` 被解成剖面标记",
          bool(fmark) and all(t.kind == TextKind.SECTION_MARKER for t in fmark),
          str([(t.handle, t.text, t.kind.value) for t in fmark]))

    # ---- C11 尺寸线层上的几何不当作轮廓 ----
    dim_role = classify_role("尺寸线层", "", "TEST")
    check("尺寸线层 ⇒ Role.UNKNOWN（不参与轮廓）",
          dim_role.value.value == "unknown"
          and dim_role.method == "convention:dim_layer",
          f"{dim_role.value.value} / {dim_role.method}")

    # ---- C12 细实线 / ISO 虚线 / 剖面线画成 LINE 的角色判定（YZYX 实测画法） ----
    check("细实线层 ⇒ THIN（被盖轮廓，不是开口）",
          classify_role("细实线", "", "TEST").value.value == "thin",
          str(classify_role("细实线", "", "TEST").value))
    check("AM_ISO02W050 线型 ⇒ HIDDEN（ISO 虚线覆盖）",
          classify_role("粗实线", "AM_ISO02W050", "TEST").value.value == "hidden")
    check("细实线层 + 虚线 ⇒ HIDDEN（被盖语义优先于细线语义）",
          classify_role("细实线", "AM_ISO02W050", "TEST").value.value == "hidden")
    check("剖面线层 LINE ⇒ HATCH_LINES（旧式画法填充）",
          classify_role("剖面线", "", "TEST").value.value == "hatch_lines")


# ============ D. 视图分离与定性 ============

def test_views() -> None:
    section("D. 视图分离与定性")
    tmp = ROOT / "CAD" / "temp_output"
    simple = ROOT / "CAD" / "test_simple"

    # D0 投影制标志识别（判错会让整件镜像，故只认明写的符号）
    check("第三角画法 → third_angle",
          find_projection("第三角画法") == "third_angle")
    check("THIRD ANGLE PROJECTION → third_angle",
          find_projection("THIRD ANGLE PROJECTION") == "third_angle")
    check("无标志 → 空", find_projection("技术要求") == "")
    check("'第一角' 字样被认到", find_projection("按第一角绘制") == "first_angle")
    r = parse_text("第三角画法", "H9", 0.0, 0.0, "")
    check("投影制文字归一为 PROJECTION",
          r.kind == TextKind.PROJECTION and r.projection == "third_angle",
          f"{r.kind.value}/{r.projection}")

    # D1 无标签三视图：布局规则必须推出与带标签图纸一致的主/俯/左
    d = read_dxf(tmp / "bracket_angker_三视图_v4.dxf")
    detect_views(d)
    qs = type_views(d)
    got = {v.id: v.resolved_type for v in d.views}
    check("三视图 v4 分离出 3 个视图", len(d.views) == 3, str(len(d.views)))
    check("三视图 v4 主视图定在 V1", got.get("V1") == ViewType.FRONT,
          str(got.get("V1")))
    check("三视图 v4 V0 判为俯视图", got.get("V0") == ViewType.TOP,
          str(got.get("V0")))
    check("三视图 v4 V2 判为左视图", got.get("V2") == ViewType.LEFT,
          str(got.get("V2")))
    v0 = next(v for v in d.views if v.id == "V0")
    check("俯/仰歧义必须进备选（不许静默当俯视图）",
          ViewType.BOTTOM in v0.type.alternatives, str(v0.type.alternatives))
    check("俯/仰歧义 ⇒ 未定",
          not v0.type.is_settled)
    check("无标签图纸必须报投影制未确定",
          any(q.kind == OpenQuestion.UNKNOWN_PROJECTION for q in qs))

    # D2 视图归属只有一个真相来源：全部图元都能反查到视图
    assigned = set()
    for v in d.views:
        assigned |= set(v.all_handles())
    unassigned = [e.handle for e in d.evidence if e.handle not in assigned]
    check("三视图 v4 图元全部归属视图", not unassigned,
          f"{len(unassigned)} 项未归属")
    ev0 = next(e for e in d.evidence if e.kind.value == "edge")
    v = d.view_of(ev0.handle)
    check("Drawing.view_of 能反查", v is not None)
    check("view_of 与 View.evidence 一致",
          v is not None and ev0.handle in v.evidence)

    # D3 带中文标签的剖面图纸：标签是 ANNOTATED，剖面切平面来自文字
    d2 = read_dxf(tmp / "bracket_angker_图纸_20260922_剖面图.dxf")
    detect_views(d2)
    type_views(d2)
    kinds = {v.resolved_type for v in d2.views}
    check("剖面图纸 6 个视图", len(d2.views) == 6, str(len(d2.views)))
    check("主/俯/左/剖 全部定性",
          {ViewType.FRONT, ViewType.TOP, ViewType.LEFT,
           ViewType.SECTION} <= kinds, str(kinds))
    by_type = {v.resolved_type: v for v in d2.views}
    for label, want in (("主视图", ViewType.FRONT), ("俯视图", ViewType.TOP),
                        ("左视图", ViewType.LEFT)):
        v = by_type[want]
        check(f"{label} 由标签定性且 tier=ANNOTATED",
              v.type.tier == Tier.ANNOTATED and v.type.is_settled,
              f"{v.type}")
    secs = [v for v in d2.views if v.resolved_type == ViewType.SECTION]
    cut_pos = {v.cut.label: v.cut.cut_pos for v in secs}
    check("三个剖视图都带切平面位置",
          cut_pos == {"A": 0.0, "B": 121.89, "C": -18.11}, str(cut_pos))
    check("剖视图定性依据是剖面标题（不是猜）",
          all(v.type.method == "note:section_title" for v in secs))

    # D4 英文标签 + 只写 SIDE VIEW 的侧视图（左右未定但要有值可用）
    d3 = read_dxf(simple / "block_3view.dxf")
    detect_views(d3)
    qs3 = type_views(d3)
    got3 = {v.label_handle: v.resolved_type for v in d3.views}
    types3 = {v.resolved_type for v in d3.views}
    check("block_3view 三个视图全定性", None not in got3.values(), str(got3))
    check("block_3view 得到 主/俯/侧",
          {ViewType.FRONT, ViewType.TOP} <= types3, str(types3))
    side = next(v for v in d3.views if v.label_handle is not None
                and d3.text_by_handle(v.label_handle).view_type == "side")
    check("只写 SIDE VIEW ⇒ 给出可用值但保留备选",
          side.resolved_type in (ViewType.LEFT, ViewType.RIGHT)
          and not side.type.is_settled,
          str(side.type))
    check("SIDE VIEW 的左右歧义有对应待确认项",
          any(q.view == side.id for q in qs3 if q.candidates),
          str([str(q) for q in qs3]))

    # D5 三视图 v4 无文字 ⇒ 标注数必须为 0（不能凭空造出标签来定性）
    check("三视图 v4 无任何标注",
          all(len(v.annotations) == 0 for v in d.views))

    # ---- D6 递归 XY 切分：同列上下堆叠的视图必须切开（YZYX 布局，2026-10-12）----
    # 两段式（先切行、再在行内切列）在"同列上下堆叠、且邻列视图的 y 跨度盖住
    # 这两视图之间的空隙"上结构性失效：YZYX 的「c 向」与下方大拱视图空着 110.7mm
    # （阈值才 34.9）仍被并进同一行，行内按 X 切时两者 x 完全重合 ⇒ 永远切不开。
    # 递归切分在每个子块上重新问"还有没有 y 向空隙"，故 5 个视图逐层切出。
    # 窗口尺寸取自 _yz.dxf 实测（_yz.dxf 已 gitignore，故此处用同形合成盒）。
    yz_boxes = [
        BBox2(3265.4, 1541.2, 3660.4, 1728.7),   # 0 右上 C—C 复合投影
        BBox2(2478.3, 1541.2, 2823.3, 1728.7),   # 1 左上 A—A 全剖
        BBox2(3337.4, 1194.3, 3561.5, 1315.3),   # 2 「c 向」局部视图
        BBox2(2478.3,  857.3, 2823.3, 1252.3),   # 3 俯视
        BBox2(3265.4,  896.1, 3660.4, 1083.6),   # 4 右下大拱视图
    ]
    groups = _xy_cut(list(range(len(yz_boxes))), yz_boxes, 47.29, 34.86)
    check("递归 XY 切分：YZYX 布局切出 5 簇", len(groups) == 5, str(groups))
    g_of = {i: k for k, g in enumerate(groups) for i in g}
    check("递归 XY 切分：「c 向」与下方大拱不在同一簇（两段式在此失效）",
          g_of.get(2) != g_of.get(4), str(groups))
    # 对照：两段式的第一步（全局按 Y 切行）就会把 2 与 4 并进同一行 —— 这是失效点
    rows_old = _cluster_1d([(b.ymin, b.ymax) for b in yz_boxes], 34.86)
    check("对照：两段式第一步把「c 向」与下方大拱并进同一行",
          any(2 in r and 4 in r for r in rows_old), str(rows_old))

    # ---- D7 三等定律裁决主视图（YZYX 布局，2026-10-12）----
    # 判据"恰好一个视图同时有行、列伙伴"只对三视图 L 型布局成立；YZYX 两列多行
    # 5 视图 ⇒ 五个全是"有行有列" ⇒ 旧判据失效 ⇒ 全表 UNKNOWN、特征树 0 条。
    # 补充依据取自投影本身：真锚点的**每个**对齐伙伴都在共享轴上与它等长。
    yz_views = [View(id=f"V{i}", bbox=b) for i, b in enumerate(yz_boxes)]
    cols, rows = _partners(yz_views)
    scores = {v.id: _extent_score(v, cols, rows) for v in yz_views}
    check("三等定律打分：V1 = +2 且唯一最大",
          scores == {"V0": 1, "V1": 2, "V2": -3, "V3": -1, "V4": -1}, str(scores))
    check("三等定律裁决主视图 = V1（与手工读图一致）",
          _pick_front_by_extent(yz_views, cols, rows) is yz_views[1])
    # 负例：最高分并列（正方形零件的视图全同尺寸）不许硬猜
    square = [View(id="A", bbox=BBox2(0, 0, 100, 100)),
              View(id="B", bbox=BBox2(0, 200, 100, 300))]
    cols2, rows2 = _partners(square)
    check("三等定律最高分并列 ⇒ 返回 None（不硬猜）",
          _pick_front_by_extent(square, cols2, rows2) is None)


# ============ E. 验证层 ============

def _spans(triple: tuple[float, float, float], tier: Tier = Tier.PROJECTION
           ) -> dict:
    """造一个齐备的 Expected.spans（三轴各一个已定的 Claim）。"""
    return {
        a: Claim(triple[i], f"test:{a}", tier, evidence=("E1",))
        for i, a in enumerate(("x", "y", "z"))
    }


def test_verify() -> None:
    section("E. 验证层（图纸判模型）")
    from src.rebuild.verify import (
        RATIO_TOL,
        Comparison,
        Expected,
        Verdict,
        compare,
        coverage,
        decide,
        expect_from_drawing,
    )
    from src.rebuild.verify.compare import _combine
    tmp = ROOT / "CAD" / "temp_output"

    # E0 _combine 的返回契约 —— 一致时报"说明"、冲突时才报 Question。
    #    两者都是字符串，混淆过一次（agree 路径返回裸 str 塞进 Question 位）
    #    会让全部 verify 崩在 QuestionList.add 上，故把形状锁住。
    a = Claim(203.300, "view:V0.u", Tier.PROJECTION, evidence=("EA",))
    b = Claim(203.301, "view:V1.u", Tier.PROJECTION, evidence=("EB",))
    merged, note, q = _combine([a, b], "x")
    check("_combine 一致 ⇒ 无 Question", q is None, repr(q))
    check("_combine 一致 ⇒ 有说明且为 str", isinstance(note, str) and bool(note),
          repr(note))
    check("_combine 一致 ⇒ 取均值且算已定",
          abs(merged.value - 203.3005) < 1e-6 and merged.is_settled,
          f"{merged.value} settled={merged.is_settled}")
    merged2, note2, q2 = _combine(
        [Claim(51.0, "view:V2.v", Tier.PROJECTION, evidence=("EC",)),
         Claim(67.0, "view:V0.v", Tier.PROJECTION, evidence=("ED",))], "y")
    check("_combine 冲突 ⇒ 报 Question", q2 is not None and isinstance(note2, str))
    # merge 的语义：值取其中一个（可用的那个），另一个进备选 —— 备选里装的是
    # **落选者**，不是全部候选，故 51.0 与 67.0 二者恰有一个在 alternatives 里
    check("_combine 冲突 ⇒ 值仍可用但保留备选",
          not merged2.is_settled and merged2.value in (51.0, 67.0)
          and (merged2.alternatives == (67.0,) if merged2.value == 51.0
               else merged2.alternatives == (51.0,)),
          f"{merged2.value} / {merged2.alternatives}")

    # E1 三视图 v4：期望三向尺寸＝图纸包围盒（本项是阶段 0 的尺子本身）
    d = read_dxf(tmp / "bracket_angker_三视图_v4.dxf")
    detect_views(d)
    type_views(d)
    ex = expect_from_drawing(d)
    check("三视图 v4 给全三向尺寸", not ex.missing, str(ex.missing))
    t = ex.triple() or (0, 0, 0)
    check("三视图 v4 期望 X≈203.30", abs(t[0] - 203.30) < 0.05, f"{t[0]:.3f}")
    check("三视图 v4 期望 Y=51.00", abs(t[1] - 51.0) < 0.05, f"{t[1]:.3f}")
    check("三视图 v4 期望 Z=44.00", abs(t[2] - 44.0) < 0.05, f"{t[2]:.3f}")
    check("期望尺寸 tier=PROJECTION（不是猜的）",
          all(c.tier == Tier.PROJECTION for c in ex.spans.values()),
          str({a: c.tier.name for a, c in ex.spans.items()}))
    check("每路观测都带依据（无依据不入 Claim）",
          all(c.evidence for c in ex.spans.values()))
    check("三视图 v4 两路来源一致（不报视图歧义）",
          not ex.questions.by_kind(OpenQuestion.AMBIGUOUS_VIEW),
          str([str(q) for q in ex.questions]))

    # E2 剖面图纸：剖切线画在视图外且两端伸出，若混入包围盒会把 Y 从 51 撑到 67。
    #    这条是回归锚 —— 视图分离里"排除 Role.SECTION_CUT"那条规则的守卫。
    d2 = read_dxf(tmp / "bracket_angker_图纸_20260922_剖面图.dxf")
    detect_views(d2)
    type_views(d2)
    ex2 = expect_from_drawing(d2)
    t2 = ex2.triple() or (0, 0, 0)
    check("剖面图纸期望 Y=51.00（剖切线未撑大包围盒）",
          abs(t2[1] - 51.0) < 0.05, f"{t2[1]:.3f}")
    sec_ids = {v.id for v in d2.views
               if v.resolved_type == ViewType.SECTION}
    check("剖视图不参与期望尺寸（只画剖到的一块）",
          sec_ids.isdisjoint({vid for vid, _, _ in ex2.observations}),
          str(sorted(sec_ids)))

    # E3 判决的四种走向（纯合成，不读文件）
    good = (204.289, 51.0, 44.0)
    g_ok = decide(compare(Expected(spans=_spans((203.30, 51.0, 44.0))), good),
                  Expected(spans=_spans((203.30, 51.0, 44.0))))
    check("尺寸齐 + 比例符 ⇒ ACCEPT", g_ok.verdict == Verdict.ACCEPT,
          g_ok.verdict.value)

    ex_rej = Expected(spans=_spans((203.30, 51.0, 44.0)))
    g_rej = decide(compare(ex_rej, (204.3, 1.92, 44.0)), ex_rej)
    check("单轴被拉伸 ⇒ REJECT", g_rej.verdict == Verdict.REJECT,
          f"{g_rej.verdict.value} {g_rej.reasons}")
    check("REJECT 的理由点名了那条轴",
          any("Y" in r for r in g_rej.reasons), str(g_rej.reasons))

    ex_conf = Expected(spans=_spans((203.30, 51.0, 44.0)))
    ex_conf.spans["y"] = merge([
        Claim(51.0, "view:V2.v", Tier.PROJECTION, evidence=("E1",)),
        Claim(67.0, "view:V0.v", Tier.PROJECTION, evidence=("E2",)),
    ])
    g_conf = decide(compare(ex_conf, good), ex_conf)
    check("图纸两路来源冲突 ⇒ NEEDS_CONFIRMATION（不是 ACCEPT）",
          g_conf.verdict == Verdict.NEEDS_CONFIRMATION, g_conf.verdict.value)

    ex_none = Expected()
    g_err = decide(compare(ex_none, None), ex_none, measured_ok=False,
                   measure_error="STEP 读不了")
    check("模型量不到 ⇒ ERROR（不是通过）",
          g_err.verdict == Verdict.ERROR, g_err.verdict.value)

    # E4 主判据必须尺度无关：整体缩比照样 ACCEPT，单轴拉伸必须毙
    ex_s = Expected(spans=_spans((203.30, 51.0, 44.0)))
    c_scale = compare(ex_s, (203.30 * 2, 51.0 * 2, 44.0 * 2))
    check("图纸与模型差 2 倍缩比 ⇒ 比例仍通过", c_scale.ratio_ok,
          str(c_scale.failing_axes))
    check("缩比时隐含比例尺一致", c_scale.scale_uniform
          and all(abs(v - 2.0) < 1e-9 for v in c_scale.implied_scale.values()),
          str(c_scale.implied_scale))
    c_stretch = compare(ex_s, (203.30, 51.0 * 1.2, 44.0))
    check("单轴 +20% 拉伸 ⇒ 落在容差外", c_stretch.failing_axes == ["y"],
          str(c_stretch.failing_axes))
    check("比例容差是 5%", abs(RATIO_TOL - 0.05) < 1e-12, str(RATIO_TOL))

    # E5 读取覆盖率：两张靶子都必须 100% 归位（掉下去就是丢东西了）
    for name, dd in (("三视图 v4", d), ("剖面图纸", d2)):
        cov = coverage(dd)
        check(f"{name} 图元 100% 归位", cov.evidence_ratio == 1.0
              and not cov.orphans, cov.summary())
        check(f"{name} 文字 100% 分类", cov.text_ratio == 1.0,
              str(cov.unparsed))
        check(f"{name} 角色依据分布非空", bool(cov.tier_hist),
              str(cov.tier_hist))

    # E6 依赖分层：verify 的 __init__ 不许把 OCC 拉进来
    #    （默认 python 没有 OCC，本文件能在默认 python 下跑完即证明了这一点）
    check("verify 包不拉入 step_probe", "src.rebuild.verify.step_probe"
          not in sys.modules, "被 __init__ 导出了")
    check("verify 包不拉入 OCC", not [m for m in sys.modules
                                     if m.split(".")[0] == "OCC"],
          str([m for m in sys.modules if m.split(".")[0] == "OCC"][:3]))
    check("Comparison 可独立构造（报告层可用）",
          Comparison(None, None).ratio_ok)

    # E7 **该拒绝时必须拒绝**：单视图、零尺寸标注的极简靶子，第三向尺寸
    #    根本不在图上（plate 的图面 4 线 2 圆，文字还写着与实况不符的 100x60x10）
    #    ⇒ 必须 NEEDS_CONFIRMATION，不许"照常输出"。老管线在这几个靶子上
    #    之所以"对"，是因为靶子是人按已知答案画的，不是它读出来的。
    single = read_dxf(ROOT / "CAD" / "test_simple" / "plate_100x60.dxf")
    detect_views(single)
    type_views(single)
    ex_single = expect_from_drawing(single)
    check("单视图靶子：三向尺寸给不全",
          set(ex_single.missing) == {"x", "y", "z"}, str(ex_single.spans))
    g_single = decide(compare(ex_single, (100.0, 60.0, 20.0)), ex_single)
    check("单视图靶子 ⇒ NEEDS_CONFIRMATION（不猜厚度）",
          g_single.verdict == Verdict.NEEDS_CONFIRMATION,
          g_single.verdict.value)
    check("拒判的理由点名缺视图",
          any("缺" in r for r in g_single.reasons), str(g_single.reasons))


# ============ F. 跨视图对应（阶段 1） ============

#: 6 个回归靶子 —— 阶段 1 验收要求"中心线共线匹配在 6 个回归用例上无误配"
_CASES = (
    ROOT / "CAD" / "temp_output" / "bracket_angker_图纸_20260922_剖面图.dxf",
    ROOT / "CAD" / "temp_output" / "bracket_angker_三视图_v4.dxf",
    ROOT / "CAD" / "20160112-181116-09933.dxf",
    ROOT / "CAD" / "test_simple" / "block_3view.dxf",
    ROOT / "CAD" / "test_simple" / "plate_100x60.dxf",
    ROOT / "CAD" / "temp_output" / "spoon_三视图.dxf",
)


def _windows(frames: dict) -> dict[str, tuple[float, float]]:
    """各模型轴上、全部视图共同给出的坐标窗口。"""
    out: dict[str, tuple[float, float]] = {}
    for f in frames.values():
        for a in "xyz":
            s = f.model_span(a)
            if s is None:
                continue
            lo, hi = out.get(a, (s[0], s[1]))
            out[a] = (min(lo, s[0]), max(hi, s[1]))
    return out


def test_correspondence() -> None:
    section("F. 跨视图对应（阶段 1）")

    # F1 阶段 1 验收①：bracket 剖面图纸的两条剖面轴 —— 与标题文字
    #    （B—B x=121.89 穿 r25.5 / C—C x=-18.11 穿 r20）**逐项对上**。
    #    切平面位置由几何圆配准得出：标题坐标 + 恒定平移 +40.11 = 模型坐标，
    #    两条剖面各自独立算出同一平移（曾互斥、报 INCONSISTENT_FRAME，见 F2）。
    sec = read_dxf(ROOT / "CAD" / "temp_output"
                   / "bracket_angker_图纸_20260922_剖面图.dxf")
    detect_views(sec)
    type_views(sec)
    res = build_correspondence(sec)
    # 键取**来源视图**（V4/V5），不取剖面标签 —— 标签是单个字母（B/C），
    # 一张图上两个剖面可能同名不同位，用视图 id 才是唯一的
    axes = {c.refs[0][0]: c.mapping.value
            for c in res.by_kind(CorrKind.AXIS)
            if isinstance(c.mapping.value, Axis3)}
    check("剖面轴读数 2 条（V4 / V5）", set(axes) == {"V4", "V5"},
          str(sorted(axes)))

    b = axes.get("V4")
    if b is not None:
        check("B—B 轴沿 Z", b.direction.z == 1.0 and b.direction.x == 0.0,
              str(b.direction))
        check("B—B 半径 = 标题的 25.5",
              abs(b.radius.value - 25.5) < 1e-9, str(b.radius.value))
        check("B—B 切平面 x = 162.00（121.89 + 平移 40.11）",
              abs(b.origin.x - 162.0) < 0.01, f"{b.origin.x:.4f}")
        check("B—B 孔心 y = 148.05", abs(b.origin.y - 148.0547) < 0.01,
              f"{b.origin.y:.4f}")
    c = axes.get("V5")
    if c is not None:
        check("C—C 轴沿 Z", c.direction.z == 1.0, str(c.direction))
        check("C—C 半径 = 标题的 20", abs(c.radius.value - 20.0) < 1e-9,
              str(c.radius.value))
        check("C—C 切平面 x = 22.00（-18.11 经同一平移 40.11）",
              abs(c.origin.x - 22.0) < 0.01, f"{c.origin.x:.4f}")

    # F2 标题坐标系与图面几何**只差一个平移**（+40.11，两条剖面各自独立算出同一值）。
    #    曾经这里报 INCONSISTENT_FRAME：两剖面给出的"镜像常量"互斥、平移解不存在。
    #    根因在 V0 俯视图的 u 轴——帧记 mirror_axes=('y',)（轴记错了）且 mirror 参数
    #    无人消费，几何一律按未翻面解释（drawing_u = 207.2992 − model_x，见
    #    resolve_frame_mirrors 的 docstring）。帧翻面位改正后标注/图面同源，疑问消失。
    #    注意判据不是"没报错就算过"：翻面本身是**投出来的**（V0 镜像解释比现行解释多
    #    解释 72mm 轮廓线），裁决过程记在 resolved 里，下面一并核。
    inc = res.questions.by_kind(OpenQuestion.INCONSISTENT_FRAME)
    check("标注坐标系与图面几何已同源（不再报不一致）", len(inc) == 0, str(len(inc)))
    votes = [a for a in res.questions.resolved
             if a.by == "correspondence:mirror_vote"]
    check("V0 帧翻面由跨视图投票裁决（记入 resolved）",
          len(votes) == 1 and votes[0].question.view == "V0"
          and "翻面" in str(votes[0].answer),
          str([str(a) for a in votes])[:200])

    # F3 中心线共线匹配：**6 个回归用例逐张跑，判据不是"看起来对"而是
    #    "落在零件自己的坐标窗口里"** —— 误配必然把位置甩到窗口外。
    n_center = 0
    for path in _CASES:
        if not path.exists():
            check(f"{path.name} 存在", False)
            continue
        d = read_dxf(path)
        detect_views(d)
        type_views(d)
        r = build_correspondence(d)
        win = _windows(r.frames)
        bad: list[str] = []
        for corr in r.by_kind(CorrKind.AXIS):
            val = corr.mapping.value
            if not isinstance(val, Axis3) or val.radius is not None:
                continue          # 只看中心线来的（无半径）
            n_center += 1
            # 同视图十字中心线定出的轴，**沿该视图投影方向的那一维本来就没信息**
            # （图纸上不可见），代码按 0 占位 —— 那不是误配，跳过该维
            skip = {r.frames[v].p_axis for v, _ in corr.refs if v in r.frames}
            for a, coord in (("x", val.origin.x), ("y", val.origin.y),
                             ("z", val.origin.z)):
                if a in skip:
                    continue
                w = win.get(a)
                if w is not None and not (w[0] - 1.0 <= coord <= w[1] + 1.0):
                    bad.append(f"{a}={coord:.2f}∉[{w[0]:.2f},{w[1]:.2f}]")
        check(f"{path.name}：中心线轴全落在零件坐标窗口内", not bad,
              " / ".join(bad))
    check("靶子里确有中心线被匹配上（否则 F3 是空转）", n_center > 0,
          str(n_center))

    # F4 消影/混合壁量尺：并集合并 —— 0.37mm 步的影子碎段群要能合起来
    #    跟可见轮廓比，缝隙 ≤0.1 算连续、跨越更大缺口才断开
    from src.rebuild.views.correspondence import _merge_total
    check("并集量尺：≤0.1 缝隙的碎段合并",
          abs(_merge_total([(0.0, 0.37), (0.37, 0.74),
                             (5.0, 5.5), (5.55, 6.0)]) - 1.74) < 1e-9,
          str(_merge_total([(0.0, 0.37), (0.37, 0.74),
                             (5.0, 5.5), (5.55, 6.0)])))
    check("并集量尺：>0.1 的缝断开计两段",
          abs(_merge_total([(0.0, 1.0), (1.2, 2.0)]) - 1.8) < 1e-9,
          str(_merge_total([(0.0, 1.0), (1.2, 2.0)])))

    # F5 轮廓弧判定（拱 vs 圆边，2026-10-16 定稿）——两个门槛各见一次边界：
    #    ①缺口 > 半圈（画到的弧不足半圆 ⇒ "其余被遮挡"的整圆假设无界，
    #    半圆拱长得一模一样）；②缺口过半落在视图轮廓盒外（盒外不可能有材料）。
    #    四例数值全部取自实测坐标，来源图纸均 gitignore，用同形合成复现。
    import math
    from src.rebuild.model.geom2d import BBox2
    from src.rebuild.views.correspondence import _arc_cover, _profile_arc
    # 端点取整把覆盖算宽：单段 169.86°（YZYX 拱弧实测跨度 5.07°..174.93°）
    # 报 170.5° —— 正是它越过 ARC_COVER_MIN=170° 的机制，故"覆盖够"不能
    # 单独作"是圆"的依据。
    check("弧覆盖 0.5° 分箱：单段 169.86° 报 170.5°",
          abs(_arc_cover([(math.radians(5.07), math.radians(169.86))])
              - math.radians(170.5)) < 1e-9,
          f"{math.degrees(_arc_cover([(math.radians(5.07), math.radians(169.86))])):.1f}°")
    _yz_box = BBox2(3265.44, 1541.25, 3660.44, 1728.75)
    check("轮廓弧①：YZYX 塔拱（r187.5@剖分面，缺口 189.5°>180 且 95% 在盒外）→ 拦",
          _profile_arc(3462.94, 1541.25, 187.5,
                       [(math.radians(5.07), math.radians(169.86))], _yz_box))
    check("轮廓弧②：半圆画满一整个直径（缺口 179.5°≤180，YZYX 半孔/轴测量半圆槽形）→ 不拦",
          not _profile_arc(42.0, 32.0, 20.0,
                           [(math.radians(90.0), math.radians(90.0)),
                            (math.radians(180.0), math.radians(90.0))],
                           BBox2(2.0, 2.0, 42.0, 62.0)))
    check("轮廓弧③：键槽开口（20160112 φ43 截面形，缺口 32.0°≤180）→ 不拦",
          not _profile_arc(0.25, -84.77, 21.5, [(0.0, math.radians(327.6))],
                           BBox2(-21.25, -106.27, 20.90, -63.27)))
    check("轮廓弧④：缺口 > 半圈但落在轮廓盒内（bracket 抬升长圆 r20 形）→ 不拦",
          not _profile_arc(50.0, 50.0, 20.0, [(0.0, math.radians(170.0))],
                           BBox2(0.0, 0.0, 100.0, 100.0)))


# ============ G. 约定层（阶段 2） ============

_SEC_DWG = ROOT / "CAD" / "temp_output" / "bracket_angker_图纸_20260922_剖面图.dxf"
_BLOCK = ROOT / "CAD" / "test_simple" / "block_3view.dxf"
_PF60K = ROOT / "CAD" / "temp_output" / "pf60k_闭环_三视图_20260817.dxf"
#: 自检自给的断裂视图夹具（不能依赖入库产物：一次性夹具按约定不入库）
_FIXTURE_BREAK = ROOT / "CAD" / "temp_output" / "_selftest_break.dxf"
#: 自检自给的局部剖夹具（同上）
_FIXTURE_PARTIAL = ROOT / "CAD" / "temp_output" / "_selftest_partial.dxf"
#: 自检自给的向视图夹具（「c 向」，同上）
_FIXTURE_DIRECTION = ROOT / "CAD" / "temp_output" / "_selftest_direction.dxf"
#: 自检自给的孔标注夹具（`n~∅d 深h` 绑定链，同上）
_FIXTURE_CALLOUT = ROOT / "CAD" / "temp_output" / "_selftest_callout.dxf"
#: 自检自给的**无标题**剖视夹具（半剖/全剖几何推断，同上）
_FIXTURE_HALF = ROOT / "CAD" / "temp_output" / "_selftest_half.dxf"


def _write_break_fixture(out: Path) -> Path:
    """造一张**断裂视图**图纸。

    主视图沿横向被截短（图上 120，真长 200），俯视图完整 —— 于是
    "X 跨度该信谁"有唯一正确答案，也能做反向对照（不喂断裂信息时
    会不会真去用那个残缺的 120）。附带螺纹/未注圆角的正例与一条
    "零件名里的 M4 片段不该当螺纹"的反例。
    """
    import ezdxf

    out.parent.mkdir(parents=True, exist_ok=True)
    doc = ezdxf.new("R2010")
    for name in ("轮廓线", "波浪线", "标注"):
        doc.layers.add(name)
    msp = doc.modelspace()

    def rect(x0: float, y0: float, x1: float, y1: float) -> None:
        msp.add_lwpolyline([(x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0)],
                           dxfattribs={"layer": "轮廓线"})

    rect(0, 80, 120, 140)                    # 主视图（断裂）
    msp.add_lwpolyline([(60, 76), (57, 84), (63, 92), (57, 100), (63, 108),
                        (57, 116), (63, 124), (57, 132), (63, 140), (60, 144)],
                       dxfattribs={"layer": "波浪线"})
    rect(0, 0, 200, 60)                      # 俯视图（完整）
    rect(250, 80, 310, 140)                  # 左视图（完整）
    msp.add_circle((280, 110), 4, dxfattribs={"layer": "轮廓线"})   # M8 大径圆
    for text, pos in (("主视图", (55, 148)), ("俯视图", (90, -12)),
                      ("左视图", (272, 148)), ("M8", (276, 98)),
                      ("未注圆角 R2", (250, 74)),
                      ("麒浚传动_PF60K-14-50-70-M4-L2-12", (250, 66))):
        msp.add_text(text, dxfattribs={"layer": "标注", "height": 5}
                     ).set_placement(pos)
    doc.saveas(out)
    return out


def _write_partial_fixture(out: Path) -> Path:
    """造一张**局部剖**图纸（YZYX C—C 画法的三个信号各一个正例）：

    - 剖视图标题写作「c 向剖视」——明写"剖"才成剖面标题，而剖切种类留空，
      必须靠剖面线覆盖范围几何推断
    - 剖面线画成 ``剖面线`` 图层的 LINE（旧式画法，无 HATCH 实体）且**只盖左半**
    - 一条 ``细实线`` 层线（被盖住的槽底轮廓）
    - 两条线性尺寸标注：图上明标 20 / 3，defpoint 精确落在几何端点上
    """
    import ezdxf

    out.parent.mkdir(parents=True, exist_ok=True)
    doc = ezdxf.new("R2010")
    for name in ("轮廓线", "剖面线", "细实线", "标注"):
        doc.layers.add(name)
    msp = doc.modelspace()

    # 剖视图外框 80×60 + 内部竖线 x=20（左半结构的边界，也是尺寸锚点）
    msp.add_lwpolyline([(0, 0), (80, 0), (80, 60), (0, 60), (0, 0)],
                       dxfattribs={"layer": "轮廓线"})
    msp.add_line((20, 0), (20, 60), dxfattribs={"layer": "轮廓线"})
    # 细实线：被盖住的轮廓（槽底），在右半区域
    msp.add_line((60, 20), (70, 20), dxfattribs={"layer": "细实线"})
    # 剖面线：只盖左半 x 0..20（+45° 短线，全在图框内）。
    # ⚠️ 跨度有意收在 y 5..55：并集高 50/60 ≈ 0.83，与宽 10/80 ≈ 0.13
    # 都 <0.9 —— 覆盖比几何推断必须判 local（盖到 y=60 会误判 full）
    for y in (5, 15, 25, 35, 45):
        msp.add_line((0, y), (10, y + 10), dxfattribs={"layer": "剖面线"})
    # 两条线性尺寸（defpoints 落在几何端点上：竖线两端 / 底边左段）
    dimstyle = doc.dimstyles.add("EZDXF")
    msp.add_linear_dim(base=(0, -8), p1=(0, 0), p2=(20, 0),
                       dimstyle=dimstyle.dxf.name,
                       dxfattribs={"layer": "标注"})
    # angle=90：竖尺寸必须写角度 —— ezdxf 按角度投影算实测值，
    # 不写会拿水平方向去量 (20,0)→(20,3)，get_measurement 得 0
    msp.add_linear_dim(base=(30, 0), p1=(20, 0), p2=(20, 3), angle=90,
                       dimstyle=dimstyle.dxf.name,
                       dxfattribs={"layer": "标注"})
    # 「c 向剖视」剖面标题（无剖切种类词 —— 几何推断的入口）
    msp.add_text("c 向剖视", dxfattribs={"layer": "标注", "height": 5}
                 ).set_placement((40, -14))
    doc.saveas(out)
    return out


def _write_direction_fixture(out: Path) -> Path:
    """造一张**向视图**图纸（YZYX V2「c 向」实测形态）：

    - 标题「c 向」—— 向视图（按箭头方向投射、位置自由），**不是剖视图**
    - 一条波浪断裂线（细实线层折线）—— 视图被截短
    - **零剖面线**：没有 HATCH、也没有剖面线层 LINE
    - 两条轮廓线 + 一个尺寸

    这是 v0.6.29 的更正靶子：这三个信号曾被整体读成"局部剖视图"，于是
    产出三条**全是伪的**阻塞疑问 —— section.scope 的"剖切种类读不出来"、
    section.material 的"是剖视图但图上没有剖面线"、correspondence 的
    "切平面位置未知"。判据就是这三条不许再出现。
    """
    import ezdxf

    out.parent.mkdir(parents=True, exist_ok=True)
    doc = ezdxf.new("R2010")
    for name in ("轮廓线", "细实线", "标注"):
        doc.layers.add(name)
    msp = doc.modelspace()

    # 视图内容：一段外轮廓 + 一个局部特征（R30 弧的直线化替身）
    msp.add_lwpolyline([(0, 0), (60, 0), (60, 40), (0, 40), (0, 0)],
                       dxfattribs={"layer": "轮廓线"})
    msp.add_line((15, 0), (15, 40), dxfattribs={"layer": "轮廓线"})
    # 波浪断裂线（细实线层折线，锯齿形）—— 视图沿横向被截短
    wave = [(0.0, 50.0), (7.5, 46.0), (7.5, 54.0), (15.0, 46.0),
            (15.0, 54.0), (22.5, 46.0)]
    msp.add_lwpolyline(wave, dxfattribs={"layer": "细实线"})
    # 一个尺寸 + 标题
    dimstyle = doc.dimstyles.add("EZDXF")
    msp.add_linear_dim(base=(0, -8), p1=(0, 0), p2=(15, 0),
                       dimstyle=dimstyle.dxf.name, dxfattribs={"layer": "标注"})
    msp.add_text("c 向", dxfattribs={"layer": "标注", "height": 5}
                 ).set_placement((40, -14))
    doc.saveas(out)
    return out


def _write_callout_fixture(out: Path) -> Path:
    """造一张**孔组标注**图纸（YZYX「n~∅d 深h」形态的最小复刻，首角投影）。

    - 主视图 (0,80)-(60,110)：外框 + 圆 A 的孔壁**虚线对**（x 15..25，图上
      y 98..110 —— 从顶面往下 12）；圆 B 在主视图里**不画**轮廓对（简化画法）
    - 俯视图 (0,0)-(60,40)：两个可见 r5 圆（x=20 / x=40）—— 圆 A 的 span 由
      投影直接量到，圆 B 只靠"同组同构"的组内传播（tier 差一档）
    - 左视图 (250,80)-(290,110)：一个可见 r3 圆，全图无轮廓对 ⇒ 绑定成立但
      "孔口位置未知" ⇒ 按设计**拒绝发射**（这条正是"不许按 0 起硬切"的靶子）
    - 两条孔标注：`2~∅10 深12`（贴俯视图，数量对得上）/ `3~∅6 深25`
      （贴左视图，图上只有 1 个圆 —— 数量不符照绑只记账）
    """
    import ezdxf

    out.parent.mkdir(parents=True, exist_ok=True)
    doc = ezdxf.new("R2010")
    for name in ("轮廓线", "虚线", "标注"):
        doc.layers.add(name)
    msp = doc.modelspace()

    def rect(x0: float, y0: float, x1: float, y1: float) -> None:
        msp.add_lwpolyline([(x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0)],
                           dxfattribs={"layer": "轮廓线"})

    rect(0, 80, 60, 110)                     # 主视图 60×30
    rect(0, 0, 60, 40)                       # 俯视图 60×40
    rect(250, 80, 290, 110)                  # 左视图 40×30
    # 圆 A 的孔壁对（虚线）：x=15/25 间距 2r=10，自顶面向下 12
    msp.add_line((15, 98), (15, 110), dxfattribs={"layer": "虚线"})
    msp.add_line((25, 98), (25, 110), dxfattribs={"layer": "虚线"})
    msp.add_circle((20, 20), 5, dxfattribs={"layer": "轮廓线"})   # 圆 A
    msp.add_circle((40, 20), 5, dxfattribs={"layer": "轮廓线"})   # 圆 B
    msp.add_circle((270, 95), 3, dxfattribs={"layer": "轮廓线"})  # 左视图 r3
    for text, pos in (("主视图", (18, 114)), ("俯视图", (12, -12)),
                      ("左视图", (258, 114)), ("2~∅10 深12", (44, -12)),
                      ("3~∅6 深25", (300, 95))):
        msp.add_text(text, dxfattribs={"layer": "标注", "height": 5}
                     ).set_placement(pos)
    doc.saveas(out)
    return out


def _write_half_fixture(out: Path) -> Path:
    """造一张**无剖切标题**的图纸（YZYX V0/V1 实测形态的最小复刻）：

    - 视图 A：贯穿的竖直中心线 + 剖面线**只盖中心线左侧**（留 4mm 间隙）
      ⇒ 几何推断半剖（另一侧是外形视，按制图法不画剖面线）
    - 视图 B：剖面线横跨全幅（覆盖比 1.0）⇒ 几何推断全剖
    - 视图 C：一条剖面线都没有 ⇒ 不许凭空产出剖视结论（反向对照：
      越界推断的后果正是把普通视图当剖视图去裁材料）

    三个视图都**没有**剖面标题 —— 这正是 v0.6.31 补的缺口：此前
    scope 只处理 ``isinstance(cut, CutSpec)`` 的视图，半剖从未被识别。
    """
    import ezdxf

    out.parent.mkdir(parents=True, exist_ok=True)
    doc = ezdxf.new("R2010")
    for name in ("轮廓线", "剖面线", "中心线"):
        doc.layers.add(name)
    msp = doc.modelspace()

    def rect(x0: float, y0: float, x1: float, y1: float) -> None:
        msp.add_lwpolyline([(x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0)],
                           dxfattribs={"layer": "轮廓线"})

    rect(0, 0, 80, 60)                       # 视图 A（半剖候选）
    msp.add_line((40, 0), (40, 60), dxfattribs={"layer": "中心线"})
    for y in (5, 15, 25, 35, 45):            # 剖面线只盖左半（≤x=36）
        msp.add_line((0, y), (36, y), dxfattribs={"layer": "剖面线"})
    rect(150, 0, 230, 60)                    # 视图 B（全剖候选）
    for y in (5, 15, 25, 35, 45):
        msp.add_line((150, y), (230, y), dxfattribs={"layer": "剖面线"})
    rect(300, 0, 380, 60)                    # 视图 C（反向对照：无剖面线）
    doc.saveas(out)
    return out


def _prepared(path: Path):
    """读 → 分离 → 定性（约定层与对应层的共同前置）。"""
    d = read_dxf(path)
    detect_views(d)
    type_views(d)
    return d


def test_conventions() -> None:
    section("G. 约定层（阶段 2）")

    # ---- G1 每条规则**独立**可跑（阶段 2 验收原文："每条规则有独立测试"） ----
    names = REG.registered()
    check("注册表里 11 条规则", len(names) == 11, str(names))
    check("孔标注规则已注册", "callout.hole_groups" in names, str(names))
    d = _prepared(_SEC_DWG)
    per: dict[str, Conventions] = {
        n: run_rules(RuleCtx(d=d), only=[n]) for n in names}
    for n in names:
        check(f"单跑 {n} 不抛异常", not per[n].failed, str(per[n].failed))
        check(f"单跑 {n} 的结论只来自它自己",
              all(c.rule == n for c in per[n].items))

    # ---- G2 失败隔离：坏规则变成待确认项，其余照跑 ----
    def _boom(ctx: RuleCtx):                       # noqa: ANN202
        raise RuntimeError("故意的")

    REG.register("selftest.boom")(_boom)           # 临时插一条会炸的规则
    try:
        r = run_rules(RuleCtx(d=d))
    finally:
        REG._RULES[:] = [x for x in REG._RULES if x.name != "selftest.boom"]
    check("坏规则被记账", [n for n, _ in r.failed] == ["selftest.boom"],
          str(r.failed))
    check("坏规则转成待确认项",
          bool(r.questions.by_kind(OpenQuestion.OUT_OF_DOMAIN)))
    check("其余规则照跑（材料结论仍在）", bool(r.of_kind(ConvKind.MATERIAL)))
    check("临时规则已摘除", "selftest.boom" not in REG.registered())

    # ---- G3 断裂视图：从波浪线一路走到"该模型轴坐标不可用" ----
    d2 = _prepared(_write_break_fixture(_FIXTURE_BREAK))
    conv = run_rules(RuleCtx(d=d2))
    front = next(v.id for v in d2.views if v.resolved_type == ViewType.FRONT)
    brk = conv.of_kind(ConvKind.BREAK)
    check("识别出 1 处断裂（波浪线折线聚成一条）",
          len(brk) == 1 and brk[0].view == front,
          f"{len(brk)} 条：{[c.view for c in brk]}")
    check("断裂方向 = 图纸横向 u（竖波浪线横跨零件）",
          bool(brk) and isinstance(brk[0].value, BrokenView)
          and brk[0].value.which == ("u",),
          str(brk[0].value.which) if brk else "无")
    check("断裂是 CONVENTION 级（图层名明写）",
          bool(brk) and brk[0].tier is Tier.CONVENTION)
    check("断裂信息汇总进 Conventions.broken", conv.broken == {front: ("u",)},
          str(conv.broken))
    bq = conv.questions.by_kind(OpenQuestion.BROKEN_VIEW)
    check("报出断裂视图待确认项", len(bq) == 1 and bq[0].view == front,
          str([q.view for q in bq]))

    # 约定层说"图纸横向不可用" → 视图坐标系把它翻成模型轴 x
    res = build_correspondence(d2, broken=conv.broken)
    f0 = res.frames[front]
    top = next(v.id for v in d2.views if v.resolved_type == ViewType.TOP)
    check("主视图的 x 轴被判为断裂轴", f0.broken_axes == ("x",),
          str(f0.broken_axes))
    check("断裂轴的跨度不可用（返回 None）", f0.model_span("x") is None)
    check("未断裂的 z 轴跨度照常可用", f0.model_span("z") == (80.0, 140.0),
          str(f0.model_span("z")))
    check("X 跨度改由俯视图提供（0–200，而非残缺的 0–120）",
          f0.u_span == (0.0, 200.0), str(f0.u_span))
    check("俯视图自己不被牵连", res.frames[top].broken_axes == ()
          and res.frames[top].model_span("x") == (0.0, 200.0))
    # 反向对照：这条链子真的在起作用 —— 不喂断裂信息，主视图就会拿
    # 自己残缺的 120 去给全图定标（正是旧管线的错法）
    plain = build_correspondence(d2).frames[front]
    check("反向对照：不喂断裂信息则会用残缺的 120 定标",
          plain.u_span == (0.0, 120.0), str(plain.u_span))

    # ---- G4 螺纹：正例（有几何佐证）+ 反例（零件名里的 M4） ----
    th = conv.of_kind(ConvKind.THREAD)
    check("「M8」读出 1 条螺纹", len(th) == 1, str(len(th)))
    if th:
        spec = th[0].value
        check("M8 大径 = 8", isinstance(spec, ThreadSpec) and spec.major_d == 8.0,
              str(spec))
        check("找到对应大径圆 ⇒ 升到 CONVENTION 级",
              th[0].tier is Tier.CONVENTION and spec.hole_ref is not None)
    longs = [t for t in d2.texts if "PF60K" in (t.text or "")]
    check("零件名长文字确实被读到（防反例空转）", len(longs) == 1,
          str(len(longs)))
    if longs:
        lh = longs[0].handle
        check("零件名里的 M4 片段不被当成螺纹",
              all(lh not in c.evidence for c in th))

    # ---- G5 未注圆角 ----
    fl = conv.of_kind(ConvKind.FILLET)
    check("「未注圆角 R2」读出 R2",
          len(fl) == 1 and fl[0].value.radius == 2.0,
          str([c.value for c in fl]))
    check("未注圆角是 ANNOTATED 级（图上明写）",
          bool(fl) and fl[0].tier is Tier.ANNOTATED)

    # ---- G6 剖切种类 → 能不能当截面棱柱用（决策表逐条） ----
    for kind, sc, usable in (("纵向全剖", "full", True), ("横剖", "full", True),
                             ("剖视", "full", True), ("半剖", "half", False),
                             ("局部剖", "local", False), ("旋转剖", "multi", False),
                             ("阶梯剖", "multi", False), ("", "unknown", False)):
        got = _classify(kind)
        check(f"剖切「{kind or '空'}」⇒ {sc}/{'可用' if usable else '不可用'}",
              got[0] == sc and got[1] is usable, str(got[:2]))
    scs = per["section.scope"].of_kind(ConvKind.SECTION)
    check("bracket 三个剖视图全判为可作截面棱柱",
          len(scs) == 3 and all(c.value.usable_as_prism for c in scs),
          str([(c.view, c.value.scope) for c in scs]))

    # ---- G7 HATCH ⇒ 材料 ----
    mat = per["section.material"].of_kind(ConvKind.MATERIAL)
    check("bracket 三个剖视图各 2 处剖面填充",
          len(mat) == 3 and all(c.value.count == 2 for c in mat),
          str([(c.view, c.value.count) for c in mat]))
    check("填充图案读到了（ANSI31）",
          bool(mat) and all(c.value.pattern for c in mat))
    check("剖面填充的证据 handle 互不重复（IR 不变式）",
          all(len(set(c.evidence)) == len(c.evidence) for c in mat))

    # ---- G8 虚线 ⇒ 内部特征 ----
    hid = per["linetype.hidden"].of_kind(ConvKind.HIDDEN)
    check("bracket 六个视图都读到虚线",
          len(hid) == 6 and all(c.value.count > 0 for c in hid),
          str([(c.view, c.value.count) for c in hid]))

    # ---- G9 阵列：PF60K 的 4×φ5.5 分布圆 ----
    cf = run_rules(RuleCtx(d=_prepared(_PF60K)))
    pat = cf.of_kind(ConvKind.PATTERN)
    check("PF60K 认出 1 个环形阵列", len(pat) == 1, str(len(pat)))
    if pat:
        p = pat[0].value
        check("是 Pattern 且 4 个孔", isinstance(p, Pattern) and p.n == 4,
              str(p))
        check("分布圆 R35", abs(p.radius - 35.0) < 0.01, f"{p.radius:.4f}")
        check("孔半径 2.75（φ5.5）", abs(p.hole_radius - 2.75) < 1e-9,
              str(p.hole_radius))
        check("四孔严格 90° 等距",
              [round(a, 6) for a in p.angles] == [45.0, 135.0, 225.0, 315.0],
              str(p.angles))
        check("图上没写「均布」⇒ 如实报出待确认项",
              not p.annotated
              and bool(cf.questions.by_kind(OpenQuestion.AMBIGUOUS_FEATURE)))

    # ---- G10 对称（正例 block_3view / 负例：夹具里没有中心线） ----
    c3 = run_rules(RuleCtx(d=_prepared(_BLOCK)))
    sym = c3.of_kind(ConvKind.SYMMETRY)
    check("block_3view 三个视图都判出对称",
          len(sym) == 3 and all(c.value.support >= 0.9 for c in sym),
          str([(c.view, round(c.value.support, 3)) for c in sym]))
    check("无中心线的夹具不产生对称结论",
          not conv.of_kind(ConvKind.SYMMETRY))
    check("无剖面的三视图不产生材料/虚线结论",
          not c3.of_kind(ConvKind.MATERIAL) and not c3.of_kind(ConvKind.HIDDEN))

    # ---- G11 局部剖三信号（YZYX C—C 手工读图三轮经验的前移版） ----
    # 「c 向剖视」标题 + LINE 画法剖面线（只盖左半）+ 细实线 + 两条尺寸标注
    from src.rebuild.evidence.text_parser import CutSpec
    d3 = _prepared(_write_partial_fixture(_FIXTURE_PARTIAL))
    cv3 = run_rules(RuleCtx(d=d3))
    check("夹具分离出 1 个视图", len(d3.views) == 1, str(len(d3.views)))
    v3 = d3.views[0]
    check("「c 向剖视」标题 ⇒ 视图定性 SECTION",
          v3.resolved_type == ViewType.SECTION, str(v3.resolved_type))
    check("CutSpec：标签归一 C、剖切种类留空（几何推断入口）",
          isinstance(v3.cut, CutSpec) and v3.cut.label == "C"
          and not v3.cut.kind, str(v3.cut))
    scs3 = cv3.of_kind(ConvKind.SECTION)
    check("标题没写种类 ⇒ 剖面线覆盖比几何推断为 local",
          len(scs3) == 1 and scs3[0].value.scope == "local",
          str([(c.view, c.value.scope) for c in scs3]))
    check("local ⇒ 不可作截面棱柱（防整幅裁真材料）",
          bool(scs3) and scs3[0].value.usable_as_prism is False)
    check("几何推断的剖切种类是 GUESS 级（图上没明写）",
          bool(scs3) and scs3[0].tier is Tier.GUESS)
    check("报出「不得整幅裁材料」待确认项",
          bool(cv3.questions.by_kind(OpenQuestion.AMBIGUOUS_FEATURE)))
    # 护栏：无切平面的 CutSpec（「c 向剖视」没写位置）过全链不崩 ——
    # 对应层必须优雅跳过（correspondence.py 的 is_located 守卫）
    check("无切平面的剖视图过 understand 全链不崩",
          isinstance(understand(str(_FIXTURE_PARTIAL)), tuple))
    mat3 = cv3.of_kind(ConvKind.MATERIAL)
    check("剖面线画成 LINE 也读成材料信号（5 条聚 1 区）",
          len(mat3) == 1 and mat3[0].value.count == 5
          and len(mat3[0].value.zones) == 1,
          str([(c.value.count, len(c.value.zones)) for c in mat3]))
    check("LINE 画法的图案记为 lines",
          bool(mat3) and mat3[0].value.pattern == "lines")
    th3 = cv3.of_kind(ConvKind.THIN)
    thin_edge = next((e for e in d3.evidence
                      if e.role.value == Role.THIN.value), None)
    check("细实线 1 条、证据 handle 对",
          len(th3) == 1 and th3[0].value.count == 1 and thin_edge is not None
          and th3[0].evidence == (thin_edge.handle,),
          str([(c.view, c.value.count) for c in th3]))
    dims3 = cv3.of_kind(ConvKind.DIMENSION)
    check("两条尺寸各产一条结论", len(dims3) == 2, str(len(dims3)))
    check("尺寸值 20 / 3 逐位读出",
          sorted(c.value.value for c in dims3) == [3.0, 20.0],
          str([c.value.value for c in dims3]))
    check("两条尺寸都锚到几何（defpoint ↔ 端点配对）",
          bool(dims3) and all(c.value.anchors for c in dims3),
          str([(c.value.value, len(c.value.anchors)) for c in dims3]))
    check("尺寸是 ANNOTATED 级（图上明标）",
          bool(dims3) and all(c.tier is Tier.ANNOTATED for c in dims3))
    # 反向对照：bracket 剖面图里没有细实线/尺寸（新规则不能凭空产出结论），
    # 且它标题明写种类的全剖**不因几何推断路径的存在而降级**
    check("bracket 剖面图反向对照：无细实线/尺寸结论",
          not per["linetype.thin"].of_kind(ConvKind.THIN)
          and not per["dimension.anchors"].of_kind(ConvKind.DIMENSION))
    check("bracket 全剖不降级：三条都仍是 full 且 CONVENTION 级",
          len(scs) == 3 and all(c.value.scope == "full"
                                and c.tier is Tier.CONVENTION for c in scs),
          str([(c.view, c.value.scope, c.tier.value) for c in scs]))

    # ---- G12 向视图（YZYX V2「c 向」实测形态：三条伪疑问的更正靶子） ----
    # 标题「c 向」+ 波浪断裂线 + **零剖面线**。此前被整条读成局部剖视图，
    # 产出："剖切种类读不出来"（section.scope）、"是剖视图但图上没有剖面线"
    # （section.material）、"切平面位置未知"（correspondence）—— 全是伪的。
    from src.rebuild.evidence.text_parser import TextKind
    d4 = read_dxf(_write_direction_fixture(_FIXTURE_DIRECTION))
    detect_views(d4)
    qs4 = type_views(d4)
    check("向视图夹具分离出 1 个视图", len(d4.views) == 1, str(len(d4.views)))
    v4 = d4.views[0]
    t4 = next((t for t in d4.texts
               if t.kind == TextKind.DIRECTION_VIEW), None)
    check("「c 向」读成 DIRECTION_VIEW 标题、标签归一 C",
          t4 is not None and t4.direction_label == "C", str(t4))
    check("向视图不带 CutSpec（图上没有切平面）", v4.cut is None, str(v4.cut))
    check("向视图不被定性为 SECTION（无剖面含义）",
          v4.resolved_type != ViewType.SECTION, str(v4.resolved_type))
    check("向视图产出专用 UNKNOWN_VIEW 疑问（点明投射方向）",
          any(q.kind == OpenQuestion.UNKNOWN_VIEW and "向视图" in q.detail
              for q in qs4.items),
          str([q.detail for q in qs4.items]))
    cv4 = run_rules(RuleCtx(d=d4))
    check("向视图不产 SECTION 结论（不套剖面语义）",
          not cv4.of_kind(ConvKind.SECTION),
          str([(c.rule, c.value) for c in cv4.of_kind(ConvKind.SECTION)]))
    check("向视图不产 MATERIAL 结论（零剖面线不报缺）",
          not cv4.of_kind(ConvKind.MATERIAL))
    dets4 = [q.detail for q in cv4.questions.items]
    check("不再有「剖切种类读不出来」伪疑问",
          not any("剖切种类" in s for s in dets4), str(dets4))
    check("不再有「是剖视图但图上没有剖面线」伪疑问",
          not any("没有剖面线" in s for s in dets4), str(dets4))
    check("向视图过 understand 全链不崩",
          isinstance(understand(str(_FIXTURE_DIRECTION)), tuple))

    # ---- G13 孔标注「n~∅d 深h」：读取与门（YZYX 六条实测 + 反例防线） ----
    # 只有"孔才有的说法"（数量前缀 / 深 / 孔类关键词）才构成孔标注；
    # 光秃秃的直径与螺纹是零件尺寸（φ96.5 / M16 可能是轴），不许混进孔组。
    from src.rebuild.conventions.callout import parse_callout
    for s, n, dia, dep in (("8~∅13", 8, 13.0, None),
                           ("4~∅10-7H 深25", 4, 10.0, 25.0),
                           ("3~∅10-7H 深20", 3, 10.0, 20.0),
                           ("2~∅6锥销孔", 2, 6.0, None),
                           ("∅16锥孔", 1, 16.0, None)):   # 数量缺省 = 1
        hc = parse_callout("H0", s)
        check(f"孔标注「{s}」读得出来",
              hc is not None and hc.count == n and hc.depth == dep
              and abs(hc.diameter - dia) < 1e-9, str(hc))
    hc_t = parse_callout("H1", "2~M16-7H (通孔)")
    check("「2~M16-7H (通孔)」：螺纹大径当名义直径、公差带与显式通孔都在",
          hc_t is not None and hc_t.thread == "M16" and hc_t.tolerance == "7H"
          and abs(hc_t.diameter - 16.0) < 1e-9 and "kw:通孔" in hc_t.matched,
          str(hc_t))
    hc_k = parse_callout("H2", "2~∅6锥销孔")
    check("「锥销孔」读出孔种（不是普通孔）",
          hc_k is not None and hc_k.kind == "taper_pin_hole", str(hc_k))
    hc_d = parse_callout("H3", "4~∅10-7H 深25")
    check("「深25」⇒ 盲孔（through=False）", hc_d is not None
          and hc_d.depth == 25.0 and hc_d.through is False, str(hc_d))
    for s in ("φ96.5", "R15", "1.5×45°", "φ5.5×90°", "M16",
              "技术要求：未注圆角 R3"):
        check(f"「{s}」不是孔标注（误报防线）",
              parse_callout("H4", s) is None, s)

    # ---- G14 无标题剖视的几何推断（YZYX V0 半剖 / V1 全剖实测形态） ----
    # 缺口：scope 此前只认"有剖面标题"的视图（isinstance(cut, CutSpec)），
    # 无标题的半剖从未被识别。判据：中心线 + 材料整体单侧 ⇒ 半剖；材料
    # 横跨全幅 ⇒ 全剖；判不出不产出（反例：视图 C 零剖面线）。
    d14 = _prepared(_write_half_fixture(_FIXTURE_HALF))
    cv14 = run_rules(RuleCtx(d=d14))
    scs14 = cv14.of_kind(ConvKind.SECTION)
    check("无标题：半剖/全剖各推断一条、零剖面线的视图不产结论",
          len(scs14) == 2 and all(c.value.origin == "inferred"
                                  for c in scs14),
          str([(c.view, c.value.scope, c.value.origin) for c in scs14]))
    half14 = next((c for c in scs14 if c.value.scope == "half"), None)
    check("中心线 + 材料单侧 ⇒ 半剖，记下剖面在左半",
          half14 is not None and half14.value.side == "左半"
          and half14.value.kind == ""
          and half14.value.usable_as_prism is False,
          str(half14 and half14.value))
    full14 = next((c for c in scs14 if c.value.scope == "full"), None)
    check("材料横跨全幅 ⇒ 全剖（覆盖比 ≥0.9）",
          full14 is not None, str(full14 and full14.value))
    check("几何推断一律 GUESS 级 + 不作截面棱柱 + 不额外报疑问（缺信息≠歧义）",
          all(c.tier is Tier.GUESS for c in scs14)
          and all(c.value.usable_as_prism is False for c in scs14)
          and not [q for q in cv14.questions.by_kind(
                       OpenQuestion.AMBIGUOUS_FEATURE) if "剖" in q.detail],
          str([(c.tier.name, c.value.usable_as_prism) for c in scs14]))


# ---- 阶段 3：特征层 ----

def _recognized(path: Path):
    """读 → 分离 → 定性 → 约定 → 对应 → 识别（阶段 3 全链）。

    **与 ``pipeline.understand`` 同一条接线**：从头共用一份 QuestionList
    （type_views 起、约定层的问题并进去、corr 与 recognize 都往它上面写）。
    不共用的话 corr 层的歧义疑问落在 corr.questions、识别层的裁决落在
    rep.questions —— 两个列表各记各的，``rep.questions.resolved`` 永远
    为空（H5 查"裁决记录可追"时才发现，此前一直如此）。
    """
    d = read_dxf(path)
    detect_views(d)
    qs = type_views(d)
    conv = run_rules(RuleCtx(d=d))
    qs.extend(conv.questions.items)
    corr = build_correspondence(d, qs, broken=conv.broken)
    return d, conv, corr, recognize(d, corr, conv, qs)


def test_features() -> None:
    section("H. 特征层（阶段 3）")

    # ---- H1 参数契约与轮廓坐标系（发射器按同一张表落位） ----
    missing = [t.value for t in FeatureType if t not in PARAMS]
    check("每种特征都有参数契约 PARAMS", not missing, str(missing))
    for d_name, (b1, b2) in ((n, profile_plane(n)) for n in "xyz"):
        c = b1.cross(b2)
        axis = {"x": Vector3(1, 0, 0), "y": Vector3(0, 1, 0),
                "z": Vector3(0, 0, 1)}[d_name]
        check(f"{d_name} 向轮廓基右手（b1×b2 = dir）",
              (c - axis).norm < 1e-12, f"{b1}×{b2}={c}")
    # 往返：ir_coords 以**零件原点**为原点（o≠原点时 ir_point 不是它的逆）
    ok = True
    for n in "xyz":
        p = ir_point(Point3(0.0, 0.0, 0.0), n, 7.0, -4.0, 11.0)
        ok = ok and all(abs(x - y) < 1e-9
                        for x, y in zip(ir_coords(p, n), (7.0, -4.0, 11.0)))
    check("ir_point / ir_coords 往返一致（三向，原点为 o）", ok)

    # ---- H2 预测：孔与凸台在同一条轴上**唯一**的区分是虚实 ----
    # 取盲孔（depth 给出）：通孔的长度由基体决定，横视图的预测要等基体知了才有
    hole = Feature(id=FeatureId(1), type=Claim(FeatureType.HOLE, "t", Tier.GUESS),
                   params={"radius": Claim(5.0, "t", Tier.GUESS),
                           "through": Claim(False, "t", Tier.GUESS),
                           "depth": Claim(10.0, "t", Tier.GUESS)},
                   axis=Claim(Axis3(Point3(0, 0, 0), Vector3(0, 0, 1)),
                              "t", Tier.GUESS))
    boss = Feature(id=FeatureId(2), type=Claim(FeatureType.BOSS, "t", Tier.GUESS),
                   params={"radius": Claim(5.0, "t", Tier.GUESS),
                           "height": Claim(3.0, "t", Tier.GUESS)},
                   axis=Claim(Axis3(Point3(0, 0, 0), Vector3(0, 0, 1)),
                              "t", Tier.GUESS))
    ph = predict_in_view(hole, "front")
    pb = predict_in_view(boss, "front")
    check("孔沿 z 在正视图中预测为两条**虚**平行线",
          len(ph) == 2 and all(x.kind == "segment" and not x.visible for x in ph),
          str(ph))
    check("凸台沿 z 在正视图中预测为两条**实**平行线",
          len(pb) == 2 and all(x.kind == "segment" and x.visible for x in pb),
          str(pb))
    check("顺轴（俯视）看两者都是实心圆",
          all(x.kind == "circle" for x in predict_in_view(hole, "top")
              + predict_in_view(boss, "top")))

    # ---- H3 先验：R8 vs R8.5（CLAUDE.md 信息论局限表的落点） ----
    s85 = snap_radius(8.5)
    check("R10 优先数系里没有 8.5，最近的是 8.0",
          s85.standard and abs(s85.value - 8.0) < 1e-9 and s85.changed,
          str(s85))
    check("偏离约 5.88%（8.5→8.0）", abs(s85.delta_pct - 5.88) < 0.01,
          f"{s85.delta_pct:.2f}%")
    s80 = snap_radius(8.0)
    check("8.0 本身就是标准值（不改）",
          s80.standard and not s80.changed, str(s80))
    d85 = snap_diameter(8.5)
    check("φ8.5 在麻花钻表里是标准值 ⇒ 两张表必须分开",
          d85.standard and not d85.changed and d85.source == "drill", str(d85))
    far = snap_radius(1000.0)
    check("表外的值如实报「非标准」，不硬套", not far.standard, str(far))
    c85 = snap_claim(8.5, "radius")
    check("snap_claim 给出 PRIOR 级并保留原值作备选",
          c85.tier is Tier.PRIOR and c85.value == 8.0
          and 8.5 in c85.alternatives, str(c85))

    # ---- H4 求解：合并的冲突判据（硬碰硬才算矛盾） ----
    a = Claim(25.5, "note:x", Tier.ANNOTATED, evidence=("H1",))
    b = Claim(25.5, "projection:y", Tier.PROJECTION, evidence=("H3",))
    m, cf = merge_with_conflict(a, b, label="半径")
    check("同值两路合并无冲突", cf is None and m.value == 25.5)
    m2, cf2 = merge_with_conflict(
        a, Claim(26.5, "note:z", Tier.ANNOTATED, evidence=("H2",)), label="半径")
    check("两路都是图上明标且差 1mm ⇒ 报冲突",
          cf2 is not None and m2.value == 25.5, str(cf2))
    m3, cf3 = merge_with_conflict(
        a, Claim(26.5, "projection:y", Tier.PROJECTION, evidence=("H4",)),
        label="半径")
    check("标注 vs 投影差 1mm **不**算冲突（出图误差是常态）", cf3 is None)

    # ---- H5 bracket：高度分解 + 剖面标题并证据 + 通孔判定 ----
    # 树自 v0.6.22 阶段 7 起是"分解后"的形态：基体降到最低公共高度，
    # 分区（材料升 / 切除）各成一段 base/pocket —— 7 特征是分解前的账。
    _, conv_b, corr_b, rep_b = _recognized(_SEC_DWG)
    check("bracket 剖面图纸识别出 11 个特征（基体降高 +4 分区 + 2 圆角 + "
          "月牙缺口/张缝/销孔；r9 拒发、剖面标题不建孤儿）",
          len(rep_b.part.features) == 11,
          str([(str(f.id), f.type.value) for f in rep_b.part.features]))
    base = rep_b.part.features[0]
    check("基体降到 z[2,24]（高 22）——高度分解已生效（不再是沿 z 拉伸 44）",
          base.type.value == "base" and base.params["dir"].value == "z"
          and abs(base.params["length"].value - 22.0) < 1e-9,
          str(base.params["length"]))
    f1 = next((f for f in rep_b.part.features if f.id == FeatureId(1)), None)
    check("材料分区各成一段抬升 base（#1 塔柱 z24..46 高 22、#2 圆盘 z24..30 高 6）",
          f1 is not None
          and all(rep_b.part.features[i].type.value == "base" for i in (1, 2))
          and abs(f1.params["length"].value - 22.0) < 1e-9
          and abs(rep_b.part.features[2].params["length"].value - 6.0) < 1e-9,
          str([(str(f.id), f.type.value) for f in rep_b.part.features[:3]]))
    check("剖面标题（B—B r25.5 / A—A r20）与已读圆柱重合 ⇒ 只并证据、不建孤儿",
          f1 is not None and len(f1.evidence) >= 5
          and all(f.type.method != "note:section_title"
                  for f in rep_b.part.features)
          and sum("只并证据" in n for n in rep_b.notes) == 2,
          str([n for n in rep_b.notes if "只并证据" in n]))
    f3 = next((f for f in rep_b.part.features if f.id == FeatureId(3)), None)
    check("#3 深 44 = 该轴材料厚 44 ⇒ 通孔（DERIVED，非 GUESS）",
          f3 is not None and f3.params["through"].value is True
          and f3.params["through"].tier is Tier.DERIVED
          and f3.params["through"].method == "derived:depth_vs_material",
          str(f3.params["through"]) if f3 else "无 #3")
    check("r15.7 实/虚冲突由分区剪影裁决为孔（hole/PROJECTION，不再 GUESS）",
          f3 is not None and f3.type.value == "hole"
          and f3.type.tier is Tier.PROJECTION
          and FeatureType.BOSS not in (f3.type.alternatives or ()),
          str(f3.type) if f3 else "无 #3")
    check("被裁决的圆歧义进 resolved 而不是被删（可追当时怎么想的）",
          any("实线轮廓对" in a.question.detail and "hole" in str(a.answer)
              for a in rep_b.questions.resolved)
          and any("找不到间距 2r" in a.question.detail
                  and "neither" in str(a.answer)
                  for a in rep_b.questions.resolved),
          str([str(a)[:60] for a in rep_b.questions.resolved]))
    check("r9 圆（R3 环面相切圆）在 HLR 图上全无轮廓对 ⇒ 拒发、不猜孔",
          all(abs(f.params["radius"].value - 9.0) > 1e-9
              for f in rep_b.part.features if "radius" in f.params)
          and any("不建特征" in n for n in rep_b.notes),
          str([n for n in rep_b.notes if "不建特征" in n]))
    check("每处孔都有 through（发射器不接受缺参数）",
          all("through" in f.params for f in rep_b.part.features
              if f.type.value == "hole"))

    # ---- H5c HLR 重合消影/混合壁通道（corr 报疑 → 分区剪影裁决） ----
    # 叉尖 r12 的侧视图下壁带内实 12 / 虚 12 并存（半圆柱面与"孔壁虚线被
    # 可见优先去重消影"在图上同形）—— 逐段配对判据抓不到（最长隐藏对仅
    # 0.37），并集量尺报疑；分区/特征剪影裁决回 boss、与特征现值一致 ⇒
    # 只记账不改写（体积零漂移由验收表逐位保证）。r25.5 塔柱带内基体
    # 圆角轮廓、r20 下壁的实虚重叠同样报疑、同样被分区裁决。
    # 混合壁检查按**每个正交视图自己的最长轮廓对**看，不再只绑定全局最长
    # 对所在的那个视图——否则共线合并后 V2 读满 44mm，V1 壁带里的歧义就
    # 被跳过了（V1 左壁只画了 25mm 上段，它仍是最直接的图面证据）。
    occl = [a for a in rep_b.questions.resolved if "消影" in a.question.detail]
    check("消影之疑报出并全部裁决（r12 叉尖 + r25.5 塔柱带 + r20 异源重叠）",
          len(occl) == 3
          and all(a.by == "recognize:hlr_occlude"
                  and "boss" in str(a.answer) for a in occl)
          and any("r12" in a.question.detail for a in occl)
          and any("r25.5" in a.question.detail for a in occl)
          and any("r20" in a.question.detail for a in occl),
          str([str(a)[:70] for a in occl]))
    check("r12 特征仍为 boss/PROJECTION（裁决一致 ⇒ 不改写、tier 不降）",
          any(f.type.value == "boss"
              and abs(f.params["radius"].value - 12.0) < 1e-9
              and f.type.tier is Tier.PROJECTION
              for f in rep_b.part.features),
          str([(str(f.id), f.type.value) for f in rep_b.part.features
               if "radius" in f.params
               and abs(f.params["radius"].value - 12.0) < 1e-9]))

    # ---- H5d PF60K：r25/r8.5 凹槽的实/虚并存按回转母线证据覆盖裁决 ----
    # r8.5 的侧视图壁带内实 5.90 / 虚 5.00、r25 下壁实 8.00 / 虚 5.00
    # 并存 —— 若是独立圆柱这是"半圆柱/消影孔"之疑；但圆边已被回转基体
    # 吸收（凹槽/台阶是母线自身的图面），按证据覆盖裁决，不阻塞。
    _, _, _, rep_p = _recognized(_PF60K)
    occl_p = [a for a in rep_p.questions.resolved
              if "消影" in a.question.detail]
    check("PF60K r25/r8.5 实/虚并存按回转母线证据覆盖裁决（凹槽图面非消影孔）",
          len(occl_p) == 2
          and all(a.by == "revolve:profile_absorbed" for a in occl_p)
          and any("r8.5" in a.question.detail for a in occl_p)
          and any("r25 " in a.question.detail for a in occl_p),
          str([str(a)[:70] for a in occl_p]))

    # ---- H6 PF60K：阵列挂到正确的孔上（判据是"在分布圆上"，不是"在圆心上"） ----
    pats = [f for f in rep_p.part.features if f.type.value == "pattern"]
    check("PF60K 识别出 1 个阵列特征", len(pats) == 1, str(len(pats)))
    if pats:
        p = pats[0]
        child = p.params.get("child")
        ch = (next((f for f in rep_p.part.features if f.id == child.value), None)
              if child is not None else None)
        check("阵列挂上了被阵列的孔（不是「找不到 child」）",
              ch is not None, str(child))
        if ch is not None:
            o, c3 = ch.axis.value.origin, p.placement.value
            dist = ((o.x - c3.x) ** 2 + (o.y - c3.y) ** 2) ** 0.5
            r_bc = p.params["bc_radius"].value
            check("孔轴落在分布圆上（|dist − R| ≤ 0.6）",
                  abs(dist - r_bc) <= 0.6, f"dist={dist:.4f} R={r_bc:.4f}")
            check("孔径与阵列声明一致（r2.75）",
                  abs(ch.params["radius"].value - 2.75) < 1e-9)
        check("阵列中心＝孔系中心（其余孔绕它均布）",
              abs(p.placement.value.x - 42.0) < 0.01
              and abs(p.placement.value.y - 192.9) < 0.01,
              f"({p.placement.value.x:.2f},{p.placement.value.y:.2f})")

    # ---- H7 关系抽取：等半径/同心成为约束（gate 的输入） ----
    sr = rep_p.solved
    eq = [c for c in (sr.constraints if sr else ())
          if c.type is ConstraintType.EQUAL_RADIUS]
    check("PF60K 的等半径孔两两成约束（C(4,2)=6 条起）", len(eq) >= 6,
          f"{len(eq)} 条")
    check("同轴特征之间抽出共线约束（同心圆不再被合并的连带结果）",
          sr is not None
          and any(c.type is ConstraintType.COLLINEAR for c in sr.constraints))
    check("阵列与子孔同心",
          sr is not None
          and any(c.type is ConstraintType.CONCENTRIC for c in sr.constraints))

    # ---- H8 待确认项不重复报（识别层与求解层共用一份清单） ----
    marker = re.compile(r"#(\d+)\.(\w+)")
    for name, rep in (("bracket 剖面图纸", rep_b), ("PF60K", rep_p)):
        where: dict[str, str] = {}
        dup: list[str] = []
        for q in rep.questions:
            for m in marker.finditer(q.detail):
                if m.group(0) in where:
                    dup.append(f"{m.group(0)}：{where[m.group(0)]} / {q.detail[:24]}")
                where[m.group(0)] = q.detail[:24]
        check(f"{name}：同一参数只被一条待确认项点名", not dup, str(dup))
    check("识别层末尾自动跑求解（rep.solved 非空）",
          rep_b.solved is not None and rep_p.solved is not None)

    # ---- H9 孔标注绑定（图上明写的「n~∅d 深h」压过投影反推） ----
    # 夹具（_write_callout_fixture）：圆 A 有孔壁虚线对（span 直接量到）、
    # 圆 B 主视图里不画轮廓对（只靠"同组同构"传播）、左视图 r3 全图无轮廓对
    # ⇒ 绑定成立但孔口位置无依据 ⇒ 按设计拒绝发射。三档一次全测到。
    from src.rebuild.features.callouts import (HoleBinding, bind_hole_groups,
                                               bound_hole_params)
    from src.rebuild.conventions.callout import HoleCallout
    d9, conv9, corr9, rep9 = _recognized(
        _write_callout_fixture(_FIXTURE_CALLOUT))
    cos = conv9.of_kind(ConvKind.CALLOUT)
    top9 = next(v.id for v in d9.views if v.resolved_type == ViewType.TOP)
    left9 = next((v.id for v in d9.views if v.resolved_type == ViewType.LEFT),
                 None)
    check("两条孔标注各归到唯一视图（俯视图/左视图独立各自归属）",
          len(cos) == 2
          and {c.value.text for c in cos} == {"2~∅10 深12", "3~∅6 深25"}
          and {c.view for c in cos} == {top9, left9},
          str([(c.value.text, c.view) for c in cos]))
    binds9 = bind_hole_groups(conv9, corr9, d9)
    uni9 = list({id(b): b for b in binds9.by_handle.values()}.values())
    b10 = next((b for b in uni9 if abs(b.radius - 5.0) < 1e-9), None)
    b3 = next((b for b in uni9 if abs(b.radius - 3.0) < 1e-9), None)
    check("「2~∅10 深12」半径严合绑上 2 个圆（数量与标注相符）",
          b10 is not None and len(b10.handles) == 2 and b10.count_ok,
          str(b10))
    check("span 由有轮廓对的圆读出（12 = 孔壁虚线对间距）、传播给全组",
          b10 is not None and b10.span is not None
          and abs(b10.span_len - 12.0) < 1e-9 and b10.propagated
          and b10.span_from in b10.handles, str(b10))
    check("「3~∅6 深25」图上只数到 1 个圆 ⇒ 照绑、只记账（不当闸门）",
          b3 is not None and not b3.count_ok and b3.span is None, str(b3))
    holes9 = [f for f in rep9.part.features if f.type.value == "hole"]
    check("两个绑定圆各建一条孔特征，无 span 的 r3 拒绝发射 ⇒ 共 2 条",
          len(holes9) == 2
          and all(abs(f.params["radius"].value - 5.0) < 1e-9
                  for f in holes9),
          str([(str(f.id), f.params.get("radius")) for f in
               rep9.part.features]))
    check("深度都按画出来的区间切（12 盲孔，不再按通孔切穿）",
          all(f.params["depth"].value is not None
              and abs(f.params["depth"].value - 12.0) < 1e-9
              and f.params["through"].value is False for f in holes9),
          str([(f.params.get("depth"), f.params.get("through"))
               for f in holes9]))
    check("span 来源圆 PROJECTION、同组传播圆降一档 CONVENTION（tier 可追）",
          sorted(f.params["axial_at"].method for f in holes9)
          == ["callout:group_span", "projection:outline_pair"],
          str([f.params["axial_at"].method for f in holes9]))
    check("类型由标注定：hole/ANNOTATED（annotation:hole_callout）",
          all(f.type.tier is Tier.ANNOTATED
              and f.type.method == "annotation:hole_callout" for f in holes9),
          str([(f.type.tier.name, f.type.method) for f in holes9]))
    md9 = rep9.questions.by_kind(OpenQuestion.MISSING_DIMENSION)
    check("r3「孔口位置未知」⇒ 拦路疑问（按设计拒绝，不按 0 起硬切）",
          len(md9) == 1 and "3~∅6 深25" in md9[0].detail
          and "孔口位置未知" in md9[0].detail,
          str([q.detail for q in md9]))
    cb9 = [a for a in rep9.questions.resolved
           if a.by == "recognize:callout_bind"]
    check("两条「找不到轮廓对」之疑由标注裁决（含无 span 的 r3）",
          len(cb9) == 2 and all("hole" in str(a.answer) for a in cb9),
          str([str(a.question.detail)[:40] for a in cb9]))
    check("被绑定的圆不再当分区依据（高度分解只记账、不消费）",
          any("孔标注绑定" in n and "不当分区依据" in n for n in rep9.notes),
          str([n for n in rep9.notes if "高度分解" in n]))
    check("孔标注夹具过 understand 全链不崩",
          isinstance(understand(str(_FIXTURE_CALLOUT)), tuple))
    # 第三条出路（夹具里没有）：未注深度且无 span ⇒ 通孔。图上明写「通孔」
    # 是 ANNOTATED，只靠制图惯例（不写深度即通孔）才是 CONVENTION 级。
    hc_thr = HoleCallout(text_ref="H9", text="2~∅8 (通孔)", count=2,
                         diameter=8.0, matched=("count:2", "kw:通孔"))
    p_thr, why_thr = bound_hole_params(
        HoleBinding(callout=hc_thr, handles=("A", "B"), radius=4.0,
                    count_ok=True), ("A",))
    check("未注深度且无 span ⇒ 通孔（明写「通孔」⇒ ANNOTATED）",
          not why_thr and p_thr["through"].value is True
          and p_thr["through"].tier is Tier.ANNOTATED
          and p_thr["axial_at"].value == 0.0, str(p_thr))
    hc_nd = HoleCallout(text_ref="H9b", text="2~∅8", count=2,
                        diameter=8.0, matched=("count:2",))
    p_nd, _ = bound_hole_params(
        HoleBinding(callout=hc_nd, handles=("A", "B"), radius=4.0,
                    count_ok=True), ("A",))
    check("未注深度、图上也没写「通孔」⇒ 按制图惯例（CONVENTION 级）",
          p_nd["through"].value is True
          and p_nd["through"].tier is Tier.CONVENTION
          and p_nd["through"].method == "convention:no_depth_means_through",
          str(p_nd))

    # ---- H10 孔口定位：同心材料分区顶面（§C6 第三段，4~∅10-7H 深25） ----
    # 轮廓对没读到 ⇒ 此前按设计"拒绝发射"（不许按 0 起硬切）。可孔口还在
    # 俯视材料分区里写着：与孔**同轴、半径更大**的材料分区，其顶面就是
    # 孔口面（孔从这块材料顶面下钻，深度按标注）。实测 YZYX 三个圆 2:1
    # ⇒ 取多数派 1686.25（= v15a 真值 z145 顶面的图纸系）。
    from types import SimpleNamespace

    from src.rebuild.features.callouts import (CalloutBindings,
                                               infer_callout_mouth_spans)
    from src.rebuild.model.geom import Axis3 as _A3, Point3 as _P3, \
        Vector3 as _V3
    from src.rebuild.views.correspondence import CylinderHint

    def _hint10(x, y, r, handle):
        ax = _A3(_P3(x, y, 0.0), _V3(0.0, 0.0, 1.0),
                 Claim(r, "projection:circle", Tier.PROJECTION, (handle,)))
        return CylinderHint(axis=ax, radius=r)

    def _corr10(hints):
        return SimpleNamespace(cylinders=lambda: [
            SimpleNamespace(mapping=SimpleNamespace(value=h)) for h in hints])

    def _zone10(role, hint, lo, hi):
        return SimpleNamespace(role=role, hints=(hint,), t_lo=lo, t_hi=hi)

    hc10 = HoleCallout(text_ref="H10", text="4~∅10-7H 深25", count=4,
                       diameter=10.0, depth=25.0, matched=("count:4",))
    holes10 = [_hint10(0, 0, 5, "k1"), _hint10(30, 0, 5, "k2"),
               _hint10(60, 0, 5, "k3")]
    b10 = HoleBinding(callout=hc10, handles=("k1", "k2", "k3"), radius=5.0,
                      count_ok=False)
    bd10 = CalloutBindings(by_handle={"k1": b10, "k2": b10, "k3": b10})
    plan10 = SimpleNamespace(zones=(
        _zone10("material", _hint10(0, 0, 6.5, "p1"), 1541.25, 1686.25),
        _zone10("material", _hint10(30, 0, 6.5, "p2"), 1541.25, 1686.25),
        _zone10("material", _hint10(60, 0, 6.5, "p3"), 1541.25, 1589.50)))
    nt10: list[str] = []
    n10 = infer_callout_mouth_spans(bd10, _corr10(holes10), plan10, nt10)
    check("三个圆 2:1 多数派 ⇒ 孔口取 1686.25、span 深 25（= z120..145）",
          n10 == 1 and abs(bd10.by_handle["k1"].span[0] - 1661.25) < 1e-9
          and abs(bd10.by_handle["k1"].span[1] - 1686.25) < 1e-9
          and bd10.by_handle["k1"].span_how == "zone:concentric_mouth",
          f"n={n10} span={bd10.by_handle['k1'].span}")
    check("全组 handle 同步换成新绑定（发射端按圆边查）",
          all(bd10.by_handle[h].span is not None for h in ("k1", "k2", "k3")))
    p10, why10 = bound_hole_params(bd10.by_handle["k1"], ("k1",))
    check("分区推断的 span：CONVENTION 级、method=zone:concentric_mouth",
          not why10 and p10["axial_at"].method == "zone:concentric_mouth"
          and p10["axial_at"].tier is Tier.CONVENTION
          and abs(p10["depth"].value - 25.0) < 1e-9, str(p10))
    b11 = HoleBinding(callout=hc10, handles=("k1", "k2"), radius=5.0,
                      count_ok=False)
    bd11 = CalloutBindings(by_handle={"k1": b11, "k2": b11})
    nt11: list[str] = []
    n11 = infer_callout_mouth_spans(bd11, _corr10(holes10[:2]),
                                    SimpleNamespace(zones=(
                                        _zone10("material",
                                                _hint10(0, 0, 6.5, "p1"),
                                                1541.25, 1686.25),
                                        _zone10("material",
                                                _hint10(30, 0, 6.5, "p2"),
                                                1541.25, 1589.50))), nt11)
    check("1:1 打平 ⇒ 不推、记账后维持拒绝发射（宁可少建不可错建）",
          n11 == 0 and bd11.by_handle["k1"].span is None
          and any("不构成多数" in s for s in nt11), str(nt11))
    b12 = HoleBinding(callout=hc10, handles=("k1",), radius=5.0,
                      count_ok=False)
    bd12 = CalloutBindings(by_handle={"k1": b12})
    n12 = infer_callout_mouth_spans(
        bd12, _corr10(holes10[:1]),
        SimpleNamespace(zones=(_zone10("material",
                                       _hint10(0, 0, 5.0, "self"),
                                       1541.25, 1686.25),)), [])
    check("同半径的同心圆是孔自己 ⇒ 不算孔口（防循环证据，H9 的 r3 由此守住）",
          n12 == 0 and bd12.by_handle["k1"].span is None)
    b13 = HoleBinding(callout=hc10, handles=("k1",), radius=5.0,
                      count_ok=False)
    bd13 = CalloutBindings(by_handle={"k1": b13})
    n13 = infer_callout_mouth_spans(
        bd13, _corr10(holes10[:1]),
        SimpleNamespace(zones=(_zone10("material",
                                       _hint10(0, 0, 6.5, "p1"),
                                       1589.50, 1600.0),)), [])
    check("分区厚度不够（顶面−深 < 分区底）⇒ 不是孔口面、不推",
          n13 == 0 and bd13.by_handle["k1"].span is None)

    # ---- H11 剖面补扫的跨视图支持门（非剖面视图的可见线佐证） ----
    # 缺口：剖面里"HATCH 边界水平线"可以只是后方可见轮廓（窗口区对面的筒壁）
    # 或平顶实体的顶面轮廓在切面上的投影——单剖面视图表达不足以断言"该段
    # 回转成实体"。YZYX 实锤（v15a 截面网格）：r145 [2604.3,2624.3]（塔帽
    # 顶）与 r140 [2629.3,2645.3] 在材料双探针里全过但为过发；俯视 V3 的
    # r145 可见 span 只覆盖盘 [2484.3,2504.3]。判据：add 段须被 ≥1 个非剖面
    # （无 HATCH，即不在 mats 里）子午帧的 visible span 覆盖 ≥50% 段长。
    import src.rebuild.features.axis_revolve as _ar

    fr_sec = SimpleNamespace(view_id="V1", u_axis="x", v_axis="z", p_axis="y")
    fr_top = SimpleNamespace(view_id="V3", u_axis="x", v_axis="y", p_axis="z")
    corr11 = SimpleNamespace(frames={"V1": fr_sec, "V3": fr_top})
    mats11 = {("x", "V1"): (None, 0.0)}           # V1 是剖面（有 HATCH）
    cand11 = SimpleNamespace(centre=_P3(0.0, 0.0, 0.0))
    seg_tower = _ar._BoreSeg(r=145.0, x0=2604.3, x1=2624.3, ax_probe=2614.3,
                             rad=145.0, handles=("h1",))
    seg_disc = _ar._BoreSeg(r=145.0, x0=2484.3, x1=2504.3, ax_probe=2494.3,
                            rad=145.0, handles=("h2",))
    table11 = {"V3": [(2484.3, 2504.3)]}          # 俯视只有盘的可见线
    _orig_ss = _ar._span_scan
    _ar._span_scan = lambda d, fr, dn, c, rn: (table11.get(fr.view_id, []), [])
    try:
        ok_tower = _ar._non_section_support(
            None, corr11, mats11, cand11, "x", seg_tower, {})
        ok_disc = _ar._non_section_support(
            None, corr11, mats11, cand11, "x", seg_disc, {})
        table11["V3"] = []
        ok_none = _ar._non_section_support(
            None, corr11, mats11, cand11, "x", seg_disc, {})
    finally:
        _ar._span_scan = _orig_ss
    check("非剖帧 span 不覆盖该段 ⇒ 拒（塔帽顶 r145 [2604.3,2624.3] 形态）",
          ok_tower is False)
    check("非剖帧 span 全覆盖 ⇒ 过（盘 r145 [2484.3,2504.3] 形态）",
          ok_disc is True)
    check("剖面帧（在 mats 里）不算支持票——空非剖 ⇒ 拒", ok_none is False)


    # ---- H12 轴向起点绑定（P1-A）：span 在图纸系，发射系可能要平移 ----
    # 通用性盲测 P0 的结论：7/7 held-out 件的孔/凸台都缺 axial_at ⇒ 发射器
    # 静默按 0 起（IMU 基体 y101..121，一个孔也没切中）。这一组的四条不变式：
    #   ① 轮廓对 span ⇒ axial_at（图纸系）；
    #   ② 回转体基体的轴向发射系从 0 起 ⇒ span 必须平移（否则法兰练习的
    #      Ø10 通孔落到 1786 之外，切出零厚度圆盘 = 静默不切）；
    #   ③ 棱柱基体的两套系重合 ⇒ 不平移；
    #   ④ 没有依据的盲孔/凸台 ⇒ 拦路，不许交给发射器按 0 起。
    from src.rebuild.features.recognizer import (
        _axis_shift,
        _base_emit_range,
        bind_axial_positions,
    )
    from types import SimpleNamespace as _NS

    def _frame12(vid, u_axis, u_span, v_axis, v_span, p_axis):
        spans = {u_axis: u_span, v_axis: v_span}
        return _NS(view_id=vid, u_axis=u_axis, v_axis=v_axis, p_axis=p_axis,
                   model_span=lambda a: spans.get(a))

    # 前视图 v=z 复刻法兰练习：图纸 z 1786.7..1806.7；俯视图给 x/y 跨度
    corr12 = _NS(frames={
        "V1": _frame12("V1", "x", (-40.0, 40.0), "z", (1786.706984, 1806.706984), "y"),
        "V0": _frame12("V0", "x", (-40.0, 40.0), "y", (-40.0, 40.0), "z"),
    })
    ev12 = ("b0",)

    def _rev_base12():
        return Feature(
            id=FeatureId(0),
            type=Claim(FeatureType.REVOLVE, "t", Tier.PROJECTION, ev12),
            params={
                "dir": Claim("z", "t", Tier.PROJECTION, ev12),
                "angle_deg": Claim(360.0, "t", Tier.PROJECTION, ev12),
                "radius_profile": Claim([(0.0, 40.0), (20.0, 40.0)], "t",
                                        Tier.PROJECTION, ev12),
                "origin": Claim(Point3(0.0, 0.0, 0.0), "t",
                                Tier.PROJECTION, ev12),
            },
            axis=Claim(Axis3(Point3(0.0, 0.0, 0.0), Vector3(0.0, 0.0, 1.0)),
                       "t", Tier.PROJECTION, ev12),
        )

    base_r = _rev_base12()
    check("回转体基体的轴向发射区间 0..20（origin 沿轴分量恒 0）",
          _base_emit_range(base_r, "z") == (0.0, 20.0),
          str(_base_emit_range(base_r, "z")))
    check("图纸系→发射系平移 = 0 − 1786.707（只沿自身轴）",
          abs(_axis_shift(base_r, corr12, "z") + 1786.706984) < 1e-6
          and _axis_shift(base_r, corr12, "x") == 0.0,
          f"dz={_axis_shift(base_r, corr12, 'z')}")

    def _hole12(fid, **params):
        return Feature(
            id=FeatureId(fid),
            type=Claim(FeatureType.HOLE, "t", Tier.PROJECTION, ("h1",)),
            params=params,
            axis=Claim(Axis3(Point3(10.0, 0.0, 0.0), Vector3(0.0, 0.0, 1.0)),
                       "t", Tier.PROJECTION, ("h1",)),
        )

    # ①+② span 读出的起点（图纸系 1786.707）必须平移到发射系 0
    part12 = Part(features=[
        base_r,
        _hole12(1, radius=Claim(5.0, "t", Tier.PROJECTION, ("h1",)),
                through=Claim(False, "t", Tier.PROJECTION, ("h1",)),
                depth=Claim(20.0, "t", Tier.PROJECTION, ("h1",)),
                axial_at=Claim(1786.706984, "projection:outline_pair_span",
                               Tier.PROJECTION, ("h1",))),
        # ③ 通孔无 span ⇒ 取基体材料端（发射系 0），不是图纸端 1786.7
        _hole12(2, radius=Claim(5.0, "t", Tier.PROJECTION, ("h2",)),
                through=Claim(True, "t", Tier.PROJECTION, ("h2",))),
    ])
    rep12 = _NS(questions=QuestionList(), notes=[])
    bind_axial_positions(part12, rep12, corr12)
    check("span 起点随回转体基体平移：1786.707 → 0（法兰练习 Ø10 通孔形态）",
          abs(part12.by_id(FeatureId(1)).params["axial_at"].value) < 1e-6,
          str(part12.by_id(FeatureId(1)).params["axial_at"]))
    check("通孔无 span ⇒ 取基体材料端 0（derived:through_base_span）",
          part12.by_id(FeatureId(2)).params["axial_at"].value == 0.0
          and part12.by_id(FeatureId(2)).params["axial_at"].method
          == "derived:through_base_span",
          str(part12.by_id(FeatureId(2)).params["axial_at"]))
    check("通孔补齐不报拦路（几何推论有依据）",
          not rep12.questions.by_kind(OpenQuestion.MISSING_DIMENSION),
          str(rep12.questions.items))

    # ③ 棱柱基体：origin 即图纸跨度下界 ⇒ 平移量 0、通孔锚 = 101（IMU 形态）
    base_p = Feature(
        id=FeatureId(0),
        type=Claim(FeatureType.BASE, "t", Tier.PROJECTION, ev12),
        params={
            "dir": Claim("y", "t", Tier.PROJECTION, ev12),
            "length": Claim(20.0, "t", Tier.PROJECTION, ev12),
            "profile": Claim([(40.0, 30.0)], "t", Tier.PROJECTION, ev12),
            "origin": Claim(Point3(2.0, 101.0, 2.0), "t",
                            Tier.PROJECTION, ev12),
        },
    )
    corr_p = _NS(frames={
        "V1": _frame12("V1", "x", (2.0, 42.0), "y", (101.0, 121.0), "z"),
        "V0": _frame12("V0", "x", (2.0, 42.0), "z", (2.0, 32.0), "y"),
    })
    check("棱柱基体：两套系重合（平移 0）",
          _axis_shift(base_p, corr_p, "y") == 0.0,
          str(_axis_shift(base_p, corr_p, "y")))
    part_p = Part(features=[
        base_p,
        # 轴沿基体方向 y（_hole12 固定给 +z，这里单独建）
        Feature(
            id=FeatureId(3),
            type=Claim(FeatureType.HOLE, "t", Tier.PROJECTION, ("h3",)),
            params={"radius": Claim(4.0, "t", Tier.PROJECTION, ("h3",)),
                    "through": Claim(True, "t", Tier.PROJECTION, ("h3",))},
            axis=Claim(Axis3(Point3(22.0, 0.0, 43.0), Vector3(0.0, 1.0, 0.0)),
                       "t", Tier.PROJECTION, ("h3",)),
        ),
    ])
    rep_p = _NS(questions=QuestionList(), notes=[])
    bind_axial_positions(part_p, rep_p, corr_p)
    check("棱柱基体通孔锚 = 基体材料低端 101（IMU y101..121 形态）",
          part_p.by_id(FeatureId(3)).params["axial_at"].value == 101.0,
          str(part_p.by_id(FeatureId(3)).params["axial_at"]))

    # ⑤ 通孔哨兵 axial_at=0.0（callouts 的"下界不拘"）也要换成真实锚：
    #    图纸原点落在材料内部/负半轴时，0.0 会把通孔切成半截
    part_s = Part(features=[
        base_p,
        Feature(
            id=FeatureId(5),
            type=Claim(FeatureType.HOLE, "t", Tier.PROJECTION, ("h5",)),
            params={"radius": Claim(4.0, "t", Tier.PROJECTION, ("h5",)),
                    "through": Claim(True, "convention:no_depth_means_through",
                                     Tier.CONVENTION, ("h5",)),
                    "axial_at": Claim(0.0, "convention:no_depth_means_through",
                                      Tier.CONVENTION, ("h5",))},
            axis=Claim(Axis3(Point3(22.0, 0.0, 43.0), Vector3(0.0, 1.0, 0.0)),
                       "t", Tier.PROJECTION, ("h5",)),
        ),
    ])
    rep_s = _NS(questions=QuestionList(), notes=[])
    bind_axial_positions(part_s, rep_s, corr_p)
    ax_s = part_s.by_id(FeatureId(5)).params["axial_at"]
    check("通孔哨兵 0.0 → 基体材料端 101（切穿语义不变、不再依赖原点巧合）",
          ax_s.value == 101.0
          and ax_s.method == "derived:through_base_span",
          str(ax_s))

    # ④ 盲孔无依据 ⇒ 拦路（发射器的 0 默认不是读数）
    part_b = Part(features=[
        base_p,
        Feature(
            id=FeatureId(4),
            type=Claim(FeatureType.HOLE, "t", Tier.PROJECTION, ("h4",)),
            params={"radius": Claim(4.0, "t", Tier.PROJECTION, ("h4",)),
                    "through": Claim(False, "t", Tier.PROJECTION, ("h4",)),
                    "depth": Claim(10.0, "t", Tier.PROJECTION, ("h4",))},
            axis=Claim(Axis3(Point3(22.0, 0.0, 43.0), Vector3(0.0, 1.0, 0.0)),
                       "t", Tier.PROJECTION, ("h4",)),
        ),
    ])
    rep_b = _NS(questions=QuestionList(), notes=[])
    bind_axial_positions(part_b, rep_b, corr_p)
    qb = rep_b.questions.by_kind(OpenQuestion.MISSING_DIMENSION)
    check("盲孔没有轴向起点 ⇒ 报拦路 MISSING_DIMENSION（不按 0 起）",
          "axial_at" not in part_b.by_id(FeatureId(4)).params
          and any("#4.axial_at" in q.detail for q in qb), str(qb))


    # ---- H13 轮廓视图选择（P1-B）：最薄视图没形状信息时换视图 ----
    # 通用性盲测 P0 的轴测量：三向跨度 x40 / y44 / z60，沿最薄 x 拉伸的
    # V2 环面积 2640 = 44×60 恰好铺满包围盒 ⇒ 基体是包围盒棱柱（105,600，
    # 金值 42,380.2，+149%）。判据只用图纸：最薄视图的**非矩形度**为 0
    # （环没有任何形状信息）时，改取非矩形度最大（≥10%）的视图作轮廓。
    # 这条不碰"最薄视图没有环"的情形——那是没读出来，不该拿别的视图猜。
    from src.rebuild.features import recognizer as _rec
    from types import SimpleNamespace as _NS13

    def _frame13(vid, p_axis):
        return _NS13(view_id=vid, p_axis=p_axis)

    def _choose13(ext, frames, fills):
        rep = _NS13(notes=[])
        orig = _rec._ring_fill
        _rec._ring_fill = lambda d, f: fills.get(f.view_id)
        try:
            out = _rec._choose_extrude_dir(None, frames, ext, rep)
        finally:
            _rec._ring_fill = orig
        return out, rep.notes

    f13 = {"V0": _frame13("V0", "z"), "V1": _frame13("V1", "y"),
           "V2": _frame13("V2", "x")}
    out13, notes13 = _choose13({"x": 40.0, "y": 44.0, "z": 60.0}, f13,
                               {"V0": 0.509, "V1": 0.167, "V2": 0.0})
    check("最薄 x 的 V2 是矩形 ⇒ 改取非矩形度最大的 V0 沿 z 拉伸（轴测量形态）",
          out13 == ("z", "projection:informative_view", "V0")
          and len(notes13) == 1 and "没有形状信息" in notes13[0],
          f"{out13} notes={notes13}")

    out13, notes13 = _choose13({"x": 203.3, "y": 51.0, "z": 44.0}, f13,
                               {"V0": 0.232, "V1": 0.326, "V2": 0.0})
    check("最薄视图本身有形状（bracket V0 非矩形度 0.232）⇒ 不换视图",
          out13 == ("z", "projection:thinnest_extent", None) and not notes13,
          f"{out13} notes={notes13}")

    out13, notes13 = _choose13({"x": 40.0, "y": 20.0, "z": 45.0}, f13,
                               {"V0": 0.0, "V1": 0.003, "V2": 0.0})
    check("其余视图全是矩形 ⇒ 没有可换的视图，维持最薄 y（IMU 形态）",
          out13 == ("y", "projection:thinnest_extent", None) and not notes13,
          f"{out13} notes={notes13}")

    out13, notes13 = _choose13({"x": 40.0, "y": 44.0, "z": 60.0}, f13,
                               {"V0": 0.509, "V1": 0.167, "V2": None})
    check("最薄视图**没有环** ⇒ 维持原行为（包围盒回退 + 拦路，不拿别视图猜）",
          out13 == ("x", "projection:thinnest_extent", None) and not notes13,
          f"{out13} notes={notes13}")

    # 集成锚：真实图纸上的基体选择（P1-B 转绿的那一刀）
    _d13, _c13, _co13, rep13 = understand(
        str(ROOT / "CAD" / "temp_output" / "轴测量.dxf"))
    base13 = next((x for x in rep13.part.features
                   if x.type.value == "base"), None)
    check("轴测量 基体沿 z 拉伸、轮廓取 V0 的 L 形环 864（不再是包围盒）",
          base13 is not None
          and base13.params["dir"].value == "z"
          and base13.params["dir"].method == "projection:informative_view"
          and base13.source_view == "V0"
          and abs(base13.params["profile"].value.signed_area() - 864.0) < 1e-6,
          f"{None if base13 is None else base13.params['dir']} "
          f"view={None if base13 is None else base13.source_view} "
          f"area={None if base13 is None else base13.params['profile'].value.signed_area()}")

    _d13b, _c13b, _co13b, rep13b = understand(
        str(ROOT / "CAD" / "temp_output" / "bracket_angker_三视图_v4.dxf"))
    base13b = next((x for x in rep13b.part.features
                    if x.type.value == "base"), None)
    check("bracket 基体仍沿最薄 z 取 V0（P1-B 不碰已对的靶子）",
          base13b is not None
          and base13b.params["dir"].value == "z"
          and base13b.params["dir"].method == "projection:thinnest_extent"
          and base13b.source_view == "V0",
          f"{None if base13b is None else base13b.params['dir']} "
          f"view={None if base13b is None else base13b.source_view}")

    # ---- H14 轮廓环基体的自轮廓排除（20180425 气缸前盖）----
    # 轮廓环基体的 φ155 由两段 r77.5 圆弧拼成（合计 191.6° ≥ 180°），
    # correspondence 会把它们聚成一个同轴圆柱 hint。若不排除，基体自己的
    # 轮廓线会变成一条 GUESS 孔 —— force 发射时布尔把基体切空（"特征 #6
    # 建完后没有实体"）。判据 = 弧心 + 半径都对上轮廓环上的弧；只对上
    # 半径不算（真孔可能与轮廓弧同半径但不同心）。
    from src.rebuild.features.recognizer import _base_outline as _base_outline14
    from src.rebuild.model.geom2d import (
        Point2 as _P2_14, Profile2 as _Prof14, ProfileSeg2 as _Seg14)
    from src.rebuild.views.correspondence import CylinderHint as _Hint14

    _b1_14, _b2_14 = profile_plane("z")
    _o14 = Point3(10.0, 20.0, 30.0)
    _base14 = Feature(
        id=FeatureId(0),
        type=Claim(FeatureType.BASE, "t", Tier.PROJECTION, ev12),
        params={
            "dir": Claim("z", "t", Tier.PROJECTION, ev12),
            "length": Claim(33.0, "t", Tier.PROJECTION, ev12),
            "profile": Claim(_Prof14(segments=(
                _Seg14(kind="arc", p1=_P2_14(0.0, 0.0), p2=_P2_14(1.0, 0.0),
                       center=_P2_14(5.0, -7.0), radius=77.5),
                _Seg14(kind="line", p1=_P2_14(1.0, 0.0), p2=_P2_14(0.0, 0.0)),
            )), "t", Tier.PROJECTION, ev12),
            "origin": Claim(_o14, "t", Tier.PROJECTION, ev12),
        },
    )
    _skip14 = _base_outline14(_base14)

    def _hint14(cx: float, cy: float, r: float):
        # hint 轴 = 轮廓平面上过 (cx, cy) 的竖直线（沿 z；沿 z 的位置无关）
        _o = _o14 + _b1_14 * cx + _b2_14 * cy + Vector3(0.0, 0.0, 60.0)
        return _Hint14(axis=Axis3(_o, Vector3(0.0, 0.0, 1.0)), radius=r)

    check("轮廓环上的弧（圆心+半径都对上）⇒ 排除，不变成 GUESS 孔",
          _skip14 is not None and _skip14(_hint14(5.0, -7.0, 77.5)) is True,
          str(_skip14 and _skip14(_hint14(5.0, -7.0, 77.5))))
    check("同半径不同心 / 同心不同半径 ⇒ 不排除（真孔保留）",
          _skip14(_hint14(5.0, 0.0, 77.5)) is False
          and _skip14(_hint14(5.0, -7.0, 70.0)) is False,
          f"{_skip14(_hint14(5.0, 0.0, 77.5))} "
          f"{_skip14(_hint14(5.0, -7.0, 70.0))}")

    # ---- H15 图面符号圆不进化：圆心必须在视图 bbox 内（20180425）----
    # 图纸右下角的表面粗糙度符号里有一个 r1.684 圆，视图检测器把它并进了
    # V1 的证据表（但不在 V1 的 bbox 里），圆柱通道据此建了一个贯穿小孔。
    # 判据只用视图自己的 bbox：特征圆的圆心必在视图轮廓之内。
    from src.rebuild.evidence.model import (
        Evidence as _Ev15, Kind as _Kind15)
    from src.rebuild.model.geom2d import (
        Point2 as _P2_15, Circle2 as _C15, BBox2 as _B15)
    from src.rebuild.views.correspondence import (
        _center_in_view as _civ15, _circle_edges_of as _ceo15)

    _v15 = View(id="V1", evidence=["c1", "c2"],
                bbox=_B15(0.0, 0.0, 100.0, 100.0))
    _idx15 = {
        "c1": _Ev15(handle="c1", kind=_Kind15.EDGE,
                    geom=_C15(_P2_15(50.0, 50.0), 10.0),
                    role=Claim(Role.VISIBLE, "t", Tier.GUESS)),
        "c2": _Ev15(handle="c2", kind=_Kind15.EDGE,
                    geom=_C15(_P2_15(150.0, 50.0), 1.684),
                    role=Claim(Role.VISIBLE, "t", Tier.GUESS)),
    }
    _edges15, _ = _ceo15(None, _idx15, _v15)
    check("视图 bbox 内的圆照常进通道；bbox 外的符号圆（r1.684）被挡下",
          [h for h, _, _ in _edges15] == ["c1"]
          and _civ15(_P2_15(100.5, 50.0), _v15.bbox)
          and not _civ15(_P2_15(150.0, 50.0), _v15.bbox),
          str(_edges15))


# ---- 阶段 4：汇流（理解层；发射层要 OCC/SW，见 emit 自己的 --demo） ----

_FIXTURES = {
    "block_3view": "test_simple/block_3view.dxf",
    "plate_100x60": "test_simple/plate_100x60.dxf",
    "l_bracket": "test_simple/l_bracket.dxf",
    "flange_d80": "test_simple/flange_d80.dxf",
    "图形练习": "图形练习.dxf",
    "法兰练习": "法兰练习.dxf",
}


def _fixture(name: str) -> Path:
    return ROOT / "CAD" / _FIXTURES[name]


def test_pipeline() -> None:
    section("I. 汇流（阶段 4，理解层）")

    # ---- I1 六个回归用例逐张跑通（读→…→特征树），不在理解层抛异常 ----
    trees: dict[str, Any] = {}
    for name in _FIXTURES:
        p = _fixture(name)
        if not p.exists():
            check(f"{name} 存在", False, str(p))
            continue
        d, _conv, _corr, rep = understand(p)
        trees[name] = rep
        check(f"{name} 得出特征树", rep.part is not None)
    # 单视图：看得见的照常量，看不见的降成 GUESS 并拦路 —— 既不装作知道，
    # 也不因为缺一维就把整张图丢掉（旧管线在此处直接当已知量用）
    pt = trees["plate_100x60"]
    check("plate_100x60 单视图仍认出轮廓 100×60 + 两个 Ø10 孔",
          len(pt.part.features) == 3
          and pt.part.features[0].params["length"].tier is Tier.GUESS,
          str([(str(f.id), f.type.value) for f in pt.part.features]))
    check("厚度未知 ⇒ 拦路的缺尺寸待确认项",
          any(q.kind is OpenQuestion.MISSING_DIMENSION for q in pt.questions),
          str([q.kind.value for q in pt.questions]))

    # ---- I2 block_3view：树与黄金值**结构**一致 ----
    rep = trees["block_3view"]
    base = rep.part.features[0]
    prof = base.params["profile"].value
    ext = profile_span(prof)
    check("基体 100×60 沿 y 拉伸 30（= 黄金 bbox 100/30/60）",
          base.params["dir"].value == "y"
          and base.params["length"].value == 30.0
          and ext == (60.0, 100.0),          # dir=y 时平面基 (z,x) ⇒ 60×100
          f"{ext} {prof}")
    holes = [f for f in rep.part.features if f.type.value == "hole"]
    check("4 个 r5 孔（两块视图各 2 个）",
          len(holes) == 4 and all(abs(f.params["radius"].value - 5.0) < 1e-9
                                  for f in holes), str(len(holes)))
    zs = sorted(round(f.axis.value.origin.x) for f in holes
                if round(f.axis.value.direction.z) == 1)
    ys = sorted(round(f.axis.value.origin.x) for f in holes
                if round(f.axis.value.direction.y) == 1)
    check("沿 z 的两孔在 x=30/70", zs == [30, 70], str(zs))
    check("沿 y 的两孔在 x=30/70", ys == [30, 70], str(ys))
    check("四孔都是通孔（无底轮廓 ⇒ 惯例取通孔，备选盲孔）",
          all(f.params["through"].value is True for f in holes)
          and all(False in f.params["through"].alternatives for f in holes))

    # ---- I3 树能**算回**黄金体积（这才是"解释得通"的硬判据） ----
    import math
    def _thick(axis_name: str) -> float:
        """基体在某轴上的材料厚度（与 recognizer._material_extent 同口径）。"""
        b1, b2 = {"x": ("y", "z"), "y": ("z", "x"), "z": ("x", "y")}[
            base.params["dir"].value]
        w1, w2 = profile_span(base.params["profile"].value)
        return {base.params["dir"].value: base.params["length"].value,
                b1: w1, b2: w2}[axis_name]

    box = 100.0 * 30.0 * 60.0
    cut = sum(math.pi * (f.params["radius"].value ** 2)
              * _thick("z" if round(f.axis.value.direction.z) == 1 else "y")
              for f in holes)
    overlap = 2 * 16 * 5.0 ** 3 / 3.0          # 沿 y 与沿 z 的孔互相穿过
    vol = box - cut + overlap
    gold = 167196.2
    check(f"树算出的体积 {vol:.1f} ≈ 黄金 {gold}（±1）",
          abs(vol - gold) <= 1.0, f"{vol:.2f}")

    # ---- I4 rebuild()：发射失败不算理解失败，两类结果分开记账 ----
    r = rebuild(ROOT / "CAD" / "test_simple" / "block_3view.dxf")
    check("不给 --step/--sldprt 时不发模型、也不报错",
          r.ok and r.step is None and r.sldprt is None and not r.errors,
          str(r.errors))
    check("未知投影制**不**算拦路项（镜像已在视图坐标系里处理）",
          all(q.kind is not OpenQuestion.UNKNOWN_PROJECTION
              for q in r.blocking()),
          str([q.kind.value for q in r.blocking()]))
    js = json.loads(r.to_json())
    check("to_json 可解析且特征数一致",
          len(js["features"]) == len(r.part.features)
          and js["source"].endswith("block_3view.dxf"))

    # ---- I5 发射闸门：**类型未定也算拦路**（发射器据此拒绝） ----
    # 这是"知道该拒绝"的硬判据：孔还是凸台没定的特征，radius/depth 却可能是
    # 实打实带证据的 —— 只查参数会让闸门形同虚设（实测曾如此）。
    check("block_3view 的孔类型未定 ⇒ 报成拦路的歧义",
          any(q.kind is OpenQuestion.AMBIGUOUS_FEATURE
              and "#1.type" in q.detail for q in r.blocking()),
          str([q.detail[:40] for q in r.blocking()]))
    r2 = rebuild(ROOT / "CAD" / "test_simple" / "block_3view.dxf",
                 step=ROOT / "CAD" / "temp_output" / "_never.step")
    check("有拦路项时默认**不发射**（并说明为什么、怎么放行）",
          r2.step is None and not r2.errors
          and any("force" in n for n in r2.notes),
          str(r2.notes))

    # ---- I6 回转体基体上的孔也要判出通孔（flange_d80 曾整批漏判） ----
    f80 = trees["flange_d80"]
    holes80 = [f for f in f80.part.features if f.type.value == "hole"]
    r8 = [f for f in holes80 if abs(f.params["radius"].value - 4.0) < 1e-9]
    check("flange_d80 五个孔（Ø40 中心孔 + 四个 Ø8）都挂上了 through",
          len(holes80) == 5 and len(r8) == 4
          and all("through" in f.params for f in holes80),
          str([(str(f.id), sorted(f.params)) for f in holes80]))
    pat = next((f for f in f80.part.features if f.type.value == "pattern"), None)
    check("阵列中心记在 placement 上（发射器即从此取，不再另有 center 参数）",
          pat is not None and "center" not in pat.params
          and isinstance(pat.placement.value, Point3),
          str(pat.params) if pat else "没有阵列特征")

    # ---- I7 发射器里**不碰 SW/OCC 的那部分**逻辑（阶段 4） ----
    # `sw_builder` 只在 `_connect()` 里 import pywin32，模块本身是纯的 ⇒
    # 阵列覆盖判据、克隆标记、特征命名、缺参记账全都能在这里验，
    # 不必等 SW 在跑（那部分归 `run_rebuild_acceptance.py --sw`）。
    import contextlib
    import io

    from .emit import sw_builder as SWB

    # ① 阵列实例已被逐个孔占掉 ⇒ 不再重复发射（不判就会在同一处切两刀，
    #    SW 的 `FeatureCut3` 返回 None，整棵树发射失败 —— flange_d80 实测死在这）
    plan = SWB.pattern_plan(pat, f80.part)
    covered_ids = {str(q.id) for q in f80.part.features if q.type.value == "hole"}
    check("flange_d80 的 4 处阵列实例里 3 处已被逐个孔建出 ⇒ 阵列不再新建几何",
          not plan.positions and len(plan.covered) == 3
          and set(plan.covered) <= covered_ids,
          f"positions={len(plan.positions)} covered={plan.covered}")

    # ② 反过来：没被占掉的实例必须照发（否则就是静默少建）
    part = Part()
    part.add(Feature(
        id=FeatureId(0), type=Claim(FeatureType.REVOLVE, "t", Tier.GUESS),
        params={"angle_deg": Claim(360.0, "t", Tier.GUESS),
                "dir": Claim("z", "t", Tier.GUESS),
                "radius_profile": Claim([(0.0, 50.0), (10.0, 50.0)], "t", Tier.GUESS)},
        axis=Claim(Axis3(Point3(0, 0, 0), Vector3(0, 0, 1)), "t", Tier.GUESS)))
    part.add(Feature(
        id=FeatureId(1), type=Claim(FeatureType.HOLE, "t", Tier.GUESS),
        params={"radius": Claim(4.0, "t", Tier.GUESS),
                "through": Claim(True, "t", Tier.GUESS),
                "axial_at": Claim(0.0, "t", Tier.GUESS)},
        axis=Claim(Axis3(Point3(35.0, 0.0, 0.0), Vector3(0, 0, 1)), "t", Tier.GUESS),
        depends_on=[FeatureId(0)]))
    part.add(Feature(
        id=FeatureId(2), type=Claim(FeatureType.PATTERN, "t", Tier.GUESS),
        params={"kind": Claim("circular", "t", Tier.GUESS),
                "count": Claim(6, "t", Tier.GUESS),
                "child": Claim(1, "t", Tier.GUESS),
                "start_deg": Claim(0.0, "t", Tier.GUESS)},
        placement=Claim(Point3(0.0, 0.0, 0.0), "t", Tier.GUESS),
        depends_on=[FeatureId(0), FeatureId(1)]))
    p2 = SWB.pattern_plan(part.features[2], part)
    r_first = (p2.positions[0] - Point3(0.0, 0.0, 0.0)).norm if p2.positions else 0.0
    check("无人覆盖的阵列照发 5 个实例，且都落在分布圆 r35 上",
          len(p2.positions) == 5 and not p2.covered
          and all(abs((q - Point3(0.0, 0.0, 0.0)).norm - 35.0) < 1e-9
                  for q in p2.positions)
          and abs(r_first - 35.0) < 1e-9,
          f"positions={len(p2.positions)} 首个半径={r_first:.3f}")

    # ③ 克隆要能被认出来：SW 树里克隆的切除名字带 `p` 后缀，否则与原件重名
    ghost = SWB._clone_at(part.features[1], Point3(0.0, 35.0, 0.0), Vector3(0, 0, 1))
    check("阵列克隆与原件分得开（判据是轴上来源标记 pattern:rotate）",
          SWB._is_clone(ghost) and not SWB._is_clone(part.features[1]))

    class _Named:                      # 冒充 SW 特征对象，只看它被起了什么名
        pass

    fake = _Named()
    SWB._name_feature(fake, ghost, "Cut")
    SWB._name_feature(_Named(), part.features[1], "Boss")
    check("克隆命名带 p 后缀（Cut1p vs Cut1）⇒ SW 树能与特征树逐条对",
          str(fake.Name) == f"Cut{ghost.id}p", str(fake.Name))

    # ④ 缺 `axial_at` 不许静默：0 是默认值不是读数，必须留一行账
    #    （实测代价：bracket 的凸台全从 z=0 长出、伸出基体 2mm，bbox 46 vs 基准 44）
    boss_no_ax = Feature(
        id=FeatureId(9), type=Claim(FeatureType.BOSS, "t", Tier.GUESS),
        params={"radius": Claim(5.0, "t", Tier.GUESS),
                "height": Claim(3.0, "t", Tier.GUESS)},
        axis=Claim(Axis3(Point3(0, 0, 0), Vector3(0, 0, 1)), "t", Tier.GUESS))
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        t0 = SWB._axial_at(boss_no_ax)
    check("boss 没给 axial_at ⇒ 按 0 起但**留账**（不静默）",
          t0 == 0.0 and "没有 axial_at" in buf.getvalue(), buf.getvalue().strip())
    buf2 = io.StringIO()
    with contextlib.redirect_stdout(buf2):
        t0b = SWB._axial_at(part.features[1])          # 这个孔带了 axial_at=0
    check("给了 axial_at 就照读数走、不打账",
          t0b == 0.0 and buf2.getvalue() == "",
          f"{buf2.getvalue().strip()!r} {part.features[1].params['axial_at']}")

    # ---- I8 发射后自检：模型 bbox vs 图纸跨度（P1-C，2026-10-17） ----
    # 通用性盲测的静默错误里，轴测量是"多出的材料没图纸依据"：r20 半圆槽
    # 被跨视图对应读成凸台，模型 x 向比图纸宽 20mm。判据只用两块 ——
    # **图纸各轴跨度**（视图 span 并集，绝对位置不比）与**建出来的 bbox 尺寸**。
    # 回转体半径由视图圆弧直接读出，给它一条包络豁免：PF60K 的 Ø80 盘边只
    # 在四个倒角缺口处画了 r40 短弧，俯视图方框只有 60 —— 不豁免就误杀 9 绿。
    from types import SimpleNamespace as _NS8

    from src.rebuild.model.questions import QuestionList as _QL8
    from src.rebuild.pipeline import (RebuildResult, _extent_selfcheck,
                                      _revolve_sizes, drawing_extents,
                                      extent_questions)

    def _understand8(rel: str):
        p8 = ROOT / rel
        return understand(p8) if p8.exists() else None

    u8 = _understand8("CAD/temp_output/轴测量.dxf")
    if u8 is not None:
        _d8, _c8, corr8, rep8 = u8
        dr8 = drawing_extents(corr8)
        check("轴测量图纸跨度尺寸 40/44/60",
              all(abs((dr8[a][1] - dr8[a][0]) - v) < 0.01
                  for a, v in (("x", 40.0), ("y", 44.0), ("z", 60.0))),
              str({a: round(v[1] - v[0], 2) for a, v in dr8.items()}))
        q8 = extent_questions(rep8.part, (60.0, 44.0, 60.0), corr8)
        check("x 向发射 60 > 图纸 40 ⇒ 一条 INCONSISTENT_EXTENT 拦路疑问",
              len(q8) == 1 and q8[0].kind is OpenQuestion.INCONSISTENT_EXTENT
              and "X 向" in q8[0].detail,
              str([q.detail[:70] for q in q8]))
        check("同一棵树按图纸尺寸发射 ⇒ 不报（判据只看超量，不看树像不像）",
              not extent_questions(rep8.part, (40.0, 44.0, 60.0), corr8))
        check("容差 max(1mm, 0.5%)：x 超 0.9 不报、超 1.1 报",
              not extent_questions(rep8.part, (40.9, 44.0, 60.0), corr8)
              and len(extent_questions(rep8.part, (41.1, 44.0, 60.0),
                                       corr8)) == 1)

        # 落地行为：非 force 时连文件一起撤回；force 时保留供诊断
        tmp8 = ROOT / "CAD" / "temp_output" / "_selftest_extent.step"
        tmp8.parent.mkdir(parents=True, exist_ok=True)
        tmp8.write_text("x", encoding="utf-8")
        res8 = RebuildResult(source=ROOT / "x.dxf")
        res8.report = _NS8(part=rep8.part, questions=_QL8())
        res8.step = tmp8
        res8.emitted_extents = (60.0, 44.0, 60.0)
        _extent_selfcheck(res8, rep8.part, corr8, force=False)
        check("非 force：自检判矛盾 ⇒ 删掉刚写出的模型、step 置 None、疑问拦路",
              res8.step is None and not tmp8.exists() and bool(res8.blocking()),
              f"step={res8.step} exists={tmp8.exists()}")
        tmp8.write_text("x", encoding="utf-8")
        res8b = RebuildResult(source=ROOT / "x.dxf")
        res8b.report = _NS8(part=rep8.part, questions=_QL8())
        res8b.step = tmp8
        res8b.emitted_extents = (60.0, 44.0, 60.0)
        _extent_selfcheck(res8b, rep8.part, corr8, force=True)
        check("force：模型保留（供诊断），疑问照样入册",
              res8b.step == tmp8 and tmp8.exists() and bool(res8b.blocking()))
        tmp8.unlink(missing_ok=True)

    _d8p, _c8p, corr8p, rep8p = understand(_fixture("plate_100x60"))
    check("单视图图纸没有 z 向跨度 ⇒ 该轴不参与自检",
          "z" not in drawing_extents(corr8p)
          and not extent_questions(rep8p.part, (100.0, 60.0, 999.0), corr8p),
          str(drawing_extents(corr8p)))

    u8f = _understand8("CAD/temp_output/pf60k_闭环_三视图_20260817.dxf")
    if u8f is not None:
        _df8, _cf8, corrf, repf = u8f
        drf = drawing_extents(corrf)
        revf = _revolve_sizes(repf.part)
        check("PF60K 图纸 y 跨度只有 60，回转体半径包络给到 80",
              abs((drf["y"][1] - drf["y"][0]) - 60.0) < 0.01
              and abs(revf.get("y", 0.0) - 80.0) < 0.01,
              f"drawn={drf.get('y')} "
              f"rev={ {k: round(v, 2) for k, v in revf.items()} }")
        check("PF60K 按 80×80×96.9 发射 ⇒ 包络解释得通，不报（9 绿不被误杀）",
              not extent_questions(repf.part, (80.0, 80.0, 96.9), corrf))
        check("同一棵树若 z 向硬长到 120 ⇒ 仍报（包络不是万能豁免）",
              any(q.detail.startswith("Z 向")
                  for q in extent_questions(repf.part, (80.0, 80.0, 120.0),
                                            corrf)))

    u8b = _understand8("CAD/temp_output/bracket_angker_三视图_v4.dxf")
    if u8b is not None:
        _db8, _cb8, corrb, repb = u8b
        check("bracket 按图纸跨度 203.3/51/44 发射 ⇒ 不报（9 绿回归锚）",
              not extent_questions(repb.part, (203.3, 51.0, 44.0), corrb))


# ============ J. 轮廓环提取（views/ring） ============

def test_ring() -> None:
    """轮廓环提取（views/ring.py）——锚今天落地的移植与三处修复。

    运行序**必须**：分离 → 定性 → 提环（section 守卫依赖 is_section
    ⇔ 定性结果）——这里的 helper 与 ring.py 冒烟的 _main 同序。
    """
    section("J. 轮廓环提取（views/ring）")
    simple = ROOT / "CAD" / "test_simple"
    tmp = ROOT / "CAD" / "temp_output"

    def ring_of(path, vid):
        d = read_dxf(path)
        detect_views(d)
        type_views(d)
        v = next(v for v in d.views if v.id == vid)
        return extract_ring(d, v)

    def invariants(tag, r):
        g = r.ring
        check(f"{tag} 有环", g is not None, r.note or "无")
        if g is None:
            return
        n = len(g.segs)
        check(f"{tag} 段链闭合",
              all(g.segs[i].p2 == g.segs[(i + 1) % n].p1 for i in range(n)))
        check(f"{tag} 面积为正", g.area > 0, f"{g.area}")
        check(f"{tag} coverage≥0.75", min(g.coverage) >= 0.75, str(g.coverage))

    # J1 L 形轮廓（凹角非矩形——步骤 C 变绿的靶子；旧管线逐字复现）
    r = ring_of(simple / "l_bracket.dxf", "V0")
    invariants("l_bracket V0", r)
    if r.ring is not None:
        check("l_bracket 面积 = 60×60−50×50 = 1100",
              abs(r.ring.area - 1100.0) < 1e-6, f"{r.ring.area}")
        check("l_bracket 6 段（含凹角）", len(r.ring.segs) == 6,
              str(len(r.ring.segs)))

    # J2 矩形靶子（环提取的正确性基线，防回归）
    for path, vid, want in ((simple / "block_3view.dxf", "V0", 3000.0),
                            (simple / "block_3view.dxf", "V1", 6000.0),
                            (simple / "block_3view.dxf", "V2", 1800.0),
                            (simple / "plate_100x60.dxf", "V0", 6000.0),
                            (ROOT / "CAD" / "法兰练习.dxf", "V1", 1600.0)):
        r = ring_of(path, vid)
        invariants(f"{path.name}/{vid}", r)
        if r.ring is not None:
            check(f"{path.name}/{vid} 面积 = {want}",
                  abs(r.ring.area - want) < 1e-6, f"{r.ring.area}")

    # J3 三角形侧视图（分量守卫放宽到 <3 的锚：四棱锥侧投影）
    for vid in ("V1", "V2"):
        r = ring_of(ROOT / "CAD" / "图形练习.dxf", vid)
        invariants(f"图形练习/{vid}", r)
        if r.ring is not None:
            check(f"图形练习/{vid} 三角形面积 1800",
                  abs(r.ring.area - 1800.0) < 1e-6, f"{r.ring.area}")
            check(f"图形练习/{vid} 3 段", len(r.ring.segs) == 3,
                  str(len(r.ring.segs)))
    r = ring_of(ROOT / "CAD" / "图形练习.dxf", "V0")
    check("图形练习/V0 底面正方形 3600",
          r.ring is not None and abs(r.ring.area - 3600.0) < 1e-6,
          f"{r.ring.area if r.ring else r.note}")

    # J4 纯圆视图让位（note 次序锚：圆是 2 顶点组件 ⇒ 候选池必空，
    # has_lines 判定必须在 pool 判定之前，否则错报 no_ring_found）
    for path in (simple / "flange_d80.dxf", ROOT / "CAD" / "法兰练习.dxf"):
        r = ring_of(path, "V0")
        check(f"{path.name}/V0 纯圆视图让位",
              r.ring is None and r.note == "circles_only_view", r.note)

    # J5 bracket 侧视图 2244 满矩形——三处修复的联合锚：
    #   · 缺口横/竖线 26 条中 21/5 条是 hidden ⇒ 若 HIDDEN 入图，
    #     遍历拐进缺口线簇拼出 1662 伪环（剖面图纸实测）
    #   · 面环自交淘汰须与面积比较同层（否则自交大环把干净环压死）
    r = ring_of(tmp / "bracket_angker_三视图_v4.dxf", "V2")
    invariants("bracket 三视图 V2", r)
    if r.ring is not None:
        check("bracket 三视图 V2 面积 = 51×44 = 2244（非伪缺口环）",
              abs(r.ring.area - 2244.0) < 0.01, f"{r.ring.area}")
    # 剖面图纸（融合投影版）同名视图：已回到矩形量级，
    # 剩 2244−2241.58 = 2.42 未收敛（等步骤 E 专项），先用容差锁住
    # "不许退回 1662 伪环"
    r = ring_of(tmp / "bracket_angker_图纸_20260922_剖面图.dxf", "V2")
    invariants("bracket 剖面图 V2", r)
    if r.ring is not None:
        check("bracket 剖面图 V2 为矩形量级（±3，不许退回伪缺口环）",
              abs(r.ring.area - 2244.0) < 3.0, f"{r.ring.area}")

    # J6 剖视图让位（section 守卫——步骤 F 的排除契约）
    d = read_dxf(tmp / "bracket_angker_图纸_20260922_剖面图.dxf")
    detect_views(d)
    type_views(d)
    secs = [v for v in d.views if v.id in ("V3", "V4", "V5")]
    for v in secs:
        r = extract_ring(d, v)
        check(f"剖面图纸 {v.id} 剖视图让位",
              r.ring is None and r.note == "section_view", r.note)

    # J7 顶点胶合兜底（P1-B）：长边端点间 0.01~0.5mm 微缝落在 SNAP 网格
    #    两侧 ⇒ raw/welded 的度 1 修剪把整条链级联删掉。胶合**只在两遍都
    #    没过门时**跑——已成功的视图结果必须逐位不变（v15 误焊教训的边界）。
    from src.rebuild.views import ring as _rg

    # 合成正方形：左下角断 0.02mm（v0 与 v4 两个顶点，跨越 SNAP 网格）
    vp = {0: (0.0, 0.0), 1: (100.0, 0.0), 2: (100.0, 100.0),
          3: (0.0, 100.0), 4: (0.02, 0.0)}
    es = [_rg._E("L", 0, 1), _rg._E("L", 1, 2),
          _rg._E("L", 2, 3), _rg._E("L", 3, 4)]
    check("0.02mm 断口：raw 提不出环（度 1 修剪级联）",
          _rg._one_pass(es, vp, {}) is None)
    gvp, ges = _rg._glue(es, vp)
    gp = _rg._one_pass(ges, gvp, {})
    check("胶合把 0.02mm 断口并上 ⇒ 100×100 闭环",
          gp is not None and abs(gp.area - 10000.0) < 1e-6,
          f"{None if gp is None else gp.area}")
    check("胶合保持边数/边序（micro_len 的 eid 下标仍有效）",
          len(ges) == len(es), f"{len(ges)} vs {len(es)}")

    # 真实锚：D79307（P0 的 no_ring_found 靶子，35×20×40 拱形件）
    d79 = read_dxf(tmp / "D79307A264FCA6D8EC32E95B1B11BDBD.dxf")
    detect_views(d79)
    type_views(d79)
    r79 = {v.id: extract_ring(d79, v) for v in d79.views}
    # v0.6.45：胶合先跑**有界**版（簇直径 ≤ GLUE_CLOSE），数值随之更新——
    # 无界版靠 0.5mm 传递合并救环，簇可跨数毫米，代表位拉长边（V1 底脚
    # 3.7mm 斜线抄近路即此）。有界版 V1 262.00（金值剖面 263.58）、V0 697.55。
    # 再加 GLUE_COCIRC 后 V1 261.94：r1.4 角部两端点（相距 0.25mm）不再
    # 被并，环不再沿同一圆折返出 7.85° 尖刺（自交 ⇒ 发射器判面无效）。
    check("D79307 V1 raw/welded 都无环 ⇒ 有界胶合救回 261.94",
          r79["V1"].raw is None and r79["V1"].welded is None
          and r79["V1"].ring is not None
          and r79["V1"].ring.rule == "glued"
          and abs(r79["V1"].ring.area - 261.93785) < 0.01,
          f"{r79['V1'].note} "
          f"{None if r79['V1'].ring is None else r79['V1'].ring.area}")
    check("D79307 V0 raw 环 356.8 覆盖率不足 ⇒ 有界胶合救回 697.55",
          r79["V0"].raw is not None
          and abs(r79["V0"].raw.area - 356.8) < 0.1
          and r79["V0"].ring is not None
          and r79["V0"].ring.rule == "glued"
          and abs(r79["V0"].ring.area - 697.5506) < 0.01,
          f"raw={None if r79['V0'].raw is None else r79['V0'].raw.area} "
          f"ring={None if r79['V0'].ring is None else r79['V0'].ring.area}")
    # 有界胶合的破坏性证明：0/1 相距 0.4、1/2 相距 0.4（A—C 0.8 > cap）。
    # 无界模式把三个顶点并进同一簇（A、C 代表位相同）；有界模式拒绝
    # "合并后直径超过 GLUE_CLOSE"的第二跳，A 与 C 保持分离。
    vpc = {0: (0.0, 0.0), 1: (0.4, 0.0), 2: (0.8, 0.0)}
    esc = [_rg._E("L", 0, 1), _rg._E("L", 1, 2)]
    gv_all, _ = _rg._glue(esc, vpc)
    gv_cap, _ = _rg._glue(esc, vpc, cap=_rg.GLUE_CLOSE)
    check("有界胶合：链式合并不得越过簇直径上限（0.4+0.4 > 0.5）",
          gv_all[0] == gv_all[2] and gv_cap[0] != gv_cap[2],
          f"all 同簇={gv_all[0] == gv_all[2]} cap 同簇={gv_cap[0] == gv_cap[2]}")
    # 同一圆上跨弧端点禁并（GLUE_COCIRC）：把同一圆上相距 0.25mm 的
    # 两个弧端点并成一簇 = 塌掉其间真实弧长，环会在该圆上折返出尖刺。
    # 对照组：不同圆上的端点相距同样 0.25mm 照常合并（禁并只针对同圆）。
    th = 0.18
    qp = {0: (1.4, 0.0),
          1: (1.4 * math.cos(th), 1.4 * math.sin(th)),
          2: (0.0, 1.4),
          3: (1.4 * math.cos(1.0), 1.4 * math.sin(1.0)),
          4: (1.65, 0.0),
          5: (1.65, 1.0)}
    ep = [_rg._E("A", 0, 2, cx=0.0, cy=0.0, r=1.4),
          _rg._E("A", 1, 3, cx=0.0, cy=0.0, r=1.4),
          _rg._E("A", 4, 5, cx=0.25, cy=0.0, r=1.4)]
    gvp, _ = _rg._glue(ep, qp, cap=_rg.GLUE_CLOSE)
    check("有界胶合：同一圆（r1.4）上相距 0.25mm 的两弧端点不得合并",
          gvp[0] != gvp[1], f"0/1 同簇={gvp[0] == gvp[1]}")
    check("有界胶合：不同圆上的端点仍按距离合并（禁并只针对同圆）",
          gvp[0] == gvp[4], f"0/4 同簇={gvp[0] == gvp[4]}")
    check("D79307 V2 raw 已过门 ⇒ 胶合不跑（glued 诊断恒 None）",
          r79["V2"].ring is not None and r79["V2"].ring.rule == "raw"
          and r79["V2"].glued is None,
          f"{None if r79['V2'].ring is None else r79['V2'].ring.rule} "
          f"glued={r79['V2'].glued}")

    # 破坏性证明：raw 已过门的视图根本不会调用 _glue
    _orig_glue = _rg._glue

    def _boom(*a, **k):
        raise AssertionError("_glue 不该在 raw 成功时被调用")

    _rg._glue = _boom
    try:
        r = ring_of(ROOT / "CAD" / "图形练习.dxf", "V0")
    finally:
        _rg._glue = _orig_glue
    check("raw 已过门的视图不跑胶合（已成功结果逐位不变的保证）",
          r.ring is not None and r.ring.rule == "raw",
          f"{r.ring.rule if r.ring else r.note}")

    # J8 跨 0/2π 缝拆分 + 微弧旋向（P1-D）：D79307-剖面基体曾把 0.013°
    #    微弧读成 359.987° 近整圆 ⇒ 轮廓自交、BRepCheck 判 B-rep 无效。
    #    两条根因各自锚住：
    #    ① ``_split_primitives`` 混用 ``ang % TAU`` 原始角与可能为负的
    #       ``sa``/``sa+span``，拆出 sa > ea 的段（契约是 ea = sa + span）；
    #    ② recognizer 的朝向判据用吸附后的顶点做弦叉积——微弧矢高
    #       （~0.001mm）小于顶点吸附误差时符号由噪声决定。
    # ①合成锚：弧 -10°→0° 被 -0.2° 的横线切开（跨缝，raw 角 ≈ 6.2797）
    r10 = 10.0
    th = math.radians(-0.2)
    arc_seam = ("A", 0.0, 0.0, r10, math.radians(-10.0), 0.0)
    line_cut = ("L", 0.0, r10 * math.sin(th), 20.0, r10 * math.sin(th))
    outs = _rg._split_primitives([arc_seam, line_cut])
    arcs = [p for p in outs if p[0] == "A"]
    check("跨 0/2π 缝拆分：输出弧满足 ea ≥ sa 契约",
          bool(arcs) and all(p[5] >= p[4] - 1e-12 for p in arcs),
          str([(round(math.degrees(p[4]), 3),
                round(math.degrees(p[5]), 3)) for p in arcs]))
    check("跨 0/2π 缝拆分：无跨缝伪整圆（跨度 ≤ 输入 10°）",
          bool(arcs) and all(p[5] - p[4] <= math.radians(10.0) + 1e-9
                             for p in arcs),
          str([round(math.degrees(p[5] - p[4]), 3) for p in arcs]))

    # ②真实锚：D79307-剖面基体轮廓不得含「近整圆伪弧」（发射器口径）
    d79s, _c, _co, rep79s = understand(
        tmp / "D79307A264FCA6D8EC32E95B1B11BDBD_剖面图.dxf")
    prof79 = next((f.param("profile").value for f in rep79s.part.features
                   if f.type.value == "base"), None)
    pseudo = []
    tiny = 0
    if prof79 is not None:
        for i, s in enumerate(prof79.segments):
            if s.kind != "arc" or s.center is None:
                continue
            span = ((s.ea - s.sa) if s.ccw else (s.sa - s.ea)) % (2 * math.pi)
            chord = math.hypot(s.p2.x - s.p1.x, s.p2.y - s.p1.y)
            if chord < 0.1:
                tiny += 1
            if span > math.pi and chord < 0.3:
                pseudo.append((i, round(math.degrees(span), 3)))
    check("D79307-剖面 基体轮廓存在", prof79 is not None)
    check("D79307-剖面 基体无近整圆伪弧（P1-D 自交根因）",
          prof79 is not None and not pseudo, str(pseudo))
    check("D79307-剖面 基体保留 4 条 <0.1mm 微弧（未被静默丢弃）",
          prof79 is not None and tiny == 4, str(tiny))


# ============ K. 剖视图语义（20180425 气缸前盖三刀） ============

def test_section_semantics() -> None:
    """剖视图的三条语义（v0.6.45，20180425 气缸前盖）：

    ① **定性**：剖视图按 HATCH 计数定性，不按「X—X」标题（标题可能只绑到
       剖切线端点的俯视图上——bracket 剖面图实测 V0=top 带 A—A）；
    ② **定轴**：切平面没标位置时按同行/同列布局推断 u/v/p 轴；
    ③ **材料反证**：剖视图里可见轮廓全是实线，"实线对 ⇒ 凸台"不成立；
       剖面线（HATCH）说空就是孔/腔。只做 True→False 单向修正。
    """
    section("K. 剖视图语义（定性 / 定轴 / 材料反证）")
    from src.rebuild.evidence.model import Drawing, Evidence, Kind
    from src.rebuild.features.recognizer import _rebut_by_section
    from src.rebuild.model.geom2d import Line2, Point2
    from src.rebuild.views.correspondence import (
        CylinderHint,
        ViewFrame,
        _section_axes_by_layout,
    )
    from src.rebuild.views.view_typer import _extent_score, _hatched_views

    def ev(h: str, role: Role) -> Evidence:
        return Evidence(handle=h, kind=Kind.EDGE, layer="0",
                        geom=Line2(Point2(0.0, 0.0), Point2(1.0, 0.0)),
                        role=Claim(role, "test", Tier.GUESS))

    def bbox(x0: float, x1: float, y0: float, y1: float) -> BBox2:
        return BBox2.of_points([Point2(x0, y0), Point2(x1, y1)])

    # ---- K1 HATCH 计数是剖视定性判据 ----
    d = Drawing(path="test")
    d.evidence = [
        ev("h1", Role.HATCH_BOUNDARY), ev("h2", Role.HATCH_BOUNDARY),
        ev("h3", Role.HATCH_BOUNDARY), ev("l1", Role.VISIBLE),
    ]
    v0 = View(id="V0", evidence=["h1", "h2", "h3", "l1"])
    v1 = View(id="V1", evidence=[])
    d.views = [v0, v1]
    check("K1 剖面线 ≥3 ⇒ 判剖视图",
          _hatched_views(d, d.views) == {"V0"}, str(_hatched_views(d, d.views)))
    d.evidence = d.evidence[:2]          # 只有 2 条 → 不是剖面线
    check("K1 剖面线 <3 ⇒ 不判剖视图（局部剖/零散填充不误判）",
          _hatched_views(d, d.views) == set())

    # ---- K2 剖视伙伴跳过等长判定 ----
    # 剖视按剖切位置配置，本不与父视图等长：带 sections 时宽不等只记 0 分，
    # 不带时记 −1（曾把主视图候选扣成 0 分、全部 UNKNOWN）。
    a = View(id="A", bbox=bbox(0, 155, 0, 115))
    b = View(id="B", bbox=bbox(0, 33, 0, 115))     # 同行、宽不等
    cols = {"A": [b], "B": [a]}
    rows: dict[str, list[View]] = {"A": [], "B": []}
    check("K2 不等宽的剖视伙伴不扣分（记 0）",
          _extent_score(a, cols, rows, {"B"}) == 0
          and _extent_score(a, cols, rows) == -1,
          f"with={_extent_score(a, cols, rows, {'B'})}"
          f" without={_extent_score(a, cols, rows)}")

    # ---- K3 切平面未标注时按布局定轴 ----
    typed = [a, b]
    a.type = Claim(ViewType.FRONT, "test", Tier.GUESS)
    b.type = Claim(ViewType.SECTION, "test", Tier.GUESS)
    got = _section_axes_by_layout(b, typed, {"A": ("x", "z")})
    check("K3 剖视与主视图同行 ⇒ u=主视图 p(y)、v=主视图 v(z)",
          got == (("y", "z"), "A"), str(got))
    c = View(id="C", bbox=bbox(0, 33, 0, 115))
    c.type = Claim(ViewType.SECTION, "test", Tier.GUESS)
    check("K3 剖视只与另一个剖视同行 ⇒ 不互相锚定（返回 None）",
          _section_axes_by_layout(c, [b, c], {}) is None)

    # ---- K4 剖面材料反证（True→False 单向） ----
    fr = ViewFrame(view_id="V0", view_type=ViewType.SECTION,
                   u_axis="y", v_axis="z", p_axis="x",
                   u_span=(0.0, 33.0), v_span=(-50.0, 50.0))

    def hint(solid: bool | None = True, **kw: Any) -> Any:
        kw.setdefault("profile_method", "outline:V0")
        return CylinderHint(axis=Axis3(Point3(0.0, 0.0, 0.0), Vector3(0.0, 1.0, 0.0)),
                            radius=10.0, length=33.0, solid=solid,
                            span=(0.0, 33.0), **kw)

    def mats(mm: Any, frame: ViewFrame = fr) -> dict:
        return {"V0": (frame, mm, None)}

    def empty_mid(pt: Point2) -> bool:
        return not (-10.0 <= pt.y <= 10.0)      # 圆区间整段空

    def full(pt: Point2) -> bool:
        return True

    def blind(pt: Point2) -> bool:
        # 圆区间里 y∈[24,33]（a1 端）一段空 ⇒ 自 a1 端钻入、深 9 的盲孔
        if -10.0 <= pt.y <= 10.0:
            return pt.x < 24.0
        return True
    check("K4 圆区间整段无剖面线 ⇒ 判孔，span 取剖视全跨度（通孔）",
          _rebut_by_section(hint(), mats(empty_mid)) == (False, (0.0, 33.0)),
          str(_rebut_by_section(hint(), mats(empty_mid))))
    check("K4 圆区间有材料 ⇒ 不翻（凸台判定保留）",
          _rebut_by_section(hint(), mats(full)) == (True, None))
    check("K4 贴一端无料 ⇒ 判盲孔/腔，span 不改（深度仍以轮廓对为准）",
          _rebut_by_section(hint(), mats(blind)) == (False, None),
          str(_rebut_by_section(hint(), mats(blind))))
    check("K4 solid=None 不参与反证（False/None→True 永远不做）",
          _rebut_by_section(hint(solid=None), mats(empty_mid)) == (None, None))
    check("K4 圆轴不在剖视帧轴内 ⇒ 跳过（剖切面没穿过它）",
          _rebut_by_section(
              hint(),
              mats(full, ViewFrame(view_id="V0", view_type=ViewType.SECTION,
                                   u_axis="x", v_axis="z", p_axis="y",
                                   u_span=(0.0, 33.0), v_span=(-50.0, 50.0)))
          ) == (True, None))
    check("K4 非轮廓对来源（callout/无 profile）⇒ 不参与反证",
          _rebut_by_section(hint(profile_method=""), mats(empty_mid)) == (True, None))


# ============ L. 剖面材料通道（section_bore） ============

def test_section_bore() -> None:
    """剖面 HATCH 空腔 ⇒ 孔（v0.6.45，20180425 气缸前盖）。

    判据的四块地基，各自单独钉住：
    ① 直径标注要**几何**成立（间距=值、中点落在段轴、值的 2 倍=段宽）——
       只按数值配对会把图上「32 深」「15 螺纹深」当直径，凭空造出 Ø32 孔；
    ② 同轴更宽的空腔是**半径台阶**，不是横穿断口；
    ③ 段外至少一侧有材料（排除零件外的空气带），2/5 而非 4/5；
    ④ 剖面取代同轴旧 HOLE，但图上明写的孔标注（annotation:）不动。
    """
    section("L. 剖面材料通道（标注几何 / 台阶 / 壁面 / 取代）")
    from types import SimpleNamespace

    from src.rebuild.evidence.model import Drawing, Evidence, Kind
    from src.rebuild.features.section_bore import (
        _Cand,
        _candidates,
        _cut_plane_pos,
        _dim_proof,
        _gap_covered,
        _prove,
        _wall_ok,
        replace_coaxial,
    )
    from src.rebuild.model.geom2d import Line2, Point2
    from src.rebuild.views.correspondence import ViewFrame

    fr = ViewFrame(view_id="V0", view_type=ViewType.SECTION,
                   u_axis="y", v_axis="z", p_axis="x",
                   u_span=(0.0, 40.0), v_span=(0.0, 40.0))

    # ---- L1 直径标注的三点几何判据 ----
    seg = _Cand("u", 30.0, 5.0, 10.0, 20.0)
    good = [(10.0, (12.0, 25.0), (12.0, 35.0))]
    check("L1 垂直间距=值、中点落在段轴上 ⇒ 采用标注值",
          _dim_proof(seg, good, fr) == 10.0, str(_dim_proof(seg, good, fr)))
    check("L1 两点沿轴方向（那是深度/宽度标注）不构成直径",
          _dim_proof(seg, [(10.0, (10.0, 30.0), (20.0, 30.0))], fr) is None)
    check("L1 标注值 ≠ 2×段半宽（深度「32」误配半宽 5 的段）⇒ 不采用",
          _dim_proof(seg, [(32.0, (12.0, 14.0), (12.0, 46.0))], fr) is None)
    check("L1 中点偏离段轴 > 0.5 ⇒ 不采用",
          _dim_proof(seg, [(10.0, (12.0, 18.0), (12.0, 28.0))], fr) is None)
    check("L1 标注中点沿轴超出段跨度 > 1 ⇒ 不采用",
          _dim_proof(seg, [(10.0, (30.0, 25.0), (30.0, 35.0))], fr) is None)
    segv = _Cand("v", 30.0, 5.0, 10.0, 20.0)
    check("L1 沿 v 的段：垂直方向取 u（x）间距",
          _dim_proof(segv, [(10.0, (25.0, 12.0), (35.0, 12.0))], fr) == 10.0)

    # ---- L2 同轴链：无标注段沿用实测半宽 ----
    got = _prove([_Cand("u", 30.0, 4.8, 10.0, 20.0),
                  _Cand("u", 30.0, 3.0, 24.0, 40.0),
                  _Cand("u", 36.0, 4.0, 24.0, 40.0)], good, fr)
    check("L2 标注段用标注值当半径（4.8 → 5.0），同轴段记 coaxial",
          len(got) == 2 and got[0].half == 5.0
          and got[1].proof == "coaxial:dim:10"
          and got[1].tier == Tier.PROJECTION and got[1].half == 3.0,
          str([(c.half, c.proof) for c in got]))
    check("L2 无标注且不同轴 ⇒ 不建（原则二），_prove 不返回",
          all(c.center == 30.0 for c in got), str([c.center for c in got]))

    # ---- L3 断口：同轴更宽 = 台阶；异轴横穿 = 打断 ----
    step = [[(30.0, 5.0)], [(30.0, 12.0)], [(30.0, 5.0)]]
    check("L3 同轴更宽的空腔是半径台阶，不算横穿（段在此终止）",
          _gap_covered(step, 0, 2, 30.0, 5.0) is False)
    cross = [[(30.0, 5.0)], [(31.0, 8.0)], [(30.0, 5.0)]]
    check("L3 异轴空腔覆盖 ≥ 半段宽 ⇒ 断口不终止该段",
          _gap_covered(cross, 0, 2, 30.0, 5.0) is True)
    narrow = [[(30.0, 5.0)], [(34.0, 1.0)], [(30.0, 5.0)]]
    check("L3 异轴但覆盖不足半段宽（擦边）⇒ 不算横穿",
          _gap_covered(narrow, 0, 2, 30.0, 5.0) is False)

    # ---- L4 壁面：至少一侧有材料，2/5 采样 ----
    hole = _Cand("u", 0.0, 5.0, 0.0, 10.0)
    check("L4 段外侧有材料 ⇒ 保留",
          _wall_ok(fr, lambda p: abs(p.y) > 5.05, hole) is True)
    check("L4 只有一侧有材料也保留（孔常通到零件外表面）",
          _wall_ok(fr, lambda p: p.y > 5.05, hole) is True)
    check("L4 两侧 6mm 内都搜不到材料 ⇒ 零件外的空气带、丢弃",
          _wall_ok(fr, lambda p: False, hole) is False)
    check("L4 5 点只有段两端 2 点搜到材料 ⇒ 仍保留（WALL_FRAC=2/5，"
          "4/5 会丢掉被横孔穿通的 Ø40 段）",
          _wall_ok(fr, lambda p: abs(p.y) > 5.05
                   and (p.x < 2.5 or p.x > 7.5), hole) is True)

    # ---- L5 扫掠：恒定空腔段 ----
    us = [float(i) for i in range(11)]
    vs = [float(i) for i in range(11)]
    mat = [[not (3 <= j <= 7) for j in range(11)] for i in range(11)]
    cs = _candidates(us, vs, mat)
    real = next(c for c in cs if c.axis == "u")
    check("L5 沿 u 的空腔带 ⇒ 段 axis=u、center/half 与跨度正确",
          real.center == 5.0 and real.half == 2.0
          and real.lo == 0.0 and real.hi == 10.0, str(real))
    wide = next((c for c in cs if c.axis == "v"), None)
    check("L5 异轴伪段照样产出、由 MAX_HALF_FRAC 在上层挡掉（不在扫掠里猜）",
          wide is not None and wide.half == 5.0
          and wide.half > 0.35 * (us[-1] - us[0]), str(wide))

    # ---- L6 取代：剖面压过投影猜测，但孔标注不动 ----
    def feat(fid: int, ftype: FeatureType, meth: str, z0: float = 0.0) -> Feature:
        ax = Axis3(Point3(0.0, 0.0, z0), Vector3(0.0, 1.0, 0.0))
        return Feature(id=FeatureId(fid),
                       type=Claim(ftype, meth, Tier.PROJECTION, ("h1",)),
                       axis=Claim(ax, meth, Tier.PROJECTION, ("h1",)))

    part = SimpleNamespace(features=[
        feat(1, FeatureType.HOLE, "outline:V1"),
        feat(2, FeatureType.HOLE, "annotation:hole_callout"),
        feat(3, FeatureType.BOSS, "outline:V2"),
        feat(4, FeatureType.HOLE, "outline:V1", 50.0),
    ])
    rep = SimpleNamespace(notes=[])
    new = feat(90, FeatureType.HOLE, "section:material_profile+dim")
    n = replace_coaxial(part, [new], rep)
    check("L6 同轴旧 HOLE 被摘掉，孔标注/BOSS/异轴 HOLE 保留",
          n == 1 and [f.id for f in part.features] == [2, 3, 4],
          f"n={n} ids={[f.id for f in part.features]}")
    check("L6 摘除记进 notes（可追溯）",
          any("#1（outline:V1）" in s for s in rep.notes), str(rep.notes))
    check("L6 无新段时不动特征树", replace_coaxial(part, [], rep) == 0)

    # ---- L7 剖切面位置：唯一候选才采用 ----
    def axis_line(h: str, x: float) -> Evidence:
        return Evidence(handle=h, kind=Kind.EDGE, layer="0",
                        geom=Line2(Point2(x, 0.0), Point2(x, 100.0)),
                        role=Claim(Role.AXIS, "test", Tier.GUESS))

    d = Drawing(path="test")
    v0 = View(id="V0", type=Claim(ViewType.SECTION, "test", Tier.GUESS),
              bbox=BBox2.of_points([Point2(0.0, 0.0), Point2(40.0, 100.0)]))
    v1 = View(id="V1", type=Claim(ViewType.FRONT, "test", Tier.GUESS),
              evidence=["a1"], bbox=BBox2.of_points([Point2(0.0, 0.0),
                                                     Point2(200.0, 100.0)]))
    d.views = [v0, v1]
    corr = SimpleNamespace(frames={
        "V1": ViewFrame(view_id="V1", view_type=ViewType.FRONT,
                        u_axis="x", v_axis="z", p_axis="y")})
    d.evidence = [axis_line("a1", 50.0)]
    check("L7 剖切面法向=p_axis，位置从其它视图的点画线读（唯一候选）",
          _cut_plane_pos(d, corr, v0, fr) == ("x", 50.0),
          str(_cut_plane_pos(d, corr, v0, fr)))
    d.evidence.append(axis_line("a2", 60.0))
    v1.evidence.append("a2")
    check("L7 两条不同位置的剖切线 ⇒ 整剖面放弃（不猜）",
          _cut_plane_pos(d, corr, v0, fr) is None)
    d.evidence = [axis_line("a1", 50.0), axis_line("a2", 50.04)]
    check("L7 0.04mm 内的重复线去重后仍是唯一候选",
          _cut_plane_pos(d, corr, v0, fr) == ("x", 50.0))


# ============ 主入口 ============

def main() -> int:
    print("=" * 72)
    print("src/rebuild 阶段 0 自检")
    print("=" * 72)
    test_claim()
    test_text_parser()
    test_reader()
    test_views()
    test_verify()
    test_correspondence()
    test_conventions()
    test_features()
    test_pipeline()
    test_ring()
    test_section_semantics()
    test_section_bore()

    print("\n" + "=" * 72)
    if _failed:
        print(f"[FAIL] {len(_failed)} 项失败 / {_passed} 项通过")
        for f in _failed:
            print(f"  • {f}")
        return 1
    print(f"[OK] 全部通过（{_passed} 项）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
