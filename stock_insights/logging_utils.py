"""Application logging helpers.

Console output is designed for fast scanning during runtime:
- DEBUG    = cyan   + ellipsis icon
- INFO     = green  + check icon
- WARNING  = yellow + warning icon
- ERROR    = red    + cross icon
- CRITICAL = magenta + bang icon

The file logger keeps full detail without ANSI color codes.
"""

from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path


SERIAL_COUNTER = 0
LOGGER_NAME = "stock_insights"


class _IconColorFormatter(logging.Formatter):
    """Formatter that adds a small level icon and optional ANSI colors."""

    RESET = "\033[0m"
    COLORS = {
        logging.DEBUG: "\033[36m",     # cyan
        logging.INFO: "\033[32m",      # green
        logging.WARNING: "\033[33m",   # yellow
        logging.ERROR: "\033[31m",     # red
        logging.CRITICAL: "\033[35m",  # magenta
    }
    ICONS = {
        logging.DEBUG: "…",
        logging.INFO: "✓",
        logging.WARNING: "!",
        logging.ERROR: "✖",
        logging.CRITICAL: "‼",
    }

    def format(self, record: logging.LogRecord) -> str:
        record.levelicon = self.ICONS.get(record.levelno, "•")
        base = super().format(record)
        color = self.COLORS.get(record.levelno, "")
        if not color or not sys.stdout.isatty():
            return base
        return f"{color}{base}{self.RESET}"


def get_logger(name: str | None = None) -> logging.Logger:
    """Return the shared application logger or a child logger."""
    if not name:
        return logging.getLogger(LOGGER_NAME)
    return logging.getLogger(f"{LOGGER_NAME}.{name}")


def serial_debug(message: str) -> None:
    """Log a numbered debug event to make async flows easier to follow."""
    global SERIAL_COUNTER
    SERIAL_COUNTER += 1
    get_logger("trace").debug("[%04d] %s", SERIAL_COUNTER, message)


def _silence_noisy_loggers() -> None:
    """Reduce third-party debug spam while keeping app debug enabled."""
    for name, level in {
        "matplotlib": logging.WARNING,
        "matplotlib.font_manager": logging.ERROR,
        "PIL": logging.WARNING,
        "urllib3": logging.WARNING,
        "yfinance": logging.WARNING,
        "numexpr": logging.WARNING,
        "asyncio": logging.WARNING,
    }.items():
        logging.getLogger(name).setLevel(level)


def setup_logging() -> logging.Logger:
    """Configure rotating file logging plus a readable colored console logger."""
    log_dir = Path.home() / ".stock_insights_logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "app.log"

    root = logging.getLogger()
    root.setLevel(logging.DEBUG)
    root.handlers.clear()

    file_handler = RotatingFileHandler(
        log_file,
        maxBytes=1_000_000,
        backupCount=3,
        encoding="utf-8",
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(
        logging.Formatter("%(asctime)s | %(levelname)-8s | %(name)s | %(message)s")
    )

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.DEBUG)
    console_handler.setFormatter(
        _IconColorFormatter(
            "%(asctime)s | %(levelicon)s %(levelname)-8s | %(name)s | %(message)s",
            "%H:%M:%S",
        )
    )

    root.addHandler(file_handler)
    root.addHandler(console_handler)
    _silence_noisy_loggers()

    logger = get_logger()
    logger.info("Logging initialized")
    logger.debug("Log file: %s", log_file)
    return logger
