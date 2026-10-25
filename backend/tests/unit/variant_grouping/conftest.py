"""The walk's tests check the naming rules: the learned namer is off unless a test module turns
it back on (``test_learned_naming.py``)."""

import pytest

from backend.app.services.variant_grouping import learned_naming


@pytest.fixture(autouse=True)
def rule_names(monkeypatch):
    monkeypatch.setattr(learned_naming, "load", lambda: None)
