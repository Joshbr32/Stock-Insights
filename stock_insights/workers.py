"""Background worker objects used by QThread."""

from __future__ import annotations

import urllib.request
from typing import List

from PySide6.QtCore import QObject, Signal

from .data import fetch_marks, get_stock_snapshot
from .logging_utils import get_logger


logger = get_logger("workers")


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


class SnapshotWorker(QObject):
    finished = Signal(dict)
    error = Signal(str)

    def __init__(self, ticker: str):
        super().__init__()
        self.ticker = ticker

    def run(self) -> None:
        try:
            logger.info("Snapshot refresh started for %s", self.ticker)
            snapshot = get_stock_snapshot(self.ticker)
            logger.info("Snapshot refresh completed for %s", self.ticker)
            self.finished.emit(snapshot)
        except Exception as exc:  # pragma: no cover - Qt worker boundary
            logger.exception("Snapshot worker failed for %s", self.ticker)
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
        self.done.emit(ok)
