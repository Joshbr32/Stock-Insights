# si_controller/__init__.py
**Purpose:** Package marker and `CONTROLLER_VERSION` (shown in `/status`, the CLI and the manager). The package docstring says what the controller is and why it is kept apart from the Colonial controller on the same PC.
**Used by:** `controller.py`, `cli.py`.  **Depends on:** nothing.

## How to change it safely
Bump `CONTROLLER_VERSION` when the controller's behaviour or API changes. The whole package is standard library only: it runs on the server's own Python. Overview of the package and its operation: `docs/ops/server-pc.md`.
