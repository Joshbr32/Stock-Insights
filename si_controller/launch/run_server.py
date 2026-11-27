"""Run the sync server so the controller can stop it gracefully.

Usage (by the controller only):  python run_server.py <path\\to\\server.py> [server args...]

Runs ``server.py`` exactly as ``python server.py`` would (``__main__``, its own
folder first on the import path), plus one thread that waits for the word
``stop`` on standard input and then raises SIGINT in the main thread. uvicorn
treats that like Ctrl+C: it stops accepting connections, finishes requests in
flight and runs shutdown hooks. If standard input closes (the controller went
away) the server is stopped the same way.

Nothing else may sit in this folder: as the script being run, its folder would
otherwise be first on the server's import path. (It is replaced below, but
keeping the folder empty makes that obviously safe.)
"""
import _thread
import os
import runpy
import signal
import sys
import threading

_stop_requested = threading.Event()


def _watch_stdin() -> None:
    try:
        for line in sys.stdin:
            if line.strip() == "stop":
                break
    except (OSError, ValueError):
        pass
    _stop_requested.set()
    _thread.interrupt_main(signal.SIGINT)


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: run_server.py <server.py> [args...]", file=sys.stderr)
        return 2
    script = os.path.abspath(sys.argv[1])
    sys.argv = [script] + sys.argv[2:]
    sys.path[0] = os.path.dirname(script)
    threading.Thread(target=_watch_stdin, name="stop-watch", daemon=True).start()
    try:
        runpy.run_path(script, run_name="__main__")
    except KeyboardInterrupt:
        # uvicorn re-raises the captured SIGINT after its clean shutdown.
        return 0 if _stop_requested.is_set() else 130
    except SystemExit as exc:
        code = exc.code
        if code is None:
            return 0
        if isinstance(code, int):
            return code
        print(code, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
