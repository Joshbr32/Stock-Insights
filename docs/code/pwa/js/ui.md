# pwa/js/ui.js
**Purpose:** Presentation plumbing shared by the PWA modules: safe DOM builders, icons, number/date formatting, guarded localStorage, reduced-motion check.
**Used by:** `pwa/js/app.js`, `pwa/js/charts.js`.  **Depends on:** nothing (browser APIs only).

## Key types and functions
| Name | Kind | What it does / contract |
|---|---|---|
| `el(tag, attrs, children)` | fn | Creates an HTML element. `class`, `onX` (function => addEventListener), other attrs via setAttribute; `false`/`null` attrs skipped. Strings become text nodes. There is no `html` option on purpose (XSS). |
| `svg(tag, attrs, children)` | fn | Same, in the SVG namespace. |
| `icon(d)` / `ICONS` | fn / object | 24-unit stroke icon from path strings; `ICONS` has home, trades, goals, watch, settings, refresh, close. |
| `money(v, {whole})` | fn | `$1,234.56`, negatives as `−$88.00` (U+2212). `whole` drops cents. `—` for null/NaN. |
| `signedMoney(v, opts)` | fn | Always signed: `+$412.50`, `−$88.00`, `$0.00` near zero. |
| `num(v)`, `percent(v, d)` | fn | Plain number (max 2 decimals), `12.3%`. |
| `pctChange(v, d)` | fn | `▲ 4.2%` / `▼ 1.1%` so direction never relies on colour. |
| `tone(v)` | fn | `"good"` / `"bad"` / `""` CSS class with a 0.005 dead band. |
| `fmtShortDate`, `fmtClock`, `fmtIsoDate` | fn | "Mar 4", "2:14 PM", "Mar 4, 2026" (from YYYY-MM-DD, local time). |
| `plural(n, one, many?)` | fn | "1 trade" / "3 trades". |
| `store.get/set/remove` | object | localStorage wrapped in try/catch (private mode, quota). |
| `reducedMotion()` | fn | `prefers-reduced-motion: reduce`. |

## Data and state
None; `store` is the only storage access and holds no keys of its own.

## How to change it safely
- Keep every builder free of markup parsing; callers rely on it for XSS safety.
- Formatting changes show everywhere (home, goals, dialogs, toasts); keep U+2212 and the ▲/▼ glyphs (design-system.md).
- Adding a module-level export is safe; renaming breaks app.js/charts.js.

## Map
- 1-57 DOM builders, icons
- 59-106 number formatting
- 108-124 dates, plural
- 126-151 storage, reduced motion
