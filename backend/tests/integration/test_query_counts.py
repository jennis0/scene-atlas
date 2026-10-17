"""Query-count regression tests for read endpoints on hot paths.

Each test measures an endpoint over a small library, grows the library, and
checks the number of SQL statements stays the same: a per-row (N+1) query
shows up as a count that grows with the data. The absolute ceilings catch a
regression that adds a fixed number of queries per request.
"""

from datetime import datetime, timedelta

import pytest

from backend.app.models.database import Color, Image, ImageGroup, ImportJob, Tag

_START = datetime(2025, 1, 1)


class _Library:
    def __init__(self, session_factory):
        self._session_factory = session_factory
        self.groups = 0
        self.images = 0

    def add_groups(self, count: int, images_per_group: int = 6) -> None:
        with self._session_factory() as db:
            for _ in range(count):
                self.groups += 1
                group = ImageGroup(
                    base_name=f"Forest Group {self.groups}",
                    author=f"Author{self.groups % 3}",
                    created_at=_START + timedelta(days=self.groups),
                )
                db.add(group)
                db.flush()
                for i in range(images_per_group):
                    self.images += 1
                    img = Image(
                        name=f"Forest Map {self.images}",
                        filename=f"map{self.images}.jpg",
                        storage_key=f"map{self.images}.jpg",
                        author=group.author,
                        group_id=group.id,
                        gridded=i % 2 == 0,
                        image_type="battlemap" if i % 3 else "scene",
                        search_text=f"Forest Map {self.images}" + (" night" if i == 0 else ""),
                        created_at=_START + timedelta(hours=self.images),
                    )
                    db.add(img)
                    db.flush()
                    if i == 1:
                        group.primary_image_id = img.id
                    db.add(Tag(image_id=img.id, category="lighting", value="night"))
                    db.add(Tag(image_id=img.id, category="season", value="winter"))
                    db.add(Color(image_id=img.id, color_hex="#ffffff", color_order=1))
                    db.add(Color(image_id=img.id, color_hex="#203040", color_order=2))
            db.commit()


@pytest.fixture
def library(test_client, tmp_db, monkeypatch):
    _, SessionLocal = tmp_db

    class _NoClip:
        def encode_text(self, query):
            raise RuntimeError("no model in tests")

    import backend.app.services.search_service as search_service

    monkeypatch.setattr(search_service, "get_clip_service", _NoClip)
    lib = _Library(SessionLocal)
    lib.add_groups(3)
    return test_client, lib


def _count(client, query_counter, url, params=None) -> int:
    client.get(url, params=params)  # warm the process-wide alias cache
    with query_counter as q:
        resp = client.get(url, params=params)
    assert resp.status_code == 200, resp.text
    return q.count


def _assert_constant(client, lib, query_counter, url, params=None, ceiling=12):
    small = _count(client, query_counter, url, params)
    lib.add_groups(12)
    large = _count(client, query_counter, url, params)
    assert large == small, f"{url} {params}: {small} queries for 3 groups, {large} for 15"
    assert large <= ceiling, f"{url} {params}: {large} queries (ceiling {ceiling})"


@pytest.mark.parametrize(
    "params",
    [
        {},
        {"include_all_image_ids": True},
        {"tags": ["lighting:night"], "colors": ["#ffffff"], "image_types": ["scene"]},
        {"query": "forest", "text_only": True},
        {"query": "forest", "include_all_image_ids": True},
        {"query": "night", "text_only": True},
        {"query": "forest night", "text_only": True, "tags": ["season:winter"]},
    ],
)
def test_group_search_query_count_is_constant(library, query_counter, params):
    client, lib = library
    _assert_constant(client, lib, query_counter, "/api/v1/search/groups", params)


@pytest.mark.parametrize(
    "params",
    [
        {},
        {"sort_by": "name", "colors": ["#ffffff"], "tags": ["lighting:night"]},
        {"query": "forest", "text_only": True, "sort_by": "relevance"},
        {"query": "forest night", "sort_by": "created_at", "gridded": True},
    ],
)
def test_image_search_query_count_is_constant(library, query_counter, params):
    client, lib = library
    _assert_constant(client, lib, query_counter, "/api/v1/search/", params)


def test_facets_query_count(library, query_counter):
    client, lib = library
    _assert_constant(client, lib, query_counter, "/api/v1/search/facets", ceiling=6)


def test_image_list_query_count(library, query_counter):
    client, lib = library
    _assert_constant(client, lib, query_counter, "/api/v1/images/", {"limit": 100}, ceiling=5)


def test_image_scenes_query_count(library, query_counter):
    client, lib = library
    small = _count(client, query_counter, "/api/v1/images/1/scenes")
    with lib._session_factory() as db:
        for n in range(10):
            db.add(Image(filename=f"x{n}.jpg", storage_key=f"x{n}.jpg", group_id=1))
            db.flush()
        db.commit()
    large = _count(client, query_counter, "/api/v1/images/1/scenes")
    assert large == small <= 6


def test_group_detail_query_count(library, query_counter):
    client, lib = library
    small = _count(client, query_counter, "/api/v1/groups/1")
    with lib._session_factory() as db:
        for n in range(10):
            img = Image(filename=f"x{n}.jpg", storage_key=f"x{n}.jpg", group_id=1)
            db.add(img)
            db.flush()
            db.add(Tag(image_id=img.id, category="lighting", value="day"))
        db.commit()
    large = _count(client, query_counter, "/api/v1/groups/1")
    assert large == small <= 5


