"""An import's grouping phase (ADR-028, design/ingestion.md §5.8, design/variant-grouping.md
§3): images import ungrouped and unlisted, then the finished job's groups are identified
once, from paths and content, and minted.

Drives the real imports API and worker (``api`` fixture, ``drain()``). The grouping phase
runs inline where it is scheduled (root conftest), without embeddings: these tests exercise
the pHash renditions, names and folders. Twin maps are the same picture with and without a
faint drawn grid, in folders with different names, so only their content joins them.
"""

from __future__ import annotations

import io

import numpy as np
import pytest
from PIL import Image as PILImage

from backend.app.models import Image, ImageGroup, ImportGroup, ImportItem, ImportJob
from backend.app.services import ImageParser, variant_grouping
from backend.pipeline import group_jobs
from backend.pipeline.group_jobs import Outcome, Readiness, group_job

from .test_imports_api import BASE

GROUPS = "/api/v1/groups"
SEARCH = "/api/v1/search"


def picture(seed: int) -> PILImage.Image:
    """A detailed picture (24×32 blocks): its pHash is stable under a faint grid."""
    cells = np.random.default_rng(seed).integers(0, 255, (24, 32, 3), dtype=np.uint8)
    return PILImage.fromarray(cells).resize((320, 240), PILImage.Resampling.NEAREST)


def with_grid(image: PILImage.Image, step: int = 40) -> PILImage.Image:
    pixels = np.asarray(image).copy()
    pixels[:, ::step] = pixels[::step, :] = 20
    return PILImage.blend(image, PILImage.fromarray(pixels), 0.3)


def png(image: PILImage.Image) -> bytes:
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    return buf.getvalue()


DAY, NIGHT, KEEP = picture(1), picture(2), picture(3)
# Two folders of one map, gridless and gridded, named differently; and another map
TWINS = {
    "Czepeku/Lantern Pass/Lantern Pass Day.png": png(DAY),
    "Czepeku/Lantern Pass/Lantern Pass Night.png": png(NIGHT),
    "Czepeku/Moonlit Road/Moonlit Road Day.png": png(with_grid(DAY)),
    "Czepeku/Moonlit Road/Moonlit Road Night.png": png(with_grid(NIGHT)),
    "Czepeku/Sunken Keep/Sunken Keep.png": png(KEEP),
}


def manifest_and_seal(api, files, image_type="battlemap") -> tuple[str, dict[str, int]]:
    job_id = api.create("Pack", image_type=image_type)
    result = api.manifest(
        job_id, [{"relative_path": p, "size": len(d), "client_ref": p} for p, d in files.items()]
    )
    assert api.client.post(f"{BASE}/{job_id}/seal").status_code == 200
    return job_id, {i["relative_path"]: i["item_id"] for i in result["items"]}


def upload(api, job_id, ids, files, paths=None) -> None:
    for path in paths if paths is not None else files:
        assert api.put(job_id, ids[path], files[path]).status_code == 200


def import_files(api, files, image_type="battlemap") -> tuple[str, dict[str, int]]:
    job_id, ids = manifest_and_seal(api, files, image_type)
    upload(api, job_id, ids, files)
    return job_id, ids


def gallery_of(api, filename: str) -> int | None:
    with api.SessionLocal() as db:
        (group_id,) = db.query(Image.group_id).filter(Image.filename == filename).one()
        return group_id


def job(api, job_id) -> ImportJob:
    with api.SessionLocal() as db:
        row = db.get_one(ImportJob, job_id)
        db.expunge(row)
        return row


def listed_count(api) -> int:
    return api.client.get(f"{SEARCH}/facets").json()["total_images"]


def run(job_id: str, readiness: Readiness = Readiness.OFF) -> Outcome:
    return group_job(job_id, readiness=lambda: readiness)


# ---------------------------------------------------------------------------
# Importing: per image, ungrouped, unlisted
# ---------------------------------------------------------------------------


def test_a_seal_parses_files_without_grouping_them(api):
    job_id, _ = manifest_and_seal(api, TWINS)
    detail = api.detail(job_id)
    assert detail["groups"] == [] and detail["group_count"] == 0
    with api.SessionLocal() as db:
        assert db.query(ImportGroup).count() == 0
        items = db.query(ImportItem).filter_by(job_id=job_id).all()
        assert all(item.parsed and item.import_group_id is None for item in items)


