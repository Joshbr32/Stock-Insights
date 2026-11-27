# pwa/server_quotes_patch.py
**Purpose:** OBSOLETE one-off paste-in snippet that once added `GET /quotes` (yfinance only, one request per symbol) to an older server at `misc_helpers/server.py`. It is not imported or run by anything and does not run standalone (it references `app`, `Depends`, `current_user`, `HTTPException` from the server module).
**Used by:** nothing. Referenced only by `pwa/README.md` setup step 1 (also stale).  **Depends on:** n/a.

## Status
`server/server.py` already contains a better `/quotes` (Stooq batch first, yfinance fallback, symbol validation, cached misses). Pasting this file in would register a second `/quotes` route and duplicate globals. Candidate for deletion together with the README step; kept until the owner decides.

The server hides `*.py` under `pwa/` from the static mount, so this file is no longer publicly downloadable.

## Map
- 1-22 docstring with old paste instructions
- 24-71 cache globals, `_fetch_one_quote`
- 74-113 `get_quotes` route
