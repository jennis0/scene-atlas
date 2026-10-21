# Search Architecture

## Overview

Scene Atlas uses **hybrid search** combining three ranked result lists — FTS5 full-text, CLIP semantic, and alias expansion — merged via Reciprocal Rank Fusion (RRF). The frontend sends a single query string; the backend runs all three search paths, fuses their rankings, applies SQL filters, and returns paginated results.

## Search Modes

Users control which search paths run via a prefix on the query string:

| Prefix | Mode | What runs | Use case |
|--------|------|-----------|----------|
| _(none)_ | Hybrid | FTS5 + CLIP + alias | Default — best for most queries |
| `~` | Semantic-only | CLIP only | Visual similarity ("a dark cave with water") |
| `=` | Text-only | FTS5 only | Exact keyword matching, faster |

`useGallerySearch.ts` strips the prefix before sending `query`, `semantic_only`, and `text_only` params to the API.

## Data Flow

```
User types query in search bar
    │
    ▼
Frontend (useGallerySearch.ts)
    ├── Strip prefix (~, =)
    ├── Build SearchParams
    └── GET /api/v1/search/groups (or /search/)
            │
            ▼
    api/search.py — parses params into SearchFilters + SearchMode
            │
            ▼
    services/search_service.py
    ├── image_conditions() / group_conditions()
    │   └── SQL WHERE clauses from filters
    │       (image_type, media_type, gridded, authors,
    │        tags, exclude_tags, colors, etc.)
    │
    ├── rank_candidates()
    │   ├── [unless semantic_only] fts_search(query)
    │   │   ├── _sanitize_fts_query()     ← preserves "quoted phrases"
    │   │   ├── AND pass (primary)
    │   │   └── OR pass (fallback)
    │   ├── [if text hits] get_alias_expansions(query)
    │   │   └── fts_search_terms(aliases)  ← OR semantics, 0.5× weight
    │   ├── [unless text_only] clip_service.encode_text(query)
    │   │   └── lancedb_service.search_similar(embedding)
    │   └── fuse_rankings()  ← Reciprocal Rank Fusion
    │
    ├── Filter candidates in SQL as (id, sort key) rows
    ├── Sort (by relevance, name, or created_at), paginate ids
    └── _load_images(page ids)  ← tags/colours/group in a fixed
                                   number of queries
            │
            ▼
    Frontend receives images[] + scores{}
    └── Client-side relevance slider filters on RRF score
```

## FTS5 Text Search

### Virtual Table

```sql
CREATE VIRTUAL TABLE image_fts USING fts5(
    name, filename, author, search_text,
    content='images', content_rowid='id',
    tokenize='porter unicode61 remove_diacritics 2'
);
```

**Tokenizer chain:**
- `porter` — Stemmer: "forests" matches "forest", "mining" matches "mine"
- `unicode61` — Case-folding and Unicode normalisation
- `remove_diacritics 2` — "Cepeku" matches "Čepeku"

### Column Weights (BM25)

| Column | Weight | Rationale |
|--------|--------|-----------|
| `name` | 10.0 | Title matches are highest priority |
| `search_text` | 5.0 | Tag values and metadata |
| `filename` | 1.0 | Useful fallback |
| `author` | 0.5 | Rarely matches user intent |

BM25 scores are **negative** — more negative = better match.

### Query Processing

`_sanitize_fts_query(raw)` sanitizes user input:
1. Strips FTS5 boolean operators (`AND`, `OR`, `NOT`)
2. Extracts balanced `"quoted phrases"` and sanitizes their interiors
3. Strips all remaining non-word/non-space characters from loose text
4. Single-word phrases degrade to plain terms; unbalanced quotes become loose words

### Multi-Word Strategy

For queries with 2+ tokens, `fts_search()` runs two passes:
1. **AND pass** — all terms/phrases must match (implicit in FTS5 space-separated syntax)
2. **OR pass** — any term/phrase matches, appended after AND results

