"""Variant grouping in the import pipeline: the seal's walk and refinement (ADR-028,
design/variant-grouping.md §3, design/ingestion.md §5.8).

Drives the real imports API and worker (``api`` fixture, ``drain()``). Refinement runs
inline where it is scheduled (root conftest), without embeddings: these tests exercise the
pHash renditions, names and folders. Twin maps are the same picture with and without a
faint drawn grid, in folders with different names, so the seal (paths only) keeps them
apart and refinement (content) joins them.
"""

from __future__ import annotations

import io
from collections import Counter

import numpy as np
import pytest
from PIL import Image as PILImage

from backend.app.models import Image, ImageGroup, ImportGroup, ImportJob
from backend.app.services import ImageParser, variant_grouping
from backend.app.services.deletion_service import delete_image_rows
from backend.app.services.variant_grouping import GroupingFile
from backend.pipeline import refine_groups
from backend.pipeline.refine_groups import Outcome, Readiness, refine_job_groups

from .test_imports_api import BASE


def picture(seed: int) -> PILImage.Image:
    """A detailed picture (24×32 blocks): its pHash is stable under a faint grid."""
    cells = np.random.default_rng(seed).integers(0, 255, (24, 32, 3), dtype=np.uint8)
    return PILImage.fromarray(cells).resize((320, 240), PILImage.Resampling.NEAREST)


def with_grid(image: PILImage.Image, step: int = 40) -> PILImage.Image:
    lines = image.copy()
    pixels = np.asarray(lines).copy()
    pixels[:, ::step] = pixels[::step, :] = 20
    return PILImage.blend(image, PILImage.fromarray(pixels), 0.3)


def png(image: PILImage.Image) -> bytes:
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    return buf.getvalue()


DAY, NIGHT, KEEP = picture(1), picture(2), picture(3)
# Two folders of one map: gridless and gridded, named differently
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


def groups_by_folder(api, job_id) -> dict[str, set[int]]:
    """Each top-level map folder → the gallery groups its images are in."""
    with api.SessionLocal() as db:
        rows = db.query(Image.filename, Image.group_id).filter(Image.import_job_id == job_id)
        found: dict[str, set[int]] = {}
        for filename, group_id in rows:
            folder = next(p.split("/")[1] for p in TWINS if p.endswith(filename))
            found.setdefault(folder, set()).add(group_id)
        return found


def job(api, job_id) -> ImportJob:
    with api.SessionLocal() as db:
        row = db.get_one(ImportJob, job_id)
        db.expunge(row)
        return row


# ---------------------------------------------------------------------------
# Seal
# ---------------------------------------------------------------------------


def test_seal_groups_maps_by_the_tree_walk(api):
    files = {
        # Gridded and gridless folders of one map collapse; variants join by name
        "Czepeku/Forest Road Gridded/Forest Road Day.png": b"x",
        "Czepeku/Forest Road Gridless/Forest Road Day.png": b"x",
        "Czepeku/Forest Road Gridless/Forest Road Night.png": b"x",
        "Czepeku/Sunken Keep/Sunken Keep.png": b"x",
    }
    job_id, _ = manifest_and_seal(api, files)
    detail = api.detail(job_id)
    assert sorted((g["group_name"], g["author"]) for g in detail["groups"]) == [
        ("Forest Road", "Czepeku"),
        ("Sunken Keep", "Czepeku"),
    ]
    assert job(api, job_id).grouping_refined_at is None


def test_maps_go_through_the_walk_and_other_types_through_group_files(api, monkeypatch):
    seen: dict[str, list[str]] = {}
    walk, group_files = variant_grouping.group_by_paths, ImageParser.group_files

    def spy_walk(files, parser, params=None, known_authors=()):
        seen.setdefault("walk", []).extend(f.path for f in files)
        return walk(files, parser, params, known_authors)

    def spy_group_files(self, paths, image_type="battlemap", known_authors=()):
        seen.setdefault(f"group_files:{image_type}", []).extend(paths)
        return group_files(self, paths, image_type, known_authors)

    monkeypatch.setattr(variant_grouping, "group_by_paths", spy_walk)
    monkeypatch.setattr(ImageParser, "group_files", spy_group_files)
    job_id = api.create("Mixed")
    api.manifest(
        job_id,
        [
            {"relative_path": "Czepeku/Keep/Keep Day.png", "image_type": "battlemap"},
            {"relative_path": "Czepeku/Keep/Keep Night.png", "image_type": "auto"},
            {"relative_path": "Czepeku/Vistas/Keep Vista.png", "image_type": "scene"},
        ],
    )
    assert api.client.post(f"{BASE}/{job_id}/seal").status_code == 200
    assert sorted(seen["walk"]) == ["Czepeku/Keep/Keep Day.png", "Czepeku/Keep/Keep Night.png"]
    assert seen["group_files:scene"] == ["Czepeku/Vistas/Keep Vista.png"]
    assert set(seen) == {"walk", "group_files:scene"}


