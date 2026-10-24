"""The grouping phase of an import: identify its groups once, from paths and content, and
mint them (ADR-028, design/ingestion.md §5.8, design/variant-grouping.md §3).

While a job imports, its committed images have no group (``Image.awaiting_grouping``) and
are listed nowhere. When the job has nothing open (every file done, a duplicate, failed or
skipped), its status is ``grouping``: ``group_job`` runs the grouping once over all of the
job's files, by their detected type, and assigns the images in one write transaction:

- **maps** (battlemaps, and Auto items the image-type head called maps, plus files of a map
  type that made no image) go through ``variant_grouping.group_with_content`` with the
  images' content features (pHash renditions, edge maps, embeddings);
- **scenes** (everything else: Auto skips tokens and assets, and Include imports them as maps
  or scenes) are attached to a map group or grouped among themselves
  (``variant_grouping.group_scenes``).

Each resulting group becomes an ``ImportGroup`` of the job (the report, Undo, the review
editor and the sorted-out lists work from these) and, if any of its files became an image,
a gallery group: an existing one with the same ``(name, author)`` when the name identifies
the map and is unique in the import, else a new one. Then the job is ``completed``. The
pipeline never changes these groups again.

**Late items** (retry, include, import as copy after the job finished) re-open the job;
when it has finished again it is grouped again. The walk covers every file of the job, for
context, but only images still awaiting a group are placed, and nothing already grouped
moves: a file keeps the import group it had, and its new image joins that group's gallery
group; if it has none, the gallery group of this job that the file's group overlaps, else a
new one (``plan_grouping``, pure).

Three steps, so the write lock is held briefly: read (no lock), compute (no lock), and
write (one ``write_session``), which first checks that nothing changed since the read
(else reads again). A crash rolls the write back; the job stays ``grouping`` and is grouped
again.

**Model availability.** While the embedding model is loading or switching (the worker is
held, or the model is loading) grouping waits: the job stays ``grouping`` and a later sweep
runs it. With no model at all it runs without embeddings. Without a calibration for the
active encoder the embedding rules are off (``grouping_calibration``). Groups are minted once,
so a run first embeds the job's images that have no vector (a failed write is otherwise only
repaired by reconciliation, at startup and daily), and while many still have none (the index
unreadable) waits, for a few minutes at most, then groups without them.

Scheduling (``GroupingScheduler``): every batch (``process_batch``), every idle wake of the
worker and the API actions that can settle a job sweep every job due; JobRunner work lost on
restart is found by the first sweep. One run per job at a time. A run that raises is retried
by later sweeps; after ``_MAX_FAILED_RUNS`` the job is grouped by its paths alone, so its
images don't stay hidden.
"""

from __future__ import annotations

import logging
import math
import threading
import time
from collections import Counter
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from enum import StrEnum
from pathlib import PurePosixPath

import numpy as np
from sqlalchemy import func, insert, select, update
from sqlalchemy.orm import Session

from backend.app.models import Image, ImageGroup, ImportGroup, ImportItem, ImportJob, Tag
from backend.app.services import ImageParser, variant_grouping
from backend.app.services import ingest_state as st
from backend.app.services.image_parser import build_search_text
from backend.app.services.linked_files import chunks
from backend.app.services.variant_grouping import (
    ContentFeatures,
    EmbeddingThresholds,
    GroupingFile,
    GroupingParams,
    ProposedGroup,
)

from .grouping_features import load_grouping_features
from .ingest_queue import (
    BATTLEMAP,
    SCENE,
    _session,
    build_parser,
    existing_groups,
    has_open_items,
    in_map_bucket,
    job_counts,
    known_authors,
    recompute_job_status,
    utcnow,
    write_session,
)

logger = logging.getLogger(__name__)

_EMBEDDING_CHUNK = 500  # ids per LanceDB lookup
MAPS = BATTLEMAP  # the bucket grouped by the tree walk
UNKNOWN_AUTHOR = "Unknown"
# The map and scene groupings of a run: their decisions are logged at DEBUG
_Debug = variant_grouping.Grouping[int] | variant_grouping.SceneGrouping[int]


# Planning (pure)


@dataclass(frozen=True)
class Proposal:
    """One group the grouping found: its files (item ids), name and author, the files'
    sub-group labels, and whether its name may pick an existing gallery group."""

    items: tuple[int, ...]
    name: str
    author: str
    subgroups: Mapping[int, str | None] = field(default_factory=dict)
    match_existing: bool = True


