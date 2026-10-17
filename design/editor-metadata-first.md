# Group editor: metadata first, details on demand (plan)

Status: **done** (phases 1–3). Phase 3 shipped bulk edits by id, without lazy details: see
"Phase 3 as built". Branches `feature/editor-metadata-first` (phases 1–2) and
`feature/editor-bulk-edit` (phase 3). Related: [frontend.md](frontend.md) (editor and import review),
[ingest-redesign.md](ingest-redesign.md), [search.md](search.md).

## Why

The group editor (`EditGroupDialog`) holds every group's full detail in memory before
anything can be edited, and renders every file card in the All view. That's fine for a
pack and doesn't scale to large imports (the reference library is ~56k images; one
folder import can plan thousands of groups).

Measured 2026-10-17, local backend, Caeora import (68 groups, 454 images):

| | |
|---|---|
| `GET /groups/{id}` | median 4.1 ms, 4.7 KB; ~1.24 KB per image |
| 68 groups, one request at a time | 0.3 s |
| 68 groups, 8 at a time | 1.5–1.9 s (the backend serialises group reads; parallel requests contend) |
| Editor: first groups shown | ~0.3 s |
| Editor: all 68 loaded | ~1.6 s (was ~2.3 s before batching was tuned) |
| All view DOM | all 454 file cards rendered; nothing virtualised |

The remaining load time is rendering, not the network: each appended batch re-renders
every file card. Extrapolating to ~2,000 groups / ~13k images: ~9 s of requests, ~16 MB
of group detail, and ~13k file cards in the DOM, which will hang the tab long before the
data finishes arriving.

## The constraint that shapes the design

Every editor change, including bulk actions in All, is saved by `autoSaveGroup`:
a full `PUT /groups/{id}` whose `images` field is **the list of images to keep**
(`GroupEditRequest`). Images missing from it are deleted. So a group must never be saved
unless all its files are loaded. Today that holds only because everything is loaded up
front. A lazy editor needs the save path to stop depending on full group state for
file-level edits.

Bulk file actions (`bulkAddTag`, `bulkSetGrid`, `bulkSetImageType`, `bulkSetSubgroup` in
`useFileEditing`) currently mutate in-memory file state and then re-PUT every affected
group. There is no bulk image endpoint, only `PATCH /images/{id}` and
`POST /tags/image/{id}`, one image at a time.

Group-level operations (`merge`, `delete`, `moveImages`) are already id-based and work
without file detail.

## Design

### Backend

