"""Grouping refinement: merge an import's map groups once content says they are one map
(ADR-028, design/variant-grouping.md §3, design/ingestion.md §5.8).

A seal groups maps from their paths alone (``ingest_queue.compute_plan``). Once a *scope*
has nothing left open (every item done, a duplicate, failed or skipped) and its vectors are
written, ``refine_job_groups`` re-runs the walk over its files with their content features
(pHash renditions, edge-map layout, embeddings) and **merges** the gallery groups each
resulting group touches. It never splits, and it only changes groups this job created that
the user hasn't edited (``ImageGroup.edited_at``).

Scopes (``Scope``): an import with more than ``PARTITION_MIN_MAP_FILES`` map files is sealed
with a partition per import group (its effective top-level folder,
``variant_grouping.partition_keys``). Each partition is refined as soon as it has finished,
so its groups become reviewable while the rest imports; when the whole job has finished,
a final whole-job pass adds the joins across partitions (cross-tree renditions). Smaller
imports have no partitions and get only the whole-job pass. A refined scope stamps its import
groups (``ImportGroup.grouping_refined_at``), the whole-job pass also the job; re-opened
items clear their partitions' stamps (``ingest_queue._unrefine``).

Three steps, so the write lock is held only briefly:

1. **Read** (no lock): the scope's map items and the images they made, the eligible groups,
   grouping features, embeddings and the encoder's calibration.
2. **Compute** (no lock): ``variant_grouping.group_with_content`` over the whole job's map
   items (the seal's tree and name context), with content features for the scope's.
3. **Apply** (one ``write_session``): re-read membership and eligibility (images may have
   moved or been deleted, groups edited, merged or undone meanwhile), plan again with
   ``plan_merges`` (pure, cheap), merge through ``group_service``, re-point the
   ``ImportGroup`` rows of merged groups so Undo still finds the survivors, and stamp the
   scope refined.

Scheduling (``RefinementScheduler``): ``process_batch`` asks for the scopes its batch
touched; the worker's idle loop, hourly maintenance and startup sweep every due scope,
since JobRunner work is lost on restart. Requests for a scope already running are
dropped.

**Model availability.** While the embedding model is loading or switching (the worker is
held, or the model is loading) refinement is deferred: the job stays unrefined and a later
sweep runs it. With no model at all it runs without embeddings (renditions, names and
folders still work). Without a calibration for the active encoder, embedding rules are
off as well (``grouping_calibration``).
"""

from __future__ import annotations

import logging
import math
import threading
from collections import Counter
from collections.abc import Callable, Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum

import numpy as np
from sqlalchemy import case, func, select, update
from sqlalchemy.orm import Session, selectinload

from backend.app.models import Image, ImageGroup, ImportGroup, ImportItem, ImportJob
from backend.app.services import group_service, variant_grouping
from backend.app.services import ingest_state as st
from backend.app.services.fts_service import search_text_for
from backend.app.services.linked_files import chunks
from backend.app.services.variant_grouping import (
    ContentFeatures,
    EmbeddingThresholds,
    GroupingFile,
    GroupingParams,
)

from .grouping_features import load_grouping_features
from .ingest_queue import (
    _session,
    build_parser,
    has_open_items,
    job_counts,
    known_authors,
    utcnow,
    was_in_map_bucket,
    write_session,
)

logger = logging.getLogger(__name__)

_EMBEDDING_CHUNK = 500  # ids per LanceDB lookup
_TOUCHED_LIMIT = 500  # a batch's import group ids checked for closing (far more than a batch)


# Planning (pure)


@dataclass(frozen=True)
class Proposal:
    """One group of the content walk, in images: the job's images it holds (items that
    made no image take part in the walk but not here) and their sub-group labels."""

    images: tuple[int, ...]
    subgroups: Mapping[int, str] = field(default_factory=dict)
    name: str = ""
    reasons: Mapping[str, int] = field(default_factory=dict)


