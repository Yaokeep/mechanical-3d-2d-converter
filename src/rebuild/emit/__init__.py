# -*- coding: utf-8 -*-
"""发射器层：特征树 → 几何 / 原生特征模型（docs/ARCHITECTURE.md §5）。

    emit/sw_builder.py    特征树 → SW 原生特征树（pywin32）
    emit/occ_builder.py   特征树 → OCC B-rep（精确）   ← 另一条并行实现的路径

## 为什么本模块只做"懒加载包装"而不 re-export

`sw_builder` 要 pywin32、`occ_builder` 要 OCC，而 emit 层会被 `pipeline` 在
**不特定的解释器**下 import（默认 python 既没有 OCC，也不保证有 SW COM）。
模块级 `from .sw_builder import ...` 会让"只是想看一眼 emit 层有哪些入口"的
调用方直接 ImportError —— 所以这里只暴露几个薄包装，真东西在函数体内 import。

依赖方向（ARCHITECTURE §5）：`emit/ → model`（+ OCC / SW COM）。
本层**不得**反向依赖 `verify/` —— 验证必须能只看特征树就预测形状，
不能靠"造出来再量"（§5 硬规则 2）。
"""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:                      # 仅供类型标注，运行时不 import
    from ..model.feature_tree import Part

__all__ = ["build_part_occ", "build_part_sw", "occ_available", "sw_available"]


def sw_available() -> bool:
    """SW 侧发射器当前是否可用（SW 在跑 且 win32com 可导入）。不抛异常。"""
    try:
        from . import sw_builder
    except Exception:
        return False
    return sw_builder.sw_available()


def build_part_sw(part: "Part", save_to: Path, **kw: Any) -> Path:
    """`sw_builder.build_part` 的懒加载入口（参数原样透传）。"""
    from . import sw_builder

    return sw_builder.build_part(part, save_to, **kw)


def occ_available() -> bool:
    """OCC 侧发射器当前是否可用。不抛异常。

    与 `sw_available` 同一套思路：真正要判的是"能不能干活"。这里替懒加载
    兜住 `import occ_builder` 本身失败的情形（默认 python 没装 pythonocc，
    这个 import 会直接 ImportError）—— 调用方只想问一句"能用吗"，
    不该因此吃到异常。装好了再走 occ_builder 自己的几何冒烟自检。
    """
    try:
        from . import occ_builder
    except Exception:
        return False
    return occ_builder.occ_available()


def build_part_occ(part: "Part", path: Path, **kw: Any) -> Path:
    """`occ_builder.build_step` 的懒加载入口（参数原样透传）。

    粒度是"特征树 → STEP 文件"：OCC 侧没有 SW 那样的原生特征树可落，
    产物就是 B-rep 本身（想只要内存里的形状直接调 `occ_builder.build_shape`）。
    """
    from . import occ_builder

    return occ_builder.build_step(part, path, **kw)
