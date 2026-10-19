"""Reading originals: the source interface (design/library-setup.md §4.2).

An image's original is either a stored file (``storage_key``: the store, which Scene
Atlas writes) or a file in the linked folder (``source_file_id``: the user's own maps,
which it only reads). Both are read through the same small interface:

| Method | Store (``ImageStore``) | Linked folder (``LinkedFolder``) |
|---|---|---|
| ``list()`` | (the orphan sweep walks it) | the scan's walk |
| ``local_path(key)`` | the stored file | the file, after the containment check |
| ``put``, ``delete`` | yes | absent: the folder is read-only by type |

Nothing outside this interface builds a path to an original. ``original_path`` finds an
image's original whichever kind it is, and raises ``OriginalUnavailable`` when it can't
be read: the file is missing, or the linked folder isn't available (offline).
"""

from __future__ import annotations

import logging
import os
import stat
import threading
import time
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import TYPE_CHECKING, Literal

from ..config import settings

if TYPE_CHECKING:
    from ..models import Image

logger = logging.getLogger(__name__)

UnavailableState = Literal["missing", "offline"]
MISSING_REASON = "The original file is missing."


class OriginalUnavailable(Exception):
    """An original can't be read: ``missing`` (the file is gone) or ``offline`` (its
    folder isn't available). ``reason`` is shown to the user."""

    def __init__(self, state: UnavailableState, reason: str):
        super().__init__(reason)
        self.state: UnavailableState = state
        self.reason = reason


@dataclass(frozen=True)
class LinkedEntry:
    """A file found by the walk: its key, size and modification time."""

    rel_key: str
    size: int
    mtime_ns: int


def offline_reason(name: str) -> str:
    return f"{name} isn't available"


def _normcase(path: Path) -> Path:
    return Path(os.path.normcase(path))


class LinkedFolder:
    """The linked folder: the user's own maps, read where they are and never written.

    There is deliberately no ``put`` or ``delete``. Every read goes through the
    containment check in ``local_path``.
    """

    def __init__(self, root: Path):
        self.root = root

    @property
    def name(self) -> str:
        return self.root.name or str(self.root)

    def available(self) -> bool:
        """Whether the folder is there (a drive can be unplugged, a share down)."""
        return self.root.is_dir()

    def list(self) -> Iterator[LinkedEntry]:
        """Every supported image and video under the folder, keys relative to the folder
        itself (``Author/Pack/file``: the parser reads the first part as the author). The
        local import's walk: symlinks and the library's own folders are left out, and so
        is OS junk."""
        from backend.pipeline.ingest_local import is_media, walk_files

        for entry in walk_files(self.root):
            rel_key = Path(entry.path).relative_to(self.root).as_posix()
            # A backslash in a name (not Windows) isn't a key that can be read back
            if not is_media(rel_key) or "\\" in rel_key:
                continue
            info = entry.stat(follow_symlinks=False)
            yield LinkedEntry(rel_key, info.st_size, info.st_mtime_ns)

    def local_path(self, key: str) -> Path:
        """The file for ``key``, after the containment check: the key joined to the root
        must resolve inside the root, to a regular file that isn't a symlink. Anything
        else is refused as missing. Raises ``OriginalUnavailable``."""
        if not self.available():
            raise OriginalUnavailable("offline", offline_reason(self.name))
        if not _plain_key(key):
            logger.warning("Refused to read a linked file outside the folder: %r", key)
            raise OriginalUnavailable("missing", MISSING_REASON)
        candidate = self.root / key
        try:
            root = self.root.resolve(strict=True)
            resolved = candidate.resolve(strict=True)
            info = candidate.lstat()
        except (OSError, RuntimeError, ValueError):
            raise OriginalUnavailable("missing", MISSING_REASON) from None
        if not _normcase(resolved).is_relative_to(_normcase(root)):
            logger.warning("Refused to read a linked file outside the folder: %r", key)
            raise OriginalUnavailable("missing", MISSING_REASON)
        if not stat.S_ISREG(info.st_mode):  # lstat: a symlink is never a regular file
            raise OriginalUnavailable("missing", MISSING_REASON)
        return resolved


def _plain_key(key: str) -> bool:
    """A relative POSIX key with no ``..``: the shape the walk produces. (The resolve
    in ``local_path`` is the real check; this refuses the obvious cases early.)"""
    if not key or "\x00" in key:
        return False
    posix = PurePosixPath(key)
    if posix.is_absolute() or ".." in posix.parts:
        return False
    if os.name == "nt":  # a backslash or a drive is only a separator on Windows
        windows = PureWindowsPath(key)
        return not (windows.drive or windows.root or ".." in windows.parts)
    return True


def linked_folder() -> LinkedFolder | None:
    """The configured linked folder, or None. Only configuration names it (sidecar
    arguments or ``LINKED_LIBRARY_DIR``), never a request."""
    root = settings.linked_library_dir
    return LinkedFolder(root) if root is not None else None


# Whether the linked folder is there, remembered briefly: image listings ask once per
# image, and a stat of an unreachable network share can take seconds.
_AVAILABILITY_TTL = 5.0
_availability_lock = threading.Lock()
_availability: tuple[Path | None, float, bool] = (None, 0.0, False)


def linked_folder_available(*, fresh: bool = False) -> bool:
    """Whether linked originals can be read now: a folder is configured and it's there."""
    global _availability
    folder = linked_folder()
    if folder is None:
        return False
    now = time.monotonic()
    with _availability_lock:
        root, checked_at, available = _availability
        if not fresh and root == folder.root and now - checked_at < _AVAILABILITY_TTL:
            return available
    available = folder.available()
    with _availability_lock:
        _availability = (folder.root, now, available)
    return available


def forget_availability() -> None:
    """Check the folder again on the next ask (after a scan, and in tests)."""
    global _availability
    with _availability_lock:
        _availability = (None, 0.0, False)


def original_path(image: Image) -> Path:
    """The file holding ``image``'s original, to read. Raises ``OriginalUnavailable``."""
    if image.source_file_id is None:
        from . import get_image_store

        if image.storage_key is None:
            raise OriginalUnavailable("missing", MISSING_REASON)
        try:
            return get_image_store().local_path(image.storage_key)
        except FileNotFoundError:
            raise OriginalUnavailable("missing", MISSING_REASON) from None
    folder = linked_folder()
    if folder is None:
        raise OriginalUnavailable("offline", "The maps folder isn't linked")
    row = image.source_file
    if row is None:
        raise OriginalUnavailable("missing", MISSING_REASON)
    return folder.local_path(row.rel_key)
