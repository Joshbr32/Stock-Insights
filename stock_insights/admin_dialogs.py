"""Admin-flavored modal dialogs that live outside the main QML scene.

Carved out of `main_window.py` to shrink that file (it was the project's
biggest, hosting menu wiring + dialog classes + worker lifecycle + much
else). These four classes are mutually independent — they take a store
and a parent and don't touch MainWindow internals — so the extraction
is mechanical and low-risk.

Contents
────────
• UserAccountDialog       — File → User Account (self password change,
                            account add/remove)
• UserPortfolioViewer     — Admin → View User Portfolio (read-only
                            window over another user's accounts)
• SelectUserDialog        — Picker that feeds UserPortfolioViewer
• ManageUserPasswordsDialog — Admin → Manage User Passwords (reset
                              other users' passwords)
"""
from __future__ import annotations

from typing import Dict, List, Optional

from PySide6.QtCore import QSettings, Qt, QThread, QTimer, Signal
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from .api_client import DataStore, FallbackDataStore, RemoteDataStore
from .portfolio_tab import PortfolioTab
from .workers import MarksWorker

# QGroupBox style mirrors GROUP_STYLE in portfolio_tab.py / settings_dialog.py
# so admin dialogs match the rest of the modal aesthetic.
_GROUP_STYLE = (
    "QGroupBox { margin-top: 8px; }"
    "QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 2px 8px; }"
)


# ---------------------------------------------------------------------------
# Admin: User Account Management Dialog
# ---------------------------------------------------------------------------

