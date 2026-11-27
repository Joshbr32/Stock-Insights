# stock_insights/qml/GoalDashboard.qml
**Purpose:** Answers 'am I on pace?': goal line + preset pills, 40 px realized hero, pace sentence, PaceRail, and six stacked supporting metrics.
**Used by:** PortfolioView.  **Depends on:** PaceRail, Pill, Metric; `account.goal`, `account.pace`, `account.presets`, `account.goalTargetValue`, `app.setGoalTarget`.

## Key types and functions
| Name | Kind | What it does / contract |
|---|---|---|
| _maybePlay() | function | Plays the rail animation once per account name, when that account is first loaded and shown. |
| metrics grid | GridLayout | 6 columns above 820 px card width, else 3: Unrealized, Year-end forecast, Left to goal, Needed per day/week, Trading days left. |

## Data and state
None persisted. All state comes from `app` (qml_bridge.AppController) and is per-account on the AccountController.

## How to change it safely
- The 40 px hero is the only use of that size. The sentence is coloured good/bad but always states ahead/behind in words.
- Old metrics (monthly, avg daily, catch-up, days elapsed) are still in `account.goal` if they need to come back.
- All QML reads colours/fonts from `app.theme` (qml_bridge.ThemeController) and sizes text as `N * app.theme.fontScale` px on the 12/13/15/20/40 scale. Imports `QtQuick.Controls.Basic` so custom backgrounds are honoured (the native Windows style ignores them and warns). Check changes with `python scripts/ui_snapshot.py --out <dir>`; it echoes QML warnings to stderr.

## Map
- 1-35 header, props, animation trigger
- 37-64 goal line + presets
- 66-104 hero + sentence
- 106-112 rail
- 114-163 metrics
