# -*- coding: utf-8 -*-
"""图纸证据检查器 —— 阶段 0 的交付入口。

    python -m src.rebuild.inspect <dxf> [--explain HANDLE] [--dims] [--texts]
                                        [--json]

只依赖 ezdxf，**默认 python 即可运行**，不需要 cad-occt。

用途：看清图纸里到底有什么 —— 尤其是旧管线丢弃的符号通道
（剖面标题里的切平面位置与半径）。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# 允许作为脚本直接跑（python src/rebuild/inspect.py）也允许 python -m
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.rebuild.evidence.dxf_reader import read_dxf_safe   # noqa: E402
from src.rebuild.evidence.text_parser import TextKind       # noqa: E402
from src.rebuild.report import (                            # noqa: E402
    evidence_report,
    explain,
    views_report,
)
from src.rebuild.views import detect_views, type_views      # noqa: E402


def _as_json(d, questions=None) -> dict:
    """机器可读输出 —— 供后续阶段与测试消费。"""
    return {
        "path": d.path,
        "counts": d.kind_counts(),
        "layers": d.layers,
        "views": [
            {
                "id": v.id,
                "type": v.type.value.value if hasattr(v.type.value, "value")
                        else str(v.type.value),
                "tier": int(v.type.tier),
                "settled": v.type.is_settled,
                "alternatives": [a.value for a in v.type.alternatives],
                "method": (v.method.value if v.method is not None else None),
                "n_evidence": len(v.evidence),
                "n_annotations": len(v.annotations),
                "bbox": ([v.bbox.xmin, v.bbox.ymin, v.bbox.xmax, v.bbox.ymax]
                         if v.bbox is not None else None),
                "cut": ({"label": v.cut.label, "axis": v.cut.cut_axis,
                         "pos": v.cut.cut_pos, "radius": v.cut.radius}
                        if v.cut is not None else None),
            }
            for v in d.views
        ],
        "questions": [
            {"kind": q.kind.value, "detail": q.detail, "view": q.view,
             "candidates": list(q.candidates)}
            for q in (questions or [])
        ],
        "section_titles": [
            {
                "handle": str(t.handle), "text": t.text,
                "label": t.cut.label, "kind": t.cut.kind,
                "cut_axis": t.cut.cut_axis, "cut_pos": t.cut.cut_pos,
                "radius": t.cut.radius, "diameter": t.cut.diameter,
                "located": t.cut.is_located,
            }
            for t in d.texts
            if t.kind == TextKind.SECTION_TITLE and t.cut is not None
        ],
        "view_labels": [
            {"handle": str(t.handle), "text": t.text,
             "view_type": t.view_type, "x": t.x, "y": t.y}
            for t in d.texts if t.kind == TextKind.VIEW_LABEL
        ],
        "section_markers": [
            {"handle": str(t.handle), "text": t.text, "x": t.x, "y": t.y}
            for t in d.texts if t.kind == TextKind.SECTION_MARKER
        ],
        "notes": [
            {"handle": str(t.handle), "text": t.text,
             "values": [list(v) for v in t.values]}
            for t in d.texts if t.kind == TextKind.NOTE
        ],
        "dimensions": [
            {"handle": str(x.handle), "dimtype": x.dimtype, "value": x.value,
             "p1": [x.p1.x, x.p1.y] if x.p1 else None,
             "p2": [x.p2.x, x.p2.y] if x.p2 else None,
             "text_override": x.text_override}
            for x in d.dimensions
        ],
        "evidence_count": len(d.evidence),
        "texts_count": len(d.texts),
        "dimensions_count": len(d.dimensions),
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="inspect", description="DXF 证据检查（阶段 0）")
    ap.add_argument("dxf", help="输入 DXF 图纸")
    ap.add_argument("--explain", metavar="HANDLE",
                    help="溯源某个图元 handle")
    ap.add_argument("--dims", action="store_true", help="只列尺寸标注")
    ap.add_argument("--texts", action="store_true", help="只列文字解析结果")
    ap.add_argument("--views", action="store_true", help="只列视图分离与定性")
    ap.add_argument("--json", action="store_true", help="机器可读输出")
    args = ap.parse_args(argv)

    drawing = read_dxf_safe(args.dxf)
    if not drawing.evidence and not drawing.texts:
        print("[FAIL] 图纸为空或读取失败", file=sys.stderr)
        return 2

    # 视图分离 + 定性：默认一并做掉 —— 这两步只依赖 ezdxf，代价可忽略，
    # 而"某图元属于哪个视图"是后面所有推理的前提
    detect_views(drawing)
    questions = type_views(drawing)

    if args.json:
        print(json.dumps(_as_json(drawing, questions), ensure_ascii=False,
                         indent=2))
        return 0

    if args.explain:
        print(explain(drawing, args.explain))
        return 0

    if args.dims:
        if not drawing.dimensions:
            print("（无 DIMENSION 实体 —— 符号通道为空）")
        for x in drawing.dimensions:
            v = f"{x.value:g}" if x.value is not None else "?"
            print(f"{x.dimtype:10} {v:>12}  @{x.layer}  {x.handle}")
        return 0

    if args.texts:
        for t in drawing.texts:
            extra = ""
            if t.cut is not None:
                extra = (f"  [{t.cut.kind} {t.cut.cut_axis}={t.cut.cut_pos}"
                         f" r={t.cut.radius}]")
            elif t.values:
                extra = f"  {list(t.values)}"
            print(f"{t.kind.value:15} {t.text[:52]:54}{extra}")
        return 0

    if args.views:
        print(views_report(drawing, questions))
        return 0

    print(evidence_report(drawing))
    print(views_report(drawing, questions))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