class UserAccountDialog(QDialog):
    """Create / view user accounts (admin-only management + self password change)."""

    def __init__(self, store: DataStore, parent=None):
        super().__init__(parent)
        self._store = store
        self.setWindowTitle("User Account")
        self.resize(520, 420)

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        # ---- Profile group ----
        profile_grp = QGroupBox("Profile")
        profile_grid = QGridLayout(profile_grp)
        profile_grid.setContentsMargins(14, 18, 14, 14)
        profile_grid.setHorizontalSpacing(12)
        profile_grid.setVerticalSpacing(10)

        info = store.user_info
        profile_grid.addWidget(QLabel("Username:"), 0, 0)
        profile_grid.addWidget(QLabel(info.get("username", "")), 0, 1)
        profile_grid.addWidget(QLabel("Role:"), 1, 0)
        profile_grid.addWidget(QLabel("Admin" if info.get("is_admin") else "User"), 1, 1)
        profile_grid.addWidget(QLabel("Server:"), 2, 0)

        server_url = ""
        if isinstance(store, RemoteDataStore):
            server_url = store._base
        elif isinstance(store, FallbackDataStore):
            server_url = store._remote._base
        profile_grid.addWidget(QLabel(server_url or "(offline)"), 2, 1)
        root.addWidget(profile_grp)

        # ---- Change password ----
        pwd_grp = QGroupBox("Change Password")
        pwd_form = QVBoxLayout(pwd_grp)
        pwd_form.setContentsMargins(14, 18, 14, 14)
        self.new_pass_edit = QLineEdit()
        self.new_pass_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.new_pass_edit.setPlaceholderText("New password (leave blank to keep current)")
        btn_change_pwd = QPushButton("Change Password")
        btn_change_pwd.clicked.connect(self._change_password)
        pwd_form.addWidget(self.new_pass_edit)
        pwd_form.addWidget(btn_change_pwd)
        root.addWidget(pwd_grp)

        # ---- Accounts list ----
        accts_grp = QGroupBox("My Accounts")
        accts_layout = QVBoxLayout(accts_grp)
        accts_layout.setContentsMargins(14, 18, 14, 14)
        accts_layout.setSpacing(8)

        self.accounts_list = QListWidget()
        for acct in store.get_account_names():
            self.accounts_list.addItem(acct)
        accts_layout.addWidget(self.accounts_list)

        acct_btns = QHBoxLayout()
        btn_add = QPushButton("+ Add Account")
        btn_remove = QPushButton("- Remove Account")
        btn_add.clicked.connect(self._add_account)
        btn_remove.clicked.connect(self._remove_account)
        acct_btns.addWidget(btn_add)
        acct_btns.addWidget(btn_remove)
        acct_btns.addStretch(1)
        accts_layout.addLayout(acct_btns)
        root.addWidget(accts_grp)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok)
        buttons.accepted.connect(self.accept)
        root.addWidget(buttons)

    def _change_password(self):
        password = self.new_pass_edit.text().strip()
        if not password:
            return
        remote_store = self._remote_store()
        if remote_store is None:
            QMessageBox.information(self, "Offline", "Password change requires a server connection.")
            return
        try:
            import requests
            user_id = remote_store.user_info["user_id"]
            r = requests.put(
                f"{remote_store._base}/users/{user_id}/password",
                json={"new_password": password},
                headers=remote_store._headers(),
                timeout=8,
            )
            if r.ok:
                QMessageBox.information(self, "Success", "Password changed.")
                self.new_pass_edit.clear()
            else:
                QMessageBox.warning(self, "Error", r.text)
        except Exception as exc:
            QMessageBox.warning(self, "Error", str(exc))

    def _remote_store(self) -> Optional[RemoteDataStore]:
        if isinstance(self._store, RemoteDataStore):
            return self._store
        if isinstance(self._store, FallbackDataStore) and self._store._is_online:
            return self._store._remote
        return None

    def _add_account(self):
        text, ok = QInputDialog.getText(self, "Add Account", "Account name:")
        if not ok or not text.strip(): return
        name = text.strip()
        existing = self._store.get_account_names()
        if name in existing:
            QMessageBox.information(self, "Duplicate", f"'{name}' already exists.")
            return
        try:
            self._store.save_accounts(existing + [name])
            self.accounts_list.addItem(name)
        except Exception as exc:
            QMessageBox.warning(self, "Error", str(exc))

    def _remove_account(self):
        item = self.accounts_list.currentItem()
        if not item: return
        name = item.text()
        existing = self._store.get_account_names()
        if len(existing) <= 1:
            QMessageBox.information(self, "Cannot Remove", "At least one account must remain.")
            return
        if QMessageBox.question(self, "Remove Account", f"Remove '{name}'? This deletes all its trades.") \
                != QMessageBox.StandardButton.Yes:
            return
        try:
            self._store.save_accounts([a for a in existing if a != name])
            self.accounts_list.takeItem(self.accounts_list.row(item))
        except Exception as exc:
            QMessageBox.warning(self, "Error", str(exc))


# ---------------------------------------------------------------------------
# Admin: portfolio viewer for another user (still uses the QWidget PortfolioTab)
# ---------------------------------------------------------------------------

