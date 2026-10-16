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
job, deletes their files from ImageStore and LanceDB, and removes the DB rows. It belongs
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

**Note:** The `backend/app/data/vocabulary.py` loader now handles JSON→DB format conversion for seeding and pack imports, but the DB-side `common_values` parsing in `image_parser.py` and `fts_service.py` remains duplicated.

---

## 6–10. Query scaling (resolved 2026-10-17, branch `perf/search-and-queries`)

Re-audited against a synthetic 56k-image library (`python -m stress_tests.library_scale`,
the size of the reference library). Query counts are now pinned by tests using the
`query_counter` fixture (`backend/tests/conftest.py`): `integration/test_query_counts.py`
for read endpoints and the "Query counts" section of `integration/test_ingest_pipeline.py`.

| # | Original item | Outcome |
|---|---------------|---------|
| 6 | N+1 in `get_active_imports` | **Not applicable.** That endpoint went with ADR-018; its successor `GET /imports` already summarises all jobs with two grouped queries (`_summaries`). Now pinned by a test. |
| 7 | N+1 group lookup in `_save_image_to_db` | **Already fixed by the redesign** (`ingest_process._resolve_group` caches per batch). The same pattern remained elsewhere and is **DONE**: `commit_batch` and `record_failures` did one `db.get(ImportItem)` per item (now one query per batch), `plan_job` flushed once per group, and `undo_job` ran two queries per created group and loaded every deleted image's tags and colours. |
| 8 | ColorIndex loads the whole `colors` table | **DONE.** Still in memory (a SQL distance query would need LAB columns, i.e. a model change, and gives no real benefit at this size), but stored as numpy arrays: 65 MB → 9 MB retained (114 → 18 MB peak) and 146 → ~10 ms per colour at 56k images. Refresh is atomic. Matching ids are passed to SQL via `json_each` (`search_service.id_set`), as were search candidates: binding one parameter per id fails above SQLite's 32,766-variable limit. |
| 9 | Five COUNT queries per `/facets` | **Already collapsed** into one GROUP BY before this pass; the total-count query is now derived too (7 → 6 queries). The real cost was the tag and colour aggregates: migration 022 adds covering indexes, 1.0 s → 0.27 s. |
| 10 | N+1 LanceDB calls for reuse images | **Not applicable.** ADR-018 has no embedding-reuse path: duplicates become `duplicate` items without an image, and "Import as new copy" embeds normally in the batch call. Group delete/edit no longer make one LanceDB call per image either (they use `delete_image_rows`). |

Other hot-path N+1s fixed in the same pass: grouped search/browse (hero and mosaic queries
per group: 303 → 7 queries for 50 groups), `GET /images/` and `/images/{id}/scenes`
(three lazy loads per image), `GET /groups/{id}` (joined tags × colours rows),
`GET /tags/values/{category}` (loaded every Tag row), and the tag rename/delete cascade
(one IN list with every affected id). See `design/search.md` for the search structure.

Known remaining costs, acceptable for now: `/search/groups` with a query and `limit=500`
takes ~1.3 s at 56k images, mostly serialising ~2,500 images with tags and colours; one
INSERT per import group at seal time (SQLAlchemy can't batch `INSERT … RETURNING` on SQLite).

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

## 12. Upgrade GitHub Actions to Node.js 24 versions

**Priority: Medium**
**Effort: Small (1 hour + CI testing)**
**Deadline:** 2026-06-02 (GitHub forces Node.js 24 after this date)
**Files:** `.github/workflows/ci.yml`

### Problem

All GitHub Actions in the CI pipeline use versions that run on Node.js 20, which GitHub
is deprecating. After 2026-06-02, actions will be forced to run on Node.js 24.

### Fix

Upgrade all actions to their latest major versions:
- `actions/checkout` v4 → v6
- `actions/setup-node` v4 → v6
- `actions/setup-python` v5 → v6
- `astral-sh/setup-uv` v4 → v7
- `actions/upload-artifact` v4 → v7
- `actions/cache` v4 → v5

Major version bumps may have breaking changes in inputs/outputs — test each job
after upgrading.

---

## Priority Summary

| # | Item | Priority | Effort |
|---|------|----------|--------|
| 1 | Move `_cleanup_import_images` to service layer | High | Small |
| 2 | Deduplicate `_FILE_MAP_NAME` / `_load_file_map` | High | Small |
| 3 | Pipeline DB session helper | Medium | Small |
| 4 | Tag-cascade + FTS rebuild deduplication | Medium | Small |
| 5 | Tag vocabulary parsing deduplication | Low | Medium |
| 6–10 | Query scaling | — | **Done** |
| 11 | Remove `continue-on-error` from CI security scanning | Medium | Small |
| 12 | Upgrade GitHub Actions to Node.js 24 versions | Medium | Small |
