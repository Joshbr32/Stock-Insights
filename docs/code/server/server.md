# server/server.py
**Purpose:** FastAPI sync server. Stores each user's accounts, trades, goal group and watchlist in SQL Server (pyodbc), proxies live quotes (Stooq, yfinance fallback) and serves the PWA (`../pwa`) from the same origin. Public via Cloudflare Tunnel (`si.coloniallawns.ca` -> origin :8742).
**Used by:** `stock_insights/api_client.py` (desktop, `requests`), `pwa/js/api.js` (PWA, `fetch`).  **Depends on:** fastapi, uvicorn, pydantic v2, pyodbc (+ MS ODBC driver), python-dotenv (optional), requests (Stooq), yfinance (optional). Config: `server/.env` (template `server/.env.example`), deps `server/requirements.txt`.

## HTTP contract (do not change routes or JSON shapes)
| Route | Auth | Body / query | Response |
|---|---|---|---|
| GET /health | none | - | `{ok, server_version, uptime_seconds, db_ok, db_error}` (db probe cached 5 s; db_error is generic, details in log) |
| POST /auth/login | none | `{username, password}` | `{token, user_id, username, is_admin}`; 401 bad creds; 429 throttled |
| POST /auth/logout | bearer | - | `{ok: true}` |
| GET /auth/me | bearer | - | `{user_id, username, is_admin}` |
| GET /users | admin | - | `[{id, username, is_admin, created_at}]` |
| POST /users | admin | `{username, password, is_admin}` (non-empty) | 201 `{ok}`; 409 duplicate |
| PUT /users/{id}/password | self or admin | `{new_password}` (non-empty) | `{ok}`; revokes that user's other sessions |
| DELETE /users/{id} | admin | - | `{ok}`; 400 on self; deletes sessions first |
| GET /accounts | bearer | `?for_user_id` (admin) | `[{id, name, goal_target, goal_presets (JSON string), position}]` |
| PUT /accounts | bearer | `{accounts: [AccountIn]}` | `{ok}`; full sync: missing names deleted, list order -> position |
| PUT /accounts/{name}/settings | bearer | AccountIn | `{ok}` (goal_target, goal_presets only) |
| GET /trades | bearer | `?for_user_id` | `[{id, account, instrument, share_count, buy_price, sell_price, open_date, close_date, notes, is_pending, is_short}]` |
| PUT /trades/{account} | bearer | `{account_name, trades: [TradeIn]}` | `{ok}`; replaces that account's trades, auto-creates the account; URL name wins |
| GET/PUT /goal-group | bearer | `{account_names, shared_goal}` | GET default `{account_names: [], shared_goal: 500000.0}` |
| GET/PUT /watchlist | bearer | `{symbols}` | GET `["SYM", ...]` in position order |
| GET /quotes | bearer | `?symbols=A,B` (max 250) | `{SYM: price_or_null}` in request order; 400 if too many; 503 if no fetcher |
| / (mount) | none | - | static PWA files |

`for_user_id` lets an admin act on another user (`_resolve_uid`); non-admins get 403.

