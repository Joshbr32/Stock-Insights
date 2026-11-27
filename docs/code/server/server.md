# server/server.py
**Purpose:** FastAPI sync server. Stores each user's accounts, trades, goal group and watchlist in SQL Server (pyodbc), proxies live quotes (Stooq, yfinance fallback) and serves the PWA (`../pwa`) from the same origin. Public via Cloudflare Tunnel (`si.coloniallawns.ca` -> origin :8742). Contract for 1.1 changes: `docs/api/server-1.1-changes.md`.
**Used by:** `stock_insights/api_client.py` + `sync_queue.py` (desktop, `requests`), `pwa/js/api.js` (PWA, `fetch`).  **Depends on:** fastapi (>=0.110, uses `lifespan`), uvicorn, pydantic v2, pyodbc (+ MS ODBC driver), python-dotenv (optional), requests (Stooq), yfinance (optional), stdlib `hashlib.scrypt`. Schema upgrades: `server/migrations/*.sql`. Config: `server/.env` (template `server/.env.example`). Tests: `tests/test_server.py`.

## HTTP contract (do not change routes or JSON shapes)
| Route | Auth | Body / query | Response |
|---|---|---|---|
| GET /health | none | - | `{ok, server_version, uptime_seconds, db_ok, db_error, schema: "ok"/"needs_migration"}` (db probe cached 5 s) |
| POST /auth/login | none | `{username, password}` | `{token, user_id, username, is_admin}`; 401; 429 throttled. Rehashes legacy PBKDF2 to scrypt |
| POST /auth/logout | bearer | - | `{ok}`; deletes by hash and raw token |
| GET /auth/me | bearer | - | `{user_id, username, is_admin}` |
| GET /users, POST /users, PUT /users/{id}/password, DELETE /users/{id} | admin (password: self or admin) | as before | password change revokes that user's other sessions |
| GET/PUT /accounts, PUT /accounts/{name}/settings | bearer | `?for_user_id` (admin) | unchanged |
| GET /trades | bearer | `?for_user_id` | `[{id, account, instrument, share_count, buy_price, sell_price, open_date, close_date, notes, is_pending, is_short, uid, tag}]` |
| PUT /trades/{account} | bearer | `{account_name, trades: [TradeIn]}` | `{ok}`; bulk replace of one account, auto-creates it; URL name wins |
| PUT /trades/{account}/{uid} | bearer | TradeIn | `{ok, uid}`; upsert by uid, moves between accounts, idempotent; 409 if uid is another user's; 422 bad uid; 503 reduced mode |
| DELETE /trades/{account}/{uid} | bearer | - | `{ok}` always (idempotent); matches uid within the user's accounts, ignores account name; 503 reduced mode |
| GET/PUT /goal-group, GET/PUT /watchlist, GET /quotes | bearer | unchanged | unchanged |
| /docs, /redoc, /openapi.json | none | - | only when `PORTFOLIO_ENABLE_DOCS=1`, else 404 |
| / (mount) | none | - | static PWA files |

`TradeIn`: instrument, share_count, buy_price, sell_price?, open_date?, close_date?, notes, is_pending, is_short, `tag` (<=40 chars, default ""), `uid` (optional, `^[0-9a-f]{32}$`).

## Key types and functions
| Name | Kind | Contract |
|---|---|---|
| `db()` | context manager | New pyodbc connection per call (ODBC pooling); commit on success, rollback on exception. |
| `_exec(conn, sql, *params)` | func | Only way queries run; always `?` placeholders. `_chunks`/`_placeholders` build `IN (?,?..)` lists of <=500. |
| `_SCHEMA` | dict | `{ok, trade_cols, password_wide}`. Defaults True (tests); set by `_migrate_schema`/`_refresh_schema_state`. `trade_cols` False = reduced mode: per-trade routes 503, GET returns `uid: ""`, `tag: ""`, bulk PUT ignores uid/tag. `password_wide` False = new hashes use legacy PBKDF2. |
| `_migrate_schema()` | func | Runs every GO-batch of `migrations/*.sql` (each in its own transaction), then `_refresh_schema_state()`. Never raises; logs ONE error with the fix if required columns are still missing. Called from `_lifespan` (uvicorn start) and `setup_admin`. |
| `_refresh_schema_state()` | func | `COL_LENGTH`/`INFORMATION_SCHEMA` probe. Also re-run by `_probe_db` while `ok` is False, so a manual migration is picked up without a restart. |
| `_hash_password` / `_verify_password` / `_needs_rehash` | func | scrypt `scrypt$15$8$1$<salt>$<hash>` (111 chars); legacy PBKDF2 `salt:hex` (260k) still verifies. Verify caps scrypt memory at 256 MiB. |
| `_DUMMY_HASH` | const | scrypt hash checked for unknown users (equal timing). |
| `_token_digest`, `_get_user_from_token` | func | Sessions store sha256(token) hex. Miss by hash -> try raw value (64-hex only) and rewrite the row to the hash, but only if the row expires before `_LEGACY_TOKEN_CUTOFF` (2027-02-01), so a stolen hash can't be replayed as a token. |
| `_account_id(conn, user, name)` | func | Account id, auto-creating it. |
| `_trade_values`, `_trade_key`, `_norm` | func | Column tuple in `_TRADE_COLS` order; content fingerprint used by the bulk PUT to keep uid+tag of unchanged trades when a 1.0 client sends no uids. |
| `replace_account_trades` | route | Delete account rows; supplied uids: delete the user's rows with those uids elsewhere (move), uids owned by another user get a fresh uid; duplicate uids in one batch get a fresh uid. |
| `upsert_trade` | route | Select by client_id -> UPDATE (incl. account_id) or INSERT; one retry on IntegrityError (concurrent insert of same uid). |
| login throttle (`_login_blocked` etc.) | func | 10 fails/15 min per username, 30 per IP (`CF-Connecting-IP`). In memory. |
| `_CacheControlMiddleware`, `_PWAStaticFiles` | ASGI | `no-store` on API responses; static files `no-cache`, hide `*.py/*.md`/dotfiles. |
| `_probe_db()` | func | Cached `SELECT 1` for /health. |