@dataclass(frozen=True)
class JobState:
    """The job as the plan is made against it.

    - ``import_group_of``: item → its import group, for items that have one (a late run);
    - ``pending``: item → its image awaiting a group;
    - ``placed``: item → the gallery group of its image, for this job's grouped images;
    - ``gallery_of``: import group → its gallery group (None: none, or deleted since);
    - ``group_names``: import group → its (name, author);
    - ``merged``: gallery groups this job adds to but didn't create;
    - ``existing``: (name, author) → a gallery group of the library with that name.
    """

    import_group_of: Mapping[int, int] = field(default_factory=dict)
    pending: Mapping[int, int] = field(default_factory=dict)
    placed: Mapping[int, int] = field(default_factory=dict)
    gallery_of: Mapping[int, int | None] = field(default_factory=dict)
    group_names: Mapping[int, tuple[str, str]] = field(default_factory=dict)
    merged: frozenset[int] = frozenset()
    existing: Mapping[tuple[str, str], int] = field(default_factory=dict)


@dataclass(frozen=True)
class NewImportGroup:
    key: int  # negative: a stand-in for the id the row gets
    name: str
    author: str
    sort_order: int


@dataclass(frozen=True)
class GalleryChoice:
    """Where an import group's new images go: ``group_id`` (an existing gallery group), or
    a new gallery group named ``name`` by ``author`` when ``group_id`` is None."""

    group_id: int | None
    merged: bool  # the import group adds to a group it didn't create
    name: str = ""
    author: str = ""


@dataclass(frozen=True)
class GroupingPlan:
    new_import_groups: list[NewImportGroup]
    item_groups: dict[int, int]  # item → import group (new keys negative), items without one
    galleries: dict[int, GalleryChoice]  # import group → gallery, for those taking images
    images: dict[int, tuple[int, str | None]]  # pending image → (import group, subgroup)


def plan_grouping(
    proposals: Sequence[Proposal], state: JobState, first_sort_order: int = 0
) -> GroupingPlan:
    """Which import group each file and gallery group each awaiting image goes to.

    - A proposal whose files have no import group gets a new one. If some have one (a late
      run), the others join the most common of those (ties: the lowest id); files never
      change import group.
    - An awaiting image goes to its file's import group's gallery group. An import group
      without one takes, in order: the gallery group of this job that already holds most
      images of its proposal (it overlaps it); for a new import group whose name may match,
      an existing gallery group with its ``(name, author)``; else a new gallery group with
      its name.
    - Images already grouped never move.
    """
    new_groups: list[NewImportGroup] = []
    item_groups: dict[int, int] = {}
    galleries: dict[int, GalleryChoice] = {}
    images: dict[int, tuple[int, str | None]] = {}
    may_match: dict[int, bool] = {}  # new import group → its name may pick an existing group
    names = dict(state.group_names)

    for proposal in proposals:
        held = Counter(
            state.import_group_of[i] for i in proposal.items if i in state.import_group_of
        )
        if held:
            target = min(held, key=lambda g: (-held[g], g))
        else:
            target = -(len(new_groups) + 1)
            new_groups.append(
                NewImportGroup(
                    target, proposal.name, proposal.author, first_sort_order + len(new_groups)
                )
            )
            names[target] = (proposal.name, proposal.author)
            may_match[target] = proposal.match_existing
        for item in proposal.items:
            if item not in state.import_group_of:
                item_groups[item] = target
        overlap = Counter(state.placed[i] for i in proposal.items if i in state.placed)
        for item in proposal.items:
            image = state.pending.get(item)
            if image is None:
                continue
            group = state.import_group_of.get(item, target)
            images[image] = (group, proposal.subgroups.get(item))
            if group not in galleries:
                name = names.get(group, (proposal.name, proposal.author))
                galleries[group] = _gallery_for(
                    group, name, may_match.get(group, False), overlap, state
                )
    return GroupingPlan(new_groups, item_groups, galleries, images)


def _gallery_for(
    group: int,
    name: tuple[str, str],
    may_match: bool,
    overlap: Counter[int],
    state: JobState,
) -> GalleryChoice:
    current = state.gallery_of.get(group)
    if current is not None:
        return GalleryChoice(current, current in state.merged)
    if overlap:
        adopted = min(overlap, key=lambda g: (-overlap[g], g))
        return GalleryChoice(adopted, adopted in state.merged)
    existing = state.existing.get(name) if may_match else None
    if existing is not None:
        return GalleryChoice(existing, True)
    return GalleryChoice(None, False, *name)