@dataclass(frozen=True)
class Membership:
    """The gallery as a plan is made against it.

    - ``group_of``: each image's group (None: in no group); images deleted since are absent;
    - ``subgroup_of``: each image's subgroup;
    - ``eligible``: the groups refinement may change (this job's, not edited by the user);
    - ``sizes``: how many images each eligible group holds, from any import.
    """

    group_of: Mapping[int, int | None]
    subgroup_of: Mapping[int, str | None]
    eligible: Collection[int]
    sizes: Mapping[int, int]


@dataclass(frozen=True)
class GroupMerge:
    """Merge ``merged`` into ``survivor`` (which keeps its id, name and author)."""

    survivor: int
    merged: tuple[int, ...]
    name: str
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class MergePlan:
    merges: tuple[GroupMerge, ...] = ()
    subgroups: Mapping[int, str | None] = field(default_factory=dict)  # image → new subgroup
    # Eligible groups the walk splits across several groups: left exactly as they are
    conflicted: frozenset[int] = frozenset()

    @property
    def merged_groups(self) -> int:
        return sum(len(m.merged) for m in self.merges)


def plan_merges(proposals: Sequence[Proposal], membership: Membership) -> MergePlan:
    """What refinement changes, from the walk's groups and the gallery as it is now.

    - A proposal touching two or more eligible groups merges them into the one with the
      most images (ties: the lowest id). Ineligible groups, and the images in them, never
      move; images in no group, or gone, are ignored.
    - Never a split: a merge moves whole groups, and nothing else moves.
    - An eligible group the walk spreads over several proposals is *conflicted*: the walk
      disagrees with it, so it is neither merged nor relabelled. (A seal group is a union
      of content groups' parts only if paths and content disagree; refinement then makes
      no guess, rather than chaining the proposals together through it.)
    - Sub-groups: an image in an eligible, unconflicted group takes its proposal's label
      (None: the group's main body) when that differs from its subgroup.
    """
    eligible = set(membership.eligible)

    def eligible_group(image: int) -> int | None:
        group = membership.group_of.get(image)
        return group if group is not None and group in eligible else None

    touched_by: dict[int, set[int]] = {}
    for index, proposal in enumerate(proposals):
        for image in proposal.images:
            group = eligible_group(image)
            if group is not None:
                touched_by.setdefault(group, set()).add(index)
    conflicted = frozenset(g for g, indexes in touched_by.items() if len(indexes) > 1)

    merges: list[GroupMerge] = []
    subgroups: dict[int, str | None] = {}
    for proposal in proposals:
        groups: set[int] = set()
        for image in proposal.images:
            group = eligible_group(image)
            if group is None or group in conflicted:
                continue
            groups.add(group)
            label = proposal.subgroups.get(image)
            if label != membership.subgroup_of.get(image):
                subgroups[image] = label
        if len(groups) >= 2:
            survivor = min(groups, key=lambda g: (-membership.sizes.get(g, 0), g))
            merges.append(
                GroupMerge(
                    survivor,
                    tuple(sorted(groups - {survivor})),
                    proposal.name,
                    tuple(sorted(proposal.reasons)),
                )
            )
    return MergePlan(tuple(merges), subgroups, conflicted)


# Model availability


class Readiness(StrEnum):
    USE = "use"  # embeddings may be used (if the encoder is calibrated)
    OFF = "off"  # no model: refine without embeddings
    DEFER = "defer"  # the model is loading or switching: try again later


def embedding_readiness() -> Readiness:
    """Whether refinement can run now, and with embeddings (module docstring)."""
    from backend.app.services.clip_service import get_clip_unavailable_reason, is_clip_loading

    from .ingest_worker import get_ingest_worker

    if get_ingest_worker().is_held() or is_clip_loading():
        return Readiness.DEFER
    if get_clip_unavailable_reason() is not None:
        return Readiness.OFF
    return Readiness.USE


# Scope: what one run refines


@dataclass(frozen=True)
class Scope:
    """One refinement: a partition of a job (its effective top-level folder), or the whole
    job (``partition`` None: an import refined as a whole, and every import's final pass)."""

    job_id: str
    partition: str | None = None

    def __str__(self) -> str:
        if self.partition is None:
            return f"import {self.job_id}"
        return f"import {self.job_id}, partition {self.partition!r}"


