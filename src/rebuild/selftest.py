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
from src.rebuild.evidence.model import ViewType                          # noqa: E402
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
from src.rebuild.model import Claim, OpenQuestion, Tier, merge           # noqa: E402
from src.rebuild.model.feature_tree import (                             # noqa: E402
    ConstraintType,
    Feature,
    FeatureType,
    Part,
)
from src.rebuild.model.geom import Axis3, Point3, Vector3                # noqa: E402
from src.rebuild.model.geom2d import profile_span                        # noqa: E402
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
    #    切平面位置由几何圆配准得出（标题坐标与图面坐标不同源，见 F3）。
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
        check("B—B 切平面 x = 45.30（121.89 经图面镜像配准）",
              abs(b.origin.x - 45.3025) < 0.01, f"{b.origin.x:.4f}")
        check("B—B 孔心 y = 148.05", abs(b.origin.y - 148.0547) < 0.01,
              f"{b.origin.y:.4f}")
    c = axes.get("V5")
    if c is not None:
        check("C—C 轴沿 Z", c.direction.z == 1.0, str(c.direction))
        check("C—C 半径 = 标题的 20", abs(c.radius.value - 20.0) < 1e-9,
              str(c.radius.value))
        check("C—C 切平面 x = 185.30（-18.11 经同一镜像常量配准）",
              abs(c.origin.x - 185.3025) < 0.01, f"{c.origin.x:.4f}")

    # F2 标题坐标与图面坐标**互为镜像**这件事必须报出来，而不是静默选一路：
    #    两个剖面各自独立给出同一镜像常量 k=167.190，而平移解不存在
    #    （偏移 -76.59 与 +203.41 互不相同）。这是出图侧俯视图画成仰视图的
    #    直接后果（model_to_drawing.project_all_views 的 dx = up × dz）。
    inc = res.questions.by_kind(OpenQuestion.INCONSISTENT_FRAME)
    check("报出「标注坐标系与图面不一致」", len(inc) == 1, str(len(inc)))
    if inc:
        check("候选里带镜像常量 167.190",
              any("mirror:167.190" in str(x) for x in inc[0].candidates),
              str(inc[0].candidates))
        check("两个平移候选都在（-76.59 / 203.41）",
              any("-76.59" in str(x) for x in inc[0].candidates)
              and any("203.41" in str(x) for x in inc[0].candidates),
              str(inc[0].candidates))

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


# ============ G. 约定层（阶段 2） ============

_SEC_DWG = ROOT / "CAD" / "temp_output" / "bracket_angker_图纸_20260922_剖面图.dxf"
_BLOCK = ROOT / "CAD" / "test_simple" / "block_3view.dxf"
_PF60K = ROOT / "CAD" / "temp_output" / "pf60k_闭环_三视图_20260817.dxf"
#: 自检自给的断裂视图夹具（不能依赖入库产物：一次性夹具按约定不入库）
_FIXTURE_BREAK = ROOT / "CAD" / "temp_output" / "_selftest_break.dxf"


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
    check("注册表里 8 条规则", len(names) == 8, str(names))
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


# ---- 阶段 3：特征层 ----

def _recognized(path: Path):
    """读 → 分离 → 定性 → 约定 → 对应 → 识别（阶段 3 全链）。"""
    d = _prepared(path)
    conv = run_rules(RuleCtx(d=d))
    corr = build_correspondence(d, broken=conv.broken)
    return d, conv, corr, recognize(d, corr, conv)


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

    # ---- H5 bracket：剖面标题进树 + 通孔判定 ----
    _, conv_b, corr_b, rep_b = _recognized(_SEC_DWG)
    f1 = next((f for f in rep_b.part.features if f.id == FeatureId(1)), None)
    check("bracket 剖面图纸识别出 8 个特征（同心圆不合并后 +2，见 G 段说明）",
          len(rep_b.part.features) == 8,
          str([(str(f.id), f.type.value) for f in rep_b.part.features]))
    base = rep_b.part.features[0]
    check("基体=沿 z 拉伸 44（最薄向）",
          base.type.value == "base" and base.params["dir"].value == "z"
          and abs(base.params["length"].value - 44.0) < 1e-9)
    check("#1 半径被剖面标题（B—B 的 r25.5）精化为 ANNOTATED",
          f1 is not None and f1.params["radius"].tier is Tier.ANNOTATED
          and abs(f1.params["radius"].value - 25.5) < 1e-9,
          str(f1.params["radius"]) if f1 else "无 #1")
    check("同一根轴的两路证据合并（≥2 项）",
          f1 is not None and len(f1.evidence) >= 2, str(f1.evidence if f1 else ""))
    check("有特征直接来自剖面标题（note:section_title）",
          any(f.type.method == "note:section_title"
              for f in rep_b.part.features))
    f2 = next((f for f in rep_b.part.features if f.id == FeatureId(3)), None)
    check("#3 深 22 < 材料厚 44 ⇒ 判为盲孔（DERIVED，非 GUESS）",
          f2 is not None and f2.params["through"].value is False
          and f2.params["through"].tier is Tier.DERIVED
          and f2.params["through"].method == "derived:depth_vs_material",
          str(f2.params["through"]) if f2 else "无 #3")
    check("同轴同心圆各建一个特征（r25.5 凸台里再有一个 r15.7 凸台）",
          any(f.id == FeatureId(2) and abs(f.params["radius"].value - 15.7) < 1e-9
              for f in rep_b.part.features))
    check("每处孔都有 through（发射器不接受缺参数）",
          all("through" in f.params for f in rep_b.part.features
              if f.type.value == "hole"))

    # ---- H6 PF60K：阵列挂到正确的孔上（判据是"在分布圆上"，不是"在圆心上"） ----
    _, _, _, rep_p = _recognized(_PF60K)
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
              abs(p.placement.value.x - 32.0) < 0.01
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
