# stock_insights/qml/qmldir
**Purpose:** Declares the `StockInsights` QML module so the files can refer to each other by type name (`import "."`).
**Used by:** every QML file in this folder.  **Depends on:** nothing.

## How to change it safely
- Add a line `<Type> 1.0 <Type>.qml` for every new component (FocusRing and PaceRail were added for Harbor).
- Never rename an entry without updating every user.
