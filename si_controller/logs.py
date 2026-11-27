"""The controller's two records: server output and controller events.

``OutputLog``  every line the server printed (stdout and stderr), already
               redacted. Kept in memory (the last few thousand lines, each with a
               sequence number so a viewer can ask "everything after N") and
               written to ``logs\\server.log`` with size-based rotation.
``EventLog``   what the controller did and why: starts, exits with their code,
               restarts and their reason, who asked. One JSON object per line in
               ``logs\\events.jsonl`` (rotated), each with a plain sentence in
               ``message`` so the CLI and the manager need no wording of their own.

Both are thread-safe: the reader threads, the supervisor loop and the API
threads write and read them concurrently.
"""
from __future__ import annotations

import json
import os
import threading
from collections import deque
from datetime import datetime
from pathlib import Path


def now_iso() -> str:
    """Local time with its UTC offset, to the second."""
    return datetime.now().astimezone().isoformat(timespec="seconds")


class _RotatingFile:
    """Append-only text file that rolls over at ``max_bytes`` into .1 ... .N."""

    def __init__(self, path: Path, max_bytes: int, backups: int):
        self.path = Path(path)
        self.max_bytes = max_bytes
        self.backups = backups
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._fh = None
        self._size = 0

    def _open(self) -> None:
        self._fh = open(self.path, "a", encoding="utf-8", newline="\n")
        self._size = self._fh.tell()

    def write(self, text: str) -> None:
        if self._fh is None:
            self._open()
        if self._size and self._size + len(text) > self.max_bytes:
            self._rotate()
        self._fh.write(text)
        self._fh.flush()                  # the manager and a human tail this file live
        self._size += len(text.encode("utf-8"))

    def _rotate(self) -> None:
        self._fh.close()
        for i in range(self.backups - 1, 0, -1):
            src = self.path.with_name(f"{self.path.name}.{i}")
            if src.exists():
                os.replace(src, self.path.with_name(f"{self.path.name}.{i + 1}"))
        if self.backups > 0:
            os.replace(self.path, self.path.with_name(f"{self.path.name}.1"))
        else:
            self.path.unlink(missing_ok=True)
        self._open()

    def close(self) -> None:
        if self._fh:
            self._fh.close()
            self._fh = None


class OutputLog:
    def __init__(self, path: Path | None, keep_lines: int = 5000,
                 max_bytes: int = 5 * 1024 * 1024, backups: int = 5):
        self._lock = threading.Lock()
        self._lines: deque[dict] = deque(maxlen=keep_lines)
        self._seq = 0
        self._file = _RotatingFile(path, max_bytes, backups) if path else None

    def add(self, stream: str, text: str) -> None:
        with self._lock:
            self._seq += 1
            entry = {"seq": self._seq, "at": now_iso(), "stream": stream, "text": text}
            self._lines.append(entry)
            if self._file:
                try:
                    self._file.write(f"{entry['at']} {stream:<6} {text}\n")
                except OSError:
                    pass                  # a full disk must not stop the server's output pipe

    def since(self, after: int = 0, limit: int = 500) -> dict:
        """Lines with ``seq > after`` (at most ``limit``, the newest when trimmed).

        ``latest`` is the newest sequence number; ``gap`` is true when lines the
        caller has not seen were already dropped from memory.
        """
        limit = max(1, min(int(limit), 5000))
        with self._lock:
            newer = [e for e in self._lines if e["seq"] > after]
            oldest = self._lines[0]["seq"] if self._lines else self._seq + 1
            gap = after < oldest - 1 and after > 0
            return {"lines": newer[-limit:], "latest": self._seq, "gap": gap or len(newer) > limit}

    def tail(self, n: int = 40) -> list[str]:
        with self._lock:
            return [e["text"] for e in list(self._lines)[-n:]]

    def close(self) -> None:
        with self._lock:
            if self._file:
                self._file.close()


class EventLog:
    def __init__(self, path: Path | None, keep: int = 1000,
                 max_bytes: int = 2 * 1024 * 1024, backups: int = 3):
        self._lock = threading.Lock()
        self._events: deque[dict] = deque(maxlen=keep)
        self._file = _RotatingFile(path, max_bytes, backups) if path else None
        if path:
            self._load(Path(path), keep)

    def _load(self, path: Path, keep: int) -> None:
        """Bring back the last events from the file so history survives a restart."""
        try:
            with open(path, encoding="utf-8") as fh:
                lines = deque(fh, maxlen=keep)
        except OSError:
            return
        for line in lines:
            try:
                event = json.loads(line)
            except ValueError:
                continue                  # a line cut short by a power cut
            if isinstance(event, dict):
                self._events.append(event)

    def record(self, kind: str, message: str, **fields) -> dict:
        event = {"at": now_iso(), "kind": kind, "message": message}
        event.update({k: v for k, v in fields.items() if v is not None})
        with self._lock:
            self._events.append(event)
            if self._file:
                try:
                    self._file.write(json.dumps(event, ensure_ascii=False) + "\n")
                except OSError:
                    pass
        return event

    def recent(self, limit: int = 200) -> list[dict]:
        """Newest last."""
        limit = max(1, min(int(limit), 1000))
        with self._lock:
            return list(self._events)[-limit:]

    def close(self) -> None:
        with self._lock:
            if self._file:
                self._file.close()
