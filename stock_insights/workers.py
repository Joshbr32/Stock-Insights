"""Background worker objects used by QThread.

Each worker is a plain QObject that MainWindow moves onto a fresh QThread
(`worker.moveToThread(thread)`, `thread.started -> worker.run`).  `run()` does
the blocking work and reports back through signals only; because the
receiving slots live on the GUI thread, Qt queues the delivery there.

Rules for code in this file:
* never touch widgets or any other GUI-thread object from `run()`;
* always emit exactly one result signal, even on failure, because the owner
  quits and deletes the thread from that signal;
* workers are single-use.
"""

from __future__ import annotations

import urllib.request
from typing import Any, Callable, List, Optional, Tuple

from PySide6.QtCore import QObject, QThread, Signal

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
                 args: Tuple = (), kwargs: Optional[dict] = None,
                 label: str = "store-call"):
        super().__init__()
        self._fn = fn
        self._args = args
        self._kwargs = kwargs or {}
        self._label = label

    def run(self) -> None:
        try:
            result = self._fn(*self._args, **self._kwargs)
        except Exception as exc:  # pragma: no cover - Qt worker boundary
            logger.exception("%s failed", self._label)
            self.error.emit(str(exc))
            return
        # Emitted outside the try block: an exception raised while
        # delivering `done` must not be reported as a second, `error` result.
        self.done.emit(result)


class MarksWorker(QObject):
    """Fetch latest prices for `tickers`; emits `done({ticker: price})`."""
    done = Signal(dict)
    error = Signal(str)

    def __init__(self, tickers: List[str]):
        super().__init__()
        # Copied so the GUI thread can keep changing its own list.
        self.tickers = list(tickers)

    def run(self) -> None:
        try:
            logger.info("Marks refresh started for %d instrument(s)", len(self.tickers))
            data = fetch_marks(self.tickers)
            logger.info("Marks refresh completed for %d instrument(s)", len(data))
        except Exception as exc:  # pragma: no cover - Qt worker boundary
            logger.exception("Marks worker failed")
            self.error.emit(str(exc))
            return
        self.done.emit(data)


class NetCheckWorker(QObject):
    """Internet reachability probe; emits `done(True)` when any of a few
    well-known endpoints answers."""
    done = Signal(bool)

    TEST_URLS = (
        "https://www.google.com/generate_204",
        "https://clients3.google.com/generate_204",
        "https://www.msftconnecttest.com/connecttest.txt",
        "https://1.1.1.1",
    )
    PROBE_TIMEOUT_S = 3

    def run(self) -> None:
        ok = False
        try:
            for url in self.TEST_URLS:
                # Offline, the probes can take TEST_URLS x PROBE_TIMEOUT_S in
                # total.  Stop between probes once the owner asked the thread
                # to finish (QThread.requestInterruption) so shutdown is not
                # held up by the remaining ones.
                if QThread.currentThread().isInterruptionRequested():
                    break
                try:
                    logger.debug("Connectivity probe -> %s", url)
                    # `with` closes the socket; a bare urlopen() leaked one
                    # connection per successful probe.
                    with urllib.request.urlopen(url, timeout=self.PROBE_TIMEOUT_S):
                        pass
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
    """Call `store.attempt_reconnect()` (FallbackDataStore) off the GUI
    thread; emits `done(True)` when the server is back and the sync queue
    has been replayed."""
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
