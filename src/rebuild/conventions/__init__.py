# -*- coding: utf-8 -*-
"""约定层（ARCHITECTURE §5 第 2 层）—— 标准知识库。

导入本包即完成规则注册（各规则模块用 ``@register`` 自登记）。
规则是**长尾**的：加一条不动其余，坏一条不拖垮其余（见 registry.run_rules）。

依赖：``conventions → model, evidence, views``；默认 python 即可跑。
"""
from . import centerline, linetype, section, simplification   # noqa: F401 注册用
from .centerline import Pattern, Symmetry
from .linetype import HiddenProfile
from .registry import (
    BrokenView, Convention, Conventions, ConvKind, RuleCtx, run_rules,
    registered,
)
from .section import MaterialPatch, SectionScope
from .simplification import FilletSpec, ThreadSpec

__all__ = [
    "BrokenView", "Convention", "Conventions", "ConvKind", "FilletSpec",
    "HiddenProfile", "MaterialPatch", "Pattern", "RuleCtx", "SectionScope",
    "Symmetry", "ThreadSpec", "registered", "run_rules",
]
