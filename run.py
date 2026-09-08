"""
LandIQ — one-command startup.

Run with:
    python run.py

Starts each service ONE AT A TIME, waiting for it to actually respond
before starting the next. Starting them all at once was tried and caused
them to jam up fighting over the same on-disk lock files (Langflow's own
database, the embedding model cache) - so this launcher deliberately goes
slower and in order instead.

Each service opens in its own terminal window and keeps running there even
after this launcher script finishes - closing this window does not stop
them. Close each service's own window (or press Ctrl+C inside it) to stop it.
"""

import os
import socket
import subprocess
import time
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def launch(title, exe, args, extra_env=None):
    env = os.environ.copy()
    if extra_env:
        env.update(extra_env)
    # `start`'s title argument MUST be quoted, or `start` mistakes it for the
    # program to run instead (that's what "The system cannot find the file
    # LandIQ-Backend-8000" meant - it tried to launch a program literally
    # named that). Passing title as a separate list element to Popen let
    # Windows' own argument-quoting drop the quotes silently since the title
    # has no spaces needing escaping. Building one explicit string instead
    # guarantees the quotes survive exactly as written.
    # shell=True on Windows always resolves to cmd.exe (COMSPEC), so this
    # window is still Command Prompt, never PowerShell.
    # `start` hands the new window off to Windows as its own independent
    # process, so it keeps running even after this launcher script exits.
    arg_str = " ".join(f'"{a}"' for a in args)
    cmd = f'start "{title}" "{exe}" {arg_str}'
    subprocess.Popen(cmd, shell=True, cwd=str(ROOT), env=env)


def wait_for_port(port, timeout):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=1):
                return True
        except OSError:
            print(".", end="", flush=True)
            time.sleep(2)
    return False


def start_service(title, exe, args, port, timeout, extra_env=None):
    print(f"Starting {title} ", end="", flush=True)
    launch(title, exe, args, extra_env)
    if wait_for_port(port, timeout):
        print(f" ready on port {port}")
        return True
    print(f" still loading after {timeout}s - this can happen on a cold start,")
    print(f"  it will likely finish in its own window shortly. Moving on for now.")
    return False


def main():
    print("=" * 55)
    print(" LandIQ - starting all services (one at a time)")
    print("=" * 55)
    print()

    start_service(
        "LandIQ-Backend-8000",
        str(ROOT / "venv" / "Scripts" / "python.exe"),
        ["-m", "uvicorn", "api:app", "--port", "8000"],
        port=8000,
        timeout=90,
    )

    start_service(
        "LandIQ-Guardrail-8002",
        str(ROOT / "venv" / "Scripts" / "python.exe"),
        ["guardrail_server.py"],
        port=8002,
        timeout=120,
    )

    start_service(
        "LandIQ-Langflow-7860",
        str(ROOT / "langflow_env" / "Scripts" / "langflow.exe"),
        ["run", "--host", "127.0.0.1", "--port", "7860"],
        port=7860,
        timeout=240,
        extra_env={
            "LANGFLOW_SSRF_PROTECTION_ENABLED": "false",
            "LANGFLOW_CONNECTOR_SSRF_VALIDATION_ENABLED": "false",
            "LANGFLOW_CONNECTOR_SSRF_ALLOW_LOOPBACK": "true",
            "LANGFLOW_SSRF_ALLOWED_HOSTS": "127.0.0.1,localhost,0.0.0.0,::1",
        },
    )

    pixelrag_exe = ROOT / "venv_pixelrag" / "Scripts" / "pixelrag.exe"
    if pixelrag_exe.exists():
        start_service(
            "LandIQ-PixelRAG-30001",
            str(pixelrag_exe),
            [
                "serve",
                "--index-dir", "./pixelrag_index",
                "--tiles-dir", "./pixelrag_index/tiles",
                "--articles-json", "./pixelrag_index/articles.json",
                "--device", "cpu",
                "--port", "30001",
            ],
            port=30001,
            timeout=120,
        )

    print()
    print("Done. Opening browser tabs...")
    print("  http://localhost:8000                 - main LandIQ app")
    print("  http://localhost:8000/docs             - backend API docs")
    print("  http://localhost:8002/health           - guardrail / PII model health")
    print("  http://localhost:7860                  - Langflow visual builder")
    print("  http://localhost:8000/langflow/status  - confirms Langflow is wired in")
    print()
    print("To stop everything: close each service's window, or press Ctrl+C inside it.")

    for url in (
        "http://localhost:8000",
        "http://localhost:8002/health",
        "http://localhost:7860",
    ):
        try:
            webbrowser.open(url)
        except Exception:
            pass

    if pixelrag_exe.exists():
        try:
            webbrowser.open("http://localhost:8000/static/pixelrag.html")
        except Exception:
            pass


if __name__ == "__main__":
    main()