# Model availability


class Readiness(StrEnum):
    USE = "use"  # embeddings may be used (if the encoder is calibrated)
    OFF = "off"  # no model: group without embeddings
    DEFER = "defer"  # the model is loading or switching: try again later


def embedding_readiness() -> Readiness:
    """Whether grouping can run now, and with embeddings (module docstring)."""
    from backend.app.services.clip_service import get_clip_unavailable_reason, is_clip_loading

    from .ingest_worker import get_ingest_worker

    if get_ingest_worker().is_held() or is_clip_loading():
        return Readiness.DEFER
    if get_clip_unavailable_reason() is not None:
        return Readiness.OFF
    return Readiness.USE


# Read


@dataclass(frozen=True)
class _File:
    item_id: int
    path: str
    bucket: str  # MAPS, or another image type grouped by group_files
    import_group_id: int | None
    image_id: int | None  # this job's image from the file
    pending: bool
    group_id: int | None  # the image's gallery group
    pixels: tuple[int, int] | None  # the image's (width, height)
    name: str | None
    filename: str


@dataclass(frozen=True)
class _JobFiles:
    files: list[_File]
    authors: list[str]
    generation: frozenset  # what the write checks is unchanged


def _bucket(item_type: str, image_type: str | None) -> str:
    """Grouped by detected type: an image's own type, else the type the file was imported
    as (an Auto file that made no image is grouped with the maps). Every other file is a
    scene: Auto skips tokens and assets, and Include imports them as maps or scenes."""
    kind = image_type if image_type is not None else item_type
    return MAPS if in_map_bucket(kind) else SCENE


def _job_files(db: Session, job: ImportJob) -> list[_File]:
    rows = db.execute(
        select(
            ImportItem.id,
            ImportItem.relative_path,
            ImportItem.image_type,
            ImportItem.import_group_id,
            Image.id,
            Image.image_type,
            Image.awaiting_grouping,
            Image.group_id,
            Image.width,
            Image.height,
            Image.name,
            Image.filename,
        )
        .outerjoin(Image, (Image.id == ImportItem.image_id) & (Image.import_job_id == job.id))
        # Every file the seal parsed (or grouped, or that made an image): not archives,
        # nor files the manifest already settled (not an image, oversized)
        .where(
            ImportItem.job_id == job.id,
            ImportItem.kind != "archive",
            ImportItem.parsed.isnot(None)
            | ImportItem.import_group_id.isnot(None)
            | ImportItem.image_id.isnot(None),
        )
        .order_by(ImportItem.id)
    ).all()
    files: list[_File] = []
    for item_id, path, item_type, ig, image_id, image_type, pending, gid, w, h, name, fname in rows:
        files.append(
            _File(
                item_id=item_id,
                path=path,
                bucket=_bucket(item_type, image_type),
                import_group_id=ig,
                image_id=image_id,
                pending=bool(pending),
                group_id=gid,
                pixels=(w, h) if w and h else None,
                name=name,
                filename=fname or PurePosixPath(path).name,
            )
        )
    return files


def _generation(files: Iterable[_File]) -> frozenset:
    return frozenset((f.item_id, f.image_id, f.pending, f.import_group_id) for f in files)


def _read(db: Session, job: ImportJob) -> _JobFiles:
    files = _job_files(db, job)
    # The creators the library knew when the job was sealed (its own groups don't count)
    return _JobFiles(files, known_authors(db, job.planned_at), _generation(files))


def _is_due(db: Session, job: ImportJob) -> bool:
    return (
        job.planned_at is not None
        and job.grouped_at is None
        and not has_open_items(job_counts(db, job.id))
    )


def _lookup_vectors(image_ids: list[int]) -> dict[int, np.ndarray]:
    """The images' vectors; a failed lookup finds none (``get_embeddings`` logs it)."""
    from backend.app.services import get_lancedb_service

    service = get_lancedb_service()
    vectors: dict[int, np.ndarray] = {}
    for chunk in chunks(image_ids, _EMBEDDING_CHUNK):
        for image_id, vector in service.get_embeddings(list(chunk)).items():
            vectors[image_id] = np.asarray(vector, dtype=np.float32)
    return vectors


