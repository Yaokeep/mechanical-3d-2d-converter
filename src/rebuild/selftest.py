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
from src.rebuild.evidence.text_parser import TextKind, parse_text        # noqa: E402
from src.rebuild.model import Claim, Tier, merge                         # noqa: E402

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


# ============ 主入口 ============

def main() -> int:
    print("=" * 72)
    print("src/rebuild 阶段 0 自检")
    print("=" * 72)
    test_claim()
    test_text_parser()
    test_reader()

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
