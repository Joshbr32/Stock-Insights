"""Account and admin windows that live outside the main QML scene.

Contents
────────
• UserAccountDialog         — File > Account and portfolios (own password,
                              add / remove portfolios)
• UserPortfolioViewer       — Admin > View a user's portfolio (read-only
                              window over another user's portfolios, built
                              from the legacy QWidget PortfolioTab)
• SelectUserDialog          — picker that feeds UserPortfolioViewer
• ManageUserPasswordsDialog — Admin > Reset a user's password

Network calls made from these dialogs (password changes) run on a
background thread via background.BackgroundCalls so the UI never freezes
for a request timeout.
"""
from __future__ import annotations

import html
from typing import Dict, List, Optional

from PySide6.QtCore import QSettings, QTimer, Qt, Signal
from PySide6.QtWidgets import (
    QDialog,
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
from .background import BackgroundCalls, SingleFlight
from .portfolio_tab import PortfolioTab
from .widgets import (
    GAP,
    PANEL_PADDING,
    Panel,
    add_dialog_buttons,
    align_form_labels,
    confirm,
    dialog_layout,
    heading_label,
    muted_label,
    set_text_role,
)
from .workers import MarksWorker

MIN_PASSWORD_LENGTH = 4
VIEWER_MARKS_INTERVAL_MS = 30_000
PASSWORD_TIMEOUT_S = (4, 10)  # (connect, read) seconds, as api_client


def _online_remote(store: DataStore) -> Optional[RemoteDataStore]:
    """The RemoteDataStore to talk to, or None when there's no server."""
    if isinstance(store, RemoteDataStore):
        return store
    if isinstance(store, FallbackDataStore) and store._is_online:
        return store._remote
    return None


def _server_url(store: DataStore) -> str:
    if isinstance(store, RemoteDataStore):
        return store._base
    if isinstance(store, FallbackDataStore):
        return store._remote._base
    return ""


def _put_password(remote: RemoteDataStore, user_id: int, new_password: str) -> None:
    """PUT /users/{id}/password. Raises RuntimeError with the server's reason.

    Runs on a worker thread. Reuses the store's pooled requests.Session when
    it has one. (RemoteDataStore has no public method for this yet.)
    """
    import requests

    http = getattr(remote, "_session", None) or requests
    r = http.put(
        f"{remote._base}/users/{user_id}/password",
        json={"new_password": new_password},
        headers=remote._headers(),
        timeout=PASSWORD_TIMEOUT_S,
    )
    if not r.ok:
        raise RuntimeError(r.text or f"HTTP {r.status_code}")


def _user_label(user: dict) -> str:
    return f"{user['username']} (admin)" if user.get("is_admin") else str(user["username"])


def _user_list(users: List[dict], exclude_id: int) -> QListWidget:
    lw = QListWidget()
    lw.setUniformItemSizes(True)
    for u in users:
        if u.get("id") == exclude_id:
            continue
        item = QListWidgetItem(_user_label(u))
        item.setData(Qt.ItemDataRole.UserRole, u)
        lw.addItem(item)
    return lw


# ---------------------------------------------------------------------------
# File > Account and portfolios
# ---------------------------------------------------------------------------

class UserAccountDialog(QDialog):
    """Profile, own-password change, and the user's portfolio list."""

    def __init__(self, store: DataStore, parent=None):
        super().__init__(parent)
        self._store = store
        self._bg = BackgroundCalls(self)
        self.setWindowTitle("Account and portfolios")
        self.setMinimumWidth(460)

        root = dialog_layout(self)
        info = store.user_info

        # ---- Profile ----
        profile = Panel("Profile")
        form = profile.form()
        form.addRow("Username", QLabel(info.get("username", "")))
        form.addRow("Role", QLabel("Admin" if info.get("is_admin") else "Member"))
        server = _server_url(store)
        form.addRow("Sync server", set_text_role(QLabel(server), "") if server
                    else muted_label("None. You're working offline.", wrap=False))
        root.addWidget(profile)

        # ---- Password ----
        pwd = Panel("Change password")
        pwd_form = pwd.form()
        self.new_pass_edit = QLineEdit()
        self.new_pass_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.confirm_pass_edit = QLineEdit()
        self.confirm_pass_edit.setEchoMode(QLineEdit.EchoMode.Password)
        pwd_form.addRow("New password", self.new_pass_edit)
        pwd_form.addRow("Confirm", self.confirm_pass_edit)
        self.pwd_status = muted_label("")
        self.pwd_status.setVisible(False)
        pwd.body.addWidget(self.pwd_status)
        pwd_row = QHBoxLayout()
        pwd_row.addStretch(1)
        self.btn_change_pwd = QPushButton("Change password")
        self.btn_change_pwd.setAutoDefault(False)
        self.btn_change_pwd.clicked.connect(self._change_password)
        pwd_row.addWidget(self.btn_change_pwd)
        pwd.body.addLayout(pwd_row)
        self.confirm_pass_edit.returnPressed.connect(self._change_password)
        align_form_labels(form, pwd_form)
        root.addWidget(pwd)

        # ---- Portfolios ----
        accts = Panel("Portfolios", subtitle="Each portfolio has its own trades and goal.")
        self.accounts_list = QListWidget()
        self.accounts_list.setMinimumHeight(110)
        for acct in self._account_names():
            self.accounts_list.addItem(acct)
        accts.body.addWidget(self.accounts_list)
        acct_btns = QHBoxLayout()
        acct_btns.setSpacing(8)
        btn_add = QPushButton("Add portfolio…")
        self.btn_remove = QPushButton("Remove…")
        for b in (btn_add, self.btn_remove):
            b.setAutoDefault(False)
        btn_add.clicked.connect(self._add_account)
        self.btn_remove.clicked.connect(self._remove_account)
        acct_btns.addWidget(btn_add)
        acct_btns.addWidget(self.btn_remove)
        acct_btns.addStretch(1)
        accts.body.addLayout(acct_btns)
        self.accounts_list.currentItemChanged.connect(self._sync_remove_enabled)
        self._sync_remove_enabled()
        root.addWidget(accts)

        add_dialog_buttons(self, root, primary_text=None, cancel_text="Close")

    # ---- helpers ----

    def _account_names(self) -> List[str]:
        try:
            return list(self._store.get_account_names())
        except Exception as exc:
            QMessageBox.warning(self, "Portfolios", f"Couldn't load your portfolios.\n\n{exc}")
            return []

    def _sync_remove_enabled(self, *_args) -> None:
        self.btn_remove.setEnabled(self.accounts_list.currentItem() is not None)

    def _show_pwd_status(self, text: str, role: str) -> None:
        self.pwd_status.setText(text)
        set_text_role(self.pwd_status, role)
        self.pwd_status.setVisible(bool(text))

    # ---- password ----

    def _change_password(self) -> None:
        password = self.new_pass_edit.text().strip()
        if not password:
            self._show_pwd_status("Enter a new password.", "error")
            return
        if len(password) < MIN_PASSWORD_LENGTH:
            self._show_pwd_status(f"Use at least {MIN_PASSWORD_LENGTH} characters.", "error")
            return
        if password != self.confirm_pass_edit.text().strip():
            self._show_pwd_status("The two passwords don't match. Type them again.", "error")
            return
        remote = _online_remote(self._store)
        if remote is None:
            self._show_pwd_status("You need a connection to the sync server to change your password.", "error")
            return
        self.btn_change_pwd.setEnabled(False)
        self._show_pwd_status("Changing password…", "muted")
        self._bg.run(_put_password, args=(remote, remote.user_info["user_id"], password),
                     on_done=self._password_changed, on_error=self._password_failed,
                     label="change_password")

    def _password_changed(self, _result) -> None:
        self.btn_change_pwd.setEnabled(True)
        self.new_pass_edit.clear()
        self.confirm_pass_edit.clear()
        self._show_pwd_status("Password changed. Use it next time you sign in.", "good")

    def _password_failed(self, msg: str) -> None:
        self.btn_change_pwd.setEnabled(True)
        self._show_pwd_status(f"Couldn't change your password: {msg}", "error")

    # ---- portfolios ----

    def _add_account(self) -> None:
        text, ok = QInputDialog.getText(self, "Add portfolio", "Portfolio name")
        if not ok or not text.strip():
            return
        name = text.strip()
        existing = self._account_names()
        if name in existing:
            QMessageBox.information(self, "Add portfolio", f"You already have a portfolio called “{name}”.")
            return
        try:
            self._store.save_accounts(existing + [name])
        except Exception as exc:
            QMessageBox.warning(self, "Add portfolio", f"Couldn't add the portfolio.\n\n{exc}\n\nTry again.")
            return
        self.accounts_list.addItem(name)

    def _remove_account(self) -> None:
        item = self.accounts_list.currentItem()
        if not item:
            return
        name = item.text()
        existing = self._account_names()
        if len(existing) <= 1:
            QMessageBox.information(self, "Remove portfolio",
                                    "You need at least one portfolio. Add another before removing this one.")
            return
        if not confirm(self, "Remove portfolio", f"Remove “{name}” and delete all of its trades?",
                       "Remove portfolio", destructive=True, detail="This can't be undone."):
            return
        try:
            self._store.save_accounts([a for a in existing if a != name])
        except Exception as exc:
            QMessageBox.warning(self, "Remove portfolio", f"Couldn't remove the portfolio.\n\n{exc}\n\nTry again.")
            return
        self.accounts_list.takeItem(self.accounts_list.row(item))


# ---------------------------------------------------------------------------
# Admin: read-only window over another user's portfolios
# ---------------------------------------------------------------------------

class UserPortfolioViewer(QMainWindow):
    """Read-only portfolio window opened by an admin to view another user's data."""

    closed = Signal()

    def __init__(self, user_store: DataStore, username: str, settings: QSettings, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"{username}'s portfolios (read-only)")
        self.resize(1100, 750)
        self._store = user_store
        self._settings = settings
        self.theme = getattr(parent, "theme", None)
        self._tabs: Dict[str, PortfolioTab] = {}
        self._closing = False
        self._marks_flight = SingleFlight(self, "viewer-marks")

        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(PANEL_PADDING, PANEL_PADDING, PANEL_PADDING, PANEL_PADDING)
        layout.setSpacing(GAP)

        header = QHBoxLayout()
        header.addWidget(heading_label(f"{username}'s portfolios", px=20))
        header.addStretch(1)
        header.addWidget(muted_label("Read-only. Changes can only be made by signing in as this user.",
                                     wrap=False))
        layout.addLayout(header)

        self.tab_widget = QTabWidget()
        self.tab_widget.setDocumentMode(True)
        layout.addWidget(self.tab_widget, 1)

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
            empty = muted_label(f"{username} has no portfolios yet.")
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.tab_widget.addTab(empty, "No portfolios")

        self._marks_timer = QTimer(self)
        self._marks_timer.setInterval(VIEWER_MARKS_INTERVAL_MS)
        self._marks_timer.timeout.connect(self._refresh_marks)
        self._marks_timer.start()
        QTimer.singleShot(500, self._refresh_marks)

    def _refresh_marks(self):
        if self._closing:
            return
        tickers: List[str] = []
        for tab in self._tabs.values():
            tickers.extend(tab.holdings_symbols())
        tickers = list(dict.fromkeys(t for t in tickers if t))
        if tickers:
            self._marks_flight.start(MarksWorker(tickers), lambda w: w.done.connect(self._on_marks))

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
        self._marks_flight.shutdown(4000)
        self._tabs.clear()
        event.accept()
        self.closed.emit()


# ---------------------------------------------------------------------------
# Admin: pick a user to view
# ---------------------------------------------------------------------------

class SelectUserDialog(QDialog):
    def __init__(self, users: List[dict], current_user_id: int, parent=None):
        super().__init__(parent)
        self.setWindowTitle("View a user's portfolio")
        self.setMinimumSize(380, 340)
        self._selected: Optional[dict] = None

        root = dialog_layout(self)
        root.addWidget(muted_label("Their portfolios open in a separate read-only window."))
        self.list_widget = _user_list(users, current_user_id)
        root.addWidget(self.list_widget, 1)
        if self.list_widget.count() == 0:
            root.addWidget(muted_label("There are no other users yet."))

        _row, self.btn_open = add_dialog_buttons(self, root, "Open portfolio", on_primary=self._accept)
        self.list_widget.itemDoubleClicked.connect(lambda _item: self._accept())
        self.list_widget.currentItemChanged.connect(self._sync_enabled)
        self._sync_enabled()

    def _sync_enabled(self, *_args) -> None:
        self.btn_open.setEnabled(self.list_widget.currentItem() is not None)

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
    """Admin-only: set a new password for another user.

    For small friends-only deployments where an email reset flow is
    overkill: the admin sets a password, tells the user out-of-band, and
    the user changes it later via File > Account and portfolios.

    `users` may be passed in (MainWindow fetches it in the background);
    when omitted it is fetched here, synchronously.
    """

    def __init__(self, store: DataStore, parent=None, users: Optional[List[dict]] = None):
        super().__init__(parent)
        self._store = store
        self._bg = BackgroundCalls(self)
        self.setWindowTitle("Reset a user's password")
        self.setModal(True)
        self.setWindowModality(Qt.WindowModality.ApplicationModal)
        self.setMinimumSize(420, 380)

        root = dialog_layout(self)
        root.addWidget(muted_label(
            "Pick a user and set a new password. Pass it on to them; they can "
            "change it later in File > Account and portfolios."))

        if users is None:
            try:
                users = store.list_users()
            except Exception as exc:
                QMessageBox.warning(self, self.windowTitle(),
                                    f"Couldn't load the user list.\n\n{exc}\n\nClose this and try again.")
                users = []
        self.users_list = _user_list(users, store.user_info.get("user_id", -1))
        self.users_list.itemDoubleClicked.connect(lambda _item: self._reset_selected())
        root.addWidget(self.users_list, 1)

        self.status = muted_label("")
        self.status.setVisible(False)
        root.addWidget(self.status)

        _row, self.btn_reset = add_dialog_buttons(self, root, "Reset password…",
                                                  on_primary=self._reset_selected, cancel_text="Close")
        self.users_list.currentItemChanged.connect(self._sync_enabled)
        self._sync_enabled()

    def _sync_enabled(self, *_args) -> None:
        self.btn_reset.setEnabled(self.users_list.currentItem() is not None)

    def _remote_store(self) -> Optional[RemoteDataStore]:
        return _online_remote(self._store)

    def _set_status(self, text: str, role: str) -> None:
        self.status.setText(text)
        set_text_role(self.status, role)
        self.status.setVisible(bool(text))

    def _reset_selected(self) -> None:
        item = self.users_list.currentItem()
        if item is None:
            return
        user = item.data(Qt.ItemDataRole.UserRole) or {}
        username = user.get("username", "")
        user_id = user.get("id")
        if not username or user_id is None:
            return

        remote = self._remote_store()
        if remote is None:
            self._set_status("You need a connection to the sync server to reset passwords.", "error")
            return

        # Shown in plain text: the admin has to read it back to the user.
        new_pw, ok = QInputDialog.getText(self, "Reset password", f"New password for {username}",
                                          QLineEdit.EchoMode.Normal, "")
        if not ok:
            return
        new_pw = new_pw.strip()
        if len(new_pw) < MIN_PASSWORD_LENGTH:
            self._set_status(f"Use at least {MIN_PASSWORD_LENGTH} characters. Nothing was changed.", "error")
            return
        if not confirm(self, "Reset password",
                       f"Set {username}'s password to “{new_pw}”?", "Reset password",
                       detail="Their old password stops working straight away."):
            return

        self.btn_reset.setEnabled(False)
        self._set_status(f"Resetting {username}'s password…", "muted")

        def _done(_r):
            self._sync_enabled()
            self._set_status(f"Password reset. {username} can sign in with “{new_pw}”.", "good")
            box = QMessageBox(QMessageBox.Icon.Information, "Password reset",
                              f"{username} can now sign in with this password:", parent=self)
            box.setInformativeText(html.escape(new_pw))
            box.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            box.exec()

        def _failed(msg: str):
            self._sync_enabled()
            self._set_status(f"Couldn't reset {username}'s password: {msg}", "error")

        self._bg.run(_put_password, args=(remote, user_id, new_pw), on_done=_done, on_error=_failed,
                     label="reset_password")
