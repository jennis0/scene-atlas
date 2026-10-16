# Data Storage

## Overview

The system uses three storage backends:
1. **SQLite** — relational metadata (images, tags, colors, image groups, import jobs, settings)
2. **LanceDB** — CLIP vector embeddings for semantic search
3. **Filesystem (ImageStore)** — image and thumbnail files

Schema changes are managed by **Alembic** migrations in `backend/alembic/versions/`.

## SQLite Database

**Location:** `{APP_DATA_DIR}/battlemap.db`

### Schema

```
images
  id              INTEGER PK
  filename        TEXT NOT NULL        -- Original filename (display only)
  storage_key     TEXT NOT NULL        -- Key into ImageStore (not unique-constrained; every new import owns its stored file)
  name            TEXT                 -- Display name for the individual image
  author          TEXT
  variant_group_id INTEGER FK → image_groups.id  -- (aliased as group_id in app code)
  image_type      TEXT DEFAULT 'battlemap'       -- "battlemap" or "scene"
  media_type      TEXT DEFAULT 'image'           -- "image" or "video"
  width           INTEGER
  height          INTEGER
  file_size       INTEGER             -- Bytes
  gridded         BOOLEAN             -- True/False/NULL (unknown); not used for scenes
  grid_width      INTEGER             -- Grid tile count horizontal
  grid_height     INTEGER             -- Grid tile count vertical
  grid_type       TEXT                -- "square" | "hex" | NULL
  grid_confidence FLOAT               -- 0.0–1.0; NULL = filename-detected
  sub_variant     TEXT                -- Subgroup path (aliased as subgroup in app code)
  import_job_id   TEXT                -- FK to import_jobs.id; tracks which import created the image
  content_hash    TEXT(64)            -- SHA-256 of the ORIGINAL uploaded bytes (design's source_hash); indexed
  stored_hash     TEXT(64)            -- SHA-256 of the stored file; = content_hash unless converted; indexed
  pixel_hash      TEXT(64)            -- SHA-256 of canonical decoded pixels (tier-2 dedup); indexed; NULL for video/huge JPEGs
  phash           INTEGER             -- 64-bit perceptual hash (signed); advisory only
  search_text     TEXT                -- Pre-tokenized text for FTS5 (CamelCase-split)
  thumbnail_key   TEXT                -- Key into thumbnail store
  created_at      DATETIME
  updated_at      DATETIME

image_groups (table name: variant_groups)
  id              INTEGER PK
  base_name       TEXT NOT NULL        -- Canonical group name
  author          TEXT
  primary_image_id INTEGER FK → images.id
  image_count     INTEGER DEFAULT 0   -- Maintained by DB triggers on images table
  created_at      DATETIME

tags
  id              INTEGER PK
  image_id        INTEGER FK → images.id (CASCADE DELETE)
  category        TEXT NOT NULL        -- e.g. "lighting", "environment", "features"
  value           TEXT NOT NULL        -- e.g. "night", "forest", "tavern"
  confidence      FLOAT DEFAULT 1.0   -- 0.0–1.0
  source          TEXT DEFAULT "manual" -- "auto" or "manual"
  created_at      DATETIME

tag_categories
  id              INTEGER PK
  name            TEXT NOT NULL UNIQUE -- e.g. "lighting"
  description     TEXT
  common_values   TEXT                 -- JSON array (strings or alias objects)
  color           TEXT                 -- Tailwind color preset name, e.g. "amber"
  icon            TEXT                 -- Lucide icon name, e.g. "leaf"
  display_order   INTEGER DEFAULT 0   -- Ordering in UI
  created_at      DATETIME

colors
  id              INTEGER PK
  image_id        INTEGER FK → images.id (CASCADE DELETE)
  color_hex       TEXT NOT NULL        -- e.g. "#1a2b3c"
  percentage      FLOAT               -- 0.0–100.0
  color_order     INTEGER             -- 1–5 for dominant colors

import_jobs                            -- one import the user started (ADR-018)
  id              TEXT PK              -- UUID hex string
  status          TEXT NOT NULL        -- active | paused | completed | cancelled (derived from item counts)
  source_label    TEXT                 -- Display label, e.g. "Forest Pack.zip"
  default_image_type TEXT              -- battlemap | scene
  planned_at      DATETIME             -- Set at seal; items are claimable only after this
  last_upload_at  DATETIME             -- Last byte receipt; drives "upload interrupted" and abandonment
  dismissed_at    DATETIME             -- Hidden from the dock; never deletes anything
  created_at, updated_at, completed_at DATETIME

import_groups                          -- groups planned from the paths at seal time
  id              INTEGER PK
  job_id          TEXT FK → import_jobs.id
  author, group_name TEXT
  image_group_id  INTEGER FK → variant_groups.id  -- existing group (merge) or created on first commit
  merged_into_existing BOOLEAN
  sort_order      INTEGER              -- processing order within the job
  created_at      DATETIME

import_items                           -- one row per file; all durable ingest state
  id              INTEGER PK
  job_id          TEXT FK → import_jobs.id
  import_group_id INTEGER FK → import_groups.id   -- NULL until sealed
  kind            TEXT                 -- image | video | archive
  relative_path, filename TEXT         -- display + resume matching only; never a filesystem path
  size, last_modified INTEGER          -- from the client manifest
  image_type      TEXT
  parsed          TEXT                 -- JSON parser output
  state           TEXT                 -- awaiting_bytes | ready | processing | done | duplicate | failed | skipped
  staging_key     TEXT                 -- server-generated staged filename
  source_hash     TEXT(64)             -- SHA-256 of original bytes (client hint, then server-computed)
  attempts, retry_after                -- poison detection + transient backoff
  error_kind, error_stage, error_reason, error_detail  -- kind: file | transient | system | bytes_lost
  image_id        INTEGER FK → images.id           -- set when done
  duplicate_of_image_id, duplicate_tier            -- set when duplicate (bytes | pixels)
  allow_duplicate BOOLEAN              -- "Import as new copy"
  similar_to_image_id, similarity_distance         -- perceptual flag (advisory)
  created_at, updated_at DATETIME
  -- UNIQUE (job_id, relative_path); indexes (state, job_id), (job_id, state), (job_id, import_group_id)

app_settings
  key             TEXT PK              -- Setting identifier (e.g. "grid_detection_enabled")
  value_json      TEXT                 -- JSON-encoded value (TEXT column, parsed at read time)
  updated_at      DATETIME             -- Last modification timestamp
  -- Seeded via seed_default_settings() at first boot with defaults for grid detection,
  -- color extraction, ingestion performance, import limits, and job runner configuration
```