def _load_embeddings(
    image_ids: list[int], readiness: Readiness, repair: bool
) -> tuple[dict[int, np.ndarray], EmbeddingThresholds | None]:
    """(vectors by image id, thresholds): the active encoder's calibration and the images'
    vectors; ({}, None) when embedding rules are off. ``repair``: images without a vector
    are embedded first (``vector_reconcile.repair_missing``), since reconciliation would
    only repair them at the next startup or daily run, after the groups were minted."""
    from backend.app.services.grouping_calibration import active_calibration

    from .vector_reconcile import repair_missing

    if readiness != Readiness.USE or not image_ids:
        return {}, None
    calibration = active_calibration()
    if calibration is None:
        return {}, None
    vectors = _lookup_vectors(image_ids)
    missing = [i for i in image_ids if i not in vectors]
    if repair and missing:
        try:
            if repair_missing(missing):
                vectors.update(_lookup_vectors(missing))
        except Exception:
            logger.warning(
                "Couldn't repair the vectors of %d image(s)", len(missing), exc_info=True
            )
    return vectors, calibration.thresholds


def _features(db: Session, files: list[_File]) -> dict[int, ContentFeatures]:
    """Content features of the map and scene files that made an image, by item id, without
    their embeddings (``_with_embeddings``)."""
    grouped = [f for f in files if f.bucket in (MAPS, SCENE) and f.image_id is not None]
    image_ids = sorted(f.image_id for f in grouped if f.image_id is not None)
    rows = load_grouping_features(db, image_ids)
    features: dict[int, ContentFeatures] = {}
    for f in grouped:
        if f.image_id is None:
            continue
        row = rows.get(f.image_id)
        features[f.item_id] = ContentFeatures(
            phash256=row.phash256 if row else None,
            edge=row.edge if row else None,
            log_aspect=math.log(f.pixels[0] / f.pixels[1]) if f.pixels else None,
            pixels=f.pixels,
        )
    return features


def _with_embeddings(
    files: list[_File], features: dict[int, ContentFeatures], readiness: Readiness, repair: bool
) -> tuple[dict[int, ContentFeatures], EmbeddingThresholds | None]:
    """The features with the images' vectors, and the thresholds (``_load_embeddings``)."""
    image_of = {f.item_id: f.image_id for f in files if f.item_id in features and f.image_id}
    vectors, thresholds = _load_embeddings(sorted(image_of.values()), readiness, repair)
    return {
        item: replace(content, embedding=vectors.get(image_of[item]))
        for item, content in features.items()
    }, thresholds


def _tags(db: Session, image_ids: list[int]) -> dict[int, list[dict]]:
    """Awaiting images' tags, for their search text (no one can edit them meanwhile)."""
    found: dict[int, list[dict]] = {i: [] for i in image_ids}
    for chunk in chunks(image_ids):
        for image_id, category, value in db.execute(
            select(Tag.image_id, Tag.category, Tag.value).where(Tag.image_id.in_(chunk))
        ):
            found[image_id].append({"category": category, "value": value})
    return found


# Compute


def joined_subgroups(
    map_groups: Sequence[Sequence[int]],
    map_subgroups: Sequence[Mapping[int, str | None]],
    folders: Mapping[int, str],
    joined: Mapping[int, int],
) -> dict[int, str | None]:
    """The subgroup each file joining a map group (item → map group index) takes: the one
    label of that group's maps in the file's effective folder (its sub-group folder), else
    none."""
    labels: dict[tuple[int, str], set[str | None]] = {}  # (group, folder) → its maps' labels
    for index, items in enumerate(map_groups):
        for item in items:
            labels.setdefault((index, folders[item]), set()).add(map_subgroups[index].get(item))
    subgroups: dict[int, str | None] = {}
    for item, index in joined.items():
        here = labels.get((index, folders[item]), set())
        subgroups[item] = next(iter(here)) if len(here) == 1 else None
    return subgroups


