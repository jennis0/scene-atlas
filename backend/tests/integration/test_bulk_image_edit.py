"""Integration tests for POST /api/v1/images/bulk-edit and /bulk-restore."""

import pytest

from backend.app.models.database import GRID_SOURCE_USER, Image, ImageGroup, Tag
from backend.app.services.fts_service import search_text_for

EDIT = "/api/v1/images/bulk-edit"
RESTORE = "/api/v1/images/bulk-restore"


@pytest.fixture
def seeded(test_client, tmp_db):
    """Three images in one group: one gridded by the detector, one tagged 'night'."""
    _, SessionLocal = tmp_db
    with SessionLocal() as db:
        group = ImageGroup(base_name="Ruins", author="A")
        db.add(group)
        db.flush()
        detected = Image(
            name="Ruins Day",
            filename="day.jpg",
            storage_key="day.jpg",
            group_id=group.id,
            image_type="battlemap",
            gridded=True,
            grid_type="square",
            grid_width=20,
            grid_height=15,
            grid_source="detector",
            grid_confidence=0.9,
        )
        tagged = Image(name="Ruins Night", filename="night.jpg", storage_key="night.jpg")
        plain = Image(name="Ruins Snow", filename="snow.jpg", storage_key="snow.jpg")
        for img in (tagged, plain):
            img.group_id = group.id
            img.image_type = "battlemap"
        db.add_all([detected, tagged, plain])
        db.flush()
        db.add(Tag(image_id=tagged.id, category="lighting", value="night"))
        db.flush()
        # As ingest leaves them, so an undo can be compared with the original exactly
        for img in (detected, tagged, plain):
            db.refresh(img)
            img.search_text = search_text_for(img)
        db.commit()
        ids = [detected.id, tagged.id, plain.id]
    return test_client, SessionLocal, ids


def _image(SessionLocal, image_id: int) -> dict:
    with SessionLocal() as db:
        img = db.get(Image, image_id)
        assert img is not None
        return {
            "image_type": img.image_type,
            "subgroup": img.subgroup,
            "gridded": img.gridded,
            "grid_type": img.grid_type,
            "grid_width": img.grid_width,
            "grid_height": img.grid_height,
            "grid_source": img.grid_source,
            "grid_confidence": img.grid_confidence,
            "tags": sorted((t.category, t.value) for t in img.tags),
            "search_text": img.search_text,
        }


