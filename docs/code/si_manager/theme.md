# si_manager/theme.py
**Purpose:** The manager's Harbor look: tokens (light/dark), fonts, palette and one stylesheet. Its own copy so the manager never imports `stock_insights.theme` (and with it the desktop app).
**Used by:** every `si_manager` module.  **Depends on:** PySide6.

## Key types and functions
| Name | Kind | Contract |
|---|---|---|
| `HARBOR` | dict | Harbor tokens from `docs/design/design-system.md` plus three for this app: `warn` (text-safe amber, light `#8F5B00`, dark `#E9B04A`), `warn_tint`, `bad_tint` (verdict bar and warning lines). `pace` is not used: it is reserved for the pace rail. |
| `apply(app)` | func | Picks light/dark (`SI_MANAGER_THEME=light|dark` forces one; else Qt's colour scheme), resolves fonts (Segoe UI Variable Text/Display, else Segoe UI; Cascadia Mono, else Consolas for output and commands), sets palette and stylesheet. Call once before building widgets. |
| `c(token)`, `qc(token, alpha)`, `tone_color(tone)` | func | Current-mode colour lookups. |
| `font(px, weight, display)`, `mono_font(px)` | func | Fonts in pixel sizes (13 body, 12 small, 15/16 titles, 20 page state). |
| `stylesheet()` | func | QSS; object names used: `page`, `panel`, `panelTitle`, `muted`, `nav`, `primary`, `danger`, `output`, `command`, `stale`. |

## How to change it safely
Keep shared token values equal to `stock_insights/theme.py` `_HARBOR`. Contrast: `warn` on `card` is about 6:1 in light mode. Theme is fixed at start-up (no live switching).

## Map
- 1-40 docstring, tokens, radii
- 43-90 lookups, fonts, mode detection
- 92-114 `apply`
- 116-end `stylesheet`
