"""connection_dialog.py — startup sign-in dialog.

Tries the sync server (external Cloudflare Tunnel URL, then the LAN URL)
on a background thread with retries, and offers "Work offline" (local
QSettings storage only). On success it returns a FallbackDataStore that
wraps the RemoteDataStore with a LocalDataStore cache.

`ConnectionDialog().run()` returns the DataStore, or None if the user quit.
Connection details (the step-by-step log) are hidden behind a toggle.
"""

from __future__ import annotations

import logging
import socket
import threading
import traceback
from typing import Optional

from PySide6.QtCore import QSettings, QThread, Signal
from PySide6.QtWidgets import (
    QDialog,
    QLineEdit,
    QPushButton,
    QTextEdit,
)

from .api_client import APIError, DataStore, FallbackDataStore, LocalDataStore, RemoteDataStore, remote_login
from .widgets import add_dialog_buttons, dialog_layout, heading_label, make_form, muted_label, set_text_role

_ORG = "StockInsights"
_APP = "StocksGUI"
_USER_KEY = "server/last_username"

# Cloudflare Tunnel — terminates HTTPS at the edge and proxies to the
# origin on the home LAN. Port stays implicit (443 for https).
SERVER_URL_EXTERNAL = "https://si.coloniallawns.ca"
SERVER_URL_LOCAL = "http://192.168.0.149:8742"

CONNECT_TIMEOUT = 5
MAX_RETRIES = 3
RETRY_DELAY_S = 2
# How long Quit waits for an in-flight attempt before giving up on it.
CANCEL_WAIT_MS = (CONNECT_TIMEOUT + 1) * 1000

log = logging.getLogger(__name__)

_MSG_BAD_LOGIN = "That username and password don't match. Check them and try again."
_MSG_UNREACHABLE = ("Can't reach the sync server. Try again in a moment, or work offline "
                    "to use the data saved on this computer.")


