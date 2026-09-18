"""Logging configuration.

Provides two output channels off a single `routemanager` logger:

  1. Console (stdout) using the standard human-readable formatter.
     Catalyst captures this stream at the function level.
  2. Optional JSONL file at `jsonl_file`, one JSON record per LogRecord.
     Records include `run_id` (sourced from the `_run_id_var` contextvar)
     and any structured `event` / `fields` attached via `logger.info(
     ..., extra={"event": "...", "fields": {...}})`.

The JSONL channel is the source of truth for post-mortem replay; the
console channel is for live tailing in the Catalyst dashboard.
"""

import json
import logging
import sys
from contextvars import ContextVar
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


_run_id_var: ContextVar[str] = ContextVar("run_id", default="")


def set_run_id(run_id: str) -> None:
    """Bind run_id into the logging contextvar.

    All subsequent LogRecords on this thread carry this value.
    """
    _run_id_var.set(run_id)


class _RunIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if not hasattr(record, "run_id") or not getattr(record, "run_id", ""):
            record.run_id = _run_id_var.get()
        return True


class _JsonlFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        obj = {
            "t": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "run_id": getattr(record, "run_id", ""),
            "event": getattr(record, "event", "log"),
            "message": record.getMessage(),
            "logger": record.name,
        }
        fields = getattr(record, "fields", None)
        if isinstance(fields, dict):
            for k, v in fields.items():
                if k not in obj:
                    obj[k] = v
        if record.exc_info:
            obj["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(obj, default=str)


def setup_logger(
    name: str = "routemanager",
    level: str = "INFO",
    log_file: Optional[Path] = None,
    jsonl_file: Optional[Path] = None,
) -> logging.Logger:
    """Configure and return the `routemanager` logger.

    Args:
        name:       Logger name. Must match `get_logger()` consumers.
        level:      Threshold for all handlers.
        log_file:   Optional path to a plain-text log file.
        jsonl_file: Optional path to a JSONL file. One JSON record per
                    LogRecord. Pass when you want a machine-parseable
                    artifact for post-mortem replay.
    """
    logger = logging.getLogger(name)
    logger.setLevel(getattr(logging, level.upper()))
    logger.handlers = []
    logger.addFilter(_RunIdFilter())

    text_formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - [run=%(run_id)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(getattr(logging, level.upper()))
    console_handler.setFormatter(text_formatter)
    console_handler.addFilter(_RunIdFilter())
    logger.addHandler(console_handler)

    if log_file:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_file)
        file_handler.setLevel(getattr(logging, level.upper()))
        file_handler.setFormatter(text_formatter)
        file_handler.addFilter(_RunIdFilter())
        logger.addHandler(file_handler)

    if jsonl_file:
        jsonl_file.parent.mkdir(parents=True, exist_ok=True)
        jsonl_handler = logging.FileHandler(jsonl_file)
        jsonl_handler.setLevel(getattr(logging, level.upper()))
        jsonl_handler.setFormatter(_JsonlFormatter())
        jsonl_handler.addFilter(_RunIdFilter())
        logger.addHandler(jsonl_handler)

    return logger


def get_logger(name: str = "routemanager") -> logging.Logger:
    return logging.getLogger(name)
