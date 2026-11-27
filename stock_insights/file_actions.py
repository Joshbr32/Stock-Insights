"""File menu actions: Export CSV, Back up data, Restore from backup.

Lifted out of main_window.py so MainWindow only wires menu items to these
functions. Each function owns its file picker and its result / error
messages (Harbor copy: say what happened and what to do next). The data
work itself lives in io_utils.py.

The destructive half of a restore (`io_utils.apply_backup`, which writes
through the store and may hit the network) is *not* run here:
`choose_restore()` returns a validated snapshot and the caller runs the
apply step in the background, then calls `show_restore_result()`.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Iterable, Optional

from PySide6.QtWidgets import QFileDialog, QMessageBox, QWidget

from .portfolio import Trade
from .widgets import confirm

_CSV_FILTER = "CSV files (*.csv);;All files (*)"
_BACKUP_FILTER = "Backup files (*.json);;All files (*)"
_MAX_ERRORS_SHOWN = 10


def default_export_dir() -> str:
    """~/Documents when it exists, else the home folder."""
    docs = Path.home() / "Documents"
    return str(docs if docs.exists() else Path.home())


def _plural(n: int, word: str) -> str:
    return f"{n:,d} {word}{'' if n == 1 else 's'}"


def export_csv(parent: QWidget, trades: Iterable[Trade]) -> None:
    """File > Export CSV: every trade in every portfolio for this user."""
    from .io_utils import export_trades_to_csv

    name = f"stock_insights_trades_{datetime.now():%Y%m%d_%H%M%S}.csv"
    path, _ = QFileDialog.getSaveFileName(
        parent, "Export CSV", str(Path(default_export_dir()) / name), _CSV_FILTER)
    if not path:
        return
    try:
        count = export_trades_to_csv(trades, Path(path))
    except OSError as exc:
        QMessageBox.warning(
            parent, "Export CSV",
            f"Couldn't write the CSV file.\n\n{exc}\n\n"
            "Pick a folder you can save to and try again.")
        return
    box = QMessageBox(QMessageBox.Icon.Information, "Export CSV",
                      f"Exported {_plural(count, 'trade')}.", parent=parent)
    box.setInformativeText(path)
    box.exec()


def back_up(parent: QWidget, store) -> None:
    """File > Back up data: full JSON snapshot restorable via Restore."""
    from .io_utils import write_backup

    name = f"stock_insights_backup_{datetime.now():%Y%m%d_%H%M%S}.json"
    path, _ = QFileDialog.getSaveFileName(
        parent, "Back up data", str(Path(default_export_dir()) / name), _BACKUP_FILTER)
    if not path:
        return
    try:
        written = write_backup(store, Path(path))
    except Exception as exc:  # store read or disk write; both are user-actionable
        QMessageBox.warning(
            parent, "Back up data",
            f"Couldn't save the backup.\n\n{exc}\n\n"
            "Check the folder is writable and that you're connected, then try again.")
        return
    box = QMessageBox(QMessageBox.Icon.Information, "Back up data", "Backup saved.", parent=parent)
    box.setInformativeText(
        f"{written}\n\nKeep this file somewhere safe. File > Restore from backup "
        "rebuilds every trade, watchlist symbol and goal setting from it.")
    box.exec()


def choose_restore(parent: QWidget) -> Optional[dict]:
    """Pick a backup file, parse + validate it, and confirm with the user.

    Read-only: returns the snapshot to apply, or None if the user cancelled
    or the file is not a usable backup (the reason is shown). Validation
    runs end to end before anything is changed, so a truncated file can
    never leave the store half-restored.
    """
    from .io_utils import read_backup, validate_backup

    path, _ = QFileDialog.getOpenFileName(parent, "Restore from backup", default_export_dir(),
                                          _BACKUP_FILTER)
    if not path:
        return None
    try:
        snapshot = read_backup(Path(path))
    except (OSError, ValueError) as exc:
        QMessageBox.warning(
            parent, "Restore from backup",
            f"This file isn't a backup Stock Insights can read. Nothing was changed.\n\n{exc}\n\n"
            "Pick a file made with File > Back up data.")
        return None

    errors = validate_backup(snapshot)
    if errors:
        shown = "\n".join(f"• {e}" for e in errors[:_MAX_ERRORS_SHOWN])
        more = len(errors) - _MAX_ERRORS_SHOWN
        if more > 0:
            shown += f"\n• and {_plural(more, 'more problem')}"
        box = QMessageBox(QMessageBox.Icon.Warning, "Restore from backup",
                          "This backup has problems, so nothing was changed.", parent=parent)
        box.setInformativeText("Pick another backup file.")
        box.setDetailedText(shown)
        box.exec()
        return None

    detail = (
        f"The backup has {_plural(len(snapshot.get('accounts', [])), 'portfolio')}, "
        f"{_plural(len(snapshot.get('trades', [])), 'trade')} and "
        f"{_plural(len(snapshot.get('watchlist', [])), 'watchlist symbol')}, "
        f"saved {snapshot.get('exported_at', 'at an unknown time')}.\n\n"
        "A copy of your current data is saved to your auto-backups folder first."
    )
    if not confirm(parent, "Restore from backup", "Replace all your data with this backup?",
                   "Restore backup", destructive=True, detail=detail):
        return None
    return snapshot


def show_restore_result(parent: QWidget, result: dict) -> None:
    QMessageBox.information(
        parent, "Restore from backup",
        f"Backup restored: {_plural(int(result.get('trades', 0)), 'trade')} in "
        f"{_plural(int(result.get('accounts', 0)), 'portfolio')}, "
        f"{_plural(int(result.get('watchlist', 0)), 'watchlist symbol')}.")


def show_restore_failed(parent: QWidget, message: str) -> None:
    QMessageBox.warning(
        parent, "Restore from backup",
        f"The restore stopped part-way.\n\n{message}\n\n"
        "Your data from just before the restore is in your auto-backups folder "
        "(.stock_insights\\auto_backups in your home folder). Restore that file to undo.")
