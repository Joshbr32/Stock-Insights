# stock_insights/theme.py
**Purpose:** Colour tokens for the 9 selectable themes ("Default" = Harbor), font resolution, and the ThemeManager that installs the QPalette + global widget QSS and tells the QML scene to refresh.
**Used by:** main.py (startup theme), main_window.py (owns a ThemeManager as `self.theme`), qml_bridge.py (ThemeController reads tokens/fonts), widgets.py (`theme_color()` via `tm.tokens()`), settings_dialog.py (`THEME_NAMES`, `FONT_SIZE_LABELS`), portfolio_tab.py (colour accessors, row tints).  **Depends on:** PySide6 (QtCore/QtGui/QtWidgets), winreg + ctypes on Windows, `assets/chevron-*.svg`.

## Key types and functions
| Name | Kind | What it does / contract |
|---|---|---|
| `_HARBOR` | dict | Harbor light/dark tokens straight from docs/design/design-system.md, plus widget helpers `button`, `secondary`, `focus`. |
| `_THEMES` | dict | name -> {"light": tokens, "dark": tokens}. Every token set has: bg, card, card2, text, text_muted, border, primary, text_on_color, button, secondary, good, bad, pace, focus. `pace`/`focus` are derived from `secondary` for the 8 legacy themes (loop after the dict). |
| `THEME_NAMES`, `FONT_SIZES`, `FONT_SIZE_LABELS` | consts | Public; Settings dialog + main_window use them. Order of THEME_NAMES = dict order. |
| `_UI` | dict | Radii/padding for the QSS (panels 10, controls 6, rows 32). |
| `resolve_fonts()` | func | `{"text", "display"}` families, resolved once (cached) via QFontDatabase: Segoe UI Variable Text/Display -> Segoe UI -> system font. Needs a QGuiApplication; returns empty strings before one exists (not cached). |
| `reduce_motion_enabled()` | func | True when Windows "Show animations" is off (SPI_GETCLIENTAREAANIMATION). |
| `ChevronProxyStyle` | QProxyStyle | Draws chevrons for arrow primitives; `pixelMetric(PM_HeaderDefaultSectionSizeVertical)` = 32 so every QTableView gets 32 px rows (read when the header is created). |
| `ThemeManager(window, poll_secs=3)` | QObject | Public attrs: `override_mode` (System/Light/Dark), `match_system_accent`, `theme_name`, `font_size_label`. Methods: `set_override_mode`, `set_match_system_accent`, `set_theme`, `set_font_size`, `apply`, `start_watching`, `stop_watching`, `current_state`. Signal `themeApplied` (end of apply and on font-size change). UI thread only. |
| `ThemeManager.tokens()` / `is_light()` / `font_families()` / `reduce_motion()` | methods | Public read API added for QML bridge + widgets. `tokens()` returns a copy. |
| colour accessors | methods | `profit_color, loss_color, text_color, border_color, button_color, selected_surface_color, selected_text_color, focus_border_color, pace_color` -> hex; `waiting_row_tint` (muted wash) / `short_row_tint` (primary wash) -> RGBA tuples. |
| `_themed_palette(t)` / `_themed_stylesheet(t)` | methods | Build the QPalette / global QSS for any token set (one generator for all themes). |

## Data and state
No persistence here: main_window/main.py read/write the QSettings keys `ui/THEME_OVERRIDE`, `ui/MATCH_SYSTEM_ACCENT`, `ui/THEME_NAME`, `ui/FONT_SIZE` and assign the attributes. `_last_state` caches the last applied (mode, accent, theme, font) tuple so the 3 s poll only re-applies on change. `_resolved_fonts` is a module-level cache.

## How to change it safely
- Never remove/rename a theme name, token, public method or attribute; other modules and saved settings depend on them. Add tokens to `_HARBOR` and either every legacy theme or the derivation loop.
- `pace` (amber) is reserved for the pace rail tick and equity-curve pace line. Don't use it for text or other UI.
- QSS selectors used by other files: `#leftPane`, `#leftTitle`, `#watchTableCard`, `#watchTable`, `#menuStatusCorner`. Widget dialogs owned by other teammates rely on the generic rules (QPushButton:default = primary fill, 2 px focus ring in `focus`, controls radius 6). Focus rules shrink padding by 1 px to offset the 2 px border; keep them paired.
- `match_system_accent` no longer recolours Harbor (fixed primary #2C55C9 / #7FA2FF); the attribute/setter still exist for the Settings checkbox.
- High-contrast mode: `apply()` clears the stylesheet and returns early (no themeApplied emit).
- Verify: `python -m compileall -q stock_insights/theme.py`, `python scripts/ui_snapshot.py --out <dir> [--theme "Warm Earth"]`, open a few dialogs.

## Map
- 1-30 module docstring, imports
- 32-75 `_HARBOR` tokens; 77-334 `_THEMES` (legacy palettes); 336-347 derivation loop + public consts
- 350-366 `_UI`; 368-396 fonts (`resolve_fonts`)
- 398-431 Windows accessibility probes; 433-502 `ChevronProxyStyle`
- 504-578 ThemeManager init + Windows helpers; 580-708 public API, `apply()`
- 710-757 colour accessors; 759-776 palette; 777-end QSS generator
