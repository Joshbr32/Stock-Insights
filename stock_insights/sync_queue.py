"""sync_queue.py — Persistent offline write queue.

When the server is unreachable, FallbackDataStore parks its writes here (a
JSON file on disk).  On reconnect the queue is replayed against the server in
the order the writes were made.

Queue file : <user home>/.stockinsights_sync_queue.json
             JSON list of {action, username, payload, timestamp}
Rejected   : <user home>/.stockinsights_sync_queue.rejected.json
             the last few entries the server refused for good, kept so a
             lost edit can be recovered by hand

Actions
-------
save_trades      : {account_name, trades:[...]}
save_accounts    : {accounts:[...]}
set_goal_target  : {account_name, value}
set_goal_presets : {account_name, presets:[...]}
set_goal_group   : {account_names:[...], shared_goal, individual_goals, individual_presets}
save_watchlist   : {symbols:[...]}

Every action replaces whole state on the server (full-replace PUTs), so
replaying an entry twice is harmless.  That is what makes it safe to remove
an entry only after the server confirmed it: a crash in between just means
one repeated write on the next start.

All functions are safe to call from several threads of one process.  Two app
instances sharing the file are not coordinated.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from datetime import datetime, timezone
from typing import List, Optional, Tuple

log = logging.getLogger(__name__)

_QUEUE_FILE = os.path.join(os.path.expanduser("~"), ".stockinsights_sync_queue.json")

# Serialises every load-modify-save of the queue file.  Without it a flush on
# the reconnect thread could save its view of the queue over an entry the GUI
# thread had just appended.  Never held across a network call.
_lock = threading.RLock()

# Actions that can add or remove accounts.  Queued writes are never merged
# across one of these: replaying "delete account A" before or after "save
# trades for A" gives different results.
_STRUCTURAL_ACTIONS = frozenset({"save_accounts", "set_goal_group"})
_PER_ACCOUNT_ACTIONS = frozenset({"save_trades", "set_goal_target", "set_goal_presets"})
_KNOWN_ACTIONS = _STRUCTURAL_ACTIONS | _PER_ACCOUNT_ACTIONS | {"save_watchlist"}

_MAX_REJECTED = 50


# ---------------------------------------------------------------------------
# Queue persistence helpers
# ---------------------------------------------------------------------------

def _rejected_file() -> str:
    root, ext = os.path.splitext(_QUEUE_FILE)
    return f"{root}.rejected{ext}"


def _read_json_list(path: str) -> Optional[List[dict]]:
    """Return the list stored at `path`, [] if there is no file, None if the
    file exists but cannot be used."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        return []
    except (OSError, ValueError) as exc:
        log.error("sync_queue: could not read %s: %s", path, exc)
        return None
    if not isinstance(data, list):
        log.error("sync_queue: %s does not hold a list", path)
        return None
    return [entry for entry in data if isinstance(entry, dict)]


def _write_json_list(path: str, entries: List[dict]) -> bool:
    """Atomically replace `path`: write a sibling temp file, fsync, rename.
    A crash or power cut leaves either the old file or the new one, never a
    truncated mix."""
    tmp = f"{path}.tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(entries, f, separators=(",", ":"))
            f.flush()
            os.fsync(f.fileno())
        for attempt in range(3):
            try:
                os.replace(tmp, path)
                return True
            except PermissionError:
                # Windows: a virus scanner or backup tool can hold the
                # target open for a moment.
                if attempt == 2:
                    raise
                time.sleep(0.05)
    except OSError as exc:
        log.error("sync_queue: could not save %s: %s", path, exc)
    return False


def _load_raw() -> List[dict]:
    entries = _read_json_list(_QUEUE_FILE)
    if entries is not None:
        return entries
    # Unreadable queue: move it aside instead of letting the next save
    # overwrite whatever could still be recovered from it.
    aside = f"{_QUEUE_FILE}.corrupt"
    try:
        os.replace(_QUEUE_FILE, aside)
        log.error("sync_queue: unreadable queue file moved to %s", aside)
    except OSError as exc:
        log.error("sync_queue: could not move unreadable queue file aside: %s", exc)
    return []


def _save_raw(entries: List[dict]) -> None:
    _write_json_list(_QUEUE_FILE, entries)


def _matches_username(entry: dict, username: Optional[str]) -> bool:
    return username is None or entry.get("username", "") == username


def _merge_key(action: str, payload: dict) -> Optional[tuple]:
    """Entries with the same key write the same server state; only the
    newest one matters."""
    if action in _PER_ACCOUNT_ACTIONS:
        return action, payload.get("account_name")
    if action in _KNOWN_ACTIONS:
        return (action,)
    return None


def _superseded_index(entries: List[dict], username: str, action: str, payload: dict) -> Optional[int]:
    """Index of the queued entry a new (action, payload) write makes
    redundant, or None.

    Walks this user's entries newest first.  A structural write is only
    merged with the entry directly before it; any other write is merged
    with the latest entry of the same key unless a structural write was
    queued in between.
    """
    key = _merge_key(action, payload)
    if key is None:
        return None
    for idx in range(len(entries) - 1, -1, -1):
        entry = entries[idx]
        if entry.get("username", "") != username:
            continue
        entry_action = entry.get("action", "")
        entry_payload = entry.get("payload")
        if _merge_key(entry_action, entry_payload if isinstance(entry_payload, dict) else {}) == key:
            return idx
        if action in _STRUCTURAL_ACTIONS or entry_action in _STRUCTURAL_ACTIONS:
            return None
    return None


