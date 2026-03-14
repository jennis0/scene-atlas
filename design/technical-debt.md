# Code Quality Backlog

Deferred items from the 2026-03-04 full backend code review (simplify pass). Items are
grouped by theme and ordered roughly by impact vs effort.

The following fixes **were applied** in the same session and are not listed here:
- `finalize_import` now correctly treats `broken` as terminal — **DONE**
- `ImageStore.delete` TOCTOU race fixed (atomic `unlink`) — **DONE**
- `PipelineConfig` fallback duplication removed in task files
- `confirm_all_groups` now logs per-file skip warnings (matching `confirm_import`)
- Thumbnail fallback now logs a `warning` before serving full-res
- `confirm_review` uses a single bulk `UPDATE` instead of per-row ORM mutations
- `edit_group` new-group split no longer issues per-image DB queries
- Composite index on `(tags.category, tags.value)` added in migration 016

---

## 1. Move `_cleanup_import_images` out of the API layer

**Priority: High**
**Effort: Small (1–2 hours)**
**Files:** `backend/app/api/imports.py`, `backend/pipeline/ingestion.py`,
`backend/pipeline/maintenance.py`, `backend/app/services/deletion_service.py`

### Problem

`_cleanup_import_images` is a private function inside `backend/app/api/imports.py` — part
of the HTTP API layer. It is imported from the pipeline and maintenance layers in five places
via deferred `from backend.app.api.imports import _cleanup_import_images` calls:

- `pipeline/ingestion.py` lines ~1280, ~1314, ~1346 (`_finalize_import_job`)
- `pipeline/maintenance.py` lines ~249, ~348 (`expire_stale_jobs`, `mark_interrupted_jobs`)

This inverts the correct dependency direction: `api → pipeline/services`, not the reverse.
The function has no HTTP-specific logic — it queries the DB for Image rows attached to a
job, deletes their files from ImageStore and Qdrant, and removes the DB rows. It belongs
in a service module.

### Fix

Move `_cleanup_import_images` (and rename it, since it will no longer be private to one
module) into `backend/app/services/deletion_service.py` alongside `safe_delete_image`.
Update all five import sites to import from the service. Remove the deferred imports.

```python
# backend/app/services/deletion_service.py
def cleanup_import_images(job_id: str, db: Session) -> int:
    """Delete all Image rows (and their files) attached to an import job."""
    ...
```

---

## 2. Deduplicate `_FILE_MAP_NAME` / `_load_file_map`

**Priority: High**
**Effort: Small (30 minutes)**
**Files:** `backend/app/api/imports.py`, `backend/pipeline/ingestion.py`

### Problem

The constant `_FILE_MAP_NAME = ".file_map.json"` and the function `_load_file_map(staging_dir)`
are defined identically in both files. If the staging format ever changes, one copy will be
forgotten.

`_save_file_map` (writes the map) only exists in `imports.py`. All three belong together.

### Fix

Extract to a small shared module, e.g. `backend/app/services/staging.py`:

```python
FILE_MAP_NAME = ".file_map.json"

def load_file_map(staging_dir: Path) -> dict[str, str]:
    ...

def save_file_map(staging_dir: Path, mapping: dict[str, str]) -> None:
    ...
```

Both `imports.py` and `ingestion.py` import from there. The pipeline importing from
`app/services/` is fine — only importing from `app/api/` is the problematic direction.

---

## 3. Add a pipeline DB session helper

**Priority: Medium**
**Effort: Small (1 hour) but many touch-points**
**Files:** All `backend/pipeline/` scripts and several functions in `ingestion.py`

### Problem

Every pipeline function that needs a DB session independently repeats:

```python
engine = get_engine(settings.database_url)
SessionLocal = get_session_local(engine)
with SessionLocal() as db:
    ...
```

This two-liner appears ~30 times across the pipeline layer (10 times in `ingestion.py` alone,
plus `maintenance.py`, `backfill_grid_detection.py`, `retag_all_images.py`, etc.).
`get_engine` returns a cached engine so repeated calls are not expensive, but the pattern
clutters every function and makes connection-pool tuning a 30-site change.

### Fix

Add a context manager to `pipeline_config.py` or a new `backend/pipeline/db.py`:

```python
from contextlib import contextmanager

@contextmanager
def pipeline_db():
    """Yield a short-lived DB session for pipeline use."""
    engine = get_engine(settings.database_url)
    SessionLocal = get_session_local(engine)
    with SessionLocal() as db:
        yield db
```

Then each call site becomes:
```python
with pipeline_db() as db:
    ...
```

Roll this out incrementally — `maintenance.py` is the easiest starting point since its
functions are self-contained.