## Key types and functions
| Name | Kind | Contract |
|---|---|---|
| `db()` | context manager | New pyodbc connection per call (ODBC driver-manager pooling makes this cheap); commit on success, rollback on exception, always close. |
| `_conn_string()` | func, lru_cached | Picks newest ODBC driver once. Env is read at import, so the cache is safe. |
| `_exec(conn, sql, *params)` | func | Only way queries run; always `?` placeholders. |
| `_hash_password` / `_verify_password` | func | PBKDF2-SHA256, 260k iterations, stored as `salt:hex` (no iteration count in format). |
| `_DUMMY_HASH` | const | Verified for unknown usernames so timing doesn't reveal which users exist. |
| `_login_blocked` / `_record_login_failure` / `_clear_login_failures` | func | In-memory throttle: 10 fails/15 min per username, 30 per IP (`CF-Connecting-IP` else socket peer). Resets on restart. |
| `current_user`, `admin_user`, `_bearer` | FastAPI deps | Bearer token -> user dict; 401/403. |
| `_CacheControlMiddleware` | ASGI middleware | Adds `Cache-Control: no-store` to any response without one (all API responses). |
| `_PWAStaticFiles` | StaticFiles subclass | 404s `*.py`, `*.pyc`, `*.md`, dotfiles, `__pycache__`; sets `Cache-Control: no-cache` (ETag revalidation). |
| `_probe_db()` | func | Cached `SELECT 1` for /health (`_HEALTH_TTL_S`). Holds a lock while probing so a burst of polls makes one query. |
| `_fetch_quotes_stooq` / `_fetch_quotes_yfinance` | func | Return `{sym: float or None}`; never raise. Stooq via shared `requests.Session` (`_HTTP`). |
| `setup_admin()` | CLI | `python server.py --setup`; password read with getpass. |

Middleware order (outermost first): CORS (`PORTFOLIO_CORS_ORIGINS`, default `*`), GZip (>=1 KB), Cache-Control.

## Data and state
SQL Server DB `StockInsights` (schema in `init_stockinsights.sql`, NOT in this repo), tables `dbo.users(id, username UNIQUE, password_hash, is_admin, created_at)`, `dbo.sessions(token, user_id, expires_at datetime2 naive UTC)`, `dbo.accounts(id, user_id, name, goal_target, goal_presets JSON text, position)`, `dbo.trades(id, account_id, instrument, share_count, buy_price, sell_price, open_date, close_date, notes, is_pending, is_short)`, `dbo.goal_group(user_id, account_names JSON text, shared_goal)`, `dbo.watchlist(user_id, symbol, position)`.
Deleting an account relies on an FK cascade to trades. Expired sessions are pruned on each successful login.
In-process state: `_QUOTE_CACHE` (20 s TTL, misses cached too), `_LOGIN_FAILS`, `_health_cache`. Single-process assumption (no workers > 1).
Env: `PORTFOLIO_SQL_SERVER/DATABASE/USER/PASSWORD` (password required, process exits without it), `PORTFOLIO_HOST`, `PORTFOLIO_PORT`, `PORTFOLIO_PWA_DIR`, `PORTFOLIO_CORS_ORIGINS`.

## How to change it safely
- Never read or edit `server/.env`; never point tests at the real SQL Server or tunnel.
- Keep routes and JSON shapes identical: the desktop `api_client.py` and `pwa/js/api.js` both depend on them. `SERVER_VERSION` is bumped only by the lead.
- The static mount must stay the LAST route registration (it catches everything).
- After an INSERT, don't use `SELECT SCOPE_IDENTITY()` in a separate `execute()`; pyodbc runs it in a new scope and gets NULL. Re-select by natural key or use `OUTPUT INSERTED.id` (only if the table has no triggers).
- Sync route handlers are `def` (run in the threadpool) because pyodbc blocks; keep them that way.
- Smoke test without SQL Server: fake `pyodbc` with an sqlite-backed module in `sys.modules` before import, then drive `server.app` with an ASGI call (httpx/TestClient is not installed in the venv). Then `python -m compileall -q server/server.py`.

## Map
- 1-50 module docstring, imports
- 52-136 .env loading, dependency guards, config, `SERVER_VERSION`
- 138-225 DB helpers (`_conn_string`, `db`, `_one/_all/_scalar/_exec`)
- 227-337 auth helpers, login throttling
- 339-468 app + middleware, auth deps, Pydantic models
- 470-516 /health
- 518-625 auth and user routes
- 627-843 accounts, trades, goal group, watchlist
- 845-1027 quotes (Stooq, yfinance, /quotes)
- 1029-1077 static PWA mount
- 1079-1148 startup check, `--setup`, `__main__`
