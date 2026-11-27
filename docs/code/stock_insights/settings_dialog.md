# stock_insights/settings_dialog.py
**Purpose:** File > Settings form: price refresh, connection check interval, new-trade defaults, appearance (theme, mode, text size).
**Used by:** main_window `_open_settings_dialog`.  **Depends on:** `theme` (THEME_NAMES, FONT_SIZE_LABELS), `widgets`.

## Key types and functions
| Name | Kind | What it does / contract |
|---|---|---|
| `SettingsDialog(parent, settings, current_values)` | QDialog | `current_values` keys: `L1_INTERVAL`, `NET_INTERVAL` (ms), `L1_ENABLED`, `THEME_OVERRIDE` (System/Light/Dark), `MATCH_SYSTEM_ACCENT`, `THEME_NAME`, `FONT_SIZE`, `TRADE_DEFAULT_QUANTITY`, `TRADE_QUANTITY_INCREMENT`. `settings` is unused (API compat). |
| `get_values() -> dict` | method | Same keys; intervals back in ms. Mode combo stores the value in item data ("Match Windows" → "System"). |

## Data and state
None; the caller persists to QSettings.

## How to change it safely
- Keep the key names: main_window reads them.
- `cb_match_system_accent` is hidden because no theme uses the Windows accent any more; its value still round-trips.
- Interval ranges 5–600 s.

## Map
- 1-31 docstring, imports, helpers; 34-104 `__init__` (Prices, Connection, New trades, Appearance panels); 106-117 `get_values`
