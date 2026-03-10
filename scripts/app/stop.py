"""Stop the Scene Atlas backend server.

Terminates the FastAPI server process (PID from .pids/api.pid).

Usage:
  uv run python scripts/stop.py
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
    print("=" * 50)
    print("  Scene Atlas — Stopping")
    print("=" * 50)
    print()

    _kill_by_pid_file("api")

    print()
    print("Done. Run 'uv run python scripts/start.py' to start again.")


if __name__ == "__main__":
    main()