### Full-Text Search (FTS5)

A virtual table `image_fts` provides full-text search using the FTS5 extension with Porter stemmer tokenizer. It indexes `search_text` from each image (CamelCase-split, space-separated). Triggers on INSERT, UPDATE, DELETE keep the FTS index in sync with the `images` table.

### Key Relationships
- `Image` → `ImageGroup` (many-to-one via `group_id` / physical column `variant_group_id`)
- `Image` → `Tag` (one-to-many, cascade delete)
- `Image` → `Color` (one-to-many, cascade delete)
- `ImportJob` → `ImportGroup`, `ImportItem` (one-to-many, cascade delete); `ImportItem.image_id` → `Image`

### Column Aliasing
Several DB columns retain their original names for backward compatibility (avoiding a migration), but are aliased to new names in the SQLAlchemy models. See ADR-011 for details. Key mappings:
- `variant_group_id` → `group_id`
- `variant_group_name` → `group_name`
- `sub_variant` → `subgroup`

### Seed Data

**Tag categories:** `seed_tag_categories()` runs at first boot and inserts 10 categories with vocabulary words (lighting, season, weather, environment, features, state, theme, population, perspective, style). The canonical vocabulary is stored in `backend/app/data/tag_vocabulary.json` with ~149 tags and ~220 aliases across 6 genre packs (Common, Fantasy, Sci-Fi, Cyberpunk, Horror, Historical). Once categories exist, it's a no-op so user edits are preserved. Users can import additional genre packs via Settings → Tag Packs.

**App settings:** `seed_default_settings()` runs at first boot and inserts defaults for grid detection, color extraction, ingestion performance, import limits, and job runner configuration.

## LanceDB Vector Store

