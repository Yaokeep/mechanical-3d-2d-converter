# -*- coding: utf-8 -*-
"""CLI：图纸 → 特征树 → 模型（新框架的统一入口）。

    python -m src.rebuild.rebuild <dxf> [选项]

    --step PATH     出 STEP（要 cad-occt 环境；默认不出）
    --sldprt PATH   出 SW 原生特征树（要 SW 在跑 + pywin32）
    --sw            等同于给 --sldprt 一个默认名
    --force         有拦路疑问也照样发射（逐条打 [GUESS]）
    --json          机器可读
    -q/--quiet      只印结论行

与 `inspect`（只看图纸）和 `verify_legacy`（只判模型）并列：本命令是**造**的那条。
理解层跑默认 python 即可；加了 --step/--sldprt 才需要 OCC 或 SW ——
缺环境时**不算失败**：记一行说明，理解层的结果照常打印（见 pipeline._emit_*）。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

if __package__ in (None, ""):                       # 允许直接 python 跑本文件
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.rebuild.pipeline import rebuild                          # noqa: E402


def _default_out(src: Path, suffix: str) -> Path:
    """默认产物名：与输入同目录、加后缀（时间戳由发射器自己加）。"""
    return src.with_name(f"{src.stem}_重建{suffix}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="rebuild", description="图纸 → 特征树 → 模型（新框架）")
    ap.add_argument("dxf", help="输入 DXF 图纸")
    ap.add_argument("--step", nargs="?", const="", default=None,
                    help="出 STEP（不给路径则用 <输入名>_重建.step）")
    ap.add_argument("--sldprt", nargs="?", const="", default=None,
                    help="出 SW 原生特征树（不给路径则用 <输入名>_重建.sldprt）")
    ap.add_argument("--sw", action="store_true", help="等同于 --sldprt（默认名）")
    ap.add_argument("--force", action="store_true",
                    help="有拦路疑问（类型未定/缺尺寸）时也照样发射 —— "
                         "只为与旧管线基线做可比性测量，不是正常用法")
    ap.add_argument("--json", action="store_true", help="机器可读输出")
    ap.add_argument("-q", "--quiet", action="store_true", help="只印结论行")
    args = ap.parse_args(argv)

    src = Path(args.dxf)
    if not src.exists():
        print(f"[FAIL] 文件不存在：{src}", file=sys.stderr)
        return 3

    step = None if args.step is None else Path(
        args.step or _default_out(src, ".step"))
    sldprt = None if args.sldprt is None else Path(
        args.sldprt or _default_out(src, ".sldprt"))

    try:
        res = rebuild(src, step=step, sldprt=sldprt, sw=args.sw,
                      force=args.force)
    except Exception as e:                          # noqa: BLE001
        print(f"[FAIL] 理解层就挂了：{type(e).__name__}: {e}", file=sys.stderr)
        return 1

    if args.json:
        print(res.to_json())
        return 0

    if args.quiet:
        n = len(res.part.features) if res.part else 0
        print(f"{src.name}: {n} 个特征，"
              f"{len(res.questions)} 项待确认，"
              f"STEP {'✓' if res.step else '×'} "
              f"SLDPRT {'✓' if res.sldprt else '×'}")
    else:
        print(res.describe())

    # 退出码：0 = 理解成功；2 = 有拦路的待确认项（"知道该拒绝"要能被脚本看见）
    return 2 if res.blocking() else 0


if __name__ == "__main__":
    raise SystemExit(main())