def _proposals(
    files: list[_File],
    features: Mapping[int, ContentFeatures],
    thresholds: EmbeddingThresholds | None,
    parser: ImageParser,
    authors: list[str],
) -> tuple[list[Proposal], list[_Debug]]:
    """Groups of every file: maps by the content walk; scenes attached to a map group or
    grouped among themselves (``group_scenes``)."""
    params = GroupingParams(embedding=thresholds)
    maps = [GroupingFile(f.item_id, f.path) for f in files if f.bucket == MAPS]
    scenes = [GroupingFile(f.item_id, f.path) for f in files if f.bucket == SCENE]
    grouping = None
    map_groups: list[ProposedGroup[int]] = []
    if maps:
        grouping = variant_grouping.group_with_content(
            maps, features, params, parser, known_authors=authors
        )
        map_groups = grouping.groups
    effective = variant_grouping.effective_folders(f.path for f in files)
    folders = {f.item_id: effective[f.path] for f in files}
    map_keys = [g.keys for g in map_groups]
    scene_grouping = variant_grouping.group_scenes(grouping, maps, scenes, features, params)
    attached = {item: attachment.group for item, attachment in scene_grouping.attachments.items()}
    subgroups = joined_subgroups(map_keys, [g.subgroups for g in map_groups], folders, attached)
    joined: dict[int, list[int]] = {}
    for item, index in attached.items():
        joined.setdefault(index, []).append(item)

    proposals: list[Proposal] = []
    names = Counter((g.name, g.author or UNKNOWN_AUTHOR) for g in map_groups)
    for index, group in enumerate(map_groups):
        author = group.author or UNKNOWN_AUTHOR
        extra = joined.get(index, [])
        proposals.append(
            Proposal(
                (*group.keys, *extra),
                group.name,
                author,
                {**group.subgroups, **{item: subgroups[item] for item in extra}},
                # A fallback name, or one two of this import's maps share, says nothing
                # about which map it is: it can't pick an existing group
                group.name_is_identity and names[(group.name, author)] == 1,
            )
        )
    path_of = {f.item_id: f.path for f in files}
    for items in scene_grouping.groups:
        proposals.append(_named_by_parser([(path_of[i], i) for i in items], SCENE, parser, authors))
    return proposals, [g for g in (grouping, scene_grouping) if g is not None]


def _parsed_proposals(
    files: list[_File], parser: ImageParser, authors: list[str]
) -> list[Proposal]:
    """Groups of files from their paths alone, as ``ImageParser.group_files`` makes them,
    by type."""
    by_type: dict[str, list[_File]] = {}
    for f in files:
        by_type.setdefault(f.bucket, []).append(f)
    proposals: list[Proposal] = []
    for image_type, typed in sorted(by_type.items()):
        by_path = {f.path: f.item_id for f in typed}
        for group in parser.group_files(
            list(by_path), image_type=image_type, known_authors=authors
        ):
            proposals.append(
                Proposal(
                    tuple(by_path[f["relative_path"]] for f in group["files"]),
                    group["group_name"],
                    group.get("author") or UNKNOWN_AUTHOR,
                    {
                        by_path[f["relative_path"]]: f["parsed"].get("subgroup")
                        for f in group["files"]
                    },
                )
            )
    return proposals


def _named_by_parser(
    files: Sequence[tuple[str, int]], image_type: str, parser: ImageParser, authors: list[str]
) -> Proposal:
    """A proposal for files already grouped, named as ``group_files`` names them: its first
    group's name and author, and each file's parsed subgroup."""
    by_path = dict(files)
    parsed = parser.group_files(list(by_path), image_type=image_type, known_authors=authors)
    first = parsed[0]
    return Proposal(
        tuple(item for _, item in files),
        first["group_name"],
        first.get("author") or UNKNOWN_AUTHOR,
        {
            by_path[f["relative_path"]]: f["parsed"].get("subgroup")
            for group in parsed
            for f in group["files"]
        },
    )


# Write


def _state(db: Session, job: ImportJob, files: list[_File], proposals: list[Proposal]) -> JobState:
    import_groups = db.execute(
        select(
            ImportGroup.id,
            ImportGroup.image_group_id,
            ImportGroup.merged_into_existing,
            ImportGroup.group_name,
            ImportGroup.author,
        ).where(ImportGroup.job_id == job.id)
    ).all()
    referenced = sorted({gid for _, gid, *_ in import_groups if gid is not None})
    alive: set[int] = set()
    for chunk in chunks(referenced):
        alive.update(db.scalars(select(ImageGroup.id).where(ImageGroup.id.in_(chunk))))
    names = {(p.name, p.author) for p in proposals if p.match_existing}
    existing = existing_groups(db, {name for name, _ in names})
    return JobState(
        import_group_of={f.item_id: f.import_group_id for f in files if f.import_group_id},
        pending={f.item_id: f.image_id for f in files if f.pending and f.image_id is not None},
        placed={
            f.item_id: f.group_id
            for f in files
            if not f.pending and f.group_id is not None and f.group_id in alive
        },
        gallery_of={ig: gid if gid in alive else None for ig, gid, *_ in import_groups},
        group_names={
            ig: (name, author or UNKNOWN_AUTHOR) for ig, _, _, name, author in import_groups
        },
        merged=frozenset(gid for _, gid, merged, *_ in import_groups if merged and gid in alive),
        existing={
            (name, author): gid
            for (name, author), gid in existing.items()
            if author is not None and (name, author) in names
        },
    )


