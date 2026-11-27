"""The manager's window: side menu, verdict bar, the four pages, the status bar.

All data comes from the controller through ``si_controller.client.Client`` on a
worker thread (``Background``); results come back as Qt signals, so the window
never waits on the network. Closing the window changes nothing on the server.

Polling: status every 2 s, server output every 1.5 s (only lines after the last
one seen), events every 5 s. A call still in flight is not repeated.
"""
from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import QObject, QRectF, QRunnable, Qt, QThreadPool, QTimer, Signal
from PySide6.QtGui import QIcon, QKeySequence, QPainter, QPixmap, QShortcut
from PySide6.QtWidgets import (QHBoxLayout, QLabel, QListWidget, QMainWindow, QMessageBox,
                               QStackedWidget, QStatusBar, QVBoxLayout, QWidget)

from si_controller.client import ControllerError
from si_controller.words import verdict

from . import APP_NAME, theme
from .pages import DashboardPage, EventsPage, OutputPage, TasksPage
from .tasks import Task, build_tasks, run as run_task
from .widgets import VerdictBar, draw_mark


class _Signals(QObject):
    done = Signal(object)
    failed = Signal(str)


class _Job(QRunnable):
    def __init__(self, fn):
        super().__init__()
        self.fn = fn
        self.signals = _Signals()

    def run(self):
        try:
            result = self.fn()
        except ControllerError as exc:
            self.signals.failed.emit(str(exc))
        except Exception as exc:  # noqa: BLE001 - shown in the status bar, never a crash
            self.signals.failed.emit(f"Unexpected error: {exc}")
        else:
            self.signals.done.emit(result)


