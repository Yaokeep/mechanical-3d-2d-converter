# 机械三维二维图互转 — 日志管理

import sys
from pathlib import Path
from datetime import datetime


def setup_logger(
    log_dir: Path = None,
    level: str = "INFO",
    rotation: str = "10 MB",
    retention: str = "7 days",
):
    """初始化 loguru 日志系统

    Args:
        log_dir: 日志文件目录
        level: 日志级别
        rotation: 日志轮转策略
        retention: 日志保留策略
    """
    try:
        from loguru import logger

        # 移除默认 handler
        logger.remove()

        # 控制台输出（彩色）
        logger.add(
            sys.stderr,
            format=(
                "<green>{time:HH:mm:ss}</green> | "
                "<level>{level: <8}</level> | "
                "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - "
                "<level>{message}</level>"
            ),
            level=level,
            colorize=True,
        )

        # 文件输出
        if log_dir:
            log_dir.mkdir(parents=True, exist_ok=True)
            log_path = log_dir / f"cad_converter_{datetime.now():%Y%m%d}.log"
            logger.add(
                str(log_path),
                format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | {name}:{function}:{line} - {message}",
                level="DEBUG",
                rotation=rotation,
                retention=retention,
                encoding="utf-8",
            )

        logger.info("日志系统初始化完成")
        return logger

    except ImportError:
        # loguru 未安装时回退到标准库 logging
        import logging
        logging.basicConfig(
            level=getattr(logging, level.upper(), logging.INFO),
            format="%(asctime)s | %(levelname)-8s | %(name)s - %(message)s",
        )
        return logging.getLogger("cad_converter")
