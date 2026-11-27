# stock_insights/qml/SectionTitle.qml
**Purpose:** Panel heading: 15 px/600 title plus optional muted 13 px subtitle phrase.
**Used by:** every card.  **Depends on:** `app.theme`.

## Key types and functions
| Name | Kind | What it does / contract |
|---|---|---|
| title / subtitle | string props | Subtitle hidden when empty; elides. |
| accent | color prop | Kept for API compatibility; unused (Harbor has no accent bars). |

## Data and state
None persisted. All state comes from `app` (qml_bridge.AppController) and is per-account on the AccountController.

## How to change it safely
- Subtitles are plain phrases ('32 trades, all time'), never 'A · B' meta strings.
- All QML reads colours/fonts from `app.theme` (qml_bridge.ThemeController) and sizes text as `N * app.theme.fontScale` px on the 12/13/15/20/40 scale. Imports `QtQuick.Controls.Basic` so custom backgrounds are honoured (the native Windows style ignores them and warns). Check changes with `python scripts/ui_snapshot.py --out <dir>`; it echoes QML warnings to stderr.

## Map
- 1-12 props
- 14-33 labels
