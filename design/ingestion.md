# Ingestion

How files get from the user's disk into the library: the import data model, the item state machine, the upload protocol, the ingest worker, duplicate detection, maintenance and recovery.

Background and rationale for this design: [ADR-018](decisions.md#adr-018-durable-per-item-ingest-pipeline) and [ingest-redesign.md](ingest-redesign.md) (history, measurements, open questions). Path parsing and grouping: [parser.md](parser.md). Concurrency controls: [resource-management.md](resource-management.md).

## Principles

- **The file is the unit of work and of commit.** Once a file is committed it stays. Other files failing never undoes it.
- **Jobs aggregate; they don't decide.** A job is what the user started ("Forest Pack.zip"). Its status is derived from its items.
- **The backend owns the lifecycle.** The client describes files and supplies bytes. Closing the tab can interrupt an upload, never processing.
- **Nothing destructive happens implicitly.** Cancel keeps finished work. Deleting imported images only happens through an explicit "Undo import".
- **File problems fail the file; system problems pause the queue.** A full disk or missing AI model never fails items.
- **Automatic duplicate rules have zero false positives.** Near-duplicates (gridded vs gridless, lighting variants) are what groups exist to hold.

## Code map

| Module | Responsibility |
|---|---|
| `backend/app/services/ingest_state.py` | Pure item/job state machines (no DB). `sources_for(event)` feeds DB `WHERE` clauses so illegal transitions can't be written. |
| `backend/pipeline/ingest_queue.py` | Durable operations: create, manifest, plan (seal), byte receipt, client hashes, claim, failures, recovery, retry, import-as-copy, skip, pause/resume/cancel, undo, `recompute_job_status`, `write_session()` (`BEGIN IMMEDIATE`). |
| `backend/pipeline/ingest_process.py` | One batch: `prepare_item` → `embed` → `commit_batch` → `write_vectors`, orchestrated by `process_batch`. |
| `backend/pipeline/ingest_worker.py` | `IngestWorker` loop thread and `get_ingest_worker()`. |
| `backend/pipeline/ingest_archive.py` | Server-side zip expansion into items (before seal). |
| `backend/pipeline/ingest_maintenance.py` | Scheduled, state-based cleanup. |
| `backend/pipeline/image_hashes.py` | File SHA-256, strip-wise pixel hash, DCT pHash. |
| `backend/pipeline/vector_reconcile.py` | SQLite ↔ LanceDB id-set reconciliation. |
| `backend/pipeline/error_classifier.py` | Exception → user-facing reason and `kind`. |
| `backend/app/services/memory_budget.py` | `MemoryBudget`: memory-aware admission for prepare. |
| `backend/app/api/imports.py`, `backend/app/models/import_schemas.py` | HTTP API and its models. |
| `frontend/src/lib/import/` | `ImportManager` (client-side owner of uploads and polling), `importClient`, `hasher` + `hash.worker`, `useImports` hooks. |
| `frontend/src/components/imports/` | `ImportDialog`, `ImportReportDialog`, `GroupLedger`, `ImportJobRow` (activity dock row). |

## Data model

```
import_jobs 1───* import_groups 1───* import_items *───1 images
                                       (image_id / duplicate_of_image_id)
```

Defined in `backend/app/models/database.py`; tables created by Alembic `020_ingest_items.py`, legacy tables dropped by `021_drop_legacy_import_tables.py`.

### `import_jobs`

| Column | Notes |
|---|---|
| `id` | uuid hex |
| `status` | `active` \| `paused` \| `completed` \| `cancelled` |
| `source_label` | Display label, e.g. "Forest Pack.zip" (sent as `label` by the API) |
| `default_image_type` | `battlemap` \| `scene`; used for items whose manifest entry has no type |
| `planned_at` | Set at seal. Items are claimable only after this. |
| `last_upload_at` | Last byte receipt; drives "upload interrupted" and abandonment |
| `dismissed_at` | Hidden from the activity dock. Deletes nothing. |
| `created_at`, `updated_at`, `completed_at` | |

### `import_groups`

Groups worked out from paths at seal time.

| Column | Notes |
|---|---|
| `id`, `job_id` | |
| `author`, `group_name` | Parser output |
| `image_group_id` | Gallery group this resolves to: an existing one (merge) or one created on first commit |
| `merged_into_existing` | An `ImageGroup` with the same `(base_name, author)` existed at plan time. Undo never deletes such groups. |
| `sort_order` | Processing order within the job |

### `import_items`

One row per file. All durable ingest state lives here.

| Column | Notes |
|---|---|
| `id`, `job_id`, `import_group_id` | `import_group_id` is NULL until planned |
| `kind` | `image` \| `video` \| `archive` (a zip that failed to expand is one failed `archive` item) |
| `relative_path`, `filename` | Display and resume matching only; **never used as a filesystem path**. Unique per job (`uq_import_items_job_path`). |
| `size`, `last_modified` | From the client manifest |
| `image_type` | `battlemap` \| `scene` |
| `parsed` | JSON parser output (name, subgroup, tags, filename grid info), set at plan time |
| `state` | See [Item states](#item-states) |
| `staging_key` | Server-generated staged filename; NULL until received and cleared once no longer needed |
| `source_hash` | SHA-256 of the original bytes. Client hint before upload; server-computed (authoritative) on receipt |
| `attempts`, `retry_after` | Claim counter (crash/poison detection) and transient-error backoff |
| `error_kind`, `error_stage`, `error_reason`, `error_detail` | `error_kind` ∈ `file` \| `transient` \| `system` \| `bytes_lost`; `error_reason` is user-facing, `error_detail` the raw exception (truncated to 4000 chars) |
| `image_id` | Set when `done` |
| `duplicate_of_image_id`, `duplicate_tier` | Set when `duplicate` (`bytes` \| `pixels`) |
| `allow_duplicate` | Set by "Import as new copy"; skips dedup |
| `similar_to_image_id`, `similarity_distance` | Reserved for perceptual-duplicate flags; not populated yet |

Indexes: `(state, job_id)` for claiming, `(job_id, state)` for counts, `(job_id, import_group_id)`.

### Image columns written by ingest

`images.content_hash` (SHA-256 of the original bytes), `stored_hash` (SHA-256 of the stored file; equal to `content_hash` because no conversion happens yet), `pixel_hash` (NULL for video and for reduced-scale JPEG decodes), `phash` (64-bit, NULL for video), and `import_job_id` (provenance and Undo). See [storage.md](storage.md).

## State machines

### Item states

```
                 ┌───── import as new copy ──────┐
                 ▼                               │
awaiting_bytes ─bytes received─▶ ready ─claim─▶ processing ─commit─▶ done
   │   │                          ▲  ▲              │ │
   │   └─hash matches library ────┼──┼──────────────┼─┴─dedup at commit─▶ duplicate
   │                              │  └─transient err (retry_after)
   │                              └── retry ─────── failed ◀── file error / crash limit
   └─ finish-without / cancel / abandoned ─▶ skipped
                                    (cancel also: ready ─▶ skipped)
```

The table in `ingest_state._TRANSITIONS` is the source of truth:

| From | Event | To |
|---|---|---|
| `awaiting_bytes` | `BYTES_RECEIVED` | `ready` |
| `awaiting_bytes` | `HASH_DUPLICATE` (client hash or received bytes match the library) | `duplicate` |
| `awaiting_bytes` | `FILE_ERROR` (bytes fail the magic-byte check; also manifest validation) | `failed` |
| `awaiting_bytes`, `ready` | `SKIP` (cancel, finish-without, skip group, abandoned, unsupported file in manifest) | `skipped` |
| `ready` | `CLAIM` (`attempts += 1`) | `processing` |
| `processing` | `COMMITTED` | `done` |
| `processing` | `DUPLICATE_AT_COMMIT` | `duplicate` |
| `processing` | `FILE_ERROR` | `failed` |
| `processing` | `TRANSIENT_RETRY` (attempts < 3) | `ready` with `retry_after` (5 s, 20 s, 80 s…) |
| `processing` | `GIVE_UP` (transient, attempts exhausted) | `failed` |
| `processing` | `SYSTEM_ERROR` (attempt refunded; queue pauses) | `ready` |
| `processing` | `BYTES_LOST` (staged file missing) | `awaiting_bytes` |
| `processing` | `RECOVERED` (startup, attempts < 3) | `ready` |
| `processing` | `CRASH_LIMIT` (startup, attempts ≥ 3: "Repeatedly crashed during processing") | `failed` |
| `failed` | `RETRY` / `RETRY_NEEDS_BYTES` | `ready` / `awaiting_bytes` |
| `duplicate` | `IMPORT_AS_COPY` / `IMPORT_AS_COPY_NEEDS_BYTES` | `ready` / `awaiting_bytes`, with `allow_duplicate` |

Terminal: `done`, `duplicate`, `failed`, `skipped`. `failed` and `duplicate` can be re-opened by user action. `MAX_ATTEMPTS = 3`.

### Job states

- **`active`**: the worker may claim its items.
- **`paused`**: user pause; the worker skips the job.
- **`completed`**: planned and no items in `awaiting_bytes`, `ready` or `processing`.
- **`cancelled`**: sticky. Open items become `skipped`; finished work is kept.

`ingest_state.compute_job_status()` derives the status; `ingest_queue.recompute_job_status()` is the only writer and is called after every item transition (byte receipt, client hashes, batch commit, failures, recovery, retry, import-as-copy, skip). A retry on a completed job re-opens it. **A job never fails**: outcomes are counts.

Derived in the API, never stored:
- **`upload_interrupted`**: active, items awaiting bytes, nothing ready or processing, and `last_upload_at` older than 2 minutes (`UPLOAD_STALL`). The UI offers "Choose files to resume" or "Finish without them".
- **Queue status** (`running`, `system_paused`, `reason`, `current_job_id`) from the worker.

**Undo import** (`DELETE /imports/{id}`) cancels the job, refuses with 409 while a batch is processing, deletes every image with that `import_job_id`, deletes gallery groups the job created (not merged-into ones) if now empty, then the job, groups, items and staging directory. Rows are deleted and committed first; files and vectors are removed afterwards (`deletion_service.PendingFileDeletes`).

## Upload protocol

All routes are under `/api/v1/imports` (`backend/app/api/imports.py`). Mutating routes take SQLite's write lock up front (`get_write_db` → `BEGIN IMMEDIATE`). Blocking work runs in `asyncio.to_thread`; bodies are streamed with async I/O.

| Route | Purpose |
|---|---|
| `POST /imports` | `{label, default_image_type}` → job summary (201) |
| `POST /imports/{id}/manifest` | Chunk of ≤2,000 `{client_ref, relative_path, size, last_modified, image_type?}`. OS junk (`._*`, `__MACOSX`, `.DS_Store`, `Thumbs.db`, `desktop.ini`) is ignored; unsupported files become `skipped`, oversized ones `failed`. Paths already in the job are ignored. 413 above `max_import_items` per import; 409 after seal. |
| `PUT /imports/{id}/archives?name=…` | Raw zip body, expanded into items (`ingest_archive.expand_archive`). `check_zip_safety` enforces `max_import_files` and `max_import_total_size` per archive; every member is magic-byte checked. A zip that fails becomes one failed `archive` item. Gated by the heavy-op semaphore. 409 after seal. |
| `POST /imports/{id}/seal` | Parse and group paths, resolve groups against the gallery (`IN` queries chunked at 500), set `planned_at`, wake the worker. Checks free space on the staging and library volumes (507 if short, with a 512 MB margin). Idempotent. Gated by the heavy-op semaphore. |
| `POST /imports/{id}/hashes` | Chunk of ≤2,000 `{item_id, sha256}`. Items whose hash matches the library become `duplicate` without uploading. The client hash is only used to skip. |
| `PUT /imports/{id}/items/{item_id}/content` | Raw body streamed to `staging/{job_id}/.{staging_key}.part` with inline SHA-256, then magic-byte check (`verify_media_mime`), rename to `staging/{job_id}/{staging_key}` (`staging_key` = uuid hex + extension) and `mark_bytes_received` (→ `ready` or `duplicate`). Size limit `max_import_file_size` (`max_video_file_size` for videos). Idempotent: an item already past `awaiting_bytes` drains the body and returns its state. |
| `GET /imports` | Job summaries for the dock (counts by state, group count, `upload_interrupted`) plus queue status. Weak `ETag` from the worker's version counter plus a minute bucket; `If-None-Match` → 304. |
| `GET /imports/{id}` | One job with per-group counts and resolution |
| `GET /imports/{id}/items` | Paginated (keyset on `id`, `after` / `next_after`), filter by `state`, `group_id`, `error_kind` |
| `POST /imports/{id}/pause`, `/resume`, `/cancel` | Job control |
| `POST /imports/{id}/groups/{group_id}/skip` | Skip one group's open items |
| `POST /imports/{id}/retry` | `{item_ids?}`, default all `failed` |
| `POST /imports/{id}/import-as-copy` | `{item_ids?}`, default all `duplicate` |
| `POST /imports/{id}/finish-upload` | `awaiting_bytes` → `skipped` ("Not uploaded") |
| `POST /imports/{id}/dismiss` | Hide a completed/cancelled job from the dock |
| `DELETE /imports/{id}` | Undo import |
| `POST /imports/queue/probe` | Re-check system conditions now ("Retry now") |

Security properties ([security.md](security.md)): `item_id` is always scoped to `job_id`; staged filenames are server-generated; `relative_path` never reaches the filesystem.

### Client sequence

`ImportManager` (`frontend/src/lib/import/ImportManager.ts`) is a module-level store read through `useSyncExternalStore` hooks; dialogs and the dock are views over it.

```
create job → manifest chunks → (archives) → seal ──▶ show group plan
                                              │
             hash worker ──50-file rounds──▶ POST /hashes ──▶ skip dups
                  │                                            │
                  └─ runs ahead of ─▶ upload pool (3 PUTs) ◀───┘
                                       ▼
                     worker processes items as they become ready
```

- Hashing runs in a Web Worker. It is skipped in insecure contexts (no `crypto.subtle`, e.g. plain-HTTP LAN) and for files over 256 MB; dedup then happens server-side after upload.
- Upload retries: network errors back off (cap 30 s) and retry while the tab is open ("waiting for connection"); 5xx/408/429 retry up to 5 times, then the file is a local failure (still `awaiting_bytes` server-side, so it can be resumed); 409/404 stop quietly; other 4xx fail the file.
- If setup (manifest, archives, seal, hashes) fails, the job is cancelled so it can't sit active forever.
- One poller for `GET /imports`: 1 s while active, 5 s when the tab is hidden, 30 s idle; error backoff capped at 5 s drives a `degraded` / `lost` connection state.
- `beforeunload` guard while bytes are outstanding. Nothing is persisted locally: resume works from any tab by re-picking files, matched on `(relative_path, size)` against the job's `awaiting_bytes` items.

## Ingest worker

`IngestWorker` (`backend/pipeline/ingest_worker.py`) is one loop thread per process, created by `get_ingest_worker()` and started in the FastAPI lifespan when `ingest_worker_enabled` is true (after `recover()`). `JobRunner` is not used for imports; it runs maintenance, backfills and rebuilds. Shutdown waits up to 60 s for the batch in progress.

```
recover()                                # startup: clear .incoming/, re-queue processing items
loop:
    if held or system-paused: wait / re-probe; continue
    probe()                              # model available, library reachable, free space
    claim_next_batch(cursor, ingestion_batch_size)
    process_batch(items)                 # prepare → embed → commit → vectors → staging cleanup
    bump()                               # version counter → ETag
    if nothing claimed: wait on wake event (30 s timeout)
```

- **Wake-ups**: an in-process `threading.Event`, set on byte receipt, seal, resume, retry and import-as-copy.
- **Claiming**: round-robin across `active`, planned jobs with claimable items (ordered by `created_at`), so a small import isn't stuck behind a large one. Within a job, items go in `(import_groups.sort_order, id)` order. Claimable = `ready`, not an archive, and `retry_after` NULL or past. Batch size `ingestion_batch_size` (default 16).
- **Single-process assumption**: no leases. At startup every `processing` item is orphaned by definition.
- **Holds**: `held(reason)` pauses the queue for the duration of a block and waits for the in-flight batch. The model switch (`backend/app/api/models.py`) uses it ("Paused while the AI model changes"). Holds appear as a system pause.
- **Tests and CLI** drive it synchronously with `drain()`; no thread is needed.

### Batch processing (`ingest_process.py`)

1. **`prepare_item`** (on the shared prepare pool, no DB writes):
   - Missing staged file → `bytes_lost` failure.
   - `plan_decode` reads the header and estimates peak memory; the item reserves that from `MemoryBudget` before decoding.
   - Decode once. JPEGs over `pixel_hash_max_pixels` are decoded at reduced scale (`Image.draft`) and skip the pixel hash; PNG/WebP always decode in full.
   - From that decode: pixel hash, then thumbnails (150/400/800 px JPEG, cascading large → small, LANCZOS). Colours and pHash read the 800 px thumbnail. Grid detection (`_detect_grid`, battlemaps only) re-reads the file, at reduced scale where possible; see [parser.md](parser.md#grid-detection).
   - Copy the original to `{image library}/.incoming/` and write thumbnails to `{thumbnail store}/.incoming/`, so final placement is a same-volume rename.
   - Videos: first frame for thumbnails and embedding; no pixel hash or pHash.
   - Failures are classified with the stage reached (`decode`, `hash`, `thumbnails`, `colors`, `grid_detection`, `copy`) and temp files are deleted.
2. **`embed`**: one batched embedding call over the medium thumbnails. On error, every item in the batch fails together (stage `embedding`).
3. **`commit_batch`**: one `BEGIN IMMEDIATE` transaction (`write_session`). SQLite's single writer makes check-then-insert race-free.
   - Dedup against the library and earlier items in the batch, unless `allow_duplicate`: `content_hash`/`stored_hash` → tier `bytes`, `pixel_hash` → tier `pixels`.
   - Rename temp files into place; insert image, tags and colours; resolve or create the `ImageGroup` and record it on `import_groups.image_group_id`; mark items `done`, clear `staging_key`; recompute job status.
   - On exception, placed files are deleted and every item fails with stage `db_save`.
4. **`write_vectors`**: LanceDB write after the commit. Failure is logged, not fatal; reconciliation repairs it.
5. Staged files of `done` items are deleted. A crash between commit and this step leaves files for the stray-staging sweep.

Crash windows: between rename and commit → orphan store files (orphan sweep); between commit and vector write → missing vector (reconciliation). FTS is kept current by triggers; there is no per-job rebuild.

## Duplicate detection

| Tier | Hash | Where | Catches | Action |
|---|---|---|---|---|
| Bytes | SHA-256 of the original (`content_hash`), plus `stored_hash` | Client (hint, `POST /hashes`), server on receipt, and at commit | Identical file, re-imported export | Auto-skip (`duplicate`, tier `bytes`) |
| Pixels | SHA-256 of canonical decoded pixels: EXIF orientation applied, RGBA, colour zeroed under fully transparent pixels, hashed in strips | Worker, at commit | Same image re-saved (PNG ↔ lossless WebP, metadata edits) | Auto-skip at commit (tier `pixels`) |
| Similar | 64-bit DCT pHash (`phash`) | Worker, from the 800 px thumbnail | Lossy re-encodes, resizes, gridded vs gridless | Stored only. No flags or UI yet. |

pHash never auto-skips: battlemap variants differ by thin grid lines or small props, which a pHash discards. Videos use the bytes tier only.

**Import as new copy** moves `duplicate` items back to `ready` (or `awaiting_bytes` when no bytes were ever sent) with `allow_duplicate`. The item is processed exactly like a new file and produces an independent image (own stored file, thumbnails, embedding). Staged bytes of `duplicate` items are kept for this; client-hash-skipped items never sent bytes, so they return to `awaiting_bytes` and the job shows as upload interrupted until the files are re-picked (or finished without).

## Error classification

`classify_ingest_error(exc, stage)` in `backend/pipeline/error_classifier.py` returns `{reason, kind, stage, detail}`. `reason` is shown in the import report; `detail` is the raw exception text (stored in `error_detail` and logged).

Rules, checked in order:

| Exception / pattern | Reason | Kind |
|---|---|---|
| `SystemUnavailableError` | its message | `system` |
| "embedding service unavailable" | No AI model is available | `system` |
| `UnidentifiedImageError` / "cannot identify image file" | Image is corrupt or not a supported format | `file` |
| `DecompressionBombError` | Image is too large to process safely | `file` |
| "truncated" | Image file is incomplete or truncated | `file` |
| "could not read image" (OpenCV) | Image could not be read for processing | `file` |
| `OSError` with `ENOSPC` | Not enough disk space to process image | `system` |
| `FileNotFoundError` | File was not found | `file` |
| `PermissionError` | File could not be accessed (permission denied) | `file` |
| SQLite "locked" / "busy" | The database was busy; will retry | `transient` |
| `MemoryError` | Image is too large to process (out of memory) | `transient` |
| stage `embedding` | Failed to generate image embedding | `transient` |
| stage `db_save` | Failed to save image to database | `transient` |
| stage `vector_save` | Failed to save image embedding to search index | `transient` |
| anything else | Processing failed during {stage} | `transient` |

Unknown errors are transient so a flaky failure recovers and a deterministic one costs at most three attempts. `record_failures` applies the kind: `file` → `failed`; `transient` → `ready` with backoff, or `failed` after 3 attempts; `system` → `ready` with the attempt refunded and the queue paused; `bytes_lost` → `awaiting_bytes`. API-side validation failures use stage `validate`; crash-limit failures use stage `processing`.

### System pause

Held in worker memory and re-detected after a restart. `default_probe()` checks: embedding model available (`get_clip_unavailable_reason`), image library folder exists, and at least 512 MB free on the library, thumbnail-store and staging volumes. While paused, the worker re-probes every 30 s; `POST /imports/queue/probe` probes immediately, and the lifespan probes once the model has loaded.

## Memory budget

`MemoryBudget` (`backend/app/services/memory_budget.py`) bounds the total estimated peak memory of concurrent prepare steps, independent of `max_concurrent_prepare`. Capacity is `ingest_memory_budget_mb` if set, else half of RAM beyond a 2 GiB reserve (minimum 1 GiB). An item larger than the whole budget runs alone rather than deadlocking. Estimates come from `plan_decode` (decoded pixels × bytes per pixel, progressive-JPEG coefficient buffers, and the grid-detection read at `grid_detection_max_dim`).

## Maintenance

| Task | When | Behaviour |
|---|---|---|
| `IngestWorker.recover()` | Startup | Deletes `.incoming/` in both stores; `recover_interrupted()` returns `processing` items to `ready`, or fails them at 3 attempts. Deletes no images. |
| `ingest_maintenance` (`run_ingest_maintenance`) | Scheduler, every 6 h | `abandon_stale_uploads`: active/paused jobs with no bytes for 7 days → `awaiting_bytes` items `skipped` ("Not uploaded"). `release_staged_bytes`: staged files of `done`/`skipped` items always; of `failed`/`duplicate` items once the job is dismissed or finished more than 7 days ago. `prune_dismissed_jobs`: job/group/item rows of jobs dismissed over 30 days ago (images untouched). `sweep_stray_staging_files`: unreferenced staging files and directories older than 1 h. |
| `reconcile_vectors` | Startup (once the model has loaded, via `JobRunner`) and scheduler every 24 h | Compares SQLite and LanceDB id sets; re-embeds missing images from their thumbnails and deletes orphaned vectors. |
| `sweep_orphaned_store_files` | Scheduler, every 24 h | Deletes store files no image references. Only considers the `xx/yy/<key>` shard layout (so `.incoming/` and `backups/` are never touched), ignores files younger than 1 h, and deletes nothing if more than 25% of the store looks orphaned. |
| `backup_database` | Scheduler, every 24 h | SQLite + LanceDB snapshot with rotation |

Scheduled tasks are registered in `backend/app/main.py`. The scheduler (`backend/app/services/scheduler.py`) persists each task's last run under `{APP_DATA_DIR}/scheduler/` and runs overdue tasks shortly after startup, so short Electron sessions still get maintenance.

Staging is never cleaned by file age alone, and active imports are never expired.

## Recovery and crash supervision

- **Backend crash or kill mid-import**: on restart, `recover()` re-queues in-flight items (one attempt used). An item that crashes the process three times fails instead of crash-looping. Uploads interrupted mid-stream leave `.part` files for the stray-staging sweep; the item stays `awaiting_bytes` and the client resumes it.
- **Supervisors**: `scripts/app/start.py` (development and server mode) runs the backend and frontend as child processes and restarts a crashed child with exponential backoff, giving up after 10 crashes in 5 minutes. `backend/pyinstaller/entry.py` (Electron sidecar) restarts uvicorn in-process with the same limit; module-level state survives such a restart.

## Settings

Environment / `.env` (`backend/app/config.py`):

| Setting | Default | Purpose |
|---|---|---|
| `max_import_items` | 50,000 | Files per import, across all manifest chunks |
| `ingest_memory_budget_mb` | unset (auto) | Memory budget capacity |
| `max_image_pixels` | 1,000,000,000 | Pillow `MAX_IMAGE_PIXELS` (set in `logging_config.py`) |
| `pixel_hash_max_pixels` | 100,000,000 | JPEGs above this are decoded at reduced scale and skip the pixel hash |
| `ingest_worker_enabled` | true | Start the worker in the lifespan (tests disable it) |
| `supported_formats` | `.jpg .jpeg .png .webp` | Image extensions |
| `supported_video_formats` | `.mp4 .webm` | Video extensions |
| `thumbnail_sizes` | 150, 400, 800 px | Thumbnail boxes |

App settings (database, seeded on first boot by `seed_default_settings` in `backend/app/models/database.py`; read per batch through `PipelineConfig` in `backend/pipeline/pipeline_config.py`):

| Setting | Seeded default | Purpose |
|---|---|---|
| `ingestion_batch_size` | 16 | Claim / embed / commit batch |
| `max_concurrent_prepare` | `min(cpu, 8, RAM-based cap)` (`resource_detector.py`) | Prepare pool size (fixed at startup) |
| `max_concurrent_heavy_requests` | `min(cpu // 2, 6)` | Heavy-op semaphore (archive upload, seal) |
| `max_import_file_size` | 2 GB | Per file, and per uploaded archive body |
| `max_video_file_size` | 2 GB | Per video file |
| `max_import_files` | 1,000 | Entries per uploaded zip |
| `max_import_total_size` | 2 GB | Uncompressed size per uploaded zip |
| `enable_image_grid_detection` | true | Image-analysis grid detection for battlemaps |
| `grid_detection_max_dim` | 8,000 | Longest side analysed by grid detection |
| `grid_min_cell_px` / `grid_max_cell_px` | 32 / 320 | Cell size range |
| `grid_presence_threshold` / `grid_size_threshold` | 0.20 / 0.15 | Confidence thresholds |
| `grid_period_ratio_threshold` / `grid_hex_rot_conf` | 0.98 / 0.20 | Square vs hex classification |
| `num_dominant_colors`, `color_clustering_samples`, `color_kmeans_n_init` | 5, 5000, 3 | Colour extraction |
| `convert_to_webp`, `webp_lossless`, `webp_quality` | false, true, 95 | Accepted and stored but **not used** by the ingest pipeline; stored files are always the original bytes |

## Logging

`backend/app/logging_config.py` `setup_logging(data_dir, debug)` is called once per entry point (`backend/app/main.py`, `backend/pyinstaller/entry.py`). Handlers: stdout and a `RotatingFileHandler` at `{APP_DATA_DIR}/logs/scene-atlas.log` (10 MB, 5 backups). Format `%(asctime)s %(levelname)-8s [%(name)s] %(message)s`. `debug` sets `DEBUG`, otherwise `INFO`. Modules use `logging.getLogger(__name__)`.

## CLI entry points

Run with `uv run python -m <module>`:

- `backend.pipeline.backfill_content_hash`: compute missing `content_hash` values
- `backend.pipeline.backfill_grid_detection`: run grid detection over existing battlemaps
- `backend.pipeline.reparse_names`: re-run the name parser over existing images
- `backend.pipeline.retag_all_images`: regenerate auto tags from filenames (manual tags kept)
- `backend.pipeline.fix_orphaned_images`: put images without a group into an "Uncategorised" group
- `backend.pipeline.export_library`: copy the library into an `Author/Group/` folder tree with `metadata.json`

There is no CLI for bulk import of a local folder; imports go through the API.
