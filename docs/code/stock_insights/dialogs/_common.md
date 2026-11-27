# stock_insights/dialogs/_common.py
**Purpose:** Dialog-only helpers: money/goal formatting, goal/preset/price/share spin boxes, date edit factory, default goal presets.
**Used by:** dialogs/goal_options, trade_actions, trade_edit; portfolio_tab (`_fmt_*`, `_DEFAULT_PRESETS`).  **Depends on:** `widgets.fmt_money`.

## Key types and functions
| Name | Kind | What it does / contract |
|---|---|---|
| `_fmt_money(v)` / `_fmt_goal(v)` | funcs | `$1,234.56` / `$500,000` (U+2212 for negatives). |
| `_fmt_preset_label(v)` | func | `250K`, `1M`, `1.5M`. |
| `_make_goal_spin(value, min_width)` / `_make_preset_spin(value)` | funcs | Whole-dollar QDoubleSpinBox, `$` prefix, step 10,000. |
| `price_spin(value, minimum, blank_at_minimum)` | func | 2-decimal `$` field; blank (not `$0.00`) at minimum when asked. |
| `shares_spin(value, step)` | func | 1..1e9 with thousands separators. |
| `date_edit(value=None)` | func | Calendar popup, `MMM d, yyyy`, defaults to today. |
| `_DEFAULT_PRESETS` | const | `[250k, 500k, 1M]`. |

## Data and state
None (the unused QSettings preset loaders and `GROUP_STYLE` were removed).

## How to change it safely
Formatting changes show up in PortfolioTab and every dialog; keep Harbor's sign rules (`+$`, `−$`).

## Map
- 1-17 imports/constants; 20-36 formatters; 39-52 goal spins; 55-90 price/shares/date factories
