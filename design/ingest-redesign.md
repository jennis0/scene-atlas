# Ingest Redesign: History and Rationale

The per-item ingest pipeline ([ADR-018](decisions.md#adr-018-durable-per-item-ingest-pipeline)) is implemented and merged (PR #1). **[ingestion.md](ingestion.md) is the canonical description of how it works.** This document keeps the reasons for the redesign, the measurements that shaped it, the audit mapping and the open questions.

Code comments that cite sections of this document refer to the original design, now in ingestion.md:

| Original section | Now |
|---|---|
| §3 Data model | [ingestion.md: Data model](ingestion.md#data-model) |
| §4 State machines | [ingestion.md: State machines](ingestion.md#state-machines) |
| §5 Worker, §5.3 commit protocol, §5.4 errors | [ingestion.md: Ingest worker](ingestion.md#ingest-worker), [Error classification](ingestion.md#error-classification) |
| §6 Duplicate detection | [ingestion.md: Duplicate detection](ingestion.md#duplicate-detection) |
| §7 Upload protocol | [ingestion.md: Upload protocol](ingestion.md#upload-protocol) |
| §8 Frontend | [ingestion.md: Client sequence](ingestion.md#client-sequence), [frontend.md](frontend.md) |
| §9 Maintenance | [ingestion.md: Maintenance](ingestion.md#maintenance) |
| §10 Image conversion | Not implemented; see [Status](#status) |

## Why

A reliability audit (2026-10-12) found about 50 issues in the previous import flow, almost all from three structural causes:

1. **The job was treated as an all-or-nothing transaction.** A restart, any failed group, or dismissing a failed job deleted every image the job had imported.
2. **No durable per-file state.** The confirmed file list lived only in memory (`JobRunner` kwargs), so nothing could resume, cancel couldn't stop the worker, and age-based maintenance could delete a long import part-way through.
3. **The browser drove the lifecycle.** Hashing, uploading and auto-confirm ran in React effects; a tab close or remount stranded the job, and one effect caused a request loop during every import.

Other problems: duplicate detection never worked with WebP conversion on (the stored hash was of the WebP output); more than 32k files hit SQLite's bound-variable limit; per-batch work grew O(n²); three uncoordinated pollers.

The fix was a model change (durable per-file items, a server-owned worker, a single client-side owner) rather than a list of patches.

## Audit findings → design

Finding ids are from the 2026-10-12 audit (B = backend, F = frontend).

| Finding | Addressed by |
|---|---|
| B-C1 restart deletes all work, no resume | Durable items, startup recovery, no implicit deletion |
| B-C2 WebP deletes source in place | Conversion removed; stored files are the original bytes |
| B-H1 one failed group wipes the job | No job failure; per-item commit; transient retry |
| B-H2 jobs stuck `active` forever | Status derived from item counts by one function |
| B-H3 cancel doesn't stop the worker | Status checked at claim; cancel skips open items |
| B-H4 timers kill long imports | No expiry of active jobs; state-based staging cleanup |
| B-H5 dedup broken under WebP; racy | Hash of the original; commit-time check under `BEGIN IMMEDIATE` |
| B-H6 more than 32k SQLite variables | Chunked manifest and `IN` queries |
| B-H7 analyse/fail race | No analyse step or `/fail`; seal is idempotent and server-owned |
| B-H8 blocking async endpoints | Async streaming plus `to_thread` |
| B-H10 orphaned store files | Temp-then-rename placement; fixed orphan sweep |
| B-M1/M2 vector inconsistency | Id-set reconciliation instead of a forced rebuild |
| B-M5/M6 O(n²) work and huge JSON rows | Per-item rows, indexed counts, paginated items |
| B-M10 confirm submits before commit | No confirm step; the worker reads committed `ready` items |
| B-M11 import queued behind maintenance | Dedicated worker, separate from `JobRunner` |
| B-M12 maintenance never runs in Electron | Scheduler runs overdue tasks at startup |
| B-M14 per-job FTS rebuild | Removed; triggers maintain FTS |
| F1 `/imports/active` request loop | Single manager-owned poller with ETag; views are pure |
| F2 all-duplicates job stuck | Job completes from item counts |
| F3 dismiss deletes everything | Dismiss only hides; Undo is explicit |
| F4 one file or 3 s of outage fails the import | Per-file retry, continue, wait for connection |
| F5/F6 hidden or lost uploads | Manager owns uploads; `beforeunload`; resume; "upload interrupted" |
| F7 localStorage overflow | Nothing persisted locally |
| F-M2/M4/M12 failures invisible or misreported | Completion toast for every outcome; report sections from item states |

## Phase 0 measurements (2026-10-15)

384 maps sampled from the maintainer's library (stratified by size, up to 761 Mpx), Ryzen 9 5900X under WSL2, single process. Library-weighted mean CPU ms per image:

| Stage | Previous pipeline | Redesign |
|---|---|---|
| Decodes per image | 3 | 1 (plus grid detection's read) |
| Thumbnails | 430 | 89 (cascade from one decode) |
| Colours | 232 | ~84 less (from the 800 px thumbnail) |
| Grid detection (battlemaps) | 398 | 398, the largest stage (34%) |
| Pixel hash (strips) | – | 111 |
| pHash | – | ~1 |
| Embedding, small / medium model | 102 / 474 | same |
| **Total, small model** | **~1,150** | **~830 (about 5 img/s on 4 cores, 10 on 8)** |

Decisions taken from the results:

1. Claim/commit batch stays at 16. On CPU, embedding batch size barely matters for the small model and larger batches are worse for medium.
2. Pixel hash kept: strip-wise SHA-256 (about 0.7× a decode). Colour under fully transparent pixels is zeroed before hashing, because libwebp rewrites it and 8 of 12 transparent PNGs failed to match their own lossless WebP.
3. Pillow's default `MAX_IMAGE_PIXELS` (89.5 Mpx) rejected about 2% of the real library; it is now `settings.max_image_pixels` (1 Gpx).
4. 15% of image-extension files in the library were AppleDouble junk; the manifest ignores OS junk.
5. Lossless WebP made JPEGs about 3.1× larger and cost about 11 s CPU for a 20 Mpx map; lossy q90 gave 0.56× (JPEG) and 0.15× (PNG). Any future conversion option should never offer lossless for lossy sources, should use `exact=True`, and must skip images over 16,383 px (WebP's limit).
6. Ingest needs only 23–45 MB/s of library writes, well within HDD sequential speed; disk was not measured.

Memory, measured as peak RSS of the prepare step on a 400 Mpx JPEG: grid detection off 279 MB / 2.1 s; grid at a 20k cap 2,244 MB / 15.3 s; grid at an 8k cap 558 MB / 2.5 s. The grid cap is the dominant memory and CPU lever, so `grid_detection_max_dim` defaults to 8,000 (on 373 battlemaps: 99.5% presence agreement and 95% size agreement with the 20k baseline, 3–4× less CPU on the largest maps). Reduced-scale JPEG decode, reduced-scale grid reads and `MemoryBudget` came out of the same study.

## Live end-to-end run (2026-10-15)

Real backend and UI driven by Playwright against copies of real library files:

- **Awkward folder** (48 files: in-folder copy, zip of copies, truncated JPEG, `notes.txt`, AppleDouble file): 42 done, 4 duplicates, 1 failed, 1 skipped, junk ignored, 8 groups, in 11.5 s.
- **Crash recovery** (SIGKILL with 12–13 items processing): queue ready 6–7 s after restart, in-flight items re-queued, job completed; DB rows = stored files = vectors, no `.incoming` leftovers or orphans.
- **Undo** removed every row, file, thumbnail and vector in three runs.

Bugs found there were fixed (stale system pause after model load, poller stuck on its idle interval, slow reconnect after server restart, group counts including duplicates, toast theming).

## Status

| Phase | Content | Status |
|---|---|---|
| 0 | Benchmark | Done (above) |
| 1 | Backend core: tables, state machine, worker, commit protocol, hashes, reconciliation | Done |
| 2 | API, archive expansion, maintenance rewrite, removal of the old flow | Done |
| 3 | Frontend: `ImportManager`, hash worker, dialog, dock, report | Done |
| 4 | Duplicate UX | Partial. "Import as new copy" (bulk and per item) exists. Possible-duplicate (pHash) flags are not implemented; `similar_to_image_id` is never set. |
| 5 | Conversion config (`stored_format`, `stored_quality`) | Not done. The old `convert_to_webp` settings still exist but are ignored. |
| 6 | Docs and E2E | Docs folded into ingestion.md. E2E seeding (`e2e/helpers/seed.ts`) and `stress_tests/` still call the removed `/imports/init`, `/analyse` and `/confirm-all` endpoints. Failure-injection E2E specs not written. |

Tracked in [status-and-roadmap.md](status-and-roadmap.md).

## Open questions

- **Pixel-hash determinism.** A Pillow/libjpeg upgrade could change decoded output. The failure mode is a missed duplicate, never a false skip.
- **Request count.** One `PUT` per file means about 10k requests for a 10k-file import. Fine on localhost and keep-alive; reverse-proxy rate limits need configuring.
- **SQLite write contention.** User edits during a big import compete for the writer; `busy_timeout` plus transient retry covers it.
- **Possible-duplicate volume.** pHash puts gridded/gridless pairs 0–2 bits apart. Flags must be suppressed or grouped within an import group and between sibling grid/no-grid folders, or about 9k images in the maintainer's library would flag.
- **Shared-storage "add to group".** Putting an existing image into a new group needs many-to-many group membership. Deferred until there's a need.
- **Progressive JPEGs and PNG/WebP** decode at full size (up to about 1.3 GB at 200+ Mpx). Only a streaming decoder (e.g. pyvips) would fix that.
- **Grid detector accuracy** (whole-pixel spacing, period doubling/halving): see [grid-detection-v3.md](grid-detection-v3.md).
- **Bulk import of a local library** (linked folders, rescans) would add an item source whose bytes are read in place rather than staged. Revisit `kind` and `staging_key` vs a `source_path` then.
