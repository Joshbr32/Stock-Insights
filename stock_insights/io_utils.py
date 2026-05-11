"""Small import/export helpers for trade data.

CSV columns are chosen to match what most US brokers / tax tools expect,
so a power user can pull the file straight into TurboTax / Excel / a
custom spreadsheet without any reformatting.
"""
from __future__ import annotations

import csv
import json
from datetime import date
from pathlib import Path
from typing import Iterable, List, Optional

from .portfolio import Trade, trade_to_dict

# ─────────────────────────────────────────────────────────────────────────────
# CSV export
# ─────────────────────────────────────────────────────────────────────────────

CSV_COLUMNS = [
    "account", "instrument", "side", "qty", "status",
    "buy_price", "sell_price", "trade_profit",
    "open_date", "close_date", "days_held",
    "is_pending", "notes",
]


def _side(trade: Trade) -> str:
    return "Short" if trade.is_short else "Long"


def _csv_row(trade: Trade) -> dict:
    return {
        "account": (trade.account or "").strip(),
        "instrument": trade.normalized_instrument(),
        "side": _side(trade),
        "qty": int(trade.share_count),
        "status": trade.status,
        "buy_price": f"{float(trade.buy_price):.2f}",
        "sell_price": "" if trade.sell_price is None else f"{float(trade.sell_price):.2f}",
        "trade_profit": "" if trade.trade_profit is None else f"{float(trade.trade_profit):.2f}",
        "open_date": trade.open_date.isoformat() if trade.open_date else "",
        "close_date": trade.close_date.isoformat() if trade.close_date else "",
        "days_held": _days_held(trade.open_date, trade.close_date),
        "is_pending": "yes" if trade.is_pending else "no",
        "notes": (trade.notes or "").replace("\n", " ").strip(),
    }


def _days_held(opened: Optional[date], closed: Optional[date]) -> str:
    if opened is None or closed is None:
        return ""
    return str(max(0, (closed - opened).days))


def export_trades_to_csv(trades: Iterable[Trade], file_path: Path) -> int:
    """Write `trades` to `file_path` as a CSV. Returns number of rows written.

    Uses `csv.QUOTE_MINIMAL` so cells without commas / quotes stay clean,
    making the file pleasant to read in Excel + diff in git.
    """
    trades = list(trades)
    file_path = Path(file_path)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    with file_path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=CSV_COLUMNS, quoting=csv.QUOTE_MINIMAL)
        writer.writeheader()
        for t in trades:
            writer.writerow(_csv_row(t))
    return len(trades)


# ─────────────────────────────────────────────────────────────────────────────
# Backup / Restore (full JSON snapshot)
# ─────────────────────────────────────────────────────────────────────────────

BACKUP_SCHEMA_VERSION = 1


def build_backup(store) -> dict:
    """Snapshot everything we'd need to fully restore the user's data.

    Reads exclusively through the DataStore interface so it works for
    RemoteDataStore + LocalDataStore + FallbackDataStore alike.
    """
    info = store.user_info
    accounts = store.get_account_names()

    # Per-account: goal target + presets
    goal_targets: dict[str, float] = {}
    goal_presets: dict[str, List[float]] = {}
    for name in accounts:
        try:
            goal_targets[name] = float(store.get_goal_target(name))
        except Exception:
            goal_targets[name] = 500_000.0
        try:
            goal_presets[name] = list(store.get_goal_presets(name))
        except Exception:
            goal_presets[name] = [250_000.0, 500_000.0, 1_000_000.0]

    # Shared-goal grouping
    try:
        shared_accounts, shared_goal = store.get_goal_group()
    except Exception:
        shared_accounts, shared_goal = [], 500_000.0

    # Watchlist
    try:
        watchlist = list(store.get_watchlist())
    except Exception:
        watchlist = []

    # Trades (every account, untouched)
    try:
        trades = [trade_to_dict(t) for t in store.get_all_trades()]
    except Exception:
        trades = []

    from datetime import datetime, timezone
    return {
        "schema_version": BACKUP_SCHEMA_VERSION,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "username": info.get("username", ""),
        "accounts": list(accounts),
        "goal_targets": goal_targets,
        "goal_presets": goal_presets,
        "goal_group": {
            "shared_accounts": list(shared_accounts),
            "shared_goal": float(shared_goal),
        },
        "watchlist": watchlist,
        "trades": trades,
    }


def write_backup(store, file_path: Path) -> Path:
    """Serialize a backup snapshot to disk and return the written path."""
    file_path = Path(file_path)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    snapshot = build_backup(store)
    file_path.write_text(json.dumps(snapshot, indent=2), encoding="utf-8")
    return file_path


def read_backup(file_path: Path) -> dict:
    """Parse a backup file. Raises ValueError on schema mismatch / bad JSON."""
    file_path = Path(file_path)
    data = json.loads(file_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("Backup file is not a JSON object.")
    version = int(data.get("schema_version", 0))
    if version != BACKUP_SCHEMA_VERSION:
        raise ValueError(
            f"Backup schema version {version} not supported "
            f"(expected {BACKUP_SCHEMA_VERSION}).",
        )
    return data


def apply_backup(store, snapshot: dict) -> dict:
    """Restore a backup snapshot into the store.

    Returns a small summary dict {accounts, trades, watchlist} so the
    caller can show "Restored N trades, M accounts" in a toast.
    Existing data is OVERWRITTEN — callers should confirm with the user
    before invoking this.
    """
    from .portfolio import trades_from_json

    summary = {"accounts": 0, "trades": 0, "watchlist": 0}

    # 1) Accounts list
    accounts = list(snapshot.get("accounts", []))
    if accounts:
        store.save_accounts(accounts)
        summary["accounts"] = len(accounts)

    # 2) Goal targets + presets per account
    for name, target in (snapshot.get("goal_targets") or {}).items():
        try:
            store.set_goal_target(name, float(target))
        except Exception:
            pass
    for name, presets in (snapshot.get("goal_presets") or {}).items():
        try:
            store.set_goal_presets(name, [float(p) for p in presets])
        except Exception:
            pass

    # 3) Shared goal group
    goal_group = snapshot.get("goal_group") or {}
    shared_accounts = list(goal_group.get("shared_accounts", []))
    shared_goal = float(goal_group.get("shared_goal", 500_000.0))
    individual_goals = {
        name: float(target)
        for name, target in (snapshot.get("goal_targets") or {}).items()
    }
    individual_presets = {
        name: [float(p) for p in presets]
        for name, presets in (snapshot.get("goal_presets") or {}).items()
    }
    try:
        store.set_goal_group(
            shared_accounts, shared_goal,
            individual_goals, individual_presets,
        )
    except Exception:
        pass

    # 4) Watchlist
    watchlist = list(snapshot.get("watchlist") or [])
    if watchlist:
        store.save_watchlist(watchlist)
        summary["watchlist"] = len(watchlist)

    # 5) Trades — group by account and save_account_trades per slice.
    raw_trades = snapshot.get("trades") or []
    if raw_trades:
        all_trades = trades_from_json(json.dumps(raw_trades))
        # Tag each trade's account, then save per slice
        by_account: dict[str, list] = {}
        for t in all_trades:
            acct = (t.account or "").strip() or (accounts[0] if accounts else "Default")
            by_account.setdefault(acct, []).append(t)
        for name, ts in by_account.items():
            try:
                store.save_account_trades(name, ts)
            except Exception:
                pass
            summary["trades"] += len(ts)

    return summary
