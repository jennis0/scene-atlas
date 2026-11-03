"""process_utils: RSS and handing freed memory back to the OS."""

import sys

from backend.app.process_utils import get_rss_mb, release_freed_memory


def test_rss_is_reported():
    rss = get_rss_mb()
    assert rss is None or rss > 0


def test_release_freed_memory_trims_on_linux_only():
    assert release_freed_memory() is sys.platform.startswith("linux")