def test_images_are_listed_nowhere_until_grouped(api, no_grouping):
    job_id, _ = import_files(api, TWINS)
    api.worker.drain()
    detail = api.detail(job_id)
    assert detail["status"] == "grouping" and detail["grouped_at"] is None
    assert detail["counts"]["done"] == 5
    assert detail["reviewable_group_ids"] == []
    with api.SessionLocal() as db:
        assert {(i.awaiting_grouping, i.group_id) for i in db.query(Image)} == {(True, None)}
    # Not in browsing, search, facets or the image list
    assert listed_count(api) == 0
    assert api.client.get(f"{SEARCH}/", params={"q": "Lantern"}).json()["total"] == 0
    assert api.client.get(f"{SEARCH}/", params={"q": ""}).json()["total"] == 0
    assert api.client.get(f"{SEARCH}/groups", params={"q": ""}).json()["total_groups"] == 0
    assert api.client.get("/api/v1/images/").json() == []

    assert run(job_id) == Outcome.GROUPED
    detail = api.detail(job_id)
    assert detail["status"] == "completed" and detail["grouped_at"] is not None
    assert listed_count(api) == 5
    assert api.client.get(f"{SEARCH}/", params={"q": ""}).json()["total"] == 5
    assert api.client.get(f"{SEARCH}/", params={"q": "Lantern"}).json()["total"] >= 2


# ---------------------------------------------------------------------------
# Identifying groups
# ---------------------------------------------------------------------------


def test_twin_folders_become_one_group(api):
    job_id, _ = import_files(api, TWINS)
    api.worker.drain()

    assert job(api, job_id).status == "completed"
    lantern = gallery_of(api, "Lantern Pass Day.png")
    assert lantern is not None
    for name in ("Lantern Pass Night.png", "Moonlit Road Day.png", "Moonlit Road Night.png"):
        assert gallery_of(api, name) == lantern
    assert gallery_of(api, "Sunken Keep.png") not in (None, lantern)

    detail = api.detail(job_id)
    assert detail["group_count"] == 2
    assert sorted(detail["reviewable_group_ids"]) == sorted(
        {lantern, gallery_of(api, "Sunken Keep.png")}
    )
    with api.SessionLocal() as db:
        group = db.get_one(ImageGroup, lantern)
        assert group.image_count == 4 and group.author == "Czepeku"
        assert {i.author for i in db.query(Image)} == {"Czepeku"}
        assert {i.awaiting_grouping for i in db.query(Image)} == {False}


def test_maps_go_through_the_walk_and_other_types_through_group_files(api, monkeypatch):
    seen: dict[str, list[str]] = {}
    walk, group_files = variant_grouping.group_with_content, ImageParser.group_files

    def spy_walk(files, features, params, parser, known_authors=()):
        seen.setdefault("walk", []).extend(f.path for f in files)
        return walk(files, features, params, parser, known_authors)

    def spy_group_files(self, paths, image_type="battlemap", known_authors=()):
        seen.setdefault(f"group_files:{image_type}", []).extend(paths)
        return group_files(self, paths, image_type, known_authors)

    monkeypatch.setattr(variant_grouping, "group_with_content", spy_walk)
    monkeypatch.setattr(ImageParser, "group_files", spy_group_files)
    # Two maps under Czepeku, so the vista (in neither map's folder) is grouped by type
    files = {
        "Czepeku/Keep/Keep Day.png": png(picture(4)),
        "Czepeku/Keep/Keep Night.png": png(picture(5)),
        "Czepeku/Fort/Fort Day.png": png(picture(11)),
        "Czepeku/Vistas/Keep Vista.png": png(picture(6)),
    }
    job_id = api.create("Mixed")
    result = api.manifest(
        job_id,
        [
            {"relative_path": p, "size": len(d), "image_type": "scene" if "Vista" in p else None}
            for p, d in files.items()
        ],
    )
    ids = {i["relative_path"]: i["item_id"] for i in result["items"]}
    assert api.client.post(f"{BASE}/{job_id}/seal").status_code == 200
    upload(api, job_id, ids, files)
    api.worker.drain()
    assert sorted(seen["walk"]) == [
        "Czepeku/Fort/Fort Day.png",
        "Czepeku/Keep/Keep Day.png",
        "Czepeku/Keep/Keep Night.png",
    ]
    assert seen["group_files:scene"] == ["Czepeku/Vistas/Keep Vista.png"]
    assert set(seen) == {"walk", "group_files:scene"}


