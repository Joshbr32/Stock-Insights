"""The four pages: Dashboard, Server output, Events, Tasks.

Pages only display what they are given and emit what the user asked for; the
window (``window.py``) does every call to the controller off the UI thread.
"""
from __future__ import annotations

import re
from datetime import datetime

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import (QGuiApplication, QKeySequence, QShortcut, QSyntaxHighlighter,
                           QTextCharFormat, QTextCursor, QTextDocument, QTextOption)
from PySide6.QtWidgets import (QAbstractItemView, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
                               QPlainTextEdit, QPushButton, QScrollArea, QTableWidget,
                               QTableWidgetItem, QTextEdit, QVBoxLayout, QWidget)

from si_controller.words import STATE_WORDS, duration, service_line, state_tone

from . import theme
from .tasks import Task
from .widgets import CheckRow, Facts, Panel, StateMark, mark_icon, muted

def clock(iso: str | None, with_day: bool = False) -> str:
    """``14:03:22``, or ``25 Nov 14:03`` for another day when ``with_day``."""
    if not iso:
        return ""
    try:
        at = datetime.fromisoformat(iso)
    except ValueError:
        return iso
    if with_day and at.date() != datetime.now().date():
        return at.strftime("%d %b %H:%M").lstrip("0")
    return at.strftime("%H:%M:%S")


