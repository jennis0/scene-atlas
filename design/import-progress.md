# Import progress

Status: **built**. Replaces the progress view of the import dialog, adds an "import still running"
strip to the group editor, and keeps the gallery usable while an import runs (§6).

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

- **One layout for every import**: overall progress, a short "now importing" list, the problems
  in one line, and the controls. No full group list while running; the report has it afterwards.
- **Time left is measured, not modelled**: a rolling average of the time to process one map over
  the last 100 maps this session processed, times the files left.
- **The editor strip** says the import is running, offers to go back to the progress, and adds
  groups that finished since it opened when asked (never on its own, so rows don't move under the
  user).

## 3. Progress view

```
 neutral_party                                       Importing
 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━░░░░░░░░░░░░░░░░░░░░░░░░░░░
 1,695 of 4,503 files · 103 of 347 groups · about 25 min left
 Sending 2,692 of 4,503 files

 NOW IMPORTING
   Forest Ponds Expert            ━━━━━━━░░░░   12 / 18
   Frozen Lake                    waiting

 98 already in your library · 3 failed: listed in the report when it finishes

 [Pause]  [Cancel import]              [Review 103 groups]  [Close]
```

- **Bar**: what's finished (imported, duplicate, failed or skipped) out of everything, with what's
  been received shown behind it while an upload is still sending.
- **Line under it**: files finished, groups finished (no open items), and the time left once there
  is a rate to go on.
- **Now importing**: the first three groups, in processing order, that still have open items.
- **Problems** only when there are some.
- **Controls**: bordered buttons with icons, Pause / Resume and Cancel on the left; Close and
  **Review N groups** (the one solid button; opens the editor on the groups that have images so
  far) on the right. The two sides wrap as units on narrow windows. The report uses the same
  footer (Undo import | Done, Review in editor).
- **Closing a running import** shows a toast ("… is still importing; follow it from Activity")
  rather than a permanent "keeps running if you close this" hint in the footer (user, 2026-10-17).
- The system-pause, connection, waiting-for-folder, upload-interrupted and send-failure notices
  stay as they are.

## 4. Backend

- **Rate**: `ProcessingRate` (`backend/pipeline/ingest_rate.py`) keeps the last batches' (files,
  seconds) until they cover 100 files; `seconds_per_item` is their total seconds over total files.
  The worker records each batch's wall time and the files it settled (refunded files, from a
  system pause or a missing folder, don't count). In memory only: a restart starts a new session.
  Exposed as `queue.seconds_per_item`.
- **Job summary**: `groups_done` (groups with no open items) and `groups_reviewable` (gallery
  groups the editor can open: an imported image from this job and no unfinished import group of
  this job adding to them), from one grouped query each across the listed jobs. The detail lists
  them as `reviewable_group_ids`; the frontend never re-derives the rule.
- **Detail**: `GET /imports/{id}?groups=active&limit=3` returns only the first `limit` groups with
  open items. The default (`all`) is unchanged; the report uses it.

Time left = open files (awaiting bytes, ready, processing) × `seconds_per_item`. With several
imports running at once the worker shares its time between them, so each one's estimate is
optimistic; good enough, and it corrects itself as the rate is measured.

## 5. Group editor strip

Shown when the editor was opened from an import that hasn't finished:

```
 ⟳ Import still running · 103 of 347 groups              [Show progress]
   12 more groups are ready                               [Add them]
```

- `useGalleryDialogs` keeps the job id with the review's group ids.
- **Show progress** closes the editor (pending metadata saves are flushed as on any close) and
  opens the import dialog.
- **Add them** fetches the job's groups and appends the new reviewable ids; the editor's
  import-review loader already loads only ids it hasn't seen.
- **Only finished groups are reviewable** (`groups_reviewable` in the summary,
  `reviewable_group_ids` in the detail): a gallery group is held back until every import group adding to it
  has nothing awaiting bytes, ready or processing. A group loaded while still filling missed
  the images that landed later, and before deletion was made explicit an edit to it deleted
  them.
- When the import finishes the strip says so ("Import finished · 347 groups") and still offers to
  add the rest.

## 6. Gallery while importing

Found on the user's large library (2026-10-18): the gallery reset its grouped results every 4 s
while an import ran. Each reset showed "Searching…" for the seconds the search took on a large
library and threw away the scrolled-in pages, so the app was unusable for the length of an import.

Decisions (user, 2026-10-18):

- **Never clear the grid for an import.** `refreshGalleryInPlace` (`lib/queryKeys.ts`) refetches
  in the background and swaps the results in when they arrive. Grouped results are trimmed to
  their first page first, so the refetch is one request and later pages load against the new
  order. A refetch already running is left to finish (`cancelRefetch: false`) so a search slower
  than the interval still lands.
- **Refresh only where new maps would show up.** `useImportGalleryRefresh` refreshes (at most
  every 4 s) only while the results are scrolled to the top (within 120 px) and the image viewer
  is closed (it indexes into the results). While an import runs it also needs new maps to land
  at the top: newest first with no search text, so a name sort or a search isn't reshuffled
  every few seconds. Once an import finishes, being at the top is enough. Anything else waits
  until the user is back at the top.
- **No "N new maps" pill.** The user didn't want one; the gallery catches up silently.
- **A turn-off threshold (refresh off above N maps) was rejected**: the cost is the reset, not
  the library size.
- **Facets refresh when an import finishes**, not on every tick, except while the library is
  empty, where they gate the welcome screen and must update as soon as the first maps land. The
  scene count in the results bar therefore holds still during an import; the Activity dock
  shows progress.

The scroll position is read from the element marked `data-results-scroller` (ImageGrid, and the
grouped view's container in `Gallery`), via a capture-phase scroll listener on `<main>`.

Grouped pages are fetched by offset, so groups added since a page loaded shift the next page onto
groups already shown; `useGroupSearch` keeps each group once (`groupKey`).

## 7. Tests

Backend: rate window and refunds; summary group counts; `groups=active`. Frontend: time-left
formatting, the progress view (now-importing rows, problems line, review count, controls), the
editor strip (running, ready count, add, show progress, finished), the gallery refresh rules
(`useImportGalleryRefresh.test.tsx`), in-place refresh (`queryKeys.test.ts`) and group
de-duplication across pages (`useGroupSearch.test.tsx`).
