"""Tests for resource_detector module."""

from unittest.mock import patch

from backend.app.resource_detector import compute_resource_defaults


def test_returns_all_expected_keys():
    """compute_resource_defaults returns all three concurrency keys."""
    defaults = compute_resource_defaults()
    assert set(defaults) == {
        "max_job_workers",
        "max_concurrent_prepare",
        "max_concurrent_heavy_requests",
    }


def test_minimum_values_enforced_single_core_low_ram():
    """On a 1-core 1 GB machine, all values must be >= 1."""
    with patch("os.cpu_count", return_value=1), patch("psutil.virtual_memory") as mock_mem:
        mock_mem.return_value.total = 1 * 1024**3
        defaults = compute_resource_defaults()
    assert defaults["max_job_workers"] >= 1
    assert defaults["max_concurrent_prepare"] >= 1
    assert defaults["max_concurrent_heavy_requests"] >= 1


def test_high_spec_machine_scales_up():
    """On a 16-core 32 GB machine, concurrency scales up appropriately."""
    with patch("os.cpu_count", return_value=16), patch("psutil.virtual_memory") as mock_mem:
        mock_mem.return_value.total = 32 * 1024**3
        defaults = compute_resource_defaults()
    assert defaults["max_job_workers"] >= 4
    assert defaults["max_concurrent_prepare"] >= 4


def test_prepare_workers_capped_at_four_however_big_the_machine():
    """Prepare threads share the GIL with API requests: past 4 they starve searches
    during an import without importing any faster."""
    with patch("os.cpu_count", return_value=64), patch("psutil.virtual_memory") as mock_mem:
        mock_mem.return_value.total = 256 * 1024**3
        defaults = compute_resource_defaults()
    assert defaults["max_concurrent_prepare"] == 4


def test_low_ram_caps_concurrent_prepare():
    """On a 2 GB machine, prepare is capped lower than on 16 GB."""
    with patch("os.cpu_count", return_value=8), patch("psutil.virtual_memory") as mock_mem:
        mock_mem.return_value.total = 2 * 1024**3
        low_ram = compute_resource_defaults()

    with patch("os.cpu_count", return_value=8), patch("psutil.virtual_memory") as mock_mem2:
        mock_mem2.return_value.total = 16 * 1024**3
        high_ram = compute_resource_defaults()

    assert low_ram["max_concurrent_prepare"] < high_ram["max_concurrent_prepare"]


def test_psutil_unavailable_falls_back_gracefully():
    """When psutil is unavailable, returns conservative but valid ints."""
    with patch("backend.app.resource_detector._psutil", None):
        defaults = compute_resource_defaults()
    assert all(isinstance(v, int) and v >= 1 for v in defaults.values())