def _check_port_open(host: str, port: int, timeout: float = 3.0) -> bool:
    """TCP pre-flight — fails fast instead of hanging on DNS/firewall drops."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _parse_host_port(url: str):
    # Default port depends on the scheme (https -> 443, http -> 80). Without
    # this, the Cloudflare Tunnel URL would TCP-probe port 80 and falsely
    # report "unreachable" because the tunnel only listens on 443.
    is_https = url.startswith("https://")
    url = url.replace("http://", "").replace("https://", "")
    host_port = url.split("/")[0]
    if ":" in host_port:
        host, port = host_port.rsplit(":", 1)
        return host, int(port)
    return host_port, 443 if is_https else 80


class _LoginThread(QThread):
    """Sign-in attempts off the GUI thread.

    Subclasses QThread (run() override) rather than moveToThread: simpler
    and reliable in PySide6. Signals are connected to bound methods of the
    dialog so handlers run on the GUI thread. `cancel()` stops between
    attempts and cuts the retry delay short.
    """

    success = Signal(object)  # RemoteDataStore
    error = Signal(str)
    log_msg = Signal(str)

    def __init__(self, username: str, password: str, parent=None):
        super().__init__(parent)
        self._username = username
        self._password = password
        self._cancel = threading.Event()

    def cancel(self) -> None:
        self._cancel.set()

    def _emit(self, msg: str):
        self.log_msg.emit(msg)
        log.debug("[LoginThread] %s", msg)

    def _pause(self) -> None:
        """Retry delay that returns early when cancelled."""
        self._emit(f"  Retrying in {RETRY_DELAY_S}s...")
        self._cancel.wait(RETRY_DELAY_S)

    def _try_connect(self, url: str):
        """RemoteDataStore on success, None if the port is unreachable.
        Raises APIError for HTTP-level errors (wrong password, etc.)."""
        host, port = _parse_host_port(url)
        self._emit(f"  Checking TCP {host}:{port} ...")
        if not _check_port_open(host, port, timeout=CONNECT_TIMEOUT):
            self._emit(f"  Port {port} not reachable on {host}.")
            return None
        self._emit("  Port open. Sending login request...")
        return remote_login(url, self._username, self._password, timeout=CONNECT_TIMEOUT)

    def run(self):
        try:
            import requests

            self._emit(f"User: {self._username}")
            for label, url in [("external", SERVER_URL_EXTERNAL), ("local", SERVER_URL_LOCAL)]:
                self._emit(f"--- Trying {label} URL: {url} ---")
                for attempt in range(1, MAX_RETRIES + 1):
                    if self._cancel.is_set():
                        self._emit("Cancelled.")
                        return
                    self._emit(f"Attempt {attempt}/{MAX_RETRIES} ...")
                    last = attempt == MAX_RETRIES
                    try:
                        store = self._try_connect(url)
                        if store is None:
                            if not last:
                                self._pause()
                            continue
                        self._emit("Signed in.")
                        self.success.emit(store)
                        return
                    except APIError as exc:
                        if exc.status_code == 401:
                            self._emit("  Server responded: 401 Unauthorized (unknown user or wrong password).")
                            self.error.emit(_MSG_BAD_LOGIN)
                        else:
                            self._emit(f"  Server error {exc.status_code}: {exc}")
                            self.error.emit(f"The sync server had a problem ({exc.status_code}). "
                                            "Try again in a moment, or work offline.")
                        return
                    except requests.exceptions.Timeout:
                        self._emit(f"  Timed out after {CONNECT_TIMEOUT}s.")
                    except requests.exceptions.ConnectionError as exc:
                        self._emit(f"  Connection error: {exc}")
                    except Exception as exc:
                        self._emit(f"  Unexpected error: {exc}\n{traceback.format_exc()}")
                    if not last:
                        self._pause()
                self._emit(f"All {MAX_RETRIES} attempts failed for {label} URL.\n")

            self._emit("Unable to connect to server. Things to check on the server machine:")
            self._emit("  1. server.py is running.")
            self._emit("  2. Port 8742 is open in Windows Firewall (LAN access).")
            self._emit("  3. The Cloudflare Tunnel is running (it proxies the external URL to port 8742).")
            self.error.emit(_MSG_UNREACHABLE)

        except Exception as exc:
            self._emit(f"FATAL ERROR:\n{traceback.format_exc()}")
            self.error.emit(f"Something went wrong while signing in: {exc}")


class ConnectionDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Stock Insights")
        self.setModal(True)
        self.setMinimumWidth(420)
        self._store: Optional[DataStore] = None
        self._thread: Optional[_LoginThread] = None
        self._pending_username = ""

        s = QSettings(_ORG, _APP)
        root = dialog_layout(self)

        root.addWidget(heading_label("Sign in", px=20))
        root.addWidget(muted_label("Sign in to sync your trades with the server and your phone."))

        form = make_form()
        self.user_edit = QLineEdit()
        self.user_edit.setText(s.value(_USER_KEY, "", type=str) or "")
        self.pass_edit = QLineEdit()
        self.pass_edit.setEchoMode(QLineEdit.EchoMode.Password)
        form.addRow("Username", self.user_edit)
        form.addRow("Password", self.pass_edit)
        root.addLayout(form)

        self.status_label = muted_label("")
        self.status_label.setVisible(False)
        root.addWidget(self.status_label)

        self.debug_box = QTextEdit()
        self.debug_box.setReadOnly(True)
        self.debug_box.setFixedHeight(140)
        self.debug_box.setVisible(False)
        root.addWidget(self.debug_box)

        self.btn_toggle_debug = QPushButton("Show connection details")
        self.btn_toggle_debug.setFlat(True)
        self.btn_toggle_debug.setAutoDefault(False)
        self.btn_toggle_debug.clicked.connect(self._toggle_debug)

        self.btn_offline = QPushButton("Work offline")
        self.btn_offline.setAutoDefault(False)
        self.btn_offline.setToolTip("Use the data saved on this computer. Nothing syncs until you sign in.")
        self.btn_offline.clicked.connect(self._on_offline)
        _row, self.btn_login = add_dialog_buttons(
            self, root, "Sign in", on_primary=self._on_login, cancel_text="Quit",
            leading=(self.btn_offline, self.btn_toggle_debug))
        self.pass_edit.returnPressed.connect(self._on_login)

        (self.pass_edit if self.user_edit.text() else self.user_edit).setFocus()
        self._log("Dialog opened.")
        self._log(f"Server (external): {SERVER_URL_EXTERNAL}")
        self._log(f"Server (local):    {SERVER_URL_LOCAL}")

    def run(self) -> Optional[DataStore]:
        result = self.exec()
        if result == QDialog.DialogCode.Rejected and self._store is None:
            return None
        return self._store

    def _log(self, msg: str):
        self.debug_box.append(msg)
        log.debug("[ConnectionDialog] %s", msg)

    def _toggle_debug(self):
        visible = not self.debug_box.isVisible()
        self.debug_box.setVisible(visible)
        self.btn_toggle_debug.setText("Hide connection details" if visible else "Show connection details")
        self.adjustSize()

    def _show_status(self, text: str, role: str = "muted") -> None:
        self.status_label.setText(text)
        set_text_role(self.status_label, role)
        self.status_label.setVisible(bool(text))

    def _show_error(self, msg: str) -> None:
        self._show_status(msg, "error")

    def _set_busy(self, busy: bool):
        for w in (self.btn_login, self.btn_offline, self.user_edit, self.pass_edit):
            w.setEnabled(not busy)
        self.btn_login.setText("Signing in…" if busy else "Sign in")
        if busy:
            self._show_status("Connecting to the sync server…")

    def _on_login(self):
        if self._thread is not None:
            return
        username = self.user_edit.text().strip()
        if not username:
            self._show_error("Enter your username.")
            self.user_edit.setFocus()
            return

        self._set_busy(True)
        self._log("")
        self._log("--- Sign in attempt ---")
        self._pending_username = username
        thread = _LoginThread(username, self.pass_edit.text(), parent=self)
        # Bound methods (not lambdas): PySide6 runs lambda slots on the
        # emitting thread, and these touch widgets.
        thread.log_msg.connect(self._log)
        thread.success.connect(self._on_login_success)
        thread.error.connect(self._on_login_error)
        thread.finished.connect(self._on_thread_finished)
        self._thread = thread
        thread.start()

    def _on_thread_finished(self):
        thread, self._thread = self._thread, None
        if thread is not None:
            thread.deleteLater()

    def _on_login_success(self, store: RemoteDataStore):
        s = QSettings(_ORG, _APP)
        s.setValue(_USER_KEY, self._pending_username)
        s.sync()
        # MainWindow wires the offline/online callbacks after it opens.
        self._store = FallbackDataStore(remote=store, local=LocalDataStore(self._pending_username))
        self.accept()

    def _on_login_error(self, msg: str):
        self._set_busy(False)
        self._show_error(msg)
        self.pass_edit.setFocus()
        self.pass_edit.selectAll()

    def _on_offline(self):
        username = self.user_edit.text().strip() or "local"
        self._log(f"Working offline as '{username}'.")
        self._store = LocalDataStore(username)
        self.accept()

    def done(self, result: int) -> None:
        # Quit while signing in: stop the attempt so the QThread is not
        # destroyed while running (that aborts the process).
        thread = self._thread
        if thread is not None and thread.isRunning():
            thread.cancel()
            for sig in (thread.success, thread.error):
                try:
                    sig.disconnect()
                except (RuntimeError, TypeError):
                    pass
            thread.wait(CANCEL_WAIT_MS)
        super().done(result)
