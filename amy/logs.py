"""Structured logging for Amy: console lines, rotating JSONL file, per-turn ids, redaction."""

from __future__ import annotations

import contextlib
import contextvars
import json
import logging
import logging.handlers
import os
import sys
import time
import uuid
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any, Optional

ROOT_LOGGER = "amy"

_turn_id: contextvars.ContextVar[str] = contextvars.ContextVar("amy_turn_id", default="")
_redact: Optional[Callable[[str], str]] = None
_configured = False


def current_turn_id() -> str:
    return _turn_id.get()


@contextlib.contextmanager
def turn_context(turn_id: Optional[str] = None) -> Iterator[str]:
    """Tag every log line (and audit record) emitted in this context with a turn id."""
    tid = turn_id or uuid.uuid4().hex[:10]
    token = _turn_id.set(tid)
    try:
        yield tid
    finally:
        _turn_id.reset(token)


def set_redactor(fn: Optional[Callable[[str], str]]) -> None:
    """Scrub secrets from every log message before it reaches any handler."""
    global _redact
    _redact = fn


class _ContextFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.turn_id = _turn_id.get()
        fn = _redact
        if fn is not None:
            try:
                msg = record.getMessage()
                clean = fn(msg)
                if clean != msg:
                    record.msg, record.args = clean, None
            except Exception:  # never let redaction break logging
                record.msg, record.args = "[log message dropped: redaction failed]", None
        return True


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        out: dict[str, Any] = {
            "ts": round(record.created, 3),
            "level": record.levelname.lower(),
            "logger": record.name,
            "msg": record.getMessage(),
            "where": f"{record.module}.{record.funcName}:{record.lineno}",
            "thread": record.threadName,
        }
        tid = getattr(record, "turn_id", "")
        if tid:
            out["turn"] = tid
        if record.exc_info:
            out["exc"] = self.formatException(record.exc_info)
            fn = _redact
            if fn is not None:
                out["exc"] = fn(out["exc"])
        return json.dumps(out, ensure_ascii=False, default=str)


class ConsoleFormatter(logging.Formatter):
    """Keeps the familiar ``# amy …`` console style; adds level only when it matters."""

    def format(self, record: logging.LogRecord) -> str:
        level = "" if record.levelno == logging.INFO else f"{record.levelname.lower()}: "
        tid = getattr(record, "turn_id", "")
        tag = f"[{tid}] " if tid and record.levelno >= logging.INFO else ""
        line = f"# amy {tag}{level}{record.getMessage()}"
        if record.exc_info and record.levelno >= logging.WARNING:
            line += "\n" + self.formatException(record.exc_info)
        return line


def log_dir() -> Path:
    root = Path(os.environ.get("AMY_ROOT") or Path.cwd())
    return Path(os.environ.get("AMY_LOG_DIR") or root / "logs")


def setup_logging(*, level: Optional[str] = None, file: bool = True) -> logging.Logger:
    """Idempotent. ``AMY_LOG_LEVEL`` controls the console; the file always records DEBUG."""
    global _configured
    logger = logging.getLogger(ROOT_LOGGER)
    if _configured:
        return logger
    logger.setLevel(logging.DEBUG)
    logger.propagate = False
    ctx = _ContextFilter()

    console = logging.StreamHandler(sys.stdout)
    console.setLevel((level or os.environ.get("AMY_LOG_LEVEL") or "INFO").upper())
    console.setFormatter(ConsoleFormatter())
    console.addFilter(ctx)
    logger.addHandler(console)

    if file and (os.environ.get("AMY_LOG_FILE", "1").lower() not in ("0", "false", "off")):
        try:
            d = log_dir()
            d.mkdir(parents=True, exist_ok=True)
            fh = logging.handlers.RotatingFileHandler(
                d / "amy.jsonl", maxBytes=5 * 1024 * 1024, backupCount=5, encoding="utf-8"
            )
            fh.setLevel(logging.DEBUG)
            fh.setFormatter(JsonFormatter())
            fh.addFilter(ctx)
            logger.addHandler(fh)
        except OSError as e:
            logger.warning("file logging disabled: %s", e)
    _configured = True
    logger.debug("logging configured pid=%s at=%s", os.getpid(), time.strftime("%Y-%m-%dT%H:%M:%S"))
    return logger


def get_logger(name: str) -> logging.Logger:
    """Module loggers live under ``amy.`` so one configuration covers everything."""
    if name == ROOT_LOGGER or name.startswith(ROOT_LOGGER + "."):
        return logging.getLogger(name)
    return logging.getLogger(f"{ROOT_LOGGER}.{name}")
