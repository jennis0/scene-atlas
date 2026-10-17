"""Opt-in regression test of grid detection on real maps from a local library.

Real maps are commercial artwork, so the cases live outside the repo. Point
``GRID_REGRESSION_CASES`` at a file recorded with::

    uv run --extra cpu python scripts/models/grid/train_grid_models.py record \\
        --labels labels.csv --out grid_cases.jsonl

and run ``GRID_REGRESSION_CASES=grid_cases.jsonl uv run python -m pytest
backend/tests/unit/test_grid_regression_local.py``. Any change in a result fails,
listing what moved; re-record only after reviewing the differences.
"""

import json
import os
from pathlib import Path

import pytest

from backend.app.services.grid import detect_grid

CASES = os.environ.get("GRID_REGRESSION_CASES")

pytestmark = pytest.mark.skipif(
    not CASES, reason="set GRID_REGRESSION_CASES to a recorded cases file to run"
)


def _cases() -> list[dict]:
    if not CASES:
        return []
    return [json.loads(line) for line in Path(CASES).read_text().splitlines() if line.strip()]


def test_grid_results_unchanged_on_local_maps():
    changed = []
    missing = []
    for case in _cases():
        path = Path(case["path"])
        if not path.exists():
            missing.append(path.name)
            continue
        for key, size_only in (("result", False), ("size_only_result", True)):
            now = detect_grid(path, case["width"], case["height"], size_only=size_only)
            if now != case[key]:
                changed.append(f"{path.name} [{key}]: {case[key]} -> {now}")
    assert not missing, f"{len(missing)} case images are missing, e.g. {missing[:3]}"
    assert not changed, f"{len(changed)} results changed:\n" + "\n".join(changed[:30])
