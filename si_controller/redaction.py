"""Mask secrets in captured server output before it is stored or shown.

The server should never print a secret, but a traceback or a pyodbc error can
carry a connection string (``PWD=...``) and a debug line can carry a bearer token.
Every captured line passes through ``redact_line`` before it reaches the ring
buffer, the log file or the API.
"""
from __future__ import annotations

import re

REDACTED = "[redacted]"

# key=value / key: value / "key": "value" where the key names a secret,
# including PWD= in an ODBC connection string and PORTFOLIO_SQL_PASSWORD=.
_PAIR = re.compile(
    r"""(?ix)
    (?P<key>["']?\b(?:[a-z0-9]+[_-])*
        (?:password|passwd|pwd|token|secret|api[_-]?key|authorization|credentials?)
        (?:[_-][a-z0-9]+)*["']?)
    (?P<sep>\s*[=:]\s*)
    (?P<value>\[redacted\]|"[^"]*"|'[^']*'|[^\s,;&)\]}]+)
    """)
_BEARER = re.compile(r"(?i)\b(bearer|basic)\s+(?!\[redacted\])[A-Za-z0-9._~+/=\-]{6,}")
_URL_CREDENTIALS = re.compile(r"(?i)\b([a-z][a-z0-9+.\-]*://[^/\s:@]+):([^@\s/]+)@")
_NOT_SECRET = {"", "none", "null", "true", "false", REDACTED, "bearer", "basic"}


def redact_line(line: str) -> str:
    """Return ``line`` with secret-looking values replaced by ``[redacted]``."""
    if not line:
        return line
    line = _BEARER.sub(lambda m: f"{m.group(1)} {REDACTED}", line)
    line = _URL_CREDENTIALS.sub(lambda m: f"{m.group(1)}:{REDACTED}@", line)

    def pair(m: re.Match) -> str:
        value = m.group("value")
        if value.strip("\"'").lower() in _NOT_SECRET:
            return m.group(0)
        quote = value[0] if value[0] in "\"'" else ""
        return f"{m.group('key')}{m.group('sep')}{quote}{REDACTED}{quote}"

    return _PAIR.sub(pair, line)
