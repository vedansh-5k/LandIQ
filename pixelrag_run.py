"""
LandIQ — PixelRAG launcher (standalone).

Run with:
    python pixelrag_run.py

Starts the PixelRAG visual-search API (its own venv, venv_pixelrag/) on
port 30001 and opens its health check in your browser as soon as it's
ready. Runs in THIS terminal window — no popup window, no PowerShell —
press Ctrl+C here to stop it.

PixelRAG itself has no page of its own — it's a JSON API the main app
calls into. Once api.py is also running, the actual visual-search UI is
at http://localhost:8000/static/pixelrag.html.
"""

import socket
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PIXELRAG_EXE = ROOT / "venv_pixelrag" / "Scripts" / "pixelrag.exe"
INDEX_DIR = ROOT / "pixelrag_index"
PORT = 30001


def wait_and_open():
    deadline = time.time() + 120
    while time.time() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", PORT), timeout=1):
                webbrowser.open(f"http://localhost:{PORT}/health")
                return
        except OSError:
            time.sleep(2)
    print(f"PixelRAG still starting after 120s — open http://localhost:{PORT}/health manually when ready.")


def main():
    if not PIXELRAG_EXE.exists():
        print(f"ERROR: {PIXELRAG_EXE} not found. PixelRAG's venv (venv_pixelrag) isn't set up.")
        sys.exit(1)

    if not INDEX_DIR.exists():
        print(f"WARNING: {INDEX_DIR} not found yet — PixelRAG will start with an empty index.")

    print(f"Starting PixelRAG on http://localhost:{PORT} ...")
    threading.Thread(target=wait_and_open, daemon=True).start()

    subprocess.run(
        [
            str(PIXELRAG_EXE), "serve",
            "--index-dir", str(INDEX_DIR),
            "--tiles-dir", str(INDEX_DIR / "tiles"),
            "--articles-json", str(INDEX_DIR / "articles.json"),
            "--device", "cpu",
            "--port", str(PORT),
        ],
        cwd=str(ROOT),
    )


if __name__ == "__main__":
    main()
