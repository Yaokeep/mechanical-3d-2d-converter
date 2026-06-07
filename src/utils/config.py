# 机械三维二维图互转 — 应用配置管理

import json
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional


@dataclass
class AppConfig:
    """应用程序全局配置

    存储用户偏好设置，支持 JSON 文件持久化。
    """

    # 文件路径
    last_directory: str = ""

    # 显示
    theme: str = "light"                    # "light" | "dark"
    language: str = "zh_CN"                 # 界面语言

    # 3D 视图
    display_mode: str = "shaded"            # "wireframe" | "shaded" | "shaded_with_edges"
    background_color: str = "#d0d0d0"       # 3D 视图背景色

    # 2D 视图
    grid_enabled: bool = True
    grid_spacing: float = 10.0              # 网格间距 (mm)
    default_layout: str = "four_view"       # "single" | "four_view" | "six_view"

    # 工程图
    default_view_scale: float = 1.0
    auto_dimension: bool = True             # 是否自动生成标注
    dimension_precision: int = 2            # 标注小数位

    # 导出
    default_export_format: str = "step"
    hlr_precision: float = 1e-3            # HLR 计算精度
    stl_deflection: float = 0.01           # STL 三角剖分精度

    @classmethod
    def load(cls, path: Optional[Path] = None) -> "AppConfig":
        """从 JSON 文件加载配置

        Args:
            path: 配置文件路径，默认为 ~/.cad_converter_config.json

        Returns:
            AppConfig 实例
        """
        if path is None:
            path = Path.home() / ".cad_converter_config.json"

        if not path.exists():
            return cls()

        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})
        except (json.JSONDecodeError, IOError):
            return cls()

    def save(self, path: Optional[Path] = None) -> None:
        """保存配置到 JSON 文件

        Args:
            path: 配置文件路径
        """
        if path is None:
            path = Path.home() / ".cad_converter_config.json"

        with open(path, "w", encoding="utf-8") as f:
            json.dump(asdict(self), f, indent=2, ensure_ascii=False)

    def reset_defaults(self) -> None:
        """重置为默认配置"""
        defaults = AppConfig()
        for field_name in self.__dataclass_fields__:
            setattr(self, field_name, getattr(defaults, field_name))
