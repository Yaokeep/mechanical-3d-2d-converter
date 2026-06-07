# 机械三维二维图互转 — 单位转换工具

from enum import Enum


class UnitSystem(Enum):
    """单位制"""
    MM = "mm"        # 毫米
    CM = "cm"        # 厘米
    M = "m"          # 米
    INCH = "inch"    # 英寸
    FOOT = "ft"      # 英尺


class UnitConverter:
    """单位转换器

    支持毫米（mm）、厘米（cm）、米（m）、英寸（inch）、英尺（ft）之间的转换。
    内部计算统一使用毫米。
    """

    # 1 单位 = 多少毫米
    TO_MM = {
        UnitSystem.MM: 1.0,
        UnitSystem.CM: 10.0,
        UnitSystem.M: 1000.0,
        UnitSystem.INCH: 25.4,
        UnitSystem.FOOT: 304.8,
    }

    # 显示精度
    DEFAULT_PRECISION = 4

    @classmethod
    def convert(cls, value: float, from_unit: UnitSystem, to_unit: UnitSystem) -> float:
        """在两个单位之间转换数值

        Args:
            value: 原始数值
            from_unit: 原始单位
            to_unit: 目标单位

        Returns:
            转换后的数值
        """
        mm_value = value * cls.TO_MM[from_unit]
        return mm_value / cls.TO_MM[to_unit]

    @classmethod
    def to_mm(cls, value: float, unit: UnitSystem) -> float:
        """转换为毫米"""
        return value * cls.TO_MM[unit]

    @classmethod
    def from_mm(cls, value: float, unit: UnitSystem) -> float:
        """从毫米转换"""
        return value / cls.TO_MM[unit]

    @classmethod
    def format_value(cls, value: float, unit: UnitSystem = UnitSystem.MM, precision: int = None) -> str:
        """格式化输出带单位的数值

        Args:
            value: 数值
            unit: 单位
            precision: 小数位数

        Returns:
            格式化字符串，如 "125.00 mm"
        """
        if precision is None:
            precision = cls.DEFAULT_PRECISION

        unit_symbols = {
            UnitSystem.MM: "mm",
            UnitSystem.CM: "cm",
            UnitSystem.M: "m",
            UnitSystem.INCH: "in",
            UnitSystem.FOOT: "ft",
        }

        symbol = unit_symbols.get(unit, "")
        return f"{value:.{precision}f} {symbol}"
