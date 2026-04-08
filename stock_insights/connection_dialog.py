"""connection_dialog.py — Login dialog with offline fallback, retry logic, and debug logging."""

from __future__ import annotations

import logging
import socket
import time
import traceback
from typing import Optional

from PySide6.QtCore import QSettings, Qt, QThread, Signal
from PySide6.QtWidgets import (
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
)

from .api_client import APIError, DataStore, LocalDataStore, RemoteDataStore, remote_login

_ORG = "StockInsights"
_APP = "StocksGUI"
_USER_KEY = "server/last_username"

SERVER_URL_EXTERNAL = "http://66.225.151.13:8742"
SERVER_URL_LOCAL    = "http://192.168.0.149:8742"

CONNECT_TIMEOUT = 5
MAX_RETRIES     = 3

log = logging.getLogger(__name__)


def _check_port_open(host: str, port: int, timeout: float = 3.0) -> bool:
    """TCP pre-flight — fails fast instead of hanging on DNS/firewall drops."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _parse_host_port(url: str):
    url = url.replace("http://", "").replace("https://", "")
    host_port = url.split("/")[0]
    if ":" in host_port:
        host, port = host_port.rsplit(":", 1)
        return host, int(port)
    return host_port, 80


class _LoginThread(QThread):
    """Subclass QThread so run() is guaranteed to execute on thread.start().

    The moveToThread + started.connect(worker.run) pattern is fragile in
    PySide6 — overriding run() directly is the reliable approach.
    """

    success = Signal(object)   # RemoteDataStore
    error   = Signal(str)
    log_msg = Signal(str)

    def __init__(self, username: str, password: str, parent=None):
        super().__init__(parent)
        self._username = username
        self._password = password

    def _emit(self, msg: str):
        self.log_msg.emit(msg)
        log.debug("[LoginThread] %s", msg)

    def _try_connect(self, url: str):
        """Returns RemoteDataStore on success, None if port unreachable.
        Raises APIError for HTTP-level errors (wrong password, etc.)."""
        import requests
        host, port = _parse_host_port(url)
        self._emit(f"  Checking TCP {host}:{port} ...")
        if not _check_port_open(host, port, timeout=CONNECT_TIMEOUT):
            self._emit(f"  Port {port} not reachable on {host}.")
            return None
        self._emit("  Port open. Sending login request...")
        store = remote_login(url, self._username, self._password,
                             timeout=CONNECT_TIMEOUT)
        return store

    def run(self):
        """Called automatically by QThread.start()."""
        try:
            import requests

            self._emit(f"User: {self._username}")
            self._emit(f"Server (external): {SERVER_URL_EXTERNAL}")
            self._emit(f"Server (local):    {SERVER_URL_LOCAL}")
            self._emit("")

            for label, url in [("external", SERVER_URL_EXTERNAL),
                                ("local",    SERVER_URL_LOCAL)]:
                self._emit(f"--- Trying {label} URL: {url} ---")

                for attempt in range(1, MAX_RETRIES + 1):
                    self._emit(f"Attempt {attempt}/{MAX_RETRIES} ...")
                    try:
                        store = self._try_connect(url)

                        if store is None:
                            if attempt < MAX_RETRIES:
                                self._emit("  No response. Retrying in 2s...")
                                time.sleep(2)
                            continue

                        self._emit("  Server connected.")
                        self._emit(f"Logging in as '{self._username}'...")
                        self._emit("Connected.")
                        self._emit("Loading data...")
                        self._emit("Successful.")
                        self.success.emit(store)
                        return

                    except APIError as exc:
                        if exc.status_code == 401:
                            self._emit("  Server responded: 401 Unauthorized.")
                            self._emit(f"  Username '{self._username}' may not exist,")
                            self._emit("  or the password is incorrect.")
                            self.error.emit(
                                f"Login failed: invalid username or password.\n"
                                f"Username entered: '{self._username}'"
                            )
                        else:
                            self._emit(f"  Server error {exc.status_code}: {exc}")
                            self.error.emit(f"Server error ({exc.status_code}): {exc}")
                        return

                    except requests.exceptions.Timeout:
                        self._emit(f"  Timed out after {CONNECT_TIMEOUT}s.")
                        if attempt < MAX_RETRIES:
                            self._emit("  Retrying in 2s...")
                            time.sleep(2)

                    except requests.exceptions.ConnectionError as exc:
                        self._emit(f"  Connection error: {exc}")
                        if attempt < MAX_RETRIES:
                            self._emit("  Retrying in 2s...")
                            time.sleep(2)

                    except Exception as exc:
                        self._emit(f"  Unexpected error: {exc}\n{traceback.format_exc()}")
                        if attempt < MAX_RETRIES:
                            self._emit("  Retrying in 2s...")
                            time.sleep(2)

                self._emit(f"All {MAX_RETRIES} attempts failed for {label} URL.\n")

            self._emit("Unable to connect to server.")
            self._emit("Suggestions:")
            self._emit("  1. Is server.py running on COLONIAL_SERVER?")
            self._emit("  2. Is port 8742 open in Windows Firewall on COLONIAL_SERVER?")
            self._emit("  3. Is router port forwarding 8742 -> 192.168.0.149?")
            self._emit("  4. Click 'Work Offline' to continue without the server.")
            self.error.emit(
                "Could not reach the server on either URL.\n"
                "Check the debug log for details, or click 'Work Offline'."
            )

        except Exception as exc:
            tb = traceback.format_exc()
            self._emit(f"FATAL ERROR:\n{tb}")
            self.error.emit(f"Unexpected error: {exc}")


class ConnectionDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Stock Insights — Login")
        self.setModal(True)
        self.resize(420, 300)
        self._store: Optional[DataStore] = None
        self._thread: Optional[_LoginThread] = None

        s = QSettings(_ORG, _APP)

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 20, 20, 20)
        root.setSpacing(10)

        form = QFormLayout()
        form.setSpacing(10)

        self.user_edit = QLineEdit()
        self.user_edit.setPlaceholderText("Username")
        self.user_edit.setText(str(s.value(_USER_KEY, "") or ""))

        self.pass_edit = QLineEdit()
        self.pass_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.pass_edit.setPlaceholderText("Password")
        self.pass_edit.returnPressed.connect(self._on_login)

        form.addRow("Username:", self.user_edit)
        form.addRow("Password:", self.pass_edit)
        root.addLayout(form)

        self.status_label = QLabel("")
        self.status_label.setWordWrap(True)
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        root.addWidget(self.status_label)

        self.debug_box = QTextEdit()
        self.debug_box.setReadOnly(True)
        self.debug_box.setFixedHeight(130)
        self.debug_box.setStyleSheet("font-family: monospace; font-size: 11px;")
        self.debug_box.setVisible(False)
        root.addWidget(self.debug_box)

        self.btn_toggle_debug = QPushButton("Show Debug Log")
        self.btn_toggle_debug.setFlat(True)
        self.btn_toggle_debug.setStyleSheet("color: gray; font-size: 11px;")
        self.btn_toggle_debug.clicked.connect(self._toggle_debug)
        root.addWidget(self.btn_toggle_debug)

        btn_row = QHBoxLayout()
        self.btn_offline = QPushButton("Work Offline")
        self.btn_offline.setToolTip("Skip server — use local device storage only")
        self.btn_offline.clicked.connect(self._on_offline)
        btn_quit = QPushButton("Quit")
        btn_quit.clicked.connect(self.reject)
        self.btn_login = QPushButton("Sign In")
        self.btn_login.setDefault(True)
        self.btn_login.clicked.connect(self._on_login)
        btn_row.addWidget(self.btn_offline)
        btn_row.addStretch(1)
        btn_row.addWidget(btn_quit)
        btn_row.addWidget(self.btn_login)
        root.addLayout(btn_row)

        self._log("Dialog opened.")
        self._log(f"Server IP (external): {SERVER_URL_EXTERNAL}")
        self._log(f"Server IP (local):    {SERVER_URL_LOCAL}")

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
        self.btn_toggle_debug.setText("Hide Debug Log" if visible else "Show Debug Log")

    def _set_busy(self, busy: bool):
        self.btn_login.setEnabled(not busy)
        self.btn_offline.setEnabled(not busy)
        self.user_edit.setEnabled(not busy)
        self.pass_edit.setEnabled(not busy)
        if busy:
            self.status_label.setText("Connecting...")
            self.status_label.setStyleSheet("color: gray;")

    def _on_login(self):
        username = self.user_edit.text().strip()
        password = self.pass_edit.text()
        if not username:
            self.status_label.setText("Enter your username.")
            self.status_label.setStyleSheet("color: red;")
            return

        self._set_busy(True)
        self._log("")
        self._log("--- Sign in attempt ---")
        self._log(f"User: {username}")
        self._log("Connecting to server...")

        thread = _LoginThread(username, password, parent=self)
        thread.log_msg.connect(self._log)
        thread.success.connect(lambda store: self._on_login_success(store, username, thread))
        thread.error.connect(lambda msg: self._on_login_error(msg, thread))
        thread.finished.connect(thread.deleteLater)
        self._thread = thread
        thread.start()

    def _on_login_success(self, store: RemoteDataStore, username: str, thread: _LoginThread):
        thread.quit()
        s = QSettings(_ORG, _APP)
        s.setValue(_USER_KEY, username)
        s.sync()
        self._store = store
        self.accept()

    def _on_login_error(self, msg: str, thread: _LoginThread):
        thread.quit()
        self._set_busy(False)
        self.debug_box.setVisible(True)
        self.btn_toggle_debug.setText("Hide Debug Log")
        self.status_label.setText(msg.split("\n")[0])
        self.status_label.setStyleSheet("color: red;")

    def _on_offline(self):
        username = self.user_edit.text().strip() or "local"
        self._log(f"Working offline as '{username}'.")
        self._store = LocalDataStore(username)
        self.accept()