def _scope_groups(scope: Scope):
    """SQL: the scope's import groups."""
    where = ImportGroup.job_id == scope.job_id
    if scope.partition is not None:
        where = where & (ImportGroup.partition_key == scope.partition)
    return where


def _is_due(db: Session, scope: Scope) -> bool:
    """A job is due when sealed, with nothing open, and not refined as a whole; a partition
    when the job is sealed, none of the partition's items is open, and one of its import
    groups isn't refined."""
    job = db.get(ImportJob, scope.job_id)
    if job is None or job.planned_at is None:
        return False
    if scope.partition is None:
        return job.grouping_refined_at is None and not has_open_items(job_counts(db, job.id))
    is_open = case((ImportItem.state.in_(st.OPEN_ITEM_STATES), 1), else_=0)
    unrefined = case((ImportGroup.grouping_refined_at.is_(None), 1), else_=0)
    row = db.execute(
        select(func.max(is_open), func.max(unrefined))
        .select_from(ImportGroup)
        .join(ImportItem, ImportItem.import_group_id == ImportGroup.id)
        .where(_scope_groups(scope))
    ).one()
    return row[0] == 0 and row[1] == 1


# Read


@dataclass(frozen=True)
class _ScopeFiles:
    """What the content walk runs over.

    The walk always covers **every** map item of the job, as the seal saw them (keyed by item
    id): name analysis (global tokens, house prefixes, hubs, recurring folder names) and the
    tree depend on the whole file set, so a walk over one partition alone could name and join
    differently from the seal and break merge-only. Content features are given only to the
    scope's items (``featured``); the rest take part through names and folders, exactly as at
    seal.
    """

    scope: Scope
    files: list[GroupingFile[int]]
    image_of: dict[int, int]  # item id → image id, every map item that made one
    featured: dict[int, int]  # the scope's part of image_of; also the run's generation
    log_aspect: dict[int, float]  # image id → log(width / height)
    authors: list[str]


def _map_items(job_id: str):
    """SQL: the job's map items, their import group's partition, and the images this job
    made from them (refreshes of older images are left out)."""
    return (
        select(
            ImportItem.id,
            ImportItem.relative_path,
            ImportGroup.partition_key,
            Image.id,
            Image.width,
            Image.height,
        )
        .join(ImportGroup, ImportGroup.id == ImportItem.import_group_id)
        .outerjoin(Image, (Image.id == ImportItem.image_id) & (Image.import_job_id == job_id))
        .where(ImportItem.job_id == job_id, ImportItem.kind != "archive", was_in_map_bucket())
        .order_by(ImportItem.id)
    )


def _scope_images(rows, scope: Scope) -> dict[int, int]:
    """Item → image of the scope's map items that made an image."""
    return {
        item_id: image_id
        for item_id, _, partition, image_id, *_ in rows
        if image_id is not None and (scope.partition is None or partition == scope.partition)
    }


def _read_files(db: Session, scope: Scope) -> _ScopeFiles:
    job = db.get_one(ImportJob, scope.job_id)
    if not job.grouping_refinable:
        # Sealed by the old parser (before migration 029): it keeps its groups, and a run
        # only stamps it, so its groups can be reviewed again after a re-open
        return _ScopeFiles(scope, [], {}, {}, {}, [])
    rows = db.execute(_map_items(scope.job_id)).all()
    files = [GroupingFile(item_id, path) for item_id, path, *_ in rows]
    log_aspect = {
        image_id: math.log(width / height)
        for *_, image_id, width, height in rows
        if image_id is not None and width and height
    }
    # The creators the library knew when the job was sealed, as the seal pass saw them
    return _ScopeFiles(
        scope,
        files,
        _scope_images(rows, Scope(scope.job_id)),
        _scope_images(rows, scope),
        log_aspect,
        known_authors(db, job.planned_at),
    )


