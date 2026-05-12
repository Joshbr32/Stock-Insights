"""Background worker objects used by QThread."""

from __future__ import annotations

import urllib.request
from typing import Any, Callable, List, Tuple

from PySide6.QtCore import QObject, Signal

from .data import fetch_marks
from .logging_utils import get_logger

logger = get_logger("workers")


class StoreCallWorker(QObject):
    """Run a single store call (or any callable) on a background thread,
    then emit either `done(result)` or `error(str)` back to the GUI thread.

    Used for backgrounding network-bound writes — `save_account_trades`,
    `save_watchlist`, etc. — so the calling dialog can close immediately
    instead of blocking the UI for a network roundtrip on slow links.

    The companion helper on MainWindow is `_run_in_background` (see there
    for the QThread lifecycle wiring). Worker instances are single-use:
    the QThread that hosts them quits as soon as `run()` returns, and
    both are deleted via `deleteLater()`.
    """
    done = Signal(object)
    error = Signal(str)

    def __init__(self, fn: Callable[..., Any],
                 args: Tuple = (), kwargs: dict | None = None,
                 label: str = "store-call"):
        super().__init__()
        self._fn = fn
        self._args = args
        self._kwargs = kwargs or {}
        self._label = label

    def run(self) -> None:
        try:
            result = self._fn(*self._args, **self._kwargs)
            self.done.emit(result)
        except Exception as exc:  # pragma: no cover - Qt worker boundary
            logger.exception("%s failed", self._label)
            self.error.emit(str(exc))


class MarksWorker(QObject):
    done = Signal(dict)
    error = Signal(str)

    def __init__(self, tickers: List[str]):
        super().__init__()
        self.tickers = tickers

    def run(self) -> None:
        try:
            logger.info("Marks refresh started for %d instrument(s)", len(self.tickers))
            data = fetch_marks(self.tickers)
            logger.info("Marks refresh completed for %d instrument(s)", len(data))
            self.done.emit(data)
        except Exception as exc:  # pragma: no cover - Qt worker boundary
            logger.exception("Marks worker failed")
            self.error.emit(str(exc))


class NetCheckWorker(QObject):
    done = Signal(bool)

    TEST_URLS = (
        "https://www.google.com/generate_204",
        "https://clients3.google.com/generate_204",
        "https://www.msftconnecttest.com/connecttest.txt",
        "https://1.1.1.1",
    )

    def run(self) -> None:
        ok = False
        try:
            for url in self.TEST_URLS:
                try:
                    logger.debug("Connectivity probe -> %s", url)
                    urllib.request.urlopen(url, timeout=3)
                    logger.info("Connectivity probe succeeded via %s", url)
                    ok = True
                    break
                except Exception as exc:
                    logger.debug("Connectivity probe failed via %s: %s", url, exc)
            if not ok:
                logger.warning("Connectivity probe failed for all endpoints")
        except Exception:  # pragma: no cover - Qt worker boundary
            logger.exception("NetCheckWorker failed")
        self.done.emit(ok)


class ReconnectWorker(QObject):
    done = Signal(bool)

    def __init__(self, store):
        super().__init__()
        self._store = store

    def run(self) -> None:
        try:
            logger.info("Reconnect attempt started")
            ok = bool(self._store.attempt_reconnect())
            logger.info("Reconnect attempt finished: %s", "success" if ok else "no change")
        except Exception:  # pragma: no cover - Qt worker boundary
            logger.exception("Reconnect worker failed")
            ok = False
        self.done.emit(ok)
