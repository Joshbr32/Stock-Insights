# stock_insights/qml/Main.qml
**Purpose:** Root of the scene loaded by MainWindow's QQuickWidget: a `Control` with the `bg` background and a two-pane SplitView (WatchlistPane | PortfolioPane).
**Used by:** main_window.py `_build_qml_host` (`setSource(Main.qml)`), scripts/ui_snapshot.py.  **Depends on:** WatchlistPane, PortfolioPane, `app.theme`.

## Key types and functions
| Name | Kind | What it does / contract |
|---|---|---|
| root Control | item | Sets `font.family` (resolved UI font), base 13 px size and `font.features: {tnum: 1}` once; every Label/Control inherits them. |
| SplitView handle | item | 12 px gutter; hairline only on hover/drag. |

## Data and state
None persisted. All state comes from `app` (qml_bridge.AppController) and is per-account on the AccountController.

## How to change it safely
- Keep the root a Control (font propagation). Plain Items don't propagate fonts to Labels.
- Pane min widths: watchlist 190, portfolio 480.
- All QML reads colours/fonts from `app.theme` (qml_bridge.ThemeController) and sizes text as `N * app.theme.fontScale` px on the 12/13/15/20/40 scale. Imports `QtQuick.Controls.Basic` so custom backgrounds are honoured (the native Windows style ignores them and warns). Check changes with `python scripts/ui_snapshot.py --out <dir>`; it echoes QML warnings to stderr.

## Map
- 1-11 imports + header comment
- 12-20 root Control + font
- 22-51 SplitView, handle, panes