def _write(
    db: Session,
    job: ImportJob,
    files: list[_File],
    plan: GroupingPlan,
    tags: Mapping[int, list[dict]],
) -> int:
    """Write a plan in the caller's transaction; returns how many gallery groups it minted.
    Batched: the new rows as ordered ``INSERT .. RETURNING`` batches, the updates as
    executemany."""
    to_mint = [key for key, choice in plan.galleries.items() if choice.group_id is None]
    minted_ids = (
        db.scalars(
            insert(ImageGroup).returning(ImageGroup.id, sort_by_parameter_order=True),
            [
                {"base_name": plan.galleries[k].name, "author": plan.galleries[k].author}
                for k in to_mint
            ],
        ).all()
        if to_mint
        else []
    )
    minted = dict(zip(to_mint, minted_ids, strict=True))
    gallery = {key: minted.get(key, choice.group_id) for key, choice in plan.galleries.items()}

    new_ids = (
        db.scalars(
            insert(ImportGroup).returning(ImportGroup.id, sort_by_parameter_order=True),
            [
                {
                    "job_id": job.id,
                    "author": g.author,
                    "group_name": g.name,
                    "image_group_id": gallery.get(g.key),
                    "merged_into_existing": g.key in plan.galleries
                    and plan.galleries[g.key].merged,
                    "sort_order": g.sort_order,
                }
                for g in plan.new_import_groups
            ],
        ).all()
        if plan.new_import_groups
        else []
    )
    ids = {g.key: new_id for g, new_id in zip(plan.new_import_groups, new_ids, strict=True)}

    def resolved(key: int) -> int:
        return ids.get(key, key)

    changed = [
        {"id": key, "image_group_id": gallery[key], "merged_into_existing": choice.merged}
        for key, choice in plan.galleries.items()
        if key not in ids
    ]
    if changed:
        db.execute(update(ImportGroup), changed)
    if plan.item_groups:
        db.execute(
            update(ImportItem),
            [
                {"id": item, "import_group_id": resolved(key)}
                for item, key in plan.item_groups.items()
            ],
        )

    authors: dict[int, str | None] = {minted[k]: plan.galleries[k].author for k in minted}
    looked_up = sorted({gid for gid in gallery.values() if gid is not None} - set(authors))
    for chunk in chunks(looked_up):
        query = select(ImageGroup.id, ImageGroup.author).where(ImageGroup.id.in_(chunk))
        for gid, author in db.execute(query):  # not dict(result): a Result has .keys()
            authors[gid] = author
    by_image = {f.image_id: f for f in files if f.image_id is not None}
    updates = []
    for image_id, (key, subgroup) in plan.images.items():
        f = by_image[image_id]
        gallery_id = gallery[key]
        author = authors.get(gallery_id) if gallery_id is not None else None
        updates.append(
            {
                "id": image_id,
                "group_id": gallery_id,
                "author": author,
                "subgroup": subgroup,
                "awaiting_grouping": False,
                "search_text": build_search_text(
                    name=f.name,
                    filename=f.filename,
                    author=author,
                    tags=list(tags.get(image_id, [])),
                    subgroup=subgroup,
                ),
            }
        )
    if updates:
        db.execute(update(Image), updates)  # executemany by primary key
    return len(minted)


def _orphans(files: list[_File], proposals: list[Proposal]) -> list[Proposal]:
    """A file in no proposal (it shouldn't happen) is a group of its own, so no image is
    left awaiting a group forever."""
    covered = {item for p in proposals for item in p.items}
    return [
        Proposal((f.item_id,), f.name or PurePosixPath(f.path).stem, UNKNOWN_AUTHOR, {}, False)
        for f in files
        if f.item_id not in covered
    ]


# Entry point


class Outcome(StrEnum):
    GROUPED = "grouped"
    DEFERRED = "deferred"  # the model is busy; a later sweep runs it
    NO_VECTORS = "no_vectors"  # many of its images have no vector yet; a later sweep runs it
    NOT_DUE = "not_due"  # unknown, unsealed, still importing, or grouped already


_MAX_PASSES = 3  # a job whose files change while it is grouped is read again
# A run with embedding rules on waits (NO_VECTORS) while more than this share of the job's map
# and scene images have no vector
_MISSING_VECTORS_SHARE = 0.1


