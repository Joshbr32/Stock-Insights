# Stock Insights — Mobile PWA

A phone-friendly Progressive Web App that talks to your existing Stock
Insights FastAPI backend. Built as a companion to the desktop client —
same data, same accounts, just optimized for a phone screen.

## What you get

- 📈 **Portfolio** — combined or per-account market value, holdings table,
  trade analytics, and an equity-curve chart of cumulative realized P/L
- 🗓️ **Date-range filter** — All time / This week / This month / Last 30
  days / YTD. Drives both the analytics card and the trade list, mirroring
  the desktop app's filter (and persisting across reloads via localStorage)
- 📒 **Trades** — list, add, edit, delete trades; supports long/short and
  pending orders
- 🎯 **Goals** — shared and per-account goal dashboards with progress bars
  and "what's needed per day/week/month" math
- ⭐ **Watchlist** — add/remove symbols, live prices
- 🔒 Login with the same credentials as the desktop app
- 📱 Installs to home screen, works in dark mode automatically

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

If you're going to access the PWA from your phone over the internet
(not on the same Wi-Fi as the server), you need HTTPS. Easiest paths:

- **Cloudflare Tunnel** in front of port 8742 (free, gives you a real
  HTTPS URL and protects your home IP). Recommended.
- **Caddy** as a reverse proxy with auto-HTTPS via Let's Encrypt.
- **Tailscale** if it's just for you — your phone gets a private
  HTTPS-on-magic-DNS URL like `https://your-server.tailnet.ts.net`.

For local-network testing (phone on same Wi-Fi as desktop server), most
browsers also allow PWA features when accessing `http://localhost`,
but **not** plain `http://192.168.x.x`. So a tunnel or Tailscale really
is the friction-free answer.

### 4. Connect your phone

1. Open the URL where you hosted the PWA in your phone's browser
   (Safari on iOS, Chrome on Android).
2. On the login screen, enter your server URL — e.g.
   `https://your-tunnel-url.example.com` or `http://66.225.151.13:8742`
   if you're on the same network. Trailing slash is fine; the PWA
   strips it.
3. Sign in with your normal Stock Insights credentials.
4. Add to home screen:
    - **iOS:** Share → "Add to Home Screen"
    - **Android:** ⋮ menu → "Install app" or "Add to home screen"

The token lasts 30 days, so you won't need to log in every time.

---

## File map

```
.
├── index.html                 # App shell
├── styles.css                 # All styling (editorial / cream paper aesthetic)
├── manifest.webmanifest       # PWA install metadata
├── sw.js                      # Service worker (offline shell)
├── js/
│   ├── api.js                 # Fetch wrapper for the FastAPI backend
│   ├── portfolio.js           # JS port of compute fns from portfolio.py
│   └── app.js                 # Views, routing, event handlers
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

## Customizing

- **Colors / fonts** — all design tokens are CSS variables at the top of
  `styles.css`. The accent color is `--accent`, and dark-mode overrides
  live in the `@media (prefers-color-scheme: dark)` block. The aesthetic
  is "editorial broadsheet": Fraunces for display headlines, JetBrains
  Mono for tabular numbers, warm cream paper background. Tweak away.
- **Quote refresh interval** — edit `QUOTE_TTL` in `server_quotes_patch.py`
  (default 20s). The PWA itself only refreshes on demand (pull the ↻
  button or switch tabs).
- **Adding new fields to a trade** — add to the `incoming` object in
  `saveTradeFromForm` (`js/app.js`) and the `TradeIn` model on the server.

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
