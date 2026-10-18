# Ingestion

How files get from the user's disk into the library: the import data model, the item state machine, the upload protocol, the ingest worker, duplicate detection, maintenance and recovery.

Rationale: [ADR-018](decisions.md#adr-018-durable-per-item-ingest-pipeline). The pipeline replaced an earlier job-and-confirm design in October 2026 (PR #1; stored format added later); Scene Atlas was unreleased, so the old tables, statuses and endpoints were removed without a data migration. In the desktop app, picked and dropped files are read in place rather than uploaded: [local-ingest.md](local-ingest.md). Path parsing and grouping: [parser.md](parser.md). Concurrency controls: [resource-management.md](resource-management.md).

Section numbers are referenced from code comments (`design/ingestion.md §N`); keep them stable.

## Code map

| Module | Responsibility |
|---|---|
| `backend/app/services/ingest_state.py` | Pure item/job state machines (no DB). `sources_for(event)` feeds DB `WHERE` clauses so illegal transitions can't be written. |
| `backend/pipeline/ingest_queue.py` | Durable operations: create, manifest, plan (seal), byte receipt, client hashes, claim, failures, recovery, retry, import-as-copy, skip, pause/resume/cancel, undo, `recompute_job_status`, `write_session()` (`BEGIN IMMEDIATE`). |
| `backend/pipeline/ingest_process.py` | One batch: `prepare_item` → `embed` → (`sort_auto_items` → `finish_item`) → `commit_batch` → `write_vectors`, orchestrated by `process_batch`. |
| `backend/app/services/image_type_classifier.py` | Bundled image-type heads (map / illustration / token / other), matched to the installed encoder by sha256; Auto imports ([§5.6](#56-auto-image-type)). |
| `backend/pipeline/ingest_worker.py` | `IngestWorker` loop thread and `get_ingest_worker()`. |
| `backend/pipeline/ingest_archive.py` | Server-side zip expansion into items (before seal). |
| `backend/pipeline/ingest_local.py` | Local imports (desktop app): list picked folders and files into ready items read in place ([local-ingest.md](local-ingest.md)). |
| `backend/pipeline/ingest_maintenance.py` | Scheduled, state-based cleanup. |
| `backend/pipeline/image_hashes.py` | File SHA-256, strip-wise pixel hash, DCT pHash. |
| `backend/pipeline/stored_format.py` | Optional conversion of new imports to the configured stored format. |
| `backend/pipeline/vector_reconcile.py` | SQLite ↔ LanceDB id-set reconciliation. |
| `backend/pipeline/error_classifier.py` | Exception → user-facing reason and `kind`. |
| `backend/app/services/memory_budget.py` | `MemoryBudget`: memory-aware admission for prepare. |
| `backend/app/api/imports.py`, `backend/app/models/import_schemas.py` | HTTP API and its models. |
| `frontend/src/lib/import/` | `ImportManager` (client-side owner of uploads and polling), `importClient`, `hasher` + `hash.worker`, `useImports` hooks. |
| `frontend/src/components/imports/` | `ImportDialog` (with `ImportResultView`), `GroupLedger`, `ImportJobRow` (activity dock row). |

## 1. Why

A reliability audit (2026-10-12) found about 50 issues in the old import flow, from three structural causes: the job was an all-or-nothing transaction (a restart or one failed group deleted every image it had imported); there was no durable per-file state (the file list lived in `JobRunner` kwargs, so nothing could resume or be cancelled); and the browser drove the lifecycle, so tab closes and remounts stranded jobs. Duplicate detection also broke under WebP conversion, and imports over ~32k files hit SQLite's variable limit. Details: [ADR-018](decisions.md#adr-018-durable-per-item-ingest-pipeline).

## 2. Principles

- **The file is the unit of work and of commit.** Once a file is committed it stays. Other files failing never undoes it.
- **Jobs aggregate; they don't decide.** A job is what the user started ("Forest Pack.zip"). Its status is derived from its items.
- **The backend owns the lifecycle.** The client describes files and supplies bytes. Closing the tab can interrupt an upload, never processing.
- **Nothing destructive happens implicitly.** Cancel keeps finished work. Deleting imported images only happens through an explicit "Undo import".
- **File problems fail the file; system problems pause the queue.** A full disk or missing AI model never fails items.
- **Automatic duplicate rules have zero false positives.** Near-duplicates (gridded vs gridless, lighting variants) are what groups exist to hold.

## 3. Data model

```
import_jobs 1───* import_groups 1───* import_items *───1 images
                                       (image_id / duplicate_of_image_id)
```

Defined in `backend/app/models/database.py`; tables created by Alembic `020_ingest_items.py`, legacy tables dropped by `021_drop_legacy_import_tables.py`.

### 3.1 `import_jobs`

| Column | Notes |
|---|---|
| `id` | uuid hex |
| `status` | `active` \| `paused` \| `completed` \| `cancelled` |
| `source_label` | Display label, e.g. "Forest Pack.zip" (sent as `label` by the API) |
| `default_image_type` | `battlemap` \| `scene` \| `auto`; used for items whose manifest entry has no type |
| `planned_at` | Set at seal. Items are claimable only after this. |
| `last_upload_at` | Last byte receipt; drives "upload interrupted" and abandonment |
| `source_roots` | Local imports: JSON list of the folders the job reads from; the worker skips the job while any is missing |
| `dismissed_at` | Hidden from the activity dock. Deletes nothing. |
| `created_at`, `updated_at`, `completed_at` | |

### 3.2 `import_groups`

Groups worked out from paths at seal time.

| Column | Notes |
|---|---|
| `id`, `job_id` | |
| `author`, `group_name` | Parser output |
| `image_group_id` | Gallery group this resolves to: an existing one (merge) or one created on first commit |
| `merged_into_existing` | An `ImageGroup` with the same `(base_name, author)` existed at plan time. Undo never deletes such groups. |
| `sort_order` | Processing order within the job |

### 3.3 `import_items`

One row per file. All durable ingest state lives here.

| Column | Notes |
|---|---|
| `id`, `job_id`, `import_group_id` | `import_group_id` is NULL until planned |
| `kind` | `image` \| `video` \| `archive` (a zip that failed to expand is one failed `archive` item) |
| `relative_path`, `filename` | Display and resume matching only; **never used as a filesystem path**. Unique per job (`uq_import_items_job_path`). |
| `size`, `last_modified` | From the client manifest |
| `image_type` | `battlemap` \| `scene` \| `auto` (resolved while processing; set to a fixed type on include) |
| `parsed` | JSON parser output (name, subgroup, tags, filename grid info), set at plan time. Auto items also carry `scene_tags` ([§5.6](#56-auto-image-type)) |
| `classification` | Auto items: JSON `{group, probabilities, fell_back, head}` from the image-type head |
| `preview_key` | Items Auto sorted out: a preview (the medium thumbnail) in the job's staging folder |
| `state` | See [§4.1](#41-item-states) |
| `staging_key` | Server-generated staged filename; NULL until received and cleared once no longer needed |
| `source_hash` | SHA-256 of the original bytes. Client hint before upload; server-computed (authoritative) on receipt |
| `source_path` | Local imports: absolute path of the original, read by the worker and never written. Exactly one of `staging_key` / `source_path` locates an item's bytes |
| `attempts`, `retry_after` | Claim counter (crash/poison detection) and transient-error backoff |
| `error_kind`, `error_stage`, `error_reason`, `error_detail` | `error_kind` ∈ `file` \| `transient` \| `system` \| `bytes_lost`, or `sorted_out` on a skipped item Auto set aside; `error_reason` is user-facing, `error_detail` the raw exception (truncated to 4000 chars) |
| `image_id` | Set when `done` |
| `duplicate_of_image_id`, `duplicate_tier` | Set when `duplicate` (`bytes` \| `pixels`) |
| `allow_duplicate` | Set by "Import as new copy"; skips dedup |
| `similar_to_image_id`, `similarity_distance` | Reserved for perceptual-duplicate flags; not populated yet |

Indexes: `(state, job_id)` for claiming, `(job_id, state)` for counts, `(job_id, import_group_id)`.

### 3.4 Image columns written by ingest

`images.content_hash` (SHA-256 of the original bytes), `stored_hash` (SHA-256 of the stored file; equal to `content_hash` unless the file was converted, see [§10](#10-stored-format)), `pixel_hash` (NULL for video and for reduced-scale JPEG decodes), `phash` (64-bit, NULL for video), and `import_job_id` (provenance and Undo). See [storage.md](storage.md).

## 4. State machines

### 4.1 Item states

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
| `processing` | `SOURCE_UNAVAILABLE` (a local import's folder is missing; attempt refunded, job waits) | `ready` |
| `processing` | `RECOVERED` (startup, attempts < 3) | `ready` |
| `processing` | `CRASH_LIMIT` (startup, attempts ≥ 3: "Repeatedly crashed during processing") | `failed` |
| `failed` | `RETRY` / `RETRY_NEEDS_BYTES` | `ready` / `awaiting_bytes` |
| `duplicate` | `IMPORT_AS_COPY` / `IMPORT_AS_COPY_NEEDS_BYTES` | `ready` / `awaiting_bytes`, with `allow_duplicate` |
| `processing` | `SORTED_OUT` (Auto: token, other or unsure; `error_kind = sorted_out`) | `skipped` |
| `skipped` | `INCLUDE` / `INCLUDE_NEEDS_BYTES` (only items with `error_kind = sorted_out`; the queue checks it) | `ready` / `awaiting_bytes`, with a fixed `image_type` |

Terminal: `done`, `duplicate`, `failed`, `skipped`. `failed`, `duplicate` and sorted-out `skipped` items can be re-opened by user action. `MAX_ATTEMPTS = 3`.

### 4.2 Job states

- **`active`**: the worker may claim its items.
- **`paused`**: user pause; the worker skips the job.
- **`completed`**: planned and no items in `awaiting_bytes`, `ready` or `processing`.
- **`cancelled`**: sticky. Open items become `skipped`; finished work is kept.

`ingest_state.compute_job_status()` derives the status; `ingest_queue.recompute_job_status()` is the only writer and is called after every item transition (byte receipt, client hashes, batch commit, failures, recovery, retry, import-as-copy, skip). A retry on a completed job re-opens it. **A job never fails**: outcomes are counts.

Derived in the API, never stored:
- **`upload_interrupted`**: active, items awaiting bytes, nothing ready or processing, and `last_upload_at` older than 2 minutes (`UPLOAD_STALL`). The UI offers "Choose files to resume" or "Finish without them".
- **`waiting_for`**: a local import's folders that are missing right now (open, not cancelled). The dock and dialog say "Waiting for …".
- **`local`**: the job reads from folders on this computer (`source_roots` set); there is nothing to upload or resume.
- **Queue status** (`running`, `system_paused`, `reason`, `current_job_id`) from the worker.

**Undo import** (`DELETE /imports/{id}`) cancels the job, refuses with 409 while a batch is processing, deletes every image with that `import_job_id`, deletes gallery groups the job created (not merged-into ones) if now empty, then the job, groups, items and staging directory. Rows are deleted and committed first; files and vectors are removed afterwards (`deletion_service.PendingFileDeletes`).

## 5. Processing: the ingest worker

`IngestWorker` (`backend/pipeline/ingest_worker.py`) is one loop thread per process, created by `get_ingest_worker()` and started in the FastAPI lifespan when `ingest_worker_enabled` is true (after `recover()`). `JobRunner` is not used for imports; it runs maintenance, backfills and rebuilds. Shutdown waits up to 60 s for the batch in progress.

### 5.1 Loop

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

### 5.2 Scheduling

- **Wake-ups**: an in-process `threading.Event`, set on byte receipt, seal, resume, retry and import-as-copy.
- **Claiming**: round-robin across `active`, planned jobs with claimable items (ordered by `created_at`), so a small import isn't stuck behind a large one. Within a job, items go in `(import_groups.sort_order, id)` order. Claimable = `ready`, not an archive, and `retry_after` NULL or past. Batch size `ingestion_batch_size` (default 16).
- **Single-process assumption**: no leases. At startup every `processing` item is orphaned by definition.
- **Holds**: `held(reason)` pauses the queue for the duration of a block and waits for the in-flight batch. The model switch (`backend/app/api/models.py`) uses it ("Paused while the AI model changes"). Holds appear as a system pause.
- **Tests and CLI** drive it synchronously with `drain()`; no thread is needed.

### 5.3 Commit protocol

One batch, in `ingest_process.py`:

1. **`prepare_item`** (on the shared prepare pool, no DB writes):
   - Missing staged file → `bytes_lost` failure.
   - `plan_decode` reads the header and estimates peak memory; the item reserves that from `MemoryBudget` before decoding.
   - Decode once. JPEGs over `pixel_hash_max_pixels` are decoded at reduced scale (`Image.draft`) and skip the pixel hash; PNG/WebP always decode in full.
   - From that decode: pixel hash, then thumbnails (150/400/800 px, cascading large → small, LANCZOS; JPEG, or RGBA WebP when the image has transparent pixels; see [storage.md](storage.md#key-generation)). Colours and pHash read the 800 px thumbnail; colour extraction ignores transparent pixels. Grid detection (`_detect_grid`, battlemaps only) re-reads the file: detector v3 at full resolution for maps of 1000 px or more (unless `grid_analysis_max_dim` is set), the legacy detector below that; see [parser.md](parser.md#2-grid-detection-battlemaps-only) and [grid-detection-v3.md](grid-detection-v3.md).
   - Convert to the stored format if configured ([§10](#10-stored-format)), writing straight into `{image library}/.incoming/`.
   - Otherwise copy the original to `{image library}/.incoming/`. Thumbnails are written to `{thumbnail store}/.incoming/`. Temp files sit on their destination's volume, so final placement is a rename, and the one unavoidable library-drive write happens in parallel with CPU work, outside the write lock.
   - Videos: first frame for thumbnails and embedding; no pixel hash or pHash.
   - Failures are classified with the stage reached (`decode`, `hash`, `thumbnails`, `colors`, `grid_detection`, `convert`, `copy`) and temp files are deleted.
   - Auto items stop after colours (and the head's image features), as a `DecodedItem`: grid detection and storing the original wait for their type ([§5.6](#56-auto-image-type)). Everything else is prepared in one pass and one memory reservation, as above.
2. **`embed`**: one batched embedding call over the medium thumbnails. On error, every item in the batch fails together (stage `embedding`). Auto items are then sorted, and maps and scenes are finished on the prepare pool (`finish_item`, with its own reservation from `finish_peak_bytes`).
3. **`commit_batch`**: one `BEGIN IMMEDIATE` transaction (`write_session`). SQLite's single writer makes check-then-insert race-free.
   - Dedup against the library and earlier items in the batch, unless `allow_duplicate`: `content_hash`/`stored_hash` → tier `bytes`, `pixel_hash` → tier `pixels`.
   - Rename temp files into place; insert image, tags and colours; resolve or create the `ImageGroup` and record it on `import_groups.image_group_id`; mark items `done`, clear `staging_key`; recompute job status.
   - On exception, placed files are deleted and every item fails with stage `db_save`.
4. **`write_vectors`**: LanceDB write after the commit. Failure is logged, not fatal; reconciliation repairs it.
5. Staged files of `done` items are deleted. A crash between commit and this step leaves files for the stray-staging sweep.

Crash windows: between rename and commit → orphan store files (orphan sweep); between commit and vector write → missing vector (reconciliation). FTS is kept current by triggers; there is no per-job rebuild.

### 5.4 Error classification

`classify_ingest_error(exc, stage)` in `backend/pipeline/error_classifier.py` returns `{reason, kind, stage, detail}`. `reason` is shown in the import report; `detail` is the raw exception text (stored in `error_detail` and logged).

Rules, checked in order:

| Exception / pattern | Reason | Kind |
|---|---|---|
| `SystemUnavailableError` | its message | `system` |
| `GridModelError` | Grid detection models are missing or damaged; reinstall Scene Atlas | `system` |
| "embedding service unavailable" | No AI model is available | `system` |
| `UnidentifiedImageError` / "cannot identify image file" | Image is corrupt or not a supported format | `file` |
| `DecompressionBombError` | Image is too large to process safely | `file` |
| "truncated" | Image file is incomplete or truncated | `file` |
| "could not read image" (OpenCV) | Image could not be read for processing | `file` |
| "cannot open video" / "cannot read first frame" | Video is corrupt or not a supported format | `file` |
| `OSError` with `ENOSPC` | Not enough disk space to process image | `system` |
| `FileNotFoundError` at stage `db_save` | The image library or thumbnail folder became unavailable | `system` |
| `FileNotFoundError` (other stages) | A working file went missing; will retry | `transient` |
| `PermissionError` | File could not be accessed (permission denied) | `file` |
| SQLite "locked" / "busy" | The database was busy; will retry | `transient` |
| `MemoryError` | Image is too large to process (out of memory) | `transient` |
| stage `embedding` | Failed to generate image embedding | `transient` |
| stage `db_save` | Failed to save image to database | `transient` |
| stage `vector_save` | Failed to save image embedding to search index | `transient` |
| anything else | Processing failed during {stage} | `transient` |

A missing file is never a property of the upload. `prepare_item` turns a missing staged file into `bytes_lost` (checked before decoding and again when a `FileNotFoundError` escapes). At commit the staged file isn't read; `_place` renaming out of `.incoming/` fails only when a store folder vanished (drive unplugged, folder deleted), so the batch is refunded and the queue pauses until the probe passes, instead of failing every item or asking for a needless re-upload.

Unknown errors are transient so a flaky failure recovers and a deterministic one costs at most three attempts. `record_failures` applies the kind: `file` → `failed`; `transient` → `ready` with backoff, or `failed` after 3 attempts; `system` → `ready` with the attempt refunded and the queue paused; `bytes_lost` → `awaiting_bytes`. API-side validation failures use stage `validate`; crash-limit failures use stage `processing`.

#### System pause

Held in worker memory and re-detected after a restart. `default_probe()` checks: embedding model available (`get_clip_unavailable_reason`), image library folder exists, and at least 512 MB free on the library, thumbnail-store and staging volumes. While paused, the worker re-probes every 30 s; `POST /imports/queue/probe` probes immediately, and the lifespan probes once the model has loaded.

### 5.5 Memory budget

`MemoryBudget` (`backend/app/services/memory_budget.py`) bounds the total estimated peak memory of concurrent prepare steps, independent of `max_concurrent_prepare`. Capacity is `ingest_memory_budget_mb` if set, else half of RAM beyond a 2 GiB reserve (minimum 1 GiB). An item larger than the whole budget runs alone rather than deadlocking. Estimates come from `plan_decode`: decoded pixels × bytes per pixel, progressive-JPEG coefficient buffers, and grid detection's per-format peak (`grid_detection_bytes`, measured on 2,400 real maps; only baseline JPEGs shrink when `grid_analysis_max_dim` is set). Progressive JPEGs and PNG/WebP still decode at full size (up to about 1.3 GB at 200+ Mpx); only a streaming decoder would fix that.

### 5.6 Auto image type

Rationale: [ADR-020](decisions.md#adr-020-auto-image-type-on-import). Heads: `backend/app/services/image_type_classifier.py`, trained and exported by scene-atlas-learning (`release heads`, `release export-heads`).

- **Which items:** only those whose type is `auto` (the job default or a manifest entry). Battlemaps and Scenes are never classified.
- **Seal:** Auto items are parsed and grouped as battlemaps (group names don't depend on type). The scene parse's tags are kept as `parsed.scene_tags`. `ingest_queue.effective_parsed` gives a scene its scene tags and no filename grid fields, both when an item is sorted and when an included item is claimed.
- **Prepare:** decode as usual, then compute the head's image features (`log_aspect`, `white_frac`, `white_border_frac`) from the **800 px** thumbnail, which is what the heads were trained on. Stop there.
- **Sort** (`sort_auto_items`, after the batch embedding): `active_head()` is the bundled head whose `encoder_sha256` matches the active model's vision encoder (recorded in `version.json` at download, hashed once for older installs). map → `battlemap`, illustration → `scene`. token, other, and anything below the head's `fallback.min_confidence` (which falls back to other) are sorted out. The verdict is stored in `classification` on every Auto item.
- **Sorted out:** the medium thumbnail moves to `staging/{job}/preview-<stem>.<ext>` (`preview_key`), the other temp files are deleted, and `record_sorted_out` marks the item `skipped` with `error_kind = sorted_out` and a reason: "Looks like a token", "Doesn't look like a map or a scene", or "Couldn't tell whether this is a map or a scene". Staged bytes are kept. Local imports keep only the preview; the source is still on disk. Videos are sorted from their first frame, like still images (there are video scenes as well as animated maps).
- **Retention:** a sorted-out item stays includable until the **earlier** of its import being cleared from Activity (dismissed, including by the report's Done) or **24 hours** after the import finished. Then it **expires**: its staged bytes and preview are deleted and `error_kind` becomes `sorted_out_expired`, so it is no longer includable or listed in the group editor (it stays in the report as a plain skip). Finished imports also leave Activity after 24 hours (`FINISHED_JOB_TTL`): `GET /imports` hides them at once, and hourly maintenance dismisses them and expires their items. A preview without its file is useless, so both go together.
- **Finish** (`finish_item`): grid detection for maps, then convert or copy the original, then commit as usual.
- **No head** for the active encoder, or a head whose `embedding_dim` doesn't match: Auto items import as battlemaps (warning logged once per encoder).
- **Include** (`include_sorted_out`, `POST /imports/include`): ids across imports. Only sorted-out items move; other ids are ignored. Each item gets a fixed type (whichever of map/illustration the head rated higher), so it isn't sorted again. Its preview is deleted after the commit, and it re-opens to `ready` (`awaiting_bytes` if the staged bytes are gone). Its job re-opens too, even if paused, cancelled or dismissed, because the user asked for these files. Expired items can't be included.
- **Counts:** job and group counts carry `sorted_out` (a subset of `skipped`; expired items aren't counted). The frontend treats an import with Auto skips as not a clean finish, so its report opens on Skipped: a folder skipped entirely has no gallery group for the editor to show it in.
- **Group editor:** `GET /imports/sorted-out/counts` (gallery group → count, via `import_groups.image_group_id`) and `GET /imports/sorted-out?image_group_id=` (items across imports), backed by `ix_import_groups_image_group` and `ix_import_items_group_state`. A group gets its gallery id at its first commit, so only groups with at least one imported image (or merged into an existing group) appear there.
- **Robustness:** a failure while sorting (a bad head, a database error) fails that batch's Auto items at stage `classify` with their temp files and previews cleaned up; it never leaves items `processing`. A malformed bundled head is skipped with an error logged; the others still load.
- **Review editor:** only finished groups are opened. The backend defines the rule once: `ImportJobDetail.reviewable_group_ids` are the gallery groups with an imported image from this job and no unfinished import group of this job adding to them; `groups_reviewable` counts them.

## 6. Duplicate detection

| Tier | Hash | Where | Catches | Action |
|---|---|---|---|---|
| Bytes | SHA-256 of the original (`content_hash`), plus `stored_hash` | Client (hint, `POST /hashes`), server on receipt, and at commit | Identical file, re-imported export | Auto-skip (`duplicate`, tier `bytes`) |
| Pixels | SHA-256 of canonical decoded pixels: EXIF orientation applied, RGBA, colour zeroed under fully transparent pixels, hashed in strips | Worker, at commit | Same image re-saved (PNG ↔ lossless WebP, metadata edits) | Auto-skip at commit (tier `pixels`) |
| Similar | 64-bit DCT pHash (`phash`) | Worker, from the 800 px thumbnail | Lossy re-encodes, resizes, gridded vs gridless | Stored only. No flags or UI yet. |

pHash never auto-skips: battlemap variants differ by thin grid lines or small props, which a pHash discards. Videos use the bytes tier only.

**Import as new copy** moves `duplicate` items back to `ready` (or `awaiting_bytes` when no bytes were ever sent) with `allow_duplicate`. The item is processed exactly like a new file and produces an independent image (own stored file, thumbnails, embedding). Staged bytes of `duplicate` items are kept for this; client-hash-skipped items never sent bytes, so they return to `awaiting_bytes` and the job shows as upload interrupted until the files are re-picked (or finished without).

## 7. Upload protocol

All routes are under `/api/v1/imports` (`backend/app/api/imports.py`). Mutating routes are `@write_locked` (`api/dependencies.py`): `BEGIN IMMEDIATE` is taken and released on the endpoint's own thread, so a request can't fail on a stale snapshot while the worker commits. (Taking it in a FastAPI dependency, which runs on a different thread-pool slot, starved the pool under ~50–100 concurrent writes: the holder couldn't get a slot and waiters failed after the 10 s busy timeout.) Seal and archive upload take the heavy-op semaphore before the write lock. Blocking work runs in `asyncio.to_thread`; bodies are streamed with async I/O.

| Route | Purpose |
|---|---|
| `POST /imports` | `{label, default_image_type}` → job summary (201) |
| `POST /imports/{id}/manifest` | Chunk of ≤2,000 `{client_ref, relative_path, size, last_modified, image_type?}`. OS junk (`._*`, `__MACOSX`, `.DS_Store`, `Thumbs.db`, `desktop.ini`) is ignored; unsupported files become `skipped`, oversized ones `failed`. Paths already in the job are ignored. 413 above `max_import_items` per import; 409 after seal. |
| `PUT /imports/{id}/archives?name=…` | Raw zip body, expanded into items (`ingest_archive.expand_archive`). `check_zip_safety` enforces `max_import_files` and `max_import_total_size` per archive; every member is magic-byte checked. A zip that fails becomes one failed `archive` item. Gated by the heavy-op semaphore. 409 after seal. |
| `POST /imports/{id}/local-sources` | Desktop app only (404 in server mode). `{paths}` (≤1,000 absolute roots): the server lists them and adds `ready` items with `source_path`; zips are expanded in place and kept. 422 for a bad path, 413 above `max_local_import_items` (250k). Listing runs before the write lock. See [local-ingest.md §4](local-ingest.md#4-backend). |
| `POST /imports/{id}/seal` | Parse and group paths, resolve groups against the gallery (`IN` queries chunked at 500), set `planned_at`, wake the worker. Checks free space on the staging and library volumes (507 if short, with a 512 MB margin). Idempotent. Gated by the heavy-op semaphore. |
| `POST /imports/{id}/hashes` | Chunk of ≤2,000 `{item_id, sha256}`. Items whose hash matches the library become `duplicate` without uploading. The client hash is only used to skip. |
| `PUT /imports/{id}/items/{item_id}/content` | Raw body streamed to `staging/{job_id}/.{staging_key}.part` with inline SHA-256, then magic-byte check (`verify_media_mime`) and a size check against the manifest ("File changed size after it was chosen"), rename to `staging/{job_id}/{staging_key}` (`staging_key` = uuid hex + extension) and `mark_bytes_received` (→ `ready` or `duplicate`). Size limit `max_import_file_size` (`max_video_file_size` for videos). Idempotent: an item already past `awaiting_bytes` drains the body and returns its state. |
| `GET /imports` | Job summaries for the dock (counts by state, group count, `upload_interrupted`) plus queue status. Weak `ETag` from the worker's version counter plus a minute bucket; `If-None-Match` → 304. |
| `GET /imports/{id}` | One job with per-group counts and resolution |
| `GET /imports/{id}/items` | Paginated (keyset on `id`, `after` / `next_after`), filter by `state`, `group_id`, `error_kind` |
| `POST /imports/{id}/pause`, `/resume`, `/cancel` | Job control |
| `POST /imports/{id}/groups/{group_id}/skip` | Skip one group's open items |
| `POST /imports/{id}/retry` | `{item_ids?}`, default all `failed` |
| `POST /imports/{id}/import-as-copy` | `{item_ids?}`, default all `duplicate` |
| `POST /imports/{id}/finish-upload` | `awaiting_bytes` → `skipped` ("Not uploaded") |
| `POST /imports/{id}/dismiss` | Hide a completed/cancelled job from the dock |
| `POST /imports/dismiss-finished` | Hide every completed/cancelled job (the dock's "Clear finished") |
| `DELETE /imports/{id}` | Undo import |
| `POST /imports/queue/probe` | Re-check system conditions now ("Retry now") |
| `GET /imports/sorted-out/counts` | `{counts: {gallery group id: n}}` of items Auto sorted out ([§5.6](#56-auto-image-type)) |
| `GET /imports/sorted-out?image_group_id=` | Items Auto sorted out of one gallery group, across imports (`limit` ≤ 1000, `truncated`) |
| `POST /imports/include` | `{item_ids}` (≤10,000, across imports): include items Auto sorted out; others are ignored. `{affected, job_ids}` |
| `GET /imports/{id}/items/{item_id}/preview` | The preview kept for a sorted-out item (404 if none) |

Security properties ([security.md](security.md)): `item_id` is always scoped to `job_id`; staged filenames are server-generated; `relative_path` never reaches the filesystem.

No `/imports` endpoint is rate limited, because an import makes one request per file (about 10k for a 10k-file import); a reverse proxy with its own rate limits must allow for that. Imports are bounded by the size and item limits, the seal-time free-space check and the heavy-op semaphore.

## 8. Frontend

Screens and components: [frontend.md](frontend.md#imports).

### 8.1 `ImportManager` and the client sequence

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
- **Desktop app**: `startLocalImport(paths)` replaces the whole sequence with create → `local-sources` → seal (phase `reading`, then `sealing`); no hashing, uploads or resume. The dialog takes paths from `electronAPI.getPathForFile` on dropped items and from the native pickers ([local-ingest.md §5](local-ingest.md#5-desktop-app-and-frontend)).
- One poller for `GET /imports`: 1 s while active, 5 s when the tab is hidden, 30 s idle; error backoff capped at 5 s drives a `degraded` / `lost` connection state.
- `beforeunload` guard while bytes are outstanding. Nothing is persisted locally: resume works from any tab by re-picking files, matched on `(relative_path, size)` against the job's `awaiting_bytes` items.

### 8.2 Views

`ImportDialog` (start view; progress with notices, group ledger, Pause/Resume/Cancel; and in the same frame once finished, the result: Groups, Problems, Already in library, Skipped; Retry, Import as new copies, Undo import, Review in editor, Done) and `ImportJobRow` in the activity dock (queue banner with "Retry now" when system-paused; Undo and Dismiss on finished rows; "Clear finished" in the header dismisses every finished import and background job). All are pure views over `ImportManager`; lists page through `GET /imports/{id}/items`.

## 9. Maintenance and recovery

| Task | When | Behaviour |
|---|---|---|
| `IngestWorker.recover()` | Startup, after the storage locks are taken (so no other backend is using the stores) | Deletes `.incoming/` in both stores; `recover_interrupted()` returns `processing` items to `ready`, or fails them at 3 attempts. Deletes no images. |
| `ingest_maintenance` (`run_ingest_maintenance`) | Scheduler, hourly | Finished jobs older than 24 h are dismissed and their sorted-out items expired ([§5.6](#56-auto-image-type)). `abandon_stale_uploads`: active/paused jobs with no bytes for 7 days → `awaiting_bytes` items `skipped` ("Not uploaded"). `release_staged_bytes`: staged files of `done`/`skipped` items always, except items Auto sorted out, which keep theirs until they expire (dismissal or 24 h after the job finished); of `failed`/`duplicate` items once the job is dismissed or finished more than 7 days ago. `prune_dismissed_jobs`: job/group/item rows of jobs dismissed over 30 days ago (images untouched). `sweep_stray_staging_files`: staging files and directories older than 1 h that no item's `staging_key` or `preview_key` refers to. |
| `reconcile_vectors` | Startup (once the model has loaded, via `JobRunner`, shown as "Updating image embeddings" with progress) and scheduler every 24 h | Compares SQLite and LanceDB id sets; re-embeds missing images from their thumbnails and deletes orphaned vectors. |
| `sweep_orphaned_store_files` | Scheduler, every 24 h | Deletes store files no image references. Only considers the `xx/yy/<key>` shard layout (so `.incoming/` and `backups/` are never touched), ignores files younger than 1 h, and deletes nothing if more than 25% of the store looks orphaned. |
| `backup_database` | Scheduler, every 24 h | SQLite + LanceDB snapshot with rotation |

Scheduled tasks are registered in `backend/app/main.py`. The scheduler (`backend/app/services/scheduler.py`) persists each task's last run under `{APP_DATA_DIR}/scheduler/` and runs overdue tasks shortly after startup, so short Electron sessions still get maintenance.

Staging is never cleaned by file age alone, and active imports are never expired.

### Recovery and crash supervision

- **Backend crash or kill mid-import**: on restart, `recover()` re-queues in-flight items (one attempt used). An item that crashes the process three times fails instead of crash-looping. Uploads interrupted mid-stream leave `.part` files for the stray-staging sweep; the item stays `awaiting_bytes` and the client resumes it.
- **Supervisors**: `scripts/app/start.py` (development and server mode) runs the backend and frontend as child processes and restarts a crashed child with exponential backoff, giving up after 10 crashes in 5 minutes. `backend/pyinstaller/entry.py` (Electron sidecar) restarts uvicorn in-process with the same limit; module-level state survives such a restart.

## 10. Stored format

By default the library stores each file exactly as uploaded. Three settings change that for **new** imports; existing images are never rewritten.

| Setting | Values | Default |
|---|---|---|
| `stored_format` | `original` \| `webp` \| `jpeg` \| `png` | `original` |
| `stored_quality` | 1–100, for lossy WebP and JPEG | 90 |
| `stored_lossless` | Lossless WebP for lossless sources | true |

`stored_format.convert` runs in prepare, after grid detection, and writes into the library's `.incoming/`; it never touches the staged upload. A file is stored unchanged when it is already in the target format, is animated, has transparency with a JPEG target, or exceeds 16,383 px on either side with a WebP target.

- JPEG sources never become lossless WebP (about 3.1× larger and ~11 s CPU for a 20 Mpx map); they use `stored_quality`.
- WebP is written with `exact=True`, so colour under transparent pixels survives. The ICC profile is carried over.
- `content_hash` and `pixel_hash` always come from the upload; `stored_hash` and `file_size` describe the stored file. Dedup checks both byte hashes, so re-importing the original of a converted image is still caught.
- Downloads take their extension from `storage_key` (`backend/pipeline/naming.py`, `ImageViewer.buildDownloadFilename`), so a converted map downloads as `.webp`.
- The Electron setup wizard's "Convert to WebP" choice is saved as `stored_format = "webp"` through `PATCH /settings/` once the backend is up ([electron.md](electron.md)). Server mode can seed it at first boot with `CONVERT_TO_WEBP=1`.

## 11. Testing

Integration tests (`test_ingest_pipeline.py`, `test_imports_api.py`) drive the worker with `drain()` against real SQLite, LanceDB (`lancedb_service` fixture) and stores in `tmp_path`, faking only the embedding model; the `test_client` fixture swaps the image and thumbnail stores for temp directories and doesn't start the worker. E2E (`e2e/`) seeds through the real import protocol against a backend whose data lives in `e2e/.tmp-data`. The stress suite (`stress_tests/`, [stress-testing.md](../docs/development/stress-testing.md)) runs a live server and checks rows = stored files = vectors with no `.incoming` leftovers. Test strategy overall: [testing.md](testing.md).

## 12. Settings

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
| `max_concurrent_prepare` | `min(cpu, 4, RAM-based cap)` (`resource_detector.py`) | Prepare pool size (fixed at startup) |
| `max_concurrent_heavy_requests` | `min(cpu // 2, 6)` | Heavy-op semaphore (archive upload, seal) |
| `max_import_file_size` | 2 GB | Per file, and per uploaded archive body |
| `max_video_file_size` | 2 GB | Per video file |
| `max_import_files` | 1,000 | Entries per uploaded zip |
| `max_import_total_size` | 2 GB | Uncompressed size per uploaded zip |
| `enable_image_grid_detection` | true | Image-analysis grid detection for battlemaps |
| `grid_analysis_max_dim` | 0 (full resolution) | Longest side analysed by grid detection; lowering it misses thin lines on high-dpi maps |
| `num_dominant_colors`, `color_clustering_samples`, `color_kmeans_n_init` | 5, 5000, 3 | Colour extraction |
| `stored_format`, `stored_quality`, `stored_lossless` | `original` (`webp` if chosen in the desktop setup wizard, or `CONVERT_TO_WEBP=1` at first boot in server mode), 90, true | See [§10](#10-stored-format) |

## 13. Implementation notes

- **Pillow plugins load at startup** (`PILImage.init()` in the lifespan). Otherwise Pillow dlopens plugins on its first unidentifiable file; when that happened while prepare threads were inside threadpoolctl's `dl_iterate_phdr` (sklearn KMeans in colour extraction), the process deadlocked on the loader lock and the GIL. The stress suite found it with corrupt uploads.
- **Library purge refuses** while any import has open items.
- **Gallery refresh**: the gallery picks up images as they land without moving what's on screen (see [import-progress.md §6](import-progress.md#6-gallery-while-importing)); every finished import gets a toast with "View report" unless its dialog is open.

## 14. Open questions

- **Possible-duplicate (pHash) flags** are not built. pHash puts gridded/gridless pairs 0–2 bits apart and unrelated images at ≥20 bits, so flags must be suppressed within an import group and between sibling grid/no-grid folders, or about 9k images in the real library would flag. The report would need grouping by existing image and bulk actions.
- **Progress moves in batch-sized steps** (up to 16 items commit together).
- **Library purge deletes `backups/`**, because backups live inside the image library folder.
- **Shared-storage "add to group"** (put the existing image into the new group instead of importing a copy) needs many-to-many group membership; deferred.
- **Linked library and drop folder**: local folder import is built ([local-ingest.md](local-ingest.md)); linked folders read in place and a drop folder are planned there.
- **Pixel-hash determinism** across Pillow/libjpeg-turbo upgrades: the failure mode is a missed duplicate, never a false skip.

## 15. Logging and CLI

`backend/app/logging_config.py` `setup_logging(data_dir, debug)` is called once per entry point (`backend/app/main.py`, `backend/pyinstaller/entry.py`). Handlers: stdout and a `RotatingFileHandler` at `{APP_DATA_DIR}/logs/scene-atlas.log` (10 MB, 5 backups). Format `%(asctime)s %(levelname)-8s [%(name)s] %(message)s`. `debug` sets `DEBUG`, otherwise `INFO`. Modules use `logging.getLogger(__name__)`.

### CLI entry points

Run with `uv run python -m <module>`:

- `backend.pipeline.backfill_content_hash`: compute missing `content_hash` values
- `backend.pipeline.backfill_grid_detection`: run grid detection over existing battlemaps
- `backend.pipeline.reparse_names`: re-run the name parser over existing images
- `backend.pipeline.retag_all_images`: regenerate auto tags from filenames (manual tags kept)
- `backend.pipeline.fix_orphaned_images`: put images without a group into an "Uncategorised" group
- `backend.pipeline.export_library`: copy the library into an `Author/Group/` folder tree with `metadata.json`

There is no CLI for bulk import of a local folder; imports go through the API.
