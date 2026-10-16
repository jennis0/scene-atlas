"""Unit tests for search_service helpers (ranking fusion, id sets, mode flags)."""

import pytest
from sqlalchemy import func, select

from backend.app.models.database import Image
from backend.app.services.search_service import (
    RRF_ALIAS_WEIGHT,
    RRF_K,
    RRF_TEXT_WEIGHT,
    SearchMode,
    fuse_rankings,
    id_set,
)


class TestFuseRankings:
    def test_ranks_not_raw_scores_are_fused(self):
        merged = fuse_rankings({1: -9.0, 2: -1.0}, {}, {2: 0.9, 3: 0.1})
        assert merged[1] == pytest.approx(RRF_TEXT_WEIGHT / RRF_K)
        assert merged[2] == pytest.approx(1.0 / RRF_K + RRF_TEXT_WEIGHT / (RRF_K + 1))
        assert merged[3] == pytest.approx(1.0 / (RRF_K + 1))

    def test_alias_matches_weigh_less_than_text(self):
        merged = fuse_rankings({1: -5.0}, {2: -5.0}, {})
        assert merged[2] == pytest.approx(RRF_ALIAS_WEIGHT / RRF_K)
        assert merged[1] > merged[2]

    def test_empty(self):
        assert fuse_rankings({}, {}, {}) == {}


@pytest.mark.parametrize(
    ("text_only", "semantic_only", "mode"),
    [
        (False, False, SearchMode.HYBRID),
        (True, False, SearchMode.TEXT),
        (False, True, SearchMode.SEMANTIC),
        (True, True, SearchMode.TEXT),
    ],
)
def test_search_mode_from_flags(text_only, semantic_only, mode):
    assert SearchMode.from_flags(text_only=text_only, semantic_only=semantic_only) is mode


def test_id_set_handles_more_ids_than_sqlite_bound_parameters(db_session):
    """Colour matches and candidate pools can exceed SQLite's 32766-parameter limit."""
    for n in (1, 2, 39_999):
        db_session.add(Image(id=n, filename=f"{n}.jpg", storage_key=f"{n}.jpg"))
    db_session.flush()
    ids = range(1, 40_000)
    count = db_session.scalar(select(func.count()).where(Image.id.in_(id_set(ids))))
    assert count == 3
