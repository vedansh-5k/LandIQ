"""
run.py — LandIQ v3
Auto-kills port 8000 on Windows if already in use, then starts the server.
"""
import os
import sys
import subprocess
import time
import webbrowser

PORT = int(os.environ.get("PORT", 8000))
HOST = "0.0.0.0"


def kill_port(port: int):
    """Kill any process using the given port (Windows + Unix)."""
    killed = False
    if sys.platform == "win32":
        try:
            result = subprocess.run(
                f'netstat -aon | findstr ":{port} "',
                shell=True, capture_output=True, text=True
            )
            for line in result.stdout.splitlines():
                parts = line.split()
                if parts:
                    pid = parts[-1]
                    try:
                        pid_int = int(pid)
                        if pid_int > 0:
                            subprocess.run(f"taskkill /PID {pid_int} /F",
                                           shell=True, capture_output=True)
                            print(f"  Killed PID {pid_int} on port {port}")
                            killed = True
                    except ValueError:
                        pass
        except Exception as e:
            print(f"  Warning: could not kill port {port}: {e}")
    else:
        try:
            result = subprocess.run(
                f"lsof -ti:{port}", shell=True, capture_output=True, text=True
            )
            for pid in result.stdout.strip().split("\n"):
                if pid:
                    subprocess.run(f"kill -9 {pid}", shell=True, capture_output=True)
                    print(f"  Killed PID {pid} on port {port}")
                    killed = True
        except Exception as e:
            print(f"  Warning: could not kill port {port}: {e}")
    if killed:
        time.sleep(1)  # Wait for port to free up


def open_browser():
    time.sleep(2)
    webbrowser.open(f"http://localhost:{PORT}")


print("=" * 50)
print("  LAND INVESTMENT ADVISOR v3")
print("  Starting server...")
print("=" * 50)

# Kill anything on port 8000 first
print(f"\n[*] Freeing port {PORT}...")
kill_port(PORT)

print(f"[*] Starting on http://localhost:{PORT}\n")

# Open browser in background
import threading
threading.Thread(target=open_browser, daemon=True).start()

# Start uvicorn
try:
    import uvicorn
    uvicorn.run(
        "api:app",
        host=HOST,
        port=PORT,
        reload=False,        # reload=True causes double-bind on Windows
        log_level="info",
    )
except KeyboardInterrupt:
    print("\n[*] Server stopped.")