def _typed_import(api, files: dict[str, tuple[bytes, str]]) -> str:
    """Import files with a fixed type each: path → (bytes, type)."""
    job_id = api.create("Pack")
    result = api.manifest(
        job_id,
        [{"relative_path": p, "size": len(d), "image_type": t} for p, (d, t) in files.items()],
    )
    ids = {i["relative_path"]: i["item_id"] for i in result["items"]}
    assert api.client.post(f"{BASE}/{job_id}/seal").status_code == 200
    for path, (data, _) in files.items():
        assert api.put(job_id, ids[path], data).status_code == 200
    api.worker.drain()
    return job_id


def test_scenes_and_tokens_join_the_map_of_their_folder(api):
    """A folder holding one map group: its scene art and tokens (imported as scenes) join it."""
    job_id = _typed_import(
        api,
        {
            "Czepeku/Keep/Keep Day.png": (png(picture(20)), "battlemap"),
            "Czepeku/Keep/Keep Night.png": (png(picture(21)), "battlemap"),
            "Czepeku/Keep/Keep Vista.png": (png(picture(22)), "scene"),
            "Czepeku/Keep/Tokens/Guard.png": (png(picture(23)), "scene"),
        },
    )
    keep = gallery_of(api, "Keep Day.png")
    for name in ("Keep Night.png", "Keep Vista.png", "Guard.png"):
        assert gallery_of(api, name) == keep
    (group,) = api.detail(job_id)["groups"]
    assert (group["map_count"], group["scene_count"]) == (2, 2)
    with api.SessionLocal() as db:
        assert {i.subgroup for i in db.query(Image)} == {None}


def test_a_scene_beside_two_maps_gets_a_group_of_its_own(api):
    job_id = _typed_import(
        api,
        {
            "Czepeku/Pack/Keep Day.png": (png(picture(24)), "battlemap"),
            "Czepeku/Pack/Fort Day.png": (png(picture(25)), "battlemap"),
            "Czepeku/Pack/Harbour Vista.png": (png(picture(26)), "scene"),
        },
    )
    keep, fort, vista = (
        gallery_of(api, n) for n in ("Keep Day.png", "Fort Day.png", "Harbour Vista.png")
    )
    assert len({keep, fort, vista}) == 3
    assert len(api.detail(job_id)["groups"]) == 3


def test_an_import_of_scenes_only_is_grouped_as_before(api):
    job_id = _typed_import(
        api,
        {
            "Czepeku/Vistas/Keep Vista Day.png": (png(picture(27)), "scene"),
            "Czepeku/Vistas/Keep Vista Night.png": (png(picture(28)), "scene"),
        },
    )
    assert [g["group_name"] for g in api.detail(job_id)["groups"]] == ["Vistas"]


def test_files_that_made_no_image_get_an_import_group_without_a_gallery_group(api):
    files = {
        **TWINS,
        "Czepeku/Broken Tower/Broken Tower.png": b"not an image",
    }
    job_id, ids = manifest_and_seal(api, files)
    upload(api, job_id, ids, TWINS)
    assert api.put(job_id, ids["Czepeku/Broken Tower/Broken Tower.png"], b"x").status_code == 200
    api.worker.drain()
    detail = api.detail(job_id)
    broken = next(g for g in detail["groups"] if g["group_name"] == "Broken Tower")
    assert broken["image_group_id"] is None and broken["counts"]["failed"] == 1
    assert broken["image_group_id"] not in detail["reviewable_group_ids"]


