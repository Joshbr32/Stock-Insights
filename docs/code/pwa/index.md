# pwa/index.html
**Purpose:** The PWA's only HTML page: meta tags for install/theming, manifest and icon links, the stylesheet, and the `app.js` module. The body is empty; app.js renders everything.
**Used by:** the FastAPI static mount / any static host; precached by `pwa/sw.js`.  **Depends on:** `styles.css`, `js/app.js`, `manifest.webmanifest`, `icons/`.

## Key parts
| Name | Kind | What it does / contract |
|---|---|---|
| `theme-color` metas | meta | Harbor `bg`: `#E8ECEF` light, `#161D24` dark (per `prefers-color-scheme`). |
| `color-scheme` meta | meta | `light dark` so form controls and scrollbars follow the theme. |
| `viewport` | meta | `viewport-fit=cover`; styles.css pads with `env(safe-area-inset-*)`. |
| `apple-mobile-web-app-status-bar-style` | meta | `default` (not translucent), so the status bar never covers the top bar. |
| `<script type="module" src="./js/app.js">` | script | Entry point. |

## How to change it safely
- No web fonts or third-party origins: the app must start offline and fast.
- Any change here needs a `VERSION` bump in `pwa/sw.js`.
- `manifest.webmanifest` still has the old cream `background_color`/`theme_color` (`#f4eee0`); it should be `#E8ECEF` (owned elsewhere).

## Map
- 3-20 head (metas, manifest, icons, stylesheet)
- 21-28 body (noscript, module script)
