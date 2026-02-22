"""Stop all Battlemap Explorer services.

Terminates:
  - FastAPI server         (PID from .pids/api.pid)
  - Prefect worker         (PID from .pids/worker.pid)
  - Docker infrastructure  (unless --keep-docker is passed)

Usage:
  uv run python scripts/stop.py                # stop everything
  uv run python scripts/stop.py --keep-docker  # leave Docker running
"""

import os
import signal
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
PIDS_DIR = ROOT / ".pids"


def _kill_by_pid_file(name: str) -> None:
    pid_file = PIDS_DIR / f"{name}.pid"
    if not pid_file.exists():
        print(f"  {name}: no PID file — already stopped or never started")
        return

    pid = int(pid_file.read_text().strip())
    try:
        if sys.platform == "win32":
            # /T kills the process tree (including any children uv may have spawned)
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(pid)],
                capture_output=True,
            )
        else:
            os.kill(pid, signal.SIGTERM)
        print(f"  {name}: terminated (PID {pid})")
    except (ProcessLookupError, OSError):
        print(f"  {name}: PID {pid} not found — already stopped")
    finally:
        pid_file.unlink(missing_ok=True)


def main() -> None:
    keep_docker = "--keep-docker" in sys.argv

    print("=" * 50)
    print("  Battlemap Explorer — Stopping Services")
    print("=" * 50)
    print()

    print("Stopping background services...")
    _kill_by_pid_file("api")
    _kill_by_pid_file("worker")

    if keep_docker:
        print("\nDocker infrastructure left running (--keep-docker).")
    else:
        print("\nStopping Docker infrastructure...")
        subprocess.run(["docker", "compose", "stop"], cwd=ROOT, check=True)

    print()
    print("Done. Run 'uv run python scripts/start.py' to start again.")


if __name__ == "__main__":
    main()
