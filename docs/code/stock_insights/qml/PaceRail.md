# stock_insights/qml/PaceRail.qml
**Purpose:** The signature element: track $0 → goal, primary fill + dot at realized P/L, amber `pace` tick at today's pace, labels underneath that drop out instead of colliding.
**Used by:** GoalDashboard.  **Depends on:** `AccountController.pace` map (see qml_bridge.md), `app.theme.pace`, `app.theme.reduceMotion`.

## Key types and functions
| Name | Kind | What it does / contract |
|---|---|---|
| pace | var | Pace map: fraction, paceFraction, realizedText, expectedText, targetText, state, sentence. |
| play() | function | One-shot 0 → fraction fill, 400 ms OutCubic; instant with reduced motion; rebinds `shown` to `fraction` afterwards. |
| labels | Labels | $0, realized (under dot), "Today's pace $x" (under tick), target; dot/target labels hide when they would overlap. |

## Data and state
None persisted. All state comes from `app` (qml_bridge.AppController) and is per-account on the AccountController.

## How to change it safely
- Amber (`pace`) is used only for the tick here and the curve line in EquityCurveCard.
- Label visibility bindings are one-directional (dot -> zero/target); keep it that way to avoid binding loops.
- Accessible name reads the whole state as a sentence.
- All QML reads colours/fonts from `app.theme` (qml_bridge.ThemeController) and sizes text as `N * app.theme.fontScale` px on the 12/13/15/20/40 scale. Imports `QtQuick.Controls.Basic` so custom backgrounds are honoured (the native Windows style ignores them and warns). Check changes with `python scripts/ui_snapshot.py --out <dir>`; it echoes QML warnings to stderr.

## Map
- 1-30 header + props
- 31-50 play() + intro animation
- 52-104 track, fill, tick, dot
- 106-147 labels
