"""Structured logging configuration for TraderCoach backend.

Sets up:
- JSON formatter for file handler (machine-readable, good for log aggregators)
- Colored plain-text formatter for console (human-readable during development)
- RotatingFileHandler: logs/app.log, max 10 MB × 5 backups
- Root level: INFO; SQLAlchemy engine: WARNING (suppress noisy SQL)
"""

from __future__ import annotations

import logging
import logging.handlers
import os
import sys
import json
import traceback
from datetime import datetime, timezone
from pathlib import Path


# ── JSON formatter ────────────────────────────────────────────────────────────

class JsonFormatter(logging.Formatter):
    """Emit each log record as a single-line JSON object."""

    def format(self, record: logging.LogRecord) -> str:
        log_obj: dict = {
            "ts": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }

        # Attach exception info if present
        if record.exc_info:
            log_obj["exc"] = self.formatException(record.exc_info)

        # Attach any extra fields passed via `extra=` kwarg
        for key, value in record.__dict__.items():
            if key not in (
                "name", "msg", "args", "levelname", "levelno", "pathname",
                "filename", "module", "exc_info", "exc_text", "stack_info",
                "lineno", "funcName", "created", "msecs", "relativeCreated",
                "thread", "threadName", "processName", "process", "message",
                "taskName",
            ):
                log_obj[key] = value

        return json.dumps(log_obj, ensure_ascii=False)


# ── Console formatter ─────────────────────────────────────────────────────────

_LEVEL_COLORS = {
    "DEBUG":    "\033[37m",    # white
    "INFO":     "\033[36m",    # cyan
    "WARNING":  "\033[33m",    # yellow
    "ERROR":    "\033[31m",    # red
    "CRITICAL": "\033[1;31m",  # bold red
}
_RESET = "\033[0m"


class ConsoleFormatter(logging.Formatter):
    """Human-readable colored log lines for the terminal."""

    FMT = "{color}[{levelname:8s}]{reset} {asctime} | {name} | {message}"

    def format(self, record: logging.LogRecord) -> str:
        color = _LEVEL_COLORS.get(record.levelname, "")
        record.color = color
        record.reset = _RESET
        formatted = self.FMT.format(
            color=color,
            reset=_RESET,
            levelname=record.levelname,
            asctime=self.formatTime(record, "%H:%M:%S"),
            name=record.name,
            message=record.getMessage(),
        )
        if record.exc_info:
            formatted += "\n" + self.formatException(record.exc_info)
        return formatted


# ── Public setup function ─────────────────────────────────────────────────────

def setup_logging(log_dir: str = "logs", level: int = logging.INFO) -> None:
    """Configure root logger with file (JSON) + console (text) handlers.

    Call once at application startup, before any other imports emit logs.
    """
    Path(log_dir).mkdir(parents=True, exist_ok=True)
    log_path = Path(log_dir) / "app.log"

    root = logging.getLogger()
    root.setLevel(level)

    # Avoid duplicate handlers if called more than once (e.g. in tests)
    if root.handlers:
        return

    # ── File handler (JSON, rotating) ────────────────────────────────────────
    file_handler = logging.handlers.RotatingFileHandler(
        filename=str(log_path),
        maxBytes=10 * 1024 * 1024,  # 10 MB
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(JsonFormatter())

    # ── Console handler (plain text) ─────────────────────────────────────────
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(level)
    console_handler.setFormatter(ConsoleFormatter())

    root.addHandler(file_handler)
    root.addHandler(console_handler)

    # Silence noisy third-party loggers
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.pool").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)

    logging.getLogger(__name__).info(
        "Logging initialised — file: %s, level: %s",
        log_path.resolve(),
        logging.getLevelName(level),
    )
