"""
LandIQ — Langflow launcher (standalone).

Run with:
    python langflow_run.py

Starts Langflow (its own venv, langflow_env/) on port 7860 and opens it
in your browser as soon as it's ready. Runs in THIS terminal window —
no popup window, no PowerShell — press Ctrl+C here to stop it.
"""

import os
import socket
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
LANGFLOW_EXE = ROOT / "langflow_env" / "Scripts" / "langflow.exe"
PORT = 7860


def wait_and_open():
    deadline = time.time() + 240
    while time.time() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", PORT), timeout=1):
                webbrowser.open(f"http://localhost:{PORT}")
                return
        except OSError:
            time.sleep(2)
    print(f"Langflow still starting after 240s — open http://localhost:{PORT} manually when ready.")


def main():
    if not LANGFLOW_EXE.exists():
        print(f"ERROR: {LANGFLOW_EXE} not found. Langflow's venv (langflow_env) isn't set up.")
        sys.exit(1)

    env = os.environ.copy()
    env.update({
        "LANGFLOW_AUTO_LOGIN": "true",
        "LANGFLOW_SKIP_AUTH_AUTO_LOGIN": "true",
        "LANGFLOW_WORKER_TIMEOUT": "700",
        "LANGFLOW_SSRF_PROTECTION_ENABLED": "false",
        "LANGFLOW_CONNECTOR_SSRF_VALIDATION_ENABLED": "false",
        "LANGFLOW_CONNECTOR_SSRF_ALLOW_LOOPBACK": "true",
        "LANGFLOW_SSRF_ALLOWED_HOSTS": "127.0.0.1,localhost,0.0.0.0,::1",
    })

    print(f"Starting Langflow on http://localhost:{PORT} ...")
    threading.Thread(target=wait_and_open, daemon=True).start()

    subprocess.run(
        [str(LANGFLOW_EXE), "run", "--host", "127.0.0.1", "--port", str(PORT)],
        cwd=str(ROOT),
        env=env,
    )


if __name__ == "__main__":
    main()
