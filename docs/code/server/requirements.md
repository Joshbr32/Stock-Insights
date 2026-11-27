# server/requirements.txt and server/.env.example
**Purpose:** Runtime dependencies and environment template for `server/server.py` only (the desktop app has its own top-level `requirements.txt`).
**Used by:** `pip install -r server/requirements.txt` on the server PC; `.env.example` is copied to `server/.env` (gitignored, never read by agents).

## requirements.txt
| Package | Why |
|---|---|
| fastapi, uvicorn[standard], pydantic>=2.5 | web framework / ASGI server |
| pyodbc>=5.0 | SQL Server driver (needs MS ODBC Driver 17/18 installed) |
| python-dotenv | loads `server/.env` (optional at runtime) |
| requests>=2.31 | Stooq quotes for `/quotes` (was missing; without it only yfinance is tried) |
| yfinance (commented out) | optional quote fallback; heavy (pandas) |

## .env.example variables
`PORTFOLIO_SQL_PASSWORD` (required), `PORTFOLIO_SQL_SERVER`, `PORTFOLIO_SQL_DATABASE`, `PORTFOLIO_SQL_USER` (default `sa`; prefer a least-privilege login), `PORTFOLIO_HOST`, `PORTFOLIO_PORT`, `PORTFOLIO_PWA_DIR`, `PORTFOLIO_CORS_ORIGINS` (default `*`).

## How to change it safely
Add a variable here whenever `server.py` reads a new `PORTFOLIO_*` env var. Never put real values in `.env.example`.
