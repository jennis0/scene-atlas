# Library setup and the linked library

Status: **plan** (2026-10-19). Decision record: [ADR-021](decisions.md#adr-021-library-setup-in-the-wizard-and-the-linked-library).

This plan covers three things that ship together:

1. **Choosing storage in the setup wizard.** The Electron storage window (`electron/setup.html`) goes away. Folders become a desktop-only step in the React wizard.
2. **The linked library.** One existing maps folder is read where it is and never written to. This is feature 2 of [local-ingest.md](local-ingest.md) (§8 there was the outline).
3. **Reopening an existing library.** Point the wizard, or a server's env vars, at a Scene Atlas library and it opens. The folders must belong to the same library.

Out of scope, each decided with the user on 2026-10-19:

- **Backups and restoring from them.** They stay as they are and will be designed as a feature of their own. Reopening therefore needs both the app data folder and the store.
- **Moving a library in Settings.** Today Settings only repoints the folders, and the user moves the files by hand. A proper move is due before launch, in a separate piece of work.
- **S3-compatible stores.** Not built now, but [§9](#9-s3-later) lists what this design keeps open for them.
- **OneDrive Files On-Demand placeholders.**
- **More than one linked folder.**
- **A faster first pass for large scans.** For example, making thumbnails and names searchable before embedding.

## 1. Storage model

A library has three places, each with one job.

| | Holds | Access | Desktop default | Server |
|---|---|---|---|---|
| **App data** | Database, search index, thumbnails, models, logs, staging. It grows to several GB. | Writable, and always a local disk because it holds SQLite | `%LOCALAPPDATA%\Scene Atlas\data` (Windows), `~/Documents/Scene Atlas/data` | `APP_DATA_DIR` |
| **Store** | Originals of imported (copied) maps, `backups/`, and the library marker | Writable | `…/Scene Atlas/images` for a new library; `<linked folder>/Scene Atlas` when a folder is linked | `IMAGE_LIBRARY_DIR` |
| **Linked folder** (optional, one) | The user's existing maps | **Read-only.** Scanned, never written, moved or deleted | none | `LINKED_LIBRARY_DIR`, typically a read-only mount |

The rules are the same in both modes. The only difference is where the desktop wizard puts the store by default.

Rules checked at startup (§3.3), each giving a refusal with a plain message:

- The store and app data may sit **inside** the linked folder, as the desktop default does. They may not **be** the linked folder or **contain** it. Library purge `rmtree`s the store (`api/system.py:138`), so a store that contained the user's maps would delete them.
- The scanner skips any folder holding a library marker or a `.backend.lock`, so the library's own folders are never imported.
- Store files keep their hash-shard names. Readable `Author/Pack/file` paths were rejected: every rename, author change or regroup would mean moving files, and the folder would drift from the database.

## 2. First-run flow (desktop)

### 2.1 Before the wizard

The storage window is removed. On a first launch with no config, Electron:

- writes a config with the default folders and **`provisional: true`**;
- starts the backend on those folders, as it does for any later launch.

The wizard then opens on that provisional library.

### 2.2 Steps

```
Appearance → Your library → Stored format → Tag packs → Search model
             (desktop only)
```

The library step has to come **before** Stored format and Tag packs. Each wizard step saves to the backend on its own Continue (`StoredFormatStep`, `TagPackStep`). If folders changed after those steps, their choices would be saved into a database that is about to be thrown away. Appearance is kept per device, mirrored into the Electron config, so it survives the relaunch.

```
Your library

(•) Start a new library
( ) Use a folder of maps you already have
      D:\Battle Maps                                [Choose]
      Found 56,214 images.

      Scene Atlas adds the maps and scenes in this folder, and any
      you add to it later. Tokens and other art are skipped. Your
      files are never changed, moved or deleted. Maps you import in
      the app go in the Imported maps folder, not into your own folders.

Imported maps    D:\Battle Maps\Scene Atlas         [Change]
                 Stores full resolution images. It can be stored on any large drive.
Search data      C:\Users\…\Scene Atlas\data        [Change]
                 Stores metadata and thumbnails. Best on a fast drive.
```

Copy follows [first-run.md](first-run.md#copy): short and plain, with no explanation of mechanics.

The paragraph under "Use a folder of maps you already have" is the exception. It shows only when that option is selected, because the linked library behaves differently from an import, and users need to know four things before choosing it (user decision 2026-10-19):

- What's added: maps and scenes. Auto image type skips tokens and other art, so the copy mustn't promise "everything".
- That files added later are picked up too (§4.3).
- That their files are never changed, moved or deleted.
- That imports made in the app go to the Imported maps folder, not into the user's own folder layout.

**Picking a folder.** Every folder the user picks is checked by the backend (`POST /library/inspect`, §3.4) before Continue is enabled. The result can be one of the following.

| Result | Shown | Continue |
|---|---|---|
| A maps folder | "Found 56,214 images." | Allowed |
| An empty or new folder | nothing | Allowed |
| A Scene Atlas library with a matching search data folder | "Scene Atlas library found." The other folders are filled in from the marker's hints (§3.2). | "Open library" |
| A Scene Atlas library whose search data folder isn't found | "This library's search data folder is missing. Choose it, or pick another folder." | Blocked until it's resolved |
| Folders from two different libraries | "These folders belong to different libraries." | Blocked |
| A maps folder chosen under "Start a new library" | "This folder already has maps in it." with a link: "Use it as your existing folder" | Allowed (today's warning, made actionable) |

**Continue on the library step:**

- **Nothing changed** (a new library on the default folders): Electron records `libraryChosen: true` and the wizard moves on. There's no relaunch.
- **Something changed**: the main process does the following, in order:
  1. Validates the folders and saves the config with `libraryChosen: true`.
  2. Stops the backend.
  3. Deletes the provisional folders that are being replaced, but only if they hold nothing except Scene Atlas's own entries (`hasForeignEntries`). Nothing can have been imported into them, because the gallery is gated until setup completes.
  4. **Restarts the backend in the same window**, showing the loading page, then reloads the UI.

  The window stays put, unlike today's `app.relaunch()`, and Settings' storage change switches to the same path.
- **After the reload**, the gate (`App.tsx`) sees one of two things. A reopened library that has already been set up goes straight to the gallery. Otherwise the wizard resumes after the library step, because `electronAPI` reports `libraryChosen`, so Appearance and Your library are skipped.

**Scanning.** When a folder is linked, the backend starts scanning it as soon as it starts (§4.3). Items wait until a model is ready: the ingest queue already pauses with "No AI model is available". So the scan is listed while setup continues, and processing begins once Finish starts the model download.

### 2.3 After setup

- **Empty-library screen.** While a linked scan is running, the screen says "Adding your maps…" in place of the import prompt. The gallery fills as batches commit: images are visible before their job finishes, and the gallery refreshes at most every 4 s during an import.
- **Activity dock.** The scan is one row, "Battle Maps · 1,204 of 56,214". Its import report never opens by itself.
- **Duration.** A large first scan takes hours, because embedding and grid detection dominate. The copy says so once and nowhere else.

## 3. Library identity

### 3.1 Library ID

`library_id` is a UUID kept in `app_settings`. It is created with a new library and never changes.

### 3.2 Markers

A file named `scene-atlas-library.json` sits at the root of **both** the app data folder and the store:

```json
{
  "format": 1,
  "library_id": "4f1c…",
  "role": "store",
  "hints": { "app_data": "C:\\Users\\…\\Scene Atlas\\data", "linked": ".." }
}
```

- The **database is authoritative**. Markers mirror it so a folder can be recognised without opening SQLite: the backend's own inspect endpoint, and Electron's `hasForeignEntries`, which adds the marker name to its own-entries list.
- **Hints** are the last-known locations of the other two places, rewritten at every startup.
  - They're only hints. Drive letters change, so the wizard fills them in for the user to confirm.
  - A store inside its linked folder records `"linked": ".."`. This lets the linked folder be found again on another machine with no other information.
- The backend writes markers at startup and after a library purge. Purge `rmtree`s the store, marker included.

### 3.3 Startup check (both modes)

The check runs in the lifespan after the storage locks and before anything touches either root, so `get_image_store()` can no longer create a store on its own. In the table, D is the database's `library_id` and S is the store marker's.

| D | S | Outcome |
|---|---|---|
| none (new database) | none | **New library.** Create the ID and write both markers |
| X | X | Open |
| X | Y | **Refuse**: "The image folder belongs to a different library." |
| none (new database) | X | **Refuse**: "This image folder belongs to a library whose search data folder isn't here." |
| X | none, and the database references stored files | **Refuse**: "The image folder doesn't contain this library's maps." |
| X | none, and no stored files | Write the store marker. This is a new, empty store, for example a library that only uses a linked folder |
| database exists with no ID (a library from before this change) | none | Adopt: create the ID and write both markers |

**Linked folder.** The `library_sources` row keeps the last-known location L, compared with the configured folder C:

- **No row:** create one.
- **C equals L:** nothing to do.
- **C differs from L:** update L. The rescan matches files by relative path, so a changed drive letter just works.
- **No C, but a row exists:** the source is **detached**. Its images show as offline, and Settings offers to remove them.
- **C missing on disk:** the source is **offline**, not an error. The app starts, and search and thumbnails work because both live in app data.

**Refusals.** In the desktop app a refusal surfaces on the loading page, as the storage-lock error does today, with "Choose folders…" to reopen the library step. In server mode it is a startup error in the logs.

### 3.4 `POST /library/inspect` (desktop only)

Body: `{app_data?, store?, linked?}`, each an absolute path. It returns what the wizard needs:

- the outcome from §3.3's rules, applied to the proposed folders;
- an image count for a maps folder;
- marker details and hints for a library.

Details:

- It is **404 in server mode**, like `local-sources`.
- It is read-only, behind the loopback `Host` check.
- It returns counts and marker contents, never file names.
- The count uses the scan's walk (§4.3) and stops counting at the 250k limit.

Rule logic lives only in Python, shared by this endpoint and the startup check. Electron's job is limited to picking folders, saving the config and restarting.

**The folders are never set through the API.** The wizard sends them to Electron over IPC (`library:apply`). Electron passes them to the sidecar as arguments (`--linked-library-dir`, alongside the existing two), and `entry.py` turns them into env vars. So the backend only reads a linked folder from its own configuration, in both modes.

## 4. Linked library

### 4.1 Data model

```
library_sources                         -- one row today; a table so files and images can
  id            INTEGER PK              --   reference it and S3 can add a kind later
  kind          TEXT  'folder'
  location      TEXT                    -- last-known absolute path (S3 later: bucket/prefix)
  state         TEXT  online | offline | detached
  last_scan_at  DATETIME

source_files                            -- the durable index of the linked folder
  id            INTEGER PK
  source_id     FK → library_sources
  rel_key       TEXT                    -- POSIX path relative to the root; UNIQUE(source_id, rel_key)
  size          INTEGER
  mtime_ns      INTEGER                 -- S3 later: ETag in a version column
  content_hash  TEXT(64)                -- set once hashed
  state         TEXT  pending | image | duplicate | skipped | failed | removed
  image_id      FK → images NULL        -- the image (state image) or the match (duplicate)
  reason        TEXT NULL               -- skip/failure reason
  missing_since DATETIME NULL

images
  storage_key     NULL allowed          -- NULL for linked images
  source_file_id  FK → source_files NULL, UNIQUE
  CHECK (storage_key IS NOT NULL OR source_file_id IS NOT NULL)

import_items
  source_file_id  FK → source_files NULL   -- set for linked items; source_path stays absolute
```

`source_files` exists so rescans **never re-hash a file they've already seen**. Without it, every duplicate, skipped token or failure would be hashed again on every scan, because none of those has an image row. In the user's library that's about 1.4k byte duplicates and 1.9k tokens.

### 4.2 Reading files: one interface

Store and linked files are both read through a small source interface:

| Method | Store | Linked folder |
|---|---|---|
| `list()` | (sweep only) | the walk (§4.3) |
| `stat(key)` | yes | yes |
| `open(key)` / `local_path(key)` | path | path, after the containment check |
| `put`, `delete` | yes | **absent**, so the read-only rule is enforced by the type |

**Containment check.** A linked `rel_key` is the first stored path in the codebase that reaches the filesystem. Every read therefore does the following:

1. Joins the key to the root.
2. Calls `resolve()` on the result.
3. Requires the resolved path to be `is_relative_to(root)`.
4. Requires a regular file that isn't a symlink.

Any other result is refused. (`relative_path` in import items is display-only and never reaches the disk; zip members are extracted to generated names. This check is for linked files only.)

### 4.3 Scanning

A scan runs:

- at backend startup;
- when a linked folder is first configured;
- **every 15 minutes** while the app runs, through the scheduler;
- in the desktop app, **when the window regains focus**, at most once a minute. This covers copying maps in with Explorer or Finder and switching back;
- when **Check for changes** is clicked in Settings.

A scan that finds nothing new reads no files. It lists the folder and compares sizes and modification times, which takes about 3 s for 60k files on a local disk. It also creates no job, so it is invisible.

It never watches the folder. OS file events are unreliable on large synced folders, network shares and Docker bind mounts, and need a handle per folder.

Steps:

1. **Walk.** `os.scandir`, sorted, using the local import's walker (`ingest_local._walk`):
   - Symlinks are skipped and OS junk is dropped.
   - Library folders are skipped (§1).
   - `rel_key` is taken **from the root itself**, giving `Author/Pack/file`. Local import takes it from the root's parent instead. The parser reads the first path component as the author, so the root's own name must not be included.
2. **Diff** against `source_files` by `rel_key`:
   - **Unchanged** (same size and mtime): nothing happens, and the file isn't read.
   - **New**: insert a `pending` row and queue an item.
   - **Changed**: the file was edited in place. Queue a **refresh** of its image (§4.5).
   - **Gone**: set `missing_since`. The image is kept.
   - **Back again** (it has `missing_since` and size and mtime match): clear `missing_since`.
3. **Queue.** If there is anything to process, create **one import job** labelled with the folder's name, add the items and seal it.
   - The seal is `plan_job`, so grouping is unchanged. New files in an existing pack merge into its group by `(name, author)`.
   - Items are claimed in group-then-id order, so packs finish one at a time.
   - Image type is Auto.
   - A scan that finds nothing to process creates no job.
4. **Offline root** (the folder doesn't exist): mark the source offline and stop. Nothing is marked missing.

**Limit.** The existing `max_local_import_items` (250k) applies to new files per scan.

### 4.4 Processing a linked item

This is `_prepare_local` with two differences:

- **No copy.** The source is hashed, decoded and grid-detected where it is. Stored format doesn't apply. That avoids writing 216 GB to the app data disk during a first scan. On a local disk the source is read up to three times, and the repeat reads come mostly from the OS cache.
- **A guard against files that change during processing.** Size and mtime are checked again before commit. If they changed, the item goes back to `ready`.

Commit sets `storage_key = NULL` and `source_file_id`, and updates the `source_files` row (state, `content_hash`, `image_id`).

**Duplicates, and moves.** Early dedup (bytes tier) behaves as it does for local imports, plus one rule. If the byte match is a **linked image whose file is missing**, the file was moved. Then:

- The image is repointed to the new `source_files` row, keeping all its metadata.
- The old row is deleted.

Otherwise the file is a `duplicate` and its row records the match. If an image's file goes missing and a `duplicate` row with the same hash still exists, the next scan repoints the image to that file in the same way.

Item outcomes are written back to `source_files`:

| Item outcome | `source_files.state` |
|---|---|
| `skipped` (Auto sorted it out, or unsupported) | `skipped`, with the reason |
| `failed` | `failed`. Retried when the file changes, or by Retry in the report |

### 4.5 Changed files (refresh)

A refresh item points at an existing image. It re-runs hashing, decoding, thumbnails, embedding and grid detection, and updates that image in place:

- Names, tags, group and type are kept.
- Grid results with `grid_source = user` are kept.

Planned as the last backend phase. Until it's built, a changed file is re-processed as a new file and its old image is marked missing.

### 4.6 What existing code changes

From the inventory of every caller of `get_image_store()`:

| Place | Change |
|---|---|
| `GET /images/{id}/file`, the thumbnail fallback, group download, library export | Read through the source interface. A missing file returns 404; an offline source returns 503 with a reason the UI shows |
| `backfill_grid_detection` | Same. Skips unavailable files |
| `safe_delete_image` | Fix: it counts references with `storage_key == None`, which compiles to `IS NULL` and would call `image_store.delete(None)` |
| `delete_image_rows` | Fix: thumbnails of images without a `storage_key` are never deleted |
| Removing a linked image (delete, group edit) | Delete the row, thumbnails and vector, never the file. Set the `source_files` row to `removed`, so rescans don't bring it back. There's no "show removed files" view yet |
| Undo import | Hidden for linked jobs. Removing the folder's maps is done with "Stop using this folder" |
| Cancel on a linked job | Stops it. Its pending rows are deleted, so the next scan offers those files again. Excluding subfolders is later work |
| Library purge | Deletes `library_sources`/`source_files` rows with the rest. Never touches the linked folder. Rewrites the store marker |
| Orphan sweep | Unchanged: it only walks shard folders |
| Vector reconcile, model switch | Unchanged: they read thumbnails, so they work while the folder is offline |
| Seal's free-space check (`_check_free_space`) | Linked items need no store space |
| `ImageBase.storage_key: str` | Becomes optional. The API adds `file_state: ok \| missing \| offline` |

### 4.7 Missing and offline in the UI

- **Missing file.** The gallery tile shows a small "File missing" mark. The viewer shows the thumbnail with "The original file is missing."
- **Offline source.** A banner reads "Battle Maps isn't available", and originals can't be opened. Search, thumbnails and editing all work.
- **Settings → Library** shows:
  - the folder's state;
  - "Check for changes";
  - a missing count with "Remove missing maps";
  - "Stop using this folder", which removes that folder's maps from the library after confirming the count. This is the way out of linking the wrong folder.

  On a server, Settings shows the state and counts but never the path.

## 5. Server mode

- `LINKED_LIBRARY_DIR` names the linked folder. Docker docs recommend a read-only mount, for example `-v /srv/maps:/library:ro`.
- The store stays at `IMAGE_LIBRARY_DIR`. It can't be inside a read-only mount, so the desktop's "store inside the folder" default doesn't apply on servers.
- The rules in §1 and §3.3 apply unchanged. There's no wizard step: the scan starts at startup.
- `POST /library/inspect` doesn't exist in server mode. "Check for changes" does, because it names no path.
- This reverses local-ingest.md's "linked library is desktop only". That stance was about **client-named** paths, and an env var isn't one.

## 6. Settings (desktop)

**Storage locations** gets a third row, for the linked folder:

| Row | Actions |
|---|---|
| App data | Change: today's repoint-and-restart, with the move-files-yourself warning until Move library exists |
| Store | Change: the same |
| Linked folder | Change (restart, then a scan reconciles by relative path), Stop using |

All three run the same inspect check as the wizard. Restarts use the in-window backend restart (§2.2).

## 7. Removed and changed code

**Electron:**

- `setup.html`, `setup.preload.ts`, `showSetupWindow`, the `setup:*` IPC channels, `setupWindow`, and the `start()` else branch are removed.
- `build_icons.py` and the `electron-builder.yml` entry for setup.html are updated.
- `electron/fonts` **stays**: `loading.html` and `build_brand_images.py` use the fonts.

**Packaged tests:**

- "first launch shows the setup window" becomes "first launch opens the wizard on the default folders".
- The en-GB locale check moves into that test.
- The packaged test helper (`e2e/packaged/app.ts`) gets `libraryChosen`.

**Docs:** electron.md, first-run.md, storage.md, security.md, testing.md, `docs/deploy/desktop.md`, `docs/guide/getting-started.md`, `docs/deploy/server.md` and `configuration.md` (the new env var), and `docs/development/building.md`.

## 8. Security

- **Folder paths reach the backend only through configuration**: sidecar arguments in the desktop app, env vars on a server. No endpoint sets them.
- **`/library/inspect` reads a client-named path**, the same class of risk as `local-sources`. It is limited to the desktop app and loopback hosts, is read-only, and returns counts and marker contents only.
- **Linked reads** go through the containment check (§4.2). The source interface has no write or delete.
- **Store and app data can't be or contain the linked folder** (§1), so purge and the orphan sweep can't reach the user's files.

security.md gets a finding for the inspect endpoint and linked reads.

## 9. S3 later

Not built, but these choices are made now so S3 can be added without a rewrite:

- **All original-file access goes through the source interface (§4.2).** Nothing outside it uses `os.scandir`, `open` or `Path` on a store or linked file.
  - On S3, `local_path()` downloads to a temp file, which is why processing asks for a path rather than assuming one.
  - Serving can redirect to a presigned URL.
- **Files are identified by `(source_id, rel_key)`,** never by an absolute path.
- **Change detection is size plus a version field:** mtime on disk, ETag on S3.
- **`library_sources.kind`** leaves room for an `s3` kind; the marker becomes an object.
- **Some things stay local:** the `.incoming` rename stays inside the local store implementation, and app data stays local in every case.

## 10. Implementation plan

Each phase leaves main working, but the feature ships as one PR from `feature/library-setup`.

1. **Library identity** (backend):
   - `library_id`, markers, the startup check (§3.3) with tests for every row;
   - stopping `get_image_store()` from creating roots;
   - `POST /library/inspect`;
   - the `--linked-library-dir` / `LINKED_LIBRARY_DIR` setting.
2. **Linked library core** (backend):
   - migration: `library_sources`, `source_files`, `images.source_file_id`, nullable `storage_key`, `import_items.source_file_id`;
   - the source interface, the walker shared with local import, scan and diff;
   - processing linked items, moves and duplicates, write-back to `source_files`;
   - scans at startup, every 15 minutes, on window focus (a desktop IPC event to a scan endpoint, rate-limited to once a minute) and on demand, never two at once;
   - offline and detached states.
3. **Everything that touches originals** (backend): the §4.6 table, including the two deletion bugs, `file_state` in the API, purge, export, removing images and "Stop using this folder".
4. **Electron:**
   - remove the storage window;
   - provisional default config and `libraryChosen`;
   - `library:apply` and the in-window backend restart, which Settings switches to as well;
   - provisional cleanup;
   - the new sidecar argument;
   - packaged tests.
5. **Frontend:**
   - the Your library step and resuming the wizard;
   - the Settings storage section and Settings → Library;
   - missing and offline marks, the banner, the empty-library scanning state;
   - hiding Undo for linked jobs.
6. **Refresh of changed files** (§4.5).
7. **Docs and measurement:**
   - fold this plan into storage.md, ingestion.md, first-run.md, electron.md and local-ingest.md;
   - scan the real library natively on Windows: time to list, time to the first gallery tiles, total time, and the time for a rescan with no changes.

### Tests

- **Unit:**
  - every row of the startup check table;
  - marker read and write;
  - scan diff (new, unchanged, changed, gone, back, offline);
  - containment (`..`, absolute, symlink, a junction on Windows);
  - move matching.
- **Integration:**
  - a linked library in a temp folder: first scan, then rescans after add, delete, move and edit;
  - the source tree is byte-identical afterwards;
  - removed files stay removed;
  - offline, then online again;
  - inspect is 404 in server mode;
  - purge never touches the linked folder.
- **Frontend:**
  - the library step's states (§2.2 table), with a mocked `electronAPI`;
  - the wizard resuming after `libraryChosen`;
  - missing and offline UI.
- **Packaged (Electron):**
  - first launch, then a new library on the defaults;
  - choosing other folders restarts the backend and deletes the provisional folders;
  - reopening a library by pointing at its maps folder.

## 11. Open questions

- **Rescans at startup on a large, slow folder.** About 3 s natively for 60k files, which is fine. A network share could be much slower. Measure before adding a progress state.
- **"Show removed files".** No view yet, so a removed linked map can't come back without "Stop using" and relinking the folder. Add one if users ask.
- **Excluding subfolders** (for example `Tokens/`). Cancel isn't durable, by design. If needed, this becomes a list on `library_sources`.
