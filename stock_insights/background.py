"""QThread plumbing for running blocking work off the GUI thread.

Two patterns used by MainWindow and the admin windows:

* ``BackgroundCalls.run(fn, ...)`` — fire-and-update: run one callable on a
  fresh QThread, then call ``on_done(result)`` / ``on_error(message)`` on the
  GUI thread. Used for store writes, /health probes, password resets.
* ``SingleFlight.start(worker, ...)`` — at most one worker of a kind at a
  time (marks refresh, connectivity check, reconnect). A second start while
  one is running is ignored.

Why the relay object: in PySide6 a signal connected to a plain Python
function or lambda runs that function in the *emitting* thread. Callbacks
here touch widgets and QML models, so results are routed through a QObject
that lives on the GUI thread; Qt then queues the call onto the GUI thread.
"""
from __future__ import annotations

from typing import Any, Callable, List, Optional, Tuple

from PySide6.QtCore import QObject, QThread, Slot

from .logging_utils import get_logger

_log = get_logger("background")


class _Relay(QObject):
    """Lives on the GUI thread; turns worker signals into GUI-thread callbacks."""

    def __init__(self, on_done: Optional[Callable[[Any], None]],
                 on_error: Optional[Callable[[str], None]], label: str, parent: QObject):
        super().__init__(parent)
        self._on_done = on_done
        self._on_error = on_error
        self._label = label

    @Slot(object)
    def done(self, result: Any) -> None:
        if self._on_done is not None:
            try:
                self._on_done(result)
            except Exception:  # a broken callback must not kill the event loop
                _log.exception("%s: on_done callback failed", self._label)

    @Slot(str)
    def error(self, message: str) -> None:
        if self._on_error is not None:
            try:
                self._on_error(message)
            except Exception:
                _log.exception("%s: on_error callback failed", self._label)


class BackgroundCalls(QObject):
    """Runs one-off callables on their own QThread (see module docstring)."""

    def __init__(self, parent: QObject):
        super().__init__(parent)
        # (thread, worker, relay) triples kept alive until the thread
        # finishes; Python GC would otherwise reap them mid-call.
        self._active: List[Tuple[QThread, QObject, _Relay]] = []

    @property
    def active_count(self) -> int:
        return len(self._active)

    def run(self, fn: Callable[..., Any], args: tuple = (), kwargs: Optional[dict] = None,
            on_done: Optional[Callable[[Any], None]] = None,
            on_error: Optional[Callable[[str], None]] = None,
            label: str = "store-call") -> None:
        from .workers import StoreCallWorker

        thread = QThread(self)
        worker = StoreCallWorker(fn, args=args, kwargs=kwargs or {}, label=label)
        relay = _Relay(on_done, on_error, label, self)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.done.connect(relay.done)
        worker.error.connect(relay.error)
        worker.done.connect(thread.quit)
        worker.error.connect(thread.quit)
        self._active.append((thread, worker, relay))
        # Qt's documented teardown: delete the objects once the thread has
        # really finished. `_reap` only drops our Python references.
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(relay.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self._reap)
        thread.start()

    @Slot()
    def _reap(self) -> None:
        """Forget the thread that just finished (runs on the GUI thread)."""
        finished = self.sender()
        self._active = [e for e in self._active if e[0] is not finished]

    def shutdown(self, wait_ms: int = 2000) -> None:
        """Ask every in-flight thread to stop and wait up to `wait_ms` each.

        Calls already inside a network request cannot be interrupted; they
        finish (bounded by the request timeout) and their results are dropped.
        """
        for thread, _worker, relay in list(self._active):
            try:
                relay._on_done = None
                relay._on_error = None
                thread.requestInterruption()
                thread.quit()
                thread.wait(wait_ms)
            except RuntimeError:
                pass
        self._active.clear()


class SingleFlight(QObject):
    """Owns at most one (QThread, worker) pair at a time.

    `worker` must be a QObject with a `run()` method and either a `done`
    signal, an `error` signal, or both; the thread quits when either fires.
    Connect result handlers in `wire(worker)` to *bound methods of QObjects*
    (or to slots) so they run on the GUI thread.
    """

    def __init__(self, parent: QObject, name: str):
        super().__init__(parent)
        self._name = name
        self._thread: Optional[QThread] = None
        self._worker: Optional[QObject] = None
        self._on_finished: Optional[Callable[[], None]] = None

    def is_running(self) -> bool:
        try:
            return self._thread is not None and self._thread.isRunning()
        except RuntimeError:  # C++ side deleted
            return False

    def start(self, worker: QObject, wire: Callable[[QObject], None],
              on_finished: Optional[Callable[[], None]] = None) -> bool:
        """Start `worker` unless one is already running. Returns True if started."""
        if self.is_running():
            return False
        thread = QThread(self)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        wire(worker)
        for sig_name in ("done", "error"):
            sig = getattr(worker, sig_name, None)
            if sig is not None:
                sig.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self._finished)
        self._thread, self._worker, self._on_finished = thread, worker, on_finished
        thread.start()
        return True

    @Slot()
    def _finished(self) -> None:
        callback = self._on_finished
        self._thread = self._worker = None
        self._on_finished = None
        if callback is not None:
            try:
                callback()
            except Exception:
                _log.exception("%s: on_finished callback failed", self._name)

    def shutdown(self, wait_ms: int = 4000) -> None:
        """Stop the running worker's thread (if any) and wait for it."""
        thread = self._thread
        self._on_finished = None
        if thread is not None:
            try:
                if thread.isRunning():
                    # Workers that loop (NetCheckWorker) stop between steps
                    # once interruption is requested.
                    thread.requestInterruption()
                    thread.quit()
                    thread.wait(wait_ms)
            except RuntimeError:
                pass
        self._thread = self._worker = None
