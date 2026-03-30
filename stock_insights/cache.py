from __future__ import annotations

"""Small JSON-backed cache helpers.

Snapshots are intentionally cached in one compact JSON file because the app's
cached footprint is still small. Writes are performed atomically so a partial
write does not corrupt the cache during shutdown or interruption.
"""

import json
import time
from pathlib import Path
from typing import Any, Dict, Optional

from PySide6.QtCore import QStandardPaths

from .logging_utils import get_logger


logger = get_logger("cache")
CACHE_FILENAME = "cache.json"
SNAPSHOTS_KEY = "snapshots"


def cache_dir(app_name: str) -> Path:
    """Return the writable cache directory for the application."""
    base = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppDataLocation)
    path = Path(base) / app_name
    path.mkdir(parents=True, exist_ok=True)
    return path


def cache_path(app_name: str) -> Path:
    return cache_dir(app_name) / CACHE_FILENAME


def load_cache(app_name: str) -> Dict[str, Any]:
    """Load the cache file and return a normalized structure."""
    path = cache_path(app_name)
    default_cache = {SNAPSHOTS_KEY: {}}

    try:
        if not path.exists():
            return default_cache
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            logger.warning("Cache payload was not a dict, resetting: %s", path)
            return default_cache
        payload.setdefault(SNAPSHOTS_KEY, {})
        return payload
    except Exception:
        logger.exception("Failed to load cache from %s", path)
        return default_cache


def _atomic_write_json(path: Path, payload: Dict[str, Any]) -> None:
    temp_path = path.with_suffix(path.suffix + ".tmp")
    temp_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    temp_path.replace(path)


def save_snapshot(app_name: str, ticker: str, snapshot: Dict[str, Any]) -> None:
    """Store or replace a snapshot in the cache."""
    ticker_key = ticker.upper()
    cache = load_cache(app_name)
    cache.setdefault(SNAPSHOTS_KEY, {})[ticker_key] = {
        "ts": int(time.time()),
        "data": snapshot,
    }
    path = cache_path(app_name)
    try:
        _atomic_write_json(path, cache)
    except Exception:
        logger.exception("Failed to save snapshot for %s", ticker_key)


def get_cached_snapshot(app_name: str, ticker: str) -> Optional[Dict[str, Any]]:
    """Return a cached snapshot payload if present."""
    ticker_key = ticker.upper()
    cache = load_cache(app_name)
    item = cache.get(SNAPSHOTS_KEY, {}).get(ticker_key)
    return item.get("data") if isinstance(item, dict) else None