class TestBulkEdit:
    def test_adds_a_tag_once_and_indexes_it(self, seeded):
        client, SessionLocal, ids = seeded
        resp = client.post(
            EDIT, json={"image_ids": ids, "add_tags": [{"category": "lighting", "value": "night"}]}
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["updated"] == 3
        for image_id in ids:
            image = _image(SessionLocal, image_id)
            assert image["tags"] == [("lighting", "night")]
            assert "night" in (image["search_text"] or "").lower()

    def test_grid_change_takes_over_from_the_detector(self, seeded):
        client, SessionLocal, ids = seeded
        resp = client.post(EDIT, json={"image_ids": ids[:1], "changes": {"grid_type": "hex"}})
        assert resp.status_code == 200
        image = _image(SessionLocal, ids[0])
        assert image["grid_type"] == "hex"
        assert image["grid_source"] == GRID_SOURCE_USER
        assert image["grid_confidence"] is None
        assert image["grid_width"] == 20

    def test_turning_the_grid_off_clears_its_fields(self, seeded):
        client, SessionLocal, ids = seeded
        client.post(EDIT, json={"image_ids": ids[:1], "changes": {"gridded": False}})
        image = _image(SessionLocal, ids[0])
        assert image["gridded"] is False
        assert (image["grid_type"], image["grid_width"], image["grid_height"]) == (None,) * 3

    def test_sets_type_and_subgroup_leaving_other_fields(self, seeded):
        client, SessionLocal, ids = seeded
        changes = {"image_type": "scene", "subgroup": "Winter"}
        client.post(EDIT, json={"image_ids": ids, "changes": changes})
        for image_id in ids:
            image = _image(SessionLocal, image_id)
            assert image["image_type"] == "scene"
            assert image["subgroup"] == "Winter"
            assert "winter" in (image["search_text"] or "").lower()
        assert _image(SessionLocal, ids[0])["grid_source"] == "detector"

    def test_null_clears_a_field(self, seeded):
        client, SessionLocal, ids = seeded
        client.post(EDIT, json={"image_ids": ids, "changes": {"subgroup": "Winter"}})
        client.post(EDIT, json={"image_ids": ids, "changes": {"subgroup": None}})
        assert all(_image(SessionLocal, i)["subgroup"] is None for i in ids)

    def test_skips_unknown_ids(self, seeded):
        client, _, ids = seeded
        resp = client.post(EDIT, json={"image_ids": [*ids, 999_999], "changes": {}})
        assert resp.json()["updated"] == 3

    @pytest.mark.parametrize(
        "payload", [{"image_ids": []}, {"image_ids": [1], "changes": {"image_type": "map"}}]
    )
    def test_rejects_bad_requests(self, test_client, payload):
        assert test_client.post(EDIT, json=payload).status_code == 422


class TestBulkRestore:
    def test_undo_puts_everything_back(self, seeded):
        client, SessionLocal, ids = seeded
        before = [_image(SessionLocal, i) for i in ids]
        edit = client.post(
            EDIT,
            json={
                "image_ids": ids,
                "changes": {"gridded": False, "image_type": "scene", "subgroup": "Winter"},
                "add_tags": [{"category": "lighting", "value": "night"}],
            },
        ).json()
        assert [_image(SessionLocal, i) for i in ids] != before

        resp = client.post(RESTORE, json={"undo_id": edit["undo_id"]})
        assert resp.status_code == 200
        assert resp.json()["restored"] == 3
        assert [_image(SessionLocal, i) for i in ids] == before

    def test_an_edit_undoes_once(self, seeded):
        client, _, ids = seeded
        edit = client.post(EDIT, json={"image_ids": ids, "changes": {"subgroup": "A"}}).json()
        assert client.post(RESTORE, json={"undo_id": edit["undo_id"]}).status_code == 200
        assert client.post(RESTORE, json={"undo_id": edit["undo_id"]}).status_code == 410

    def test_unknown_undo_is_gone(self, test_client):
        assert test_client.post(RESTORE, json={"undo_id": "nope"}).status_code == 410


def _group_id(SessionLocal, image_id: int) -> int:
    with SessionLocal() as db:
        img = db.get(Image, image_id)
        assert img is not None and img.group_id is not None
        return img.group_id


class TestScope:
    def test_edits_a_whole_group_by_scope(self, seeded):
        client, SessionLocal, ids = seeded
        scope = {"group_ids": [_group_id(SessionLocal, ids[0])]}
        resp = client.post(EDIT, json={"scope": scope, "changes": {"image_type": "scene"}})
        assert resp.status_code == 200
        assert resp.json()["updated"] == 3
        assert all(_image(SessionLocal, i)["image_type"] == "scene" for i in ids)

    @pytest.mark.parametrize(
        ("flt", "expected"),
        [
            ({"grid": "square"}, [0]),
            ({"grid": "gridded"}, [0]),
            ({"grid": "unknown"}, [1, 2]),
            ({"tag": {"category": "lighting", "value": "night"}}, [1]),
            ({"subgroup": None}, [0, 1, 2]),
            ({"subgroup": "Winter"}, []),
            ({"image_type": "scene"}, []),
        ],
    )
    def test_filter_narrows_the_scope(self, seeded, flt, expected):
        client, SessionLocal, ids = seeded
        scope = {"group_ids": [_group_id(SessionLocal, ids[0])], "filter": flt}
        resp = client.post(EDIT, json={"scope": scope, "changes": {"subgroup": "Picked"}})
        assert resp.json()["updated"] == len(expected)
        picked = [
            i
            for i, image_id in enumerate(ids)
            if _image(SessionLocal, image_id)["subgroup"] == "Picked"
        ]
        assert picked == expected

    def test_needs_exactly_one_target(self, seeded):
        client, SessionLocal, ids = seeded
        scope = {"group_ids": [_group_id(SessionLocal, ids[0])]}
        assert client.post(EDIT, json={"image_ids": ids, "scope": scope}).status_code == 422
        assert client.post(EDIT, json={"changes": {}}).status_code == 422

    def test_facets_count_the_scope(self, seeded):
        client, SessionLocal, ids = seeded
        resp = client.post(
            "/api/v1/images/facets", json={"group_ids": [_group_id(SessionLocal, ids[0])]}
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 3
        assert body["image_type"] == [{"value": "battlemap", "count": 3}]
        grid = {g["value"]: g["count"] for g in body["grid"]}
        assert grid == {"square": 1, "hex": 0, "gridded": 1, "gridless": 0, "unknown": 2}
        assert body["subgroup"] == [{"value": None, "count": 3}]
        assert body["tags"] == [{"value": "lighting:night", "count": 1}]

    def test_facets_respect_the_filter(self, seeded):
        client, SessionLocal, ids = seeded
        scope = {"group_ids": [_group_id(SessionLocal, ids[0])], "filter": {"grid": "unknown"}}
        assert client.post("/api/v1/images/facets", json=scope).json()["total"] == 2
