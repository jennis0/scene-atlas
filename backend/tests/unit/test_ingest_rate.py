"""Tests for ProcessingRate, the measured time per imported file."""

import pytest

from backend.pipeline.ingest_rate import ProcessingRate


def test_unknown_until_a_batch_is_recorded():
    rate = ProcessingRate()
    assert rate.seconds_per_item() is None
    rate.record(0, 5.0)  # a batch that settled nothing doesn't count
    assert rate.seconds_per_item() is None


def test_averages_over_files_not_batches():
    rate = ProcessingRate(window=100)
    rate.record(16, 16.0)  # 1 s per file
    rate.record(4, 12.0)  # 3 s per file
    assert rate.seconds_per_item() == pytest.approx(28.0 / 20)


def test_old_batches_drop_off_once_the_rest_cover_the_window():
    rate = ProcessingRate(window=20)
    rate.record(10, 100.0)  # slow start
    rate.record(10, 10.0)
    rate.record(10, 10.0)
    # The first batch is dropped: the last two still cover 20 files
    assert rate.seconds_per_item() == pytest.approx(1.0)


def test_keeps_a_batch_the_window_still_needs():
    rate = ProcessingRate(window=20)
    rate.record(15, 15.0)
    rate.record(10, 20.0)
    # Dropping the first would leave 10 files, under the window
    assert rate.seconds_per_item() == pytest.approx(35.0 / 25)