# ---------------------------------------------------------------- Dashboard
class DashboardPage(QWidget):
    action = Signal(str)          # "start" | "restart" | "stop"

    def __init__(self):
        super().__init__()
        self.setObjectName("page")
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(12)

        server = Panel("Sync server")
        head = QHBoxLayout()
        head.setSpacing(8)
        self.state = StateMark(size=22, text_px=20)
        head.addWidget(self.state, 1)
        self.start_btn = QPushButton("Start")
        self.restart_btn = QPushButton("Restart")
        self.stop_btn = QPushButton("Stop…")
        self.stop_btn.setObjectName("danger")
        for btn, name in ((self.start_btn, "start"), (self.restart_btn, "restart"),
                          (self.stop_btn, "stop")):
            btn.clicked.connect(lambda _=False, n=name: self.action.emit(n))
            btn.setMinimumWidth(84)
        head.addWidget(self.start_btn)
        head.addWidget(self.restart_btn)
        head.addSpacing(12)               # Stop stands a little apart
        head.addWidget(self.stop_btn)
        server.body.addLayout(head)
        self.reason = QLabel()
        self.reason.setWordWrap(True)
        self.reason.setTextInteractionFlags(Qt.TextSelectableByMouse)
        server.body.addWidget(self.reason)
        server.body.addSpacing(4)
        self.facts = Facts([("uptime", "Up for"), ("version", "Server version"),
                            ("restarts", "Automatic restarts"), ("checked", "Last health check"),
                            ("memory", "Memory"), ("cpu", "Processor"), ("pid", "Process"),
                            ("port", "Port")], columns=4)
        server.body.addWidget(self.facts)
        root.addWidget(server)

        row = QHBoxLayout()
        row.setSpacing(12)
        db = Panel("Database")
        self.db_reach = CheckRow()
        self.db_schema = CheckRow()
        self.db_note = muted()
        self.db_note.setWordWrap(True)
        for w in (self.db_reach, self.db_schema, self.db_note):
            db.body.addWidget(w)
        db.body.addStretch(1)
        pc = Panel("This PC")
        self.sql = CheckRow()
        self.tunnel = CheckRow()
        self.disk = CheckRow()
        self.controller = CheckRow()
        for w in (self.sql, self.tunnel, self.disk, self.controller):
            pc.body.addWidget(w)
        pc.body.addStretch(1)
        row.addWidget(db, 1)
        row.addWidget(pc, 1)
        root.addLayout(row)

        recent = Panel("Latest from the controller")
        self.recent_rows = [CheckRow() for _ in range(4)]
        for r in self.recent_rows:
            recent.body.addWidget(r)
        self.recent_empty = muted("Nothing yet.")
        recent.body.addWidget(self.recent_empty)
        root.addWidget(recent)
        root.addStretch(1)

    def set_recent(self, events: list[dict]) -> None:
        latest = list(reversed(events[-len(self.recent_rows):]))
        for i, row in enumerate(self.recent_rows):
            if i < len(latest):
                ev = latest[i]
                tone = EVENT_LOOK.get(ev.get("kind", ""), ("idle", ""))[0]
                row.set(tone, f"{clock(ev.get('at'), True)}  {ev.get('message', '')}")
            row.setVisible(i < len(latest))
        self.recent_empty.setVisible(not latest)

    def update_status(self, status: dict | None) -> None:
        reachable = status is not None
        srv = (status or {}).get("server", {})
        state = srv.get("state", "")
        health = srv.get("health") or {}
        hd = health.get("data") or {}
        usage = srv.get("usage") or {}

        if not reachable:
            self.state.set_state("idle", "Unknown")
            self.reason.setText("The controller is not answering, so nothing here is current. "
                                "Start it with Tasks > Turn on autostart, or run "
                                "python -m si_controller run.")
        else:
            tone = state_tone(state, bool(health.get("ok")))
            self.state.set_state(tone, STATE_WORDS.get(state, state.capitalize()))
            self.reason.setText(self._reason(srv))
        self.reason.setVisible(bool(self.reason.text()))
        running = state in ("starting", "running")
        self.start_btn.setEnabled(reachable and state in ("stopped", "failed", "backoff", "waiting"))
        self.restart_btn.setEnabled(reachable and state in ("running", "starting", "backoff",
                                                             "failed"))
        self.stop_btn.setEnabled(reachable and state not in ("stopped", "stopping", "failed"))

        f = self.facts
        f.set("uptime", duration(srv.get("uptime_seconds")) if running else "")
        f.set("version", hd.get("server_version", ""))
        f.set("restarts", str(srv.get("restarts", "")) if reachable else "")
        f.set("checked", clock(health.get("checked_at")))
        f.set("memory", f"{usage['working_set_mb']:.0f} MB" if usage.get("working_set_mb") else "")
        f.set("cpu", f"{usage['cpu_percent']:.1f} %" if usage.get("cpu_percent") is not None else "")
        f.set("pid", str(srv.get("pid") or ""))
        f.set("port", str(srv.get("port", "")))

        # Database: as the server's own /health reports it
        if not health.get("alive"):
            self.db_reach.set("idle", "Not known: the server is not answering.")
            self.db_schema.set("idle", "Schema not known.")
            self.db_note.setText("")
        else:
            if hd.get("db_ok"):
                self.db_reach.set("good", "The server can reach the database.")
            else:
                self.db_reach.set("bad", "The server can't reach the database: "
                                         f"{hd.get('db_error') or 'no reason given'}.")
            self.db_schema.set(*self._schema(hd))
            self.db_note.setText(f"From the server's health check at {clock(health.get('checked_at'))}.")

        machine = (status or {}).get("machine", {})
        if reachable:
            self.sql.set(*service_line("SQL Server", machine.get("sql")))
            self.tunnel.set(*service_line("Cloudflare tunnel", machine.get("tunnel")))
            disk = machine.get("disk")
            if disk:
                low = disk["free_gb"] < 10
                self.disk.set("warn" if low else "good",
                              f"Disk {disk['path']}: {disk['free_gb']:.0f} GB free of "
                              f"{disk['total_gb']:.0f} GB" + (" (running low)" if low else ""))
            else:
                self.disk.set("idle", "Disk space not known.")
            ctl = status.get("controller", {})
            self.controller.set("good", f"Controller {ctl.get('version', '')}: running for "
                                        f"{duration(ctl.get('uptime_seconds'))}")
        else:
            for row, label in ((self.sql, "SQL Server"), (self.tunnel, "Cloudflare tunnel"),
                               (self.disk, "Disk")):
                row.set("idle", f"{label}: not known")
            self.controller.set("bad", "Controller: not answering")

    @staticmethod
    def _reason(srv: dict) -> str:
        state = srv.get("state")
        msg = (srv.get("message") or "").strip()
        if state == "waiting":
            return f"Waiting because {msg[0].lower() + msg[1:] if msg else 'of a check'}"
        if state == "backoff":
            wait = duration(srv.get("retry_in_seconds"))
            return f"{msg} Restarting in {wait}." if wait else msg
        if state == "failed":
            return (f"{msg}. Look at Server output for the cause, then press Start."
                    .replace("..", "."))
        if state == "stopped" and srv.get("last_exit"):
            ex = srv["last_exit"]
            cmd = srv.get("last_command") or {}
            who = f" by {cmd['who']}" if cmd.get("action") == "stop" and cmd.get("who") else ""
            return f"Stopped{who} at {clock(ex.get('at'), True)} (exit code {ex.get('code')})."
        health = srv.get("health") or {}
        if state == "running" and not health.get("ok") and health.get("detail"):
            return f"The health check says: {health['detail']}"
        return ""

    @staticmethod
    def _schema(hd: dict) -> tuple[str, str]:
        schema = hd.get("schema")             # server 1.1+: "ok" | "needs_migration"
        if schema == "ok":
            return "good", "The database schema is up to date."
        if schema == "needs_migration":
            return "warn", ("The database schema needs migration 001, and the server's login "
                            "could not apply it. Run Tasks > Update the database schema.")
        version = hd.get("schema_version")
        if version is None:
            return "idle", "This server version does not report its database schema."
        expected = hd.get("schema_expected")
        ok = hd.get("schema_ok")
        if ok is False or (expected is not None and expected != version):
            want = f"; this server expects {expected}" if expected is not None else ""
            return "warn", (f"Database schema is version {version}{want}. "
                            "Run Tasks > Update the database schema.")
        return "good", f"Database schema is version {version}, as expected."


