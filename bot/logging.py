"""Настройка логирования на базе structlog."""

from __future__ import annotations

import logging
from typing import Any

import structlog


def configure_logging(level: int = logging.INFO) -> None:
    """Сконфигурировать логирование для приложения."""

    timestamper = structlog.processors.TimeStamper(fmt="ISO", utc=True)

    shared_processors: list[structlog.types.Processor] = [
        timestamper,
        structlog.processors.add_log_level,
    ]

    structlog.configure(
        processors=[
            *shared_processors,
            structlog.processors.UnicodeDecoder(),
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        processor=structlog.processors.JSONRenderer(),
        foreign_pre_chain=shared_processors,
    )

    handler = logging.StreamHandler()
    handler.setFormatter(formatter)

    logging.basicConfig(level=level, handlers=[handler])


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    """Вернуть логгер structlog, привязанный к переданному имени."""

    return structlog.get_logger(name or __name__)

