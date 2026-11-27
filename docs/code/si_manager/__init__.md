# si_manager/__init__.py, __main__.py, StockInsightsServerManager.bat
**Purpose:** Package marker with `APP_NAME` ("Stock Insights Server Manager") and `MANAGER_VERSION`; the entry point `python -m si_manager`; a double-click launcher.
**Used by:** the owner on the server PC.  **Depends on:** `si_controller.client.Client`, `theme`, `window`.

## Contract
- `__main__.main()`: QApplication, `theme.apply`, `MainWindow(Client())`, exec. The client finds the controller through `%ProgramData%\StockInsights\controller` (or `SI_CONTROLLER_HOME`).
- `StockInsightsServerManager.bat`: from the repository root, starts `.venv\Scripts\pythonw.exe -m si_manager` (PySide6 lives there), else `pythonw` on PATH; no console window. A desktop shortcut can point at it.
- The manager needs PySide6; the controller does not (it runs on the server's Python).

## How to change it safely
The manager must only talk to the controller's API: no server imports, no database, no files written. Closing it changes nothing on the server.
