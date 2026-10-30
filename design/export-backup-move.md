# Export, backup and moving a library

**Status:** Design (2026-10-30). Not started.
**Roadmap rows:** Move library, Export doesn't scale, Validate backup and export at scale, Backups as a feature, LanceDB is never compacted ([status-and-roadmap.md](status-and-roadmap.md)).

Getting a library out of Scene Atlas (download, export), back in (re-import), protected (metadata backup and restore) and moved (Move library), at sizes up to about 1 TB / 200k images, in both the desktop app and server mode.

## 1. Decisions

User decisions (2026-10-30):

1. **Backups never copy originals.** A terabyte of art belongs to the user's own backup tool. Ours covers the metadata, and the button says so: **Backup metadata**.
2. **Metadata backup works in server mode**, downloaded through the browser, not only in the desktop app.
3. **One download endpoint** takes image and group ids and returns their files, optionally with metadata. Bulk downloads and full exports are both built on it.
4. **An export re-imports fully** (names, authors, groups, subgroups, types, grids, tags), and **the importer recognises an export by itself**: a zip or folder in the Scene Atlas layout goes through the normal import, with no special route or button.
5. **Move library is due before launch.**

Design decisions taken here (open to review):

- **Exports are split into parts.** The server plans the parts, and each part is an ordinary download ([§4](#4-full-export)).
- **Downloads are native browser downloads.** The browser or Electron writes them straight to disk. Today's axios `Blob` download is removed.
- **On desktop, the full export writes into a folder** as a resumable background job instead of downloading zips ([§5](#5-desktop-folder-export)).
- **Move library is desktop only.** In server mode the folders are mounts and env vars the app doesn't own; the docs say how to move them ([§8](#8-move-library)).
- **Copy, verify and resume is one engine** (`pipeline/file_transfer.py`), shared by the folder export and Move library ([§9](#9-the-transfer-engine)).

## 2. Export format v2

Today's `metadata.json` (version 1) holds per-image type, grid and tags, keyed by archive path. Name, author, group and subgroup are only implied by the folder path. That can't round-trip: names are sanitised for the filesystem, and two groups with one name collide. Version 2 replaces it.

**File:** `scene-atlas-export.json` at the root of the zip or folder. The specific name avoids picking up the `metadata.json` that some packs ship. A v1 `metadata.json` is not recognised: nobody has exported one we need to read (0.1.x was never pulled).

```jsonc
{
  "format": "scene-atlas-export",
  "version": 2,
  "app_version": "0.2.0",
  "library_id": "…",            // the source library (library_identity.py)
  "exported_at": "2026-10-30T12:00:00Z",
  "part": {"index": 3, "count": 47, "export_id": "…"},  // absent for a plain download
  "tag_categories": [            // only the categories these images use
    {"name": "season", "description": "…", "color": "sky", "icon": "snowflake", "common_values": ["winter", "…"]}
  ],
  "groups": {                    // key: the source library's group id, as a string
    "812": {"base_name": "Golden Forest", "author": "Czepeku"}
  },
  "images": [
    {
      "path": "Czepeku/Golden Forest/Golden Forest - Day - Grid 30x30.webp",
      "sha256": "…",             // content_hash: the original's bytes
      "name": "Day",
      "author": "Czepeku",
      "group": "812",            // null when ungrouped
      "subgroup": null,
      "image_type": "battlemap",
      "media_type": "image",
      "grid": {"gridded": true, "type": "square", "width": 30, "height": 30, "source": "user"},
      "tags": [{"category": "season", "value": "summer", "source": "manual", "confidence": 1.0}]
    }
  ]
}
```

- **Files keep today's readable layout** (`Author/Group/[Subgroup/]Group - [Subgroup - ]Name - Grid WxH.ext`, `unique_export_path`), so an export is still useful outside Scene Atlas.
- **Matching is by `sha256`, not by path** ([§6.3](#63-applying-the-manifest)). A user who renames folders inside an export loses nothing.
- **Not exported:** embeddings (the importing library re-embeds with its own model), thumbnails, colours, hashes other than `sha256`, grouping features, import history, ids other than group keys. All of these are rebuilt on import.
- **Linked-library images are left out by default.** The user already has those files. A checkbox includes them, for moving to a library that doesn't have the folder.
- **Written first.** In a zip it is the first entry; in a folder it is written before any image and rewritten at the end ([§5](#5-desktop-folder-export)).

## 3. The download endpoint

```
POST /api/v1/downloads   {image_ids?, group_ids?, include_metadata: bool, include_linked: bool}
  → 201 {token, image_count, total_bytes, filename}
GET  /api/v1/downloads/{token}
  → 200 application/zip, Content-Disposition: attachment, Content-Length
```

- **Two steps, because native downloads need a GET.** A selection of 10,000 ids doesn't fit a query string. The POST resolves the selection (groups expand to their listed images), checks it against the limits and stores the resolved id list under a random token. The GET streams it. The frontend then sets `location.href` (or clicks an `<a download>`), and the browser streams to disk with its own progress and its own pause.
- **Tokens** are 128-bit random, held in memory, expire after 1 hour, and can be fetched more than once (a failed download can be retried). They aren't a security boundary: server mode has no authentication of its own ([security.md](security.md)). Memory is bounded by a cap on live tokens (e.g. 64) and on ids per token (`max_import_items`, 50k).
- **Streaming** uses `zipstream-ng` as today (`ZIP_STORED`, sized, zip64). The manifest is built from the resolved rows before streaming and placed first. For a part (≤ 1000-ish images) that is small; the per-request size cap is what keeps memory bounded, not the streaming.
- **Limits:** one POST may resolve at most `download_max_bytes` (default 8 GB) and 50k images. A larger selection gets 413 with the advice to use Export. The limit exists because a single HTTP download has no resume: a dropped connection at 7.9 GB starts again.
- **Missing originals** (a linked file gone, a store file lost) are left out and listed in the manifest's `missing` array, rather than failing the download mid-stream.
- **Rate limit:** `rate_limit_expensive` on the POST. The GET isn't limited, so a retry is never refused.
- **Electron:** there's no `will-download` handler today. With none, Electron shows a save dialog, which is the behaviour wanted. This needs checking against the window's navigation guards, and a test in `e2e/packaged`. A handler is added only if the default misbehaves.

UI: multi-select in the gallery and the group view gets **Download** (n images, size shown first). The image viewer's single download stays as it is.

`GET /api/v1/export/library` and `frontend/src/lib/download.ts:downloadFile` (the `Blob` path) are removed.

## 4. Full export

Server mode can only hand files to the user through the browser, so a full export is a series of downloads.

```
POST /api/v1/export/plan  {part_bytes?: int, include_linked: bool}
  → {export_id, parts: [{index, image_count, total_bytes, token}], total_bytes, image_count}
```

- **Parts are cut by group, never through one.** Groups are visited in id order and packed into parts up to `part_bytes` (default 4 GB). Ungrouped images fill parts of their own. A group larger than `part_bytes` gets a part to itself. So a group's manifest entry and all its images are in one part, and parts re-import in any order.
- **Each part is a download token** ([§3](#3-the-download-endpoint)), with `part` filled in its manifest. Plan tokens live 24 hours rather than 1, because a 1 TB export takes many hours to download.
- **The plan is a snapshot of ids.** Images added afterwards aren't in it, deleted ones are left out of their part (and listed in `missing`), and edits made meanwhile are exported as they are when the part is fetched.
- **UI (Settings → Library → Export library):** the plan's size and part count; a list of parts, each with a Download link and a tick once fetched (kept in `localStorage`, since it's only a convenience). There's no "download all": browsers block or prompt for many automatic downloads.

At 1 TB with 4 GB parts that is about 250 clicks. That is acceptable for a rare server-mode operation. The alternative, a 1 TB single stream, can't resume. Users with shell access are pointed at copying the store folder plus a metadata backup, which is faster.

## 5. Desktop folder export

On desktop the backend can write to the user's disk, so Export library writes a folder:

- **A background job** (JobRunner, shown in the activity dock) runs `export_library(output_dir)` on the transfer engine ([§9](#9-the-transfer-engine)). The user picks an empty folder, or the folder of an earlier unfinished export.
- **Resumable.** The job writes `scene-atlas-export.json` at the start, with `"complete": false` and the entries it plans. Each file is copied to `<path>.part`, verified and renamed. A restart, or a run into the same folder, skips files already present with the right size and hash, so it carries on. The manifest is rewritten with `"complete": true` at the end.
- **Free space** for the remaining bytes (plus 512 MB) is checked before starting and again every 1 GB. A full disk pauses the job rather than failing it.
- **Shutdown** stops the job between files (`raise_if_shutting_down`). Nothing stays half-written except a `.part` file, which the next run replaces.
- **Throughput:** copy with `shutil.copyfile` (no hashing on the read side); verification hashes the written file once, against `content_hash`, which costs a second read. On one HDD expect about 2–4 hours per TB. A **Skip verification** option is not offered: an export that silently has a bad file is worse than a slow one.

The CLI (`python -m backend.pipeline.export_library`) runs the same function.

## 6. Re-import

### 6.1 Recognising an export

The import pipeline sees files in three ways, and each must find the manifest:

| Source | Where the manifest is | How |
|---|---|---|
| Zip (web upload or local) | A root member `scene-atlas-export.json` | `expand_archive` reads it before placing members |
| Local folder (desktop) | `scene-atlas-export.json` in a picked root | `ingest_local` reads it while listing |
| Browser folder upload | A manifest entry with that file name at a root | Today the manifest marks it `skipped` (unsupported). It becomes an item of kind `export_manifest`, uploaded like any file (it's small), and read at seal |

A manifest is accepted only if it parses, has `format` `scene-atlas-export` and a `version` this build reads, and passes size limits (manifest ≤ 64 MB). Anything else is logged and ignored, and the import proceeds as a normal import. **A bad or unknown manifest never fails the import.** A manifest from a newer version than the build reads is ignored, with a warning in the import report ("This export is from a newer version of Scene Atlas; imported without its metadata").

The manifest is **untrusted input**, like any uploaded file. Strings are length-limited, tag categories are validated as the tag API validates them, grid values are range-checked, and nothing in it is ever used as a filesystem path.

### 6.2 Limits for exports

Uploaded zips are limited to `max_import_files` (1000) and `max_import_total_size` (2 GB) per archive (`validation.check_zip_safety`). A 4 GB export part would be refused. Options:

- **(a)** Size export parts to the import limits by default (2 GB, 1000 files). That doubles the part count, but nothing about import changes.
- **(b)** Raise the limits for a zip whose manifest validates. The zip-bomb check is about uncompressed size; exports are `ZIP_STORED`, so compressed and uncompressed sizes match, and seal's free-space check still applies. But a 4 GB zip is one upload PUT with no resume.

**Proposal: (a).** The part size follows the importing side's limits, so any part re-imports into a default library. Users who raise their import limits can choose bigger parts.

### 6.3 Applying the manifest

- **At seal**, each item whose received `source_hash` matches an entry's `sha256` gets `parsed.export`, holding the entry. Files the client hashed early (`POST /hashes`) can be matched before upload. The rest are matched at seal; items that arrive later are matched when their bytes are received. Matching is by hash, so paths don't matter. An entry with no matching file is reported as "In the export's list but not found" (a count in the report, not an error). A file in the export with no entry is imported as a normal file.
- **Type:** the entry's `image_type` is the item's fixed type: no Auto classification.
- **Grid:** the entry's grid is written as is, with its `source`. Detection is skipped unless the entry has no grid.
- **Tags:** the entry's tags are written as they were, with their `source` and `confidence`. Missing tag categories are created from `tag_categories`; existing categories are never changed.
- **Name, author, subgroup:** from the entry, not the parser.
- **Groups.** This is the one exception to "groups are minted once, by the grouping phase" ([ingestion.md §5.8](ingestion.md#58-identifying-groups)). Images with an export entry don't go through the tree walk:
  - A new table `export_group_links (source_library_id, source_group_key, image_group_id)` maps each exported group to the gallery group made for it. The first image of a group mints the gallery group (with the manifest's `base_name` and `author`) and records the link; later images of that group, from this part or another, join it through the link. So parts can be imported in any order, or again after a failure.
  - A link whose gallery group has since been deleted is replaced.
  - Images without an entry in the same job go through the grouping phase as usual.
  - **Exporting and re-importing into the same library** (`library_id` equal) doesn't need the link table for existing images: they are byte duplicates ([§6.4](#64-duplicates)).
- **Undo import** removes the images as for any import. A gallery group the job minted from a manifest is removed with them unless another job's images joined it through the link.

### 6.4 Duplicates

An exported image that is already in the library is a byte duplicate and is skipped, as today ([ingestion.md §6](ingestion.md#6-duplicate-detection)). **Its metadata is not applied to the existing image.** Re-importing an export into the library it came from is a no-op, not a restore. Restoring metadata is what [§7](#7-backup-and-restore-metadata) is for. "Import as new copy" works as it does for any duplicate, and the copy gets the manifest's metadata.

## 7. Backup and restore metadata

### 7.1 What a backup holds

`scene-atlas-backup-<library>-<timestamp>.zip`:

- `battlemap.db`: a SQLite snapshot (the backup API, as today).
- `vectors/<table>.lance`: the **active model's table only**, compacted first ([§7.4](#74-lancedb-compaction)). Other models' tables are left out: a model switch re-embeds anyway. Without vectors a restore would re-embed the whole library, which takes hours on CPU at 200k images; the active table is about 0.8 GB there for the large model.
- `backup.json`: format, `app_version`, Alembic revision, `library_id`, image count, store file count, created time.

Not held: originals (decision 1), thumbnails, models, logs, staging. Thumbnails are rebuilt from the originals on restore ([§7.3](#73-restore)).

Estimated size at 200k images: SQLite a few hundred MB, vectors 0.4–0.8 GB. A zip that size streams fine as one download.

### 7.2 Making a backup

- **Desktop:** Settings → Library → **Backup metadata** asks for a folder, then a background job writes the zip there. A **schedule** (off / daily / weekly, keep N) writes into a chosen folder. That folder should be on another disk, and Settings says so when it isn't.
- **Server:** the same button streams the zip as a native download (`GET /api/v1/backup/metadata`). Scheduled backups write to `SCENE_ATLAS_BACKUP_DIR` (default `{SCENE_ATLAS_DATA_DIR}/backups`), which the docs suggest mounting on another volume.
- **Today's daily backups move.** They are written into the store (`{SCENE_ATLAS_IMAGES_DIR}/backups/`), on the same disk as what they protect, and keep up to 11 full, uncompacted LanceDB copies of every model. They become this scheduled backup: the backup folder, the active table only, compacted, the same rotation. Pre-migration snapshots stay where they are: they are for rolling back an update, not for disasters.
- **Consistency:** the SQLite snapshot is taken first, then the vector table is copied at a pinned LanceDB version (`checkout(version)`), so ingest isn't blocked for the length of the copy (today `backup_storage` holds the LanceDB lock for the whole `copytree`). A vector written after the snapshot is extra; one missing is repaired by `vector_reconcile` after restore. Both are harmless.

### 7.3 Restore

Restore replaces the database and the active vector table of the open library. It runs at startup, never under a running worker:

1. **Upload or pick** the backup (`POST /api/v1/backup/restore`, streamed; desktop picks a file). The server checks `backup.json`: a revision newer than the build is refused ("made by a newer version"); a different `library_id` needs confirmation ("This backup is from another library"). The zip is staged as `{data_dir}/restore/pending.zip`.
2. **Restart.** Desktop uses the in-window backend restart. Server mode exits with a message; the Compose file's `restart: unless-stopped` brings it back. The docs cover `docker run` without a restart policy.
3. **At startup**, before `init_db`: the current database and table are kept as `restore/previous/` (one generation), the backup's are moved in, then migrations run as for any upgrade.
4. **After opening:**
   - **The orphan sweep is suspended** until the user deals with the result. Files imported after the backup are in the store but in no row, which is exactly what the sweep deletes. (Its 25% guard only helps if they're a quarter of the store.)
   - **Store files no row references** are offered as an import ("312 files in your library aren't in this backup. Import them?"). This is an ordinary local import of those paths, which the store's own folders normally refuse; the importer gets an explicit exception for this job.
   - **Rows whose original is missing** are listed as missing, like a missing linked file, with "Remove missing maps".
   - **Thumbnails** a row references but that aren't on disk are rebuilt from the originals (the "Regenerate thumbnails" backlog job, which this makes a dependency).
   - Vector reconciliation runs as at any startup.

If startup fails after the swap, the next startup puts `restore/previous/` back and reports the failure.

The two disasters this covers:

- **App data lost** (a laptop reinstall, a dead SSD): restore the metadata backup. The originals are still in the store, thumbnails are rebuilt, and nothing is re-embedded.
- **Store lost:** restore the store folder from the user's own backup. It is content-addressed, so a file-level copy restores it exactly, and the metadata needs nothing. The user docs say this in plain words.

### 7.4 LanceDB compaction

Nothing compacts LanceDB today. Every write batch adds a fragment and a version, so search slows and every copy carries the history. The daily maintenance runs `table.optimize()` (compaction plus `cleanup_old_versions` older than 1 day) on each table, after the ingest queue has been idle for 10 minutes, and before every backup. This is independent of the rest and can land first.

## 8. Move library

**Desktop only.** In server mode the folders are mounts and env vars, which the app doesn't own; the server docs say how to move them (stop, move the folders, update the mounts, start), and Settings shows that text.

Settings → Storage locations → **Move…** for app data, the store, or both, to a new folder:

1. **Check.** The target must be empty (or a previous unfinished move of this library, from its marker) and must satisfy the storage rules ([library-setup.md §1](library-setup.md#1-storage-model)). Free space must cover the bytes to move plus 1 GB, unless source and target are on one volume.
2. **Same volume:** a directory rename, which is instant. Then switch (step 5).
3. **Different volume:** the ingest worker pauses, linked scans and maintenance (the orphan sweep, backups) stop, and the gallery stays usable, read-only. Imports, edits and deletes are refused with "Moving your library…". The transfer engine ([§9](#9-the-transfer-engine)) copies:
   - **Store:** every file, verified against `stored_hash`. This is the terabyte, and it is resumable.
   - **App data:** SQLite via the backup API, LanceDB at a pinned version, thumbnails and models as files. Logs and staging are not moved: staging is empty with the worker paused.
4. **Verify.** Every database row's store file and thumbnail exists in the target with the right size; the store's hash verification already ran file by file.
5. **Switch.** Electron writes the new paths to its config and restarts the backend, which opens the library at the new place (the library identity check confirms it's the same library).
6. **Remove the old copy**, only after a successful start at the new place and only when the user confirms ("Delete the old copy (812 GB)?"). Until then the old folders are left untouched. If the new place fails to open, Electron switches back.

Progress (bytes, files, time left) shows in the activity dock. Cancel stops between files and leaves the library where it was; the partial target stays for a later resume. A move survives an app restart: on start, an unfinished move is offered to resume or discard.

Moving **into the linked folder** (the desktop default puts the store at `<linked>/Scene Atlas`) is allowed. Moving the store **to be or contain** the linked folder is refused, as in setup.

## 9. The transfer engine

`backend/pipeline/file_transfer.py`, used by the folder export ([§5](#5-desktop-folder-export)) and Move library ([§8](#8-move-library)):

```python
@dataclass
class TransferItem:
    source: Path
    target_relative: str
    size: int
    sha256: str | None     # verify against this when given

def transfer(items: Iterable[TransferItem], target_root: Path, *, progress, stop) -> TransferResult
```

- Copies to `<target>.part`, `fsync`s, verifies size and (if given) SHA-256, then renames.
- **Resume:** a target that already exists with the right size is verified by hash and skipped if it matches. A crash costs one file.
- **Free space:** checked up front for the remaining bytes, and every 1 GB. Too little pauses, with a reason.
- **Errors:** a source that can't be read is recorded and skipped (reported at the end). A target write failure stops the transfer (a full or failing disk), since every following file would fail too.
- **Stop:** checked between files (shutdown or cancel).
- One file at a time per destination volume: parallel copies to one HDD are slower, not faster.

Unit-tested with fault injection (a failing read, a full disk, a crash mid-file).

## 10. Testing at scale

A **synthetic large library** fixture, `scripts/dev/make_large_library.py`. It generates N image rows with groups and tags straight into SQLite, LanceDB vectors with random values, and store files. Files can be **sparse** (`truncate`, real size, no disk use), so a 1 TB library fits on a laptop for the metadata, plan and space-check paths. Byte verification needs real bytes, so those tests use 10–50 GB of real files.

Measured and recorded in this doc, at 200k images:

| Measure | Target |
|---|---|
| Export plan time | < 5 s |
| Download POST time, 1000 images | < 1 s |
| Download stream throughput, server memory | disk-bound, < 200 MB RSS |
| Folder export throughput, resume after a kill | disk-bound; resume skips work done |
| Backup time and size, ingest stall during it | < 2 min, < 1.5 GB; no stall |
| Restore end to end (app data lost) | thumbnails dominate; record it |
| Move across volumes, resume after a kill | disk-bound; resume skips work done |
| LanceDB compaction time, search latency before/after | record it |

Round-trip tests: export a fixture library (parts and a folder), import into an empty one, and compare names, authors, groups, subgroups, types, grids and tags image by image. Parts are imported in shuffled order, and one part twice.

## 11. Order of work

Each step is its own PR:

1. **LanceDB compaction** ([§7.4](#74-lancedb-compaction)) and the scale fixture ([§10](#10-testing-at-scale)). Measure today's backup and export first, so the rest is compared against numbers.
2. **The transfer engine.**
3. **Export format v2, the download endpoint, the gallery Download action, full export parts.** The old export endpoint and the `Blob` download go.
4. **Re-import:** manifest recognition, `export_group_links`, the round-trip tests.
5. **Desktop folder export** on the engine.
6. **Backup and restore metadata**, including moving the daily backups out of the store and Regenerate thumbnails.
7. **Move library.**

Steps 1–4 and 7 are the release-0.2.0 scope as agreed (Move library before launch). Step 6 is needed to call backups a feature; it could be 0.3.0 if the release shouldn't wait, but today's backups stay on the same disk as the store until it lands.

## 12. Open questions

- **Apply metadata to duplicates?** [§6.4](#64-duplicates) skips them. A "merge" option would let a re-import update existing images' tags and groups. It isn't needed for any flow above, and silently overwriting user edits is the risk.
- **Part size default.** 2 GB / 1000 files to match the default import limits ([§6.2](#62-limits-for-exports)), or larger with raised limits.
- **Server restore without a restart policy.** Exiting to restart is simple but relies on Compose. The alternative is an in-process close and reopen of the database and LanceDB, which nothing does today.
- **Include linked images in exports by default?** Proposed: off.
