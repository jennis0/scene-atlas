# Export, import and rebuild of library metadata

**Status:** Design, third draft (2026-10-31). Not started. Two reviews shaped it; earlier drafts were bigger and are superseded.
**Target:** 0.2.0.

## 1. Scope

User decision (2026-10-31): four capabilities, nothing more.

1. **Export metadata.** A manual export of the whole library's metadata to one file ([§3](#3-export-metadata)). This is the "backup".
2. **Export groups with their metadata.** A download of selected groups or images as a zip, with the metadata in it ([§4](#4-export-groups)).
3. **Recognise the format on import.** A zip or folder holding the metadata imports with it, quickly and through the normal importer ([§5](#5-import)).
4. **Rebuild the library from a metadata export**, at startup ([§6](#6-rebuild)).

Out of scope:

- **Scheduled or rotated backups.** The existing daily SQLite/LanceDB copies are left as they are; their problems stay a backlog row.
- **Originals.** They are never in a metadata export. They belong to the user's own backup of the store folder, which is plain files.
- **Full-library zip export.** Settings → **Export library** is removed: it downloads into a browser `Blob` and fails beyond a few GB. Moving a whole library is Move library, or copying the folders.
- **Applying metadata to images already in the library** on import, and LanceDB compaction.

Move library is separate and its scope is open ([§8](#8-move-library-open)).

## 2. The format

`scene-atlas.jsonl`, UTF-8, one JSON object per line, streamed in both directions. A metadata export is gzipped (`.jsonl.gz`).

**Line 1, the header:**

```json
{"format": "scene-atlas", "version": "1.0", "kind": "library", "app_version": "0.2.0",
 "library_id": "…", "created_at": "…",
 "model": {"name": "large", "encoder_sha256": "…", "dim": 1024},
 "tag_categories": [{"name": "season", "description": "…", "color": "sky", "icon": "snowflake",
                     "common_values": ["winter"], "display_order": 3}],
 "settings": {"…": "…"}}
```

- `kind` is `library` (a metadata export, [§3](#3-export-metadata)) or `groups` (in a download, [§4](#4-export-groups)).
- `settings` (every `app_settings` row) is in `library` files only.
- `version` is `major.minor`: a reader refuses an unknown major and ignores fields it doesn't know.

**Group lines**, one per group, with its images:

```json
{"group": {"uid": "8f1c…", "base_name": "Golden Forest", "author": "Czepeku", "created_at": "…", "primary": 0},
 "images": [
   {"filename": "Golden Forest Day 30x30.webp", "name": "Day", "author": "Czepeku", "subgroup": null,
    "image_type": "battlemap", "media_type": "image", "created_at": "…",
    "width": 3000, "height": 3000, "file_size": 41234567,
    "grid": {"gridded": true, "type": "square", "width": 30, "height": 30, "confidence": 0.97, "source": "user"},
    "tags": [{"category": "season", "value": "summer", "source": "manual", "confidence": 1.0}],
    "stored_hash": "…", "content_hash": "…", "pixel_hash": "…", "phash": 123, "colors": [["#2f4a1c", 0.31]],
    "vector": "<base64 float32>",
    "path": "Czepeku/Golden Forest/Golden Forest - Day - Grid 30x30.webp",
    "storage_key": "3f9a….webp", "thumbnail_key": "…", "source_file": null}
 ]}
```

Ungrouped images are lines with `"group": null`.

| Field | In | Notes |
|---|---|---|
| `group.uid` | both | New column on image groups: a random UUID, backfilled by migration, with a unique index. Import keeps it, so a group stays the same group across downloads and libraries. |
| `primary` | both | Index of the group's primary image in `images`. |
| `path` | `groups` | The file's path in the zip. |
| `stored_hash` | both | SHA-256 of the stored file, which is the file a download contains. It differs from `content_hash` when stored-format conversion is on. Computed while reading when NULL. |
| `vector` | both | The active model's embedding. Used by an importer whose encoder matches the header's `encoder_sha256`; otherwise ignored. |
| `storage_key`, `thumbnail_key`, `source_file` | `library` | Where the original and thumbnail are; `source_file` is the linked file's `source_files` row (key, size, mtime, hash). |

**Other lines, `library` files only:** `{"source_files": [...]}` in batches, holding every row of the linked library, so removed and sorted-out files stay that way after a rebuild.

**Reading vectors** is batched (1,000 ids) on a new BTREE scalar index on the LanceDB `id` column. `get_embeddings` today runs `id IN (…)` with no index, a full scan per call. A read error fails the export rather than silently leaving vectors out.

## 3. Export metadata

Settings → Library → **Export metadata**.

- `POST /api/v1/library/metadata-export` writes the file to `{data_dir}/exports/<timestamp>.jsonl.gz` in one SQLite read transaction, then streams it as an attachment and deletes it. Writing it first keeps the read transaction short, whatever the download speed.
- About 1 GB at 200k images (mostly vectors), and a few minutes.
- **The download** works the same in both modes ([§4.2](#42-the-download-mechanism)): a browser save in server mode, a save dialog on desktop.
- The UI says what it is: names, groups, tags, grids and search data, **not the image files**, and that rebuilding needs the store folder too.

## 4. Export groups

### 4.1 The endpoint

```
POST /api/v1/downloads/check  JSON {group_ids, image_ids}  → {image_count, bytes, ok, reason}
POST /api/v1/downloads        form: group_ids, image_ids (comma-separated)  → zip attachment
```

- **One endpoint** for every download of files: multi-select in the gallery and group view, the group card's Download (replacing `api/groups.py`'s zip), and the image viewer's single file. The old `GET /export/library` and `download.ts:downloadFile` go.
- **The zip** is `ZIP_STORED`, streamed with `zipstream-ng` (sized, zip64): `scene-atlas.jsonl` (`kind: groups`) first, then the files in the readable layout (`Author/Group/[Subgroup/]Group - [Subgroup - ]Name - Grid WxH.ext`).
- **Paths can't collide:** two groups with the same `(author, base_name)`, compared case-insensitively, get the folder suffix ` [uid[:6]]`. File names are de-duplicated case-insensitively within a folder, and `sanitize_segment` avoids Windows reserved names and trailing dots.
- **Limits:** at most 999 files and 2 GB of files per download, so any download re-imports as a zip under the default import limits. `check` refuses larger selections with the reason; the UI shows count and size first. A single file over 2 GB is downloaded alone as a plain file, without metadata.
- **Linked-library images** are included: the user asked for those files.
- **Missing originals** are left out, logged, and absent from the metadata.

### 4.2 The download mechanism

- `check` runs first (JSON), so limits and errors show in the app. Then a hidden `<form method="post">` is submitted. An attachment response doesn't navigate the page, and the browser streams it straight to disk with its own progress. Nothing is held server-side between the two requests.
- **Cross-site requests are refused:** a form POST is a simple request any site can send, so `/downloads` and `/library/metadata-export` require `Sec-Fetch-Site: same-origin`, or `Origin` matching `Host` where that header is absent.
- `X-Accel-Buffering: no` is set, so nginx doesn't spool the stream to disk.
- **Electron** gets a `will-download` handler: a save dialog, then progress in the activity dock. It has no download UI of its own.

## 5. Import

### 5.1 Recognising the format

| Source | Where the metadata is |
|---|---|
| Zip (web upload or local) | A root `scene-atlas.jsonl` member, read by `expand_archive` |
| Local folder (desktop) | `scene-atlas.jsonl` in a picked root, read by `ingest_local` |
| Browser folder upload | The client reads `scene-atlas.jsonl` from the picked folder and attaches each image's entry to its row in the existing manifest chunks. Chunks are sized by bytes (≤ 512 KB), and vectors are left out on this route to keep requests under proxy body limits. |

- The entries are stored with the job (a table keyed by job and `stored_hash`).
- `scene-atlas.jsonl` itself is never listed as a skipped file.
- A file that doesn't validate, or has an unknown major version, is ignored with a note in the import report; the files import normally. **Metadata never fails an import.**
- A `library` file dropped into an import is not a rebuild. Its entries are used like a `groups` file's, matched against whatever files are imported.

The file is untrusted input: string lengths, tag rules and grid ranges are validated, and nothing in it is used as a filesystem path.

### 5.2 Applying it

- **Matching happens once, in prepare**, when the item's hash is known (uploads and zip members already carry `source_hash`; local imports hash there). Matching is by hash. A hash with several entries takes the one whose path matches, else the first.
- **A matched item** takes its entry's type, name, author, subgroup, grid and tags. The parser's filename tags and grid are not applied, and Auto classification and grid detection are skipped. The vector is used if the encoder matches, so the image isn't embedded. Thumbnails, colours and hashes are made as usual: the file is new to this library.
- **Groups** are placed in the grouping phase, as for every import ([ingestion.md §5.8](ingestion.md#58-identifying-groups)). Matched images are grouped by `uid`, joining the library's group with that `uid` if there is one (`merged_into_existing`), else a new group with the entry's name and author. The lookup runs inside the grouping write session, so two imports of the same group can't both mint it. Unmatched images go through the tree walk. `ImportGroup` rows are created as today, so the report, review and Undo are unchanged.
- **Duplicates** are skipped as usual, and their metadata is not applied. Re-importing a download into the library it came from changes nothing.

## 6. Rebuild

Rebuilds the library's metadata from a `library` file, at startup, by bulk load. It is not an import job, so nothing else runs while it does: no worker, no scans, no sweeps. The result is exactly what the file describes. Nothing is merged.

### 6.1 Starting one

The trigger is the file `{data_dir}/rebuild/pending.jsonl.gz`.

| Where | How |
|---|---|
| Settings → Library → **Rebuild from metadata…** (desktop) | Pick the file. The backend checks the header and copies it into place, then the in-window restart. |
| The library refusal page when app data is missing (`APP_DATA_NOT_HERE`, desktop) | **Rebuild from a metadata export…**. The backend has already exited, so Electron checks the header and copies the file, then starts the backend. |
| Server mode | Place the file and restart. Settings and the refusal message say how. There's no upload: a 1 GB upload fails behind default proxy limits, and a rebuild is rare. |

### 6.2 The startup step

`backend/app/library_rebuild.py`, run in the lifespan after the storage locks and **before** `check_library`, with no session or LanceDB connection open:

1. **Check** the header: a known major version, and a `library_id` equal to the store marker's. A file from another library is refused, and the pending file renamed `refused-…`.
2. **Keep the way back.** Export the current library's metadata to `rebuild/before-rebuild.jsonl.gz` via a temp file and rename. Skip this if that file exists (a re-run after a crash), or if there's no database.
3. **Wipe:** delete `battlemap.db` with its `-wal` and `-shm`, and drop every LanceDB table.
4. **Create** the database with the normal `init_db`, then write `settings` (including `library_id` and the setup flag) and the tag categories.
5. **Load** in batches of about 1,000 per transaction: `source_files`, groups, images, tags and colours as recorded. Each image's original is checked with a `stat` (store key, or linked file). One that's missing is left out and counted. Vectors are added to the active model's table. The table is named from `settings.active_model`, which the file restored.
6. **Set aside** store files the file doesn't reference: move them to `{store}/not-in-backup/`, so the orphan sweep never sees them. They're files imported after the export; they can be imported like any folder, without metadata.
7. **Finish:** delete `pending.jsonl.gz` and write a summary (loaded, missing originals, set aside) that Settings shows once. Then normal startup continues: `check_library` passes against the rebuilt database.

**A crash** leaves `pending.jsonl.gz` in place, so the next start runs the step again from stage 3. The way back from stage 2 is kept.

**Progress:** the backend prints `SCENE_ATLAS_STATUS rebuild <done>/<total>` lines, and Electron's loading page shows "Rebuilding your library… 41%". Expect a few minutes at 200k images: there's no decoding and no embedding.

**After startup:**
- Thumbnails that are missing (app data was lost) are rebuilt from the originals by a backfill job in the activity dock. This is the slow part, and only in that case. The gallery shows placeholders until it's done.
- The usual vector reconciliation embeds any image without a vector. It runs after the thumbnail backfill, because it embeds from thumbnails.

## 7. Testing

- **Round trip:** download fixture groups and import into an empty library, then compare name, author, group, subgroup, type, grid, tags and vector image by image. Also: two downloads of one group imported concurrently, and the same download imported twice.
- **Rebuild:**
  - Export metadata, change the library (edits, deletes, a new import, a linked file removed), rebuild, and compare with the export.
  - Again with app data deleted.
  - A kill at each stage of §6.2, then a restart.
  - Another library's file is refused.
- **Security:** a cross-site form POST is refused, and a manifest with oversized or hostile values is rejected without failing the import.
- **Scale:** 200k synthetic rows with vectors (`scripts/dev/make_large_library.py`): export time, size and memory; rebuild time. Record the numbers here.

## 8. Move library (open)

Not one of the four capabilities. Earlier user decision (2026-10-19): due before launch. If it stays in 0.2.0, the minimal design:

1. **Copy while the app runs:** the store, thumbnails and models. All three are add-and-delete only, never rewritten in place. This is a background job: copy with an inline hash checked against `stored_hash`, resumable, and with a marker written into the target first so linked scans skip it.
2. **On confirm**, Electron saves the new paths plus `pendingMove: {from}` and restarts.
3. **At startup**, the backend (before `check_library`) copies what changed since step 1 and the database (with `-wal`/`-shm`) and LanceDB from the old folders, then verifies that every row's files exist. On failure it exits with a distinct code, and Electron reverts to the old paths.
4. The old folder's marker becomes a tombstone (`moved_to`), and Settings offers to delete the old copy.

Desktop only: in server mode the folders are mounts, and the docs say how to move them.

## 9. Order of work

1. The format: writer, reader and validation; group `uid`; the LanceDB `id` index.
2. Export metadata.
3. Export groups: the endpoint, `check`, the download mechanism and the Electron handler. The old endpoints go.
4. Import recognition.
5. Rebuild.
