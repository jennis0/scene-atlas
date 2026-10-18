"""One backend per data dir: the lock excludes other processes and dies with its holder."""

import errno
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from backend.app.storage_lock import StorageLockedError, acquire_storage_lock

REPO_ROOT = Path(__file__).resolve().parents[3]

_HOLD = textwrap.dedent(
    """
    import sys, time
    from backend.app.storage_lock import acquire_storage_lock
    import os
    acquire_storage_lock(sys.argv[1])
    print("locked", os.getpid(), flush=True)
    time.sleep(float(sys.argv[2]))
    """
)

_TRY = textwrap.dedent(
    """
    import sys
    from backend.app.storage_lock import StorageLockedError, acquire_storage_lock
    try:
        acquire_storage_lock(sys.argv[1])
    except StorageLockedError:
        sys.exit(3)
    """
)


def _hold_in_child(data_dir: Path, seconds: float = 60) -> subprocess.Popen:
    proc = subprocess.Popen(
        [sys.executable, "-c", _HOLD, str(data_dir), str(seconds)],
        cwd=REPO_ROOT,
        stdout=subprocess.PIPE,
        text=True,
    )
    assert proc.stdout is not None
    status, pid = proc.stdout.readline().split()
    assert status == "locked"
    # The interpreter's own PID: on Windows the venv's python.exe is a launcher that
    # starts the real interpreter as a child, so proc.pid is not the lock holder.
    proc.holder_pid = int(pid)  # pyright: ignore[reportAttributeAccessIssue]
    return proc


def child_can_lock(data_dir: Path) -> bool:
    code = subprocess.run(
        [sys.executable, "-c", _TRY, str(data_dir)], cwd=REPO_ROOT, timeout=60
    ).returncode
    assert code in (0, 3)
    return code == 0


@pytest.fixture
def held_by_child(tmp_path):
    proc = _hold_in_child(tmp_path)
    yield proc
    proc.kill()
    proc.wait()


def test_reacquire_in_same_process_returns_held_lock(tmp_path):
    lock = acquire_storage_lock(tmp_path)
    try:
        assert acquire_storage_lock(tmp_path) is lock
        assert (tmp_path / ".backend.lock").exists()
    finally:
        lock.release()
    assert not lock.held


def test_other_process_is_excluded_until_release(tmp_path):
    lock = acquire_storage_lock(tmp_path)
    try:
        assert not child_can_lock(tmp_path)
    finally:
        lock.release()
    assert child_can_lock(tmp_path)


def test_locked_error_names_dir_and_holder(tmp_path, held_by_child):
    with pytest.raises(StorageLockedError) as excinfo:
        acquire_storage_lock(tmp_path)
    assert excinfo.value.holder_pid == held_by_child.holder_pid
    assert str(tmp_path.resolve()) in str(excinfo.value)
    assert "already using the folder" in str(excinfo.value)


def test_killed_holder_releases_lock(tmp_path, held_by_child):
    held_by_child.kill()
    held_by_child.wait()
    acquire_storage_lock(tmp_path).release()


def test_waits_for_holder_to_exit(tmp_path):
    proc = _hold_in_child(tmp_path, seconds=1)
    try:
        acquire_storage_lock(tmp_path, timeout=30, poll_interval=0.05).release()
    finally:
        proc.kill()
        proc.wait()


def test_gives_up_after_timeout(tmp_path, held_by_child):
    with pytest.raises(StorageLockedError):
        acquire_storage_lock(tmp_path, timeout=0.3, poll_interval=0.05)


def test_filesystem_without_lock_support_is_not_fatal(tmp_path, monkeypatch, caplog):
    from backend.app import storage_lock

    def no_locks(fd):
        raise OSError(errno.ENOLCK, "No locks available")

    monkeypatch.setattr(storage_lock, "_lock", no_locks)
    lock = acquire_storage_lock(tmp_path)
    try:
        assert not lock.held
        assert "Cannot lock" in caplog.text
    finally:
        lock.release()