**Mode:** Disk-backed local (`lancedb.connect("{APP_DATA_DIR}/lancedb")`) — memory-mapped from disk, not loaded into Python heap, no separate server process
**Table:** `embeddings_{model_name}` (e.g. `embeddings_small`) — table is model-scoped; switching models creates a new table
**Vector size:** Varies by model: 512 (small/CLIP), 768 (medium/SigLIP2-base), 1152 (large/SigLIP2-so400m)
**Distance metric:** Cosine distance (service converts to similarity by subtracting from 1.0)

Each row in LanceDB:
- **ID:** `image_id` from SQLite (integer)
- **Vector:** 512-dim CLIP embedding (normalized)
- **Payload:** `{image_id, filename, author, base_name}`

LanceDB is the semantic search index (not the source of truth — SQLite is authoritative; LanceDB can be rebuilt from stored embeddings). They are linked by `image_id`.

## Filesystem — ImageStore

The application uses two storage roots, allowing images and application data to live on separate volumes:

- **`APP_DATA_DIR`** — fast storage: SQLite database, LanceDB index, thumbnails, staging area, config. Typically on the system drive.
- **`IMAGE_LIBRARY_DIR`** — cold storage: original image files and backups. Can be on a large external or network drive.

**Images (originals):** `{IMAGE_LIBRARY_DIR}/a1/b2/...` (flat root — the library dir itself is the image store root)
**Thumbnails:** `{APP_DATA_DIR}/store/thumbnails/`
**Staging (imports):** `{APP_DATA_DIR}/staging/{job_id}/`

### Sharding Scheme

Files are stored using a 2-level hash shard based on the key's hex characters:
```
key: "a1b2c3d4e5f6.jpg"
path: {IMAGE_LIBRARY_DIR}/a1/b2/a1b2c3d4e5f6.jpg
```

This keeps any directory under ~256 entries.

### Key Generation
- Images: `uuid.uuid4().hex + extension` → e.g. `"a1b2c3d4e5f67890abcdef1234567890.jpg"` (full 32-char hex)
- Thumbnails: `{same_stem}_400x400.jpg` (or other size suffix)

### Important: DB Is the Source of Truth
The filesystem is a dumb blob store. The DB's `storage_key` and `thumbnail_key` fields are the authoritative references. If a file exists in the store but has no DB entry, it's orphaned. If a DB entry's key points to a missing file, the image is broken.

### Staging Directory
Each uploaded file is streamed to `{APP_DATA_DIR}/staging/{job_id}/` under a server-generated name recorded in `import_items.staging_key`; the user-supplied `relative_path` never reaches the filesystem (see [security.md](security.md)). Cleanup is state-based, never mtime-based: staged bytes are deleted once their item is `done` or `skipped`; those of `failed` and `duplicate` items are kept for retry / "Import as new copy" until the job is dismissed or completed more than 7 days ago (`ingest_maintenance.py`).

### Atomic placement (`.incoming/`)
The worker writes each stored original (or converted output) to `{IMAGE_LIBRARY_DIR}/.incoming/` and thumbnails to the thumbnail store's `.incoming/` during prepare, then renames them into place inside the commit transaction, so a file is either fully in the library or not at all. `.incoming/` is cleared at startup, and the orphan sweep only considers the `xx/yy/<key>` shard layout. See [ingestion.md §5.3](ingestion.md#53-commit-protocol).

### Stored format
By default the library keeps each upload's original bytes. The `stored_format` setting (`original` | `webp` | `jpeg` | `png`, with `stored_quality` 1–100, default 90, and `stored_lossless` for WebP) converts new imports on the worker's temp copy (`backend/pipeline/stored_format.py`). Conversion is skipped when the image is already in the target format, animated, has transparency with a JPEG target, or exceeds 16,383 px for WebP; JPEGs are never encoded as lossless WebP. Duplicate hashes always come from the source, so dedup works whatever the format.

## Backups

**Location:** `{IMAGE_LIBRARY_DIR}/backups/{timestamp}/`

On migration from a single-root installation, the existing images at `{old_dataDir}/store/images/` become `IMAGE_LIBRARY_DIR` (i.e. the old image root is promoted to the library root directly, rather than wrapping it in another directory).
**Contents:** SQLite snapshot + LanceDB snapshot
**Schedule:** Every 24 hours (via Scheduler)
**Rotation:** 7 daily + 4 weekly backups retained
**Trigger:** `backend/pipeline/maintenance.py:backup_database()`
