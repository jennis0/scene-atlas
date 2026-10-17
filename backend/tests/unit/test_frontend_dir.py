"""The Electron sidecar serves the UI, so the bundled frontend must be found when frozen."""

import sys
from pathlib import Path

from backend.app.main import _frontend_dir


def test_source_checkout_uses_repo_frontend_dist():
    assert _frontend_dir() == Path(__file__).resolve().parents[3] / "frontend" / "dist"


def test_frozen_build_uses_bundled_frontend_dist(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    assert _frontend_dir() == tmp_path / "frontend" / "dist"
