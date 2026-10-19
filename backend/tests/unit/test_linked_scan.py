"""The linked folder scan's diff and its scheduling (design/library-setup.md §4.3).
Applying a scan to the database is covered by integration/test_linked_library.py."""

from __future__ import annotations

import threading
import time

from backend.app.models.database import (
    FILE_DUPLICATE,
    FILE_FAILED,
    FILE_IMAGE,
    FILE_REMOVED,
)
from backend.app.services.originals import LinkedEntry
from backend.pipeline.linked_scan import KnownFile, LinkedScanner, ScanResult, diff_files


def known(id_: int, key: str, size=10, mtime=100, state=FILE_IMAGE, missing=False) -> KnownFile:
    return KnownFile(id_, key, size, mtime, state, missing)


def entry(key: str, size=10, mtime=100) -> LinkedEntry:
    return LinkedEntry(key, size, mtime)


# diff_files


def test_new_files():
    diff = diff_files([entry("A/new.png")], [])
    assert [e.rel_key for e in diff.new] == ["A/new.png"]
    assert not (diff.changed or diff.gone or diff.back)


def test_unchanged_files_are_only_counted():
    diff = diff_files(
        [entry("A/a.png"), entry("A/b.png")],
        [known(1, "A/a.png"), known(2, "A/b.png", state=FILE_DUPLICATE)],
    )
    assert diff.unchanged == 2
    assert not (diff.new or diff.changed or diff.gone or diff.back)


def test_changed_files_by_size_or_mtime():
    diff = diff_files(
        [entry("A/size.png", size=11), entry("A/mtime.png", mtime=101)],
        [known(1, "A/size.png"), known(2, "A/mtime.png")],
    )
    assert [(k.id, e.size, e.mtime_ns) for k, e in diff.changed] == [(1, 11, 100), (2, 10, 101)]


def test_gone_files():
    diff = diff_files(
        [],
        [
            known(1, "A/image.png"),
            known(2, "A/failed.png", state=FILE_FAILED),
            known(3, "A/already-missing.png", missing=True),
            known(4, "A/removed.png", state=FILE_REMOVED),
        ],
    )
    # Already missing, or removed: nothing more to record
    assert [k.id for k in diff.gone] == [1, 2]


def test_back_again_when_size_and_mtime_match():
    diff = diff_files(
        [entry("A/back.png"), entry("A/back-but-edited.png", size=99)],
        [known(1, "A/back.png", missing=True), known(2, "A/back-but-edited.png", missing=True)],
    )
    assert [k.id for k in diff.back] == [1]
    assert [k.id for k, _ in diff.changed] == [2]


def test_removed_files_are_never_offered_again():
    """Removing a linked map marks its file removed; a rescan, changed or not, leaves it."""
    diff = diff_files(
        [entry("A/removed.png"), entry("A/removed-edited.png", size=5)],
        [
            known(1, "A/removed.png", state=FILE_REMOVED),
            known(2, "A/removed-edited.png", state=FILE_REMOVED),
        ],
    )
    assert not (diff.new or diff.changed or diff.gone or diff.back)


# LinkedScanner


class _Gate:
    """A scan that waits until released, to observe a scan in progress."""

    def __init__(self):
        self.started = threading.Event()
        self.release = threading.Event()
        self.calls = 0

    def __call__(self) -> ScanResult:
        self.calls += 1
        self.started.set()
        self.release.wait(5)
        return ScanResult("online")


def test_one_scan_at_a_time():
    gate = _Gate()
    scanner = LinkedScanner(scan=gate)
    assert scanner.start("manual")
    assert gate.started.wait(5)
    assert scanner.running
    assert not scanner.start("manual")
    assert scanner.scan() is None
    gate.release.set()
    for _ in range(100):
        if not scanner.running:
            break
        time.sleep(0.01)
    assert not scanner.running
    assert gate.calls == 1


def test_focus_scans_are_throttled():
    scanner = LinkedScanner(scan=lambda: ScanResult("online"))
    assert scanner.scan() is not None
    assert not scanner.start("focus")  # a scan started under a minute ago
    assert scanner.start("manual")  # Check for changes always runs


def test_timer_is_due_after_the_interval(monkeypatch):
    scanner = LinkedScanner(scan=lambda: ScanResult("online"))
    assert scanner.due(15)  # never scanned
    assert not scanner.due(0)  # rescans off
    scanner.scan()
    assert not scanner.due(15)
    later = time.monotonic() + 15 * 60
    monkeypatch.setattr("backend.pipeline.linked_scan.time.monotonic", lambda: later)
    assert scanner.due(15)


def test_a_failed_scan_frees_the_scanner():
    def boom() -> ScanResult:
        raise RuntimeError("disk on fire")

    scanner = LinkedScanner(scan=boom)
    assert scanner.scan() is None
    assert not scanner.running
