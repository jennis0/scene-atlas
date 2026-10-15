# Ingest Pipeline Redesign

**Status:** Accepted design. Implementation is in progress on branch `worktree-ingest-redesign` (see [ADR-018](decisions.md#adr-018-durable-per-item-ingest-pipeline)).

**Scope:** the web/Electron upload path, from file selection through processing to the import report. Bulk import of an existing local library (linked folders, rescans) is **out of scope** here. This design deliberately makes it a later addition: a folder becomes another way of supplying bytes to the same item queue.

Until this lands, the current behaviour is still described by [import-state-machine.md](import-state-machine.md), [web-import.md](web-import.md) and [ingestion.md](ingestion.md). When implementation completes, fold this document into those docs (see Phase 6) and drop the "redesign" framing.

Scene Atlas is unreleased, so **no data migration or backwards compatibility** is required. Old import tables, statuses and endpoints are replaced outright.

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
| `label` | Display label, e.g. "Forest Pack.zip" or "3 folders" |
| `status` | `active` \| `paused` \| `completed` \| `cancelled` (see §4.2) |
| `default_image_type` | `battlemap` \| `scene` |
| `planned_at` | Set when the manifest is sealed and groups are planned. Items are claimable only after this. |
| `last_upload_at` | Last byte receipt. Drives the "upload interrupted" display and abandonment. |
| `dismissed_at` | Hidden from the activity dock. Never deletes anything. |
| `created_at`, `updated_at`, `completed_at` | |

Removed relative to today: `analysis_result`, `job_warnings`, `error_message`, `total_files`, `total_file_size`, and the whole `import_group_jobs` table.

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
| `similar_to_image_id`, `similarity_distance` | Perceptual-hash flag (advisory only, §6) |
| `created_at`, `updated_at` | |

Indexes:
- `(state, job_id)`, for claiming
- `(job_id, state)`, for counts
- `(job_id, import_group_id)`

### `images` changes

| Column | Notes |
|---|---|
| `source_hash` | Replaces `content_hash`. SHA-256 of the **original** uploaded bytes, never of converted output. Indexed. Not unique (see "Import as new copy"). |
| `stored_hash` | SHA-256 of the stored file. Equal to `source_hash` when no conversion happened. Lets re-imports of exported files match. Indexed. |
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

`recompute_job_status(job_id)` is the only writer of `active` ↔ `completed`, as `transition_job_status` is today. It is called after every batch commit, byte receipt, retry, import-as-copy and finish-without. A retry on a `completed` job re-opens it to `active`.

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
   - **Throughput (measured in Phase 0):** ingest is CPU-bound. The redesigned pipeline is estimated at about 5 images/s on 4 cores and about 10 on 8 with the small model (3.3 and 6.7 with the medium model). That needs 23–45 MB/s of library writes, well within HDD sequential speed.
     - Concurrent writes from the prepare pool could cause seek thrash on an HDD. The mitigation, if Phase 0 shows it, is a single library-writer thread that serialises the temp writes into one sequential stream.
     - Phase 0 measures this with the library on an HDD.
2. **Embed:** batch the embeddings.
3. **Commit** in one `BEGIN IMMEDIATE` transaction. SQLite's single writer makes check-then-insert race-free without a unique index.
   - Dedup check against `source_hash`, `stored_hash` and `pixel_hash` (skipped when `allow_duplicate`). Duplicates become `duplicate` and their temp files are discarded.
   - Rename the temp files into place.
   - Insert the images, tags and colours. Resolve or create the `ImageGroup` and record it on `import_groups.image_group_id`. Mark the items `done` with `image_id`.
   - If the commit fails, delete the renamed files, then classify the error (usually transient).
4. **Vectors:** `merge_insert` into LanceDB after the commit. A failure is logged, not fatal.
   - **Reconciliation** runs at startup, after each job completes, and on schedule. It compares image ids between SQLite and LanceDB (id sets, not counts) and re-embeds the missing ones from the stored file. This replaces today's count-based auto-rebuild, which could drop the whole table.

Crash windows:
- Between rename and commit: orphan files remain. The orphan sweep handles them (fixed to compare keys correctly).
- Between commit and vector write: the image is missing a vector. Reconciliation handles it.

The full-library FTS rebuild after each job is removed; the INSERT/UPDATE/DELETE triggers already maintain FTS.

### 5.4 Error classification

`error_classifier.classify_ingest_error` gains a `kind`:

| Kind | Examples | Handling |
|---|---|---|
| `file` | `UnidentifiedImageError`, `DecompressionBombError`, cv2 read failure, truncated file, size mismatch with manifest | Item → `failed`. Retry is allowed but labelled as unlikely to help. |
| `transient` | SQLite `database is locked`/busy, `MemoryError`, ONNX runtime error, LanceDB transient error | Item → `ready` with exponential `retry_after`, up to 3 attempts, then `failed`. A `MemoryError` on a batch re-claims those items with batch size 1. |
| `system` | `ENOSPC`, image library root unavailable, embedding model not loaded, model switch or embedding rebuild in progress | The batch's items go back to `ready` with the attempt refunded. **The queue is system-paused** with a user-facing reason. |

System pause:
- It is worker state, held in memory and re-detected after a restart.
- It is exposed in the `GET /imports` response.
- The worker re-probes the condition every 30 s (free space above the threshold, model ready, library path reachable), and the user can force a probe with "Retry now".
- Today the model-switch endpoint refuses while imports are active. Instead, the switch system-pauses ingest for its duration ("Paused while the AI model changes") and the pause clears when it finishes.

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
| 3. Perceptual | 64-bit DCT pHash (or dHash) via OpenCV/numpy (no new dependency) | Worker, from the thumbnail-sized decode | Lossy re-encodes, resized copies, VTT-compressed vs full-res, gridded vs gridless | **Never skip.** The item is `done` with `similar_to_image_id` set, shown as "Possible duplicate of X". Actions: Keep both (default) or Remove this one. ("Replace the existing image" is deferred.) |

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
- **The existing reuse path is removed:** today's `reuse_storage_key` branch in `prepare.py` and storage-key reference counting in `deletion_service`. Every image owns its stored file. Shared-storage records are a pending open question (§14).

Within one job, two identical files are handled by the commit-time check: the second becomes `duplicate` of the first.

Videos use tier 1 only.

Perceptual flags and their bulk UI are Phase 4. The hashes themselves are computed and stored from Phase 1.

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
- **Async endpoints must not block the event loop.** Streaming uses async I/O; parsing, zip expansion and DB work go through `asyncio.to_thread`. This fixes today's blocking `async def` endpoints.
- **Limits:**
  - `max_import_file_size` stays.
  - `max_import_total_size` and the per-batch `max_import_files` are replaced by the seal-time free-space check plus a generous `max_import_items` (default 50,000), enforced across all manifest chunks.
- **Rate limiting** (security phase 2) must budget for one request per file on the content endpoint.
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
  4. Show the group plan with live per-group progress. This is information, not a review gate: processing starts immediately, as today.

  The dialog can be closed at any point and reopened from the dock.
- **ActivityDock:** one row per non-dismissed job.
  - Example: "Forest Pack · uploading 120/400 · imported 80 · 2 failed".
  - Pause, cancel and open controls.
  - A queue-level banner when system-paused, with "Retry now".
  - "Upload interrupted" rows offer "Choose files to resume" or "Finish without them".
- **ImportReport** (replaces `ImportSummaryDialog` and `ImportDonePane`). Sections: Groups (status, merged-into-existing), Problems (failed grouped by `error_reason`, retry per reason or per item), Duplicates (linked to the existing image; "Import as new copy"), Possible duplicates (Phase 4), Skipped. Actions: Retry failed, Undo import (confirm with counts), Dismiss. All lists are virtualised and paginated from `GET /imports/{id}/items`.
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

- **`convert_to_webp` defaults to off** from Phase 1.
- Phase 5 replaces it with a server config option: `stored_format` ∈ `original` (default) | `webp` | `jpeg` | `png`, plus `stored_quality` (and lossless for WebP).
- **Phase 0 findings that constrain Phase 5:**
  - Lossless WebP makes JPEGs about **3.1× larger** (25 of 28 sampled) and shrinks PNGs to about 0.59×. It costs about 11 s of CPU for a 20 Mpx map, roughly 13× the rest of the pipeline.
  - Lossy q90 gives 0.56× for JPEG and 0.15× for PNG at about 0.1 s/Mpx.
  - So: never offer lossless conversion for lossy sources, always encode WebP with `exact=True`, and skip conversion for images wider or taller than 16,383 px (WebP's limit, about 0.3% of the library).
- Conversion only ever operates on worker-owned temp copies, never on staged originals or any user path.
- `source_hash` and `pixel_hash` are always computed from the source; `stored_hash` from the output.

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

E2E:
- happy path
- route-interception failure injection (aborted PUTs)
- reload mid-upload, then resume

---

## 12. Implementation plan

Large feature; worktree branch `worktree-ingest-redesign`. **The branch is not mergeable until Phase 3 completes**, because the frontend and backend contracts change together.

| Phase | Content | Exit criteria |
|---|---|---|
| **0. Benchmark** (optional, parallel) | Per-stage timings on about 500 maps from the real library: decode, thumbnails, colours, grid detection, embedding, pixel hash, WebP. | Numbers recorded here; batch size and the pixel-hash choice confirmed |
| **1. Backend core** | Alembic migration (drop `import_group_jobs`, reshape `import_jobs`, add `import_groups`/`import_items`, image hash columns). `ingest_state` module. `IngestWorker` (claim, round-robin, recovery, system pause, `drain()`). Commit protocol with tiers 1–2 and atomic placement. pHash stored. Error kinds. Vector reconciliation. WebP default off. | Unit and service-level integration tests green, driven without the HTTP API |
| **2. Backend API and maintenance** | New endpoints (§7), archive expansion, ETag progress version, model-switch pause. Delete old endpoints and pipeline functions, and rewrite maintenance (§9). Fix the orphan sweep. | API integration tests green; no references to the removed code |
| **3. Frontend** | `ImportManager`, hash worker, poller; new ImportDialog, ActivityDock and ImportReport; EditGroupDialog hookup; delete the old hooks and components; remove the Electron fs IPC. | Vitest green; manual run of import, interrupt and resume on Linux and Windows |
| **4. Duplicate UX** | Import as new copy (bulk and per item), possible-duplicate flags in the report. | Tests plus manual check |
| **5. Conversion config** | `stored_format`/`stored_quality` server config, `stored_hash`. | Tests |
| **6. E2E and docs** | E2E failure-injection specs. Fold this document into `import-state-machine.md`, `web-import.md`, `ingestion.md` and `storage.md`; update `backend.md`, `frontend.md`, `security.md` (rate limits) and `status-and-roadmap.md`. | Docs describe the shipped system; this file removed or reduced to a pointer |

### Phase 0 results (2026-10-15)

**Setup:** 384 maps sampled from the real library (stratified by size, including the largest at up to 761 Mpx). Ryzen 9 5900X under WSL2, single process at nice 19 while the machine was busy. CPU time is the primary metric. Raw data and scripts were kept outside the repo.

| Stage, library-weighted mean CPU ms per image | Current pipeline | Redesign |
|---|---|---|
| Decodes per image | 3 (PIL, cv2 colour, cv2 gray) | 1 (plus grid's grayscale read) |
| Thumbnails | 430 | 89 (cascade from decoded image) |
| Colours | 232 | ~84 less (from the 800px thumbnail) |
| Grid detection (battlemaps) | 398 | 398, **the largest stage (34%)** |
| Pixel hash (strips) | – | 111 |
| pHash | – | ~1 (from a thumbnail) |
| Embedding, small / medium model | 102 / 474 | same |
| **Total, small model** | **~1,150** | **~830 → about 5 img/s on 4 cores, 10 on 8** |

**Decisions taken from the results:**

1. **Claim and commit batch stays at 16.** On CPU, embedding batch size barely matters for the small model and larger batches are worse for medium. If the embed batch is ever split from the claim batch, use 4–8 on CPU.
2. **Pixel hash:**
   - Kept, using the strip implementation, which costs about 0.7× a decode.
   - Switched to SHA-256 (about 2× faster than BLAKE2 with SHA-NI).
   - **Fixed:** colour under fully transparent pixels is now zeroed before hashing. libwebp rewrites it by default, which made 8 of 12 transparent PNGs fail to match their own lossless WebP.
3. **Pixel limit.** `Image.MAX_IMAGE_PIXELS` was Pillow's default (89.5 Mpx), promoted to an error, which **rejected about 2% of the real library (about 1,000 maps)**. It is now `settings.max_image_pixels`, default 1 Gpx.
4. **OS junk.** 15% of image-extension files in the library are AppleDouble (`._*`, `__MACOSX`). The manifest now ignores OS junk. Other unsupported files become `skipped`, not `failed`.
5. **WebP:** see §10.
6. **Disk:** not measured; the session couldn't run Windows tools. Ingest needs only 23–45 MB/s, so the single library-writer mitigation stays optional.

**Memory per image (done, 2026-10-15).** The old pipeline decoded every image in full three times, at 4 bytes/px in Pillow, which is about 3 GB for a 760 Mpx map. Now:

- **Reduced-scale JPEG decode.** JPEGs over `settings.pixel_hash_max_pixels` (default 100 Mpx) are decoded at reduced scale with `Image.draft` (libjpeg DCT scaling). Everything downstream except the pixel hash needs ≤800 px.
  - These images skip tier 2. Tier 1 (bytes) still applies.
  - PNG and WebP can't be decoded at reduced scale by Pillow, so they are always decoded in full.
- **Reduced-scale grid read.** Grid detection reads with `cv2.IMREAD_REDUCED_GRAYSCALE_{2,4,8}` when the cap allows. The results are identical to a full read at the same cap (unit-tested).
- **Memory budget.** `MemoryBudget` (`backend/app/services/memory_budget.py`) reserves each image's estimated peak, from the header alone, before decoding.
  - Capacity: half of RAM beyond a 2 GiB reserve, or `settings.ingest_memory_budget_mb`.
  - An image bigger than the whole budget runs alone.
- **Measured** peak RSS of the whole prepare step on a 400 Mpx JPEG:

  | Configuration | Peak RSS | CPU |
  |---|---|---|
  | Grid detection off | 279 MB (mostly interpreter and libraries) | 2.1 s |
  | Grid at a 20k cap | 2,244 MB | 15.3 s |
  | Grid at an 8k cap | 558 MB | 2.5 s |

  **The grid cap is now the dominant memory and CPU lever.**

**Follow-ups, not yet scheduled:**

- **Grid cap: done, default lowered from 20,000 to 8,000 px.** Measured on 373 real battlemaps:
  - Presence agreement with the 20k baseline is 99.5%; size agreement is 95% (net about −0.5% of images).
  - Filename-truth accuracy is unchanged at 39/47.
  - CPU on the largest maps drops 3–4× (761 Mpx: 18 s → 5.5 s), and peak memory on baseline JPEGs drops from 1.45 GB to 0.37 GB.
  - 6,000 px needs the sub-pixel fix below first, and 4,000 px clearly loses accuracy.
  - Existing databases keep their seeded value until it's changed in settings.
- **Grid detector accuracy.** Two error sources, independent of the cap:
  1. Grid spacing is measured in whole pixels. A sub-pixel peak refinement fixed several off-by-one counts on large maps in an offline test.
  2. `_pick_best_periods` sometimes picks double or half the real grid size, even at 20k. This is the main error source.
  - An alternative algorithm (streamed 1-D spectral analysis) is being prototyped separately.
- **Progressive JPEGs and PNG/WebP decode at full size whatever the scale**: about 6 bytes/px of coefficient buffer for progressive JPEGs. `plan_decode` reserves accordingly, so the memory budget stays honest, but these files still cost up to about 1.3 GB at 200+ Mpx. Only a streaming decoder (pyvips) would fix that.
- **pHash** puts gridded/gridless pairs at 0–2 bits apart and unrelated images at ≥20. Phase 4 must suppress or group "possible duplicate" flags within the same import group and between sibling grid/no-grid folders, or about 9k images will flag.

### Phase 1 status (done)

**Where the code lives:**

| Module | Responsibility |
|---|---|
| `backend/app/services/ingest_state.py` | Pure item and job state machines. The DB layer derives allowed source states from its transition table. |
| `backend/pipeline/ingest_queue.py` | All durable operations: create, manifest, plan (seal), byte receipt, claim, failures, recovery, retry, import-as-copy, skip, pause, resume, cancel, `recompute_job_status`, and `write_session()` (`BEGIN IMMEDIATE`). |
| `backend/pipeline/ingest_process.py` | One batch: `prepare_item` (prepare pool), `embed`, `commit_batch` (one write transaction with temp-then-rename placement), `write_vectors`, `process_batch` |
| `backend/pipeline/ingest_worker.py` | `IngestWorker` (loop thread, round-robin cursor, system pause and probe, `drain()`, `status()` with a version counter) and `get_ingest_worker()` |
| `backend/pipeline/image_hashes.py` | SHA-256, strip-wise pixel hash, DCT pHash |
| `backend/pipeline/vector_reconcile.py` | Id-set reconciliation |
| `backend/alembic/versions/020_ingest_items.py` | New tables and columns. Additive only, so the old flow keeps working until Phase 2. |

**Refinements made during implementation:**

- **Column names.** The job label stays in `import_jobs.source_label`, and the source hash stays in `images.content_hash`. Both are still used by the old flow; rename them, if at all, in Phase 2's cleanup migration.
- **Decoding once.** Prepare decodes each image once for the pixel hash and thumbnails.
  - Colour extraction and the pHash read the 800px thumbnail rather than the original (colour extraction downsamples to 512px anyway).
  - Thumbnails cascade large → medium → small instead of copying the full-resolution image three times.
  - Only grid detection re-reads the original.
- **`error_kind`** also takes `bytes_lost` (the staged file disappeared; the item goes back to `awaiting_bytes`).
- **Sessions don't autoflush**, so `recompute_job_status` flushes before counting. Without this every job stayed `active` forever; the integration tests catch it.
- **WebP defaults to off everywhere:** the backend seed, the settings schema, the Electron setup wizard and config, and `.env.example`. The new pipeline doesn't convert at all until Phase 5.

**Carried into Phase 2:**

- **Wire the worker into the FastAPI lifespan** (`recover()` then `start()`) **at the same time as removing `mark_interrupted_jobs`.** That function would treat the new `active` jobs as interrupted and delete their images, which is why the worker isn't wired up yet.
- **The orphan sweep must skip `.incoming/`** (and `backups/`).
- **Maintenance deletes staged files of `done` items.** They're normally removed right after the commit, but a crash in between leaves them behind.
- **Undo** must use `import_groups.image_group_id` and `merged_into_existing` to decide which gallery groups to delete. The current `cleanup_import_images` uses `ImportGroupJob.created_group_id`.
- **The import report** must handle items whose `image_id` points at an image the user has since deleted. SQLite foreign keys aren't enforced.
- **MemoryError back-off to batch size 1** is not implemented; MemoryError is retried as transient. Superseded by the memory-aware admission follow-up in the Phase 0 results.

### Phase 2 status (done)

**Where the code lives:**

| Module | Responsibility |
|---|---|
| `backend/app/api/imports.py` | The §7 API. Mutating endpoints use `get_write_db` (`BEGIN IMMEDIATE`). `GET /imports` supports `ETag`, keyed on the worker version plus a minute bucket for the time-derived `upload_interrupted` flag. |
| `backend/app/models/import_schemas.py` | Request and response models |
| `backend/pipeline/ingest_archive.py` | Server-side zip expansion into items, before seal |
| `backend/pipeline/ingest_maintenance.py` | Abandon stale uploads, release staged bytes by state, prune dismissed jobs, sweep stray staging files |
| `backend/pipeline/maintenance.py` | Backups, and the orphan sweep (now deletes) |
| `backend/app/services/scheduler.py` | Persists each task's last run under `<app data>/scheduler/`, so overdue tasks run 60 s after startup |
| `backend/alembic/versions/021_drop_legacy_import_tables.py` | Drops `import_group_jobs` and the old `import_jobs` columns, and deletes old-status job rows (their images are kept) |

**Removed:**
- **Pipeline:** `ingestion.py`, `prepare.py`, `persistence.py`, `services/staging.py`, `services/import_state.py`, `tasks/webp_conversion.py` (it deleted its input in place), and the old thumbnail helpers.
- **Model:** the `ImportGroupJob` model and the old import schemas.
- **Maintenance:** `mark_interrupted_jobs`, `expire_stale_jobs`, the staging cleanups and the count-based vector check.
- **Tests:** about 15 test modules for the removed code.

**Refinements made during implementation:**

- **Duplicates are also detected on byte receipt,** not only at commit. The event was renamed `HASH_DUPLICATE`. Staged bytes are kept for "Import as new copy".
- **`mark_bytes_received` recomputes the job status itself.** Without this, an import whose every file was a duplicate stayed `active` forever, the same bug class as the old F2. Tests catch it.
- **Done items have `staging_key` cleared in the commit transaction.** The staged file is deleted after the commit; a crash in between leaves an unreferenced file for the stray-staging sweep.
- **Undo deletes rows, commits, then deletes files and vectors** (`deletion_service.PendingFileDeletes`). A failed commit can no longer leave rows pointing at deleted files (audit M3).
- **A model switch takes a worker hold** (`IngestWorker.held()`), which waits for any in-flight batch and pauses the queue with "Paused while the AI model changes". The switch is no longer refused while imports are active.
- **Library purge refuses** while any import has open items, and deletes the new import tables.
- **Orphan sweep safety valves:**
  - It only considers files in the `xx/yy/<key>` shard layout, so `backups/` and `.incoming/` are never touched.
  - It ignores files younger than an hour.
  - It deletes nothing if more than 25% of the store looks orphaned, since that most likely means the wrong database is in use.
- **Test isolation fix.** The `test_client` fixture now swaps the image and thumbnail store singletons for temp directories and doesn't start the worker. The cached singletons were how earlier test runs leaked files into the repo's `images/` folder.

**Known gaps until Phase 3 / Phase 6:**

- **The frontend still calls the old endpoints,** so imports through the UI don't work on this branch until Phase 3.
- **`e2e/helpers/seed.ts` and `stress_tests/`** still use the old API (Phase 6).
- **Library purge deletes `backups/`.** This predates the redesign: backups live inside the image library folder, and the purge removes that whole folder. It needs a separate decision.

### Phase 3 status (in progress)

**Step 1, `ImportManager`: done.** It lives in `frontend/src/lib/import/`:

| File | Responsibility |
|---|---|
| `types.ts` | API types |
| `importClient.ts` | Typed HTTP client |
| `hasher.ts`, `hash.worker.ts` | Web Worker SHA-256. Off in insecure contexts and for files over 256 MB. |
| `ImportManager.ts` | Uploads, resume, single poller, unload guard, actions |
| `useImports.ts` | `useSyncExternalStore` hooks |

**Behaviour:**
- **Upload retries:**
  - Network errors back off (capped at 30 s) and retry indefinitely while the tab is open; the upload shows "waiting for connection".
  - 5xx/408/429 retry up to 5 times, then the file is recorded as a local failure. It stays `awaiting_bytes` server-side, so it can be resumed.
  - 409/404 stop quietly.
  - Other 4xx (e.g. 413) fail the file at once.
- **Setup calls** (manifest, archives, seal, hashes) use the same retry policy. If the import can't be started (e.g. 507 at seal), the job is cancelled so it can't sit active forever.
- **Pipelining:** a hashing round (50 files) runs ahead of 3 concurrent uploads.
- **Poller:** 1 s while anything is active, 5 s when the tab is hidden, 30 s when idle, with exponential backoff on errors. One failure shows the connection as `degraded`, three as `lost`. Concurrent refreshes are coalesced.
- **Notifications:** `onJobFinished` fires when a job moves from active/paused to completed/cancelled (for toasts).

**Steps 2 (views) and 3 (wiring and deletions)** are next.

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
- **Request count.** One `PUT` per file means about 10k requests for a 10k-file import. That's fine on localhost and HTTP/1.1 keep-alive; reverse-proxy rate limits need configuring (§7).
- **SQLite write contention.** Batch commits are short, but user edits during a big import compete for the writer. `busy_timeout` plus transient retry covers it; watch for it in Phase 0/1.
- **Possible-duplicate volume.** A job could flag many items; the report needs grouping by existing image and bulk actions (Phase 4).
- **Shared-storage "add to group".** Should there also be an action that puts the *existing* image into the new group, alongside "Import as new copy"?
  - Today an image belongs to exactly one group, so this would be either a second record sharing the stored file (with diverging tags) or a move.
  - Doing it properly needs many-to-many group membership. Deferred until there's a concrete need.
- **Future bulk import.** Linked library folders will add an item source whose bytes are read in place rather than staged. The item and job model, worker, report and dock should need no structural change. Revisit `kind` and `staging_key` vs a `source_path` then.
