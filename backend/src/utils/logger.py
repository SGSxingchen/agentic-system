"""结构化日志 - 基于 structlog

提供 get_logger(name) 工厂函数:
- 开发环境: 彩色 console 输出
- 生产环境: JSON 格式输出

依赖: structlog (pip install structlog)
如果 structlog 不可用，回退到标准 logging。
"""
import logging
import os
import sys
from typing import Any

# 环境变量决定运行模式
_ENV = os.getenv("ENV", "development").lower()
_LOG_LEVEL = os.getenv("LOG_LEVEL", "DEBUG" if _ENV == "development" else "INFO").upper()

try:
    import structlog

    _HAS_STRUCTLOG = True
except ImportError:
    _HAS_STRUCTLOG = False

_configured = False


def _configure_structlog() -> None:
    """一次性配置 structlog"""
    global _configured
    if _configured:
        return
    _configured = True

    if not _HAS_STRUCTLOG:
        return

    shared_processors = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.UnicodeDecoder(),
    ]

    if _ENV == "development":
        # 开发环境: 彩色终端输出
        renderer = structlog.dev.ConsoleRenderer()
    else:
        # 生产环境: JSON 格式
        renderer = structlog.processors.JSONRenderer(ensure_ascii=False)

    structlog.configure(
        processors=[
            *shared_processors,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    # 配置标准 logging (structlog 使用它做输出)
    formatter = structlog.stdlib.ProcessorFormatter(
        processor=renderer,
        foreign_pre_chain=shared_processors,
    )
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(getattr(logging, _LOG_LEVEL, logging.DEBUG))


def get_logger(name: str) -> Any:
    """获取结构化 logger

    Args:
        name: logger 名称（通常为模块名）

    Returns:
        structlog BoundLogger（或标准 logging.Logger 作为回退）

    Usage::

        logger = get_logger(__name__)
        logger.info("agent.started", agent_name="coder", status="idle")
        logger.error("process.failed", error=str(e), task_id="abc")
    """
    if _HAS_STRUCTLOG:
        _configure_structlog()
        return structlog.get_logger(name)
    else:
        # Fallback: 标准库 logging
        logger = logging.getLogger(name)
        if not logger.handlers:
            handler = logging.StreamHandler(sys.stdout)
            handler.setFormatter(
                logging.Formatter(
                    "[%(asctime)s] %(levelname)s %(name)s: %(message)s"
                )
            )
            logger.addHandler(handler)
            logger.setLevel(getattr(logging, _LOG_LEVEL, logging.DEBUG))
        return logger