def test_a_map_with_a_unique_name_adds_to_its_existing_group(api):
    with api.SessionLocal() as db:
        db.add(ImageGroup(base_name="Sunken Keep", author="Czepeku"))
        db.commit()
    job_id, _ = manifest_and_seal(api, {"Czepeku/Sunken Keep/Sunken Keep.png": b"x"})
    (group,) = api.detail(job_id)["groups"]
    assert group["merged_into_existing"] is True


def test_a_name_two_maps_share_never_picks_an_existing_group(api, no_grouping_refinement):
    """The seal can leave one map split under one name (it is refinement's to join): such
    a name says nothing about which map it is, so neither part adds to an existing group,
    nor do the parts collapse into one gallery group by name."""
    shipwreck = picture(7)
    files = {
        "Limithron/Pack 1/Coral Reef Shipwreck Battlemap.png": png(shipwreck),
        "Limithron/Pack 2/Coral Reef Shipwreck Battlemap.png": png(with_grid(shipwreck)),
    }
    with api.SessionLocal() as db:
        existing = ImageGroup(base_name="Coral Reef Shipwreck", author="Limithron")
        db.add(existing)
        db.commit()
        existing_id = existing.id

    job_id, ids = manifest_and_seal(api, files)
    planned = api.detail(job_id)["groups"]
    assert [g["group_name"] for g in planned] == ["Coral Reef Shipwreck"] * 2
    assert all(not g["merged_into_existing"] and g["image_group_id"] is None for g in planned)

    upload(api, job_id, ids, files)
    api.worker.drain()  # refinement is run by hand below
    with api.SessionLocal() as db:
        gallery = {g.image_group_id for g in db.query(ImportGroup).filter_by(job_id=job_id)}
        assert len(gallery) == 2 and existing_id not in gallery  # two new groups

    assert refine_job_groups(job_id, readiness=lambda: Readiness.OFF) == Outcome.REFINED
    with api.SessionLocal() as db:
        gallery = {g.image_group_id for g in db.query(ImportGroup).filter_by(job_id=job_id)}
        assert len(gallery) == 1 and existing_id not in gallery  # one map, joined by content
        assert db.get(ImageGroup, existing_id).image_count == 0  # untouched


# ---------------------------------------------------------------------------
# Refinement
# ---------------------------------------------------------------------------


def test_refinement_merges_twin_folders_the_seal_kept_apart(api):
    job_id, ids = manifest_and_seal(api, TWINS)
    names = sorted(g["group_name"] for g in api.detail(job_id)["groups"])
    assert names == ["Lantern Pass", "Moonlit Road", "Sunken Keep"]  # paths alone

    upload(api, job_id, ids, TWINS)
    api.worker.drain()

    folders = groups_by_folder(api, job_id)
    assert folders["Lantern Pass"] == folders["Moonlit Road"]  # one gallery group now
    assert len(folders["Lantern Pass"]) == 1
    assert folders["Sunken Keep"].isdisjoint(folders["Lantern Pass"])
    (survivor,) = folders["Lantern Pass"]

    detail = api.detail(job_id)
    assert detail["grouping_refined_at"] is not None
    # Both import groups resolve to the survivor; it is reviewable once, in import order
    by_name = {g["group_name"]: g["image_group_id"] for g in detail["groups"]}
    assert by_name["Lantern Pass"] == by_name["Moonlit Road"] == survivor
    assert sorted(detail["reviewable_group_ids"]) == sorted({survivor, by_name["Sunken Keep"]})
    assert detail["groups_reviewable"] == 2
    with api.SessionLocal() as db:
        group = db.get_one(ImageGroup, survivor)
        assert group.image_count == 4 and group.edited_at is None
        assert {i.author for i in db.query(Image).filter_by(group_id=survivor)} == {"Czepeku"}
        assert db.query(ImageGroup).count() == 2  # the merged group is gone


