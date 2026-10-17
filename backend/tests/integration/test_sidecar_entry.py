"""The packaged-sidecar entry point, run as Electron runs it (from source)."""

import os
import queue
import socket
import subprocess
import sys
import threading
from pathlib import Path

import pytest

from backend.tests.unit.test_storage_lock import child_can_lock

REPO_ROOT = Path(__file__).resolve().parents[3]
ENTRY = REPO_ROOT / "backend" / "pyinstaller" / "entry.py"
STARTUP_TIMEOUT = 90
SHUTDOWN_TIMEOUT = 60


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Sidecar:
    def __init__(self, tmp_path: Path, *extra_args: str):
        self.port = _free_port()
        self.data_dir = tmp_path / "data"
        library = tmp_path / "images"
        self.data_dir.mkdir()
        library.mkdir()
        self.lines: queue.Queue[str] = queue.Queue()
        self.proc = subprocess.Popen(
            [
                sys.executable,
                str(ENTRY),
                "--port",
                str(self.port),
                "--app-data-dir",
                str(self.data_dir),
                "--image-library-dir",
                str(library),
                *extra_args,
            ],
            cwd=REPO_ROOT,
            env={**os.environ, "PYTHONPATH": str(REPO_ROOT)},
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        threading.Thread(target=self._pump, daemon=True).start()

    def _pump(self) -> None:
        assert self.proc.stdout is not None
        for line in self.proc.stdout:
            self.lines.put(line)

    def wait_ready(self) -> list[str]:
        """Return the output up to and including the ready line."""
        seen = []
        while True:
            try:
                line = self.lines.get(timeout=STARTUP_TIMEOUT)
            except queue.Empty:
                pytest.fail("No SCENE_ATLAS_READY; output:\n" + "".join(seen[-30:]))
            seen.append(line)
            if "SCENE_ATLAS_READY" in line:
                assert f"port={self.port}" in line
                return seen

    def stop(self) -> None:
        if self.proc.poll() is None:
            self.proc.kill()
        self.proc.wait()


@pytest.fixture
def sidecar_factory(tmp_path):
    started: list[Sidecar] = []

    def make(*extra_args: str) -> Sidecar:
        sidecar = Sidecar(tmp_path, *extra_args)
        started.append(sidecar)
        return sidecar

    yield make
    for sidecar in started:
        sidecar.stop()


def test_ready_is_printed_only_once_listening(sidecar_factory):
    sidecar = sidecar_factory()
    output = "".join(sidecar.wait_ready())
    assert "Uvicorn running on" in output
    # No retry: the socket must already be accepting when the marker appears.
    socket.create_connection(("127.0.0.1", sidecar.port), timeout=5).close()


def test_closing_stdin_shuts_down_and_releases_the_lock(sidecar_factory):
    sidecar = sidecar_factory("--parent-pid", str(os.getpid()))
    sidecar.wait_ready()
    assert sidecar.proc.stdin is not None
    sidecar.proc.stdin.close()
    assert sidecar.proc.wait(timeout=SHUTDOWN_TIMEOUT) == 0
    assert child_can_lock(sidecar.data_dir)


def test_parent_exit_shuts_down(sidecar_factory):
    parent = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"])
    try:
        sidecar = sidecar_factory("--parent-pid", str(parent.pid))
        sidecar.wait_ready()
        parent.kill()
        parent.wait()
        # stdin stays open here: only the PID poll can notice.
        assert sidecar.proc.wait(timeout=SHUTDOWN_TIMEOUT) == 0
    finally:
        parent.kill()
        parent.wait()


def test_without_parent_pid_stdin_eof_is_ignored(sidecar_factory):
    sidecar = sidecar_factory()
    sidecar.wait_ready()
    assert sidecar.proc.stdin is not None
    sidecar.proc.stdin.close()
    with pytest.raises(subprocess.TimeoutExpired):
        sidecar.proc.wait(timeout=3)
