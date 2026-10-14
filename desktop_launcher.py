"""Windows/macOS desktop launcher for the bundled Handwritify server."""
from __future__ import annotations

import faulthandler
import os
import sys
import threading
import webbrowser
from pathlib import Path


def _resource_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS)
    return Path(__file__).resolve().parent


def _port() -> int:
    """Return an available local port without binding it permanently."""
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def main() -> None:
    root = _resource_dir()
    faulthandler.dump_traceback_later(5, repeat=False)
    print(f"launcher: root={root}", flush=True)
    sys.path.insert(0, str(root))

    port = _port()
    print(f"launcher: selected port={port}", flush=True)

    print("launcher: importing backend", flush=True)
    import uvicorn
    from backend import main as app_module
    print("launcher: backend imported", flush=True)

    app_module.BASE_DIR = str(root)
    app_module.JOBS_DIR = os.path.join(root, "jobs")
    app_module.FRONTEND_DIR = os.path.join(root, "frontend")
    os.makedirs(app_module.JOBS_DIR, exist_ok=True)

    browser = threading.Thread(
        target=webbrowser.open,
        args=(f"http://127.0.0.1:{port}",),
        daemon=True,
    )
    browser.start()

    print("launcher: starting uvicorn", flush=True)
    uvicorn.run(
        app_module.app,
        host="127.0.0.1",
        port=port,
        log_level="info",
        access_log=False,
    )


if __name__ == "__main__":
    main()
