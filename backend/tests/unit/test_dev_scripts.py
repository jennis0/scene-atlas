"""The dev start/stop scripts resolve paths from their own location; moving them must not break that."""

import runpy
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]


@pytest.mark.parametrize("script", ["scripts/app/start.py", "scripts/app/stop.py"])
def test_root_is_repo_root(script):
    namespace = runpy.run_path(str(REPO_ROOT / script), run_name="not_main")
    assert namespace["ROOT"] == REPO_ROOT
    assert (namespace["ROOT"] / "backend" / "app" / "main.py").exists()
