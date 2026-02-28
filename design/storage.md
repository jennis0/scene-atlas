# Data Storage

## Overview

The system uses three storage backends:
1. **SQLite** — relational metadata (images, tags, colors, image groups, import jobs, settings)
2. **Qdrant** — CLIP vector embeddings for semantic search
3. **Filesystem (ImageStore)** — image and thumbnail files

Schema changes are managed by **Alembic** migrations in `backend/alembic/versions/`.

## SQLite Database

**Location:** `data/battlemap.db`

### Schema

```
images
  id              INTEGER PK
  filename        TEXT NOT NULL        -- Original filename (display only)
  storage_key     TEXT NOT NULL        -- Key into ImageStore (NOT unique — shared by dedup records)
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
  content_hash    TEXT(64)            -- SHA-256 hex digest for deduplication
  search_text     TEXT                -- Pre-tokenized text for FTS5 (CamelCase-split)
  thumbnail_key   TEXT                -- Key into thumbnail store
  needs_review    BOOLEAN DEFAULT FALSE
  created_at      DATETIME
  updated_at      DATETIME

image_groups (table name: variant_groups)
  id              INTEGER PK
  base_name       TEXT NOT NULL        -- Canonical group name
  author          TEXT
  primary_image_id INTEGER FK → images.id
  created_at      DATETIME

tags
  id              INTEGER PK
  image_id        INTEGER FK → images.id (CASCADE DELETE)
  category        TEXT NOT NULL        -- e.g. "lighting", "season", "terrain"
  value           TEXT NOT NULL        -- e.g. "night", "winter", "forest"
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

import_jobs
  id              TEXT PK              -- UUID hex string
  status          TEXT NOT NULL        -- uploading | staging | active | awaiting_input |
                                       -- completed | failed | cancelled | expired
  source_label    TEXT                 -- Display label for activity dock
  pending_groups  INTEGER DEFAULT 0   -- Groups not yet confirmed by user
  total_files     INTEGER DEFAULT 0
  error_message   TEXT
  analysis_result TEXT                 -- JSON: full analysis output for preview reconnection
  all_confirmed   BOOLEAN DEFAULT FALSE -- True when confirm-all was used
  created_at      DATETIME
  updated_at      DATETIME
  completed_at    DATETIME

import_group_jobs
  id              TEXT PK              -- UUID hex string
  job_id          TEXT FK → import_jobs.id
  variant_group_name TEXT NOT NULL     -- (aliased as group_name in app code)
  author          TEXT
  total_files     INTEGER DEFAULT 0
  processed_files INTEGER DEFAULT 0
  failed_files    INTEGER DEFAULT 0
  status          TEXT NOT NULL DEFAULT 'running'  -- running | completed | failed | cancelled
  error_message   TEXT
  created_group_id INTEGER             -- FK to variant_groups.id once processing finishes
  created_at      DATETIME
  completed_at    DATETIME

app_settings
  key             TEXT PK
  value_json      TEXT                 -- JSON-encoded value
  updated_at      DATETIME
```

### Full-Text Search (FTS5)

A virtual table `image_fts` provides full-text search using the FTS5 extension with Porter stemmer tokenizer. It indexes `search_text` from each image (CamelCase-split, space-separated). Triggers on INSERT, UPDATE, DELETE keep the FTS index in sync with the `images` table.

### Key Relationships
- `Image` → `ImageGroup` (many-to-one via `group_id` / physical column `variant_group_id`)
- `Image` → `Tag` (one-to-many, cascade delete)
- `Image` → `Color` (one-to-many, cascade delete)
- `ImportJob` → `ImportGroupJob` (one-to-many, cascade delete)

### Column Aliasing
Several DB columns retain their original names for backward compatibility (avoiding a migration), but are aliased to new names in the SQLAlchemy models. See ADR-011 for details. Key mappings:
- `variant_group_id` → `group_id`
- `variant_group_name` → `group_name`
- `sub_variant` → `subgroup`

### Seed Data

**Tag categories:** `seed_tag_categories()` runs at first boot and inserts 10 categories with vocabulary words (lighting, season, weather, state, theme, population, terrain, floor, perspective, quality). Once categories exist, it's a no-op so user edits are preserved.

**App settings:** `seed_default_settings()` runs at first boot and inserts defaults for grid detection, color extraction, ingestion performance, import limits, and job runner configuration.

## Qdrant Vector Store

**Mode:** Embedded local (`QdrantClient(path="data/qdrant_local")`) — no separate server process
**Collection:** `battlemap_images`
**Vector size:** 512 (CLIP ViT-B/32 projection dimension)
**Distance metric:** Cosine similarity

Each point in Qdrant:
- **ID:** `image_id` from SQLite (integer)
- **Vector:** 512-dim CLIP embedding (normalized)
- **Payload:** `{image_id, filename, author, base_name}`

Qdrant is the source of truth for semantic similarity. SQLite is the source of truth for all other metadata. They are linked by `image_id`.

## Filesystem — ImageStore

**Images:** `data/store/images/`
**Thumbnails:** `data/store/thumbnails/`
**Staging (imports):** `data/staging/{job_id}/`

### Sharding Scheme

Files are stored using a 2-level hash shard based on the key's hex characters:
```
key: "a1b2c3d4e5f6.jpg"
path: data/store/images/a1/b2/a1b2c3d4e5f6.jpg
```

This keeps any directory under ~256 entries.

### Key Generation
- Images: `uuid.uuid4().hex[:12] + extension` → e.g. `"a1b2c3d4e5f6.jpg"`
- Thumbnails: `{same_stem}_400x400.jpg` (or other size suffix)

### Important: DB Is the Source of Truth
The filesystem is a dumb blob store. The DB's `storage_key` and `thumbnail_key` fields are the authoritative references. If a file exists in the store but has no DB entry, it's orphaned. If a DB entry's key points to a missing file, the image is broken.

### Staging Directory
Import uploads are saved to `data/staging/{job_id}/` preserving relative paths from the upload. After processing, staging files are consumed by `process_single_image` which copies them into the ImageStore. Staging directories should be cleaned up after all groups in a job are processed.

## Backups

**Location:** `data/backups/{timestamp}/`
**Contents:** SQLite snapshot + Qdrant snapshot
**Schedule:** Every 24 hours (via Scheduler)
**Rotation:** 7 daily + 4 weekly backups retained
**Trigger:** `backend/pipeline/maintenance.py:backup_database()`
