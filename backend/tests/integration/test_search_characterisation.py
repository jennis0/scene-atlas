"""Golden-response tests for the search endpoints.

Pins the exact responses (ordering, totals, scores, mosaics) of ``/search/``,
``/search/groups`` and ``/search/facets`` over a deterministic library, so
refactors of the search code can't silently change behaviour. Semantic search
is replaced by a deterministic fake.

If a behaviour change is intended, regenerate the golden file and review the diff:

    UPDATE_SEARCH_GOLDEN=1 uv run python -m pytest \
        backend/tests/integration/test_search_characterisation.py
"""

import json
import os
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from backend.app.models.database import Color, Image, ImageGroup, Tag

GOLDEN_PATH = Path(__file__).parent / "golden" / "search_responses.json"
_VOLATILE_KEYS = {"created_at", "updated_at"}

# (base_name, author, [(name, image_type, media_type, gridded, grid_type, tags, colors)])
_LIBRARY = [
    (
        "Forest Variants",
        "AuthorA",
        [
            ("Forest Winter", "battlemap", "image", True, "square", ["season:winter"], ["#ffffff"]),
            ("Forest Summer", "battlemap", "image", True, "square", ["season:summer"], ["#00ff00"]),
            ("Forest Night", "battlemap", "image", True, "hex", ["lighting:night"], ["#101830"]),
            ("Forest Day", "battlemap", "image", False, None, ["lighting:day"], ["#88cc44"]),
            ("Forest Rain", "battlemap", "image", None, None, ["weather:rain"], []),
            ("Forest Fog", "scene", "image", None, None, ["weather:fog"], ["#aaaaaa"]),
        ],
    ),
    (
        "Dungeon Depths",
        "AuthorB",
        [
            ("Dungeon Dark", "battlemap", "image", True, "square", ["lighting:dark"], ["#1a1a1a"]),
            (
                "Dungeon Torch",
                "battlemap",
                "image",
                True,
                "square",
                ["lighting:torch"],
                ["#ffaa00"],
            ),
            ("Dungeon Flooded", "battlemap", "video", False, None, ["weather:rain"], ["#2244aa"]),
        ],
    ),
    (
        "Tavern",
        "AuthorC",
        [
            ("Tavern Empty", "scene", "image", None, None, ["occupancy:empty"], ["#996633"]),
            ("Tavern Crowded", "scene", "image", None, None, ["occupancy:crowded"], ["#aa7744"]),
            ("Tavern Night", "scene", "image", None, None, ["lighting:night"], ["#221100"]),
            ("Tavern Day", "scene", "image", None, None, ["lighting:day"], ["#ffeecc"]),
            ("Tavern Cellar", "battlemap", "image", True, "hex", [], ["#332211"]),
            ("Tavern Roof", "battlemap", "image", True, "square", ["season:winter"], []),
            ("Tavern Yard", "battlemap", "image", False, None, ["season:summer"], ["#33aa33"]),
        ],
    ),
    (
        "Cave Network",
        "AuthorA",
        [
            ("Cave Entrance", "battlemap", "image", True, "square", ["terrain:cave"], ["#554433"]),
            ("Cave Lake", "battlemap", "image", True, "hex", ["terrain:cave", "weather:fog"], []),
        ],
    ),
    (
        "Desert Ruins",
        "AuthorD",
        [
            ("Desert Ruins Noon", "battlemap", "image", False, None, ["lighting:day"], ["#eecc88"]),
        ],
    ),
    ("Empty Group", "AuthorE", []),
]


def _fake_semantic_scores(query: str, limit: int) -> list[dict]:
    """Deterministic stand-in for CLIP + LanceDB: distinct scores, query-dependent."""
    salt = sum(ord(c) for c in query)
    scored = [
        {"image_id": i, "score": 0.9 - 0.01 * ((i * 7 + salt) % 23) - i * 1e-4}
        for i in range(1, 40)
        if (i + salt) % 3 != 0
    ]
    scored.sort(key=lambda r: r["score"], reverse=True)
    return scored[:limit]


class _FakeClip:
    def encode_text(self, query):
        return query


class _FakeLanceDB:
    def search_similar(self, query_embedding=None, limit=10, score_threshold=None):
        return _fake_semantic_scores(query_embedding, limit)


class _BrokenClip:
    def encode_text(self, query):
        raise RuntimeError("CLIP model not loaded")


def _patch_semantic(monkeypatch, clip) -> None:
    import backend.app.api.search as api_module

    modules = [api_module]
    try:
        import backend.app.services.search_service as service_module

        modules.append(service_module)
    except ImportError:
        pass
    for module in modules:
        monkeypatch.setattr(module, "get_clip_service", lambda: clip, raising=False)
        monkeypatch.setattr(module, "get_lancedb_service", _FakeLanceDB, raising=False)


