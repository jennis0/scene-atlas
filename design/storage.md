# Data Storage

## Overview

Three storage backends:
1. **SQLite** — relational metadata (images, groups, tags, colours, import jobs, settings). The source of truth.
2. **LanceDB** — vector embeddings for semantic search. Derived; can be rebuilt by re-encoding images.
3. **Filesystem** — originals and thumbnails. Originals are in the store (`ImageStore`, which Scene Atlas writes) or in the linked folder (the user's own maps, only ever read; see [Linked folder](#linked-folder)).

Schema changes are Alembic migrations in `backend/alembic/versions/`, applied by `init_db()` at startup. A test fails if the ORM models drift from the migrated schema.

## SQLite Database

**Location:** `{SCENE_ATLAS_DATA_DIR}/battlemap.db` (`settings.database_url` is always derived from `data_dir`). Connections use WAL mode, `busy_timeout=10000` and `synchronous=NORMAL`.

### Schema

Physical column names are shown; ORM attribute aliases are noted.

```
images
  id               INTEGER PK
  filename         TEXT NOT NULL       -- Original filename (display only)
  storage_key      TEXT                -- Key into the image store (indexed, not unique);
                                       --   NULL for linked images (migration 028)
  source_file_id   INTEGER FK → source_files.id UNIQUE  -- Linked images: their file
                                       --   CHECK (storage_key IS NOT NULL OR source_file_id IS NOT NULL)
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
  grid_source      TEXT                -- filename | detector | user (migration 022);
                                       --   re-detection never overwrites user
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
  edited_at        DATETIME            -- Last user edit (migration 029, ADR-028); automatic
                                       --   grouping never changes an edited group

image_grouping_features                -- Variant-grouping features (migration 029, ADR-028)
  image_id         INTEGER PK FK → images.id
  version          SMALLINT NOT NULL   -- Feature algorithm version (GROUPING_FEATURES_VERSION)
  phash256         BLOB(32)            -- 256-bit DCT pHash = imagehash.phash(hash_size=16),
                                       --   MSB-first row-major
  edge             BLOB(2048)          -- 32×32 edge map, 1024 little-endian float16, z-scored
                                       --   (a·b / 1024 = correlation)
  computed_at      DATETIME NOT NULL

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
  lab_l, lab_a, lab_b  FLOAT NOT NULL  -- CIELAB of color_hex, for colour search (ix_colors_lab)

import_jobs
  id               TEXT PK             -- UUID hex
  status           TEXT NOT NULL DEFAULT 'active'  -- active | paused | completed | cancelled
                                       --   (derived from item counts)
  source_label     TEXT                -- e.g. "Pack.zip"
  default_image_type TEXT NOT NULL DEFAULT 'battlemap'
  planned_at       DATETIME            -- Set when sealed
  last_upload_at   DATETIME
  dismissed_at     DATETIME            -- Hidden from the activity dock
  source_roots     TEXT                -- Local imports: JSON list of folders read from
  library_source_id INTEGER FK → library_sources.id  -- A scan of the linked folder (no Undo)
  grouping_refined_at DATETIME         -- Groups refined by content (migration 029, ADR-028)
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
  source_path      TEXT                -- Local imports: the file's absolute path
  source_file_id   INTEGER FK → source_files.id  -- Linked items: the file, read by its key
  attempts         INTEGER NOT NULL DEFAULT 0
  retry_after      DATETIME
  error_kind       TEXT                -- file | transient | system | bytes_lost
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

library_sources                        -- The linked folder; one row today (migration 028)
  id               INTEGER PK
  kind             TEXT NOT NULL       -- "folder" (S3 later)
  location         TEXT NOT NULL       -- Last-known absolute path
  state            TEXT NOT NULL       -- online | offline | detached
  last_scan_at     DATETIME

source_files                           -- The durable index of the linked folder
  id               INTEGER PK
  source_id        INTEGER FK → library_sources.id NOT NULL
  rel_key          TEXT NOT NULL       -- POSIX path relative to the folder ("Author/Pack/x.png")
  size             INTEGER NOT NULL
  mtime_ns         INTEGER NOT NULL    -- The version: a rescan compares size and mtime only
  content_hash     TEXT(64)            -- Set once read
  state            TEXT NOT NULL       -- pending | image | duplicate | skipped | failed | removed
  image_id         INTEGER FK → images.id  -- The image (image) or the one matched (duplicate)
  reason           TEXT                -- skipped / failed: why
  missing_since    DATETIME            -- The file is gone; its image is kept
  UNIQUE (source_id, rel_key)

app_settings
  key              TEXT PK
  value_json       TEXT                -- JSON-encoded value
  updated_at       DATETIME
```

Besides the `AppSettings` fields, `app_settings` holds two keys the settings API can't change: `setup_completed_at` and `library_id` (see [Library identity](#library-identity)).

State machines for `import_jobs.status` and `import_items.state` are in `backend/app/services/ingest_state.py`; see [ingestion.md](ingestion.md).

### Duplicate detection columns

Ingest compares each prepared item's `source_hash` and stored hash against `images.content_hash` / `images.stored_hash` (byte duplicates) and its pixel hash against `images.pixel_hash` (same image re-encoded). Both auto-skip the item as `duplicate`. `phash` only records a near-match (`similar_to_image_id`) and never skips. The stored file is the original, so `stored_hash` equals `content_hash` for ingested images.

### Full-Text Search (FTS5)

The virtual table `image_fts` (Porter stemmer) indexes `images.search_text`. Triggers on INSERT, UPDATE and DELETE keep it in sync.

### Key Relationships
- `Image` → `ImageGroup` (many-to-one via `variant_group_id`)
- `Image` → `Tag`, `Color` (one-to-many, ORM cascade delete)
- `Image` → `image_grouping_features` (one-to-one, no ORM relationship). Written from the 800 px thumbnail at commit and replaced by a linked refresh; videos have none, and an image whose features failed has NULLs. Foreign keys aren't enforced, so `deletion_service` (single, bulk, group and Undo deletes, linked removal) and library purge delete these rows explicitly; the commit replaces rather than inserts, so a row left under a reused image id can't block an import. Images from before migration 029 have no row.
- `ImportJob` → `ImportGroup`, `ImportItem` (one-to-many, ORM cascade delete)
- `Image.import_job_id` → `ImportJob` has no cascading relationship: dismissing or pruning a job never deletes its images; only Undo (`DELETE /imports/{job_id}`) does.

### Column Aliasing
Some physical names predate renames and are aliased in the ORM (ADR-011): `variant_groups` → `ImageGroup`, `variant_group_id` → `group_id`, `sub_variant` → `subgroup`.

### Seed Data

- **Tag categories:** `seed_tag_categories()` inserts the categories in `backend/app/data/tag_vocabulary.json` with the `common` pack's tags when `tag_categories` is empty; afterwards it is a no-op so user edits are kept. Genre packs are imported from the setup wizard or Settings → Tag Packs (see [tag-packs.md](tag-packs.md)).
- **App settings:** `seed_default_settings()` inserts defaults (grid detection, colour extraction, ingestion performance, import limits, job runner, stored format) when `app_settings` is empty. See [resource-management.md](resource-management.md).

## LanceDB Vector Store

- **Mode:** embedded, `lancedb.connect("{SCENE_ATLAS_DATA_DIR}/lancedb")`; memory-mapped from disk, no server process.
- **Table:** `embeddings_{model_name}` — one table per model; switching models uses a new table.
- **Vector size:** depends on the model — 512 (small, CLIP ViT-B/32), 768 (medium, SigLIP2-base), 1024 (large, SigLIP2-large). `settings.vector_size` is set from the model manifest at startup.
- **Distance:** cosine; the service returns `1 - distance` as similarity.

Row schema: `id` (int64), `vector` (fixed-size float32 list, normalised), `image_id`, `filename`, `author`, `base_name`.

LanceDB is linked to SQLite by `image_id`. Vectors are written after the SQLite commit; `vector_reconcile.reconcile_vectors` (startup and every 24 h) re-embeds images without a vector and deletes vectors without an image.

## Filesystem — ImageStore

Two storage roots, so originals can live on a different volume:

- **`SCENE_ATLAS_DATA_DIR`** — SQLite, LanceDB, thumbnails, staging, config, scheduler state, logs, models.
- **`SCENE_ATLAS_IMAGES_DIR`** — original files and backups.

| Content | Path |
|---------|------|
| Originals | `{SCENE_ATLAS_IMAGES_DIR}/ab/cd/<key>` (the library root is the image store root) |
| Thumbnails | `{SCENE_ATLAS_DATA_DIR}/store/thumbnails/ab/cd/<key>` |
| Staging | `{SCENE_ATLAS_DATA_DIR}/staging/{job_id}/{staging_key}` |
| Ingest temp files | `{store_root}/.incoming/` (one per store) |
| Backups | `{SCENE_ATLAS_IMAGES_DIR}/backups/{YYYYmmdd_HHMMSS}/` |

### Library identity

A library is its database and its store, plus an optional linked folder (`SCENE_ATLAS_LINKED_LIBRARY_DIR`; the user's own maps, never written). The plan is [library-setup.md](library-setup.md); the code is `backend/app/library_identity.py`.

- **`library_id`**: a UUID in `app_settings`, created for a new library, or for a library from before IDs the first time it opens. The database is authoritative.
- **Markers**: `scene-atlas-library.json` at the root of the app data folder and of the store: `{"format": 1, "library_id", "role": "app_data" | "store", "hints"}`. Hints are the other folders' last-known paths; a store inside its linked folder records the linked folder as a relative path (`".."`). When app data and the store are one folder, only the store marker is written. A marker that can't be parsed counts as no marker.
- **Startup check**: after the storage locks and before the database is opened for writing, `check_library` reads the database read-only (`library_id`, a few `storage_key`s) and the store marker, and refuses to start unless the folders form one library. `open_library` then creates the ID if needed, creates an empty store if there's none, and writes both markers (hints refreshed every start).

| Database | Store marker | Outcome |
|---|---|---|
| none | none | New library: create the ID and the store, write both markers |
| X | X | Open |
| X | Y, or any marker with a database from before IDs | Refuse: "The image folder belongs to a different library." |
| none | X | Refuse: "This image folder belongs to a library whose search data folder isn't here." |
| X or no ID | none, and none of a sample of the database's stored files is in the store (including a missing store) | Refuse: "The image folder doesn't contain this library's maps." |
| X or no ID | none, and the store holds the database's files, or there are none | Open: create the ID if needed, write the marker |

The store and app data may sit inside the linked folder, but may not be it or contain it (purge empties the store); those refuse too. Refusals are logged as `STARTUP ERROR: <text>`, which the desktop app shows on its loading page. `POST /library/inspect` applies the same rules (`decide()`) to folders the setup wizard proposes, with the wizard's wording.

The walk used by local imports and the linked folder scan (`ingest_local.walk_files`) skips any folder holding a marker or `.backend.lock`, so a library's own folders are never imported.

`ImageStore` doesn't create its root, so a missing store stays missing (an unmounted drive) until the check decides. Library purge deletes everything in the store except `.backend.lock`, then writes the markers again.

### Linked folder

The linked folder (`settings.linked_library_dir`, from `SCENE_ATLAS_LINKED_LIBRARY_DIR` or the desktop app's `--linked-library-dir`) holds the user's own maps. They are read where they are and never written, moved or deleted. Plan: [library-setup.md §4](library-setup.md#4-linked-library); ingest side: [ingestion.md §5.7](ingestion.md#57-linked-items).

- **Reading originals.** Every original, stored or linked, is read through the source interface in `backend/app/services/originals.py`: `original_path(image)` returns the file or raises `OriginalUnavailable` (`missing`, or `offline` with a reason). The store is `ImageStore` (`local_path`, `put`, `delete`); the linked folder is `LinkedFolder` (`list`, `local_path`), which has no `put` or `delete`. `LinkedFolder.local_path` is the containment check: the key must be relative with no `..`, and joined to the root it must resolve inside the root to a regular file that isn't a symlink. File serving, the thumbnail fallback, group download, library export and the backfills all go through it; nothing else builds a path to an original.
- **Rows.** `library_sources` is the folder; `source_files` records what became of each of its files, so a rescan never reads a file it has seen. Images read from the folder have `storage_key` NULL and `source_file_id` set. `backend/app/services/linked_files.py` keeps the rows in step: item outcomes are written back, removing an image marks its file `removed` (rescans leave it out; files recorded as its duplicates too), and a missing image takes over a file with its bytes (a move).
- **Edited files.** A file edited in place refreshes its image (library-setup.md §4.5, [ingestion.md §5.7](ingestion.md#57-linked-items)): the image keeps its id, name, tags, group, type and user grid, and gets new thumbnails (the old ones are deleted), colours, hashes, size, dimensions, vector and re-detected grid. The row keeps its key and its image throughout; a file only touched (same bytes) just has its new size and mtime recorded. A failed refresh leaves the image as it was.
- **States.** `library_sources.state` is written at startup and by scans. Reads check the folder live: `linked_folder_available()` (cached for 5 s, since a stat of an unreachable share can hang) decides `file_state` (`ok | missing | offline`) in image responses. Offline means the folder isn't there (nothing is marked missing); detached means a row exists but no folder is configured, or "Stop using this folder" ran.
- **Purge** deletes `library_sources` and `source_files` with the other rows and never touches the folder; its next scan adds its maps again. The orphan sweep only walks the store's shard folders, and vector reconciliation and model switches read thumbnails, so both work while the folder is offline.
- **The library's own folders.** The store and app data may sit inside the linked folder (the desktop default) but may not be it or contain it; the scan's walk skips them by their marker or lock.

### Sharding

Two levels from the first four characters of the key's stem:
```
key:  a1b2c3d4....jpg
path: {base}/a1/b2/a1b2c3d4....jpg
```

### Key Generation
- Originals: `uuid4().hex + lower-cased extension` (32 hex characters + extension).
- Thumbnails: `{stem}_{w}x{h}.{ext}` for each of `settings.thumbnail_sizes` (150, 400, 800). The 400×400 key is stored in `images.thumbnail_key`. All sizes of one image share the extension:
  - `.jpg` (JPEG q85, RGB) for opaque images, including RGBA files whose alpha is fully opaque.
  - `.webp` (lossy WebP q85, RGBA) when the image has transparent pixels (alpha band, LA/PA, or a tRNS key), so the frontend shows its own backdrop behind them. Before 2026-10 alpha was flattened by `convert("RGB")`, which made transparent areas (e.g. grid-only overlay PNGs) solid black; those older thumbnails stay black until the image is re-imported, as there is no thumbnail-regeneration job.
  - Opaque images stay JPEG because it encodes several times faster than WebP and keeps existing libraries uniform. Code that derives sibling keys (`deletion_service._delete_all_thumbnails`, `maintenance._thumbnail_stem`) must not assume `.jpg`. `api/images.py` registers `image/webp` with `mimetypes` because Python < 3.13 doesn't always know it, and `FileResponse` would otherwise serve `application/octet-stream`.

### Shared storage keys

The ingest pipeline generates a new key for every image, including "import as copy". `storage_key` is not unique because older rows may share a file; `deletion_service` therefore only deletes a file (and its thumbnails) when no other row references the same `storage_key`. A linked image has no `storage_key`: its thumbnails are always deleted with it, and its file never is (its `source_files` row becomes `removed`).

### DB Is the Source of Truth
The filesystem is a blob store; `storage_key` and `thumbnail_key` are the authoritative references. `sweep_orphaned_store_files` (every 24 h) deletes store files that no row references. It only considers files in the shard layout (so `backups/` and `.incoming/` are never touched), skips files younger than an hour, and deletes nothing if more than 25% of a store looks orphaned (wrong database or unmounted drive).

### Staging

Bytes uploaded for an import are stored per job at `{SCENE_ATLAS_DATA_DIR}/staging/{job_id}/{staging_key}`. `staging_key` is server-generated (`uuid4().hex` + the item's lower-cased extension) and stored on `ImportItem.staging_key`; client-supplied paths are never used as filesystem paths.

- **Per-file upload** (`PUT …/items/{item_id}/content`) streams to `.{staging_key}.part` in the job directory, hashes and MIME-checks it, then renames it to `{staging_key}`.
- **Archive upload** (`PUT …/archives`) streams the zip to `.{uuid}.zip.part`, extracts each member to `{staging_key}.part` then `{staging_key}`, and deletes the zip.
- **Processing** writes the stored original (or converted output) and thumbnails as temp files in `<store>/.incoming/` (same volume as the destination); the commit renames them into place inside the transaction, so a file is either fully in the library or not at all. `IngestWorker.recover()` clears `.incoming/` at startup.

Cleanup is driven by item state (`ingest_maintenance.py`, every 6 h and on startup when overdue):
- Staged files of `done` / `skipped` items are removed right after their batch commits; maintenance catches any left by a crash.
- Staged files of `failed` / `duplicate` items are kept for Retry / Import as copy until the job is dismissed or finished more than 7 days ago.
- Never-uploaded items of jobs idle for 7 days are skipped.
- Dismissed jobs' rows and staging directories are deleted 30 days after dismissal (images are kept).
- Files and directories in staging that no item references and that are older than an hour (e.g. interrupted `.part` uploads) are deleted.

### Stored format

By default the library keeps each upload's original bytes. The `stored_format` setting (`original` | `webp` | `jpeg` | `png`, with `stored_quality` 1–100, default 90, and `stored_lossless` for WebP) converts new imports on the worker's temp copy (`backend/pipeline/stored_format.py`). Conversion is skipped when the image is already in the target format, animated, has transparency with a JPEG target, or exceeds 16,383 px for WebP; JPEGs are never encoded as lossless WebP. Duplicate hashes always come from the source, so dedup works whatever the format; `stored_hash` differs from `content_hash` only for converted files.

## Backups

`pipeline/maintenance.py:backup_database()` runs every 24 h. Each run writes a SQLite snapshot (sqlite3 backup API, consistent while writes continue) and a LanceDB copy into `{SCENE_ATLAS_IMAGES_DIR}/backups/{timestamp}/`, then rotates: the 7 most recent backups are kept, plus one per 7-day window for up to 4 older ones. Rotation only counts and deletes directories named `YYYYmmdd_HHMMSS`; anything else in `backups/` is left alone.

**Pre-migration snapshots.** Migrations are one-way, so before `init_db()` applies pending migrations to an Alembic-managed, file-backed SQLite database it writes a SQLite snapshot (same backup API) to `backups/pre-migration/{timestamp}_{from_rev}/battlemap.db` and keeps the 5 most recent (`maintenance.backup_before_migration`). This is the way back after an app update: reinstall the old version and restore that file. Fresh databases, pre-Alembic stamping, databases at head, and databases at a revision the build doesn't know (from a newer version; the upgrade fails anyway) get none. LanceDB is not included: no migration touches it. If the snapshot fails, `init_db()` raises `MigrationBackupError` ("Could not back up the database before migrating it: …") and startup stops without migrating. The snapshot is taken in a separate connection before the migration transaction opens; the storage lock keeps other writers out.
