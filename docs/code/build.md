# build.bat
**Purpose:** Windows build script producing `dist\StockInsights.exe` with PyInstaller and `stock_insights.spec`.
**Used by:** developer.  **Depends on:** `.venv`/`venv` Python, PySide6, pip, `stock_insights.spec`.

## Key types and functions
Steps: find venv python, verify PySide6, `pip install --upgrade pyinstaller pyinstaller-hooks-contrib`, delete `build\` and `dist\`, run `PyInstaller stock_insights.spec --noconfirm`, open `dist`.

## Data and state
Deletes and recreates `build/` and `dist/`. Do not run it during audits.

## How to change it safely
It pauses on errors and at the end, so it is not CI-friendly. The exe is windowed (`console=False`), so `sys.stdout` is None at runtime (see `logging_utils`).

## Map
venv lookup 15-30; PySide6 check 36-47; PyInstaller 49-72; finish 74-end.