def group_job(
    job_id: str,
    progress_fn: Callable[..., None] | None = None,
    *,
    readiness: Callable[[], Readiness] = embedding_readiness,
    wait_for_vectors: bool = False,
    paths_only: bool = False,
) -> Outcome:
    """Run a job's grouping phase (module docstring). Idempotent: a grouped job, or one
    still importing, is left alone. ``progress_fn`` is the JobRunner's callback.

    ``wait_for_vectors``: embed its images that have no vector, and return ``NO_VECTORS``
    rather than group without the vectors of many of them. ``paths_only``: group every file with ``ImageParser.group_files``,
    without content (for a job whose grouping keeps failing).
    """
    from .ingest_worker import get_ingest_worker

    for _ in range(_MAX_PASSES):
        ready = Readiness.OFF if paths_only else readiness()
        if ready == Readiness.DEFER:
            logger.info("Grouping of import %s waits: the model is busy", job_id)
            return Outcome.DEFERRED
        with _session() as db:
            job = db.get(ImportJob, job_id)
            if job is None or not _is_due(db, job):
                return Outcome.NOT_DUE
            read = _read(db, job)
            if progress_fn:
                progress_fn(0, 2, "Reading grouping features")
            # Paths only reads no content: a job whose grouping keeps failing must not fail there
            features = {} if paths_only else _features(db, read.files)
            parser = build_parser(db)
            pending = sorted(f.image_id for f in read.files if f.pending and f.image_id)
            tags = _tags(db, pending)
        # Outside the read: repairing missing vectors embeds images
        features, thresholds = _with_embeddings(read.files, features, ready, wait_for_vectors)
        missing = (
            sum(f.embedding is None for f in features.values()) if thresholds is not None else 0
        )
        if wait_for_vectors and missing > _MISSING_VECTORS_SHARE * len(features):
            logger.info(
                "Grouping of import %s waits: %d of %d image(s) have no vector",
                job_id,
                missing,
                len(features),
            )
            return Outcome.NO_VECTORS
        if progress_fn:
            progress_fn(1, 2, "Identifying groups")
        if paths_only:
            proposals, debug = _parsed_proposals(read.files, parser, read.authors), []
        else:
            proposals, debug = _proposals(read.files, features, thresholds, parser, read.authors)
        proposals += _orphans(read.files, proposals)

        with write_session() as db:
            job = db.get(ImportJob, job_id)
            if job is None or not _is_due(db, job):
                return Outcome.NOT_DUE
            if _generation(_job_files(db, job)) != read.generation:
                continue  # its files changed since the read: read them again
            last = db.scalar(
                select(func.max(ImportGroup.sort_order)).where(ImportGroup.job_id == job_id)
            )
            plan = plan_grouping(
                proposals, _state(db, job, read.files, proposals), (last or -1) + 1
            )
            minted = _write(db, job, read.files, plan, tags)
            job.grouped_at = utcnow()
            recompute_job_status(db, job_id)
        get_ingest_worker().bump()
        if paths_only:
            content = "paths only"
        elif thresholds is None:
            content = "embeddings off"
        else:
            content = f"embeddings on, {missing} of {len(features)} image(s) without a vector"
        _log(job_id, plan, minted, len(read.files), content, debug)
        if progress_fn:
            progress_fn(2, 2, "Done")
        return Outcome.GROUPED
    logger.warning("Import %s kept changing while it was grouped; a sweep retries", job_id)
    return Outcome.NOT_DUE


def _log(
    job_id: str,
    plan: GroupingPlan,
    minted: int,
    files: int,
    content: str,
    debug: Sequence[_Debug],
) -> None:
    logger.info(
        "Grouped import %s: %d file(s), %d image(s) placed, %d new import group(s), "
        "%d new gallery group(s); %s",
        job_id,
        files,
        len(plan.images),
        len(plan.new_import_groups),
        minted,
        content,
    )
    if logger.isEnabledFor(logging.DEBUG):
        for grouping in debug:
            for line in grouping.debug_lines():
                logger.debug("Grouping: %s", line)


# Scheduling


def due_jobs(db: Session) -> list[str]:
    """Jobs in their grouping phase (sealed, nothing open, not grouped; cancelled ones too),
    oldest first."""
    open_items = (
        select(ImportItem.id)
        .where(ImportItem.job_id == ImportJob.id, ImportItem.state.in_(st.OPEN_ITEM_STATES))
        .exists()
    )
    return list(
        db.scalars(
            select(ImportJob.id)
            .where(ImportJob.planned_at.isnot(None), ImportJob.grouped_at.is_(None), ~open_items)
            .order_by(ImportJob.created_at, ImportJob.id)
        )
    )