# ------------------------------------------------------------- Server output
_ERROR_RE = re.compile(r"\b(ERROR|CRITICAL|FATAL|Traceback)\b|\b[A-Z]\w*(Error|Exception)\b")
_WARN_RE = re.compile(r"\b(WARNING|WARN|Warning)\b")
MARK_ERROR, MARK_WARN = "✕", "!"


class _OutputHighlighter(QSyntaxHighlighter):
    """Errors in the ``bad`` colour; warnings on an amber tint. The mark glyph after
    the time (``✕`` or ``!``) says the same thing without colour."""

    def highlightBlock(self, text: str):  # noqa: N802
        if len(text) < 11:
            return
        mark = text[10]
        muted_fmt = QTextCharFormat()
        muted_fmt.setForeground(theme.qc("text_muted"))
        self.setFormat(0, 8, muted_fmt)
        if mark == MARK_ERROR:
            fmt = QTextCharFormat()
            fmt.setForeground(theme.qc("bad"))
            self.setFormat(10, len(text) - 10, fmt)
            bold = QTextCharFormat(fmt)
            bold.setFontWeight(700)
            self.setFormat(10, 1, bold)
        elif mark == MARK_WARN:
            fmt = QTextCharFormat()
            fmt.setBackground(theme.qc("warn_tint"))
            self.setFormat(10, len(text) - 10, fmt)
            glyph = QTextCharFormat(fmt)
            glyph.setForeground(theme.qc("warn"))
            glyph.setFontWeight(700)
            self.setFormat(10, 1, glyph)