class Background(QObject):
    """Runs a function on the thread pool; at most one call per key at a time."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(3)
        self._busy: set[str] = set()
        self._jobs: set[_Job] = set()

    def run(self, key: str, fn, on_done, on_failed=None) -> None:
        if key in self._busy:
            return
        self._busy.add(key)
        job = _Job(fn)
        self._jobs.add(job)                      # keep the signals object alive

        def finish(handler, value):
            self._busy.discard(key)
            self._jobs.discard(job)
            if handler:
                handler(value)

        job.signals.done.connect(lambda v: finish(on_done, v))
        job.signals.failed.connect(lambda m: finish(on_failed, m))
        self.pool.start(job)

    def wait(self, ms: int = 3000) -> None:
        self.pool.waitForDone(ms)


def app_icon() -> QIcon:
    pm = QPixmap(64, 64)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    draw_mark(p, QRectF(4, 4, 56, 56), "good")
    p.end()
    return QIcon(pm)


class NavList(QListWidget):
    """The side menu. Its selected entry gets a focus ring while it has keyboard focus
    (a ring around the whole list read as a frame, not as focus)."""

    def _focused(self, on: bool) -> None:
        self.setProperty("focused", on)
        self.style().unpolish(self)
        self.style().polish(self)

    def focusInEvent(self, event):  # noqa: N802
        self._focused(True)
        super().focusInEvent(event)

    def focusOutEvent(self, event):  # noqa: N802
        self._focused(False)
        super().focusOutEvent(event)


class MainWindow(QMainWindow):
    PAGES = ("Dashboard", "Server output", "Events", "Tasks")

    def __init__(self, client, poll: bool = True):
        super().__init__()
        self.client = client
        self.bg = Background(self)
        self.status: dict | None = None
        self.last_answer: datetime | None = None
        self.unreachable_since: datetime | None = None
        self._log_seq = 0
        self.setWindowTitle(APP_NAME)
        self.setWindowIcon(app_icon())
        self.resize(1040, 720)

        central = QWidget()
        central.setObjectName("page")
        outer = QHBoxLayout(central)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        side = QWidget()
        side.setObjectName("page")
        side.setFixedWidth(196)
        side_lay = QVBoxLayout(side)
        side_lay.setContentsMargins(0, 18, 0, 12)
        side_lay.setSpacing(12)
        title = QLabel("Stock Insights\nServer Manager")
        title.setFont(theme.font(15, 600))
        title.setContentsMargins(20, 0, 12, 4)
        side_lay.addWidget(title)
        self.nav = NavList()
        self.nav.setObjectName("nav")
        self.nav.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.nav.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.nav.addItems(self.PAGES)
        self.nav.setAccessibleName("Sections")
        side_lay.addWidget(self.nav, 1)
        outer.addWidget(side)

        main = QWidget()
        main.setObjectName("page")
        main_lay = QVBoxLayout(main)
        main_lay.setContentsMargins(8, 16, 20, 8)
        main_lay.setSpacing(12)
        self.verdict = VerdictBar()
        main_lay.addWidget(self.verdict)
        self.stack = QStackedWidget()
        self.dashboard = DashboardPage()
        self.output = OutputPage()
        self.events = EventsPage()
        self.tasks = TasksPage()
        for page in (self.dashboard, self.output, self.events, self.tasks):
            self.stack.addWidget(page)
        main_lay.addWidget(self.stack, 1)
        outer.addWidget(main, 1)
        self.setCentralWidget(central)

        self.nav.currentRowChanged.connect(self.stack.setCurrentIndex)
        self.nav.setCurrentRow(0)
        for i in range(len(self.PAGES)):
            QShortcut(QKeySequence(f"Ctrl+{i + 1}"), self,
                      activated=lambda i=i: self.nav.setCurrentRow(i))
        QShortcut(QKeySequence("F5"), self, activated=self.poll_all)

        bar = QStatusBar()
        bar.setSizeGripEnabled(False)
        self.message = QLabel("Ctrl+1 to Ctrl+4 switch sections. F5 refreshes.")
        self.updated = QLabel("Connecting to the controller…")
        bar.addWidget(self.message, 1)
        bar.addPermanentWidget(self.updated)
        self.setStatusBar(bar)

        self.dashboard.action.connect(self.request_action)
        self.tasks.run.connect(self.run_task)
        self.output.copied = self.say
        self.tasks.copied = self.say
        self.tasks.set_tasks(build_tasks(home=client.root))
        self.apply_status(None, initial=True)

        if poll:
            self._timers = []
            for ms, fn in ((2000, self.poll_status), (1500, self.poll_logs), (5000, self.poll_events)):
                t = QTimer(self)
                t.timeout.connect(fn)
                t.start(ms)
                self._timers.append(t)
            QTimer.singleShot(0, self.poll_all)

    # ------------------------------------------------------------- polling
    def poll_all(self) -> None:
        self.poll_status()
        self.poll_logs()
        self.poll_events()

    def poll_status(self) -> None:
        self.bg.run("status", self.client.status, self.apply_status,
                    lambda msg: self.apply_status(None, error=msg))

    def poll_logs(self) -> None:
        since = self._log_seq
        self.bg.run("logs", lambda: self.client.logs(since, 2000), self.apply_logs)

    def poll_events(self) -> None:
        self.bg.run("events", lambda: self.client.events(300), self.apply_events)

    def apply_events(self, events: list[dict]) -> None:
        self.events.set_events(events)
        self.dashboard.set_recent(events)

    def apply_logs(self, data: dict) -> None:
        lines = data.get("lines", [])
        latest = data.get("latest", 0)
        if latest < self._log_seq:           # the controller restarted: numbering began again
            self._log_seq = 0
            return
        if lines:
            self.output.append(lines, gap=bool(data.get("gap")) and self._log_seq > 0)
            self._log_seq = lines[-1]["seq"]

    def apply_status(self, status: dict | None, error: str | None = None,
                     initial: bool = False) -> None:
        now = datetime.now()
        if status is not None:
            self.status = status
            self.last_answer = now
            self.unreachable_since = None
            self.updated.setObjectName("")
            self.updated.setText(f"Updated {now:%H:%M:%S}")
        elif not initial:
            if self.unreachable_since is None:
                self.unreachable_since = now
            since = self.last_answer or self.unreachable_since
            self.updated.setObjectName("stale")
            self.updated.setText(f"No answer from the controller since {since:%H:%M:%S}.")
            self.updated.setToolTip(error or "")
            self.status = None
        self.updated.style().unpolish(self.updated)
        self.updated.style().polish(self.updated)

        tone, sentence = verdict(status)
        if initial:
            tone, sentence = "idle", "Asking the controller…"
        elif status is None:
            since = self.last_answer or self.unreachable_since
            sentence = (f"No answer from the controller since {since:%H:%M:%S}, "
                        "so the server's state is unknown.")
        facts = ""
        if status:
            facts = f"Controller {status['controller'].get('version', '')}"
            sql = (status.get("machine", {}).get("sql") or {}).get("name")
            if sql:
                self.tasks.set_tasks(build_tasks(sql, home=self.client.root))
        self.verdict.set(tone, sentence, facts)
        self.dashboard.update_status(status)

    # ------------------------------------------------------------- actions
    def say(self, text: str) -> None:
        self.message.setText(text)

    def request_action(self, action: str) -> None:
        if action == "stop":
            box = QMessageBox(self)
            box.setIcon(QMessageBox.Warning)
            box.setWindowTitle("Stop the server?")
            box.setText("Stop the sync server?")
            box.setInformativeText("Phones and the desktop app can't sync until it is started "
                                   "again. It will also not restart by itself until you press "
                                   "Start (or the PC restarts).")
            stop = box.addButton("Stop server", QMessageBox.DestructiveRole)
            box.addButton("Keep running", QMessageBox.RejectRole)
            box.setDefaultButton(box.buttons()[-1])
            box.exec()
            if box.clickedButton() is not stop:
                self.say("Nothing changed.")
                return
        words = {"start": "Starting", "restart": "Restarting", "stop": "Stopping"}[action]
        self.say(f"{words} the server…")
        self.bg.run(f"cmd-{action}", lambda: self.client.command(action),
                    lambda _r: (self.say(f"Asked the controller to {action} the server."),
                                self.poll_status()),
                    lambda msg: self.say(f"Could not {action} the server: {msg}"))

    def run_task(self, task: Task) -> None:
        try:
            sentence = run_task(task)
        except OSError as exc:
            sentence = f"Could not start \"{task.title}\": {exc}"
        self.tasks.show_result(task, sentence)
        self.say(sentence)

    def closeEvent(self, event):  # noqa: N802
        for t in getattr(self, "_timers", []):
            t.stop()
        self.bg.wait(2000)
        super().closeEvent(event)
