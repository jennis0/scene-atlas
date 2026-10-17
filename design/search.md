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

The frontend strips the prefix before sending `query`, `semantic_only`, and `text_only` params to the API.

## Data Flow

```
User types query in search bar
    │
    ▼
Frontend (GalleryHeader.tsx)
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
    └── Client-side relevance slider filters on CLIP score
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
| `medium` | SigLIP2-base-patch16-224, vision fp16, text int8 | 768 | jennis0/scene-atlas-medium | Default with GPU |
| `large` | SigLIP2-so400m-patch14-384, vision fp16/fp16 | 1152 | jennis0/scene-atlas-large | GPU strongly recommended |

A dev fallback path (`backend/models/{name}/`) is checked before the APP_DATA_DIR path, allowing developers to test with locally exported models without a HF download.

Each model directory (whether in APP_DATA_DIR or backend/models/) contains:
- `manifest.json` — model parameters (embedding dim, image size, normalization, tokenizer config)
- `clip_vision_encoder.onnx` and `clip_text_encoder.onnx`
- `tokenizer/` subdirectory
- `version.json` — HF commit SHA + download timestamp (completion marker, APP_DATA_DIR only)

### Model Configuration Flow

At startup (`main.py`), the manifest is read to derive:
1. `vector_size` — set from `manifest.embedding_dim`
2. `vector_collection_name` — scoped to model: `embeddings_{model_name}` (e.g. `embeddings_small`)

Switching models creates a new LanceDB table — the old table is preserved (not deleted). Run `rebuild_all_embeddings(force=True)` after switching to populate the new table. The `POST /api/v1/models/active` endpoint handles the full switch sequence automatically.

### Inference

ONNX Runtime with automatic provider selection: CUDA → DirectML → CoreML → CPU (configurable via `INFERENCE_DEVICE` env var). The `ClipService` is lazy-loaded as a singleton on first use.

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

**Population during ingestion** (`backend/pipeline/ingestion.py`):
1. `batch_generate_clip_embeddings(image_paths)` — CLIP encodes images in batched forward passes
2. `batch_save_to_vector_db(items)` — upserts `{image_id, embedding, metadata}` rows in a single call
3. Each row stores payload: `image_id`, `filename`, `author`, `base_name`

**Single-image flow** (`save_to_vector_db` in `persistence.py`):
- Used by `process_single_image()` for one-off additions
- Calls `lancedb_service.add_image_embedding(image_id, embedding, metadata)`

**Deletion** (`backend/app/services/deletion_service.py`):
- Single image: `lancedb_service.delete_image_embedding(image_id)`
- Batch (failed import cleanup): `lancedb_service.delete_embeddings(image_ids)`
- Cascade deletion removes the LanceDB row alongside SQLite row and filesystem files

**Desync detection** (`backend/pipeline/maintenance.py`):
- Scheduled daily: compares `images` row count vs LanceDB row count
- Logs warning if delta exceeds 10 images
- Repair: run `write_new_embeddings` pipeline script

**Full rebuild** (`backend/pipeline/write_new_embeddings.py`):
- `rebuild_all_embeddings()` — deletes the entire LanceDB table and regenerates all embeddings from stored images
- Used after model changes or to repair desync

**Backup:**
- `lancedb_service.backup_storage(target_dir)` — copies the LanceDB storage directory (called by the scheduled backup task)

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
| `colors` | Cylindrical-HSL colour distance via `color_index` (OR across colours) |

**Group browse** (no query) applies each filter separately as "the group has at
least one image that matches", so `image_types=scene&gridded=true` keeps a group with
one scene and a different gridded battlemap. Authors match the group's own author;
an `exclude_tags` entry keeps groups with at least one image without that tag.

**Large id sets.** Colour matches and candidate pools can exceed SQLite's limit of
32,766 bound parameters per statement on a large library, so they are passed as one
JSON parameter (`id_set()`, `json_each`) rather than as an `IN (?, ?, …)` list.

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

## Colour Index

`color_search.ColorIndex` keeps every `(image_id, colour)` pair in memory as numpy
arrays (~16 bytes per colour: ~5 MB for 56k images at 5 colours each), reloaded
from SQLite when `color_cache_ttl_seconds` (60 s) has passed. A colour query is a
vectorised distance over the arrays (~10 ms at 56k images). A SQL-side search would
need precomputed colour coordinates in the schema and isn't needed at this size.

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
| `backend/app/services/color_search.py` | LAB colour distance search |
| `frontend/src/hooks/useGallerySearch.ts` | Search state management, prefix parsing |
| `frontend/src/components/GalleryHeader.tsx` | Search input UI, mode indicator icon |
| `frontend/src/lib/api/searchApi.ts` | API client for search endpoints |
| `backend/pipeline/ingestion.py` | Embedding generation + LanceDB population during ingest |
| `backend/pipeline/persistence.py` | `batch_save_to_vector_db()`, `save_to_vector_db()` |
| `backend/pipeline/write_new_embeddings.py` | Full LanceDB rebuild from stored images |
| `backend/pipeline/maintenance.py` | Scheduled desync detection (DB vs LanceDB count) |
| `backend/app/services/deletion_service.py` | Cascade deletion (SQLite + LanceDB + filesystem) |
| `backend/alembic/versions/001_initial_schema.py` | FTS5 table + trigger creation |
| `backend/alembic/versions/015_search_ranking.py` | Tokenizer upgrade (diacritics) |
