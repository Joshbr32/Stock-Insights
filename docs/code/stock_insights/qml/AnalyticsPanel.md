# stock_insights/qml/AnalyticsPanel.qml
**Purpose:** Performance statement for the selected date range/tag: 14 Metric rows in three groups (results, trade quality, risk & counts) plus the tag and range combos.
**Used by:** PortfolioView.  **Depends on:** Metric, ThemedComboBox, SectionTitle; `account.analytics`, `availableTags`, `tagFilter`, `dateRangeKey`, `setTagFilter`, `setDateRange`.

## Key types and functions
| Name | Kind | What it does / contract |
|---|---|---|
| metric(key) / metricSign(key) | functions | Read `account.analytics[key]` / `[key + 'Sign']`. |
| range combo | ThemedComboBox | Labels -> keys all/week/month/30d/ytd; also filters TradesTable. |

## Data and state
None persisted. All state comes from `app` (qml_bridge.AppController) and is per-account on the AccountController.

## How to change it safely
- The tag combo only shows when at least one trade is tagged.
- Single column on purpose: long labels never truncate at 300 px.
- All QML reads colours/fonts from `app.theme` (qml_bridge.ThemeController) and sizes text as `N * app.theme.fontScale` px on the 12/13/15/20/40 scale. Imports `QtQuick.Controls.Basic` so custom backgrounds are honoured (the native Windows style ignores them and warns). Check changes with `python scripts/ui_snapshot.py --out <dir>`; it echoes QML warnings to stderr.

## Map
- 1-22 header + helpers
- 24-66 title + combos
- 68-112 grouped metrics
