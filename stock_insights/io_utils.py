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
    "is_pending", "tag", "notes",
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
        "tag": (getattr(trade, "tag", "") or "").strip(),
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


# ─────────────────────────────────────────────────────────────────────────────
# Auto-snapshots (safety net before destructive ops + on launch)
# ─────────────────────────────────────────────────────────────────────────────

# Per-user folder under the OS home directory. Hidden by leading dot on
# Unix; on Windows it appears under C:\Users\<name>\.stock_insights — the
# user can still browse to it manually if disaster strikes.
def _auto_backup_dir() -> Path:
    return Path.home() / ".stock_insights" / "auto_backups"


# How many recent auto-snapshots to keep. Older files get pruned each time
# a new snapshot is written. 5 is enough to recover from "I clicked
# Restore by accident yesterday" but small enough that a year of daily
# launches doesn't fill the user's home directory with JSON.
AUTO_BACKUP_KEEP = 5


def write_auto_snapshot(store, kind: str = "snapshot") -> Optional[Path]:
    """Write a defensive backup before a destructive op (or at launch).

    `kind` is a short tag baked into the filename so the user can tell
    "this was right before I clicked Restore" from "this was just the
    nightly launch snapshot" when picking which file to recover from.

    Returns the written path, or None if the snapshot failed (we never
    want to block the calling operation just because we couldn't save
    a safety copy — the auto-snapshot is best-effort).
    """
    from datetime import datetime
    try:
        target_dir = _auto_backup_dir()
        target_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        # Slugify `kind` so a caller passing weird characters can't escape
        # the folder. Only [a-z0-9_-] survive.
        safe_kind = "".join(c if c.isalnum() or c in "_-" else "_"
                            for c in kind.lower()) or "snapshot"
        path = target_dir / f"{safe_kind}-{stamp}.json"
        write_backup(store, path)
        _prune_auto_snapshots(target_dir, AUTO_BACKUP_KEEP)
        return path
    except Exception:
        # Best-effort — never let a snapshot failure break a real op.
        # If disk is full, permissions are wrong, or the store is unhappy,
        # the user still gets to do whatever they were trying to do.
        return None


def _prune_auto_snapshots(folder: Path, keep: int) -> None:
    """Delete all but the `keep` most recent .json files in `folder`.

    Sorts by mtime descending so we always keep the freshest snapshots,
    regardless of filename collation order.
    """
    try:
        files = sorted(folder.glob("*.json"),
                       key=lambda p: p.stat().st_mtime, reverse=True)
        for old in files[keep:]:
            try:
                old.unlink()
            except Exception:
                # If a file is locked / in use, just skip it; we'll try
                # again next snapshot.
                pass
    except Exception:
        pass


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


def validate_backup(snapshot: dict) -> List[str]:
    """Structural sanity-check a backup snapshot WITHOUT touching the store.

    Returns a list of human-readable error strings. An empty list means
    the snapshot is safe to feed into `apply_backup`. The check is
    deliberately conservative: we'd rather block a quirky-but-recoverable
    backup than half-restore one and leave the user with a corrupt store.

    Designed to be the first thing a "Restore From Backup" handler calls
    so the destructive `apply_backup` only runs after we've confirmed
    every required field is the right shape. This prevents the
    "corrupt-mid-restore" failure mode where trades get wiped before the
    parser hits a bad accounts entry and bails.
    """
    errors: List[str] = []

    if not isinstance(snapshot, dict):
        return ["Backup is not a JSON object."]

    # Required top-level keys + their expected types.
    spec = [
        ("schema_version", int),
        ("accounts", list),
        ("goal_targets", dict),
        ("goal_presets", dict),
        ("goal_group", dict),
        ("watchlist", list),
        ("trades", list),
    ]
    for key, expected in spec:
        if key not in snapshot:
            errors.append(f"Missing required field: {key!r}.")
            continue
        # `bool` is a subclass of `int` in Python — exclude it explicitly so
        # `"schema_version": true` doesn't sneak past the int check.
        if expected is int and isinstance(snapshot[key], bool):
            errors.append(f"Field {key!r} should be {expected.__name__}, got bool.")
            continue
        if not isinstance(snapshot[key], expected):
            errors.append(
                f"Field {key!r} should be {expected.__name__}, "
                f"got {type(snapshot[key]).__name__}."
            )

    if errors:
        return errors

    # Schema version must match exactly (no forward-compat yet).
    if int(snapshot["schema_version"]) != BACKUP_SCHEMA_VERSION:
        errors.append(
            f"Backup schema version {snapshot['schema_version']} "
            f"(expected {BACKUP_SCHEMA_VERSION})."
        )

    # Account names must be non-empty strings.
    for i, name in enumerate(snapshot["accounts"]):
        if not isinstance(name, str) or not name.strip():
            errors.append(f"Account #{i} is not a non-empty string.")

    # Goal targets / presets must reference real numbers per account.
    for name, target in snapshot["goal_targets"].items():
        if not isinstance(target, (int, float)) or isinstance(target, bool):
            errors.append(f"Goal target for {name!r} is not a number.")
    for name, presets in snapshot["goal_presets"].items():
        if not isinstance(presets, list):
            errors.append(f"Goal presets for {name!r} are not a list.")
            continue
        for j, p in enumerate(presets):
            if not isinstance(p, (int, float)) or isinstance(p, bool):
                errors.append(f"Goal preset #{j} for {name!r} is not a number.")

    # Watchlist symbols must be strings.
    for i, sym in enumerate(snapshot["watchlist"]):
        if not isinstance(sym, str):
            errors.append(f"Watchlist entry #{i} is not a string.")

    # Trades: each row must at minimum carry an instrument and a numeric
    # share_count + buy_price. We can be lenient about everything else
    # (dates, notes, sell_price) since `trades_from_json` already coerces
    # those defensively.
    for i, row in enumerate(snapshot["trades"]):
        if not isinstance(row, dict):
            errors.append(f"Trade #{i} is not a JSON object.")
            continue
        if "instrument" not in row or not str(row.get("instrument", "")).strip():
            errors.append(f"Trade #{i} has no instrument.")
        for num_field in ("share_count", "buy_price"):
            v = row.get(num_field)
            if v is None:
                errors.append(f"Trade #{i} is missing {num_field}.")
            elif isinstance(v, bool) or not isinstance(v, (int, float)):
                # Strings would parse fine in trades_from_json, but the
                # backup format always serializes these as numbers, so a
                # string here means something corrupt the file.
                errors.append(f"Trade #{i} field {num_field} is not numeric.")

    return errors


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