def _load_embeddings(image_ids: list[int], readiness: Readiness):
    """(vectors by image id, thresholds): the active encoder's calibration and the vectors
    of its dimension; ({}, None) when embedding rules are off."""
    from backend.app.services import get_lancedb_service
    from backend.app.services.grouping_calibration import active_calibration, active_thresholds

    if readiness != Readiness.USE or not image_ids or active_calibration() is None:
        return {}, None
    service = get_lancedb_service()
    vectors: dict[int, np.ndarray] = {}
    for chunk in chunks(image_ids, _EMBEDDING_CHUNK):
        for image_id, vector in service.get_embeddings(list(chunk)).items():
            vectors[image_id] = np.asarray(vector, dtype=np.float32)
    if not vectors:
        return {}, None
    dim, _ = Counter(len(v) for v in vectors.values()).most_common(1)[0]
    thresholds = active_thresholds(dim)
    if thresholds is None:
        return {}, None
    return {i: v for i, v in vectors.items() if len(v) == dim}, thresholds


def _features(
    db: Session, files: _ScopeFiles, readiness: Readiness
) -> tuple[dict[int, ContentFeatures], EmbeddingThresholds | None]:
    """Content features of the scope's items, by item id, and the embedding thresholds
    (None: rules off)."""
    image_ids = sorted(files.featured.values())
    rows = load_grouping_features(db, image_ids)
    vectors, thresholds = _load_embeddings(image_ids, readiness)
    features: dict[int, ContentFeatures] = {}
    for item_id, image_id in files.featured.items():
        row = rows.get(image_id)
        features[item_id] = ContentFeatures(
            phash256=row.phash256 if row else None,
            edge=row.edge if row else None,
            log_aspect=files.log_aspect.get(image_id),
            embedding=vectors.get(image_id),
        )
    return features, thresholds


# Compute


def _proposals(
    grouping: variant_grouping.Grouping[int], image_of: Mapping[int, int]
) -> list[Proposal]:
    return [
        Proposal(
            images=tuple(image_of[k] for k in group.keys if k in image_of),
            subgroups={image_of[k]: label for k, label in group.subgroups.items() if k in image_of},
            name=group.name,
            reasons=dict(group.reasons),
        )
        for group in grouping.groups
    ]


# Apply


def _membership(db: Session, scope: Scope, image_ids: Collection[int]) -> Membership:
    """The gallery as it is now, for the scope: its images' groups and subgroups, and the
    eligible groups (created by this job's import groups in the scope, not edited)."""
    group_of: dict[int, int | None] = {}
    subgroup_of: dict[int, str | None] = {}
    for chunk in chunks(sorted(image_ids)):
        for image_id, group_id, subgroup in db.execute(
            select(Image.id, Image.group_id, Image.subgroup).where(Image.id.in_(chunk))
        ):
            group_of[image_id] = group_id
            subgroup_of[image_id] = subgroup
    eligible_rows = db.execute(
        select(ImageGroup.id, ImageGroup.image_count)
        .join(ImportGroup, ImportGroup.image_group_id == ImageGroup.id)
        .where(
            _scope_groups(scope),
            ImportGroup.merged_into_existing.is_(False),
            ImageGroup.edited_at.is_(None),
        )
        .distinct()
    ).all()
    sizes = {group_id: count or 0 for group_id, count in eligible_rows}
    return Membership(group_of, subgroup_of, set(sizes), sizes)


def _images_with_tags(db: Session, image_ids: Collection[int]) -> list[Image]:
    images: list[Image] = []
    for chunk in chunks(sorted(image_ids)):
        images += (
            db.query(Image).options(selectinload(Image.tags)).filter(Image.id.in_(chunk)).all()
        )
    return images


def _apply(db: Session, plan: MergePlan) -> int:
    """Write a plan. Returns how many images moved."""
    if plan.subgroups:
        for image in _images_with_tags(db, plan.subgroups):
            image.subgroup = plan.subgroups[image.id]
            image.search_text = search_text_for(image)
        db.flush()
    moved = 0
    for merge in plan.merges:
        survivor = db.get_one(ImageGroup, merge.survivor)
        sources = [db.get_one(ImageGroup, gid) for gid in merge.merged]
        moved += group_service.merge_groups(db, survivor, sources)
        # Every import's groups that resolved to a merged group now resolve to the
        # survivor: Undo finds it, and the sorted-out counts and review stay with the map
        db.execute(
            update(ImportGroup)
            .where(ImportGroup.image_group_id.in_(merge.merged))
            .values(image_group_id=merge.survivor)
            .execution_options(synchronize_session=False)
        )
    return moved


