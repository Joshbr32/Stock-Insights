# server/requirements.txt, server/.env.example, server/migrations/
**Purpose:** Runtime dependencies, environment template and schema migrations for `server/server.py` only (the desktop app has its own top-level `requirements.txt`).
**Used by:** `pip install -r server/requirements.txt` on the server PC; `.env.example` is copied to `server/.env` (gitignored, never read by agents); `migrations/*.sql` are run by `server.py` at start-up and by the operator in SSMS/sqlcmd.

## requirements.txt
| Package | Why |
|---|---|
| fastapi>=0.110, uvicorn[standard], pydantic>=2.5 | web framework / ASGI server (`lifespan` hook needs fastapi >= 0.93) |
| pyodbc>=5.0 | SQL Server driver (needs MS ODBC Driver 17/18 installed) |
| python-dotenv | loads `server/.env` (optional at runtime) |
| requests>=2.31 | Stooq quotes for `/quotes` |
| yfinance (commented out) | optional quote fallback; heavy (pandas) |
Password hashing uses stdlib `hashlib.scrypt` (needs OpenSSL 1.1+, true of every python.org build). Tests need only fastapi + pytest (no httpx).

## .env.example variables
`PORTFOLIO_SQL_PASSWORD` (required), `PORTFOLIO_SQL_SERVER`, `PORTFOLIO_SQL_DATABASE`, `PORTFOLIO_SQL_USER` (default `sa`; a least-privilege login can't migrate the schema itself), `PORTFOLIO_HOST`, `PORTFOLIO_PORT`, `PORTFOLIO_PWA_DIR`, `PORTFOLIO_CORS_ORIGINS` (default `*`), `PORTFOLIO_ENABLE_DOCS` (`1` serves /docs, /redoc, /openapi.json; default off).

## migrations/001_tags_trade_uid.sql
GO-separated T-SQL batches, each guarded so the file is idempotent and non-destructive: SET options; add `dbo.trades.tag`; add `dbo.trades.client_id`; backfill uids (dynamic SQL); filtered unique index `UX_trades_client_id`; widen `dbo.users.password_hash` to NVARCHAR(255) keeping nullability; `IX_trades_account_id`, `IX_sessions_user_id`, `IX_sessions_expires_at` when no index leads with that column. No `USE` statement: it runs against the connected database.
Manual run: `sqlcmd -S localhost\STOCKINSIGHTS -d StockInsights -E -b -I -i server\migrations\001_tags_trade_uid.sql` (or open in SSMS and F5).

## How to change it safely
Add a variable to `.env.example` whenever `server.py` reads a new `PORTFOLIO_*` env var. Never put real values in `.env.example`. Never edit a migration that may already have run; add `002_*.sql` instead (files run in name order). Keep each batch self-contained: `server.py` executes batches one by one and only splits on lines that are exactly `GO`.
