# Group editor: metadata first, details on demand (plan)

Status: **planned**, not started. Branch `feature/editor-metadata-first` (stacked on
`feature/visual-refresh`). Related: [frontend.md](frontend.md) (editor and import review),
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

## Open questions

- Should bulk actions across *all* of a very large import be allowed without a
  confirmation ("Add tag 'Night' to 13,402 images?")?
- Undo for bulk edits: today there's none. Worth adding with the new endpoint (return the
  previous values), or out of scope?
- The All view at 13k images is still a long scroll. Is All the right default for very
  large imports, or should the editor open on the first group with All one click away?