def _stamp(db: Session, scope: Scope) -> None:
    """Mark the scope refined: its import groups (all of the job's, for the whole job) and,
    for the whole job, the job."""
    now = utcnow()
    db.execute(
        update(ImportGroup)
        .where(_scope_groups(scope))
        .values(grouping_refined_at=now)
        .execution_options(synchronize_session=False)
    )
    if scope.partition is None:
        db.get_one(ImportJob, scope.job_id).grouping_refined_at = now


# Entry point


class Outcome(StrEnum):
    REFINED = "refined"
    DEFERRED = "deferred"  # the model is busy; a later sweep runs it
    NOT_DUE = "not_due"  # unknown, unsealed, still open, or refined already


_MAX_PASSES = 3  # a scope whose images change while it is refined is read again


def refine_job_groups(
    job_id: str,
    progress_fn: Callable[..., None] | None = None,
    *,
    partition: str | None = None,
    readiness: Callable[[], Readiness] = embedding_readiness,
) -> Outcome:
    """Refine one job's map groups, or one partition's (module docstring). Idempotent: a
    refined scope, or one with open items, is left alone. ``progress_fn`` is the
    JobRunner's callback."""
    scope = Scope(job_id, partition)
    for _ in range(_MAX_PASSES):
        ready = readiness()
        if ready == Readiness.DEFER:
            logger.info("Grouping refinement of %s deferred: the model is busy", scope)
            return Outcome.DEFERRED
        with _session() as db:
            if not _is_due(db, scope):
                return Outcome.NOT_DUE
            files = _read_files(db, scope)
            if progress_fn:
                progress_fn(0, 2, "Reading grouping features")
            features, thresholds = _features(db, files, ready) if files.featured else ({}, None)
            parser = build_parser(db)
        if progress_fn:
            progress_fn(1, 2, "Grouping maps")
        # No map items (or an import sealed before 029): nothing to walk, only to stamp
        grouping = (
            variant_grouping.group_with_content(
                files.files,
                features,
                GroupingParams(embedding=thresholds),
                parser,
                known_authors=files.authors,
            )
            if files.files
            else variant_grouping.Grouping[int](groups=[])
        )
        proposals = _proposals(grouping, files.image_of)
        applied = _apply_if_current(files, proposals)
        if applied is None:
            continue  # its images changed meanwhile: read it again
        if isinstance(applied, Outcome):  # undone, re-opened or refined meanwhile
            return applied
        plan, moved = applied
        _log(scope, plan, moved, len(files.featured), thresholds is not None, grouping)
        if progress_fn:
            progress_fn(2, 2, "Done")
        return Outcome.REFINED
    logger.warning("%s kept changing while its grouping was refined; a sweep retries", scope)
    return Outcome.NOT_DUE


def _apply_if_current(
    files: _ScopeFiles, proposals: list[Proposal]
) -> tuple[MergePlan, int] | Outcome | None:
    """Apply in one write transaction: (plan, images moved). None when the scope's images
    changed since it was read (it re-opened and finished again: new images to group);
    ``NOT_DUE`` when it was undone, re-opened or refined meanwhile, and nothing is applied."""
    from .ingest_worker import get_ingest_worker

    scope = files.scope
    with write_session() as db:
        if not _is_due(db, scope):
            return Outcome.NOT_DUE
        current = _scope_images(db.execute(_map_items(scope.job_id)).all(), scope)
        if files.files and current != files.featured:
            return None
        images = {image for proposal in proposals for image in proposal.images}
        plan = plan_merges(proposals, _membership(db, scope, images))
        moved = _apply(db, plan)
        _stamp(db, scope)
    get_ingest_worker().bump()
    return plan, moved


