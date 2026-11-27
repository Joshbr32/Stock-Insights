# stock_insights/qml/Pill.qml
**Purpose:** Fully round 32 px chip used for goal presets; selected = primary fill.
**Used by:** GoalDashboard.  **Depends on:** FocusRing, `app.theme`.

## Key types and functions
| Name | Kind | What it does / contract |
|---|---|---|
| label / selected | props |  |
| clicked() | signal | Mouse, Space or Enter. |

## Data and state
None persisted. All state comes from `app` (qml_bridge.AppController) and is per-account on the AccountController.

## How to change it safely
- Hover colour is a binding (old version overwrote `color` imperatively and broke selection).
- All QML reads colours/fonts from `app.theme` (qml_bridge.ThemeController) and sizes text as `N * app.theme.fontScale` px on the 12/13/15/20/40 scale. Imports `QtQuick.Controls.Basic` so custom backgrounds are honoured (the native Windows style ignores them and warns). Check changes with `python scripts/ui_snapshot.py --out <dir>`; it echoes QML warnings to stderr.

## Map
- 1-30 props, colours, keys, accessibility
- 32-50 label, mouse, focus ring
