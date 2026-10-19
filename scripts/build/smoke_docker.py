"""Start the built Docker image and check it serves the API and the UI.

Runs it the way docker-compose.yml does, but as an arbitrary user on a fresh data volume,
so it also checks that the published image works for any APP_UID:APP_GID: the database
must open in the volume, and the API must report the release version. Runs in the Release
workflow before the image is pushed.

Usage:
    python scripts/build/smoke_docker.py --image IMAGE --version 0.2.0 [--timeout SECONDS]
"""

import argparse
import json
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

# Not the image's default user (1000), as an APP_UID other than the default would be.
RUN_AS = "4321:4321"


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _get(port: int, path: str, accept: str) -> tuple[int, str]:
    request = urllib.request.Request(f"http://127.0.0.1:{port}{path}", headers={"Accept": accept})
    with urllib.request.urlopen(request, timeout=10) as resp:  # noqa: S310  # nosec B310 - fixed http URL
        return resp.status, resp.read().decode("utf-8", errors="replace")


def _docker(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # nosec B603 B607 - docker with arguments built here
        ["docker", *args], check=check, capture_output=True, text=True
    )


def _wait_for_health(port: int, timeout: float) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            status, body = _get(port, "/health", "application/json")
            if status == 200:
                return json.loads(body)
        except (urllib.error.URLError, ConnectionError, TimeoutError, json.JSONDecodeError):
            pass
        time.sleep(2)
    raise TimeoutError(f"/health didn't answer within {timeout:.0f}s")


def smoke(image: str, version: str, timeout: float) -> list[str]:
    """Problems found, or an empty list."""
    problems = []
    name = f"scene-atlas-smoke-{uuid.uuid4().hex[:8]}"
    volume = f"{name}-data"
    port = _free_port()
    with tempfile.TemporaryDirectory() as images:
        # The bind mount stands in for IMAGE_DIR, which the user must own on the host.
        Path(images).chmod(0o777)
        try:
            _docker(
                "run", "--detach", "--name", name, "--user", RUN_AS,
                "--publish", f"127.0.0.1:{port}:8000",
                "--volume", f"{volume}:/app/data",
                "--volume", f"{images}:/app/images",
                "--env", "APP_DATA_DIR=/app/data",
                "--env", "IMAGE_LIBRARY_DIR=/app/images",
                "--env", "APP_MODE=server",
                image,
            )  # fmt: skip
            health = _wait_for_health(port, timeout)
            database = health.get("checks", {}).get("database")
            if database != "ok":
                problems.append(f"database check is {database!r}, not 'ok': {health}")

            _, body = _get(port, "/", "application/json")
            reported = json.loads(body).get("version")
            if reported != version:
                problems.append(f"the API reports version {reported!r}, not {version!r}")

            status, page = _get(port, "/", "text/html")
            if status != 200 or '<div id="root">' not in page:
                problems.append("/ doesn't serve the UI")
        except (TimeoutError, subprocess.CalledProcessError, urllib.error.URLError) as err:
            problems.append(f"{type(err).__name__}: {err}")
        finally:
            if problems:
                logs = _docker("logs", "--tail", "100", name, check=False)
                print(logs.stdout + logs.stderr, file=sys.stderr)
            _docker("rm", "--force", name, check=False)
            _docker("volume", "rm", "--force", volume, check=False)
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--image", required=True)
    parser.add_argument("--version", required=True, help="the version the API should report")
    parser.add_argument("--timeout", type=float, default=120)
    args = parser.parse_args()

    problems = smoke(args.image, args.version, args.timeout)
    for problem in problems:
        print(f"error: {problem}", file=sys.stderr)
    if not problems:
        print(f"{args.image} serves the API and UI as {RUN_AS} (version {args.version})")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