def test_group_detail_does_not_multiply_rows(library, query_counter):
    """Eager-loading tags and colours with joins returns tags × colours rows per image."""
    client, lib = library
    with query_counter as q:
        resp = client.get("/api/v1/groups/1")
    assert resp.status_code == 200
    images = resp.json()["images"]
    assert len(images) == 6
    assert all(len(img["tags"]) == 2 and len(img["colors"]) == 2 for img in images)
    assert not any("LEFT OUTER JOIN colors" in s and "JOIN tags" in s for s in q.statements)


def test_group_summaries_query_count(library, query_counter):
    client, lib = library
    url = "/api/v1/groups/summaries"
    small = _count_request(client, query_counter, "POST", url, json={"ids": [1, 2, 3]})
    lib.add_groups(12)
    ids = list(range(1, lib.groups + 1))
    large = _count_request(client, query_counter, "POST", url, json={"ids": ids})
    assert large == small <= 3


def test_group_details_query_count(library, query_counter):
    """One batch costs the same queries as a single group, however many groups it holds."""
    client, lib = library
    url = "/api/v1/groups/details"
    small = _count_request(client, query_counter, "POST", url, json={"ids": [1]})
    lib.add_groups(12)
    ids = list(range(1, lib.groups + 1))
    large = _count_request(client, query_counter, "POST", url, json={"ids": ids})
    assert large == small <= 5


def test_bulk_image_edit_query_count(library, query_counter):
    """A bulk edit costs the same queries for 18 images as for 90."""
    client, lib = library
    body = {
        "changes": {"subgroup": "Winter", "gridded": True},
        "add_tags": [{"category": "season", "value": "autumn"}],
    }
    url = "/api/v1/images/bulk-edit"
    ids = list(range(1, lib.images + 1))
    small = _count_request(client, query_counter, "POST", url, json={**body, "image_ids": ids})
    lib.add_groups(12)
    ids = list(range(1, lib.images + 1))
    large = _count_request(client, query_counter, "POST", url, json={**body, "image_ids": ids})
    assert large == small, "\n".join(query_counter.statements)


def test_group_bulk_update_query_count(library, query_counter):
    client, lib = library
    url = "/api/v1/groups/bulk-update"
    small = _count_request(
        client, query_counter, "POST", url, json={"ids": [1, 2, 3], "author": "X"}
    )
    lib.add_groups(12)
    ids = list(range(1, lib.groups + 1))
    large = _count_request(client, query_counter, "POST", url, json={"ids": ids, "author": "Y"})
    assert large == small, "\n".join(query_counter.statements)


def test_tag_values_query(library, query_counter):
    client, lib = library
    with lib._session_factory() as db:
        db.add(Tag(image_id=1, category="lighting", value="dusk"))
        db.commit()
    with query_counter as q:
        resp = client.get("/api/v1/tags/values/lighting")
    assert resp.json() == {"category": "lighting", "values": ["dusk", "night"]}
    assert q.count == 1
    assert "DISTINCT" in q.statements[0]


def test_import_list_query_count(library, query_counter):
    client, lib = library

    def add_jobs(count: int) -> None:
        with lib._session_factory() as db:
            for _ in range(count):
                db.add(ImportJob(id=f"{db.query(ImportJob).count():032x}", status="active"))
                db.flush()
            db.commit()

    add_jobs(2)
    small = _count(client, query_counter, "/api/v1/imports")
    add_jobs(10)
    large = _count(client, query_counter, "/api/v1/imports")
    assert large == small <= 4


def _count_request(client, query_counter, method, url, **kwargs) -> int:
    with query_counter as q:
        resp = client.request(method, url, **kwargs)
    assert resp.status_code == 200, resp.text
    return q.count


def test_tag_rename_cascade_query_count(library, query_counter):
    """Renaming a tag value re-indexes every tagged image in batched statements."""
    client, lib = library
    small = _count_request(
        client,
        query_counter,
        "PATCH",
        "/api/v1/tags/categories/lighting/tags/night",
        json={"new_value": "evening"},
    )
    lib.add_groups(12)
    large = _count_request(
        client,
        query_counter,
        "PATCH",
        "/api/v1/tags/categories/season/tags/winter",
        json={"new_value": "snowbound"},
    )
    assert large == small
    resp = client.get("/api/v1/search/", params={"query": "snowbound", "text_only": True})
    assert resp.json()["total"] == lib.images


def test_group_delete_query_count(library, query_counter):
    client, lib = library
    client.delete("/api/v1/groups/3")  # warm-up: the first delete initialises the vector store
    small = _count_request(client, query_counter, "DELETE", "/api/v1/groups/1")
    with lib._session_factory() as db:
        group = db.get(ImageGroup, 2)
        for n in range(20):
            db.add(Image(filename=f"x{n}.jpg", storage_key=f"x{n}.jpg", group_id=group.id))
        db.commit()
    large = _count_request(client, query_counter, "DELETE", "/api/v1/groups/2")
    assert large == small, "\n".join(query_counter.statements)