---

## 4. Deduplicate tag-cascade + FTS rebuild pattern in `tags.py`

**Priority: Medium**
**Effort: Small (30 minutes)**
**Files:** `backend/app/api/tags.py`

### Problem

Three endpoints in `tags.py` each independently execute this same ~12-line block after a
bulk tag write:

```python
affected_image_ids = [row[0] for row in db.query(Tag.image_id).filter(...).distinct().all()]
# ... bulk tag operation ...
if affected_image_ids:
    db.expire_all()
    affected_imgs = db.query(Image).options(subqueryload(Image.tags)).filter(...).all()
    for img in affected_imgs:
        rebuild_search_text(img, db)
invalidate_alias_cache()
```

Endpoints: `delete_tag_category`, `rename_tag_value`, `delete_tag_value`.

### Fix

Extract a helper:

```python
def _cascade_tag_change(db: Session, affected_image_ids: list[int]) -> None:
    """Reload affected images and rebuild their FTS search text."""
    if not affected_image_ids:
        return
    db.expire_all()
    imgs = db.query(Image).options(subqueryload(Image.tags)).filter(Image.id.in_(affected_image_ids)).all()
    for img in imgs:
        rebuild_search_text(img, db)
    invalidate_alias_cache()
```

---

## 5. Deduplicate tag vocabulary parsing

**Priority: Low**
**Effort: Medium (1–2 hours)**
**Files:** `backend/app/services/image_parser.py`, `backend/app/services/fts_service.py`

### Problem

Both `ImageParser._build_vocabulary` and `_load_alias_vocab` independently parse the same
`TagCategory.common_values` JSON format:

```python
# Both files contain this logic:
for entry in values:
    if isinstance(entry, str):
        canonical = entry.lower()
        # register canonical -> canonical
    elif isinstance(entry, dict):
        canonical = entry.get("value", "").lower()
        for alias in entry.get("aliases", []):
            # register alias -> canonical
```

They also both silently discard malformed JSON (`try/except json.JSONDecodeError`).

### Fix

Extract a shared `parse_tag_vocab_entries(values: list) -> dict[str, str]` function into
`backend/app/services/image_parser.py` (or a new `tag_vocab.py`), and have `fts_service.py`
import and call it.

---

## 6. N+1 queries in `get_active_imports`

**Priority: Medium**
**Effort: Small (30–60 minutes)**
**Files:** `backend/app/api/imports.py`

### Problem

`GET /imports/active` issues:
- 1 query for all `ImportJob` rows
- N queries for `ImportGroupJob` rows (one per job)

With 20 jobs in the 7-day window this is up to 21 queries. The endpoint is polled every
few seconds by the ActivityDock.

### Fix

```python
# One query for all group jobs across all relevant job IDs
all_job_ids = [j.id for j in all_jobs]
groups_by_job: dict[str, list[ImportGroupJob]] = defaultdict(list)
for grp in db.query(ImportGroupJob).filter(ImportGroupJob.job_id.in_(all_job_ids)).all():
    groups_by_job[grp.job_id].append(grp)
```

---

## 7. N+1 group lookup in `_save_image_to_db` (core import hot path)

**Priority: High**
**Effort: Medium (1–2 hours)**
**Files:** `backend/pipeline/ingestion.py`

### Problem

`_save_image_to_db` issues a `SELECT` on `ImageGroup` for every image in a batch. When
`batch_save_to_database` saves 16 images from the same group, this is 16 identical queries
in a single transaction. This is the core hot path for every import.

```python
# ingestion.py ~line 138 — called N times per batch
grp = db.query(ImageGroup).filter(
    ImageGroup.base_name == group_name,
    ImageGroup.author == author
).first()
```

### Fix

Resolve the group once per batch in `batch_save_to_database` and pass it into
`_save_image_to_db`, or cache it by `(base_name, author)` within a single DB session.
Since all images in a batch share the same group, the simplest approach is to pass an
optional `group` parameter:

```python
def _save_image_to_db(db: Session, image_data: dict, group: ImageGroup | None = None) -> int:
    ...
```

and resolve it once in `batch_save_to_database` before the loop.

---

## 8. ColorIndex loads entire `colors` table into memory

**Priority: Medium**
**Effort: Medium (half day)**
**Files:** `backend/app/services/color_search.py`

### Problem

`ColorIndex._refresh` loads every row from the `colors` table on every 60-second TTL
expiry:

```python
rows = db.query(Color.image_id, Color.color_hex).all()
```

