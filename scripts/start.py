"""Start the Scene Atlas backend server.

Launches the FastAPI server as a background process (logs → logs/api.log).
All services (Qdrant, JobRunner, Scheduler) run in-process.

The frontend dev server must be started separately in a second terminal:
  cd frontend && npm run dev

PIDs are written to .pids/ so stop.py can terminate the process cleanly.

Usage:
  uv run python scripts/start.py
"""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
PIDS_DIR = ROOT / ".pids"
LOGS_DIR = ROOT / "logs"

# Ensure the venv Python (same one running this script) is used for subprocesses.
PYTHON = sys.executable


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


def main() -> None:
    print("=" * 50)
    print("  Scene Atlas — Starting")
    print("=" * 50)
    print()

    print("Starting FastAPI server...")
    api_pid = _spawn(
        "api",
        [PYTHON, "-m", "uvicorn", "backend.app.main:app", "--host", "0.0.0.0", "--port", "8000"],
    )
    print(f"  PID {api_pid}  →  logs/api.log")

    print()
    print("=" * 50)
    print("  Server running")
    print("=" * 50)
    print()
    print("  API:      http://localhost:8000/docs")
    print("  Health:   http://localhost:8000/health")
    print()
    print("Start the frontend in a separate terminal:")
    print("  cd frontend && npm run dev  →  http://localhost:5173")
    print()
    print("Stop:          uv run python scripts/stop.py")
    print("Tail logs:     tail -f logs/api.log")


if __name__ == "__main__":
    main()
