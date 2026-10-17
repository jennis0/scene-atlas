# Data Storage

## Overview

Three storage backends:
1. **SQLite** — relational metadata (images, groups, tags, colours, import jobs, settings). The source of truth.
2. **LanceDB** — vector embeddings for semantic search. Derived; can be rebuilt by re-encoding images.
3. **Filesystem (ImageStore)** — original files and thumbnails.

Schema changes are Alembic migrations in `backend/alembic/versions/`, applied by `init_db()` at startup. A test fails if the ORM models drift from the migrated schema.

## SQLite Database

**Location:** `{APP_DATA_DIR}/battlemap.db` (`settings.database_url` is always derived from `app_data_dir`). Connections use WAL mode, `busy_timeout=10000` and `synchronous=NORMAL`.

### Schema

Physical column names are shown; ORM attribute aliases are noted.

```
images
  id               INTEGER PK
  filename         TEXT NOT NULL       -- Original filename (display only)
  storage_key      TEXT NOT NULL       -- Key into the image store (indexed, not unique)
  name             TEXT                -- Display name
  author           TEXT
  variant_group_id INTEGER FK → variant_groups.id   -- ORM: group_id
  width, height    INTEGER
  file_size        INTEGER             -- Bytes
  gridded          BOOLEAN             -- True / False / NULL (unknown)
  grid_width       INTEGER             -- Tile count
  grid_height      INTEGER             -- Tile count
  grid_type        TEXT                -- "square" | "hex" | NULL
  grid_confidence  FLOAT               -- 0.0–1.0; NULL = from filename
  sub_variant      TEXT                -- ORM: subgroup
  content_hash     TEXT(64)            -- SHA-256 of the original bytes
  stored_hash      TEXT(64)            -- SHA-256 of the stored file
  pixel_hash       TEXT(64)            -- Hash of canonical decoded pixels (NULL for videos
                                       --   and JPEGs above pixel_hash_max_pixels)
  phash            INTEGER             -- 64-bit perceptual hash (signed); advisory only
  search_text      TEXT                -- Pre-tokenised text for FTS5 (CamelCase-split)
  media_type       TEXT DEFAULT 'image'      -- "image" | "video"
  image_type       TEXT DEFAULT 'battlemap'  -- "battlemap" | "scene"
  import_job_id    TEXT FK → import_jobs.id  -- NULL for images that predate import jobs
  thumbnail_key    TEXT                -- Medium thumbnail key
  created_at, updated_at  DATETIME

variant_groups                         -- ORM: ImageGroup
  id               INTEGER PK
  base_name        TEXT NOT NULL
  author           TEXT
  primary_image_id INTEGER FK → images.id
  image_count      INTEGER NOT NULL DEFAULT 0   -- Maintained by triggers on images
  created_at       DATETIME

tags
  id               INTEGER PK
  image_id         INTEGER FK → images.id
  category         TEXT NOT NULL       -- e.g. "lighting"
  value            TEXT NOT NULL       -- e.g. "night"
  confidence       FLOAT DEFAULT 1.0
  source           TEXT DEFAULT 'manual'   -- "auto" | "manual"
  created_at       DATETIME

tag_categories
  id               INTEGER PK
  name             TEXT NOT NULL UNIQUE
  description      TEXT
  common_values    TEXT                -- JSON array (strings or alias objects)
  color            TEXT                -- Tailwind preset name
  icon             TEXT                -- Lucide icon name
  display_order    INTEGER DEFAULT 0
  created_at       DATETIME

colors
  id               INTEGER PK
  image_id         INTEGER FK → images.id
  color_hex        TEXT(7) NOT NULL    -- "#1a2b3c"
  percentage       FLOAT               -- 0.0–100.0
  color_order      INTEGER             -- 1 = most dominant

import_jobs
  id               TEXT PK             -- UUID hex
  status           TEXT NOT NULL DEFAULT 'active'  -- active | paused | completed | cancelled
                                       --   (derived from item counts)
  source_label     TEXT                -- e.g. "Pack.zip"
  default_image_type TEXT NOT NULL DEFAULT 'battlemap'
  planned_at       DATETIME            -- Set when sealed
  last_upload_at   DATETIME
  dismissed_at     DATETIME            -- Hidden from the activity dock
  created_at, updated_at, completed_at  DATETIME

import_groups                          -- Groups planned at seal time
  id               INTEGER PK
  job_id           TEXT FK → import_jobs.id NOT NULL
  author           TEXT
  group_name       TEXT NOT NULL
  image_group_id   INTEGER FK → variant_groups.id  -- Resolved gallery group
  merged_into_existing BOOLEAN NOT NULL DEFAULT false
  sort_order       INTEGER NOT NULL DEFAULT 0
  created_at       DATETIME

import_items                           -- One file; all durable ingest state
  id               INTEGER PK
  job_id           TEXT FK → import_jobs.id NOT NULL
  import_group_id  INTEGER FK → import_groups.id
  kind             TEXT NOT NULL DEFAULT 'image'   -- image | video | archive
  relative_path    TEXT NOT NULL       -- Display + resume matching only
  filename         TEXT NOT NULL
  size             INTEGER
  last_modified    INTEGER             -- Client-reported, ms since epoch
  image_type       TEXT NOT NULL DEFAULT 'battlemap'
  parsed           TEXT                -- JSON, set at plan time
  state            TEXT NOT NULL DEFAULT 'awaiting_bytes'
                                       -- awaiting_bytes | ready | processing |
                                       -- done | duplicate | failed | skipped
  staging_key      TEXT                -- Server-generated staged filename
  source_hash      TEXT(64)            -- SHA-256 of the uploaded bytes
  attempts         INTEGER NOT NULL DEFAULT 0
  retry_after      DATETIME
  error_kind       TEXT                -- file | transient | system
  error_stage      TEXT
  error_reason     TEXT                -- User-facing
  error_detail     TEXT                -- Raw exception text
  image_id         INTEGER FK → images.id
  duplicate_of_image_id INTEGER FK → images.id
  duplicate_tier   TEXT                -- bytes | pixels
  allow_duplicate  BOOLEAN NOT NULL DEFAULT false  -- "Import as copy"
  similar_to_image_id INTEGER FK → images.id       -- Perceptual near-match (advisory)
  similarity_distance INTEGER
  created_at, updated_at  DATETIME
  UNIQUE (job_id, relative_path)

app_settings
  key              TEXT PK
  value_json       TEXT                -- JSON-encoded value
  updated_at       DATETIME
```

