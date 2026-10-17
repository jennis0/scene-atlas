"""Start the Scene Atlas backend server with crash supervision.

Launches the FastAPI server as a supervised child process. If the server
crashes, it is automatically restarted with exponential backoff. Gives up
after 10 crashes within 5 minutes to avoid infinite crash loops.

The frontend dev server must be started separately in a second terminal:
  cd frontend && npm run dev

PIDs are written to .pids/ so stop.py can terminate the process cleanly.

Usage:
  uv run python scripts/app/start.py
"""

import signal
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PIDS_DIR = ROOT / ".pids"
LOGS_DIR = ROOT / "logs"
PYTHON = sys.executable

MAX_RESTARTS = 10
WINDOW_SECS = 300
MAX_BACKOFF = 30


def _supervise(name: str, cmd: list[str]) -> None:
    """Launch and supervise a child process with auto-restart on crash."""
    LOGS_DIR.mkdir(exist_ok=True)
    PIDS_DIR.mkdir(exist_ok=True)

    restarts: list[float] = []
    backoff = 1
    child_proc = None

    def _forward_signal(sig, _frame):
        if child_proc and child_proc.poll() is None:
            child_proc.send_signal(sig)

    signal.signal(signal.SIGTERM, _forward_signal)
    signal.signal(signal.SIGINT, _forward_signal)

    while True:
        log_path = LOGS_DIR / f"{name}.log"

        extra = {}
        if sys.platform == "win32":
            extra["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP

        with open(log_path, "a") as log_file:
            child_proc = subprocess.Popen(
                cmd,
                cwd=ROOT,
                stdout=log_file,
                stderr=subprocess.STDOUT,
                **extra,
            )
            pid_file = PIDS_DIR / f"{name}.pid"
            pid_file.write_text(str(child_proc.pid))
            print(f"  [{name}] PID {child_proc.pid}")

            exit_code = child_proc.wait()
        # log_file is flushed and closed here in all exit paths

        if exit_code == 0:
            print(f"  [{name}] exited cleanly")
            break

        # Check crash window
        now = time.time()
        restarts = [t for t in restarts if now - t < WINDOW_SECS]

        if len(restarts) >= MAX_RESTARTS:
            print(f"  [{name}] crashed {MAX_RESTARTS} times in {WINDOW_SECS}s — giving up")
            sys.exit(1)

        restarts.append(now)
        print(f"  [{name}] exited with code {exit_code}, restarting in {backoff}s...")
        time.sleep(backoff)
        backoff = min(backoff * 2, MAX_BACKOFF)


def main() -> None:
    print("=" * 50)
    print("  Scene Atlas — Starting (supervised)")
    print("=" * 50)
    print()

    print("Starting FastAPI server...")
    _supervise(
        "api",
        [
            PYTHON,
            "-m",
            "uvicorn",
            "backend.app.main:app",
            "--host",
            "0.0.0.0",  # noqa: S104 — LAN access in dev; Electron/Docker set their own host
            "--port",
            "8000",
            "--no-proxy-headers",  # the app handles them (FORWARDED_ALLOW_IPS)
        ],
    )


if __name__ == "__main__":
    main()