def test_a_unique_map_name_adds_to_its_existing_group(api):
    with api.SessionLocal() as db:
        db.add(ImageGroup(base_name="Sunken Keep", author="Czepeku"))
        db.commit()
        existing = db.query(ImageGroup).one().id
    job_id, _ = import_files(api, {"Czepeku/Sunken Keep/Sunken Keep.png": png(KEEP)})
    api.worker.drain()
    (group,) = api.detail(job_id)["groups"]
    assert group["merged_into_existing"] is True and group["image_group_id"] == existing
    assert gallery_of(api, "Sunken Keep.png") == existing

    # Undo keeps the group it added to
    assert api.client.delete(f"{BASE}/{job_id}").status_code == 200
    with api.SessionLocal() as db:
        assert db.get(ImageGroup, existing) is not None


def test_a_name_two_maps_share_never_picks_an_existing_group(api):
    files = {
        "Limithron/Pack 1/Coral Reef Shipwreck Battlemap.png": png(picture(7)),
        "Limithron/Pack 2/Coral Reef Shipwreck Battlemap.png": png(picture(8)),
    }
    with api.SessionLocal() as db:
        db.add(ImageGroup(base_name="Coral Reef Shipwreck", author="Limithron"))
        db.commit()
        existing = db.query(ImageGroup).one().id
    job_id, _ = import_files(api, files)
    api.worker.drain()
    groups = api.detail(job_id)["groups"]
    assert [g["group_name"] for g in groups] == ["Coral Reef Shipwreck"] * 2
    galleries = {g["image_group_id"] for g in groups}
    assert len(galleries) == 2 and existing not in galleries
    assert all(not g["merged_into_existing"] for g in groups)


def test_undo_removes_the_groups_it_minted(api):
    job_id, _ = import_files(api, TWINS)
    api.worker.drain()
    r = api.client.delete(f"{BASE}/{job_id}")
    assert r.status_code == 200 and r.json()["affected"] == 5
    with api.SessionLocal() as db:
        assert db.query(ImageGroup).count() == 0 and db.query(Image).count() == 0


def test_a_cancelled_import_still_groups_what_it_imported(api):
    job_id, ids = manifest_and_seal(api, TWINS)
    first = [p for p in TWINS if "Lantern" in p]
    upload(api, job_id, ids, TWINS, first)
    api.worker.drain()
    assert job(api, job_id).grouped_at is None  # the rest hasn't arrived
    api.client.post(f"{BASE}/{job_id}/cancel")
    api.worker.drain()  # the idle sweep picks it up
    after = job(api, job_id)
    assert after.status == "cancelled" and after.grouped_at is not None
    assert gallery_of(api, "Lantern Pass Day.png") == gallery_of(api, "Lantern Pass Night.png")
    assert listed_count(api) == 2


def test_grouping_waits_while_the_model_is_busy(api, no_grouping):
    job_id, _ = import_files(api, TWINS)
    api.worker.drain()
    assert run(job_id, Readiness.DEFER) == Outcome.DEFERRED
    assert job(api, job_id).status == "grouping"
    assert run(job_id) == Outcome.GROUPED
    assert run(job_id) == Outcome.NOT_DUE  # idempotent


def test_a_failed_write_leaves_the_job_grouping_and_it_is_grouped_again(
    api, no_grouping, monkeypatch
):
    job_id, _ = import_files(api, TWINS)
    api.worker.drain()
    write = group_jobs._write

    def broken(*args, **kwargs):
        write(*args, **kwargs)  # half the work done, then the crash
        raise RuntimeError("disk on fire")

    monkeypatch.setattr(group_jobs, "_write", broken)
    with pytest.raises(RuntimeError):
        run(job_id)
    with api.SessionLocal() as db:
        assert db.query(ImportGroup).count() == 0 and db.query(ImageGroup).count() == 0
        assert {i.awaiting_grouping for i in db.query(Image)} == {True}
    assert job(api, job_id).status == "grouping"

    monkeypatch.setattr(group_jobs, "_write", write)
    assert run(job_id) == Outcome.GROUPED
    assert gallery_of(api, "Moonlit Road Day.png") == gallery_of(api, "Lantern Pass Day.png")


