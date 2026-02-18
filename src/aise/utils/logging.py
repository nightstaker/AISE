"""Centralized logging helpers for AISE."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path
from typing import Any

from ..config import LoggingConfig

_LOGGER_NAME = "aise"
_configured_signature: tuple[str, str, bool, bool] | None = None


class _JsonFormatter(logging.Formatter):
    """Serialize logs into a compact JSON structure."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }
        for key, value in record.__dict__.items():
            if key in payload or key.startswith("_"):
                continue
            if key in {
                "name",
                "msg",
                "args",
                "created",
                "filename",
                "exc_info",
                "exc_text",
                "stack_info",
                "lineno",
                "funcName",
                "levelname",
                "levelno",
                "pathname",
                "module",
                "msecs",
                "relativeCreated",
                "thread",
                "threadName",
                "processName",
                "process",
                "message",
            }:
                continue
            payload[key] = value
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)


def configure_logging(config: LoggingConfig | None = None, *, force: bool = False) -> None:
    """Configure root logging once, with optional forced reconfiguration."""
    global _configured_signature

    cfg = config or LoggingConfig()
    level_name = str(cfg.level).upper()
    signature = (level_name, str(cfg.log_dir), bool(cfg.json_format), bool(cfg.rotate_daily))
    if not force and _configured_signature == signature:
        return

    level = getattr(logging, level_name, logging.INFO)
    log_dir = Path(cfg.log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "aise.log"

    root = logging.getLogger()
    root.setLevel(level)

    for handler in list(root.handlers):
        root.removeHandler(handler)
        handler.close()

    formatter: logging.Formatter
    if cfg.json_format:
        formatter = _JsonFormatter()
    else:
        formatter = logging.Formatter(
            "%(asctime)s | %(levelname)s | %(name)s | %(message)s",
            "%Y-%m-%d %H:%M:%S",
        )

    console = logging.StreamHandler()
    console.setFormatter(formatter)
    root.addHandler(console)

    if cfg.rotate_daily:
        file_handler = TimedRotatingFileHandler(
            filename=str(log_file),
            when="midnight",
            backupCount=7,
            encoding="utf-8",
        )
    else:
        file_handler = logging.FileHandler(filename=str(log_file), encoding="utf-8")
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)

    logging.getLogger(_LOGGER_NAME).setLevel(level)
    _configured_signature = signature
    logging.getLogger(__name__).info(
        "Logging configured: level=%s log_dir=%s json_format=%s rotate_daily=%s",
        level_name,
        log_dir,
        cfg.json_format,
        cfg.rotate_daily,
    )


def format_inference_result(result: Any) -> str:
    """Format inference output for logs with privacy-friendly truncation."""
    text = str(result)
    if len(text) <= 50:
        return text
    head = text[:20]
    tail = text[-20:]
    return f"<len={len(text)} head={head!r} tail={tail!r}>"