State machines for `import_jobs.status` and `import_items.state` are in `backend/app/services/ingest_state.py`; see [ingestion.md](ingestion.md).

### Duplicate detection columns

Ingest compares each prepared item's `source_hash` and stored hash against `images.content_hash` / `images.stored_hash` (byte duplicates) and its pixel hash against `images.pixel_hash` (same image re-encoded). Both auto-skip the item as `duplicate`. `phash` only records a near-match (`similar_to_image_id`) and never skips. The stored file is the original, so `stored_hash` equals `content_hash` for ingested images.

### Full-Text Search (FTS5)

The virtual table `image_fts` (Porter stemmer) indexes `images.search_text`. Triggers on INSERT, UPDATE and DELETE keep it in sync.

### Key Relationships
- `Image` → `ImageGroup` (many-to-one via `variant_group_id`)
- `Image` → `Tag`, `Color` (one-to-many, ORM cascade delete)
- `ImportJob` → `ImportGroup`, `ImportItem` (one-to-many, ORM cascade delete)
- `Image.import_job_id` → `ImportJob` has no cascading relationship: dismissing or pruning a job never deletes its images; only Undo (`DELETE /imports/{job_id}`) does.

### Column Aliasing
Some physical names predate renames and are aliased in the ORM (ADR-011): `variant_groups` → `ImageGroup`, `variant_group_id` → `group_id`, `sub_variant` → `subgroup`.

### Seed Data

- **Tag categories:** `seed_tag_categories()` inserts the categories in `backend/app/data/tag_vocabulary.json` when `tag_categories` is empty; afterwards it is a no-op so user edits are kept. Further genre packs are imported via Settings → Tag Packs (see [tag-packs.md](tag-packs.md)).
- **App settings:** `seed_default_settings()` inserts defaults (grid detection, colour extraction, ingestion performance, import limits, job runner, WebP options) when `app_settings` is empty. See [resource-management.md](resource-management.md).

## LanceDB Vector Store

- **Mode:** embedded, `lancedb.connect("{APP_DATA_DIR}/lancedb")`; memory-mapped from disk, no server process.
- **Table:** `embeddings_{model_name}` — one table per model; switching models uses a new table.
- **Vector size:** depends on the model — 512 (small, CLIP ViT-B/32), 768 (medium, SigLIP2-base), 1152 (large, SigLIP2-so400m). `settings.vector_size` is set from the model manifest at startup.
- **Distance:** cosine; the service returns `1 - distance` as similarity.

