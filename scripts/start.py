"""Start all Battlemap Explorer backend services.

Starts (in order):
  1. Docker infrastructure  (Qdrant, Prefect server/services, Postgres, Redis)
  2. Prefect worker         (background → logs/worker.log)
  3. FastAPI server         (background → logs/api.log)

The frontend dev server must be started separately in a second terminal:
  cd frontend && npm run dev

PIDs are written to .pids/ so stop.py can terminate the processes cleanly.

Usage:
  uv run python scripts/start.py
"""

import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).parent.parent
PIDS_DIR = ROOT / ".pids"
LOGS_DIR = ROOT / "logs"
PREFECT_API = "http://localhost:4200/api"
WORK_POOL = "battlemap-pool"

# Ensure the venv Python (same one running this script) is used for subprocesses.
PYTHON = sys.executable


def _run(cmd: list[str]) -> None:
    subprocess.run(cmd, cwd=ROOT, check=True)


def _spawn(name: str, cmd: list[str]) -> int:
    """Launch a background process, redirect output to logs/{name}.log, store PID."""
    LOGS_DIR.mkdir(exist_ok=True)
    PIDS_DIR.mkdir(exist_ok=True)

    log_path = LOGS_DIR / f"{name}.log"
    log_file = open(log_path, "w")

    extra = {}
    if sys.platform == "win32":
        # Prevent Ctrl-C in this terminal from propagating to the child
        extra["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP

    proc = subprocess.Popen(
        cmd,
        cwd=ROOT,
        stdout=log_file,
        stderr=subprocess.STDOUT,
        **extra,
    )
    (PIDS_DIR / f"{name}.pid").write_text(str(proc.pid))
    return proc.pid


def _wait_for_prefect(timeout: int = 90) -> None:
    deadline = time.time() + timeout
    print("  Waiting for Prefect server", end="", flush=True)
    while time.time() < deadline:
        try:
            urllib.request.urlopen(f"{PREFECT_API}/health", timeout=2)
            print(" ready.")
            return
        except Exception:
            print(".", end="", flush=True)
            time.sleep(3)
    print()
    print("\nERROR: Prefect server didn't become healthy.")
    print("  docker compose logs prefect-server")
    sys.exit(1)


def main() -> None:
    print("=" * 50)
    print("  Battlemap Explorer — Starting Services")
    print("=" * 50)
    print()

    # 1. Infrastructure
    print("[1/3] Starting Docker infrastructure...")
    _run(["docker", "compose", "up", "-d"])
    _wait_for_prefect()

    # 2. Prefect worker
    print("\n[2/3] Starting Prefect worker...")
    worker_pid = _spawn("worker", [PYTHON, "-m", "prefect", "worker", "start", "--pool", WORK_POOL])
    print(f"  PID {worker_pid}  →  logs/worker.log")
    # Allow the worker time to register with the server before the API starts
    time.sleep(2)

    # 3. FastAPI server
    print("\n[3/3] Starting FastAPI server...")
    api_pid = _spawn("api", [PYTHON, "-m", "uvicorn", "backend.app.main:app",
                              "--host", "0.0.0.0", "--port", "8000"])
    print(f"  PID {api_pid}  →  logs/api.log")

    print()
    print("=" * 50)
    print("  All backend services running")
    print("=" * 50)
    print()
    print("  API:      http://localhost:8000/docs")
    print("  Health:   http://localhost:8000/health")
    print("  Prefect:  http://localhost:4200")
    print()
    print("Start the frontend in a separate terminal:")
    print("  cd frontend && npm run dev  →  http://localhost:5173")
    print()
    print("Stop everything:   uv run python scripts/stop.py")
    print("Tail API logs:     tail -f logs/api.log")
    print("Tail worker logs:  tail -f logs/worker.log")


if __name__ == "__main__":
    main()