def _log(
    scope: Scope,
    plan: MergePlan,
    moved: int,
    files: int,
    embeddings: bool,
    grouping: variant_grouping.Grouping[int],
) -> None:
    reasons = Counter(reason for merge in plan.merges for reason in merge.reasons)
    logger.info(
        "Refined grouping of %s: %d image(s), %d merge(s) of %d group(s), %d image(s) "
        "moved, %d subgroup(s) relabelled, %d group(s) left as sealed (the walk splits them); "
        "embeddings %s; reasons: %s",
        scope,
        files,
        len(plan.merges),
        plan.merged_groups,
        moved,
        len(plan.subgroups),
        len(plan.conflicted),
        "on" if embeddings else "off",
        ", ".join(f"{r} ×{n}" for r, n in sorted(reasons.items())) or "none",
    )
    if logger.isEnabledFor(logging.DEBUG):
        for merge in plan.merges:
            logger.debug(
                "Refinement merge: %s into group %d (%r: %s)",
                list(merge.merged),
                merge.survivor,
                merge.name,
                ", ".join(merge.reasons),
            )
        for line in grouping.debug_lines():
            logger.debug("Refinement grouping: %s", line)


# Scheduling


def due_jobs(db: Session, job_ids: Iterable[str] | None = None) -> list[str]:
    """Jobs due for their whole-job pass (sealed, nothing open, not refined), oldest first;
    among ``job_ids`` if given."""
    open_items = (
        select(ImportItem.id)
        .where(
            ImportItem.job_id == ImportJob.id,
            ImportItem.state.in_(st.OPEN_ITEM_STATES),
        )
        .exists()
    )
    query = (
        select(ImportJob.id)
        .where(
            ImportJob.planned_at.isnot(None),
            ImportJob.grouping_refined_at.is_(None),
            ~open_items,
        )
        .order_by(ImportJob.created_at, ImportJob.id)
    )
    if job_ids is None:
        return list(db.scalars(query))
    found: list[str] = []
    for chunk in chunks(sorted(set(job_ids))):
        found += db.scalars(query.where(ImportJob.id.in_(chunk)))
    return found


def _closed_unrefined_groups(db: Session, import_group_ids: Iterable[int]) -> list[int]:
    """Of a batch's import groups, the partitioned, unrefined ones with no open item left: a
    narrow query over those groups' items, so a batch that finished no partition costs no
    partition-wide aggregation."""
    touched = sorted(set(import_group_ids))[:_TOUCHED_LIMIT]
    if not touched:
        return []
    is_open = case((ImportItem.state.in_(st.OPEN_ITEM_STATES), 1), else_=0)
    return list(
        db.scalars(
            select(ImportGroup.id)
            .join(ImportItem, ImportItem.import_group_id == ImportGroup.id)
            .where(
                ImportGroup.id.in_(touched),
                ImportGroup.partition_key.isnot(None),
                ImportGroup.grouping_refined_at.is_(None),
            )
            .group_by(ImportGroup.id)
            .having(func.max(is_open) == 0)
        )
    )


def due_partitions(
    db: Session,
    job_ids: Iterable[str] | None = None,
    import_group_ids: Iterable[int] | None = None,
) -> list[Scope]:
    """Partitions due for refinement: none of their items open and one of their import
    groups not refined, in jobs not refined as a whole. Among ``job_ids`` if given, and
    only the partitions of ``import_group_ids`` if given (a batch's groups), and then only if
    one of those groups has just closed. One grouped query, however many partitions."""
    is_open = case((ImportItem.state.in_(st.OPEN_ITEM_STATES), 1), else_=0)
    unrefined = case((ImportGroup.grouping_refined_at.is_(None), 1), else_=0)
    query = (
        select(ImportGroup.job_id, ImportGroup.partition_key)
        .join(ImportItem, ImportItem.import_group_id == ImportGroup.id)
        .join(ImportJob, ImportJob.id == ImportGroup.job_id)
        .where(
            ImportGroup.partition_key.isnot(None),
            ImportJob.planned_at.isnot(None),
            ImportJob.grouping_refined_at.is_(None),
        )
        .group_by(ImportGroup.job_id, ImportGroup.partition_key)
        .having((func.max(is_open) == 0) & (func.max(unrefined) == 1))
        .order_by(ImportGroup.job_id, ImportGroup.partition_key)
    )
    if job_ids is not None:
        query = query.where(ImportGroup.job_id.in_(sorted(set(job_ids))))
    if import_group_ids is not None:
        closed = _closed_unrefined_groups(db, import_group_ids)
        if not closed:
            return []  # the usual batch: nothing of it finished a partition
        query = query.where(
            ImportGroup.partition_key.in_(
                select(ImportGroup.partition_key).where(ImportGroup.id.in_(closed))
            )
        )
    return [Scope(job_id, partition) for job_id, partition in db.execute(query)]


