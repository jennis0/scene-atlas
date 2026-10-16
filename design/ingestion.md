# Ingestion Pipeline

**Status:** Shipped (ADR-018, merged in PR #1; storage format in Phase 5). See [ADR-018](decisions.md#adr-018-durable-per-item-ingest-pipeline).

**Scope:** the web/Electron upload path, from file selection through processing to the import report. Bulk import of an existing local library (linked folders, rescans) is **not built yet**. The model deliberately leaves room for it: a folder becomes another way of supplying bytes to the same item queue (§14).

The pipeline replaced an earlier job-and-confirm design in October 2026. Scene Atlas was unreleased, so there was no data migration; the old import tables, statuses and endpoints were removed outright. §1 records why, and §13 maps the audit findings to the design.

**Code map:**

| Area | Where |
|---|---|
| State machines | `backend/app/services/ingest_state.py` |
| Durable queue operations | `backend/pipeline/ingest_queue.py` |
| Batch processing (prepare, embed, commit, vectors) | `backend/pipeline/ingest_process.py` |
| Worker loop, pause, recovery | `backend/pipeline/ingest_worker.py` |
| Hashes (SHA-256, pixel hash, pHash) | `backend/pipeline/image_hashes.py` |
| Storage-format conversion | `backend/pipeline/stored_format.py` |
| Zip expansion | `backend/pipeline/ingest_archive.py` |
| Maintenance | `backend/pipeline/ingest_maintenance.py`, `backend/pipeline/maintenance.py`, `backend/pipeline/vector_reconcile.py` |
| HTTP API | `backend/app/api/imports.py`, `backend/app/models/import_schemas.py` |
| Frontend store | `frontend/src/lib/import/` (`ImportManager.ts`, `importClient.ts`, `hash.worker.ts`, `useImports.ts`) |
| Frontend views | `frontend/src/components/imports/` |
| Migrations | `020_ingest_items.py`, `021_drop_legacy_import_tables.py` |

---

## 1. Why

A reliability audit (2026-10-12) found about 50 issues in the import flow. Almost all of them come from three structural causes.

1. **The job was treated as an all-or-nothing transaction.** A restart (`mark_interrupted_jobs`), any failed group (`_finalize_import_job`), or dismissing a failed job deleted *every* image the job had imported. This existed to avoid false duplicate matches on re-upload.
2. **No durable per-file state.** The confirmed file list lived only in `JobRunner` kwargs in memory. Nothing recorded which files were done, so nothing could resume. Cancel couldn't stop the worker. Maintenance timers (48 h `updated_at` expiry, 24 h staging mtime) could delete a long import part-way through, and a stuck job was only detected on restart.
3. **The browser drove the lifecycle.** Hashing, the upload loop and auto-confirm ran in React effects. A tab close, remount or race stranded the job (`uploading`/`staging` forever). One effect caused a `/imports/active` request loop during every import.

Other problems:
- Duplicate detection never worked with WebP conversion on, because the stored hash was of the WebP output.
- More than 32k files hit SQLite's bound-variable limit.
- Per-batch work grew O(n²) (`.file_map.json`, staging re-stat, `file_errors` JSON).
- There were three uncoordinated pollers.

The fix is a model change, not a list of patches.

## 2. Principles

- **The file is the unit of work and of commit.** Once a file is committed it is permanent. Other files failing never undoes it.
- **Jobs aggregate; they don't decide.** A job is what the user started and sees ("Forest Pack.zip"). Its progress is derived from its items.
- **The backend owns the lifecycle.** The client describes files and supplies bytes; everything else happens server-side. Closing the tab can interrupt an upload but can never strand processing.
- **Nothing destructive happens implicitly.** Cancel stops work and keeps what's finished. Deleting imported images is only ever an explicit, confirmed "Undo import".
- **Distinguish file problems from system problems.** A bad file fails that file. A full disk or a missing AI model pauses the queue with a reason. Nothing fails because the machine was in a bad state.
- **Every automatic duplicate rule must have zero false positives.** Near-duplicates (gridded vs gridless, prop and lighting variants) are the content this app exists to group.

---

## 3. Data model

```
import_jobs 1───* import_groups 1───* import_items *───1 images
                                             (image_id / duplicate_of_image_id)
```

### `import_jobs`

| Column | Notes |
|---|---|
| `id` TEXT PK | uuid hex |
| `source_label` | Display label, e.g. "Forest Pack.zip" or "3 folders" (`label` in the API) |
| `status` | `active` \| `paused` \| `completed` \| `cancelled` (see §4.2) |
| `default_image_type` | `battlemap` \| `scene` |
| `planned_at` | Set when the manifest is sealed and groups are planned. Items are claimable only after this. |
| `last_upload_at` | Last byte receipt. Drives the "upload interrupted" display and abandonment. |
| `dismissed_at` | Hidden from the activity dock. Never deletes anything. |
| `created_at`, `updated_at`, `completed_at` | |

Removed from the earlier design: `analysis_result`, `job_warnings`, `error_message`, `total_files`, `total_file_size`, and the whole `import_group_jobs` table.

### `import_groups`

The groups worked out from the paths at seal time.

| Column | Notes |
|---|---|
| `id` PK, `job_id` FK (cascade) | |
| `author`, `group_name` | Parser output |
| `image_group_id` | The gallery group this resolves to: an existing one (merge) or one created on first commit |
| `merged_into_existing` | True if an `ImageGroup` with the same `(base_name, author)` already existed at plan time. Surfaced in the report ("Merged into existing group X"). |
| `sort_order` | Processing order within the job |

### `import_items`

One row per file. **All durable ingest state lives here.**

| Column | Notes |
|---|---|
| `id` INTEGER PK | |
| `job_id`, `import_group_id` | `import_group_id` is NULL until planned |
| `kind` | `image` \| `video` \| `archive` (a zip that failed to expand is recorded as a failed `archive` item) |
| `relative_path`, `filename` | Display and resume matching. **Never used as a filesystem path.** UNIQUE `(job_id, relative_path)` |
| `size`, `last_modified` | From the client manifest; `size` is verified on receipt |
| `image_type` | `battlemap` \| `scene` |
| `parsed` JSON | Parser output: name, subgroup, tags, filename grid info |
| `state` | See §4.1 |
| `staging_key` | Server-generated name of the staged bytes; NULL until received |
| `source_hash` | SHA-256 of the original bytes. Client-supplied hint before upload; server-computed (authoritative) on receipt |
| `attempts`, `retry_after` | Claim counter (poison detection) and backoff for transient errors |
| `error_kind`, `error_stage`, `error_reason`, `error_detail` | `error_kind` ∈ `file` \| `transient` \| `system` \| `bytes_lost`. `error_reason` is user-facing; `error_detail` is the raw exception. |
| `image_id` | Set when `done` |
| `duplicate_of_image_id`, `duplicate_tier` | Set when `duplicate` (`bytes` \| `pixels`) |
| `allow_duplicate` | Set by "Import as new copy". Skips the dedup check at commit. |
| `similar_to_image_id`, `similarity_distance` | Perceptual-hash flag (advisory only, §6). Columns exist; nothing sets them yet. |
| `created_at`, `updated_at` | |

Indexes:
- `(state, job_id)`, for claiming
- `(job_id, state)`, for counts
- `(job_id, import_group_id)`

### `images` changes

| Column | Notes |
|---|---|
| `content_hash` | SHA-256 of the **original** uploaded bytes (the item's `source_hash`), never of converted output. Indexed. Not unique (see "Import as new copy"). |
| `stored_hash` | SHA-256 of the stored file. Equal to `content_hash` when no conversion happened (§10). Lets re-imports of exported files match. Indexed. |
| `pixel_hash` | Hash of the canonical decoded pixels (§6). Indexed. NULL for video. |
| `phash` | 64-bit perceptual hash (§6). NULL for video. |

`import_job_id` stays, for provenance and Undo.

---

## 4. State machines

### 4.1 Item states

```
                 ┌───── import as new copy ──────┐
                 ▼                               │
awaiting_bytes ─bytes received─▶ ready ─claim─▶ processing ─commit─▶ done
   │   │                          ▲  ▲              │ │
   │   └─client hash = existing ──┼──┼──────────────┼─┴─dedup at commit─▶ duplicate
   │                              │  └─transient err (retry_after)
   │                              └── retry ─────── failed ◀── file error / 3rd crash
   └─ finish-without / cancel / abandoned ─▶ skipped        ▲
                                    (cancel also: ready ─▶ skipped)
```

| From | Event | To | Actor |
|---|---|---|---|
| — | manifest entry valid | `awaiting_bytes` | API |
| — | manifest entry invalid (type, size) | `failed` (`file`, stage `validate`) | API |
| — | zip member extracted | `ready` | API (archive expansion) |
| `awaiting_bytes` | client hash matches an existing image | `duplicate` (`bytes`) | API |
| `awaiting_bytes` | bytes received and valid | `ready` | API |
| `awaiting_bytes` | bytes received, invalid or hash duplicate | `failed` / `duplicate` | API |
| `ready` | claimed by worker (`attempts += 1`) | `processing` | Worker |
| `processing` | committed | `done` | Worker |
| `processing` | source or pixel hash matches at commit | `duplicate` | Worker |
| `processing` | file error | `failed` | Worker |
| `processing` | transient error, `attempts < 3` | `ready` with `retry_after` | Worker |
| `processing` | system error | `ready` (attempt refunded); queue pauses | Worker |
| `processing` | startup recovery, `attempts < 3` | `ready` | Recovery |
| `processing` | startup recovery, `attempts >= 3` | `failed` ("Repeatedly crashed during processing") | Recovery |
| `failed` | retry, staged bytes present | `ready` | API |
| `failed` | retry, staged bytes gone | `awaiting_bytes` | API |
| `duplicate` | import as new copy, staged bytes present | `ready` + `allow_duplicate` | API |
| `duplicate` | import as new copy, no staged bytes (skipped via client hash) | `awaiting_bytes` + `allow_duplicate` | API |
| `awaiting_bytes`/`ready` | cancel, finish-without, abandoned | `skipped` | API / maintenance |

Terminal: `done`, `duplicate`, `failed`, `skipped`. `failed` and `duplicate` can be re-opened by explicit user action.

The transition rules live in one pure module (`backend/app/services/ingest_state.py`), so they are unit-testable without a database.

### 4.2 Job states

Four states:
- **`active`:** the worker may claim its items.
- **`paused`:** user paused; the worker skips this job.
- **`completed`:** no items in `awaiting_bytes`, `ready` or `processing`.
- **`cancelled`:** the user cancelled. Unfinished items become `skipped` and finished work is kept.

`recompute_job_status(job_id)` is the only writer of `active` ↔ `completed`. It is called after every batch commit, byte receipt, retry, import-as-copy and finish-without. A retry on a `completed` job re-opens it to `active`.

**A job never "fails".** Outcomes are counts ("Completed · 412 imported · 3 failed · 12 duplicates").

Derived display states (computed in the API, never stored):
- **Upload interrupted:** `active`, `awaiting_bytes > 0`, nothing `ready` or `processing`, and `last_upload_at` older than 2 minutes. The UI offers "Choose files to resume" or "Finish without them".
- **Waiting on system:** the queue is system-paused (§5.4).

**Undo import** deletes every image the job created. It then deletes the job and its groups and items. The job disappears; there is no "undone" state.

---

## 5. Processing: the ingest worker

Imports no longer go through `JobRunner`, which stays for maintenance, backfills and rebuilds. A dedicated **`IngestWorker`** service starts and stops with the FastAPI lifespan. It runs a single loop thread, using the existing global prepare pool for per-image parallelism.

### 5.1 Loop

```
recover()                               # startup: processing → ready/failed, clear .incoming temp files
while not shutting_down:
    if system_paused: wait for probe/resume; continue
    batch = claim_next_batch()          # round-robin across jobs
    if not batch: wait(event, timeout=30s); continue
    prepared = prepare(batch)           # prepare pool: decode, thumbnails, colours, grid, hashes, temp copies
    embeddings = clip_batch(prepared)
    commit(prepared, embeddings)        # one SQLite write transaction
    write_vectors(committed)            # LanceDB, after commit
    recompute_job_status(...); bump progress version
```

- The loop is woken by an in-process `threading.Event`, set on byte receipt, seal, resume and retry.
- Tests drive it synchronously with `worker.drain()`, with no thread.

### 5.2 Claiming and scheduling

- **Round-robin across jobs.** The worker keeps a cursor (the last job served) and takes the next `active`, planned job with claimable items, ordered by `created_at`. A 5-file drop is never stuck behind a 10k import.
- **Within a job, items are claimed in `(import_groups.sort_order, id)` order**, so groups complete together.
- Claimable means `state = 'ready'` and (`retry_after IS NULL OR retry_after <= now`).
- A claim is one `UPDATE … SET state='processing', attempts=attempts+1 … RETURNING`, batch size `ingestion_batch_size` (default 16).
- **Single-process assumption.** The backend runs one process (as `JobRunner` already assumes), so items need no leases: at startup every `processing` item is orphaned by definition. If multiple backend processes are ever introduced, add `lease_expires_at` and a sweeper.

### 5.3 Commit protocol

The goal is that a file is either fully in the library or not at all, and that crashes can't leave visible half-states.

1. **Prepare** (no DB writes):
   - Decode once. Generate thumbnails, colours, grid detection, `pixel_hash` and `phash` from that decode.
   - Copy the original (or the converted output) to a temp file **on the library volume** (`{IMAGE_LIBRARY_DIR}/.incoming/`). Write thumbnails to `{APP_DATA_DIR}/.incoming/`.
   - Temp files sit on the same volume as their destination, so the final placement is an atomic rename even when the app-data and library dirs are different drives.
   - **Why the temp copy goes to the slow library drive:**
     - All working reads (decode, hashing) come from staging on the fast app-data drive.
     - The only library-drive I/O is the one unavoidable write of each original, which happens once wherever the temp file lives.
     - Doing that write during prepare keeps it parallel with CPU work and outside the SQLite write lock.
     - The alternatives are worse. Copying from the fast drive at commit would hold the write lock for seconds per batch on an HDD. Copying after commit would make rows visible before their files exist, and a crash would leave rows without files.
   - **Throughput (Phase 0, §12):** ingest is CPU-bound, at about 5 images/s on 4 cores and about 10 on 8 with the small model (3.3 and 6.7 with the medium model). That needs 23–45 MB/s of library writes, well within HDD sequential speed.
     - Concurrent writes from the prepare pool could cause seek thrash on an HDD. Disk behaviour was not measured; if it shows up, the mitigation is a single library-writer thread that serialises the temp writes into one sequential stream.
2. **Embed:** batch the embeddings.
3. **Commit** in one `BEGIN IMMEDIATE` transaction. SQLite's single writer makes check-then-insert race-free without a unique index.
   - Dedup check against `source_hash`, `stored_hash` and `pixel_hash` (skipped when `allow_duplicate`). Duplicates become `duplicate` and their temp files are discarded.
   - Rename the temp files into place.
   - Insert the images, tags and colours. Resolve or create the `ImageGroup` and record it on `import_groups.image_group_id`. Mark the items `done` with `image_id`.
   - If the commit fails, delete the renamed files, then classify the error (usually transient).
4. **Vectors:** `merge_insert` into LanceDB after the commit. A failure is logged, not fatal.
   - **Reconciliation** runs at startup, after each job completes, and on schedule. It compares image ids between SQLite and LanceDB (id sets, not counts) and re-embeds the missing ones from the stored file. This replaced a count-based auto-rebuild, which could drop the whole table.

Crash windows:
- Between rename and commit: orphan files remain. The orphan sweep handles them (fixed to compare keys correctly).
- Between commit and vector write: the image is missing a vector. Reconciliation handles it.

The full-library FTS rebuild after each job is removed; the INSERT/UPDATE/DELETE triggers already maintain FTS.

### 5.4 Error classification

`error_classifier.classify_ingest_error` gains a `kind`:

| Kind | Examples | Handling |
|---|---|---|
| `file` | `UnidentifiedImageError`, `DecompressionBombError`, cv2 read failure, truncated file, size mismatch with manifest | Item → `failed`. Retry is allowed but labelled as unlikely to help. |
| `transient` | SQLite `database is locked`/busy, `MemoryError`, ONNX runtime error, LanceDB transient error | Item → `ready` with exponential `retry_after`, up to 3 attempts, then `failed`. (`MemoryError` is rare now that prepare reserves from the memory budget, §12.) |
| `system` | `ENOSPC`, image library root unavailable, embedding model not loaded, model switch or embedding rebuild in progress | The batch's items go back to `ready` with the attempt refunded. **The queue is system-paused** with a user-facing reason. |

System pause:
- It is worker state, held in memory and re-detected after a restart.
- It is exposed in the `GET /imports` response.
- The worker re-probes the condition every 30 s (free space above the threshold, model ready, library path reachable), and the user can force a probe with "Retry now".
- A model switch doesn't refuse or cancel imports. It system-pauses ingest for its duration ("Paused while the AI model changes") and the pause clears when it finishes.

### 5.5 Cancel and pause

- Pause and cancel are job-status writes. The worker checks status at claim time, so a batch already in progress (at most `ingestion_batch_size` items) finishes and is kept.
- Cancel marks every `awaiting_bytes`/`ready` item of the job `skipped` in one statement.
- Group-level "Skip this group" does the same for one `import_group`.

---

## 6. Duplicate detection

Three tiers. Only tiers that can't produce a false positive act automatically.

| Tier | Hash | Computed | Catches | Action |
|---|---|---|---|---|
| 1. Bytes | SHA-256 of the original bytes (`source_hash`), plus `stored_hash` | Client (hint, before upload) and server (authoritative, while streaming to staging) | The identical file, or a re-imported export | **Auto-skip.** If the client hash matches, bytes are never sent. |
| 2. Pixels | SHA-256 of the canonical decoded pixels: EXIF orientation applied, converted to RGBA, colour zeroed under fully transparent pixels, metadata ignored. Hashed in strips to bound memory. | Worker, from the decode it already does | The same image re-saved: PNG ↔ lossless WebP, different compression, edited metadata | **Auto-skip at commit** |
| 3. Perceptual | 64-bit DCT pHash (or dHash) via OpenCV/numpy (no new dependency) | Worker, from the thumbnail-sized decode | Lossy re-encodes, resized copies, VTT-compressed vs full-res, gridded vs gridless | **Never skip.** Stored on every image as `phash`. Flagging ("Possible duplicate of X", with Keep both / Remove this one) is deferred (§12). |

Rationale for not auto-skipping on pHash: battlemap variants differ by thin grid lines or small props, which a pHash discards, so even a strict threshold would drop exactly the variants groups exist to hold.

Rationale for not using a post-conversion hash as the key:
- It depends on the encoder settings and version.
- Lossy output has no byte relationship to its source.
- It can't be computed client-side.

**Import as new copy** (per item, or "all duplicates in this job"): `duplicate` → `ready` (or `awaiting_bytes`) with `allow_duplicate`.
- The item is processed **exactly like a new file**: its own stored file, thumbnails, colours, grid detection and embedding, and an independent `Image` record. Nothing is shared with the image it matched.
- This is deliberate. The action is the escape hatch for a faulty duplicate match, so it must not inherit anything from the matched image.
- **Bytes are needed:**
  - Staged bytes of `duplicate` items are kept, like those of `failed` items (§9).
  - Items skipped via the client hash never sent bytes, so they go to `awaiting_bytes`. If this tab still holds the `File`, the manager uploads it automatically; otherwise the job shows "Choose files to resume".
- **There is no storage reuse:** the earlier `reuse_storage_key` path was removed, so every imported image owns its stored file. (`deletion_service.safe_delete_image` still checks for other references to a storage key before deleting the file, as a safeguard.) Shared-storage records are a pending open question (§14).

Within one job, two identical files are handled by the commit-time check: the second becomes `duplicate` of the first.

Videos use tier 1 only.

Perceptual flags and their bulk UI are deferred (§12); the hashes are already computed and stored.

---

## 7. Upload protocol

All endpoints live under `/api/v1/imports`. Request bodies never carry per-file lists beyond the manifest chunk, and responses never include per-file lists except the paginated items endpoint.

| Endpoint | Purpose |
|---|---|
| `POST /imports` | `{label, default_image_type}` → `{job_id}` |
| `POST /imports/{id}/manifest` | Chunk of ≤2,000 `{client_ref, relative_path, size, last_modified, image_type?}` → `[{client_ref, item_id, state, error?}]`. Validates type and size. Invalid entries become `failed` items, so they appear in the report rather than vanishing. 409 after seal. |
| `PUT /imports/{id}/archives?name=…` | Raw zip body. Expanded server-side into `ready` items. The existing guards stay: entry count, total uncompressed size, `__MACOSX`, magic bytes for **every member**. A zip that fails to expand becomes one `failed` `archive` item. 409 after seal. |
| `POST /imports/{id}/seal` | Parse, group and resolve groups (one `IN` query per ≤500 names, never a single unbounded `IN`). Sets `planned_at`. Checks free space on the staging and library volumes against the estimated need, and rejects with a clear message if short. Returns the group plan. |
| `POST /imports/{id}/hashes` | `[{item_id, sha256}]` → `[{item_id, state, duplicate_of?}]`. The client sends hashes ahead of uploading. Matches go `awaiting_bytes` → `duplicate` without sending bytes. The client hash is only ever used to skip; uploaded bytes are always re-hashed server-side. |
| `PUT /imports/{id}/items/{item_id}/content` | Raw body (not multipart), streamed to `staging/{job}/{uuid}.tmp` with SHA-256 computed inline. Then a magic-byte check, a size check against the manifest, an atomic rename, and the item goes to `ready` (or `duplicate`/`failed`). **Idempotent:** re-sending replaces the staged copy, and sending to an item past `ready` is drained and returns 200 no-op. |
| `GET /imports` | Job summaries for the dock: counts by state, group count, derived flags (`upload_interrupted`), timestamps. Plus `queue: {system_paused, reason, active_job_id}`. Supports `ETag`/`If-None-Match` (304) using an in-memory progress version, so idle polls are close to free. |
| `GET /imports/{id}` | One job: summary plus per-group counts and resolution (`merged_into_existing`). |
| `GET /imports/{id}/items` | Paginated, filterable by `state`, `group`, `error_kind`. Keyset pagination on `id`. |
| `POST /imports/{id}/pause`, `/resume`, `/cancel` | Job control |
| `POST /imports/{id}/groups/{gid}/skip` | Skip one group's remaining items |
| `POST /imports/{id}/retry` | `{item_ids?}` (default: all `failed`) |
| `POST /imports/{id}/import-as-copy` | `{item_ids?}` (default: all `duplicate`) |
| `POST /imports/{id}/finish-upload` | `awaiting_bytes` → `skipped` ("Not uploaded") |
| `POST /imports/{id}/dismiss` | Hide from the dock |
| `DELETE /imports/{id}` | **Undo import.** Deletes the job's created images, then the job. |
| `POST /imports/queue/probe` | "Retry now" for a system pause |

Notes:
- **Async endpoints must not block the event loop.** Streaming uses async I/O; parsing, zip expansion and DB work go through `asyncio.to_thread`. (The earlier endpoints blocked it.)
- **Limits:**
  - `max_import_file_size` and `max_video_file_size` cap single files.
  - An import holds at most `settings.max_import_items` files (default 50,000), enforced across all manifest chunks, and seal checks free space.
  - `max_import_files` and `max_import_total_size` now only guard zip expansion (entry count and uncompressed size).
- **Rate limiting:** no `/imports` endpoint is rate-limited, because uploads make one request per file. They are bounded by the size and item limits, the seal-time free-space check and the `acquire_heavy_op` semaphore on seal and archives (see [security.md](security.md)).
- **Security:**
  - `item_id` is always scoped to `job_id`, and staging names are server-generated.
  - `relative_path` never reaches the filesystem, preserving the guarantees in [security.md](security.md).

### Client sequence

```
create job → manifest chunks → (archives) → seal ──▶ show group plan
                                              │
             hash worker ──hashes batch──▶ POST /hashes ──▶ skip dups
                  │                                            │
                  └─ runs ahead of ─▶ upload pool (3–4 PUTs) ◀─┘
                                       │ per-file retry with backoff
                                       ▼
                     worker processes items as they become ready
```

Processing overlaps the upload; nothing waits for "upload complete".

---

## 8. Frontend

### 8.1 `ImportManager` (single owner)

`frontend/src/lib/import/ImportManager.ts` is a module-level store, outside the React tree, read through `useSyncExternalStore` hooks (`useImports()`, `useImportJob(id)`). It owns:

- **Local uploads** for jobs started in this tab: `File` handles, upload queue, byte progress, per-file retry state.
- **Hash worker** (`hash.worker.ts`). SHA-256 in a Web Worker, running a bounded distance ahead of the uploader.
  - `crypto.subtle` exists only in secure contexts. On a plain-HTTP LAN origin, client hashing is skipped and dedup happens server-side after upload. Files over 256 MB are not client-hashed either, because `subtle.digest` needs the whole buffer.
- **Upload pool:** 3–4 concurrent `PUT`s.
  - A per-file failure retries with backoff (5 attempts), then marks the file locally "upload failed" (still `awaiting_bytes` server-side, so it can be retried or resumed) and **continues with the rest**.
  - If the network is down, the uploader pauses and keeps retrying with capped backoff while the tab is open ("Waiting for connection…"). Network loss never fails an import.
- **One poller** for `GET /imports` with `ETag`.
  - About 1 s while any job is active and the tab is visible, 5 s when hidden, 30 s when idle.
  - Exponential backoff on errors, which drives a `connection: ok | degraded | lost` state.
- **`beforeunload` guard** while any local upload has outstanding bytes.
- **Persistence: none.** The server reports `upload_interrupted`, and any browser can resume by re-picking the files (matched by path and size), so nothing needs to be stored locally. (The original plan kept job ids in localStorage; it turned out to be unnecessary.)

Dialogs and the dock are pure views over the manager, so remounting a dialog cannot orphan an upload or start a request loop.

### 8.2 Views

- **ImportDialog**
  1. Pick files, a folder or a zip (drag-drop or browse), plus the battlemap/scene toggle.
  2. Show progressive folder traversal feedback ("Found 3,214 files…").
  3. Start: create, manifest, seal.
  4. Show the group plan with live per-group progress. This is information, not a review gate: processing starts immediately.

  The dialog can be closed at any point and reopened from the dock.
- **ActivityDock:** one row per non-dismissed job.
  - Example: "Forest Pack · uploading 120/400 · imported 80 · 2 failed".
  - Pause, cancel and open controls.
  - A queue-level banner when system-paused, with "Retry now".
  - "Upload interrupted" rows offer "Choose files to resume" or "Finish without them".
- **ImportReport** (replaces `ImportSummaryDialog` and `ImportDonePane`). Sections: Groups (status, merged-into-existing), Problems (failed grouped by `error_reason`, retry per reason or per item), Duplicates (linked to the existing image; "Import as new copy"), Skipped. Possible-duplicate (pHash) flags are deferred (§12). Actions: Retry failed, Undo import (confirm with counts), Dismiss. All lists are virtualised and paginated from `GET /imports/{id}/items`.
- **Notifications:** a toast on every job completion, including "Completed with 3 failures" and a system pause, with a link to the report.
- **EditGroupDialog live review** reads group progress from the manager instead of running its own poller.
- **Resume:** the user re-picks files or a folder. The manager fetches the job's `awaiting_bytes` items and matches on `(relative_path, size)`. Only missing files are hashed and uploaded.

### 8.3 Removed

- **Hooks:** `useImportState`, `useImportUpload`, `useImportPolling`, `useImportPersistence`, `useImportProgressPolling`, `useActiveImports`.
- **Libraries:** `importStorage` (replaced by a job-id list) and `hashFile` (moves into the worker).
- **Components:** `ImportSummaryDialog`, `ImportDonePane`, and the dead `ImportFileCard`/`ImportFileToolbar`.
- **Electron:** the `fsEntryTraversal` Electron fallback and its `fs:read-directory`/`fs:read-file-bytes` IPC. They have been dead since `File.path` was removed in Electron 32, and they have no path restriction.

`components/import/{FileCard,FileToolbar,MetadataForm,TagPicker,GridToggle,GridSizeInput,shared}` stay; `EditGroupDialog` and `ImageViewer` use them.

---

## 9. Maintenance

| Task | When | Behaviour |
|---|---|---|
| `recover_ingest` | Startup (before ready) | `processing` → `ready`, or `failed` at 3 attempts. Delete `.incoming/` temp files. No image deletion. Fast: two UPDATE statements. |
| Staging cleanup | Inline plus scheduled | A staged file is deleted as soon as its item is `done` or `skipped`. Staged files of `failed` and `duplicate` items are kept (for retry and import-as-copy) until the job is dismissed or completed more than 7 days ago. Never mtime-based. |
| Abandon stale uploads | Scheduled | `active` jobs with `awaiting_bytes` and `last_upload_at` more than 7 days ago: those items → `skipped` ("Not uploaded"), then the job is recomputed. |
| Prune job history | Scheduled | Delete job, group and item rows for jobs dismissed more than 30 days ago. Images are untouched. |
| Vector reconciliation | Startup (once the model has loaded) and daily | Id-set diff and re-embed (§5.3). Replaces the count-based forced rebuild. |
| Orphan store sweep | Scheduled | Fixed to compare sharded paths against keys correctly, and to account for all thumbnail sizes. Deletes orphans older than 1 h (not just logs). Tested. |

The scheduler runs each task once at startup as well as on its interval, so short Electron sessions still get maintenance.

**Removed:**
- `mark_interrupted_jobs` (destructive)
- `expire_stale_jobs`
- mtime-based `cleanup_stale_staging`
- `_finalize_import_job` cleanup
- the per-job FTS rebuild
- the `/fail` endpoint
- `analyse_upload`, `confirm-all`, `process_import_job`/`process_import_group`
- the `broken`, `expired`, `uploading` and `staging` statuses

---

## 10. Image conversion

By default the library stores each file exactly as uploaded. Three settings change that for **new** imports; existing images are never rewritten.

| Setting | Values | Default |
|---|---|---|
| `stored_format` | `original` \| `webp` \| `jpeg` \| `png` | `original` |
| `stored_quality` | 1–100, for lossy WebP and JPEG | 90 |
| `stored_lossless` | Lossless WebP for lossless sources | on |

`stored_format.convert` runs in prepare, after grid detection, and writes straight into the library's `.incoming/` temp directory. It never touches the staged upload or any user path. A file is **stored unchanged** when:

- it is already in the target format (re-encoding a JPEG only loses quality);
- it is animated (only the first frame would survive);
- it has transparency and the target is JPEG;
- the target is WebP and either side exceeds 16,383 px (WebP's limit, about 0.3% of the library).

Encoding rules, from the Phase 0 measurements:

- **JPEG sources never become lossless WebP.** That makes them about 3.1× larger (25 of 28 sampled) and costs about 11 s of CPU for a 20 Mpx map. They use `stored_quality` instead; lossy q90 gives about 0.56× for JPEG and 0.15× for PNG at about 0.1 s/Mpx.
- **WebP is always written with `exact=True`,** so colour under transparent pixels survives and the pixel hash still matches.
- The ICC profile is carried over.

**Hashes.** `content_hash` (source bytes) and `pixel_hash` always come from the upload; `stored_hash` is the SHA-256 of the stored file and `file_size` its size. Duplicate checks look at both byte hashes, so re-importing the original of a converted image is still caught at the bytes tier.

**Downloads** take their extension from `storage_key`, not the original filename (`backend/pipeline/naming.py`, `ImageViewer.buildDownloadFilename`), so a converted map downloads as `.webp`.

The Electron setup wizard's "Convert to WebP" choice still passes `CONVERT_TO_WEBP=1`, which seeds `stored_format = "webp"` on first run.

---

## 11. Testing

Backend unit tests:
- `ingest_state` transition table (every row in §4.1, plus illegal transitions)
- `recompute_job_status`
- error-kind classification
- round-robin claim ordering
- pixel-hash equality across PNG ↔ lossless WebP and metadata changes, and inequality for gridded vs gridless
- pHash distance sanity

Backend integration tests, with a real worker driven by `drain()`:
- **Happy path:** manifest → seal → PUT → done.
- **Recovery:** crash recovery (items left `processing`); a poison item fails after 3 claims.
- **Transient errors:** `database is locked` is retried and the import still completes.
- **System pause:** `ENOSPC` causes a system pause, then probe, then resume, with no failures.
- **Job control:**
  - cancel mid-job keeps `done` items;
  - Undo deletes exactly the job's images;
  - retry on a completed job re-opens it;
  - finish-without and abandonment.
- **Upload protocol:**
  - idempotent PUT;
  - resume (partial PUTs, then the remainder);
  - zip with a bad member;
  - manifest larger than 32,766 items (variable limit);
  - 409s after seal.
- **Duplicates:**
  - two concurrent jobs with the same file produce one image;
  - an in-job duplicate;
  - client-hash skip;
  - import as new copy produces a fully independent record (own file, thumbnails, embedding), including the client-hash-skipped case that needs bytes.
- **Vectors:** a vector write failure is repaired by reconciliation.
- **Model switch** causes a system pause, and ingest resumes afterwards.

Frontend:
- **`ImportManager`** (vitest, mocked API): per-file retry then continue; network-down wait and resume; resume matching; `beforeunload`; poller backoff, ETag and connection states; hash-worker fallback in an insecure context.
- **Component tests:** dock row states and report sections.

E2E (`e2e/`, Playwright against a real backend and the Vite dev server):
- The seed imports the fixture images through the real protocol (create, manifest, seal, hashes, PUT).
- Import dialog start view and type toggle; a new file imported end to end, shown in the report and undone; a re-imported file reported as already in the library; the dock row and its report.
- Not yet covered: pause/resume/cancel, retry and "Import as new copies" through the UI, and route-interception failure injection.

Stress (`stress_tests/`, see `docs/development/stress-testing.md`): a live server process with its real worker thread, SQLite, LanceDB and prepare pool, with synthetic fixtures. Scenarios cover throughput, manifests up to 40k items, round-robin fairness, concurrent jobs and endpoint spam, cancel/pause/undo/retry/import-as-copy under load, interrupted-upload resume, zip edge cases, SIGKILL recovery and maintenance running alongside an import. Its library integrity check asserts rows = stored files = vectors, with no shared content hashes and no `.incoming` leftovers.

---

## 12. Implementation history

Built in phases on `worktree-ingest-redesign` (2026-10-12 to 2026-10-16), merged as PR #1. Phase 5 and the Phase 6 test and docs work followed in a separate PR.

| Phase | Content | State |
|---|---|---|
| 0. Benchmark | Per-stage timings on 384 real maps | Done; results below |
| 1. Backend core | Tables, `ingest_state`, `IngestWorker`, commit protocol, hash tiers 1–2, vector reconciliation | Done |
| 2. API and maintenance | §7 endpoints, archive expansion, ETag, model-switch hold, §9 maintenance; old pipeline deleted | Done |
| 3. Frontend | `ImportManager`, hash worker, ImportDialog, ActivityDock, ImportReportDialog; old hooks and components deleted | Done |
| 4. Duplicate UX | Possible-duplicate (pHash) flags in the report | **Deferred** as a future feature; "Import as new copy" shipped in Phase 2–3 |
| 5. Conversion config | `stored_format`, `stored_quality`, `stored_lossless` (§10) | Done |
| 6. E2E and docs | E2E and stress suites on the new API; this document made permanent | Done |

### Phase 0 results (2026-10-15)

**Setup:** 384 maps sampled from the real library (stratified by size, up to 761 Mpx). Ryzen 9 5900X under WSL2, single process at nice 19. CPU time is the primary metric.

| Stage, library-weighted mean CPU ms per image | Old pipeline | New pipeline |
|---|---|---|
| Decodes per image | 3 (PIL, cv2 colour, cv2 gray) | 1 (plus grid's grayscale read) |
| Thumbnails | 430 | 89 (cascade from decoded image) |
| Colours | 232 | ~84 less (from the 800px thumbnail) |
| Grid detection (battlemaps) | 398 | 398, **the largest stage (34%)** |
| Pixel hash (strips) | – | 111 |
| pHash | – | ~1 (from a thumbnail) |
| Embedding, small / medium model | 102 / 474 | same |
| **Total, small model** | **~1,150** | **~830 → about 5 img/s on 4 cores, 10 on 8** |

Decisions taken from the results:

1. **Claim and commit batch stays at 16.** On CPU, embedding batch size barely matters for the small model and larger batches are worse for medium.
2. **Pixel hash** uses the strip implementation (about 0.7× a decode) with SHA-256. Colour under fully transparent pixels is zeroed before hashing, because libwebp rewrites it by default.
3. **Pixel limit.** Pillow's default 89.5 Mpx limit rejected about 2% of the real library. It is now `settings.max_image_pixels`, default 1 Gpx.
4. **OS junk.** 15% of image-extension files in the library are AppleDouble (`._*`, `__MACOSX`). The manifest ignores OS junk; other unsupported files become `skipped`, not `failed`.
5. **Storage format:** see §10.

**Memory per image.** The old pipeline decoded every image in full three times, about 3 GB for a 760 Mpx map. Now:

- **Reduced-scale JPEG decode.** JPEGs over `settings.pixel_hash_max_pixels` (default 100 Mpx) decode at reduced scale with `Image.draft`. These skip tier 2; tier 1 still applies. PNG and WebP always decode in full.
- **Memory budget.** `MemoryBudget` (`backend/app/services/memory_budget.py`) reserves each image's estimated peak, from the header alone, before decoding. Capacity is half of RAM beyond a 2 GiB reserve, or `settings.ingest_memory_budget_mb`. An image bigger than the whole budget runs alone.
- Grid detection is the dominant memory and CPU cost. Its resolution is the `grid_analysis_max_dim` setting (full resolution by default since grid v3; see [grid-detection-v3.md](grid-detection-v3.md)), and its per-format peak is part of the reservation.
- Progressive JPEGs and PNG/WebP still decode at full size (about 6 bytes/px for progressive JPEGs), up to about 1.3 GB at 200+ Mpx. Only a streaming decoder (pyvips) would fix that.

### Implementation notes worth keeping

- **Status is derived, never stored ad hoc.** `recompute_job_status` counts items; sessions don't autoflush, so it flushes first. `mark_bytes_received` recomputes too, or an all-duplicates import would stay `active` forever.
- **Duplicates are detected on byte receipt** as well as at commit (`HASH_DUPLICATE`). Their staged bytes are kept for "Import as new copy".
- **Done items have `staging_key` cleared inside the commit transaction**; the staged file is deleted afterwards, and the stray-staging sweep catches a crash in between.
- **Undo deletes rows, commits, then deletes files and vectors** (`deletion_service.PendingFileDeletes`), so a failed commit can't leave rows pointing at deleted files.
- **A model switch takes a worker hold** (`IngestWorker.held()`): it waits for the in-flight batch and pauses the queue with "Paused while the AI model changes". Imports are no longer cancelled by a model switch.
- **Library purge refuses** while any import has open items.
- **Orphan sweep safety valves:** only the `xx/yy/<key>` shard layout is considered (so `backups/` and `.incoming/` are never touched), files younger than an hour are ignored, and nothing is deleted if more than 25% of the store looks orphaned.
- **Test isolation.** The `test_client` fixture swaps the image and thumbnail store singletons for temp directories and doesn't start the worker.
- **Write-locked endpoints** (`api/dependencies.write_locked`) take `BEGIN IMMEDIATE` and release it on the endpoint's own thread. The first version took the lock in a FastAPI dependency, which runs on a different thread-pool slot from the endpoint body; under ~50–100 concurrent writes the waiters filled the pool, the holder couldn't get a slot, and requests failed with "database is locked" after the 10 s busy timeout. The stress suite found it.
- **Pillow plugins are loaded at startup** (`PILImage.init()` in the lifespan). Pillow otherwise dlopens its plugins the first time it meets an unidentifiable file; when that happened while prepare-pool threads were inside threadpoolctl's `dl_iterate_phdr` (sklearn KMeans in colour extraction), the process deadlocked on the loader lock and the GIL. The stress suite found it with corrupt uploads.
- **Uploads are checked against the manifest size;** a mismatch fails the item ("File changed size after it was chosen").
- **Frontend.** EditGroupDialog's live import-review mode was removed; the report's "Review in editor" opens every group the import created. The gallery refreshes as images land (throttled to 4 s), and every finished import gets a toast with "View report", except when its dialog is open.

### Live end-to-end run (2026-10-15)

Real backend and Vite dev server, driven through the UI with Playwright, on data copied read-only from the user's library.

- **Awkward folder** (42 maps, an in-folder copy, a zip of 3 copies, a truncated JPEG, a `notes.txt`, an AppleDouble file): 11.5 s; 42 done, 4 duplicates, 1 failed ("File content doesn't match its type"), 1 skipped, junk ignored, 8 groups.
- **Crash recovery:** the backend was SIGKILLed with 12–13 items `processing`. After restart the queue was ready in 6–7 s and the job completed about 4 s later. An integrity check found DB rows = stored files = vectors, with no `.incoming` leftovers or orphans.
- **Undo** removed every row, file, thumbnail and vector in three runs.
- Bugs it found, all fixed: a stale system pause after the model loaded; the poller keeping its idle interval after an import started; "Offline" lingering up to 30 s; finished groups counting duplicates against progress; toasts covering the dialog.

### Open items

- **Possible-duplicate flags (former Phase 4), deferred.** pHash puts gridded/gridless pairs 0–2 bits apart and unrelated images at ≥20 bits, so flags must be suppressed or grouped within an import group and between sibling grid/no-grid folders, or about 9k images in the real library would flag.
- **Progress moves in batch-sized steps** (up to 16 items commit together). A "processing" segment on the meter would make it feel smoother.
- **Library purge deletes `backups/`,** because backups live inside the image library folder. This predates the pipeline and needs its own decision.
- **Bulk local-library import** (§14).

---

## 13. Audit findings → design

Finding ids are from the 2026-10-12 audit (B = backend, F = frontend).

| Finding | Addressed by |
|---|---|
| B-C1 restart deletes all work, no resume | Durable items, `recover_ingest`, no implicit deletion (§4, §9) |
| B-C2 WebP deletes source in place | Conversion only on worker temp copies; default off (§10) |
| B-H1 one failed group wipes the job | No job failure; per-item commit; transient retry (§4.2, §5.4) |
| B-H2 jobs stuck `active` forever | Status derived from item counts by one function; no in-memory payload (§4.2) |
| B-H3 cancel doesn't stop the worker | Status checked at claim; cancel skips remaining items (§5.5) |
| B-H4 timers kill long imports | No expiry of active jobs; state-based staging cleanup (§9) |
| B-H5 dedup broken under WebP; racy | `source_hash` from the original; commit-time check under `BEGIN IMMEDIATE` (§6) |
| B-H6 more than 32k SQLite variables | Chunked manifest, chunked `IN`, no whole-job `IN` (§7) |
| B-H7 analyse/fail race | No analyse step or `/fail`; seal is idempotent and server-owned (§7) |
| B-H8 blocking async endpoints | Async streaming plus `to_thread` (§7) |
| B-H10 orphaned store files | Temp-then-rename placement; fixed sweep (§5.3, §9) |
| B-M1/M2 vector inconsistency | Id-set reconciliation, not a forced rebuild (§5.3) |
| B-M5/M6 O(n²) work and huge JSON rows | No `.file_map.json`, `analysis_result` or `file_errors` JSON; counts by indexed query; paginated items (§3, §7) |
| B-M10 confirm submits before commit | No confirm step; the worker reads committed `ready` items (§5) |
| B-M11 import queued behind maintenance | Dedicated worker separate from `JobRunner` (§5) |
| B-M12 maintenance never runs in Electron | Scheduler runs tasks at startup (§9) |
| B-M14 per-job FTS rebuild | Removed (§5.3) |
| F1 `/imports/active` request loop | Single manager-owned poller with ETag; views are pure (§8.1) |
| F2 all-duplicates job stuck in staging | No auto-confirm; job completes from item counts (§4.2) |
| F3 dismiss deletes everything | Dismiss only hides; Undo is explicit (§4.2) |
| F4 one file or 3 s of outage fails the import | Per-file retry, continue, wait for connection (§8.1) |
| F5/F6 hidden or lost uploads, phantom "Uploading" | Manager owns uploads; `beforeunload`; resume; "upload interrupted" display (§8) |
| F7 localStorage overflow | Only job ids persisted (§8.1) |
| F-M2/M4/M12 failures invisible or misreported | Completion toast for every outcome; report sections from item states (§8.2) |

## 14. Risks and open questions

- **Pixel-hash determinism.** JPEG decoding is stable for a given libjpeg-turbo, but a Pillow upgrade could in theory change the decoded output. The failure mode is a missed duplicate, never a false skip, so this is acceptable.
- **Request count.** One `PUT` per file means about 10k requests for a 10k-file import. That's fine on localhost and HTTP/1.1 keep-alive, but a reverse proxy with its own rate limits must allow for it (§7).
- **SQLite write contention.** Batch commits are short, but user edits during a big import compete for the writer. `busy_timeout` plus transient retry covers it. API endpoints take the write lock on the thread that does the work (`write_locked`, §12), so concurrent requests queue for the lock rather than for thread-pool slots.
- **Possible-duplicate volume.** When pHash flags ship, a job could flag many items; the report will need grouping by existing image and bulk actions (§12).
- **Shared-storage "add to group".** Should there also be an action that puts the *existing* image into the new group, alongside "Import as new copy"?
  - Today an image belongs to exactly one group, so this would be either a second record sharing the stored file (with diverging tags) or a move.
  - Doing it properly needs many-to-many group membership. Deferred until there's a concrete need.
- **Future bulk import.** Linked library folders will add an item source whose bytes are read in place rather than staged. The item and job model, worker, report and dock should need no structural change. Revisit `kind` and `staging_key` vs a `source_path` then.

## 15. Related

- **Videos** are imported like images but use tier-1 duplicates only. A first frame (`backend/app/services/video_utils.py`) supplies thumbnails and the embedding, and `max_video_file_size` caps their size. Images and videos are told apart by `images.media_type`.
- **Group detection** (folder-based, then prefix-based) runs at seal; see [parser.md](parser.md).
- **Grid detection** runs in prepare for battlemaps; see [grid-detection-v3.md](grid-detection-v3.md).
- **Other background work** (backfills, retagging, embedding rebuilds, model downloads) runs through `JobRunner` (`backend/app/services/job_runner.py`), and periodic maintenance through the scheduler (`backend/app/services/scheduler.py`).
- **Logging** is set up once in `backend/app/logging_config.py`: stdout plus `{data_dir}/logs/scene-atlas.log` (10 MB, 5 rotations), `DEBUG` with `--debug`.
- **Command-line maintenance** (`uv run python -m backend.pipeline.<module>`): `backfill_content_hash`, `backfill_grid_detection`, `reparse_names`, `retag_all_images`, `fix_orphaned_images`, `export_library`.