class UserPortfolioViewer(QMainWindow):
    """Read-only portfolio window opened by an admin to view another user's data."""

    closed = Signal()

    def __init__(self, user_store: DataStore, username: str, settings: QSettings, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Viewing Portfolio — {username}")
        self.resize(1100, 750)
        self._store = user_store
        self._settings = settings
        self.theme = getattr(parent, "theme", None)
        self._tabs: Dict[str, PortfolioTab] = {}
        self._closing = False
        self._active_marks_thread: Optional[QThread] = None
        self._active_marks_worker = None

        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)

        banner = QLabel(f"  👁  Admin view — {username}'s portfolios (read-only)")
        banner.setStyleSheet(
            "background: #7c3aed; color: white; padding: 6px 12px; font-weight: bold;"
        )
        layout.addWidget(banner)

        self.tab_widget = QTabWidget()
        layout.addWidget(self.tab_widget)

        try:
            accounts = user_store.get_account_names()
        except Exception:
            accounts = []

        for account in accounts:
            tab = PortfolioTab(
                account_name=account,
                store=user_store,
                settings=settings,
                read_only=True,
                parent=self,
            )
            self.tab_widget.addTab(tab, account)
            self._tabs[account] = tab

        if not accounts:
            self.tab_widget.addTab(QLabel("No accounts found."), "—")

        self._marks_timer = QTimer(self)
        self._marks_timer.setInterval(30_000)
        self._marks_timer.timeout.connect(self._refresh_marks)
        self._marks_timer.start()
        QTimer.singleShot(500, self._refresh_marks)

    def _refresh_marks(self):
        if self._closing:
            return
        if self._active_marks_thread is not None and self._active_marks_thread.isRunning():
            return
        tickers: List[str] = []
        for tab in self._tabs.values():
            tickers.extend(tab.holdings_symbols())
        tickers = list(dict.fromkeys([t for t in tickers if t]))
        if not tickers:
            return
        worker = MarksWorker(tickers)
        th = QThread(self)
        self._active_marks_worker = worker
        self._active_marks_thread = th
        worker.moveToThread(th)
        th.started.connect(worker.run)
        worker.done.connect(self._on_marks)
        worker.done.connect(th.quit)
        worker.error.connect(th.quit)
        th.finished.connect(worker.deleteLater)
        th.finished.connect(th.deleteLater)

        def _cleanup():
            self._active_marks_thread = None
            self._active_marks_worker = None

        th.finished.connect(_cleanup)
        th.start()

    def _on_marks(self, data: dict):
        if self._closing:
            return
        for tab in self._tabs.values():
            tab.update_marks(data)

    def update_ui(self):
        for tab in self._tabs.values():
            tab.update_ui()
        self.update()

    def closeEvent(self, event):
        self._closing = True
        self._marks_timer.stop()
        try:
            self._marks_timer.timeout.disconnect()
        except Exception:
            pass
        if self._active_marks_thread is not None:
            try:
                if self._active_marks_thread.isRunning():
                    self._active_marks_thread.quit()
                    self._active_marks_thread.wait(4000)
            except Exception:
                pass
            self._active_marks_thread = None
            self._active_marks_worker = None
        self._tabs.clear()
        event.accept()
        self.closed.emit()


# ---------------------------------------------------------------------------
# Admin: user selection dialog
# ---------------------------------------------------------------------------