@pytest.fixture
def golden_library(test_client, tmp_db, monkeypatch):
    from backend.app.services.color_search import color_index
    from backend.app.services.fts_service import invalidate_alias_cache

    _, SessionLocal = tmp_db
    db = SessionLocal()
    start = datetime(2025, 1, 1)
    n = 0
    for g_index, (base_name, author, images) in enumerate(_LIBRARY):
        group = ImageGroup(
            base_name=base_name, author=author, created_at=start + timedelta(days=g_index)
        )
        db.add(group)
        db.flush()
        for name, image_type, media_type, gridded, grid_type, tags, colors in images:
            n += 1
            img = Image(
                name=name,
                filename=f"{name.replace(' ', '_')}.jpg",
                storage_key=f"key{n}.jpg",
                author=author,
                group_id=group.id,
                image_type=image_type,
                media_type=media_type,
                gridded=gridded,
                grid_type=grid_type,
                search_text=" ".join([name, *(t.split(":")[1] for t in tags)]),
                created_at=start + timedelta(hours=n * 5),
                updated_at=start,
            )
            db.add(img)
            db.flush()
            if group.primary_image_id is None and n % 2 == 0:
                group.primary_image_id = img.id
            for tag in tags:
                category, value = tag.split(":")
                db.add(Tag(image_id=img.id, category=category, value=value, created_at=start))
            for order, hex_val in enumerate(colors, start=1):
                db.add(
                    Color(image_id=img.id, color_hex=hex_val, percentage=40.0, color_order=order)
                )
    # An ungrouped image: search counts it towards total_groups but never shows it.
    db.add(
        Image(
            name="Loose Forest Sketch",
            filename="loose.jpg",
            storage_key="loose.jpg",
            author="AuthorZ",
            search_text="Loose Forest Sketch",
            created_at=start + timedelta(days=30),
            updated_at=start,
        )
    )
    db.commit()
    db.close()

    color_index._loaded_at = 0.0  # the index is a process-wide cache
    invalidate_alias_cache()
    _patch_semantic(monkeypatch, _FakeClip())
    return test_client


_SEARCH_CASES: list[tuple[str, dict]] = [
    ("browse_default", {}),
    ("browse_name_asc", {"sort_by": "name", "sort_dir": "asc"}),
    ("browse_name_desc", {"sort_by": "name", "sort_dir": "desc"}),
    ("browse_created_asc", {"sort_by": "created_at", "sort_dir": "asc"}),
    ("browse_relevance_falls_back", {"sort_by": "relevance", "sort_dir": "asc"}),
    ("browse_paginated", {"limit": 4, "offset": 3}),
    ("filter_scene", {"image_types": ["scene"]}),
    ("filter_video", {"media_types": ["video"]}),
    ("filter_gridded", {"gridded": True}),
    ("filter_gridless", {"gridded": False}),
    ("filter_grid_unknown", {"gridded_unknown": True, "gridded": True}),
    ("filter_hex", {"grid_type": "hex"}),
    ("filter_authors", {"authors": ["AuthorA", "AuthorD"]}),
    ("filter_exclude_authors", {"exclude_authors": ["AuthorA", "AuthorC"]}),
    ("filter_tag", {"tags": ["lighting:night"]}),
    ("filter_tags_or", {"tags": ["lighting:night", "lighting:day"]}),
    ("filter_tags_and", {"tags": ["lighting:night", "season:winter", "lighting:day"]}),
    ("filter_tag_malformed_ignored", {"tags": ["nocolon", "weather:fog"]}),
    ("filter_exclude_tags", {"exclude_tags": ["lighting:day", "weather:rain", "junk"]}),
    ("filter_colors", {"colors": ["#ff0000", "#ffffff"]}),
    ("filter_colors_no_match", {"colors": ["#ff00ff"]}),
    (
        "filter_combined",
        {"image_types": ["battlemap"], "gridded": True, "exclude_tags": ["season:winter"]},
    ),
    ("text_forest", {"query": "forest", "text_only": True}),
    ("text_forest_relevance", {"query": "forest", "text_only": True, "sort_by": "relevance"}),
    ("text_multiword", {"query": "forest night", "text_only": True, "sort_by": "relevance"}),
    ("text_phrase", {"query": '"tavern night"', "text_only": True, "sort_by": "relevance"}),
    ("text_alias_needs_text_hit", {"query": "daytime", "text_only": True}),
    ("text_alias", {"query": "tavern daytime", "text_only": True, "sort_by": "relevance"}),
    ("text_no_match", {"query": "zzznomatch", "text_only": True}),
    ("hybrid_relevance", {"query": "forest", "sort_by": "relevance"}),
    ("hybrid_name_asc", {"query": "tavern", "sort_by": "name", "sort_dir": "asc"}),
    ("hybrid_paginated", {"query": "cave", "sort_by": "relevance", "limit": 3, "offset": 2}),
    ("hybrid_small_limit", {"query": "forest", "sort_by": "relevance", "limit": 1}),
    ("hybrid_filtered", {"query": "forest", "sort_by": "relevance", "tags": ["lighting:night"]}),
    ("semantic_only", {"query": "cave", "semantic_only": True, "sort_by": "relevance"}),
    ("text_wins_over_semantic", {"query": "cave", "semantic_only": True, "text_only": True}),
    ("deprecated_text_param", {"text": "dungeon", "sort_by": "relevance"}),
    ("deprecated_semantic_param", {"semantic": "dungeon", "sort_by": "relevance"}),
]