At 5 colors per image and 50,000 images this is 250,000 rows loaded on every refresh.
The subsequent search is a pure O(N) linear scan. Additionally, `_cache` and `_loaded_at`
are updated non-atomically, creating a narrow window where a concurrent request could
see stale data.

### Fix options

**Option A (simple):** Move color search into a SQL query with a perceptual-distance
WHERE clause using indexed hex string comparison. Approximate color search by bucketing
hex values (e.g. reduce to 4-bit per channel before indexing).

**Option B (medium):** Keep the in-memory index but make the refresh atomic using a
`threading.Lock`. For very large libraries, add a configurable TTL or a max-row cap.

**Option C (architecture):** Store a precomputed LAB color value per Color row and add
a generated column or periodic materialized view. Query with a distance threshold using
a SQL expression. Eliminates the in-memory cache entirely.

Option B is the minimum viable fix; Option C is the long-term solution once the library
grows past ~10,000 images.

---

## 9. Five COUNT queries per `/facets` request

**Priority: Medium**
**Effort: Small (30 minutes)**
**Files:** `backend/app/api/search.py`

### Problem

The `/search/facets` endpoint issues five individual `COUNT` queries for grid stats:

```python
gridded_count = db.query(func.count(Image.id)).filter(reviewed, Image.gridded.is_(True)).scalar()
gridless_count = db.query(func.count(Image.id)).filter(reviewed, Image.gridded.is_(False)).scalar()
unknown_count  = db.query(func.count(Image.id)).filter(reviewed, Image.gridded.is_(None)).scalar()
square_count   = db.query(func.count(Image.id)).filter(reviewed, Image.gridded.is_(True), Image.grid_type == "square").scalar()
hex_count      = db.query(func.count(Image.id)).filter(reviewed, Image.gridded.is_(True), Image.grid_type == "hex").scalar()
```

This endpoint is called on every gallery page load (for the filter panel) and issues at
least 9 separate queries total.

### Fix

```python
from sqlalchemy import case

rows = (
    db.query(
        Image.gridded,
        Image.grid_type,
        func.count(Image.id),
    )
    .filter(reviewed)
    .group_by(Image.gridded, Image.grid_type)
    .all()
)
# Aggregate rows in Python into the required counts
```

---

## 10. N+1 Qdrant calls for reuse (dedup) images

**Priority: Low**
**Effort: Small (30 minutes)**
**Files:** `backend/pipeline/ingestion.py`

### Problem

When a batch contains duplicate images (reuse path), their existing Qdrant embeddings
are retrieved one-at-a-time:

```python
for prep in reuse_images:
    source_id = prep["reuse_embedding_from"]
    embedding = get_qdrant_service().get_embedding(source_id)  # one RPC per image
```

`QdrantClient.retrieve` accepts a list of IDs. For a batch of 20 duplicates this is 20
serial round-trips.

### Fix

Add a `get_embeddings(ids: list[int]) -> dict[int, list[float]]` method to `QdrantService`
and call it once per batch:

```python
source_ids = [prep["reuse_embedding_from"] for prep in reuse_images]
embeddings_by_id = get_qdrant_service().get_embeddings(source_ids)
```

---

---

## 11. Remove `continue-on-error` from CI security scanning

**Priority: Medium**
**Effort: Small (30 minutes)**
**Files:** `.github/workflows/ci.yml`
**Target:** 2 weeks after merge (2026-03-28)

### Problem

The `pip-audit`, `bandit`, and `npm audit` CI steps all use `continue-on-error: true`,
so findings never fail the build. This was necessary to establish a baseline without
blocking CI, but it means findings will be permanently ignored unless someone actively
reviews CI logs on green builds.

### Fix

1. Triage the initial findings (fix or suppress known issues).
2. Remove `continue-on-error: true` from all three steps.
3. Add targeted `bandit` exclusions (via `bandit.yaml` or `# nosec` comments) for
   any remaining acceptable findings.

---

## Priority Summary

| # | Item | Priority | Effort |
|---|------|----------|--------|
| 1 | Move `_cleanup_import_images` to service layer | High | Small |
| 2 | Deduplicate `_FILE_MAP_NAME` / `_load_file_map` | High | Small |
| 7 | N+1 group lookup in `_save_image_to_db` | High | Medium |
| 3 | Pipeline DB session helper | Medium | Small |
| 4 | Tag-cascade + FTS rebuild deduplication | Medium | Small |
| 6 | N+1 in `get_active_imports` | Medium | Small |
| 8 | ColorIndex full-table load | Medium | Medium |
| 9 | Five COUNT queries in `/facets` | Medium | Small |
| 5 | Tag vocabulary parsing deduplication | Low | Medium |
| 10 | N+1 Qdrant reuse calls | Low | Small |
