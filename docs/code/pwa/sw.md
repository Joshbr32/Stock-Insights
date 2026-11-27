# pwa/sw.js
**Purpose:** Service worker giving the PWA installability and an offline app shell. Registered by `pwa/js/app.js` (`navigator.serviceWorker.register("./sw.js")`).
**Used by:** the browser.  **Depends on:** Cache Storage. Related: `pwa/manifest.webmanifest` (name, icons, theme `#f4eee0`, `start_url`/`scope` `./`), `scripts/pre-commit-pwa-version-check` (blocks shell edits without a VERSION bump).

## Key parts
| Name | Kind | Contract |
|---|---|---|
| `VERSION` | const | Cache name (`si-shell-vN`). Bump whenever any SHELL file changes. Only the lead changes it. |
| `CACHE_PREFIX` | const | Only caches with this prefix are deleted on activate. |
| `SHELL` | const | Pre-cached on install with `cache: "reload"` (bypasses the HTTP cache). |
| `STATIC_EXT` | regex | Only these extensions are served from / written to the cache. |
| install | handler | Pre-cache SHELL, `skipWaiting()`. |
| activate | handler | Delete old `si-shell-*` caches, `clients.claim()`. |
| fetch | handler | See strategy. |

## Strategy
- Non-GET, cross-origin, or carrying `Authorization`: not intercepted (network only).
- Navigations: cache (ignoring query string) -> network -> cached `./index.html` when offline.
- Same-origin static asset (`STATIC_EXT`): cache-first, then network, successful responses cached.
- Everything else same-origin (`/health`, `/quotes`, `/trades`, `/docs`, ...) is API: not intercepted. The API is served from the same origin as the PWA, so this rule is what keeps portfolio data from being served stale.
- No Google Fonts rules: the PWA no longer uses font hosts, and cross-origin requests are never cached.

## How to change it safely
- Any edit to a SHELL file (index.html, styles.css, js/*.js, manifest, icons) needs a `VERSION` bump, otherwise installed phones keep the old copy (cache-first).
- Never cache API responses here; they are per-user and the server marks them `no-store`.
- No node available; parse-check by loading the file text in headless Edge (`new Function(src)`).

## Map
- 1-24 header comment, `VERSION` + history
- 25-39 `CACHE_PREFIX`, `SHELL`, `STATIC_EXT`
- 41-57 install / activate
- 59-96 fetch
