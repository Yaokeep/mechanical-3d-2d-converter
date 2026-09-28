# -*- coding: utf-8 -*-
"""验证层（ARCHITECTURE §6、§8 阶段 0）。

**先有尺子，再有工件。** 本包当前的用途是把旧管线
（``dxf_to_3d_general.py``）的输出拿图纸判一遍 —— 判过才输出。

依赖分层（ARCHITECTURE §5）：本 ``__init__`` 只导出**不需要 OCC** 的部分，
默认 python 即可 import。``step_probe`` 要 OCC 且必须用 cad-occt 环境，
故**不在此处导出**，由调用方按需 import。
"""
from .compare import (
    RATIO_TOL,
    SCALE_TOL,
    Comparison,
    Expected,
    compare,
    expect_from_drawing,
)
from .coverage import Coverage, coverage, coverage_report
from .gate import GateResult, Verdict, decide

__all__ = [
    "RATIO_TOL", "SCALE_TOL",
    "Comparison", "Expected", "compare", "expect_from_drawing",
    "Coverage", "coverage", "coverage_report",
    "GateResult", "Verdict", "decide",
]