def test_an_edited_group_is_never_touched(api):
    job_id, ids = manifest_and_seal(api, TWINS)
    first = [p for p in TWINS if "Moonlit Road" not in p]
    upload(api, job_id, ids, TWINS, first)
    api.worker.drain()  # not finished: Moonlit Road awaits its files
    (lantern,) = groups_by_folder(api, job_id)["Lantern Pass"]
    edit = {"base_name": "My Pass", "author": "Czepeku", "images": [], "delete_image_ids": []}
    assert api.client.put(f"/api/v1/groups/{lantern}", json=edit).status_code == 200

    upload(api, job_id, ids, TWINS, [p for p in TWINS if p not in first])
    api.worker.drain()

    folders = groups_by_folder(api, job_id)
    assert folders["Lantern Pass"] == {lantern}
    assert folders["Moonlit Road"] != {lantern}
    assert job(api, job_id).grouping_refined_at is not None
    with api.SessionLocal() as db:
        assert db.get_one(ImageGroup, lantern).base_name == "My Pass"


def test_a_group_the_import_added_to_is_never_touched(api):
    with api.SessionLocal() as db:
        db.add(ImageGroup(base_name="Lantern Pass", author="Czepeku"))
        db.commit()
    job_id, _ = import_files(api, TWINS)
    api.worker.drain()

    detail = api.detail(job_id)
    lantern = next(g for g in detail["groups"] if g["group_name"] == "Lantern Pass")
    assert lantern["merged_into_existing"] is True
    folders = groups_by_folder(api, job_id)
    assert folders["Lantern Pass"] == {lantern["image_group_id"]}
    assert folders["Moonlit Road"] != folders["Lantern Pass"]  # not merged into it
    assert detail["grouping_refined_at"] is not None


def test_undo_after_refinement_removes_the_jobs_groups(api):
    job_id, _ = import_files(api, TWINS)
    api.worker.drain()
    assert len(groups_by_folder(api, job_id)["Lantern Pass"]) == 1
    r = api.client.delete(f"{BASE}/{job_id}")
    assert r.status_code == 200 and r.json()["affected"] == 5
    with api.SessionLocal() as db:
        assert db.query(ImageGroup).count() == 0
        assert db.query(Image).count() == 0


def test_a_reopened_import_is_refined_again(api):
    """A file that failed and is retried re-opens the import: once it finishes, its
    grouping is refined again with the new image."""
    keep_twin = "Czepeku/Drowned Hall/Drowned Hall.png"
    files = {**TWINS, keep_twin: png(with_grid(KEEP))}
    job_id, ids = manifest_and_seal(api, files)
    upload(api, job_id, ids, files, [p for p in files if p != keep_twin])
    # The twin arrives damaged: it fails, and the import finishes without it
    assert api.put(job_id, ids[keep_twin], b"not an image").json()["state"] == "failed"
    api.worker.drain()
    first = job(api, job_id)
    assert first.status == "completed" and first.grouping_refined_at is not None
    with api.SessionLocal() as db:
        assert db.query(ImageGroup).count() == 2  # Lantern Pass + Moonlit Road, Sunken Keep

    assert api.client.post(f"{BASE}/{job_id}/retry").json()["affected"] == 1
    assert job(api, job_id).grouping_refined_at is None  # re-opened
    assert api.detail(job_id)["reviewable_group_ids"] == []
    upload(api, job_id, ids, files, [keep_twin])  # chosen again, intact this time
    api.worker.drain()

    again = job(api, job_id)
    assert again.status == "completed" and again.grouping_refined_at is not None
    with api.SessionLocal() as db:
        keep_groups = {
            group_id
            for (group_id,) in db.query(Image.group_id).filter(
                Image.filename.in_(("Sunken Keep.png", "Drowned Hall.png"))
            )
        }
        assert len(keep_groups) == 1  # the new image joined its twin
        assert db.query(ImageGroup).count() == 2


