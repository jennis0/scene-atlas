"""Tests for memory-aware admission (backend/app/services/memory_budget.py)."""

import threading
import time

import pytest

from backend.app.services.memory_budget import MemoryBudget, default_capacity_bytes


def test_reserve_and_release():
    budget = MemoryBudget(100)
    with budget.reserve(60):
        assert budget.in_use == 60
    assert budget.in_use == 0


def test_released_on_exception():
    budget = MemoryBudget(100)
    with pytest.raises(RuntimeError), budget.reserve(60):
        raise RuntimeError("boom")
    assert budget.in_use == 0


def test_waits_when_exhausted():
    budget = MemoryBudget(100)
    entered = threading.Event()
    order = []

    def second():
        with budget.reserve(60):
            order.append("second")
            entered.set()

    with budget.reserve(60):
        thread = threading.Thread(target=second)
        thread.start()
        time.sleep(0.1)
        assert not entered.is_set()  # 60 + 60 > 100: must wait
        order.append("first-done")
    assert entered.wait(2)
    thread.join()
    assert order == ["first-done", "second"]


def test_small_items_share_the_budget():
    budget = MemoryBudget(100)
    with budget.reserve(40), budget.reserve(40):
        assert budget.in_use == 80


def test_oversized_item_runs_alone_instead_of_deadlocking():
    budget = MemoryBudget(100)
    with budget.reserve(500):
        assert budget.in_use == 100  # clamped to capacity: nothing else gets in
    assert budget.in_use == 0


def test_rejects_non_positive_capacity():
    with pytest.raises(ValueError):
        MemoryBudget(0)


def test_default_capacity_is_at_least_one_gib():
    assert default_capacity_bytes() >= 1024**3