def test_files_that_change_between_read_and_write_are_read_again(api, no_grouping, monkeypatch):
    job_id, _ = import_files(api, TWINS)
    api.worker.drain()
    read = group_jobs._read
    calls: list[int] = []

    def change_then_read(db, job_):
        files = read(db, job_)
        if not calls:
            with api.SessionLocal() as other:
                image = other.query(Image).filter(Image.filename == "Sunken Keep.png").one()
                from backend.app.services.deletion_service import delete_image_rows

                delete_image_rows(other, [image])
                other.commit()
        calls.append(len([f for f in files.files if f.image_id]))
        return files

    monkeypatch.setattr(group_jobs, "_read", change_then_read)
    assert run(job_id) == Outcome.GROUPED
    assert calls == [5, 4]
    with api.SessionLocal() as db:
        assert {i.awaiting_grouping for i in db.query(Image)} == {False}


# ---------------------------------------------------------------------------
# Late items
# ---------------------------------------------------------------------------


def test_a_late_image_joins_the_group_its_file_was_in(api):
    """A file that failed is retried after the import finished: its new image joins the
    group its file belonged to, and nothing already grouped moves."""
    files = {**TWINS, "Czepeku/Lantern Pass/Lantern Pass Dusk.png": png(picture(9))}
    late = "Czepeku/Lantern Pass/Lantern Pass Dusk.png"
    job_id, ids = manifest_and_seal(api, files)
    upload(api, job_id, ids, files, [p for p in files if p != late])
    assert api.put(job_id, ids[late], b"not an image").json()["state"] == "failed"
    api.worker.drain()
    before = {name: gallery_of(api, name) for name in ("Lantern Pass Day.png", "Sunken Keep.png")}
    with api.SessionLocal() as db:
        groups_before = db.query(ImageGroup).count()
        item = db.get_one(ImportItem, ids[late])
        late_group = item.import_group_id
    assert late_group is not None  # grouped by path although it made no image

    assert api.client.post(f"{BASE}/{job_id}/retry").json()["affected"] == 1
    assert job(api, job_id).grouped_at is None
    assert api.detail(job_id)["reviewable_group_ids"] == []  # until the late file is grouped
    upload(api, job_id, ids, files, [late])
    api.worker.drain()

    assert job(api, job_id).status == "completed"
    assert gallery_of(api, "Lantern Pass Dusk.png") == before["Lantern Pass Day.png"]
    assert {n: gallery_of(api, n) for n in before} == before
    with api.SessionLocal() as db:
        assert db.query(ImageGroup).count() == groups_before
        assert db.get_one(ImportItem, ids[late]).import_group_id == late_group


def test_a_late_image_whose_group_has_no_gallery_group_gets_a_new_one(api):
    files = {**TWINS, "Czepeku/Broken Tower/Broken Tower.png": png(picture(10))}
    late = "Czepeku/Broken Tower/Broken Tower.png"
    job_id, ids = manifest_and_seal(api, files)
    upload(api, job_id, ids, TWINS)
    assert api.put(job_id, ids[late], b"not an image").json()["state"] == "failed"
    api.worker.drain()
    api.client.post(f"{BASE}/{job_id}/retry")
    upload(api, job_id, ids, files, [late])
    api.worker.drain()

    tower = gallery_of(api, "Broken Tower.png")
    assert tower is not None and tower not in {gallery_of(api, p.split("/")[-1]) for p in TWINS}
    detail = api.detail(job_id)
    group = next(g for g in detail["groups"] if g["group_name"] == "Broken Tower")
    assert group["image_group_id"] == tower and tower in detail["reviewable_group_ids"]


def test_the_orphan_fixer_leaves_images_awaiting_grouping_alone(api, no_grouping, monkeypatch):
    from backend.pipeline import fix_orphaned_images

    job_id, _ = import_files(api, TWINS)
    api.worker.drain()
    monkeypatch.setattr("backend.pipeline.db.pipeline_db", lambda: _session_ctx(api), raising=False)
    monkeypatch.setattr(fix_orphaned_images, "pipeline_db", lambda: _session_ctx(api))
    fix_orphaned_images.fix_orphaned_images()
    with api.SessionLocal() as db:
        assert db.query(ImageGroup).count() == 0
        assert {i.group_id for i in db.query(Image)} == {None}


def _session_ctx(api):
    from contextlib import contextmanager

    @contextmanager
    def ctx():
        db = api.SessionLocal()
        try:
            yield db
            db.commit()
        finally:
            db.close()

    return ctx()