_GROUP_CASES: list[tuple[str, dict]] = [
    ("browse_default", {}),
    ("browse_name_asc", {"sort_by": "name", "sort_dir": "asc"}),
    ("browse_name_desc", {"sort_by": "name", "sort_dir": "desc"}),
    ("browse_created_asc", {"sort_by": "created_at", "sort_dir": "asc"}),
    ("browse_paginated", {"limit": 2, "offset": 1}),
    ("browse_all_ids", {"include_all_image_ids": True}),
    ("browse_all_ids_scene", {"include_all_image_ids": True, "image_types": ["scene"]}),
    ("browse_video", {"media_types": ["video"]}),
    ("browse_gridded", {"gridded": True}),
    ("browse_gridless", {"gridded": False}),
    ("browse_grid_unknown", {"gridded_unknown": True}),
    ("browse_hex", {"grid_type": "hex"}),
    ("browse_authors", {"authors": ["AuthorA"]}),
    ("browse_exclude_authors", {"exclude_authors": ["AuthorA"]}),
    ("browse_tags", {"tags": ["lighting:night", "season:winter"]}),
    ("browse_tags_or", {"tags": ["lighting:night", "lighting:torch"]}),
    ("browse_exclude_tags", {"exclude_tags": ["terrain:cave", "lighting:day"]}),
    ("browse_colors", {"colors": ["#ffffff"]}),
    ("browse_colors_no_match", {"colors": ["#ff00ff"]}),
    ("search_hybrid", {"query": "forest"}),
    ("search_hybrid_all_ids", {"query": "forest", "include_all_image_ids": True}),
    ("search_text", {"query": "tavern", "text_only": True}),
    (
        "search_text_all_ids",
        {"query": "tavern night", "text_only": True, "include_all_image_ids": True},
    ),
    ("search_semantic", {"query": "cave", "semantic_only": True}),
    ("search_paginated", {"query": "dungeon", "limit": 1, "offset": 1}),
    ("search_filtered", {"query": "forest", "gridded": True, "authors": ["AuthorA"]}),
    ("search_tags", {"query": "night", "tags": ["lighting:night"]}),
    ("search_colors", {"query": "forest", "colors": ["#00ff00"]}),
    ("search_whitespace_query", {"query": "   "}),
]


def _normalise(value):
    if isinstance(value, dict):
        return {k: _normalise(v) for k, v in value.items() if k not in _VOLATILE_KEYS}
    if isinstance(value, list):
        return [_normalise(v) for v in value]
    if isinstance(value, float):
        return round(value, 9)
    return value


def _collect(client) -> dict:
    out: dict = {"search": {}, "groups": {}}
    for name, params in _SEARCH_CASES:
        resp = client.get("/api/v1/search/", params=params)
        out["search"][name] = {"status": resp.status_code, "body": _normalise(resp.json())}
    for name, params in _GROUP_CASES:
        resp = client.get("/api/v1/search/groups", params=params)
        out["groups"][name] = {"status": resp.status_code, "body": _normalise(resp.json())}
    out["facets"] = _normalise(client.get("/api/v1/search/facets").json())
    return out


def test_search_responses_match_golden(golden_library):
    actual = _collect(golden_library)
    if os.environ.get("UPDATE_SEARCH_GOLDEN"):
        GOLDEN_PATH.write_text(json.dumps(actual, indent=1, sort_keys=True) + "\n")
    expected = json.loads(GOLDEN_PATH.read_text())
    for section in ("search", "groups"):
        for name in expected[section]:
            assert actual[section][name] == expected[section][name], f"{section}/{name}"
    assert actual["facets"] == expected["facets"]


def test_semantic_failure_responses(golden_library, monkeypatch):
    _patch_semantic(monkeypatch, _BrokenClip())
    client = golden_library
    params = {"query": "forest", "semantic_only": True}
    assert client.get("/api/v1/search/", params=params).status_code == 503
    assert client.get("/api/v1/search/groups", params=params).status_code == 503

    hybrid = client.get("/api/v1/search/groups", params={"query": "forest"})
    assert hybrid.status_code == 200
    assert "Forest Variants" in [g["base_name"] for g in hybrid.json()["groups"]]
