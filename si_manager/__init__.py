"""si_manager: the desktop "Stock Insights Server Manager" for the server PC.

A PySide6 window that only talks to the controller's loopback API
(``si_controller``) to show the sync server's state, its output and the
controller's events, and to start, restart or stop it. It opens no database and
contains no server code. Closing it changes nothing about the running server.
"""

APP_NAME = "Stock Insights Server Manager"
MANAGER_VERSION = "1.0.0"