1. **Group summaries** — `POST /api/v1/groups/summaries` `{ids: number[]}` →
   `[{id, base_name, author, image_count, primary_image_id, image_ids}]`, one query.
   Enough for the sidebar, the All counts, selection by id, and bulk actions.
   (POST so thousands of ids don't hit URL limits.)
2. **Batch details** — `POST /api/v1/groups/details` `{ids}` → `GroupDetailResponse[]`,
   one query (the same `selectinload`s as `GET /groups/{id}`), capped (e.g. 100 ids).
   Replaces N single-group requests.
3. **Bulk image edit** — `POST /api/v1/images/bulk-edit`
   `{image_ids, set?: {image_type?, gridded?, grid_type?, grid_width?, grid_height?, subgroup?}, add_tags?: [{category, value}], remove_tags?: [...]}`
   in one transaction, returning the updated count. It must have the same side effects
   as `PATCH /images/{id}` and `POST /tags/image/{id}` (search text, LanceDB metadata if
   any field is mirrored there, tag counts), so the first step is to list those side
   effects and share the code rather than duplicate it.

Query counts for 1 and 2 get pinned in `integration/test_query_counts.py`.

### Frontend

1. **Load summaries first.** The editor opens with every group in the sidebar and the
   correct counts immediately. `EditableGroupState` gains `loaded: boolean`; `files` is
   empty until loaded, with `imageIds` and `imageCount` from the summary.
2. **The safety rule, enforced in one place.** `autoSaveGroup` refuses (and logs) a group
   that isn't loaded. A unit test asserts that no editor path PUTs an unloaded group.
3. **Bulk actions go by id.** When a bulk action's scope includes unloaded groups, it
   calls `bulk-edit` with the image ids from the summaries, applies the change locally to
   loaded groups, and marks unloaded ones stale (refetched when opened). Within loaded
   groups it can keep today's path or also use `bulk-edit`; using it everywhere is
   simpler and cheaper than re-PUTting groups.
4. **Virtualised All view.** Group sections in a `@tanstack/react-virtual` list (already a
   dependency, used by the gallery and import ledger). Sections entering the viewport
   request their details through the batch endpoint (debounced, a few at a time), with
   a placeholder of the right height from `imageCount`. Selecting a group in the sidebar
   loads it first.
5. **Per-group editing is unchanged** once a group is loaded: rename, reorder, split,
   subgroups and per-file edits still save through `PUT /groups/{id}`.

Mass edit (search results) and import review both start from ids, so both use the same
path; single-group edit is a one-group case of it.

## Phases

Each phase ships on its own and leaves the app working.

1. **Batch + summaries endpoints; load summaries first, details in background batches.**
   Sidebar and counts are instant; details still all load (via the batch endpoint, so far
   fewer requests). Low risk: the save path doesn't change. *Small–medium.*
2. **Virtualise the All view.** Removes the render cost, the actual bottleneck at scale.
   Independent of the save path. *Medium.*
3. **Bulk image edit endpoint; route bulk actions through it; then load details only on
   demand.** Lazy loading is only safe after this. *Medium–large.*

## Tests and checks

- Backend: endpoint tests for all three, including bulk-edit side effects matching the
  single-image endpoints; pinned query counts.
- Frontend: "never saves an unloaded group"; bulk action over loaded + unloaded groups;
  virtualised All view renders only visible sections; opening on a start group.
- A synthetic large import (e.g. 2,000 groups) as a perf fixture, with the same timings as
  the table above recorded before and after each phase.

## Phase 1 as built

- `POST /groups/summaries` (up to 5,000 ids) and `POST /groups/details` (up to 100) in
  `backend/app/api/groups.py`. Both return groups in the order asked, de-duplicated, and
  leave out ids that no longer exist. `groupApi.summaries` and `groupApi.details` split
  bigger requests into chunks and send them one after another.
- Import review fetches summaries, then details in a queue (`nextReviewBatch`): the start
  group or a clicked placeholder goes alone and first, then a batch of 8, then 40s.
- **Unloaded groups are not editor state.** They're kept in `pendingGroups` and shown as
  placeholder rows. The plan had a `loaded` flag on `EditableGroupState`. Keeping them out
  instead means no existing code path (save, bulk actions, scope, counts) can meet an
  unloaded group, so the save path really is unchanged. Phase 3 brings them into editor
  state, with the `loaded` flag and the save guard, once bulk edits go by id.
- While groups are loading, All says its changes apply only to the loaded groups.
- Opening on All is capped at `ALL_VIEW_IMAGE_LIMIT` (500 images); above it, review opens
  on the first group.
- Mass edit uses the details endpoint (500 groups is 5 requests instead of 500).

Measured on the scratch library (92 groups): summaries for all of them took 5 ms (12 KB).
Details in batches of 40 took ~150 ms, against ~380 ms for 92 single requests.

## Phase 2 as built

The All view isn't a list of group sections: it's one two-column grid of every in-scope
file, split by subgroup label (across groups). So the virtualised unit is a **row**: a
subgroup heading or a pair of cards (`buildFileRows` in `edit-group/fileRows.ts`),
rendered by `VirtualFileRows` in `EditGroupFileGrid` with `@tanstack/react-virtual`,
measured as they mount.

- Only from 60 files (`VIRTUALIZE_FROM`). Below that the grid renders whole, as before,
  keeping sticky subgroup headings and one drop target per subgroup section. Windowed
  rows lose both: headings scroll with their row, and each row is its own drop target
  for its subgroup (`DroppableSubgroupSection` `idSuffix`; drops read the subgroup from
  the target's data, not its id).
- The scroll container is held in state through a callback ref, not `useRef`: the
  virtualiser reads it in its first layout effect, which runs before a parent's ref is
  attached, and with a ref it never measured the viewport and rendered nothing.
- Applies to every view with many files: All, a multi-selection, or one large group.

Measured: Edit all over 92 groups / 515 files opens in ~1.5 s with 14 images in the DOM,
against ~2.5 s with all 515 rendered. Per-change re-renders now touch only the visible
rows, which is what made editing in a large All view sluggish.

## Phase 3 as built

- `POST /images/bulk-edit` and `POST /images/bulk-restore` (undo), and
  `POST /groups/bulk-update` (author), in `services/bulk_edit_service.py`; see
  [backend.md](backend.md) for the side effects they share with the single-image endpoints.
- The toolbar's bulk actions go through `useBulkImageEdit`: one request, applied locally at
  once (without a group save), reverted if the request fails, a confirmation from 500
  images, and Undo in the toast.
- Author and name save on blur only when changed. Before, leaving the author field on All
  re-saved every group in scope even if nothing changed: 500 `PUT`s, ~20 s, each rewriting
  the group's tags.
- The card type toggle got `aria-pressed`.

### Why there are no lazy details

The plan ended with loading a group's files only when it scrolls into view. Measured on a
synthetic library of 500 groups × 26 images (13,000, the most Edit all can open), production
build:

| | |
|---|---|
| Open Edit all | ~4.8 s: 1.7 s the `/search/groups` id fetch, ~2.1 s five details batches, the rest render |
| JS heap | ~55–65 MB |
| Bulk type change, 13,000 images | ~2.6 s (server ~1.7 s); undo ~2.9 s |
| Three keystrokes in the author field | ~250 ms |

Lazy details could save at most the ~2 s of details. Against that, the All view's file grid is
sorted by subgroup (unknown until a group's files arrive), and selection and the file filter
work on file data, so unloaded groups couldn't be selected or filtered. Not worth it at this
size. If libraries grow past this, the cheaper next steps are virtualising the sidebar (its
500 rows are most of a keystroke's render) and a faster id fetch for Edit all.

## Decisions (2026-10-17)

- **Large bulk actions ask first**, from 500 images: "Set type to scene on 13,000 images?"
  (done in phase 3).
- **Bulk edits get undo:** `bulk-edit` returns the previous values, and the toast's Undo
  sends them back (done in phase 3).
- **Very large imports open on the first group**, with All one click away (done in phase
  1, see above).