def _remove_entry(entry: dict) -> None:
    """Drop one entry (matched by value; the timestamp makes it unique)."""
    with _lock:
        entries = _load_raw()
        try:
            entries.remove(entry)
        except ValueError:
            return
        _save_raw(entries)


def _still_queued(entry: dict) -> bool:
    with _lock:
        return entry in _load_raw()


def _record_rejected(entry: dict, reason: str) -> None:
    """Keep a discarded entry on disk so the edit is not lost without trace."""
    with _lock:
        path = _rejected_file()
        rejected = _read_json_list(path) or []
        rejected.append({
            **entry,
            "rejected_at": datetime.now(timezone.utc).isoformat(),
            "reason": reason[:300],
        })
        _write_json_list(path, rejected[-_MAX_REJECTED:])


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def queue_length(username: Optional[str] = None) -> int:
    with _lock:
        return sum(1 for entry in _load_raw() if _matches_username(entry, username))


def is_empty(username: Optional[str] = None) -> bool:
    return queue_length(username=username) == 0


def enqueue(username: str, action: str, payload: dict) -> None:
    """Append one write operation to the queue.

    An older queued write that this one fully replaces (same action for the
    same account, e.g. two saves of one account's trades) is dropped, so the
    queue stays about as large as the number of things edited offline
    instead of growing with every edit.
    """
    with _lock:
        entries = _load_raw()
        stale = _superseded_index(entries, username, action, payload)
        if stale is not None:
            del entries[stale]
        entries.append({
            "action": action,
            "username": username,
            "payload": payload,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
        _save_raw(entries)
    log.info("sync_queue: queued %s for %s (queue length: %d)", action, username, len(entries))


def clear(username: Optional[str] = None) -> None:
    with _lock:
        if username is None:
            _save_raw([])
            return
        _save_raw([entry for entry in _load_raw() if not _matches_username(entry, username)])


def flush(remote_store, username: Optional[str] = None) -> Tuple[int, int]:
    """Replay queued writes against remote_store, oldest first.

    Returns (succeeded, failed).  Each entry is removed from the file as
    soon as the server confirms it.  What happens on failure depends on
    whether a retry can help:

    * network error, 5xx, expired token (401), 408/425/429: stop here and
      keep this entry and everything after it.  Later entries are not tried,
      because applying them ahead of an earlier write would reorder edits.
    * any other 4xx, or an entry that cannot be replayed at all (unknown
      action, malformed payload): the entry is moved to the rejected file
      and the flush continues, so one bad entry cannot block the queue.

    Writes queued while the flush is running are left for the next flush.
    """
    from .api_client import APIError  # local import to avoid circular
    import requests

    with _lock:
        pending = [entry for entry in _load_raw() if _matches_username(entry, username)]

    succeeded = 0
    failed = 0
    for entry in pending:
        if not _still_queued(entry):
            # Replaced by a newer write (or cleared) since the snapshot.
            continue
        action = entry.get("action", "")
        try:
            _replay(remote_store, action, entry.get("payload", {}))
        except requests.exceptions.RequestException as exc:
            log.warning("sync_queue: network lost during flush at %s: %s", action, exc)
            break
        except APIError as exc:
            failed += 1
            if exc.is_transient:
                log.warning("sync_queue: %s not accepted yet (%s), will retry: %s",
                            action, exc.status_code, exc)
                break
            log.error("sync_queue: server rejected %s (%s), discarding: %s",
                      action, exc.status_code, exc)
            _record_rejected(entry, f"HTTP {exc.status_code}: {exc}")
            _remove_entry(entry)
        except Exception as exc:
            # Not a server answer: the entry itself is unusable and would
            # fail the same way on every retry.
            failed += 1
            log.exception("sync_queue: cannot replay %s, discarding", action)
            _record_rejected(entry, f"{type(exc).__name__}: {exc}")
            _remove_entry(entry)
        else:
            succeeded += 1
            _remove_entry(entry)
            log.info("sync_queue: flushed %s", action)

    return succeeded, failed


def _replay(store, action: str, payload: dict) -> None:
    """Execute one queued action against the remote store."""
    from .portfolio import trades_from_json

    if action == "save_trades":
        store.save_account_trades(payload["account_name"], trades_from_json(payload.get("trades", [])))

    elif action == "save_accounts":
        store.save_accounts(payload["accounts"])

    elif action == "set_goal_target":
        store.set_goal_target(payload["account_name"], float(payload["value"]))

    elif action == "set_goal_presets":
        store.set_goal_presets(payload["account_name"], payload["presets"])

    elif action == "set_goal_group":
        store.set_goal_group(
            shared_accounts=payload["account_names"],
            shared_goal=float(payload["shared_goal"]),
            individual_goals=payload.get("individual_goals", {}),
            individual_presets=payload.get("individual_presets", {}),
        )

    elif action == "save_watchlist":
        store.save_watchlist(payload["symbols"])

    else:
        raise ValueError(f"unknown sync action '{action}'")