def test_the_editor_waits_for_refinement(api, no_grouping_refinement):
    job_id, _ = import_files(api, TWINS)
    api.worker.drain()
    detail = api.detail(job_id)
    assert detail["status"] == "completed" and detail["grouping_refined_at"] is None
    assert detail["reviewable_group_ids"] == [] and detail["groups_reviewable"] == 0
    summary = next(j for j in api.client.get(BASE).json()["jobs"] if j["id"] == job_id)
    assert summary["groups_reviewable"] == 0 and summary["grouping_refined_at"] is None
    etag = api.client.get(BASE).headers["etag"]

    assert refine_job_groups(job_id, readiness=lambda: Readiness.OFF) == Outcome.REFINED
    detail = api.detail(job_id)
    assert detail["grouping_refined_at"] is not None
    assert len(detail["reviewable_group_ids"]) == 2
    # The list's ETag changes, so pollers see the refinement
    assert api.client.get(BASE, headers={"If-None-Match": etag}).status_code == 200


def test_refinement_is_idempotent(api):
    job_id, _ = import_files(api, TWINS)
    api.worker.drain()
    before = groups_by_folder(api, job_id)
    assert refine_job_groups(job_id, readiness=lambda: Readiness.OFF) == Outcome.NOT_DUE

    with api.SessionLocal() as db:  # as if it had never been refined
        db.get_one(ImportJob, job_id).grouping_refined_at = None
        db.commit()
    assert refine_job_groups(job_id, readiness=lambda: Readiness.OFF) == Outcome.REFINED
    assert groups_by_folder(api, job_id) == before


def test_images_deleted_between_compute_and_apply_are_skipped(
    api, no_grouping_refinement, monkeypatch
):
    job_id, _ = import_files(api, TWINS)
    api.worker.drain()
    apply = refine_groups._apply_if_current

    def delete_then_apply(files, proposals):
        with api.SessionLocal() as db:
            gone = db.query(Image).filter(Image.filename == "Moonlit Road Day.png").all()
            delete_image_rows(db, gone)
            db.commit()
        return apply(files, proposals)

    monkeypatch.setattr(refine_groups, "_apply_if_current", delete_then_apply)
    assert refine_job_groups(job_id, readiness=lambda: Readiness.OFF) == Outcome.REFINED
    folders = groups_by_folder(api, job_id)
    assert folders["Lantern Pass"] == folders["Moonlit Road"]  # the rest still merged
    with api.SessionLocal() as db:
        (survivor,) = folders["Lantern Pass"]
        assert db.get_one(ImageGroup, survivor).image_count == 3


def test_a_group_edited_between_compute_and_apply_is_left_alone(
    api, no_grouping_refinement, monkeypatch
):
    job_id, _ = import_files(api, TWINS)
    api.worker.drain()
    (moonlit,) = groups_by_folder(api, job_id)["Moonlit Road"]
    apply = refine_groups._apply_if_current

    def edit_then_apply(files, proposals):
        edit = {"base_name": "Moonlit", "author": "Czepeku", "images": [], "delete_image_ids": []}
        assert api.client.put(f"/api/v1/groups/{moonlit}", json=edit).status_code == 200
        return apply(files, proposals)

    monkeypatch.setattr(refine_groups, "_apply_if_current", edit_then_apply)
    assert refine_job_groups(job_id, readiness=lambda: Readiness.OFF) == Outcome.REFINED
    folders = groups_by_folder(api, job_id)
    assert folders["Moonlit Road"] == {moonlit} != folders["Lantern Pass"]


def test_an_undo_between_compute_and_apply_applies_nothing(
    api, no_grouping_refinement, monkeypatch
):
    job_id, _ = import_files(api, TWINS)
    api.worker.drain()
    apply = refine_groups._apply_if_current

    def undo_then_apply(files, proposals):
        assert api.client.delete(f"{BASE}/{files.scope.job_id}").status_code == 200
        return apply(files, proposals)

    monkeypatch.setattr(refine_groups, "_apply_if_current", undo_then_apply)
    assert refine_job_groups(job_id, readiness=lambda: Readiness.OFF) == Outcome.NOT_DUE
    with api.SessionLocal() as db:
        assert db.query(ImageGroup).count() == 0