## Data and state
SQL Server DB `StockInsights` (base schema `init_stockinsights.sql`, NOT in repo). Tables: `dbo.users(id, username UNIQUE, password_hash NVARCHAR(255), is_admin, created_at)`, `dbo.sessions(token = sha256 hex, user_id, expires_at datetime2 naive UTC)`, `dbo.accounts(id, user_id, name, goal_target, goal_presets JSON text, position)`, `dbo.trades(id, account_id, instrument, share_count, buy_price, sell_price, open_date, close_date, notes, is_pending, is_short, tag NVARCHAR(40) NOT NULL DEFAULT '', client_id NVARCHAR(36) NULL = trade uid)`, `dbo.goal_group`, `dbo.watchlist`. Indexes added by migration 001: `UX_trades_client_id` (filtered unique), `IX_trades_account_id`, `IX_sessions_user_id`, `IX_sessions_expires_at` (each only if no index already leads with that column).
Account delete relies on FK cascade to trades. Expired sessions pruned on each login.
In-process: `_QUOTE_CACHE`, `_LOGIN_FAILS`, `_health_cache`, `_SCHEMA`. Single process only.
Env: `PORTFOLIO_SQL_SERVER/DATABASE/USER/PASSWORD` (password required), `PORTFOLIO_HOST`, `PORTFOLIO_PORT`, `PORTFOLIO_PWA_DIR`, `PORTFOLIO_CORS_ORIGINS`, `PORTFOLIO_ENABLE_DOCS`.

## How to change it safely
- Never read `server/.env`; never point tests at the real SQL Server or tunnel.
- Routes/JSON shapes are shared with `api_client.py`, `sync_queue.py`, `pwa/js/api.js`; change all together and update `docs/api/`. `SERVER_VERSION` is bumped only by the lead.
- New schema change = new `migrations/NNN_*.sql`; every batch guarded and self-contained (dynamic `EXEC` when it references a column added in the same file). Update `_SCHEMA_PROBE_SQL`/`_SCHEMA` if code depends on it, and keep a reduced-mode path.
- Static mount must stay the LAST route registration.
- Don't use `SCOPE_IDENTITY()` in a separate `execute()` (new scope -> NULL); re-select by natural key.
- Route handlers stay sync `def` (pyodbc blocks; they run in the threadpool).
- Filtered index => sessions writing `dbo.trades` need QUOTED_IDENTIFIER/ANSI_NULLS ON (ODBC default).
- Test: `./.venv/Scripts/python.exe -m pytest tests/test_server.py -q` (sqlite-backed fake pyodbc, raw ASGI calls; no httpx needed).

## Map
- 1-60 docstring, imports
- 61-148 .env loading, dependency guards, config (`DOCS_ENABLED`, `SERVER_VERSION`)
- 150-248 DB helpers (`db`, `_one/_all/_scalar/_exec`, `_chunks`)
- 250-345 schema check / migration (`_SCHEMA`, `_migrate_schema`)
- 347-482 passwords (scrypt/PBKDF2), tokens (hash, legacy upgrade)
- 484-533 login throttling
- 535-688 app + lifespan + middleware, auth deps, Pydantic models (`TradeIn`)
- 689-740 /health
- 742-864 auth and user routes
- 866-939 accounts
- 941-1181 trades (helpers, GET, bulk PUT, per-trade PUT/DELETE)
- 1183-1257 goal group, watchlist
- 1259-1441 quotes
- 1443-1491 static PWA mount
- 1493-1565 startup check, `--setup`, `__main__`
