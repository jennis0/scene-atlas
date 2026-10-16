# Code Quality Backlog

Deferred items from the 2026-03-04 full backend code review (simplify pass). Items are
grouped by theme and ordered roughly by impact vs effort.

The following fixes **were applied** in the same session and are not listed here:
- `ImageStore.delete` TOCTOU race fixed (atomic `unlink`) — **DONE**
- `PipelineConfig` fallback duplication removed in task files
- Thumbnail fallback now logs a `warning` before serving full-res
- `edit_group` new-group split no longer issues per-image DB queries
- Composite index on `(tags.category, tags.value)` added in migration 016

Items 1, 2, 6, 7 and 10 (`_cleanup_import_images` placement, `.file_map.json` helpers,
N+1 in `get_active_imports`, N+1 group lookup in `_save_image_to_db`, N+1 LanceDB reuse
calls) were **removed** with the code they described when the import pipeline was replaced
(ADR-018). Numbering is kept stable.

---

## 3. Add a pipeline DB session helper

**Priority: Medium**
**Effort: Small (1 hour) but many touch-points**
**Files:** All `backend/pipeline/` scripts

### Problem

Every pipeline function that needs a DB session independently repeats:

```python
engine = get_engine(settings.database_url)
SessionLocal = get_session_local(engine)
with SessionLocal() as db:
    ...
```

This two-liner still appears ~15 times across the pipeline layer (`backfill_grid_detection.py`, `retag_all_images.py`, etc.).
`get_engine` returns a cached engine so repeated calls are not expensive, but the pattern
clutters every function and makes connection-pool tuning a many-site change.

**Partly done:** `backend/pipeline/db.py:pipeline_db()` exists and is used by `maintenance.py`
and `vector_reconcile.py`; the remaining call sites still need migrating. (The ingest pipeline
uses its own `ingest_queue.write_session()` for `BEGIN IMMEDIATE` transactions.)

### Fix

The helper in `backend/pipeline/db.py` (it also commits on clean exit and rolls back on error):

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
| 3 | Pipeline DB session helper | Medium | Small |
| 4 | Tag-cascade + FTS rebuild deduplication | Medium | Small |
| 8 | ColorIndex full-table load | Medium | Medium |
| 9 | Five COUNT queries in `/facets` | Medium | Small |
| 5 | Tag vocabulary parsing deduplication | Low | Medium |
| 11 | Remove `continue-on-error` from CI security scanning | Medium | Small |
| 12 | Upgrade GitHub Actions to Node.js 24 versions | Medium | Small |
