# Export, backup and moving a library

**Status:** Design, second draft (2026-10-30). Not started. The first draft was reviewed and rejected; this one replaces it.
**Roadmap rows:** Move library, Export doesn't scale, Validate backup and export at scale, Backups as a feature, LanceDB is never compacted ([status-and-roadmap.md](status-and-roadmap.md)).

Getting a library out (download, export), back in (re-import), protected (backup, restore) and moved (Move library), at up to about 1 TB / 200k images, on desktop and server.

## 1. Decisions

User decisions (2026-10-30):

1. **Backups never hold originals.** The button says **Backup metadata**. Originals are for the user's own backup tool.
2. **Backup works in server mode** as a download, not only on desktop.
3. **One download endpoint** takes image and group ids. Bulk downloads and full exports are both built on it, and server mode exports only through it.
4. **An export re-imports fully, recognised by the normal importer.** There's no special route.
5. **One format, a JSONL line per group** ([§2](#2-the-format)), for exports and backups alike.
6. **Restore wipes the library and rebuilds it from the backup.** Nothing is merged.
7. **Move library is due before launch.** Keep the design minimal.

Consequences:

- **Restore is an import.** It is a wipe, then an import of the backup that adopts the files already in the store ([§6](#6-restore)). There's no SQLite file swap and no second format.
- **Re-import is for sharing or leaving, not for moving 1 TB.** Re-importing redoes decoding and thumbnails. Moving a library is Move library, or copying both folders and reopening ([library-setup.md](library-setup.md)).
- **One startup step** ("pending library operation") runs restore and the last stage of Move library before the library check, with nothing open ([§8](#8-the-startup-step)).

## 2. The format

`scene-atlas.jsonl`, UTF-8, one JSON object per line.

**Line 1, the header:**

```json
{"format": "scene-atlas", "version": "2.0", "kind": "export", "app_version": "0.2.0",
 "library_id": "…", "created_at": "2026-10-30T12:00:00Z",
 "model": {"name": "large", "encoder_sha256": "…", "dim": 1024},
 "tag_categories": [{"name": "season", "description": "…", "color": "sky", "icon": "snowflake", "common_values": ["winter"]}]}
```

`kind` is `export` (files alongside) or `backup` (no files). `version` is `major.minor`. A reader refuses an unknown major and ignores fields it doesn't know.

**Every other line is one group with its files:**

```json
{"group": {"uid": "8f1c…", "base_name": "Golden Forest", "author": "Czepeku"},
 "files": [
   {"path": "Czepeku/Golden Forest/Golden Forest - Day - Grid 30x30.webp",
    "sha256": "…", "size": 41234567,
    "name": "Day", "subgroup": null, "image_type": "battlemap", "media_type": "image",
    "grid": {"gridded": true, "type": "square", "width": 30, "height": 30, "source": "user"},
    "tags": [{"category": "season", "value": "summer", "source": "manual", "confidence": 1.0}],
    "vector": "<base64 float32>",
    "storage_key": "3f9a….webp", "thumbnail_key": "…", "linked_path": null}
 ]}
```

- **`group.uid`** is a new random UUID column on image groups (migration; backfilled for existing groups). Import keeps it, so a group stays the same group across libraries and parts. Ungrouped images are lines with `"group": null`.
- **`sha256`** is the hash of the bytes written: `stored_hash`, computed while copying when the column is NULL. That's the stored file, which may differ from the original upload when stored-format conversion is on.
- **`vector`** is the active model's embedding. An importer whose encoder matches `encoder_sha256` uses it and skips embedding; otherwise it re-embeds. About 5.5 KB per image for the large model.
- **Backup-only fields:** `storage_key`, `thumbnail_key` and `linked_path` (the file's path in the linked library). Exports leave them out.
- **Exports leave out linked-library images** by default. The user already has those files; a checkbox includes them.
- **Files keep the readable layout** (`Author/Group/[Subgroup/]Group - [Subgroup - ]Name - Grid WxH.ext`), so an export is useful outside Scene Atlas. `unique_export_path` is changed to de-duplicate case-insensitively, and `sanitize_segment` to avoid Windows reserved names and trailing dots.
- **One group can span several lines.** A group too big for one part ([§4](#4-full-export)) appears in each part with the same `uid`, carrying only that part's files.

Streaming: the writer emits a line per group from a keyset query, and the reader applies a line at a time. Nothing holds the whole file in memory. At 200k images the file is about 1.1 GB (mostly vectors).

## 3. Downloads

```
POST /api/v1/downloads   (form fields: image_ids, group_ids, include_metadata)
  → 200 application/zip, Content-Disposition: attachment, Content-Length
```

- **A form POST is a native download.** The frontend submits a hidden `<form method="post">`, and the browser writes the response straight to disk with its own progress. There are no tokens and nothing kept server-side. A form also means an error page can't replace the app: the form targets a hidden iframe.
- **The zip** is `ZIP_STORED` and streamed with `zipstream-ng` (sized, zip64). `scene-atlas.jsonl` comes first when `include_metadata` is set, then the files.
- **Limit:** one request covers at most 50k images and `download_max_bytes` (default 8 GB). A larger one is refused before streaming starts, with advice to use Export. A single HTTP download can't resume, so a cap keeps failures cheap.
- **Missing originals** are left out and logged; the zip still completes.
- `X-Accel-Buffering: no` is set, so nginx doesn't spool the stream to disk.
- **Electron** gets a `will-download` handler that saves where the user picks and reports progress to the activity dock. Without one there's a save dialog and then no progress at all.
- **Replaced:** `GET /api/v1/export/library`, the group zip endpoint (`api/groups.py`) and `frontend/src/lib/download.ts:downloadFile`, which downloads into a `Blob`. The image viewer's single-file download becomes a plain link to the original.

UI: multi-select in the gallery and group view gets **Download** (count and size shown first). The group card menu's Download uses the same endpoint.

## 4. Full export

Settings → Library → **Export library** lists parts. Each part is a form POST like a download, carrying a range instead of ids:

```
GET  /api/v1/export/parts?part_bytes=2000000000  → [{index, start, end, image_count, bytes}]
POST /api/v1/export/part  (start, end)            → zip
```

- **A part is a range in `(group id, image id)` order**, packed up to `part_bytes`. Ungrouped images sort last. A group bigger than a part is split between parts at a file boundary ([§2](#2-the-format)).
- **Stateless.** Ranges are recomputed on each visit; a part is defined only by its range, so it survives restarts. Images added later fall into later ranges. A part fetched twice may differ if the library changed in between, which is harmless: re-import skips duplicates.
- **Default 2 GB, 999 files per part**, under the default zip import limits (1000 files including the manifest, 2 GB). The part's `scene-atlas.jsonl` and zip overhead are counted.
- **On desktop** Export library writes a folder instead ([§5](#5-desktop-folder-export)). Zip parts remain available there.

1 TB at 2 GB is about 500 parts, so it isn't a practical way to move a whole large library through a browser. The server docs say so, and give the alternative: copy the store folder and take a metadata backup.

## 5. Desktop folder export

A background job (JobRunner, shown in the activity dock) writes the export into a folder the user picks:

- `scene-atlas.jsonl` is written as the job goes, a line per group after that group's files are written, so it is never ahead of the files.
- **Resume:** a run into the folder of an unfinished export reads its `scene-atlas.jsonl`, skips the groups already listed and carries on. It continues with the same file names, because suffixes like ` (2)` are planned per group, not across the export.
- **Copying** uses the transfer engine ([§9](#9-the-transfer-engine)).
- **Refused targets:** inside the linked folder, or inside the library's own folders.

The CLI (`python -m backend.pipeline.export_library`) runs the same function.

## 6. Restore

### 6.1 Backup

**Backup metadata** writes `scene-atlas-backup-<timestamp>.jsonl` (`kind: backup`), gzipped. At 200k images that's about 1 GB.

- **Desktop:** to a folder the user picks, as a background job. Settings warns if the folder is on the store's disk.
- **Server:** a form POST download (`POST /api/v1/backup`), so it can't be triggered cross-site by an `<img>`. It is rate-limited as expensive.
- **The daily backup** writes the same file into `{SCENE_ATLAS_DATA_DIR}/backups/` and keeps the last 7. It replaces today's SQLite-plus-LanceDB copies in the store. Those sit on the same disk as the originals, keep up to 11 full copies of every model's vectors, and hold the LanceDB lock while copying.
- **Consistency:** the writer reads in one SQLite read transaction (a snapshot), and reads vectors by id for each group as it goes. A vector missing at that moment is left out, and restore re-embeds that image.
- **Pre-migration snapshots** (SQLite, before an upgrade) are unchanged. They roll back an update, which is a different job.

### 6.2 Restore

Restoring makes the library exactly what the backup describes. Nothing in the current library survives except originals, which are kept but set aside.

1. **Stage.** The user picks or uploads a backup. The backend checks the header (format, a `major` it reads, the same `library_id` as this store's marker; another library's backup is refused) and writes it to `{data_dir}/restore/pending.jsonl.gz`. Then it restarts:
   - desktop: the in-window backend restart;
   - server: the process exits and the Compose `restart: unless-stopped` policy brings it back.
2. **At startup** ([§8](#8-the-startup-step)):
   1. Write a backup of the current library to `restore/before-restore.jsonl.gz`, unless there is no database.
   2. Delete the database (with its `-wal` and `-shm` files) and drop every LanceDB table.
   3. Create an empty database at the current schema. The library ID comes from the store marker.
   4. Queue a **restore job** from the file.
3. **The restore job** is an ordinary import job with one new item kind, **adopt**: a file already in the store, committed with its `storage_key` rather than copied, like a linked item is read in place.
   - Each file's name, type, grid, tags and group come from its line. No Auto classification, grid detection or grouping phase runs.
   - Its vector is written from the line when the encoder matches; otherwise it is embedded as usual.
   - Its thumbnail is reused if the file at `thumbnail_key` exists; otherwise it is made from the original. Colours, hashes and grouping features are recomputed. That costs a decode per image: minutes when app data survived, hours for 1 TB when it didn't.
   - Linked files are matched by `linked_path` in the linked library.
   - A file whose original is missing fails with "Original not found".
   - A crash is resumed as any import is.
4. **Store files not in the backup** (imported after it) are moved to `{store}/not-in-backup/` before the orphan sweep can see them. The import report lists the count, and they can be imported like any folder. They return without their metadata, which the backup didn't have.

**Entry points.** Settings → Library → **Restore metadata…**. When the app refuses to open a store because its app data is missing ([library-setup.md](library-setup.md), `APP_DATA_NOT_HERE`), the loading page and wizard offer **Restore from a metadata backup…**. In server mode the refusal message says to place the backup at `{data_dir}/restore/pending.jsonl.gz` and restart.

**Security.** Server mode has no authentication, so anyone who can reach it can already purge the library. Restore is no worse: the file is data, not a database, and it's validated line by line (string lengths, tag rules, grid ranges, `storage_key` matching the store's key pattern, `linked_path` contained by the linked folder).

## 7. Re-import

An export (`kind: export`) is recognised wherever files reach the importer:

| Source | How |
|---|---|
| Zip (web upload or local) | `expand_archive` finds a root `scene-atlas.jsonl` member |
| Local folder (desktop) | `ingest_local` finds it in a picked root |
| Browser folder upload | The client finds it in the picked folder and sends it (`PUT /imports/{id}/export-manifest`) before the manifest and seal |

For server mode the browser-folder route is the one to document: a large zip upload is one request, and proxies limit request bodies (nginx 1 MB, Cloudflare 100 MB by default).

The manifest is stored per job (in the job's staging folder) and indexed by `(path, sha256)` in a small table. A manifest that fails validation is ignored, with a note in the report. **It never fails the import.**

- **Matching** happens when an item's authoritative hash is known: on receipt for uploads, after hashing in prepare for local imports, at expansion for zips. A match is by path and hash, then by hash alone (so renamed folders still match). Several files with one hash take their entries in path order; the extras are imported as copies.
- **A matched item** gets its entry's fixed type, grid, name, subgroup and tags. The parser's filename tags and grid are not applied. Auto classification and grid detection are skipped.
- **Groups** are placed in the grouping phase, as for any import ([ingestion.md §5.8](ingestion.md#58-identifying-groups)): matched images are grouped by `uid`, joining the library's group with that `uid` if one exists, else a new one. Unmatched images go through the tree walk. Both create `ImportGroup` rows as today, so the report, review and Undo work unchanged.
- **Vectors** from the export are used when the encoder matches.
- **Duplicates** are skipped as usual, so re-importing an export into its own library is a no-op. Their metadata is not applied.

## 8. The startup step

`backend/app/library_ops.py`: a pending operation recorded as a file in `{data_dir}/pending-op.json`, run in the lifespan after the storage locks and **before** `check_library`, with no database session or LanceDB connection open:

- **restore** ([§6.2](#62-restore)), and the **finish** stage of Move library ([§10](#10-move-library)).
- It writes `in-progress` before changing anything. If that marker is found at the next start, the step is run again: both operations are written to be re-runnable.
- Electron and the loading page show "Restoring your library…" or "Finishing the move…" while it runs.

## 9. The transfer engine

`backend/pipeline/file_transfer.py`, used by the folder export and Move library:

- Copies each file to `<target>.part` while hashing what it reads, compares the hash with the expected one where there is one, `fsync`s, then renames. Hashing on the read side catches a bad source and costs nothing next to disk speed.
- **Resume:** a target that exists with the expected size and hash is skipped.
- **Free space** is checked before starting and every 1 GB. Too little fails the job with its progress kept, and running it again resumes.
- **Per-file errors** (unreadable source, name too long, a name or size the target filesystem refuses) are recorded and skipped, and reported at the end. A full or failing disk stops the job.
- **Stop** is checked between files.

## 10. Move library

**Desktop only.** In server mode the folders are mounts; the server docs explain how to move them (stop, move, update the mounts, start).

Settings → Storage locations → **Move…**, for the store, app data, or both:

1. **Check** the target: empty, not the linked folder or inside it, not containing it, enough free space. Write a **move marker** into the target first, so linked scans skip it ([library-setup.md §1](library-setup.md#1-storage-model)).
2. **Copy the store while the app runs.** Store files are only ever added and deleted, never changed (uuid names), so a live copy is safe. This is the terabyte; it's a resumable background job on the transfer engine, verified against `stored_hash` (size only when NULL).
3. **Finish at restart** (a startup step, [§8](#8-the-startup-step)), with the backend's files closed:
   - copy store files added since step 2, and delete from the target any that were deleted since;
   - copy app data (database with `-wal`/`-shm`, LanceDB, thumbnails, models; not logs or staging);
   - verify that every row's store file and thumbnail exists in the target;
   - Electron writes the new paths to its config and the backend opens there. If it refuses, Electron reverts to the old paths.
4. **The old copy's marker** becomes a tombstone (`moved_to`), so it can't be reopened as the same library. Settings offers to delete the old copy ("Delete the old copy (812 GB)?") once the new place has opened.

Imports with staged bytes block a move of app data ("Finish or cancel open imports first"), as purge does.

## 11. LanceDB compaction

Nothing compacts LanceDB today, so every write batch adds a fragment and a version. Daily maintenance runs `optimize()` (compaction, then `cleanup_old_versions` older than a day) on each table once the ingest queue has been idle for 10 minutes. It doesn't run at the same time as a backup.

## 12. Testing

- **Round trip:** export a fixture library (parts and folder), import into an empty library, and compare every image's name, author, group, subgroup, type, grid, tags and vector. Parts are imported in shuffled order, and one part twice.
- **Restore:** back up, change the library (edits, deletes, a new import), restore, and compare with the backup. Then do the same again with app data deleted.
- **Fault injection** in the transfer engine and the startup step (a kill mid-file, mid-restore, mid-finish, then a restart).
- **Scale** (`scripts/dev/make_large_library.py`, 200k rows with vectors and small real files): backup time and size, restore time with thumbnails kept, export part listing, download memory, compaction time. These numbers are recorded here.

## 13. Order of work

One PR each:

1. LanceDB compaction, and the scale fixture.
2. The format (writer and reader) and group `uid`.
3. Downloads and export parts. The old endpoints and the `Blob` download go.
4. Re-import.
5. Backup and restore, with the startup step and the adopt item kind.
6. The transfer engine, desktop folder export and Move library.

## 14. Open questions

- **Release scope.** All six steps before 0.2.0, or 0.2.0 with Move library only (needing steps 6 and the startup step) and the rest in 0.3.0?
