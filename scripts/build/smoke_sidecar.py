"""Start the built sidecar and check it serves the API and the UI.

Catches bundles that build but can't run (a missing hidden import or data file, or a
shared library the build step damaged). Runs on every platform in the Release workflow.

Usage:
    uv run python scripts/build/smoke_sidecar.py [--exe PATH] [--timeout SECONDS]
"""

import argparse
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from pathlib import Path

from build_sidecar import SIDECAR_EXE

READY_MARKER = "SCENE_ATLAS_READY"


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _get(port: int, path: str) -> tuple[int, str]:
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}", headers={"Accept": "text/html"}
    )
    with urllib.request.urlopen(request, timeout=10) as resp:  # noqa: S310 - fixed http URL
        return resp.status, resp.read().decode("utf-8", errors="replace")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--exe", type=Path, default=SIDECAR_EXE)
    parser.add_argument("--timeout", type=float, default=180.0)
    args = parser.parse_args()

    if not args.exe.exists():
        print(f"Sidecar not found: {args.exe}", file=sys.stderr)
        return 1

    port = _free_port()
    with tempfile.TemporaryDirectory(prefix="sidecar-smoke-") as tmp:
        data, library = Path(tmp, "data"), Path(tmp, "library")
        data.mkdir()
        library.mkdir()
        cmd = [str(args.exe), "--port", str(port), "--app-data-dir", str(data)]
        cmd += ["--image-library-dir", str(library)]
        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        output: list[str] = []
        ready = threading.Event()

        def pump() -> None:
            for line in proc.stdout or ():
                output.append(line)
                if READY_MARKER in line:
                    ready.set()

        threading.Thread(target=pump, daemon=True).start()

        try:
            deadline = time.monotonic() + args.timeout
            while not ready.wait(0.5):
                if proc.poll() is not None or time.monotonic() > deadline:
                    reason = "exited" if proc.poll() is not None else "timed out"
                    print(f"Sidecar {reason} before {READY_MARKER}:", file=sys.stderr)
                    print("".join(output[-60:]), file=sys.stderr)
                    return 1

            status, _ = _get(port, "/health")
            if status != 200:
                print(f"/health returned {status}", file=sys.stderr)
                return 1
            status, body = _get(port, "/")
            if status != 200 or '<div id="root"' not in body:
                print(f"/ did not serve the UI (status {status})", file=sys.stderr)
                return 1
            print(f"Sidecar OK: ready, /health 200, UI served on port {port}")
            return 0
        finally:
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=30)
                except subprocess.TimeoutExpired:
                    proc.kill()


if __name__ == "__main__":
    sys.exit(main())