def test_refinement_waits_while_the_model_is_busy(api, no_grouping_refinement):
    job_id, _ = import_files(api, TWINS)
    api.worker.drain()
    assert refine_job_groups(job_id, readiness=lambda: Readiness.DEFER) == Outcome.DEFERRED
    assert job(api, job_id).grouping_refined_at is None
    assert len(groups_by_folder(api, job_id)["Moonlit Road"]) == 1


def test_an_import_without_maps_is_just_marked_refined(api):
    files = {"Czepeku/Vistas/Keep Vista.png": png(KEEP)}
    job_id, _ = import_files(api, files, image_type="scene")
    api.worker.drain()
    detail = api.detail(job_id)
    assert detail["grouping_refined_at"] is not None
    assert len(detail["reviewable_group_ids"]) == 1


def test_an_import_finished_without_a_batch_is_refined_by_the_sweep(api):
    """Cancelled before anything was uploaded: no batch runs, the worker's idle sweep
    refines it."""
    job_id, _ = manifest_and_seal(api, TWINS)
    api.client.post(f"{BASE}/{job_id}/cancel")
    assert job(api, job_id).grouping_refined_at is None
    api.worker.drain()
    assert job(api, job_id).grouping_refined_at is not None


def test_merge_reasons_are_logged(api, caplog):
    import logging

    with caplog.at_level(logging.INFO, logger="backend.pipeline.refine_groups"):
        job_id, _ = import_files(api, TWINS)
        api.worker.drain()
    (line,) = [r.getMessage() for r in caplog.records if "Refined grouping" in r.getMessage()]
    assert "1 merge(s) of 1 group(s)" in line and "rendition" in line
    assert Counter(groups_by_folder(api, job_id)["Lantern Pass"]).total() == 1


def test_a_plan_made_before_the_lock_is_made_again_if_the_files_changed(api):
    """The seal plans outside the write lock; files added meanwhile still get a group."""
    from backend.pipeline import ingest_queue as q

    job_id = api.create("Pack")
    api.manifest(job_id, [{"relative_path": "Czepeku/Keep/Keep Day.png"}])
    with api.SessionLocal() as db:
        planned = q.compute_plan(db, job_id)
        q.add_manifest_items(
            db, db.get_one(ImportJob, job_id), [q.ManifestEntry("Czepeku/Keep/Keep Night.png")]
        )
        q.apply_plan(db, job_id, planned)
        db.commit()
        items = db.query(q.ImportItem).filter_by(job_id=job_id).all()
        assert all(item.import_group_id is not None for item in items)
        assert len({item.import_group_id for item in items}) == 1


def test_a_scope_whose_images_changed_meanwhile_is_read_again(
    api, no_grouping_refinement, monkeypatch
):
    """Its images changed between compute and apply (it re-opened and finished again, or an
    image was deleted): the plan is stale, so the files are read and grouped again."""
    job_id, _ = import_files(api, TWINS)
    api.worker.drain()
    apply = refine_groups._apply_if_current
    seen: list[int] = []

    def change_then_apply(files, proposals):
        if not seen:
            with api.SessionLocal() as db:
                gone = db.query(Image).filter(Image.filename == "Sunken Keep.png").all()
                delete_image_rows(db, gone)
                db.commit()
        seen.append(len(files.image_of))
        return apply(files, proposals)

    monkeypatch.setattr(refine_groups, "_apply_if_current", change_then_apply)
    assert refine_job_groups(job_id, readiness=lambda: Readiness.OFF) == Outcome.REFINED
    assert seen == [5, 4]
    folders = groups_by_folder(api, job_id)
    assert folders["Lantern Pass"] == folders["Moonlit Road"]


# ---------------------------------------------------------------------------
# Partitions: large imports are refined top-level folder by top-level folder
# ---------------------------------------------------------------------------

# Two top-level folders; Moonlit Road (in the second) is the gridded twin of Lantern Pass
PARTITIONED = {
    "Czepeku/Lantern Pass/Lantern Pass Day.png": png(DAY),
    "Czepeku/Lantern Pass/Lantern Pass Night.png": png(NIGHT),
    "Czepeku/Sunken Keep/Sunken Keep.png": png(KEEP),
    "Patreon Extras/Moonlit Road/Moonlit Road Day.png": png(with_grid(DAY)),
    "Patreon Extras/Moonlit Road/Moonlit Road Night.png": png(with_grid(NIGHT)),
    "Patreon Extras/Old Mill/Old Mill.png": png(picture(4)),
}
FIRST = [p for p in PARTITIONED if p.startswith("Czepeku/")]
SECOND = [p for p in PARTITIONED if p not in FIRST]


