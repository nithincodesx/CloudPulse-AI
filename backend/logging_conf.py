"""CloudPulse AI — structured logging (structlog).

JSON lines on non-TTY outputs (Render, CI, file) so logs are machine-parseable;
a human-friendly colored console when attached to a terminal (local dev).

Usage::

    from logging_conf import configure_logging, get_logger

    configure_logging()   # once, at app import
    logger = get_logger("backend.main")
    logger.info("server.registered", server_id="…")
"""

from __future__ import annotations

import logging
import os
import sys

import structlog


def configure_logging(level: int = logging.INFO) -> None:
    """Configure stdlib + structlog. Safe to call more than once."""
    log_level = os.getenv("LOG_LEVEL", "").upper()
    if log_level in ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"):
        level = getattr(logging, log_level)

    timestamper = structlog.processors.TimeStamper(fmt="iso", utc=True)

    shared_processors: list = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        timestamper,
    ]

    if sys.stderr.isatty():
        # Local dev: colored, human-readable console.
        processors = shared_processors + [
            structlog.dev.ConsoleRenderer(colors=True),
        ]
    else:
        # Prod / CI: one JSON object per line.
        processors = shared_processors + [
            structlog.processors.dict_tracebacks,
            structlog.processors.JSONRenderer(),
        ]

    logging.basicConfig(format="%(message)s", stream=sys.stderr, level=level)
    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(level),
        logger_factory=structlog.PrintLoggerFactory(file=sys.stderr),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str = "cloudpulse") -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name)