class SelectUserDialog(QDialog):
    def __init__(self, users: List[dict], current_user_id: int, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Select User to View")
        self.resize(360, 280)
        self._selected: Optional[dict] = None

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(10)

        root.addWidget(QLabel("Select a user to open their portfolio in a read-only window:"))

        self.list_widget = QListWidget()
        for user in users:
            if user["id"] == current_user_id:
                continue
            item = QListWidgetItem(f"{'[Admin] ' if user['is_admin'] else ''}{user['username']}")
            item.setData(Qt.ItemDataRole.UserRole, user)
            self.list_widget.addItem(item)
        root.addWidget(self.list_widget)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

        self.list_widget.doubleClicked.connect(self._accept)

    def _accept(self):
        item = self.list_widget.currentItem()
        if item:
            self._selected = item.data(Qt.ItemDataRole.UserRole)
            self.accept()

    def selected_user(self) -> Optional[dict]:
        return self._selected


# ---------------------------------------------------------------------------
# Admin: reset other users' passwords
# ---------------------------------------------------------------------------

class ManageUserPasswordsDialog(QDialog):
    """Admin-only dialog for resetting any user's password.

    Used by small-team / friends-only deployments where a proper
    self-service "forgot password" email flow is overkill — admin types
    the new password, communicates it to the user out-of-band, the user
    can change it themselves later via File → User Account.
    """

    def __init__(self, store: DataStore, parent=None):
        super().__init__(parent)
        self._store = store
        self.setWindowTitle("Manage User Passwords")
        self.setModal(True)
        self.setWindowModality(Qt.WindowModality.ApplicationModal)
        self.setMinimumWidth(440)
        self.resize(480, 400)

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        # ── Section: Users ──────────────────────────────────────────────
        users_grp = QGroupBox("Users")
        users_grp.setStyleSheet(_GROUP_STYLE)
        users_lay = QVBoxLayout(users_grp)
        users_lay.setContentsMargins(14, 14, 14, 14)
        users_lay.setSpacing(8)

        self.users_list = QListWidget()
        self.users_list.itemDoubleClicked.connect(lambda _: self._reset_selected())
        try:
            users = store.list_users()
        except Exception as exc:
            QMessageBox.warning(self, "Error", f"Could not fetch users: {exc}")
            users = []
        my_id = store.user_info.get("user_id", -1)
        for u in users:
            if u["id"] == my_id:
                continue  # admin can self-reset via File > User Account
            label = f"{'[Admin] ' if u.get('is_admin') else ''}{u['username']}"
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, u)
            self.users_list.addItem(item)
        users_lay.addWidget(self.users_list)

        info = QLabel(
            "Pick a user, then click <b>Reset Password</b>. The new password "
            "is shown to you so you can pass it to them — they can change it "
            "themselves later via File → User Account."
        )
        info.setWordWrap(True)
        info.setStyleSheet("color: gray; font-size: 11px;")
        users_lay.addWidget(info)

        btn_reset = QPushButton("Reset Password…")
        btn_reset.clicked.connect(self._reset_selected)
        users_lay.addWidget(btn_reset)

        root.addWidget(users_grp)

        # ── Close button ────────────────────────────────────────────────
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    # ------------------------------------------------------------------

    def _remote_store(self) -> Optional[RemoteDataStore]:
        if isinstance(self._store, RemoteDataStore):
            return self._store
        if isinstance(self._store, FallbackDataStore) and self._store._is_online:
            return self._store._remote
        return None

    def _reset_selected(self) -> None:
        item = self.users_list.currentItem()
        if item is None:
            QMessageBox.information(self, "Select user",
                                    "Pick a user from the list first.")
            return
        user = item.data(Qt.ItemDataRole.UserRole) or {}
        username = user.get("username", "")
        user_id = user.get("id")
        if not username or user_id is None:
            return

        remote = self._remote_store()
        if remote is None:
            QMessageBox.information(
                self, "Offline",
                "Resetting another user's password requires a server connection. "
                "Reconnect and try again.",
            )
            return

        # Plain-text input — admin will need to read the new password back
        # to the user out-of-band, so masking it doesn't help here.
        new_pw, ok = QInputDialog.getText(
            self, "Reset Password",
            f"New password for {username}:",
            QLineEdit.EchoMode.Normal, "",
        )
        if not ok:
            return
        new_pw = new_pw.strip()
        if not new_pw:
            QMessageBox.warning(self, "Empty password",
                                "Password cannot be empty.")
            return
        if len(new_pw) < 4:
            QMessageBox.warning(self, "Too short",
                                "Use at least 4 characters.")
            return

        if QMessageBox.question(
                self, "Confirm Reset",
                f"Reset password for <b>{username}</b> to:<br><br>"
                f"&nbsp;&nbsp;<code>{new_pw}</code><br><br>Proceed?",
        ) != QMessageBox.StandardButton.Yes:
            return

        try:
            import requests
            r = requests.put(
                f"{remote._base}/users/{user_id}/password",
                json={"new_password": new_pw},
                headers=remote._headers(),
                timeout=8,
            )
        except Exception as exc:
            QMessageBox.warning(self, "Error", str(exc))
            return

        if r.ok:
            QMessageBox.information(
                self, "Password Reset",
                f"Password reset for <b>{username}</b>.<br><br>"
                f"They can log in with: <code>{new_pw}</code>",
            )
        else:
            QMessageBox.warning(self, "Error", r.text)
