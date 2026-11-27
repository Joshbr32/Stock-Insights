"""si_controller: keeps the Stock Insights sync server running on the server PC.

A small supervisor (standard library only, runs on the server's own Python) that
starts ``server/server.py`` as a child process, checks ``GET /health``, restarts it
with back-off when it exits or stops answering, captures its output (secrets
redacted) and offers a loopback-only management API with a token for
``python -m si_controller`` and the desktop manager (``si_manager``).

Modelled on the Colonial controller that runs on the same PC, but deliberately
separate from it: different ports (server 8742, API 8746), folder
(``%ProgramData%\\StockInsights\\controller``) and scheduled task name.
"""

CONTROLLER_VERSION = "1.0.0"
