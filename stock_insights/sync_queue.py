"""sync_queue.py — Persistent offline write queue.

When the server is unreachable, writes are queued here (JSON file on disk).
On reconnect, the queue is flushed to the server in order.

Queue file location: <user home>/.stockinsights_sync_queue.json
Each entry is a dict: {action, username, payload, timestamp}

Actions
-------
save_trades      : {account_name, trades:[...]}
save_accounts    : {accounts:[...]}
set_goal_target  : {account_name, value}
set_goal_presets : {account_name, presets:[...]}
set_goal_group   : {account_names:[...], shared_goal, individual_goals, individual_presets}
save_watchlist   : {symbols:[...]}
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from typing import List, Optional

log = logging.getLogger(__name__)

_QUEUE_FILE = os.path.join(os.path.expanduser("~"), ".stockinsights_sync_queue.json")


# ---------------------------------------------------------------------------
# Queue persistence helpers
# ---------------------------------------------------------------------------

def _load_raw() -> List[dict]:
    try:
        with open(_QUEUE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            return data
    except FileNotFoundError:
        pass
    except Exception as exc:
        log.warning("sync_queue: could not load queue file: %s", exc)
    return []


def _save_raw(entries: List[dict]) -> None:
    try:
        with open(_QUEUE_FILE, "w", encoding="utf-8") as f:
            json.dump(entries, f, indent=2)
    except Exception as exc:
        log.error("sync_queue: could not save queue file: %s", exc)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def _matches_username(entry: dict, username: Optional[str]) -> bool:
    return username is None or entry.get("username", "") == username


def queue_length(username: Optional[str] = None) -> int:
    return sum(1 for entry in _load_raw() if _matches_username(entry, username))


def is_empty(username: Optional[str] = None) -> bool:
    return queue_length(username=username) == 0


def enqueue(username: str, action: str, payload: dict) -> None:
    """Append one write operation to the queue."""
    entries = _load_raw()
    entries.append({
        "action": action,
        "username": username,
        "payload": payload,
        "timestamp": datetime.utcnow().isoformat(),
    })
    _save_raw(entries)
    log.info("sync_queue: queued %s for %s (queue length: %d)", action, username, len(entries))


def clear(username: Optional[str] = None) -> None:
    if username is None:
        _save_raw([])
        return
    kept = [entry for entry in _load_raw() if not _matches_username(entry, username)]
    _save_raw(kept)


def flush(remote_store, username: Optional[str] = None) -> tuple[int, int]:
    """Replay all queued writes against remote_store.

    Returns (succeeded, failed).  Entries that succeed are removed from the
    queue.  Entries that fail (server error) are kept for the next attempt.
    On a network error the flush aborts early and keeps all remaining entries.
    """
    from .api_client import APIError  # local import to avoid circular
    import requests

    if username is not None:
        return _flush_for_user(remote_store, username)

    entries = _load_raw()
    if not entries:
        return 0, 0

    succeeded = 0
    failed = 0
    remaining: List[dict] = []

    for entry in entries:
        action  = entry.get("action", "")
        payload = entry.get("payload", {})
        try:
            _replay(remote_store, action, payload)
            succeeded += 1
            log.info("sync_queue: flushed %s", action)
        except (requests.exceptions.ConnectionError,
                requests.exceptions.Timeout):
            # Network gone again — stop and keep everything from here on
            remaining.append(entry)
            remaining.extend(entries[entries.index(entry) + 1:])
            log.warning("sync_queue: network lost during flush, keeping %d entries", len(remaining))
            break
        except APIError as exc:
            if exc.status_code in (401, 403):
                # Auth error — discard the entry, can't do anything about it
                log.error("sync_queue: discarding %s due to auth error: %s", action, exc)
                failed += 1
            else:
                # Server error — keep and retry later
                remaining.append(entry)
                failed += 1
                log.warning("sync_queue: server error for %s (%s), keeping", action, exc)
        except Exception as exc:
            log.error("sync_queue: unexpected error replaying %s: %s", action, exc)
            remaining.append(entry)
            failed += 1

    _save_raw(remaining)
    return succeeded, failed


def _flush_for_user(remote_store, username: str) -> tuple[int, int]:
    from .api_client import APIError
    import requests

    indexed_entries = list(enumerate(_load_raw()))
    target_entries = [(idx, entry) for idx, entry in indexed_entries if _matches_username(entry, username)]
    if not target_entries:
        return 0, 0

    succeeded = 0
    failed = 0
    keep_indices = {idx for idx, entry in indexed_entries if not _matches_username(entry, username)}

    for pos, (original_idx, entry) in enumerate(target_entries):
        action = entry.get("action", "")
        payload = entry.get("payload", {})
        try:
            _replay(remote_store, action, payload)
            succeeded += 1
            log.info("sync_queue: flushed %s for %s", action, username)
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout):
            keep_indices.add(original_idx)
            keep_indices.update(idx for idx, _ in target_entries[pos + 1:])
            log.warning("sync_queue: network lost during flush for %s, keeping queued writes", username)
            break
        except APIError as exc:
            if exc.status_code in (401, 403):
                log.error("sync_queue: discarding %s for %s due to auth error: %s", action, username, exc)
                failed += 1
            else:
                keep_indices.add(original_idx)
                failed += 1
                log.warning("sync_queue: server error for %s (%s), keeping", action, exc)
        except Exception as exc:
            log.error("sync_queue: unexpected error replaying %s for %s: %s", action, username, exc)
            keep_indices.add(original_idx)
            failed += 1

    remaining = [entry for idx, entry in indexed_entries if idx in keep_indices]
    _save_raw(remaining)
    return succeeded, failed


def _replay(store, action: str, payload: dict) -> None:
    """Execute one queued action against the remote store."""
    from .portfolio import trades_from_json

    if action == "save_trades":
        account_name = payload["account_name"]
        trades_data = payload.get("trades", [])
        trades = trades_from_json(json.dumps(trades_data))
        store.save_account_trades(account_name, trades)

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
        log.warning("sync_queue: unknown action '%s', discarding", action)
