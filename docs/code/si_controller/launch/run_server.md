# si_controller/launch/run_server.py
**Purpose:** Runs `server.py` as `__main__` (exactly like `python server.py`) and turns the word `stop` on stdin, or stdin closing, into SIGINT in the main thread, so uvicorn shuts down cleanly (finishes requests in flight, runs shutdown hooks).
**Used by:** `supervisor.ServerProcess` through `Config.server_argv(LAUNCHER)`.  **Depends on:** stdlib only (`runpy`, `_thread.interrupt_main`).

## Contract
`python run_server.py <path\to\server.py> [server args]`. Puts the server's folder first on `sys.path`. Exit code: the server's own; 0 after a requested stop (uvicorn re-raises the captured SIGINT as KeyboardInterrupt after its shutdown); 130 for an interrupt nobody asked for. Checked with uvicorn 0.54: `stop` gives "Shutting down … Finished server process" and exit 0 in about 0.2 s.

## How to change it safely
Keep this folder otherwise empty (it is the running script's folder). Import nothing from `si_controller` here: this code runs inside the server's process.
