# pwa/js/api.js
**Purpose:** ES module exporting `Api`, the PWA's only HTTP client for the FastAPI server (`server/server.py`). Holds the bearer token and cached user info in localStorage.
**Used by:** `pwa/js/app.js` (`import {Api} from "./api.js"`).  **Depends on:** browser `fetch`, `AbortController`, `localStorage`, `navigator.onLine`. Route contract: see `docs/code/server/server.md`.

## Key types and functions
| Name | Kind | Contract |
|---|---|---|
| `Api.getServer()` | method | API base URL: `window.SI_API_URL` if set, else `location.origin`, trailing slashes stripped. |
| `Api.getToken() / getUser() / isAuthed() / clearAuth()` | methods | localStorage auth state. `getUser()` returns null on a corrupt entry. |
| `Api._request(path, opts)` | method | `opts = {method, body, headers, skipAuth, timeoutMs}`. Resolves to parsed JSON (null for empty/204). Rejects with `Error` having `.code` = HTTP status, or 0 for offline / unreachable / timeout. 401 (unless `skipAuth`) clears auth and rejects with "Session expired". |
| `Api.login(u, p)` | async | POST /auth/login, stores token + `{user_id, username, is_admin}`. Returns server JSON. 429 = throttled (message from server). |
| `Api.logout()` | async | Best-effort POST /auth/logout (5 s timeout), always clears auth. |
| `getAccounts, saveAccounts(accounts)` | methods | GET / PUT /accounts. |
| `getTrades, replaceAccountTrades(name, trades)` | methods | GET /trades; PUT /trades/{encoded name} with `{account_name, trades}`. |
| `getGoalGroup, setGoalGroup(names, goal)` | methods | GET / PUT /goal-group. |
| `getWatchlist, setWatchlist(symbols)` | methods | GET / PUT /watchlist. |
| `getQuotes(symbols)` | async | De-dupes + upper-cases, GET /quotes; `{}` for an empty list. |

## Behaviour
- Timeout `TIMEOUT_MS` = 15 s via AbortController.
- GETs retry once after 600 ms on a network error or 502/503/504 (Cloudflare while the origin restarts). PUT/POST never retry.
- `navigator.onLine === false` fails fast with "You're offline".
- `Content-Type: application/json` only when there is a body (avoids CORS preflight on GETs when cross-origin).
- `cache: "no-store"` on every fetch; the server also sends `Cache-Control: no-store` on API responses.
- FastAPI 422 `detail` arrays are flattened into a readable message.

## Data and state
localStorage: `si.token` (bearer token, 30-day server expiry), `si.user` (JSON `{user_id, username, is_admin}`). Legacy `si.server` is removed on load.

## How to change it safely
- app.js calls these methods by name and relies on `err.code === 401` and `err.message`; keep names, signatures and resolve shapes.
- Changing this file changes the SW app shell: the lead must bump `VERSION` in `pwa/sw.js`.
- No node in the dev environment; syntax/behaviour can be checked by loading the code in headless Edge with a stubbed `fetch`.

## Map
- 1-50 header, constants, `_apiError`, `_detailMessage`, `_sleep`
- 52-80 server URL + auth state
- 82-146 `_request`
- 148-172 login / logout
- 174-221 resource calls
