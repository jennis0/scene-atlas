# Local ingest

Three ways to import files without the browser uploading them. Status: **plan**. Feature 1 is
specified in detail and **built** (branch `feature/local-folder-ingest`); features 2 and 3 are outlined so the data model leaves room for them. Feature 2 is desktop-only too: in server mode only the drop folder will read server paths.

| # | Feature | What it is | Status |
|---|---|---|---|
| 1 | **Local folder import** | In the desktop app, an import from files or folders on this computer reads them where they are and copies them into the library. No upload. Chosen automatically; the user sees the same import dialog. | Built |
| 2 | **Linked library** (in-place) | Desktop app only. Folders configured at the app level stay where they are; the library references them instead of copying. Rescans pick up new, moved and missing files. | Outline ([§8](#8-feature-2-linked-library-outline)) |
| 3 | **Drop folder** | A folder watched by the server; files dropped in are imported, then removed. The server-mode replacement for feature 1. | Outline ([§9](#9-feature-3-drop-folder-outline)) |

Features 2 and 3 build on feature 1's server-side reading. Feature 1 also stands alone: a USB
drive or a downloads folder you want copied in.

Builds on [ingestion.md](ingestion.md) (items, states, worker); section numbers there are cited
as "ingestion §N".

## 1. Why

The import dialog uploads every file through the browser. For a large existing library (the
target is the user's 56k images / 216 GB, [ingestion.md](ingestion.md) Phase 0 benchmark),
that costs:

- **The renderer walks the tree.** A dropped folder is enumerated with `webkitGetAsEntry`
  (100 entries per `readEntries` call) and a `File` is held for every file; the manifest is built
  and sent from the browser.
- **The client hashes everything** (`hasher` worker) to skip duplicates before upload, which is
  a full read of 216 GB in the renderer.
- **Every byte is written twice on the server**: to `staging/`, then copied to
  `{library}/.incoming/` at prepare.
- **The browser drives the upload.** Closing the window or a restart mid-upload leaves the job
  "upload interrupted" until the user re-picks the files.

The time saved is smaller than it looks: localhost upload of 216 GB is ~10–20 minutes, while
processing (embedding, grid detection, thumbnails) is hours either way. The real gains are
reliability (a restart just carries on), no second write, no renderer memory per file, and
seconds instead of minutes to start a 50k-file import.

## 2. Decisions

| Decision | Choice | Why |
|---|---|---|
| Where it's available | **Desktop app only** (`APP_MODE=app`). Server mode keeps browser upload; feature 3 covers it later. | In server mode the client and the files are on different machines, and an endpoint that reads server paths named by a client is a file-read primitive. |
| How it's chosen | **Automatically**: in the desktop app, picks and drops that have local paths use it; anything else uploads as today. | Same dialog, same review; nothing to learn. |
| Copy or reference | **Copy** into the store, exactly as an upload ends up. Referencing in place is feature 2, configured at the app level, never per import. | Keeps the store's invariant (it owns every file it serves) for feature 1. |
| Who enumerates | **The server**, from the roots the user picked (folders and files). | Native `os.scandir` lists 60k files in seconds; the renderer takes minutes and holds a `File` each. |

## 3. Flow

```
renderer (Electron)                         backend
───────────────────                         ───────
pick folder (native dialog)  ─┐
or drop (getPathForFile on    ├─ roots ──▶  POST /imports                     → job
top-level items, no traversal)┘              POST /imports/{id}/local-sources → enumerate roots,
                                                                                insert items (ready),
                                                                                expand zips in place
                                             POST /imports/{id}/seal          → plan groups, wake worker
poll, review, report as today  ◀──────────  worker: read source → hash → dedup → copy → process
```

There is no `/hashes` call and no `PUT …/content`. The import report, the review editor
(including large-import mode, [editor-metadata-first.md](editor-metadata-first.md)) and the
activity dock are unchanged.

## 4. Backend

### 4.1 Data model

`import_items` gains **`source_path TEXT NULL`**: the absolute path of the original file, set
only for local items. `relative_path` keeps its meaning and its rule (display and grouping only,
never a filesystem path, ingestion §3.3); `source_path` is the one client-derived path that
reaches the filesystem, and only after the checks in [§6](#6-security).

`import_jobs` gains **`source_roots JSON NULL`**: the roots the user picked, for availability
checks ([§4.4](#44-failures)) and the report's label.

Exactly one of `staging_key` / `source_path` describes where an item's bytes are. Feature 2
will reuse `source_path` (relative to a linked root) for images, so the column name is chosen
to carry over.

Alembic migration: two nullable columns, no backfill.

### 4.2 `POST /imports/{id}/local-sources`

Body `{paths: [absolute path, …]}` (≤ 1,000 roots). App mode only: **404 in server mode**, so
the route doesn't exist there. `@write_locked`, heavy-op semaphore, enumeration in
`asyncio.to_thread`. 409 after seal.

For each root:

- **Folder**: walked with `os.scandir`, not following directory symlinks (no cycles, no escaping
  the chosen tree). `relative_path` is the path from the root's *parent*, so it starts with the
  folder's name: the same shape as `webkitdirectory` and drops, so the parser and grouping behave
  identically.
- **File**: one item, `relative_path` = its name.
- **Zip** (as a root or inside a folder): expanded with `expand_archive` reading the zip in
  place. `expand_archive` currently deletes `zip_path` afterwards; it gets a `keep_source` flag.
  Members are extracted to staging (they have no path of their own), so they're ordinary
  staged items. The zip's own relative path is passed as its name, so a pack zip's members
  land under its folder ([ingestion.md](ingestion.md#archive-member-paths)).

Filtering is the manifest's (ingestion §7): OS junk ignored, unsupported files `skipped`,
oversized `failed`. Items are inserted with `size`, `last_modified` from `stat`, `source_path`,
and state **`ready`** (the bytes are available; nothing is claimable before seal). Two roots
whose relative paths collide (two folders both called `Maps`) get the second root's paths
prefixed with its parent folder's name, as zip members are. Returns the counts, as the manifest
does.

**Limit**: `max_import_items` is 50,000, below the 56k target. Local imports get their own
`max_local_import_items` (default 250,000): the 50k cap protected the browser and the upload
protocol, neither of which is involved. Large-import review was measured at 50k
([editor-metadata-first.md](editor-metadata-first.md)).

Enumerating 60k files natively takes a few seconds (PowerShell measured ~3 s on the target
library). The request is synchronous; the dialog shows "Reading folder…". If OneDrive or a slow
drive makes that too long in practice, enumeration becomes a background step with progress.

### 4.3 Worker: reading a local item

`prepare_item` resolves an item's bytes from `source_path` when it is set, otherwise from
staging as today. For a local item:

1. **Stat** the source. Missing → see [§4.4](#44-failures).
2. **Hash** it (`file_sha256`, one read) and **check bytes-tier duplicates** against the library
   before decoding (read-only query; commit re-checks under the write lock as it does now). A
   duplicate costs one read instead of a full decode, thumbnails and grid detection, which
   matters when a library is re-imported. Uploads get this check at byte receipt; this is the
   local equivalent.
3. **Copy** to `{library}/.incoming/` (stored format `original`) or convert straight into it
   (ingestion §10). This is the copy prepare already makes from staging, so the library drive
   sees one write, not two.
4. Decode, thumbnails, colours, grid detection and commit run unchanged, reading the
   **`.incoming` copy**, not the source. The source is read twice (hash, copy; the second
   usually from the OS cache) and never again, so a slow or removable source isn't re-read by
   grid detection, and a file that changes mid-processing can't produce an inconsistent image.

The source is never written, moved or deleted. Undo import deletes the copies, as for uploads.

### 4.4 Failures

| Situation | Outcome |
|---|---|
| Source file missing, its root present | `failed`, kind `file`, stage `read`: "The file was moved or deleted after it was chosen". Retry re-reads it. |
| Source root missing (drive unplugged, folder renamed, network share down) | **The job waits**; nothing fails. The item goes back to `ready` with the attempt refunded (new event `SOURCE_UNAVAILABLE`), the worker skips jobs whose roots are missing, and the dock shows "Waiting for D:\Maps" with Cancel. Other imports continue: this is not a queue-wide system pause. |
| File changed between choosing and processing | Accepted: the bytes read at step 2 are what's imported. Grouping came from the path, which hasn't changed. A file caught mid-write fails as truncated and can be retried. |
| `PermissionError` | `failed`, kind `file` (existing rule). |

`bytes_lost` and `awaiting_bytes` never apply to local items: `RETRY` and `IMPORT_AS_COPY`
re-open them to `ready` because the source is the bytes (`_reopen` checks `source_path` as well
as the staged file). `upload_interrupted` can't trigger, since no local item awaits bytes.

**Restart**: local items are `ready` or `processing`; `recover()` re-queues as today and the
import continues with no user action.

## 5. Desktop app and frontend

### 5.1 Electron (preload and main)

Added to `window.electronAPI`:

| Member | Implementation | Use |
|---|---|---|
| `getPathForFile(file)` | `webUtils.getPathForFile` (Electron ≥ 32; we're on 40) in the preload | Paths of dropped items. Returns `''` for files with no disk path. |
| `chooseImportFolders()` | `system:choose-import-folders` → `dialog.showOpenDialog({properties: ['openDirectory', 'multiSelections']})` via `handleTrusted` | "Choose folder" without the renderer enumerating it |
| `chooseImportFiles()` | `system:choose-import-files` → `openFile`, `multiSelections`, image/video/zip filters | "Choose files" |

This is the first filesystem IPC; [electron.md](electron.md)'s "there is no filesystem IPC" line
is updated. The handlers only return paths the user picked; reading happens in the backend.

### 5.2 Import dialog and ImportManager

- **Detection**: `electronAPI.getPathForFile` present (desktop app) and `GET /system` reports
  `mode: app`.
- **Drop**: before any traversal, take `getPathForFile` of each top-level `dataTransfer.files`
  entry (a dropped folder has a path too). If every one has a path, start a local import with
  those roots; otherwise fall back to the current traversal and upload for the whole drop. No
  mixed jobs: one rule, easy to test.
- **Choose folder / files**: the native dialogs above instead of `<input webkitdirectory>`.
- **`ImportManager.startLocal(roots, options)`**: create the job (label: the root's name, or "N
  folders"), `local-sources`, seal, then the existing polling. No hashing, no upload slots, no
  resume-with-files.
- **Resume**: nothing to resume from the client; "Choose files to resume" never shows for local
  jobs.
- **"Reading folder…"** state in the dialog while `local-sources` runs, with the counts it
  returns.

Server mode and plain browsers are unchanged.

## 6. Security

Reading paths named by a client is the risk this feature adds. Controls:

- **App mode only.** The route is not registered in server mode ([§2](#2-decisions)). In app
  mode the sidecar binds `127.0.0.1` and has no auth (security.md), so anyone who can call the
  API is already a local process running as the user, which can read the files directly.
- **DNS rebinding** is the gap: a web page whose domain re-resolves to `127.0.0.1` becomes
  same-origin with the sidecar and could name paths and then fetch the imported copies. The
  backend has no `Host` check today (it would also protect every other endpoint).
  **Prerequisite: in app mode, reject requests whose `Host` isn't `127.0.0.1:<port>` or
  `localhost:<port>`** (Starlette `TrustedHostMiddleware`). Cross-origin requests without
  rebinding are already stopped by CORS preflight on the JSON body.
- **Only media is ingested.** Every local file passes the magic-byte check
  (`verify_media_mime`) when the worker reads it, before anything is copied, so the route can't
  pull arbitrary files into the store. (Checking at listing time would open every file of a 60k
  library before the import could start.)
- **Paths are normalised** (`Path.resolve`, absolute, existing) at enumeration; directory
  symlinks aren't followed; `source_path` is re-checked to be a regular file when read.
- **The source is never written.**

security.md gets a finding for this route and the `Host` check.

## 7. Implementation plan (feature 1)

1. **Backend core**: migration, `local-sources` route and enumeration (folders, files, zips
   with `keep_source`), `source_roots`, limits, app-mode gating, `Host` check.
2. **Worker**: `prepare_item` source resolution, early bytes-tier dedup, copy-first processing,
   `SOURCE_UNAVAILABLE` and per-job root availability, `_reopen` for local items, dock field
   for a waiting job.
3. **Electron**: preload `getPathForFile`, native pickers via `handleTrusted`.
4. **Frontend**: detection, drop and picker routing, `ImportManager.startLocal`, "Reading
   folder…" and "Waiting for …" states.
5. **Docs and measurement**: ingestion.md (item `source_path`, local flow, §4/§5 changes),
   electron.md, security.md; import the 50k synthetic library both ways and compare
   time-to-first-group, total time, renderer memory and library-drive writes.

### Tests

- **Unit**: enumeration (junk, unsupported, oversize, nested folders, symlink not followed,
  relative-path shape, root collisions), state transitions for `SOURCE_UNAVAILABLE` and local
  re-open, prepare's source resolution and early dedup.
- **Integration**: route is 404 in server mode; `Host` check; an end-to-end local import from a
  temp folder (done, duplicate, missing file → failed → retry, root removed → waits → restored →
  completes); zip roots aren't deleted; the source tree is byte-identical afterwards; restart
  mid-import continues.
- **Frontend**: drop routing with and without paths, picker routing, `startLocal` (mocked
  `electronAPI`), dialog states.
- **E2E** runs against the web build, where the feature is off; the integration suite covers
  the flow. An Electron smoke test of the pickers is manual for now.

### Measured (2026-10-17, WSL, dev build, CPU, small model)

| | |
|---|---|
| List 50,000 files (`list_roots`, ext4) | 2.6 s |
| `local-sources` + seal over HTTP, 50,000 files | 7.6 s + 8.1 s |
| Real folder from the target library (`atraxian_bear`, 800 files, read over WSL's `/mnt/d`) | listed in 10.8 s; processed in 11.5 min: 674 imported, 126 duplicates (copies inside the folder), 0 failed |
| The same folder imported again | 6.5 min, all 800 duplicates, nothing decoded or stored |

Re-import time is the hash read, bound here by WSL's 9p link to `/mnt/d` (~25 MB/s). The
desktop app on Windows reads at disk speed. A rescan in feature 2 should skip hashing files
whose path, size and mtime are unchanged.

## 8. Feature 2: linked library (outline)

Folders configured **at the app level** (Settings in the desktop app) become part of the library
without being copied. Desktop app only: in server mode the drop folder is the only way the server
reads its own paths.

- **Images reference their file**: `images.source_root_id` + `source_path` relative to the root;
  `storage_key` NULL for linked images. Thumbnails and embeddings live in the app's store as
  usual. Serving the original reads from the root.
- **Deleting never touches the original**: "Remove from library" only. The orphan sweep and
  library purge skip linked files.
- **Missing isn't deleted**: a root that's unavailable shows its images as offline; a missing
  file shows as missing. Neither is purged automatically.
- **Rescan** (manual, and at startup) adds new files through feature 1's item queue, marks
  missing ones, and matches moves by content hash and size. No file watching at first: watching
  60k files in a synced folder is unreliable.
- **Stored format** doesn't apply: linked files stay as they are.
- **OneDrive Files On-Demand**: files must stay downloaded; an online-only placeholder triggers
  a download on read or fails offline. The settings page says so.
- **Open questions**: overlapping roots; a linked root inside the store; turning a linked image
  into a copy (and back); what "Undo import" means for a rescan.

## 9. Feature 3: drop folder (outline)

A server-configured folder watched for new files; the server-mode way to bulk import without
the browser.

- **Settle before reading**: a file is picked up once its size and mtime are stable for a
  period, so half-copied files aren't imported.
- **Grouping**: files arrive over time, so either each top-level subfolder is one import once it
  has been quiet for a while, or loose files are batched by quiet period.
- **Removal only after commit**: imported files are deleted once their image is committed;
  duplicates and failures move to `processed/` and `failed/` with the reason, so nothing dropped
  vanishes without a record.
- Mechanically: feature 1's enumeration and worker path, plus a watcher (polling, not OS events,
  for network shares) and a "remove source after commit" option.

## 10. Open questions

- **Large enumerations**: synchronous `local-sources` is fine at a few seconds; measure on the
  real library (natively on Windows, not over WSL's `/mnt/d`, which is minutes) before deciding
  whether it needs to be a background step.
- **Re-import cost**: every file is hashed again (one full read). Matching path + size + mtime
  against earlier local imports would make re-importing a grown library near-instant.
- **Mixed drops** (some items without a disk path) fall back to upload for the whole drop. Revisit
  only if it happens in practice.
