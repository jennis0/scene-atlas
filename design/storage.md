# Data Storage

## Overview

The system uses three storage backends:
1. **SQLite** — relational metadata (images, tags, colors, variant groups, import jobs)
2. **Qdrant** — CLIP vector embeddings for semantic search
3. **Filesystem (ImageStore)** — image and thumbnail files

## SQLite Database

**Location:** `data/battlemap.db`

### Schema

```
images
  id              INTEGER PK
  filename        TEXT NOT NULL        -- Original filename (display only)
  storage_key     TEXT NOT NULL UNIQUE -- Key into ImageStore (e.g. "a1b2c3d4e5f6.jpg")
  name            TEXT                 -- Inferred base name / variant group name
  author          TEXT
  variant_group_id INTEGER FK → variant_groups.id
  width           INTEGER
  height          INTEGER
  file_size       INTEGER             -- Bytes
  gridded         BOOLEAN             -- True/False/NULL (unknown)
  grid_width      INTEGER             -- Grid square dimensions
  grid_height     INTEGER
  sub_variant     TEXT                 -- Sub-variant path (e.g. "Eerie / No Grid")
  thumbnail_key   TEXT                 -- Key into thumbnail store
  needs_review    BOOLEAN DEFAULT FALSE
  created_at      DATETIME
  updated_at      DATETIME

variant_groups
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
  created_at      DATETIME

colors
  id              INTEGER PK
  image_id        INTEGER FK → images.id (CASCADE DELETE)
  color_hex       TEXT NOT NULL        -- e.g. "#1a2b3c"
  percentage      FLOAT               -- 0.0–100.0
  color_order     INTEGER             -- 1–5 for dominant colors

import_jobs
  id              TEXT PK              -- UUID hex string
  status          TEXT NOT NULL        -- staging, pending, running, completed, failed
  author          TEXT
  variant_group_name TEXT
  variant_group_id INTEGER
  total_files     INTEGER DEFAULT 0
  processed_files INTEGER DEFAULT 0
  failed_files    INTEGER DEFAULT 0
  error_message   TEXT
  flow_run_id     TEXT                 -- Prefect flow run ID for status tracking
  created_at      DATETIME
  completed_at    DATETIME
```

### Key Relationships
- `Image` → `VariantGroup` (many-to-one via `variant_group_id`)
- `Image` → `Tag` (one-to-many, cascade delete)
- `Image` → `Color` (one-to-many, cascade delete)

### Seed Data
`seed_tag_categories()` runs at startup and upserts tag categories with vocabulary words. Existing categories are updated, stale categories are deleted. Categories: lighting, season, weather, state, theme, population, terrain, floor, perspective, quality.

## Qdrant Vector Store

**Host:** localhost:6333 (Docker container)
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