Row schema: `id` (int64), `vector` (fixed-size float32 list, normalised), `image_id`, `filename`, `author`, `base_name`.

LanceDB is linked to SQLite by `image_id`. Vectors are written after the SQLite commit; `vector_reconcile.reconcile_vectors` (startup and every 24 h) re-embeds images without a vector and deletes vectors without an image.

## Filesystem — ImageStore

Two storage roots, so originals can live on a different volume:

- **`APP_DATA_DIR`** — SQLite, LanceDB, thumbnails, staging, config, scheduler state, logs, models.
- **`IMAGE_LIBRARY_DIR`** — original files and backups.

| Content | Path |
|---------|------|
| Originals | `{IMAGE_LIBRARY_DIR}/ab/cd/<key>` (the library root is the image store root) |
| Thumbnails | `{APP_DATA_DIR}/store/thumbnails/ab/cd/<key>` |
| Staging | `{APP_DATA_DIR}/staging/{job_id}/{staging_key}` |
| Ingest temp files | `{store_root}/.incoming/` (one per store) |
| Backups | `{IMAGE_LIBRARY_DIR}/backups/{YYYYmmdd_HHMMSS}/` |

### Sharding

Two levels from the first four characters of the key's stem:
```
key:  a1b2c3d4....jpg
path: {base}/a1/b2/a1b2c3d4....jpg
```

### Key Generation
- Originals: `uuid4().hex + lower-cased extension` (32 hex characters + extension).
- Thumbnails: `{stem}_{w}x{h}.jpg` for each of `settings.thumbnail_sizes` (150, 400, 800). The 400×400 key is stored in `images.thumbnail_key`.

### Shared storage keys

The ingest pipeline generates a new key for every image, including "import as copy". `storage_key` is not unique because older rows may share a file; `deletion_service` therefore only deletes a file (and its thumbnails) when no other row references the same `storage_key`.

### DB Is the Source of Truth
The filesystem is a blob store; `storage_key` and `thumbnail_key` are the authoritative references. `sweep_orphaned_store_files` (every 24 h) deletes store files that no row references. It only considers files in the shard layout (so `backups/` and `.incoming/` are never touched), skips files younger than an hour, and deletes nothing if more than 25% of a store looks orphaned (wrong database or unmounted drive).

### Staging

Bytes uploaded for an import are stored per job at `{APP_DATA_DIR}/staging/{job_id}/{staging_key}`. `staging_key` is server-generated (`uuid4().hex` + the item's lower-cased extension) and stored on `ImportItem.staging_key`; client-supplied paths are never used as filesystem paths.

- **Per-file upload** (`PUT …/items/{item_id}/content`) streams to `.{staging_key}.part` in the job directory, hashes and MIME-checks it, then renames it to `{staging_key}`.
- **Archive upload** (`PUT …/archives`) streams the zip to `.{uuid}.zip.part`, extracts each member to `{staging_key}.part` then `{staging_key}`, and deletes the zip.
- **Processing** writes the stored original and thumbnails as temp files in `<store>/.incoming/` (same volume as the destination); the commit renames them into place inside the transaction. `IngestWorker.recover()` clears `.incoming/` at startup.

Cleanup is driven by item state (`ingest_maintenance.py`, every 6 h and on startup when overdue):
- Staged files of `done` / `skipped` items are removed right after their batch commits; maintenance catches any left by a crash.
- Staged files of `failed` / `duplicate` items are kept for Retry / Import as copy until the job is dismissed or finished more than 7 days ago.
- Never-uploaded items of jobs idle for 7 days are skipped.
- Dismissed jobs' rows and staging directories are deleted 30 days after dismissal (images are kept).
- Files and directories in staging that no item references and that are older than an hour (e.g. interrupted `.part` uploads) are deleted.

## Backups

`pipeline/maintenance.py:backup_database()` runs every 24 h. Each run writes a SQLite snapshot (sqlite3 backup API, consistent while writes continue) and a LanceDB copy into `{IMAGE_LIBRARY_DIR}/backups/{timestamp}/`, then rotates: the 7 most recent backups are kept, plus one per 7-day window for up to 4 older ones.
