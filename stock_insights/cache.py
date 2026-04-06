from __future__ import annotations

"""Small JSON-backed cache helpers."""

import json
from pathlib import Path
from typing import Any, Dict

from PySide6.QtCore import QStandardPaths

from .logging_utils import get_logger


logger = get_logger("cache")
CACHE_FILENAME = "cache.json"


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
    default_cache: Dict[str, Any] = {}

    try:
        if not path.exists():
            return default_cache
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            logger.warning("Cache payload was not a dict, resetting: %s", path)
            return default_cache
        return payload
    except Exception:
        logger.exception("Failed to load cache from %s", path)
        return default_cache


def _atomic_write_json(path: Path, payload: Dict[str, Any]) -> None:
    temp_path = path.with_suffix(path.suffix + ".tmp")
    temp_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    temp_path.replace(path)


def save_cache(app_name: str, payload: Dict[str, Any]) -> None:
    """Atomically overwrite the cache file."""
    path = cache_path(app_name)
    try:
        _atomic_write_json(path, payload)
    except Exception:
        logger.exception("Failed to save cache for %s", app_name)
