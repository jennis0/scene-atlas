# Export, import and rebuild

**Status:** Design, sixth draft (2026-10-31). Not started. Three reviews shaped it; earlier drafts were bigger and are superseded.
**Target:** 0.2.0.

## 1. Scope

User decisions (2026-10-31): these five capabilities, nothing more.

1. **Export metadata.** A manual export of the whole library's metadata to one file ([§4](#4-export-metadata)). This is the "backup".
2. **Export groups with their metadata.** A download of selected groups or images as a zip, with the metadata in it ([§5](#5-export-groups)).
3. **Recognise the format on import.** A zip or folder holding the metadata imports with it, quickly and through the normal importer ([§6](#6-import)).
4. **Rebuild the library from a metadata export**, at startup ([§8](#8-rebuild)).
5. **Export the whole library** as a folder of readable files plus the metadata, so users aren't locked in ([§7](#7-full-library-export)).

Downloads, the full export and rebuild's set-aside folder all write the same **readable layout** ([§3](#3-the-readable-layout)), and the importer recognises it.

Out of scope:

- **Scheduled backups.** None, and the old daily SQLite/LanceDB copy has been removed (user decision 2026-10-31). Pre-migration snapshots stay: they roll back an app update.
- **Originals.** They are never in a metadata export. They belong to the user's own backup of the store folder, which is plain files.
- **Full-library zip download.** Today's Settings → **Export library** downloads one zip into a browser `Blob` and fails beyond a few GB. It is replaced by the folder export ([§7](#7-full-library-export)); 1 TB doesn't go through a browser.
- **Hard links** in exports (rejected 2026-10-31): an editor that saves in place would silently change the original. Exports copy.
- **Applying metadata to images already in the library** on import, and LanceDB compaction.

**Move library** is also in 0.2.0 (user decision 2026-10-31, confirming 2026-10-19), and shares the copy step with the folder writer ([§10](#10-move-library)).

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

- `kind` is `library` (a metadata export, [§4](#4-export-metadata)) or `groups` (beside files: a download, a full export or a set-aside folder).
- `settings` (every `app_settings` row) is in `library` files only.
- `version` is `major.minor`: a reader refuses an unknown major and ignores fields it doesn't know.

**Group lines**, one per group, with its images:

```json
{"group": {"id": 812, "uid": "8f1c…", "base_name": "Golden Forest", "author": "Czepeku", "created_at": "…", "primary": 0},
 "images": [
   {"id": 40321, "filename": "Golden Forest Day 30x30.webp", "name": "Day", "author": "Czepeku", "subgroup": null,
    "image_type": "battlemap", "media_type": "image", "created_at": "…",
    "width": 3000, "height": 3000, "file_size": 41234567,
    "grid": {"gridded": true, "type": "square", "width": 30, "height": 30, "confidence": 0.97, "source": "user"},
    "tags": [{"category": "season", "value": "summer", "source": "manual", "confidence": 1.0}],
    "missing_since": null,
    "stored_hash": "…", "content_hash": "…", "pixel_hash": "…", "phash": 123, "colors": [["#2f4a1c", 0.31]],
    "vector": "<base64 float32>",
    "path": "Czepeku_Golden Forest/Czepeku_Golden Forest_Day_G30x30[summer].webp",
    "storage_key": "3f9a….webp", "thumbnail_key": "…", "source_file_id": null}
 ]}
```

Ungrouped images are lines with `"group": null`. Images still awaiting grouping (mid-import, not listed anywhere) are left out.

| Field | In | Notes |
|---|---|---|
| `id` (image and group) | `library` | The ids in the source database. A rebuild inserts with the same ids, so `source_files.image_id` (which can point at another image for a duplicate row), `primary_image_id` and the LanceDB ids line up with no remapping. A `groups` import ignores them. |
| `group.uid` | both | New column on image groups: a random UUID, backfilled by migration, with a unique index. Import keeps it, so a group stays the same group across downloads and libraries. |
| `primary` | both | Index of the group's primary image in `images`. |
| `path` | `groups` | The file's path, relative to the `scene-atlas.jsonl` beside it. |
| `stored_hash` | both | SHA-256 of the stored file, which is the file a download contains. It differs from `content_hash` when stored-format conversion is on. Computed while reading when NULL. |
| `vector` | both | The active model's embedding. Used by an importer whose encoder matches the header's `encoder_sha256`; otherwise ignored. |
| `storage_key`, `thumbnail_key`, `source_file_id`, `missing_since` | `library` | Where the original and thumbnail are, and the linked file's `source_files` row. |
| `colors` | both | Hex and share only. The `lab_*` columns (NOT NULL) are computed from the hex on load. |

**Other lines, `library` files only:** `{"source_files": [...]}` in batches, holding every row of the linked library with its `id`, `image_id`, state, size, mtime and hash, so removed, duplicate and sorted-out files stay that way after a rebuild.

**Reading vectors:** the metadata export and full export stream the LanceDB table once, in id order, alongside the image query; downloads (≤ 999 images) read their ids in one `id IN (…)` query. Neither uses `get_embeddings` as it is, because it swallows errors and returns `{}`: a read error fails the export rather than silently leaving vectors out. No scalar index is needed.

## 3. The readable layout

User decision (2026-10-31). One function, `pipeline/naming.py:readable_path`, used by every writer of files.

```
Czepeku_Golden Forest/
  Czepeku_Golden Forest_Day_G30x30[summer,forest].webp
  Czepeku_Golden Forest_Night_GL[summer,forest].webp
  Czepeku_Golden Forest_Winter_Day_G30x30[winter].webp     subgroup "Winter"
Czepeku_Lone Tavern_HG20x15[urban].png                     a group of one, at the top level
Tom Cartos_Harbour_G.jpg                                   gridded, size unknown
scene-atlas.jsonl
```

- **Folders:** one per group of two or more images, named `Author_Group`. Groups of one and ungrouped images sit at the top level. There is no author level.
- **File names:** `Author_Group_[Subgroup_]Name_Grid[tags].ext`.
  - A missing author or subgroup is left out, not written as "Unknown".
  - A name equal to its group's name isn't repeated (`Czepeku_Lone Tavern_…`).
- **Grid:**
  - `G<w>x<h>` for a square grid and `HG<w>x<h>` for a hex grid; just `G` or `HG` when the size isn't known.
  - `GL` for gridless.
  - Nothing when it isn't known whether there is a grid (most scenes).
- **Length:** folder names are capped at 80 characters. Tags are values only, comma-separated with no spaces, in category order; they are dropped from the end until the file name is at most 150 characters, and then the name segments are shortened (name first, then group). The desktop folder export also counts the chosen folder's own path length, so the whole path stays under Windows' 260.
- **Characters:** `sanitize_segment` replaces `/\:*?"<>|` and `_` inside a segment (with a space, so the separators stay unambiguous). It also avoids Windows reserved names (`CON`, `NUL`…) and trailing dots and spaces.
- **Collisions:** compared case-insensitively. A second group with the same folder name gets ` (2)`, in group-id order, and a second file with the same name in a folder gets ` (2)` in image-id order. A resumed export also checks the folder names already on disk, since groups can be deleted or renamed between runs.

The names are for people. The metadata lives in `scene-atlas.jsonl`, so nothing is parsed back out of them.

## 4. Export metadata

Settings → Library → **Export metadata**.

- **Desktop** writes straight to a path the user picks, as a background job.
- **Server:** `POST /api/v1/library/metadata-export` writes the file to `{data_dir}/exports/<timestamp>.jsonl.gz` in one SQLite read transaction, then streams it as an attachment and deletes it. Writing it first keeps the read transaction short, whatever the download speed. Stale files there (an aborted download) are deleted at startup.
- About 1 GB at 200k images (mostly vectors), and a few minutes.
- The server download uses the mechanism in [§5.2](#52-the-download-mechanism).
- The UI says what it is: names, groups, tags, grids and search data, **not the image files**, and that rebuilding needs the store folder too.

## 5. Export groups

### 5.1 The endpoint

```
POST /api/v1/downloads/check  JSON {group_ids, image_ids}  → {image_count, bytes, ok, reason}
POST /api/v1/downloads        form: group_ids, image_ids (comma-separated)  → zip attachment
```

- **One endpoint** for every download of files: multi-select in the gallery and group view, the group card's Download (replacing `api/groups.py`'s zip), and the image viewer's single file. The old `GET /export/library`, `download.ts:downloadFile`, and `naming.download_filename` with its frontend mirror `buildDownloadFilename` go.
- **The zip** is `ZIP_STORED`, streamed with `zipstream-ng` (sized, zip64): `scene-atlas.jsonl` (`kind: groups`) first, then the files in the readable layout ([§3](#3-the-readable-layout)).
- **Limits:** at most 999 files, and 2 GiB minus the size of `scene-atlas.jsonl` (`check_zip_safety` counts it against `max_import_total_size`), so any download re-imports as a zip under the default import limits. `check` refuses larger selections with the reason; the UI shows count and size first. A single file over 2 GB is downloaded alone as a plain file, without metadata.
- **Linked-library images** are included: the user asked for those files.
- **Missing originals** are left out, logged, and absent from the metadata.

### 5.2 The download mechanism

- `check` runs first (JSON), so limits and errors show in the app. Then a hidden `<form method="post">` is submitted. An attachment response doesn't navigate the page, and the browser streams it straight to disk with its own progress. Nothing is held server-side between the two requests.
- **Cross-site requests are refused:** a form POST is a simple request any site can send, so `/downloads` and `/library/metadata-export` require `Sec-Fetch-Site: same-origin`, or `Origin` matching `Host` where that header is absent.
- `X-Accel-Buffering: no` is set, so nginx doesn't spool the stream to disk.
- **Electron** gets a `will-download` handler: a save dialog, then progress in the activity dock. It has no download UI of its own.

## 6. Import

### 6.1 Recognising the format

| Source | Where the metadata is |
|---|---|
| Zip (web upload or local) | A root `scene-atlas.jsonl` member, read by `expand_archive` |
| Local folder (desktop) | `scene-atlas.jsonl` in a picked root, read by `ingest_local` |
| Browser folder upload | The client uploads `scene-atlas.jsonl` as the job's first item; prepare holds the job's other items until it has arrived. This is the zip and local code path, with no parsing in the browser. |

- The entries are stored with the job (a table keyed by job and `stored_hash`).
- `scene-atlas.jsonl` itself is never listed as a skipped file (`kind_for_path` would call it unsupported).
- 0.1.x `metadata.json` exports are not recognised.
- A file that doesn't validate, or has an unknown major version, is ignored with a note in the import report; the files import normally. **Metadata never fails an import.**
- A `library` file dropped into an import is not a rebuild. Its entries are used like a `groups` file's, matched against whatever files are imported.

The file is untrusted input: string lengths, tag rules and grid ranges are validated, and nothing in it is used as a filesystem path.

### 6.2 Applying it

- **Matching happens once, in prepare**, when the item's hash is known (uploads and zip members already carry `source_hash`; local imports hash there). Matching is by hash. A hash with several entries takes the one whose path matches (for a zip, the member's raw path inside the zip, before `place_members` rewrites it), else the first.
- **A matched item** takes its entry's type, name, author, subgroup, grid and tags. The parser's filename tags and grid are not applied, and Auto classification and grid detection are skipped. The vector is used if the encoder matches, so the image isn't embedded. Thumbnails, colours and hashes are made as usual: the file is new to this library. Stored-format conversion is skipped when the file is already in the target format, so lossy files don't lose quality on each round trip.
- **Groups** are placed in the grouping phase, as for every import ([ingestion.md §5.8](ingestion.md#58-identifying-groups)). Matched images are grouped by `uid`, joining the library's group with that `uid` if there is one (`merged_into_existing`), else a new group with the entry's name and author. The lookup runs inside the grouping write session, so two imports of the same group can't both mint it. Unmatched images go through the tree walk. `ImportGroup` rows are created as today, so the report, review and Undo are unchanged.
- **Duplicates** are skipped as usual, and their metadata is not applied. Re-importing a download into the library it came from changes nothing.

## 7. Full library export

Settings → Library → **Export library**: a folder of readable files plus `scene-atlas.jsonl`. It works outside Scene Atlas, and it re-imports with everything.

- **Where it writes:**
  - Desktop: a folder the user picks (refused if it's inside the linked library or the library's own folders).
  - Server: `{SCENE_ATLAS_IMAGES_DIR}/exports/<timestamp>/`. That's the images mount, which the admin can already reach on the host, so there's nothing new to configure. Settings shows the path, and the free space against the export's size, before starting.
- **A background job** in the activity dock: the **folder writer** (`pipeline/folder_writer.py`), which writes chosen images in the readable layout.
  - Groups go in id order; each group's files are written, then its line is appended to `scene-atlas.jsonl`, so the metadata is never ahead of the files.
  - Each file is copied to `<name>.part` with an inline SHA-256, checked against `stored_hash`, then renamed.
  - **Resume:** a run into an unfinished export's folder reads its `scene-atlas.jsonl` and carries on after the last group listed.
  - **Free space** is checked before each group. Too little fails the job with its progress kept; running it again resumes.
  - **Per-file problems** (an unreadable original, a name the target refuses) are skipped and listed at the end. A full or failing disk stops the job.
- **Linked-library images** are included, with a checkbox to leave them out: the user has those files already.
- **Expect** disk speed: hours for 1 TB.

The CLI (`python -m backend.pipeline.export_library <dir>`) runs the same job.

## 8. Rebuild

Replaces the library's metadata with a `library` file. The user decided the flow (2026-10-31): **Settings → Library → Rebuild from export**, upload, see what will change, confirm, and the app restarts into the rebuilt library. Nothing is merged.

The rule throughout: **nothing is changed until everything that can be checked has been, and any failure puts the library back as it was.**

### 8.1 Upload

The file is staged at `{data_dir}/rebuild/staged.jsonl.gz` in both modes, so the rebuild never depends on a drive that can be unplugged.

- **Server:** uploaded in 8 MB chunks (`PUT /api/v1/library/rebuild/upload?offset=…`), so it passes proxy body limits; nginx's 1 MB default still needs raising to 8 MB, which the server docs say. A gap or overlap is rejected.
- **Desktop:** the picked file is copied there.

A new upload replaces the staged one.

### 8.2 Check before anything changes

`POST /api/v1/library/rebuild/check` reads the staged file once, streaming, and changes nothing:

- **Every line is validated**, not just the header, so loading at restart can't fail on content. A file that doesn't validate, or has an unknown major version, is refused with the line it failed on.
- **From another library** is allowed (user decision 2026-10-31), with a warning: "This export is from a different library." The rebuilt library keeps this store's `library_id`. The counts below are what protect against the wrong file: one from elsewhere shows nearly everything missing.
- **Missing:** images in the file whose original isn't there (`stat` of the store key; linked files are only checked when the linked folder is online). Stored images that are missing won't be in the rebuilt library. Missing linked images are kept, marked missing, as a scan would mark them.
- **Will be lost:** images in the current library that aren't in the file, matched by `storage_key`, or by `source_files` key for linked images. Their metadata goes. Their files are kept in a readable folder ([§8.3](#83-at-restart), stage 3). Linked ones are imported again by the next scan, with fresh metadata; the dialog says so.
- **Refused while an import is running**, since its images would be set aside without being counted.
- **Vectors:** if the file's `encoder_sha256` doesn't match the installed model, the dialog says the library will be re-embedded after the rebuild (hours for a large library).

The dialog shows: "**7 images in 3 groups are missing.** 3 images in 1 group in your current library will be lost." Each sentence has a disclosure listing groups, each expandable to its image names. Lists are capped at 500 groups in the response (with "and 12 more"). With nothing missing or lost, it says so. **Rebuild** and **Cancel**; Cancel deletes the staged file.

### 8.3 At restart

On **Rebuild**, the backend writes `{data_dir}/rebuild/pending.json` (a rebuild id, the staged file's SHA-256, the check's missing count, `attempts: 0`) and restarts: the in-window backend restart on desktop; on a server it exits and the Compose `restart: unless-stopped` policy brings it back (the docs cover `docker run` without one). The swap needs the database and LanceDB closed, which is why it happens at startup.

`backend/app/library_rebuild.py` runs in the lifespan after the storage locks and after `check_library`, before `init_db`. It goes ahead only when the library check opened the library (or found app data missing, [§8.4](#84-when-app-data-is-lost)).

0. **Pre-flight**, changing nothing. The staged file's SHA-256 must match `pending.json`. The store, and the linked folder if one is configured, must be reachable. If any check fails, the rebuild is cancelled: `pending.json` is removed, and the reason is recorded for Settings to show. `attempts` is incremented; after two crashed attempts, the rebuild is rolled back instead of tried again.
1. **Move the current metadata aside** to `rebuild/old-<id>/`: `battlemap.db` with its `-wal` and `-shm`, then the LanceDB folder. Each item is moved only if it is still at the source and not yet at the destination, so a re-run after a crash continues rather than overwrites.
2. **Load the file** into a fresh database (`init_db`):
   - Settings come from the file, except `library_id`, `active_model` and the setup flag, which stay this install's.
   - Then the tag categories, a `library_sources` row for this install's linked folder (`detached` if none is configured), `source_files`, groups, images, tags and colours, inserted with their ids in batches of about 1,000 per transaction.
   - `pending` `source_files` rows are written as `pending`, so the next scan queues them again.
   - Vectors are loaded into the active model's table only when `encoder_sha256` matches the installed encoder.
   - Missing stored originals are left out. If more are missing than the check counted, the rebuild rolls back, because a folder has probably gone offline.
3. **Set aside** store files (shard layout only, so `backups/` and `exports/` are untouched) that the file doesn't reference. They go to `{store}/not-in-backup/<timestamp>/` in the readable layout, named from the database in `old-<id>/`:
   - The folder's `scene-atlas.jsonl` is written **first**, including each file's `storage_key`. It is the move log: re-running continues from it, and a rollback reverses it exactly. It also means importing the folder brings the images back with their groups, tags and grids.
   - Each file is moved by rename, on the same volume, with no hashing. A file counts as moved when it is at the destination and gone from the source.
   - Their thumbnails move into `old-<id>/thumbnails/`, so the orphan sweep doesn't delete them.
   - Store files the old database didn't know either go to `unknown/` under their store names.
4. **Finish:** delete `pending.json`, the staged file and any earlier `old-*` folders, and record a summary (loaded, missing, set aside) that Settings shows once. Startup continues with `init_db`, which finds the database at head.

**Rollback** is automatic. If stage 1, 2 or 3 raises, or after two crashed attempts:
- stage 3's moves are reversed from the move log;
- the new database and LanceDB are deleted;
- `old-<id>/` is moved back;
- `pending.json` is removed, and the error is recorded for Settings to show.

The library is then exactly as it was.

**Progress:** the backend prints `SCENE_ATLAS_STATUS rebuild <done>/<total>` lines (a new protocol). Electron's loading page shows "Rebuilding your library… 41%", and Electron's start-up wait (`waitForHealth`, 120 s today) is extended while status lines keep arriving. In server mode `/health` doesn't answer until the step is done, so the UI shows "Rebuilding your library…" with no percentage. A few minutes at 200k images: nothing is decoded, and nothing is embedded when the encoder matches.

**After startup:**
- **Missing thumbnails** (app data was lost) are rebuilt from the originals by a new backfill job (`write_thumbnails` runs only in ingest today). This is the slow part, and it only happens in that case.
- **Vector reconciliation**, after that backfill, embeds images without a vector: all of them when the encoder didn't match.

### 8.4 When app data is lost

This is the main reason to rebuild. In this case the app refuses to open the store (`APP_DATA_NOT_HERE`, [library-setup.md](library-setup.md)), so Settings can't be reached.

- **Desktop:** the refusal page offers **Rebuild from export…**. The backend exits with a code of its own for this refusal (today every refusal is 4), so Electron can tell it apart. Electron copies the picked file to `rebuild/staged.jsonl.gz`, writes `pending.json`, and starts the backend.
- **Server:** the refusal message says to place the file at `{data_dir}/rebuild/pending.jsonl.gz` and restart. That file is honoured only when there is no database, so a stray copy can never replace a working library.

There is no check step in this case: there's no current library to lose. Pre-flight, rollback and the summary still apply. Store files the export doesn't list have no metadata to name them by, so they go to `not-in-backup/<timestamp>/unknown/`.

## 9. Testing

- **Readable layout:** unit tests for names (grid codes, tag truncation at 150 characters, reserved names, case-insensitive collisions, groups of one).
- **Full export:** export a fixture library, kill it part-way and resume, then import the folder into an empty library and compare.
- **Round trip:** download fixture groups and import into an empty library, then compare name, author, group, subgroup, type, grid, tags and vector image by image. Also: two downloads of one group imported concurrently, and the same download imported twice.
- **Rebuild:**
  - Export metadata, change the library (edits, deletes, a new import, a linked file removed), check that the counts and lists match, rebuild, and compare with the export.
  - Again with app data deleted ([§8.4](#84-when-app-data-is-lost)).
  - A kill at each stage of §8.3, then a restart (continues); two kills (rolls back).
  - A failure at each stage rolls back to exactly the previous library, set-aside files included.
  - The store or linked folder offline at restart cancels the rebuild without changes.
  - A staged file changed after the check is refused.
  - Another library's file rebuilds, with the warning, and keeps the store's `library_id`.
  - The set-aside folder re-imports with its metadata.
  - A chunked upload with a gap or an overlap is rejected.
  - The vectors are kept when the encoder matches, and re-embedded when it doesn't.
- **Security:** a cross-site form POST is refused, and a manifest with oversized or hostile values is rejected without failing the import.
- **Scale:** 200k synthetic rows with vectors (`scripts/dev/make_large_library.py`): export time, size and memory; rebuild time. Record the numbers here.

## 10. Move library

In 0.2.0 (user decision 2026-10-31). The minimal design:

1. **Copy while the app runs:** the store, thumbnails and models. All three are add-and-delete only, never rewritten in place. This is a background job, using the folder writer's copy step ([§7](#7-full-library-export)): an inline hash checked against `stored_hash`, resumable, and with a marker written into the target first so linked scans skip it.
2. **On confirm**, Electron saves the new paths plus `pendingMove: {from}` and restarts.
3. **At startup**, the backend (before `check_library`) copies what changed since step 1 and the database (with `-wal`/`-shm`) and LanceDB from the old folders, then verifies that every row's files exist. On failure it exits with a distinct code, and Electron reverts to the old paths.
4. The old folder's marker becomes a tombstone (`moved_to`), and Settings offers to delete the old copy.

Desktop only: in server mode the folders are mounts, and the docs say how to move them.

## 11. Order of work

1. The format (writer, reader, validation), the readable layout, group `uid`.
2. Export metadata.
3. Export groups: the endpoint, `check`, the download mechanism and the Electron handler. The old endpoints go.
4. Import recognition.
5. The folder writer and full library export.
6. Rebuild, with set-aside on the folder writer.
7. Move library.
