"""process_utils: RSS and handing freed memory back to the OS."""

import ctypes
import sys

import pytest

from backend.app.process_utils import get_rss_mb, release_freed_memory


def _has_glibc() -> bool:
    try:
        return hasattr(ctypes.CDLL("libc.so.6"), "malloc_trim")
    except OSError:
        return False


def test_rss_is_reported():
    rss = get_rss_mb()
    assert rss is None or rss > 0


def test_release_freed_memory_never_raises():
    assert release_freed_memory() in (True, False)


@pytest.mark.skipif(not sys.platform.startswith("linux") or not _has_glibc(), reason="glibc")
def test_release_freed_memory_trims_with_glibc():
    assert release_freed_memory() is True


@pytest.mark.skipif(sys.platform.startswith("linux"), reason="trims only on Linux")
def test_release_freed_memory_only_collects_elsewhere():
    assert release_freed_memory() is False
