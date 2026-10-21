"""Exclusive per-storage-root lock: one backend per SCENE_ATLAS_DATA_DIR and SCENE_ATLAS_IMAGES_DIR.

Two backends on one root corrupt each other: startup recovery clears
``.incoming/`` and re-queues items the other process is processing, and the
orphan sweep deletes library files the other database references. The lock is
an OS advisory lock on ``<root>/.backend.lock`` (``fcntl.flock`` on POSIX,
``msvcrt.locking`` on Windows), so the OS drops it when the process exits,
however it exits. The file itself is left in place.
"""

import contextlib
import errno
import logging
import os
import sys
import time
from pathlib import Path

logger = logging.getLogger(__name__)

LOCK_FILENAME = ".backend.lock"

# Lock held by someone else. Anything else (e.g. ENOLCK on a network share
# without lock support) means locking is unavailable there.
_CONTENDED = {errno.EACCES, errno.EAGAIN, errno.EWOULDBLOCK, errno.EDEADLK}


class StorageLockedError(RuntimeError):
    """Another process holds the lock on a storage root."""

    def __init__(self, root: Path, holder_pid: int | None):
        holder = f" (process {holder_pid})" if holder_pid else ""
        super().__init__(
            f"Another Scene Atlas backend{holder} is already using the folder {root}. "
            "Close it, or stop that server, then start again."
        )
        self.root = root
        self.holder_pid = holder_pid


def _lock(fd: int) -> None:
    if sys.platform == "win32":
        import msvcrt

        os.lseek(fd, 0, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
    else:
        import fcntl

        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)


def _unlock(fd: int) -> None:
    if sys.platform == "win32":
        import msvcrt

        os.lseek(fd, 0, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
    else:
        import fcntl

        fcntl.flock(fd, fcntl.LOCK_UN)


def _read_pid(path: Path) -> int | None:
    # Skip the locked first byte: on Windows, reading a locked range fails.
    try:
        with path.open("rb") as f:
            f.seek(1)
            return int(f.read(32).strip() or b"0") or None
    except (OSError, ValueError):
        return None


class StorageLock:
    """Holds the lock on one root until released (or the process exits)."""

    def __init__(self, root: Path, fd: int | None):
        self.root = root
        self._fd = fd

    @property
    def held(self) -> bool:
        return self._fd is not None

    def release(self) -> None:
        fd, self._fd = self._fd, None
        if _held.get(self.root) is self:
            del _held[self.root]
        if fd is None:
            return
        with contextlib.suppress(OSError):
            _unlock(fd)
        os.close(fd)


# One lock per root per process: re-acquiring returns the held lock, so an
# in-process restart (the sidecar's crash supervisor) doesn't lock itself out.
_held: dict[Path, StorageLock] = {}


def acquire_storage_lock(
    root: Path, timeout: float = 0.0, poll_interval: float = 0.25
) -> StorageLock:
    """Lock *root* for this process, waiting up to *timeout* seconds.

    Raises StorageLockedError if another process still holds it. Where the
    filesystem has no lock support, logs a warning and returns an unheld lock.
    """
    root = Path(root).resolve()
    existing = _held.get(root)
    if existing is not None:
        return existing

    path = root / LOCK_FILENAME
    fd = os.open(path, os.O_RDWR | os.O_CREAT | getattr(os, "O_BINARY", 0), 0o644)
    deadline = time.monotonic() + timeout
    try:
        while True:
            try:
                _lock(fd)
                break
            except OSError as exc:
                if exc.errno not in _CONTENDED:
                    logger.warning(
                        "Cannot lock %s (%s); not guarding against a second backend there",
                        root,
                        exc,
                    )
                    os.close(fd)
                    lock = StorageLock(root, None)
                    _held[root] = lock
                    return lock
            if time.monotonic() >= deadline:
                raise StorageLockedError(root, _read_pid(path))
            time.sleep(poll_interval)
        # Byte 0 is the lock byte; the PID after it is for the error message.
        os.ftruncate(fd, 0)
        os.lseek(fd, 0, os.SEEK_SET)
        os.write(fd, f"\n{os.getpid()}\n".encode())
    except BaseException:
        with contextlib.suppress(OSError):
            os.close(fd)
        raise

    lock = StorageLock(root, fd)
    _held[root] = lock
    return lock
