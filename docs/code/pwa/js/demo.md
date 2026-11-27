# pwa/js/demo.js
**Purpose:** Offline demo mode for design review and manual testing: replaces the `Api` object's methods with in-memory fixtures so every view renders with no server.
**Used by:** `pwa/js/app.js` (dynamic `import("./demo.js")` only when the URL has `?demo`).  **Depends on:** nothing.

## Key types and functions
| Name | Kind | What it does / contract |
|---|---|---|
| `installDemo(Api)` | fn | Mutates `Api` in place: auth always on, fixtures for accounts (Main 12k goal, Roth 5k, Swing none), a Main+Roth shared goal of 20k, 46 closed trades over ~10 months plus open long, open short, pending order, a watchlist, jittered quotes. Writes change the in-memory copy only. |

URL variants: `?demo` (signed in), `?demo=login` (starts at the login screen; any password works), `?demo=offline` (quotes fail, to show the "prices unavailable" state).

## Data and state
In memory only; reload resets everything. Trade dates are relative to today, generated with a fixed seed so screenshots repeat.

## How to change it safely
- Must stay off by default and never be needed by the normal app path. It is intentionally not in `sw.js`'s precache list, and app.js skips service-worker registration in demo mode so fixtures are never cached.
- When `api.js` gains a method the app uses, add a fake here or demo mode throws.
- One fixture note contains `<b>` markup on purpose, to check that notes render as text.

## Map
- 1-49 symbols, date helper, `fixtureTrades()`
- 51-104 `installDemo`
