# Server 1.1: tags, per-trade saves, hashed tokens, stronger passwords

The contract shared by `server/server.py`, the desktop client (`stock_insights/api_client.py`,
`sync_queue.py`) and the PWA (`pwa/js/api.js`, `app.js`). Change all three together.

## Database (migration `server/migrations/001_tags_trade_uid.sql`, also applied idempotently at server start)

| Change | Detail |
|---|---|
| `dbo.trades.tag` | `NVARCHAR(40) NOT NULL DEFAULT ''` |
| `dbo.trades.client_id` | `NVARCHAR(36) NULL`; backfilled for existing rows with `LOWER(REPLACE(CONVERT(NVARCHAR(36), NEWID()), '-', ''))`; filtered unique index `UX_trades_client_id` on `(client_id) WHERE client_id IS NOT NULL` |
| `dbo.users.password_hash` | widened to `NVARCHAR(255)` if narrower |
| `dbo.sessions.token` | unchanged type; now stores `sha256(token)` hex (64 chars) instead of the token |
| Indexes | `IX_trades_account_id`, `IX_sessions_user_id`, `IX_sessions_expires_at` if missing |

If the server's SQL login lacks `ALTER` rights the start-up migration logs one clear error and the
server keeps running; `/health` reports `"schema": "needs_migration"` and the admin runs the `.sql`
file once (SSMS or `sqlcmd`) as an owner.

## Trade identity: `uid`

- Every trade has a client-generated `uid`: 32 lowercase hex chars (uuid4 without dashes).
  Clients create it when the trade is first logged, so trades created offline keep a stable id and
  replaying a queued save is idempotent.
- The server stores it in `dbo.trades.client_id`. `uid` is unique per database (uuid4).
- Trades without a uid (old clients, old backups) get one: the server generates it on insert;
  clients generate one when loading a trade without it.

## HTTP

| Route | Change |
|---|---|
| `GET /trades` | each row adds `"uid": str` and `"tag": str` |
| `PUT /trades/{account_name}/{uid}` | **new**. Body: `TradeIn`. Upsert one trade by uid: insert, update in place, or move it to `account_name` (account auto-created as today). Idempotent. Returns `{"ok": true, "uid": uid}` |
| `DELETE /trades/{account_name}/{uid}` | **new**. Idempotent: 200 `{"ok": true}` whether or not it existed. Only deletes a trade of that user |
| `PUT /trades/{account_name}` | unchanged route (bulk replace, used by restore and old clients). `TradeIn` accepts optional `uid` (kept if given, generated if not) and `tag` |
| `TradeIn` | adds `tag: str = ""` (max 40), `uid: Optional[str] = None` (validated `^[0-9a-f]{32}$`) |
| `/docs`, `/redoc`, `/openapi.json` | **off** unless `PORTFOLIO_ENABLE_DOCS=1` |
| `/health` | adds `"schema": "ok" | "needs_migration"` |

`for_user_id` (admin) works on the new routes exactly as on the existing ones.

## Auth

- **Session tokens**: the client still receives the raw 64-hex token. The server stores and looks up
  `sha256(token).hexdigest()`. Legacy rows that hold a raw token: when a lookup by hash misses, look
  up the raw value once; if found, rewrite that row to the hash and continue. Logout and password
  changes delete by hash (and raw, during the transition).
- **Passwords**: new format `scrypt$<log2 N>$<r>$<p>$<salt hex>$<hash hex>` with N=2^15, r=8, p=1,
  16-byte salt, 32-byte key (≈ 111 chars), using stdlib `hashlib.scrypt`. Legacy `salt:hex`
  PBKDF2 hashes still verify; on a successful login with a legacy hash, rehash and store the new
  format. `_DUMMY_HASH` uses the new format so unknown-user timing matches.

## Versions

`SERVER_VERSION` 1.1.0, `APP_VERSION` 1.1.0, `pwa/sw.js` `VERSION` si-shell-v7 (the lead bumps them).