AND results appear first in the ranked list, so RRF naturally scores them higher.

### Phrase Matching

Quoted phrases use FTS5's native phrase matching:
- `"forest shrine"` — matches only when "forest" is immediately followed by "shrine"
- `"forest shrine" cave` — phrase AND + regular term AND
- Words inside phrases are **excluded from alias expansion**

### Search Text Construction

`build_search_text()` in `image_parser.py` builds the indexed text at ingest time:
- CamelCase splitting: `"desertCanyon"` → `"desert Canyon"`
- Separator replacement: underscores, hyphens, dollar signs → spaces
- Components: image name + filename + author + tag values + subgroup paths

## Alias Expansion

Tag categories define a vocabulary with optional aliases (e.g. "rainy" → "rain"). `get_alias_expansions()` looks up synonyms for loose query words and runs a separate FTS5 pass with OR semantics.

- **Vocabulary source:** `TagCategory.common_values` in the database
- **Cache:** Module-level dict with 5-minute TTL (avoids per-request DB hit)
- **FTS5 pass:** Uses `fts_search_terms()` (OR join, bypasses sanitizer's OR-stripping)
- **RRF weight:** 0.5× (lower than text, prevents alias dilution)
- **Phrase exclusion:** Words inside `"quoted phrases"` are not alias-expanded

## CLIP Semantic Search

### Model Selection

Three models are offered, each hosted on HuggingFace and downloaded on demand to `APP_DATA_DIR/models/{name}/`. The active model is resolved in priority order:
1. `EMBEDDING_MODEL` env var (dev/operator override)
2. `active_model` key in `app_settings` DB (set via `POST /api/v1/models/active`)
3. Auto-detect: GPU present → `medium`, CPU-only → `small`

| Name | Architecture | Embedding Dim | HF Repo | Notes |
|------|-------------|---------------|---------|-------|
| `small` | CLIP ViT-B/32 (laion2B), vision fp16, text int8 | 512 | jennis0/scene-atlas-small | Default without GPU |
| `medium` | SigLIP2-base-patch16-384 fine-tune, w4a16 | 768 | jennis0/scene-atlas-medium | Default with GPU |
| `large` | SigLIP2-large-patch16-384 fine-tune, w8a16 | 1024 | jennis0/scene-atlas-large | GPU strongly recommended |

`clip_service._default_models_dir()` uses `APP_DATA_DIR/models/{name}/` when it contains a `manifest.json`. Otherwise, in a non-frozen (dev) run it falls back to `backend/models/{name}/`, so developers can test locally exported models without a HF download. Frozen builds never use the dev fallback.

Each model directory (whether in APP_DATA_DIR or backend/models/) contains:
- `manifest.json` — model parameters (embedding dim, image size, normalization, tokenizer config)
- `clip_vision_encoder.onnx` and `clip_text_encoder.onnx`
- `tokenizer/` subdirectory
- `version.json` — HF commit SHA + download timestamp (completion marker, APP_DATA_DIR only)

### Model Configuration Flow

At startup (`main.py`), `vector_size` is set from `manifest.embedding_dim`. The LanceDB table is scoped to the model: `get_collection_name(model)` → `embeddings_{model_name}` (e.g. `embeddings_small`), used by `get_lancedb_service()` and `reload_lancedb_service()`.

Switching models creates a new LanceDB table — the old table is preserved (not deleted). Run `rebuild_all_embeddings(force=True)` after switching to populate the new table. The `POST /api/v1/models/active` endpoint handles the full switch sequence automatically.

### Inference

ONNX Runtime with automatic provider selection: CUDA → DirectML → CoreML → CPU (configurable via `INFERENCE_DEVICE` env var; see `ort_providers.py`). The model loads on a background thread at startup (`start_clip_background_load()`); `get_clip_service()` blocks until it is ready, and `get_clip_unavailable_reason()` reports a missing or failed model without blocking.

### Vector Database

LanceDB runs **in-process** (disk-backed, memory-mapped, no Docker). Thread-safe: writes serialised via `RLock`, reads lock-free.

- **Table:** `embeddings_{EMBEDDING_MODEL}` (model-scoped)
- **Distance metric:** Cosine distance (service converts to similarity by subtracting from 1.0)
- **Score threshold:** model-dependent (configured per model in the model registry via `get_semantic_threshold()`)
- **Candidate pool:** Image search: text candidates = limit×10, alias and semantic candidates = limit×3. Group search: max(limit×20, 1000) for all candidate types.

### Query Flow

1. `clip_service.encode_text(query)` → N-dim normalised vector (depends on active model; see model table above)
2. `lancedb_service.search_similar(embedding, limit, threshold)` → `[{image_id, score}]`

### Vector Population & Maintenance

LanceDB is the **semantic search index, not the source of truth** — SQLite is authoritative. If LanceDB loses data, embeddings can be regenerated from images.

**Population during ingestion** (`backend/pipeline/ingest_process.py`, see [ingestion.md](ingestion.md)):
1. `embed()` — `embedding_generation.batch_generate_clip_embeddings()` encodes a batch in one call
2. Images are committed to SQLite first, then `write_vectors()` calls `lancedb_service.batch_add_embeddings()`
3. Each row stores `image_id`, `filename`, `author`, `base_name`
4. A failed vector write is logged and left for reconciliation; the images stay committed

**Deletion** (`backend/app/services/deletion_service.py`):
- Single image: `lancedb_service.delete_image_embedding(image_id)`
- Batch (group/bulk deletes): `lancedb_service.delete_embeddings(image_ids)` in chunks
- Cascade deletion removes the LanceDB row alongside SQLite row and filesystem files

**Reconciliation** (`backend/pipeline/vector_reconcile.py`, `reconcile_vectors()`):
- Compares the SQLite image id set with the LanceDB id set (ids, not counts)
- Re-embeds images missing a vector from their stored thumbnails; images without a thumbnail are counted as `unrepairable`
- Deletes vectors whose image no longer exists
- Runs once at startup after the model is ready (via the job runner) and every 24 h via the scheduler

**Full rebuild** (`backend/pipeline/write_new_embeddings.py`):
- `rebuild_all_embeddings()` — clears the active model's table, then runs `reconcile_vectors`, which re-embeds every image from its medium thumbnail (what imports embed) and writes batch by batch. A rebuild that stops part-way is finished by the next startup reconciliation.
- Reports per-image progress ("320 of 4,761 images"); stops with `VectorWriteError` if LanceDB refuses `MAX_FAILED_WRITES` (3) batches in a row, rather than reporting progress while saving nothing.
- Without `force`, skipped when every image already has a vector
- Used after model changes (`POST /api/v1/models/active` runs it)
- Until October 2026 it re-encoded the original files and wrote 100-row batches; a model switch on a 4,761-image library saved nothing (every LanceDB merge failed with "Spill has sent an error") while showing 50%.

**Backup:**
- `lancedb_service.backup_storage(target_dir)` — copies the LanceDB storage directory (called by `maintenance.backup_database()`, scheduled every 24 h)

## Reciprocal Rank Fusion (RRF)

Merges three independently-ranked result lists into a single score:

```
score(image) = Σ  weight_i / (K + rank_i)
               i ∈ {text, alias, semantic}
```

| Parameter | Value | Notes |
|-----------|-------|-------|
| K | 60 | Standard RRF dampening constant |
| Text weight | 1.1 | Slight boost for keyword matches |
| Alias weight | 0.5 | Lower to prevent synonym dilution |
| Semantic weight | 1.0 | Baseline |

Images only contribute to lists they appear in. The merged score determines final ordering when `sort_by=relevance`.

**Client-side scores:** The API returns RRF merged scores (not raw CLIP scores) in the `scores` dict. The frontend relevance slider filters on these RRF scores (typical range 0–0.05).

## SQL Filters

After RRF produces a candidate set, SQL filters narrow it (without a query they
apply to the whole library):

| Filter | Semantics |
|--------|-----------|
| `image_types` | IN filter (battlemap, scene) |
| `media_types` | IN filter (image, video) |
| `gridded` / `gridded_unknown` | Boolean / IS NULL |
| `grid_type` | Exact match (square, hex) |
| `authors` | OR across values |
| `exclude_authors` | NOT IN |
| `tags` | OR within category, AND across categories |
| `exclude_tags` | NOT IN (per tag) |
| `colors` | CIE76 delta E in SQL via `color_match_ids` (OR across colours) |

**Group browse** (no query) applies each filter separately as "the group has at
least one image that matches", so `image_types=scene&gridded=true` keeps a group with
one scene and a different gridded battlemap. Authors match the group's own author;
an `exclude_tags` entry keeps groups with at least one image without that tag.

**Large id sets.** Candidate pools can exceed SQLite's limit of 32,766 bound
parameters per statement on a large library, so they are passed as one JSON
parameter (`id_set()`, `json_each`) rather than as an `IN (?, ?, …)` list. Colour
matches never leave SQLite: they are an `IN (subquery)`.

## Loading and Query Counts

Search never loads full Image objects for every candidate: candidates are filtered
and sorted as `(id, name, created_at)` rows, then only the returned page is loaded
with `selectinload` (tags, colours) and `joinedload` (group). Group heroes, mosaics
and mosaic top-ups come from `row_number() OVER (PARTITION BY group_id …)` queries,
so each request costs a fixed number of queries whatever the page size (about 5–8;
`selectinload` adds one query per 500 images loaded). This is pinned by
`backend/tests/integration/test_query_counts.py`; response shapes and ordering are
pinned by golden tests (`test_search_characterisation.py`, regenerate with
`UPDATE_SEARCH_GOLDEN=1` only for intended changes).

To check a change at real-library scale, build a synthetic library and benchmark
the read paths: `uv run python -m stress_tests.library_scale build 56000 --db /tmp/lib.db`
then `... run --db /tmp/lib.db`.

## Colour Search

Every `colors` row stores its CIELAB (D65) coordinates in `lab_l`, `lab_a`, `lab_b`,
set by a `@validates("color_hex")` hook on the model (`backend/app/colorspace.py`
does the conversion), so every code path that creates a `Color` gets them; raw SQL
inserts (the stress library) must compute them too. Migration 024 added and
backfilled the columns.

A colour filter matches an image when any of its dominant colours is within
`color_distance_threshold` (app setting, CIE76 delta E, default 25) of any target
colour. `color_search.color_match_ids` builds the query: a range on `lab_l` that
`ix_colors_lab (lab_l, lab_a, lab_b, image_id)` answers, then the `lab_a`/`lab_b`
box and the exact squared distance, all from the covering index. Targets whose
`lab_l` ranges overlap share one range scan; separate scans would visit shared rows
once per target. Search embeds the query as `Image.id IN (subquery)`, so the ids
are never materialised in Python. `L*` leads the index because extracted map colours
are mostly low-chroma, so `a*`/`b*` ranges are less selective (checked with
`EXPLAIN QUERY PLAN` and timings on real colour distributions).

**Threshold.** Until migration 024 colour search used distance in an HSL cylinder
(default 0.35) from an in-memory numpy index refreshed on a TTL. The delta E
default was calibrated on dominant colours extracted from 3,000 real maps and
scenes: 25 gives the closest match counts to the old default (median ratio 1.0 for
colours taken from images, 1.2 for the filter palette; Jaccard overlap 0.80 and
0.43, since the two metrics have different shapes). The migration maps 0.35 to 25
and scales custom values by the same ratio. The metrics disagree most on greys and
pale tints: HSL treats a pale cream as fully saturated and far from white, and a
mid grey as close to white; delta E does the opposite.

That default is loose. With real colour distributions a grey target matches ~80% of
the library at delta E 25 (the old 0.35 matched about as many). Most index rows then
fall in the `L*` range, so at 56k images the colour query costs ~40 ms for one colour
and ~80 ms for three, and a colour-filtered browse is 70–140 ms slower than with
the old in-memory index (which was faster per query but reloaded the whole table,
~600 ms, every minute). At delta E 12 the query takes 10–30 ms, matches ~30%, and
browse is as fast as before. Benchmark with `stress_tests/library_scale.py`
(colour cases) before changing the default.

**Settings.** Settings → General → Colour match offers Close (12), Similar (25,
the default) and Broad (40) (`COLOR_MATCH_OPTIONS` in `SettingsTabContent.tsx`).
Any value from 0 to 100 can still be set through `PATCH /settings/`; a value that
isn't one of the three shows no option selected.

## FTS5 Index Maintenance

### Triggers (auto-sync)

Three SQLite triggers keep `image_fts` in sync with the `images` table:
- `image_fts_ai` — AFTER INSERT: adds new row to FTS
- `image_fts_ad` — AFTER DELETE: removes row from FTS
- `image_fts_au` — AFTER UPDATE: delete-then-insert (FTS5 content sync pattern)

### Maintenance Functions

| Function | Purpose |
|----------|---------|
| `backfill_search_text(db)` | Populate `search_text` for all images missing it. Drops triggers during bulk update, rebuilds afterwards |
| `fts_rebuild(db)` | Full FTS5 index rebuild (`INSERT INTO image_fts(image_fts) VALUES ('rebuild')`) |
| `rebuild_search_text(image, db)` | Single-image re-index after tag changes. Recalculates `search_text` and flushes to trigger `image_fts_au` |

## Key Files

| File | Responsibility |
|------|---------------|
| `backend/app/api/search.py` | Search API endpoints: parameter parsing, error mapping |
| `backend/app/services/search_service.py` | Filters, ranking, RRF fusion, image/group search, facets |
| `backend/app/services/fts_service.py` | FTS5 query building, sanitization, alias expansion, index maintenance |
| `backend/app/services/clip_service.py` | CLIP model loading, text/image encoding |
| `backend/app/services/lancedb_service.py` | LanceDB disk-backed vector DB client |
| `backend/app/services/image_parser.py` | `build_search_text()`, filename/metadata parsing |
| `backend/app/services/color_search.py` | `color_match_ids`: SQL delta E colour search |
| `backend/app/colorspace.py` | sRGB hex to CIELAB conversion |
| `frontend/src/hooks/useGallerySearch.ts` | Search state management, prefix parsing |
| `frontend/src/components/GalleryHeader.tsx` | Search input UI, mode indicator icon |
| `frontend/src/lib/api/searchApi.ts` | API client for search endpoints |
| `backend/pipeline/ingest_process.py` | Embedding generation + LanceDB writes during ingest |
| `backend/pipeline/tasks/embedding_generation.py` | `batch_generate_clip_embeddings()` |
| `backend/pipeline/vector_reconcile.py` | SQLite/LanceDB id reconciliation (startup + every 24 h) |
| `backend/pipeline/write_new_embeddings.py` | Full LanceDB rebuild from stored images |
| `backend/pipeline/maintenance.py` | Scheduled SQLite + LanceDB backups, orphaned file sweep |
| `backend/app/services/deletion_service.py` | Cascade deletion (SQLite + LanceDB + filesystem) |
| `backend/alembic/versions/001_initial_schema.py` | FTS5 table + trigger creation |
| `backend/alembic/versions/015_search_ranking.py` | Tokenizer upgrade (diacritics) |