class OutputPage(QWidget):
    def __init__(self):
        super().__init__()
        self.setObjectName("page")
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(12)
        panel = Panel()
        bar = QHBoxLayout()
        bar.setSpacing(8)
        self.find = QLineEdit()
        self.find.setPlaceholderText("Find in output")
        self.find.setClearButtonEnabled(True)
        self.find.setMaximumWidth(280)
        self.find.returnPressed.connect(lambda: self.find_next(backward=False))
        self.find.textChanged.connect(self._mark_matches)
        QShortcut(QKeySequence("Shift+Return"), self.find,
                  activated=lambda: self.find_next(backward=True))
        QShortcut(QKeySequence.Find, self, activated=lambda: (self.find.setFocus(),
                                                                self.find.selectAll()))
        self.matches = muted()
        self.pause = QPushButton("Pause")
        self.pause.setCheckable(True)
        self.pause.toggled.connect(self._paused)
        self.wrap = QPushButton("Wrap long lines")
        self.wrap.setCheckable(True)
        self.wrap.toggled.connect(self._wrap)
        copy = QPushButton("Copy all")
        copy.clicked.connect(self._copy)
        bar.addWidget(self.find)
        bar.addWidget(self.matches)
        bar.addStretch(1)
        bar.addWidget(self.pause)
        bar.addWidget(self.wrap)
        bar.addWidget(copy)
        panel.body.addLayout(bar)

        self.view = QPlainTextEdit()
        self.view.setObjectName("output")
        self.view.setReadOnly(True)
        self.view.setFont(theme.mono_font(12))
        self.view.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.view.setMaximumBlockCount(5000)
        self.view.setTextInteractionFlags(Qt.TextSelectableByMouse | Qt.TextSelectableByKeyboard)
        self.view.setAccessibleName("Server output")
        self._hl = _OutputHighlighter(self.view.document())
        panel.body.addWidget(self.view, 1)
        self.note = muted("Errors are marked ✕ and shown in red; warnings are marked ! on an "
                          "amber band. Secrets are replaced with [redacted] before they are kept.")
        self.note.setWordWrap(True)
        panel.body.addWidget(self.note)
        root.addWidget(panel, 1)

        self._pending: list[str] = []
        self._in_traceback = False
        self.copied = None            # set by the window: shows a status message

    def format_line(self, entry: dict) -> str:
        text = entry.get("text", "")
        if text.startswith("Traceback"):
            self._in_traceback = True
        elif self._in_traceback and not (text.startswith(" ") or text.startswith("\t")):
            # The last line of a traceback ("ValueError: ...") still belongs to it.
            self._in_traceback = False
            return f"{clock(entry.get('at'))}  {MARK_ERROR}  {text}"
        if self._in_traceback or _ERROR_RE.search(text):
            mark = MARK_ERROR
        elif _WARN_RE.search(text):
            mark = MARK_WARN
        else:
            mark = " "
        return f"{clock(entry.get('at'))}  {mark}  {text}"

    def append(self, entries: list[dict], gap: bool = False) -> None:
        lines = [self.format_line(e) for e in entries]
        if gap:
            lines.insert(0, f"{'':8}  !  (Some earlier lines were not fetched; see server.log.)")
        if not lines:
            return
        if self.pause.isChecked():
            self._pending.extend(lines)
            self.matches.setText(f"Paused. {len(self._pending)} new lines are waiting.")
            return
        self._write(lines)

    def _write(self, lines: list[str]) -> None:
        bar = self.view.verticalScrollBar()
        at_bottom = bar.value() >= bar.maximum() - 4
        self.view.appendPlainText("\n".join(lines))
        if at_bottom:
            bar.setValue(bar.maximum())
        if self.find.text():
            self._mark_matches(self.find.text())

    def _paused(self, on: bool) -> None:
        self.pause.setText("Paused" if on else "Pause")
        if not on and self._pending:
            pending, self._pending = self._pending, []
            self._write(pending)
            self.matches.setText("")

    def _wrap(self, on: bool) -> None:
        self.view.setLineWrapMode(QPlainTextEdit.WidgetWidth if on else QPlainTextEdit.NoWrap)

    def _copy(self) -> None:
        QGuiApplication.clipboard().setText(self.view.toPlainText())
        if self.copied:
            self.copied("Copied the server output.")

    def find_next(self, backward: bool = False) -> None:
        word = self.find.text()
        if not word:
            return
        flags = QTextDocument.FindBackward if backward else QTextDocument.FindFlag(0)
        if not self.view.find(word, flags):
            cursor = self.view.textCursor()
            cursor.movePosition(QTextCursor.End if backward else QTextCursor.Start)
            self.view.setTextCursor(cursor)
            self.view.find(word, flags)

    def _mark_matches(self, word: str) -> None:
        selections = []
        if word:
            fmt = QTextCharFormat()
            fmt.setBackground(theme.qc("primary", 70))
            cursor = self.view.document().find(word)
            while not cursor.isNull() and len(selections) < 2000:
                sel = QTextEdit.ExtraSelection()
                sel.cursor = cursor
                sel.format = fmt
                selections.append(sel)
                cursor = self.view.document().find(word, cursor)
            if not self._pending:
                self.matches.setText(f"{len(selections)} match{'es' if len(selections) != 1 else ''}")
        elif not self._pending:
            self.matches.setText("")
        self.view.setExtraSelections(selections)


# -------------------------------------------------------------------- Events
EVENT_LOOK = {
    "running": ("good", "Running"), "spawned": ("busy", "Started"),
    "start_requested": ("idle", "Asked"), "stop_requested": ("idle", "Asked"),
    "restart_requested": ("idle", "Asked"), "stopped": ("idle", "Stopped"),
    "exited": ("bad", "Exited"), "hung": ("bad", "Not answering"),
    "start_timeout": ("bad", "No answer"), "spawn_failed": ("bad", "Could not start"),
    "killed": ("warn", "Forced"), "failed": ("bad", "Gave up"), "waiting": ("warn", "Waiting"),
    "controller_started": ("idle", "Controller"), "controller_stopping": ("idle", "Controller"),
    "api_failed": ("bad", "Controller"),
}