@pytest.fixture
def partitioned(api, monkeypatch):
    """Imports of more than two map files are refined partition by partition."""
    from backend.pipeline import ingest_queue as q

    monkeypatch.setattr(q, "PARTITION_MIN_MAP_FILES", 2)
    return api


def gallery_of(api, filename: str) -> int:
    with api.SessionLocal() as db:
        (group_id,) = db.query(Image.group_id).filter(Image.filename == filename).one()
        return group_id


def stamps(api, job_id) -> dict[str, bool]:
    """Each import group's name → whether its partition is refined."""
    with api.SessionLocal() as db:
        return {
            g.group_name: g.grouping_refined_at is not None
            for g in db.query(ImportGroup).filter_by(job_id=job_id)
        }


def test_a_large_import_is_sealed_with_partitions(partitioned):
    job_id, _ = manifest_and_seal(partitioned, PARTITIONED)
    with partitioned.SessionLocal() as db:
        keys = {
            g.group_name: g.partition_key for g in db.query(ImportGroup).filter_by(job_id=job_id)
        }
    assert keys == {
        "Lantern Pass": "czepeku",
        "Sunken Keep": "czepeku",
        "Moonlit Road": "patreon extras",
        "Old Mill": "patreon extras",
    }


def test_a_small_import_has_no_partitions(api):
    job_id, _ = import_files(api, TWINS)
    with api.SessionLocal() as db:
        assert {g.partition_key for g in db.query(ImportGroup).filter_by(job_id=job_id)} == {None}
    api.worker.drain()
    assert set(stamps(api, job_id).values()) == {True}  # stamped by the whole-job pass


def test_a_partition_is_refined_and_reviewable_before_the_import_finishes(partitioned):
    api = partitioned
    job_id, ids = manifest_and_seal(api, PARTITIONED)
    upload(api, job_id, ids, PARTITIONED, FIRST)
    api.worker.drain()

    detail = api.detail(job_id)
    assert detail["status"] == "active"  # the second folder hasn't arrived
    assert job(api, job_id).grouping_refined_at is None
    assert stamps(api, job_id) == {
        "Lantern Pass": True,
        "Sunken Keep": True,
        "Moonlit Road": False,
        "Old Mill": False,
    }
    first_groups = {gallery_of(api, "Lantern Pass Day.png"), gallery_of(api, "Sunken Keep.png")}
    assert set(detail["reviewable_group_ids"]) == first_groups
    assert detail["grouping_refined_at"] is not None  # the gallery refreshes on it


def test_the_final_pass_merges_twins_across_partitions(partitioned):
    api = partitioned
    job_id, ids = manifest_and_seal(api, PARTITIONED)
    upload(api, job_id, ids, PARTITIONED, FIRST)
    api.worker.drain()
    lantern = gallery_of(api, "Lantern Pass Day.png")
    assert gallery_of(api, "Lantern Pass Night.png") == lantern

    upload(api, job_id, ids, PARTITIONED, SECOND)
    api.worker.drain()
    assert job(api, job_id).grouping_refined_at is not None
    # The partition passes couldn't see across folders; the whole-job pass joins the twin
    assert gallery_of(api, "Moonlit Road Day.png") == gallery_of(api, "Lantern Pass Day.png")
    assert gallery_of(api, "Old Mill.png") != gallery_of(api, "Sunken Keep.png")
    detail = api.detail(job_id)
    assert len(detail["reviewable_group_ids"]) == 3
    assert set(stamps(api, job_id).values()) == {True}