Runner = Callable[[Scope, Callable[[Scope], Outcome]], None]


def _job_runner(scope: Scope, run: Callable[[Scope], Outcome]) -> None:
    """Hand a run to the JobRunner. The name starts with "Import" so the activity dock
    leaves it to the import's own row (``useBackgroundJobs``)."""
    from backend.app.services.job_runner import get_job_runner

    get_job_runner().submit(run, scope, name=f"Import grouping {scope.job_id[:8]}")


def _inline(scope: Scope, run: Callable[[Scope], Outcome]) -> None:
    run(scope)


class RefinementScheduler:
    """Starts refinement of due scopes (jobs and partitions), at most one run per scope at a
    time.

    ``runner`` decides where a run happens: the JobRunner by default, inline (synchronous)
    for tests and the CLI. ``readiness`` is passed to every run.
    """

    def __init__(
        self,
        runner: Runner = _job_runner,
        readiness: Callable[[], Readiness] = embedding_readiness,
    ):
        self._runner = runner
        self._readiness = readiness
        self._lock = threading.Lock()
        self._running: set[Scope] = set()

    @classmethod
    def inline(cls, readiness: Callable[[], Readiness] = embedding_readiness):
        return cls(_inline, readiness)

    def due(
        self, job_ids: Iterable[str] | None = None, import_group_ids: Iterable[int] | None = None
    ) -> list[Scope]:
        """Due scopes: whole jobs first (a job due as a whole needs no partition passes),
        then partitions."""
        jobs = None if job_ids is None else list(job_ids)
        with _session() as db:
            whole = due_jobs(db, jobs)
            parts = due_partitions(db, jobs, import_group_ids)
        done = set(whole)
        return [Scope(j) for j in whole] + [p for p in parts if p.job_id not in done]

    def schedule(
        self, job_ids: Iterable[str] | None = None, import_group_ids: Iterable[int] | None = None
    ) -> list[Scope]:
        """Start refinement of the due scopes among ``job_ids`` (every due scope if None;
        with ``import_group_ids``, only those groups' partitions). Returns the scopes
        started; never raises (a failure is logged, the sweep retries)."""
        try:
            due = self.due(job_ids, import_group_ids)
        except Exception:
            logger.exception("Couldn't look up imports due for grouping refinement")
            return []
        started: list[Scope] = []
        for scope in due:
            with self._lock:
                if scope in self._running:
                    continue
                self._running.add(scope)
            try:
                self._runner(scope, self._run)
            except Exception:
                self._done(scope)
                logger.exception("Couldn't start grouping refinement of %s", scope)
                continue
            started.append(scope)
        return started

    def running(self) -> set[Scope]:
        with self._lock:
            return set(self._running)

    def _run(self, scope: Scope, progress_fn: Callable[..., None] | None = None) -> Outcome:
        try:
            return refine_job_groups(
                scope.job_id, progress_fn, partition=scope.partition, readiness=self._readiness
            )
        except Exception:
            logger.exception("Grouping refinement of %s failed; a sweep retries", scope)
            return Outcome.NOT_DUE
        finally:
            self._done(scope)

    def _done(self, scope: Scope) -> None:
        with self._lock:
            self._running.discard(scope)


_scheduler: RefinementScheduler | None = None
_scheduler_lock = threading.Lock()


def get_refinement_scheduler() -> RefinementScheduler:
    """The process-wide scheduler (tests install an inline one)."""
    global _scheduler
    with _scheduler_lock:
        if _scheduler is None:
            _scheduler = RefinementScheduler()
        return _scheduler


def schedule_refinements(
    job_ids: Iterable[str] | None = None, import_group_ids: Iterable[int] | None = None
) -> list[Scope]:
    """Start refinement of due scopes (every one if ``job_ids`` is None; with
    ``import_group_ids``, only partitions those groups belong to)."""
    return get_refinement_scheduler().schedule(job_ids, import_group_ids)
