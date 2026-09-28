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

import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.rebuild.evidence.dxf_reader import read_dxf                     # noqa: E402
from src.rebuild.evidence.model import ViewType                          # noqa: E402
from src.rebuild.evidence.text_parser import (                           # noqa: E402
    TextKind,
    find_projection,
    parse_text,
)
from src.rebuild.model import Claim, OpenQuestion, Tier, merge           # noqa: E402
from src.rebuild.views import detect_views, type_views                   # noqa: E402

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
