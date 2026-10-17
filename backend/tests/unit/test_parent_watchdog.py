"""The sidecar watchdog fires once when Electron closes stdin or exits."""

import contextlib
import os
import subprocess
import sys
import threading
import time

import pytest

from backend.app.parent_watchdog import ParentWatchdog


class Recorder:
    def __init__(self):
        self.calls = 0
        self.event = threading.Event()

    def __call__(self):
        self.calls += 1
        self.event.set()


@pytest.fixture
def pipe():
    read_fd, write_fd = os.pipe()
    fds = {"read": read_fd, "write": write_fd}
    yield fds
    for fd in fds.values():
        with contextlib.suppress(OSError):
            os.close(fd)


@pytest.fixture
def child():
    proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    yield proc
    proc.kill()
    proc.wait()


def _watchdog(on_gone, **kwargs):
    kwargs.setdefault("parent_pid", os.getpid())
    kwargs.setdefault("poll_interval", 0.05)
    kwargs.setdefault("hard_exit", lambda code: None)
    return ParentWatchdog(on_gone, **kwargs)


def test_fires_when_stdin_closes(pipe):
    on_gone = Recorder()
    _watchdog(on_gone, stdin_fd=pipe["read"]).start()
    os.write(pipe["write"], b"ignored")
    assert not on_gone.event.wait(0.3)
    os.close(pipe.pop("write"))
    assert on_gone.event.wait(5)


def test_fires_when_parent_exits(child):
    on_gone = Recorder()
    watchdog = _watchdog(on_gone, parent_pid=child.pid, stdin_fd=None)
    watchdog.start()
    assert not on_gone.event.wait(0.3)
    child.kill()
    child.wait()
    assert on_gone.event.wait(5)
    assert watchdog.fired


def test_fires_immediately_if_parent_already_gone(child):
    child.kill()
    child.wait()
    on_gone = Recorder()
    _watchdog(on_gone, parent_pid=child.pid, stdin_fd=None).start()
    assert on_gone.calls == 1


def test_fires_only_once(pipe, child):
    on_gone = Recorder()
    _watchdog(on_gone, parent_pid=child.pid, stdin_fd=pipe["read"]).start()
    os.close(pipe.pop("write"))
    child.kill()
    child.wait()
    assert on_gone.event.wait(5)
    time.sleep(0.3)
    assert on_gone.calls == 1


def test_unreadable_stdin_falls_back_to_pid_poll(child):
    on_gone = Recorder()
    _watchdog(on_gone, parent_pid=child.pid, stdin_fd=987_654).start()  # EBADF
    assert not on_gone.event.wait(0.3)
    child.kill()
    child.wait()
    assert on_gone.event.wait(5)


def test_hard_exits_if_shutdown_hangs(pipe):
    exited = threading.Event()
    codes = []

    def hard_exit(code):
        codes.append(code)
        exited.set()

    _watchdog(Recorder(), stdin_fd=pipe["read"], grace_secs=0.1, hard_exit=hard_exit).start()
    os.close(pipe.pop("write"))
    assert exited.wait(5)
    assert codes == [1]