class EventsPage(QWidget):
    def __init__(self):
        super().__init__()
        self.setObjectName("page")
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        panel = Panel()
        panel.body.addWidget(muted("What the controller did and why, newest first. "
                                   "The full history is events.jsonl in the logs folder."))
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Kind", "When", "What happened"])
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(32)
        self.table.setShowGrid(False)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setWordWrap(False)
        self.table.setFocusPolicy(Qt.StrongFocus)
        head = self.table.horizontalHeader()
        head.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        head.setSectionResizeMode(0, QHeaderView.Fixed)
        head.setSectionResizeMode(1, QHeaderView.Fixed)
        head.setSectionResizeMode(2, QHeaderView.Stretch)
        self.table.setColumnWidth(0, 150)
        self.table.setColumnWidth(1, 130)
        self.table.setAccessibleName("Controller events")
        panel.body.addWidget(self.table, 1)
        root.addWidget(panel, 1)
        self._shown: list[dict] = []

    def set_events(self, events: list[dict]) -> None:
        if events == self._shown:
            return
        self._shown = list(events)
        rows = list(reversed(events))
        self.table.setRowCount(len(rows))
        for i, ev in enumerate(rows):
            tone, word = EVENT_LOOK.get(ev.get("kind", ""), ("idle", "Note"))
            kind = QTableWidgetItem(mark_icon(tone), word)
            when = QTableWidgetItem(clock(ev.get("at"), with_day=True))
            what = QTableWidgetItem(ev.get("message", ""))
            what.setToolTip(ev.get("message", ""))
            for col, item in enumerate((kind, when, what)):
                self.table.setItem(i, col, item)


# --------------------------------------------------------------------- Tasks
class TasksPage(QWidget):
    run = Signal(object)          # Task

    def __init__(self):
        super().__init__()
        self.setObjectName("page")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        holder = QWidget()
        holder.setObjectName("page")
        self.lay = QVBoxLayout(holder)
        self.lay.setContentsMargins(0, 0, 0, 0)
        self.lay.setSpacing(12)
        scroll.setWidget(holder)
        outer.addWidget(scroll)
        self._results: dict[str, QLabel] = {}
        self._tasks: list[Task] = []
        self.copied = None

    def set_tasks(self, tasks: list[Task]) -> None:
        if [t for t in tasks] == self._tasks:
            return
        self._tasks = list(tasks)
        while self.lay.count():
            item = self.lay.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        for task in tasks:
            self.lay.addWidget(self._card(task))
        self.lay.addStretch(1)

    def _card(self, task: Task) -> Panel:
        panel = Panel(task.title)
        desc = QLabel(task.description)
        desc.setWordWrap(True)
        panel.body.addWidget(desc)
        cmd = QPlainTextEdit(task.command)
        cmd.setObjectName("command")
        cmd.setReadOnly(True)
        cmd.setFont(theme.mono_font(12))
        cmd.setWordWrapMode(QTextOption.WrapAtWordBoundaryOrAnywhere)
        cmd.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        cmd.setFixedHeight(cmd.fontMetrics().lineSpacing() * 2 + 16)
        cmd.setTabChangesFocus(True)
        cmd.setAccessibleName(f"Command for {task.title}")
        panel.body.addWidget(cmd)
        row = QHBoxLayout()
        row.setSpacing(8)
        run = QPushButton("Run…" if task.elevated else "Open")
        if task.key == "uninstall":
            run.setObjectName("danger")
        run.setEnabled(not task.missing)
        run.clicked.connect(lambda _=False, t=task: self.run.emit(t))
        copy = QPushButton("Copy command")
        copy.clicked.connect(lambda _=False, t=task: self._copy(t))
        row.addWidget(run)
        row.addWidget(copy)
        note = muted(task.missing or ("Needs administrator rights: Windows will ask, and it runs "
                                      "in its own window." if task.elevated else ""))
        note.setWordWrap(True)
        row.addSpacing(8)
        row.addWidget(note, 1)
        panel.body.addLayout(row)
        result = muted()
        result.setVisible(False)
        panel.body.addWidget(result)
        self._results[task.key] = result
        return panel

    def _copy(self, task: Task) -> None:
        QGuiApplication.clipboard().setText(task.command)
        if self.copied:
            self.copied(f"Copied the command for \"{task.title}\".")

    def show_result(self, task: Task, sentence: str) -> None:
        label = self._results.get(task.key)
        if label:
            label.setText(sentence)
            label.setVisible(True)
