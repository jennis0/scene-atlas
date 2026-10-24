# Import progress

Status: **built**. Replaces the progress view of the import dialog, adds an "import still running"
strip to the group editor, and keeps the gallery usable while an import runs (§6).

**Since 2026-10-22 (ADR-028)** an import's groups are identified once, when every file is settled:
progress is per file, then "Identifying groups…", then the report. The "now importing" group
list and the groups-done count of the 2026-10-17 design (below, §2–§3) went with it.

## 1. Why

Found on a real 5,800-file import (2026-10-17):

- **The progress view was a ledger of every group.** At 347 groups it's a long list of rows,
  most of them "waiting"; it doesn't say how long is left or what's happening now.
- **The group editor didn't say the import was still running.** Opened from the progress view, it
  listed the 103 groups finished so far, with no sign that 244 more were coming and no way back to
  the progress. It looked like the import had lost most of the folder.
- **The view re-fetched every group's counts on every poll.** Fine for 50 groups, wasteful for
  5,000.

## 2. Decisions (user, 2026-10-17)

- **One layout for every import**: overall progress, the problems in one line, and the controls.
  No group list while running (there are no groups yet); the report has them afterwards. (A short
  "now importing" list of groups was dropped in 2026-10-22 with groups at seal.)
- **Time left is measured, not modelled**: a rolling average of the time to process one map over
  the last 100 maps this session processed, times the files left.
- **The editor strip** says the import is running, offers to go back to the progress, and adds
  groups that finished since it opened when asked (never on its own, so rows don't move under the
  user).

## 3. Progress view

```
 neutral_party                                       Importing
 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━░░░░░░░░░░░░░░░░░░░░░░░░░░░
 1,695 of 4,503 files done · about 25 min left
 Sending 2,692 of 4,503 files

 98 already in your library · 3 failed: listed in the report when it finishes

 [Pause]  [Cancel import]                                [Close]
```

Once every file is settled (status `grouping`), until the groups are identified:

```
 neutral_party                                       Identifying groups
 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  (the full bar breathes)
 ⟳ Identifying groups…
```

- **Bar**: what's finished (imported, duplicate, failed or skipped) out of everything, with what's
  been received shown behind it while an upload is still sending. While the groups are identified
  the full bar pulses (not with reduced motion).
- **Line under it**: files finished and the time left once there is a rate to go on; then
  "Identifying groups…" with a spinner.
- **Problems** only when there are some.
- **Controls**: bordered buttons with icons, Pause / Resume and Cancel on the left; Close and
  **Review N groups** (the one solid button, once the groups exist) on the right. The two sides
  wrap as units on narrow windows. The report uses the same footer (Undo import | Done, Review in
  editor).
- **Closing a running import** shows a toast ("… is still importing; follow it from Activity")
  rather than a permanent "keeps running if you close this" hint in the footer (user, 2026-10-17).
- The system-pause, connection, waiting-for-folder, upload-interrupted and send-failure notices
  stay as they are. The dock row says "Identifying groups" for a job in that phase.

## 4. Backend

- **Rate**: `ProcessingRate` (`backend/pipeline/ingest_rate.py`) keeps the last batches' (files,
  seconds) until they cover 100 files; `seconds_per_item` is their total seconds over total files.
  The worker records each batch's wall time and the files it settled (refunded files, from a
  system pause or a missing folder, don't count). In memory only: a restart starts a new session.
  Exposed as `queue.seconds_per_item`.
- **Job summary**: per-file `counts`, the status (`grouping` between the last file and the
  groups, [ingestion.md §5.8](ingestion.md#58-identifying-groups)), `group_count` (import groups:
  none until grouped), `groups_reviewable` (gallery groups the editor can open: an imported image
  from this job, once the job is grouped) and `grouped_at`, from one grouped query each across the
  listed jobs. The detail lists the reviewable groups as `reviewable_group_ids`; the frontend
  never re-derives the rule.
- **Detail**: `GET /imports/{id}`, the job with its groups (none while importing). The progress
  view doesn't fetch it.

Time left = open files (awaiting bytes, ready, processing) × `seconds_per_item`. With several
imports running at once the worker shares its time between them, so each one's estimate is
optimistic; good enough, and it corrects itself as the rate is measured.

## 5. Group editor strip

Shown when the editor was opened from an import that hasn't finished:

```
 ⟳ Import still running · 1,695 of 4,503 files done      [Show progress]
   12 more groups are ready                               [Add them]
```

With groups minted at the end, the editor is opened on a running import only when late files
(a retry, an include) re-opened a finished one.

- `useGalleryDialogs` keeps the job id with the review's group ids.
- **Show progress** closes the editor (pending metadata saves are flushed as on any close) and
  opens the import dialog.
- **Add them** fetches the job's groups and appends the new reviewable ids; the editor's
  import-review loader already loads only ids it hasn't seen.
- **Only grouped imports' groups are reviewable** (`groups_reviewable` in the summary,
  `reviewable_group_ids` in the detail; ADR-028): groups exist once every file is settled and
  the grouping phase has run, and a re-opened import's groups wait until its late files are
  grouped too. The finished toast's Review falls back to the import dialog if the import isn't
  grouped yet.
- When the import finishes the strip says so ("Import finished · 347 groups") and still offers to
  add the rest.

## 6. Gallery and imports

Found on the user's large library (2026-10-18): the gallery reset its grouped results every 4 s
while an import ran. Each reset showed "Searching…" for the seconds the search took on a large
library and threw away the scrolled-in pages, so the app was unusable for the length of an import.

Decisions (user, 2026-10-18):

- **Never clear the grid for an import.** `refreshGalleryInPlace` (`lib/queryKeys.ts`) refetches
  in the background and swaps the results in when they arrive. Grouped results are trimmed to
  their first page first, so the refetch is one request and later pages load against the new
  order. A refetch already running is left to finish (`cancelRefetch: false`) so a search slower
  than the interval still lands.
- **Refresh when an import is grouped.** An import's images are listed nowhere until its groups
  are identified (ADR-028), so they appear all at once. `useImportGalleryRefresh` refreshes (at
  most every 4 s) when the latest `grouped_at` of the listed imports moves past the latest seen
  (`latestGroupedAt`; the first value once the list has loaded is a baseline, and an older one, a
  dismissed or re-opened import, changes nothing), or an import finishes, and only while the
  results are scrolled to the top (within 120 px) and the image viewer is closed. Anything else
  waits until the user is back at the top. (Until 2026-10-22 it also refreshed while an import
  ran, as images landed.)
- **No "N new maps" pill.** The user didn't want one; the gallery catches up silently.
- **A turn-off threshold (refresh off above N maps) was rejected**: the cost is the reset, not
  the library size.
- **Facets refresh when an import finishes**, and with the results while the library is empty,
  where they gate the welcome screen. The Activity dock shows progress.

The scroll position is read from the element marked `data-results-scroller` (ImageGrid, and the
grouped view's container in `Gallery`), via a capture-phase scroll listener on `<main>`.

Grouped pages are fetched by offset, so groups added since a page loaded shift the next page onto
groups already shown; `useGroupSearch` keeps each group once (`groupKey`).

## 7. Tests

Backend: rate window and refunds; per-file progress then groups (`test_progress_fields`); the
grouping phase (`test_grouping_phase.py`). Frontend: time-left formatting, the progress view
(files done, "Identifying groups…", problems line, review count, controls), the editor strip
(running, ready count, add, show progress, finished), the gallery refresh rules
(`useImportGalleryRefresh.test.tsx`), in-place refresh (`queryKeys.test.ts`) and group
de-duplication across pages (`useGroupSearch.test.tsx`).
