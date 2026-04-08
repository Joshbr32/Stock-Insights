"""update_checker.py — "Check for Updates" feature.

Fetches a tiny JSON manifest from a public URL, compares it against the
running APP_VERSION, and shows a dialog with the result.

The network call runs in a QThread so the UI never freezes.

Manifest format (host this file at version.UPDATE_MANIFEST_URL):
    {
        "version": "1.0.1",
        "notes":   "What changed in this release.",
        "download_url": "https://github.com/YOU/stock-insights/releases/latest"
    }
"""

from __future__ import annotations

import json
import urllib.request
from typing import Optional

from PySide6.QtCore import QObject, QThread, Signal
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
)

from .version import APP_VERSION, UPDATE_MANIFEST_URL


# ---------------------------------------------------------------------------
# Version comparison helper
# ---------------------------------------------------------------------------

def _parse_version(v: str) -> tuple[int, ...]:
    """Convert "1.2.3" → (1, 2, 3).  Non-numeric parts are treated as 0."""
    parts = []
    for p in str(v).strip().lstrip("v").split("."):
        try:
            parts.append(int(p))
        except ValueError:
            parts.append(0)
    return tuple(parts)


def _newer(remote: str, local: str) -> bool:
    return _parse_version(remote) > _parse_version(local)


# ---------------------------------------------------------------------------
# Background worker
# ---------------------------------------------------------------------------

class _UpdateWorker(QObject):
    """Fetches the version manifest on a background thread."""

    finished = Signal(dict)   # {"version", "notes", "download_url"} or {"error": "..."}

    def run(self) -> None:
        try:
            req = urllib.request.Request(
                UPDATE_MANIFEST_URL,
                headers={"User-Agent": f"StockInsights/{APP_VERSION}"},
            )
            with urllib.request.urlopen(req, timeout=8) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            self.finished.emit(data)
        except Exception as exc:
            self.finished.emit({"error": str(exc)})


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def check_for_updates(parent=None, silent_if_current: bool = False) -> None:
    """
    Start a background update check and show a result dialog.

    Parameters
    ----------
    parent : QWidget, optional
        Parent window for the dialog.
    silent_if_current : bool
        If True, show no dialog when already up-to-date (useful for
        automatic startup checks — set to True to avoid nagging).
    """
    # Show a "checking…" dialog immediately so the user gets feedback
    checking_dlg = _CheckingDialog(parent)
    checking_dlg.show()

    worker = _UpdateWorker()
    thread = QThread(parent)
    worker.moveToThread(thread)
    thread.started.connect(worker.run)
    worker.finished.connect(
        lambda data: _on_result(data, parent, silent_if_current, checking_dlg, thread, worker)
    )
    thread.finished.connect(thread.deleteLater)
    thread.start()


def _on_result(
    data: dict,
    parent,
    silent_if_current: bool,
    checking_dlg: "QDialog",
    thread: QThread,
    worker: _UpdateWorker,
) -> None:
    thread.quit()
    checking_dlg.accept()   # close the "checking…" dialog

    if "error" in data:
        _ErrorDialog(data["error"], parent).exec()
        return

    remote_version = data.get("version", "")
    notes = data.get("notes", "")
    download_url = data.get("download_url", "")

    if _newer(remote_version, APP_VERSION):
        _UpdateAvailableDialog(remote_version, notes, download_url, parent).exec()
    else:
        if not silent_if_current:
            _UpToDateDialog(APP_VERSION, parent).exec()


# ---------------------------------------------------------------------------
# Dialogs
# ---------------------------------------------------------------------------

class _CheckingDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Check for Updates")
        self.setModal(True)
        self.setFixedSize(280, 80)
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel("  Checking for updates…"))


class _UpToDateDialog(QDialog):
    def __init__(self, current_version: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Check for Updates")
        self.setModal(True)
        self.setFixedSize(340, 110)
        lay = QVBoxLayout(self)
        lay.setSpacing(12)
        lay.addWidget(QLabel(f"✔  Stock Insights {current_version} is up to date."))
        btns = QHBoxLayout()
        ok = QPushButton("OK")
        ok.setDefault(True)
        ok.clicked.connect(self.accept)
        btns.addStretch(1)
        btns.addWidget(ok)
        lay.addLayout(btns)


class _UpdateAvailableDialog(QDialog):
    def __init__(self, new_version: str, notes: str, download_url: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Update Available")
        self.setModal(True)
        self.setMinimumWidth(400)
        self._url = download_url

        lay = QVBoxLayout(self)
        lay.setSpacing(12)
        lay.setContentsMargins(20, 20, 20, 20)

        title = QLabel(f"<b>Stock Insights {new_version} is available!</b>")
        lay.addWidget(title)

        current_lbl = QLabel(f"You are running version {APP_VERSION}.")
        current_lbl.setStyleSheet("color: gray; font-size: 11px;")
        lay.addWidget(current_lbl)

        if notes:
            lay.addWidget(QLabel(f"<i>{notes}</i>"))

        lay.addWidget(QLabel("Press <b>Download Update</b> to open the download page."))

        btns = QHBoxLayout()
        btn_later = QPushButton("Later")
        btn_later.clicked.connect(self.reject)
        btn_download = QPushButton("Download Update")
        btn_download.setDefault(True)
        btn_download.clicked.connect(self._open_download)
        btns.addStretch(1)
        btns.addWidget(btn_later)
        btns.addWidget(btn_download)
        lay.addLayout(btns)

    def _open_download(self):
        if self._url:
            import webbrowser
            webbrowser.open(self._url)
        self.accept()


class _ErrorDialog(QDialog):
    def __init__(self, error_msg: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Update Check Failed")
        self.setModal(True)
        self.setMinimumWidth(380)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 20, 20, 20)
        lay.setSpacing(12)
        lay.addWidget(QLabel("Could not check for updates."))
        err_lbl = QLabel(error_msg)
        err_lbl.setWordWrap(True)
        err_lbl.setStyleSheet("color: gray; font-size: 11px;")
        lay.addWidget(err_lbl)

        btns = QHBoxLayout()
        ok = QPushButton("OK")
        ok.setDefault(True)
        ok.clicked.connect(self.accept)
        btns.addStretch(1)
        btns.addWidget(ok)
        lay.addLayout(btns)