def test_reopening_clears_only_the_reopened_partition(partitioned):
    api = partitioned
    job_id, ids = manifest_and_seal(api, PARTITIONED)
    damaged = "Patreon Extras/Old Mill/Old Mill.png"
    upload(api, job_id, ids, PARTITIONED, [p for p in PARTITIONED if p != damaged])
    assert api.put(job_id, ids[damaged], b"not an image").json()["state"] == "failed"
    api.worker.drain()
    assert job(api, job_id).grouping_refined_at is not None
    assert set(stamps(api, job_id).values()) == {True}

    assert api.client.post(f"{BASE}/{job_id}/retry").json()["affected"] == 1
    assert job(api, job_id).grouping_refined_at is None
    assert stamps(api, job_id) == {
        "Lantern Pass": True,  # its partition is untouched (and holds the merged twin)
        "Sunken Keep": True,
        "Moonlit Road": False,
        "Old Mill": False,
    }
    detail = api.detail(job_id)
    keep = gallery_of(api, "Sunken Keep.png")
    assert keep in detail["reviewable_group_ids"]
    # The twins' group is fed by a re-opened import group too: held back
    assert gallery_of(api, "Lantern Pass Day.png") not in detail["reviewable_group_ids"]

    upload(api, job_id, ids, PARTITIONED, [damaged])
    api.worker.drain()
    assert job(api, job_id).grouping_refined_at is not None
    assert set(stamps(api, job_id).values()) == {True}


def test_finding_due_partitions_is_one_query_whatever_their_number(
    partitioned, no_grouping_refinement, query_counter
):
    api = partitioned
    counts = []
    for folders in (2, 6):
        files = {
            f"Maker {chr(65 + f)}/{name}/{name} {variant}.png": b"x"
            for f in range(folders)
            for name in ("Amber Keep", "Brook Fort")
            for variant in ("Day", "Night")
        }
        job_id, _ = manifest_and_seal(api, files)
        with api.SessionLocal() as db:
            group_ids = [g.id for g in db.query(ImportGroup).filter_by(job_id=job_id)]
            with query_counter as q:
                assert refine_groups.due_partitions(db, [job_id], group_ids) == []
            counts.append(q.count)
            with query_counter as q:
                refine_groups.due_partitions(db)
            counts.append(q.count)
    assert counts == [1, 1, 1, 1], counts


def test_a_partition_pass_names_files_in_the_whole_imports_context(partitioned, monkeypatch):
    """``Mzx`` is a house prefix only across the whole import (the global strip needs many
    files). A walk over the small partition alone would keep it and join Forest Road with
    Forest Cave on the shared base "mzx forest", a path join the seal withheld. The partition
    pass walks the whole import, so it names and joins exactly as the seal did."""
    api = partitioned
    small = {
        f"Mzx Bundle/Mzx {name} {variant}.png": png(picture(seed * 2 + v))
        for seed, name in enumerate(("Forest Road", "Forest Cave"), start=20)
        for v, variant in enumerate(("Day", "Night"))
    }
    words = "Amber Brook Cedar Dune Ember Fjord Glade Harbor Iris Jade Keep Lagoon Marsh"
    places = [
        "Tavern",
        "Crypt",
        "Temple",
        "Bridge",
        "Cave",
        "Fort",
        "Mill",
        "Tower",
        "Market",
        "Docks",
        "Ruins",
        "Camp",
    ]
    big = {
        f"Mzx Collection/{w} {places[i % 12]}/Mzx {w} {places[i % 12]} {v}.png": b"x"
        for i, w in enumerate(words.split())
        for v in ("Day", "Night")
    }
    files = {**small, **big}
    parser = ImageParser()
    alone = variant_grouping.group_by_paths(
        [GroupingFile(i, p) for i, p in enumerate(small)], parser
    )
    assert len(alone.groups) == 1  # the trap: on its own, the bundle is one group

    plans: list[refine_groups.MergePlan] = []
    plan_merges = refine_groups.plan_merges

    def spy(proposals, membership):
        plans.append(plan_merges(proposals, membership))
        return plans[-1]

    monkeypatch.setattr(refine_groups, "plan_merges", spy)
    job_id, ids = manifest_and_seal(api, files)
    assert len({g["group_name"] for g in api.detail(job_id)["groups"]}) >= 2
    upload(api, job_id, ids, files, list(small))
    api.worker.drain()

    assert stamps(api, job_id)["Forest Road"] and stamps(api, job_id)["Forest Cave"]
    assert gallery_of(api, "Mzx Forest Road Day.png") != gallery_of(api, "Mzx Forest Cave Day.png")
    assert plans and all(not p.conflicted and not p.merges for p in plans)
