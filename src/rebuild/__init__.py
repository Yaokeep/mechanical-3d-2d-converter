# -*- coding: utf-8 -*-
"""图纸理解与三维重建框架（设计见 docs/ARCHITECTURE.md）。

分层（依赖方向单向，见 ARCHITECTURE §5）：

    model        中间表示（零依赖）
    evidence     【第1层】读符号通道
    views        视图分离 + 跨视图对应
    conventions  【第2层】制图约定知识库
    features     【第3层】特征识别 + 约束求解
    verify       【第4层】特征级预测 / 重投影 / 覆盖率 / gate
    emit         特征树 → OCC B-rep / SW 特征树

解释器分层：model~features、verify.predict/coverage、report 只需
ezdxf + numpy，跑默认 python；verify.reproject 与 emit 需要 OCC（cad-occt）。
"""
from __future__ import annotations

__version__ = "0.1.0"
