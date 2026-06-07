# 机械三维二维图互转 — 文件格式注册表

from typing import Type, Optional


class BaseImporter:
    """导入器基类"""
    FORMAT_NAME: str = ""
    EXTENSIONS: list[str] = []

    def import_file(self, path: str) -> "Document":
        raise NotImplementedError


class BaseExporter:
    """导出器基类"""
    FORMAT_NAME: str = ""
    EXTENSIONS: list[str] = []

    def export(self, path: str, document: "Document", **kwargs) -> None:
        raise NotImplementedError


class FormatRegistry:
    """文件格式注册表（工厂模式）

    使用方式：
        FormatRegistry.register_importer(".stp", StepImporter)
        importer = FormatRegistry.get_importer(".stp")
        doc = importer.import_file("model.stp")
    """

    _importers: dict[str, Type[BaseImporter]] = {}
    _exporters: dict[str, Type[BaseExporter]] = {}

    @classmethod
    def register_importer(cls, extension: str, importer_cls: Type[BaseImporter]) -> None:
        """注册文件导入器

        Args:
            extension: 文件扩展名（含点），如 ".step"
            importer_cls: 导入器类
        """
        ext = extension.lower()
        cls._importers[ext] = importer_cls

    @classmethod
    def register_exporter(cls, extension: str, exporter_cls: Type[BaseExporter]) -> None:
        """注册文件导出器

        Args:
            extension: 文件扩展名（含点），如 ".step"
            exporter_cls: 导出器类
        """
        ext = extension.lower()
        cls._exporters[ext] = exporter_cls

    @classmethod
    def get_importer(cls, extension: str) -> Optional[BaseImporter]:
        """根据文件扩展名获取导入器实例

        Returns:
            导入器实例，如果格式不支持则返回 None
        """
        ext = extension.lower()
        importer_cls = cls._importers.get(ext)
        if importer_cls is None:
            return None
        return importer_cls()

    @classmethod
    def get_exporter(cls, extension: str) -> Optional[BaseExporter]:
        """根据文件扩展名获取导出器实例

        Returns:
            导出器实例，如果格式不支持则返回 None
        """
        ext = extension.lower()
        exporter_cls = cls._exporters.get(ext)
        if exporter_cls is None:
            return None
        return exporter_cls()

    @classmethod
    def supported_import_formats(cls) -> list[str]:
        """获取所有支持的导入格式扩展名"""
        return list(cls._importers.keys())

    @classmethod
    def supported_export_formats(cls) -> list[str]:
        """获取所有支持的导出格式扩展名"""
        return list(cls._exporters.keys())

    @classmethod
    def import_file_filter(cls) -> str:
        """生成文件对话框的导入过滤器字符串"""
        parts = []
        for ext, imp_cls in cls._importers.items():
            parts.append(f"{imp_cls.FORMAT_NAME} (*{ext})")
        parts.append("所有文件 (*.*)")
        return ";;".join(parts)

    @classmethod
    def export_file_filter(cls) -> str:
        """生成文件对话框的导出过滤器字符串"""
        parts = []
        for ext, exp_cls in cls._exporters.items():
            parts.append(f"{exp_cls.FORMAT_NAME} (*{ext})")
        return ";;".join(parts)
