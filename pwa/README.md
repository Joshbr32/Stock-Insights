# Stock Insights — Mobile PWA

A phone-friendly Progressive Web App that talks to your existing Stock
Insights FastAPI backend. Built as a companion to the desktop client —
same data, same accounts, just optimized for a phone screen.

## What you get

- **Home** - the pace rail (are you on pace for this year's goal?), total and
  unrealised P/L, open positions with a per-symbol drill-down, and a
  performance section: equity curve (with the goal's pace line), trade
  analytics, and date-range / tag filters that persist across reloads
- **Trades** - list, log, edit and delete trades; long/short and pending orders
- **Goals** - shared and per-account goals, each with its own pace rail and
  "needed per month / week / day" numbers
- **Watchlist** - add and remove symbols, live prices
- **Settings** - who you're signed in as, back up / restore (same JSON format
  as the desktop), sign out
- Live prices refresh every minute while the app is on screen and pause in the
  background; light and dark follow the phone's setting
- Installs to the home screen and opens offline (last-loaded shell)

The visual language is "Harbor", shared with the desktop app:
`docs/design/design-system.md`.

---

## Setup (one-time)

### 1. Patch your server

Open `misc_helpers/server.py` and paste the contents of
`server_quotes_patch.py` (everything below the marker line) into the
route-handlers section — anywhere before the `_test_connection` function
works. This adds a `GET /quotes` endpoint that the PWA needs for live
prices (it proxies through your server's existing `yfinance` install,
which avoids browser CORS issues with Yahoo).

Restart the server.

### 2. Decide how to host the static files

Pick one of these — they all work:

**Option A — serve from the same FastAPI server (simplest).** Add this
near the top of `server.py`, after the `app = FastAPI(...)` line:

```python
from fastapi.staticfiles import StaticFiles
import pathlib

_PWA_DIR = pathlib.Path(__file__).parent / "pwa"
if _PWA_DIR.exists():
    app.mount("/", StaticFiles(directory=str(_PWA_DIR), html=True), name="pwa")
```

Then copy this whole folder into `misc_helpers/pwa/` next to
`server.py`. Restart, and it's live at `http://your-server:8742/`.

> ⚠️ Mount the static files **last** so it doesn't shadow API routes.
> If routes start 404'ing, move the mount to the bottom of `server.py`.

**Option B — host the static files anywhere.** Vercel, Netlify, GitHub
Pages, an nginx box, `python -m http.server` on your LAN — anything that
serves static files works. The PWA is pure HTML/CSS/JS with no build
step. Just upload the contents of this folder.

**Option C — local quick test.** From this folder:

```bash
python -m http.server 8000
```

Then visit `http://localhost:8000` on your computer first to verify
everything works before going mobile.

### 3. HTTPS gotcha

PWAs require a "secure context" — i.e. **HTTPS or localhost**. Service
workers won't register otherwise, which means no install-to-home-screen.

**This deployment already solves that**: a Cloudflare Tunnel terminates
HTTPS at the edge and proxies to the origin server on port 8742, so
the PWA is reachable at <https://si.coloniallawns.ca/> with no extra
config on the phone. The home IP stays private; only Cloudflare's
edge accepts inbound traffic.

If you ever need to re-create this from scratch on a different machine:

- **Cloudflare Tunnel** in front of port 8742 (free, gives you a real
  HTTPS URL and protects your home IP). What this deployment uses.
- **Caddy** as a reverse proxy with auto-HTTPS via Let's Encrypt.
- **Tailscale** if it's just for you — your phone gets a private
  HTTPS-on-magic-DNS URL like `https://your-server.tailnet.ts.net`.

For local-network testing (phone on same Wi-Fi as desktop server), most
browsers also allow PWA features when accessing `http://localhost`,
but **not** plain `http://192.168.x.x`. So the tunnel is also the
friction-free answer when you're on Wi-Fi.

### 4. Connect your phone

1. Open the URL where you hosted the PWA in your phone's browser
   (Safari on iOS, Chrome on Android). For this deployment that's
   **<https://si.coloniallawns.ca/>** — the Cloudflare Tunnel into
   the sync server.
2. Sign in with your normal Stock Insights credentials. The PWA
   auto-detects the API server from the page's origin, so no separate
   URL field is needed.
3. Add to home screen:
    - **iOS:** Share → "Add to Home Screen"
    - **Android:** ⋮ menu → "Install app" or "Add to home screen"

The token lasts 30 days, so you won't need to log in every time.

---

## File map

```
.
├── index.html                 # App shell
├── styles.css                 # All styling (Harbor tokens, light/dark)
├── manifest.webmanifest       # PWA install metadata
├── sw.js                      # Service worker (offline shell)
├── js/
│   ├── api.js                 # Fetch wrapper for the FastAPI backend
│   ├── portfolio.js           # JS port of compute fns from portfolio.py
│   ├── app.js                 # State, data loading, views, dialogs
│   ├── charts.js              # Pace rail + equity-curve chart
│   ├── ui.js                  # DOM builders, formatting, safe localStorage
│   └── demo.js                # ?demo fixtures (loaded on demand, not precached)
├── icons/                     # PWA icons (192, 512, maskable)
├── make_icons.py              # Regenerate icons (optional)
└── server_quotes_patch.py     # Server-side patch — adds /quotes endpoint
```

---

## How it talks to your server

The PWA hits these existing endpoints (no new ones beyond `/quotes`):

| Verb | Path                   | Used for                                     |
|------|------------------------|----------------------------------------------|
| POST | /auth/login            | Sign in                                      |
| POST | /auth/logout           | Sign out                                     |
| GET  | /accounts              | Account list + targets                       |
| GET  | /trades                | All trades for user                          |
| PUT  | /trades/{account_name} | Save trades for one account (atomic replace) |
| GET  | /goal-group            | Shared goal config                           |
| GET  | /watchlist             | Watchlist symbols                            |
| PUT  | /watchlist             | Save watchlist                               |
| GET  | /quotes?symbols=A,B,C  | **NEW** — live prices                        |

Trade writes use the same atomic-replace-account-trades pattern as the
desktop app, so adding/editing/deleting from your phone won't conflict
with simultaneous edits on desktop *for different accounts*. Within a
single account, last-write-wins.

---

## Updating the PWA — `sw.js` cache busting

The service worker caches the app shell (HTML/CSS/JS) under a versioned
key — phones keep serving the cached files until the version changes.
**After editing any shell file you MUST bump `VERSION` in `pwa/sw.js`**
(e.g. `si-shell-v3` → `si-shell-v4`), otherwise deployed updates never
reach installed PWAs.

The repo ships a pre-commit hook that enforces this for you. Install
it once per checkout:

```sh
bash scripts/install-git-hooks.sh
```

After install, any commit that touches a shell file (`pwa/js/*.js`,
`pwa/styles.css`, `pwa/index.html`) without also touching `pwa/sw.js` is
blocked with a reminder. New JS modules must also be added to the `SHELL`
precache list in `sw.js`, or the app won't open offline. Bypass for
non-deploy commits with `git commit --no-verify`.

---

## Customizing

- **Colors / fonts** - all tokens are CSS custom properties at the top of
  `styles.css` (light) with dark overrides under
  `@media (prefers-color-scheme: dark)`. They mirror the Harbor token table in
  `docs/design/design-system.md`; change both together. Fonts are the system
  stack only (no web fonts, so cold starts and offline use cost nothing).
- **Quote refresh interval** — edit `QUOTE_TTL` in `server_quotes_patch.py`
  (default 20s). The PWA polls `/quotes` every 60 s while visible
  (`QUOTE_POLL_MS` in `js/app.js`), stops in a background tab, and reloads
  everything when you come back after 5 minutes (`STALE_RELOAD_MS`).
- **Demo mode** - open `index.html?demo` (or `?demo=login`, `?demo=offline`)
  to see every view with fixture data and no network. Serve the folder with
  `python -m http.server 8000 --directory pwa`. Demo mode never registers the
  service worker.
- **Adding new fields to a trade** — add to the `incoming` object in
  `saveTradeFromForm` and `toTradeIn` (`js/app.js`) and the `TradeIn` model
  on the server.

---

## Known limitations

- **Account creation** — the PWA doesn't currently create new accounts
  or edit goal targets / presets. Do those in the desktop app; the PWA
  picks them up. (Easy to add — `Api.saveAccounts` is wired, just no UI
  for it yet.)
- **Trade reordering** — the desktop has drag-to-reorder; on mobile,
  trades sort newest-first by id.
- **No offline writes** — service worker caches the app shell so it
  *opens* offline, but writes always go straight to the server.
- **Trade tags** - the PWA sends `tag` with every trade, but the server's
  `TradeIn` model has no `tag` field yet, so tags set on the phone are dropped
  on save until the server stores them.