Runner = Callable[[str, Callable[[str], None]], None]


def _job_runner(job_id: str, run: Callable[[str], None]) -> None:
    """Hand a run to the JobRunner. The name starts with "Import" so the activity dock
    leaves it to the import's own row (``useBackgroundJobs``)."""
    from backend.app.services.job_runner import get_job_runner

    get_job_runner().submit(run, job_id, name=f"Import grouping {job_id[:8]}")


# Runs of a job that may raise before it is grouped by its paths alone; if that fails too,
# the job is left alone until a restart
_MAX_FAILED_RUNS = 3
# How long a job may wait for missing vectors (NO_VECTORS), from its first such run, before it
# is grouped without them. Each run repairs what it can first; this covers a vector index that
# is briefly unreadable.
_VECTOR_WAIT_SECONDS = 300.0


class GroupingScheduler:
    """Starts the grouping phase of due jobs, at most one run per job at a time.

    ``runner`` decides where a run happens: the JobRunner by default, inline (synchronous)
    in tests. ``readiness`` is passed to every run; ``clock`` times waits for vectors.

    Failed runs and waits for vectors are kept per job in memory, not in the database: a
    restart starts them again, which only repeats a bounded number of runs.
    """

    def __init__(
        self,
        runner: Runner = _job_runner,
        readiness: Callable[[], Readiness] = embedding_readiness,
        clock: Callable[[], float] = time.monotonic,
    ):
        self._runner = runner
        self._readiness = readiness
        self._clock = clock
        self._lock = threading.Lock()
        self._running: set[str] = set()
        self._failures: Counter[str] = Counter()
        self._waiting_since: dict[str, float] = {}  # job → its first NO_VECTORS run

    def schedule(self) -> list[str]:
        """Start the grouping phase of every due job. Returns the jobs started; never raises
        (a failure is logged, a later sweep retries)."""
        try:
            with _session() as db:
                due = due_jobs(db)
        except Exception:
            logger.exception("Couldn't look up imports due for grouping")
            return []
        started: list[str] = []
        for job_id in due:
            with self._lock:
                if job_id in self._running or self._failures[job_id] > _MAX_FAILED_RUNS:
                    continue
                self._running.add(job_id)
            try:
                self._runner(job_id, self._run)
            except Exception:
                with self._lock:
                    self._running.discard(job_id)
                logger.exception("Couldn't start grouping import %s", job_id)
                continue
            started.append(job_id)
        return started

    def _run(self, job_id: str, progress_fn: Callable[..., None] | None = None) -> None:
        now = self._clock()
        with self._lock:
            failures = self._failures[job_id]
            since = self._waiting_since.get(job_id, now)
        outcome: Outcome | None = None
        try:
            outcome = group_job(
                job_id,
                progress_fn,
                readiness=self._readiness,
                wait_for_vectors=now - since < _VECTOR_WAIT_SECONDS,
                paths_only=failures >= _MAX_FAILED_RUNS,
            )
        except Exception:
            failures += 1
            if failures < _MAX_FAILED_RUNS:
                logger.exception("Grouping import %s failed; a sweep retries", job_id)
            elif failures == _MAX_FAILED_RUNS:
                logger.exception(
                    "Grouping import %s failed %d times; it will be grouped by its file paths "
                    "alone",
                    job_id,
                    failures,
                )
            else:
                logger.exception(
                    "Grouping import %s by its file paths failed too; its images stay hidden "
                    "until the app restarts",
                    job_id,
                )
        finally:
            with self._lock:
                self._running.discard(job_id)
                if outcome is None:
                    self._failures[job_id] = failures
                elif outcome == Outcome.NO_VECTORS:
                    self._waiting_since[job_id] = since
                elif outcome != Outcome.DEFERRED:
                    self._failures.pop(job_id, None)
                    self._waiting_since.pop(job_id, None)


_scheduler: GroupingScheduler | None = None
_scheduler_lock = threading.Lock()


def get_grouping_scheduler() -> GroupingScheduler:
    """The process-wide scheduler (tests install an inline one)."""
    global _scheduler
    with _scheduler_lock:
        if _scheduler is None:
            _scheduler = GroupingScheduler()
        return _scheduler


def schedule_grouping() -> list[str]:
    """Start the grouping phase of every due job."""
    return get_grouping_scheduler().schedule()
