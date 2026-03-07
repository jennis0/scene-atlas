"""Tests for the global prepare pool."""

from concurrent.futures import ThreadPoolExecutor

import pytest

from backend.app.services.prepare_pool import (
    get_prepare_pool,
    init_prepare_pool,
    shutdown_prepare_pool,
)


@pytest.fixture(autouse=True)
def clean_pool():
    """Ensure pool is shut down before and after each test."""
    shutdown_prepare_pool(wait=True)
    yield
    shutdown_prepare_pool(wait=True)


def test_get_pool_before_init_raises():
    """Getting the pool before init should raise RuntimeError."""
    with pytest.raises(RuntimeError, match="not initialised"):
        get_prepare_pool()


def test_init_creates_pool():
    """init_prepare_pool should create a ThreadPoolExecutor."""
    init_prepare_pool(max_workers=2)
    pool = get_prepare_pool()
    assert isinstance(pool, ThreadPoolExecutor)


def test_init_idempotent():
    """Calling init_prepare_pool twice should be safe (idempotent)."""
    init_prepare_pool(max_workers=2)
    init_prepare_pool(max_workers=4)  # second call is no-op
    # Verify pool is still functional (first call's workers in use)
    pool = get_prepare_pool()
    result = pool.submit(lambda: 42).result()
    assert result == 42
