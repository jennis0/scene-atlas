# Variant grouping v2: bottom-up tree walk

**Status:** In progress (ADR-028). Replaces `ImageParser.group_files` for maps.
**Research:** scene-atlas-learning `docs/variant-grouping-results.md` (experiments E0–E5) and
`docs/superpowers/specs/2026-10-21-variant-grouping-design.md`. The algorithm is E5
(`grouping/e5/`), Joe's bottom-up tree walk, in narrow mode.

## 1. Why

`group_files` groups from paths alone. On the research benchmark (28k maps from four makers,
realistic folder layouts) it scores BCubed F1 0.67; on new makers' real folders 0.58. The
failures are structural:

- the second folder is read as the group whatever it is (packs and topic folders lump);
- a greedy sorted-prefix chain collapses whole makers (`Moonlight_Maps_*`: 55 maps in one group);
- there is no content evidence, so gridded/gridless twins in different folders never join
  and coincidental prefixes never split.

E5 scores 0.976 on the benchmark and 0.944 on new makers, with no whole-folder lumps.

## 2. The algorithm (E5, narrow mode)

Inputs: a set of files with paths relative to the import root and, optionally, content features
per file. The output is a partition into groups, a sub-group label per file, a reason for every
join, and suggestions (joins it deliberately does not make).

**Effective tree.** Rendition folders (grid / format / DPI / size / platform words, or the
parent's name plus such words: `Beast Prison 12x12`, `VTT`, `70 DPI (VTT)`) and variant
folders (`Night`, `Winter`) are transparent: their files belong to the parent. Siblings whose
names differ only by such words (`Forest Road Gridded` / `Forest Road Gridless`) collapse.

**Names.** Tokens minus variant, rendition and size words and numbers give a file's identity.
Series numbers are kept (`vol#4`). Before keys are cut, tokens shared by nearly every file are
judged per folder (folder IDF):
- a *house prefix* when many distinct multi-token names remain after them (`leasealairMaps_…`):
  strip them;
- the *map's name* when only variant words remain: keep them, as evidence the folder is one map.

Numbered families with no name (`IMG_0012`, `NumberedGLMaps_52`) carry no identity.

**Walk.** Each effective folder is processed deepest first.
1. **Own files.** Link on certain evidence and take connected components:
   - pHash renditions (≤ 12 of 256 bits, same aspect);
   - same identity name.

   Then add probable evidence by agreement only: edge-map correlation **and** embedding cosine
   both high, never against different name keys. Then:
   - shared 2-token base (gated by cohesion in house-prefix folders and in large families);
   - folder-named map.

   A content split stands unless names or folders give positive evidence.
2. **Container or meaningful parent.** A folder is a container if it is the root, has a
   generic name (`Maps`, `Pack 03`), has a name recurring elsewhere in the tree (author or
   topic folders), has a house-prefix name, or holds too many units. The ascent stops at a
   container.
3. **Meaningful parent.**
   - Join its units on the same certain evidence across them.
   - **The parent is the evidence:** units in different child folders join as sub-groups when a
     cohesion and production-fingerprint gate allows it (embedding cohesion, aspect, `NxM`).
   - Unnamed parts (`1st_Floor.png`) join a folder-named map.
   - Similarity alone never joins: sub-groups need a folder or a meaningful shared key.
4. **Cross-tree (narrow).** pHash renditions anywhere, except between two large groups.
   Everything else is a suggestion.

Sub-group labels come only from joined child folders, or from level names (`floor 2`, `roof`).

## 3. Where it runs

Content features exist only after the ingest worker has processed an image, but groups are
planned at seal time. Grouping therefore runs twice:

| Pass | When | Evidence | Effect |
|---|---|---|---|
| **Seal** | `compute_plan`, before the write lock (as `seal_scan` already did) | paths only: tree, names, containers, parent rules without the content gate (see below) | creates the import groups |
| **Refinement** | per partition as each finishes (imports of more than 500 maps), then over the whole job once its last item is committed and its vectors written | paths + pHash256 + edge map + embeddings | **merges only**, within the partition / job |

Merge-only is by construction: refinement re-runs the full walk and, for each resulting group,
merges the gallery groups it touches. It never splits. That is safe because content only
*adds* joins (renditions, agreement, cohesion-gated parents), and at seal time every
content-gated join is withheld rather than guessed.

**Seal matching.** A map group adds to an existing gallery group with the same `(name, author)`
only when its name identifies the map (`ProposedGroup.name_is_identity`) and no other map group
of the import has that name: the seal can leave one map split under one name (a folder-named
folder whose parts are joined only by content), and such a name says nothing about which map it
is. Files already settled at seal (failed or skipped by the manifest) take no part.

**Eligible groups.** Refinement only touches gallery groups that:
- this job created (`ImportGroup.merged_into_existing = false`), and
- the user has not edited (`variant_groups.edited_at IS NULL`).

It never reshapes pre-existing groups or another job's groups. An eligible group the content walk
spreads over two of its groups (paths and content disagree, which merge-only says shouldn't
happen) is left exactly as it is: merging through it would chain the two together.

**Partitions** (user decision 2026-10-22: groups become reviewable as they close). An import with
more than `PARTITION_MIN_MAP_FILES` (500) map files is sealed with a partition per import group:
its effective top-level folder (`partition_keys`; rendition and variant folders are transparent,
root files are `""`). A seal group never spans two, since the walk never joins top-level folders
from paths (the root is a container). As soon as none of a partition's items is open, the walk
runs over all of the job's map items, with content features only for the partition's (the
others join by names and folders only, as at seal: name analysis depends on the whole file set,
so a partition-only walk could break merge-only), and merges within the partition's eligible
groups; its import groups are
stamped (`import_groups.grouping_refined_at`) and become reviewable. When the whole job has
finished, the whole-job pass below runs once more over everything, which adds the joins across
partitions (cross-tree renditions, `x1`). Both are merge-only. Smaller imports have no partitions
and get only the whole-job pass.

**Trigger.** A job is due when it is sealed, has nothing open (completed, or cancelled with
nothing left processing) and `grouping_refined_at IS NULL`; a partition when none of its items is
open and one of its import groups isn't stamped. `process_batch` submits, after `write_vectors`,
the job its batch touched if due, else the due partitions of the batch's import groups (one
grouped query). The worker's idle loop sweeps every due scope at most once a minute (jobs finished
without a batch: cancel, skip, finish without missing files; and deferred runs). Because
JobRunner state is lost on restart, startup (once the model has loaded) and the hourly
`ingest_maintenance` sweep too. One run per scope (job, or job and partition) at a time.
Re-opened items (retry, import as copy, include sorted-out) clear their partitions' stamps
(`_unrefine`) and the job's (`recompute_job_status`), so they refine again when they finish.
Refinement is idempotent.

**Model availability.** While the model is loading or switching (the worker is held), a run is
deferred and a later sweep runs it; with no model at all it runs without embeddings.

**Reviewable.** A gallery group becomes reviewable in the import editor only once every import
group of the job feeding it is closed and stamped (its partition, or the whole job, refined), so
the editor doesn't show a group a pass is about to merge. The whole-job pass after partitions may
still merge a reviewed group away (a twin across top-level folders); the editor drops groups that
no longer exist. The job summary's `grouping_refined_at` is the latest stamp, and the gallery
refreshes when it changes. Re-opened items clear their partitions' stamps and the job's.

**Apply.**
1. Compute outside any transaction. The walk runs over every map item the seal grouped, those
   that made no image included (by path), so its tree is the seal's; `known_authors` are the
   creators of groups that existed when the job was sealed.
2. In one short `write_session()`: nothing if the job was undone, re-opened or refined
   meanwhile; read again if it finished again. Otherwise re-read membership (images may have
   moved or been deleted) and eligibility, plan with the pure `plan_merges`, and merge into the
   group with the most images (ties: lowest id), keeping its id, name, author and cover.
3. Re-point every `ImportGroup.image_group_id` that named a merged group, so Undo still finds
   the survivor.
4. Update `Image.author`, `search_text` and `subgroup` (`group_service.merge_groups`).
5. Set `grouping_refined_at` and `bump()` the worker.

## 4. Content features

New table `image_grouping_features(image_id PK, version, phash256 BLOB(32), edge BLOB(2048))`.
It is computed in `_decode` from the large (800 px) thumbnail next to the existing pHash, and
rewritten on linked refresh.
- **`phash256`:** DCT pHash identical to `imagehash.phash(hash_size=16)`, the research
  catalog's hash. The rendition threshold transfers unchanged. The existing 64-bit `phash`
  column is untouched.
- **`edge`:** the research layout descriptor. Grayscale 64×64 bilinear, central-difference
  gradient magnitude pooled to 32×32, z-scored, float16.
- **Embeddings:** the active model's vectors from LanceDB. Missing vectors are allowed; for
  those images the embedding rules don't fire.

Both features flatten transparency onto white first, as the research thumbnails did. The edge
is stored z-scored, so `a @ b / 1024` is the Pearson correlation.

Measured parity (A3, 399 real maps, research thumbnail path vs Scene Atlas's):
- **opaque maps (JPEG):** mean 0.9 bits apart, max 6; none past the 12-bit rendition threshold;
- **transparent tokens and assets (WebP):** mean 1.9, max 22 (2% past 12);
- **edge correlation:** at least 0.996.

Videos and failed decodes have no features; they group by names only. Images imported before
migration 029 have no feature row (no backfill yet).

## 5. Per-model calibration

The embedding thresholds (agreement, parent cohesion, whole-folder cohesion, large-family
gate) depend on the encoder. They ship as `backend/app/data/heads/grouping/<vision encoder
sha256>.json`, following the image-type head pattern, and are produced by scene-atlas-learning
from Scene Atlas–style ONNX embeddings. If no calibration matches the active encoder, the
embedding rules are switched off (renditions, names and folders still work).

Format `scene-atlas-grouping-calibration/1` (`grouping_calibration.py`): `encoder_sha256` (also
the file's stem), `embedding_dim`, and `thresholds` with exactly the research's names
`agree_emb`, `coh`, `coh_all`, `coh_key`, `coh_suggest` (→ `EmbeddingThresholds.agree`,
`parent`, `whole_folder`, `shared_base`, `suggest`), each in [-1, 1]. Files are loaded once; a
malformed one is logged and skipped. A calibration whose `embedding_dim` doesn't match the
vectors in hand is not used. None ship yet, so embedding rules are off until the research side
produces them.

## 6. Provenance

`variant_groups.edited_at` is set by every user edit of a group's metadata or membership
(`group_service.mark_edited` / `mark_groups_edited`):

- `api/groups.py`: edit (rename, author, per-image deletes and updates), split (the group and
  each new one), move (source and target), merge (the survivor), bulk author
  (`bulk_edit_service.set_groups_author`);
- `api/images.py`: a subgroup change (`PATCH /images/{id}`), deleting an image;
- `bulk_edit_service`: a bulk subgroup change and its undo (only groups whose subgroups change).

Tag, grid and type edits are not group structure and leave it alone. Refinement never touches an
edited group, and doesn't mark the groups it merges. This is the same rule as `grid_source = user`.
The group-mutation helpers (reassign, merge, delete if empty, cover repair) live in
`group_service`, shared by the API and refinement.

## 7. Scope

**In:**
- maps (battlemap and Auto items);
- new imports and linked-folder scans (each scan job refines its own new images).

**Out (for now):**
- other image types, which keep `group_files`;
- suggestions in the UI (computed and logged at DEBUG, not stored);
- attaching tokens and scene art to map groups;
- regrouping existing libraries: migration 029 marks every job sealed before it
  `grouping_refinable = false` and stamps it refined, so refinement never runs on imports the old
  parser grouped (their groups may have been curated before `edited_at` existed);
- cross-import joins beyond the existing exact `(name, author)` match.

## 8. Code

`backend/app/services/variant_grouping/` is pure (no DB, no I/O), typed and unit-tested:

| Module | Contents |
|---|---|
| `vocab.py` | word lists |
| `names.py` | tokens, identity, folder IDF, hubs, levels |
| `tree.py` | effective tree |
| `evidence.py` | features, candidate pairs, pair signals; numpy, blocked, CPU |
| `cohesion.py` | unit gates: cohesion, production fingerprint, average linkage, whole-folder test |
| `walk.py` | the walk, with `GroupingParams` and the per-folder decision log |
| `naming.py` | group names and authors, via `ImageParser`'s public `clean_group_name` / `author_from_stem` |
| `schema.py` | `GroupingFile`, `ProposedGroup`, `Suggestion`, `Grouping` |
| `__init__.py` | `group_by_paths()` and `group_with_content()` (both take `known_authors`) |

### Deviations from E5

The port matched E5 narrow exactly (same partitions on the benchmark test split, 27 recipes, and
on reserved), then took these deliberate changes. Each was checked with the research parity
bench: full-content BCubed stays within noise of E5, merge-only holds, the seal pass improves.

- **Dropped:** local / global modes, ablation switches, learned axis words, content-component
  sub-groups, the `kcap` family cap (1000, never reached), unused signals (struct map, pixel dims).
- **Missing features are withheld:** a missing pHash is never a rendition (E5 read two missing
  hashes as 0 bits apart), a missing aspect is never compatible, and the whole-folder test (c0)
  needs every unit to have an embedding.
- **Small maker prefixes:** a 2-token key made only of an enclosing folder's name
  (`Moonlight Maps/…/Moonlight_Maps_…`) is a house prefix, not a shared base, when ≥2 distinct
  multi-token names follow it (folder IDF generalised to small folders).
- **Variant-only folders (a6):** a specific-named leaf folder whose files have no identity
  (`Golden Forest/Night.webp`) is one map at seal, as `group_files` Pass 0.
- **Rooms are not generic:** `library` and `archive` (and plurals) left the generic-folder words.
- **Level designators** trailing a file's identity (`Inn_Basement`, `…_Upper_Level`) are cut
  from it, so one-word maps join their floors with level sub-groups. The agreement veto keeps
  them (`veto_key`), so it is as strong as E5's.
- **Naming** (new; E5 had none): folder names only when the folder is named after its files,
  is an a6 folder, or is a meaningful folder holding exactly the group below the top level or
  whose children it joined; trailing level words and `by <Author>` dropped from identity names;
  fallback names are the first file's cleaned stem (`name_is_identity = False`). Author: a
  folder named after a known author, else a folder named by a stripped house prefix, else the
  parser's author with leading rendition folders skipped; root files have no author.
- **Determinism:** set-order tie-breaks made explicit; files are walked in path order.

`backend/pipeline/` holds the DB glue:
- seal: `compute_plan` (`_plan_maps`);
- features: `ingest_process`;
- refinement: `refine_groups.py` (lifecycle and triggers: [ingestion.md §5.8](ingestion.md#58-grouping-refinement)).

`backend/app/services/` holds the shared pieces: `group_service.py` (group mutations and
provenance) and `grouping_calibration.py` (per-encoder thresholds).

## 9. Validation

- **Port parity.** scene-atlas-learning wraps the Scene Atlas module as a bench method. It must
  match E5 (±0.005 BCubed F1) on the benchmark test split (realistic, targeted) and on the new
  makers, given the same features.
- **Feature parity.** `phash256` bit-identical to `imagehash` on fixture images; `edge` equal to
  the research descriptor within float16 tolerance.
- **Seal-time quality.** The paths-only pass is measured on the benchmark; it should not be
  worse than `group_files`. Merge-only is checked: full-walk groups never split a seal group.
- **Integration.**
  - seal + refinement merge twin folders;
  - edited groups are untouched;
  - Undo after refinement removes the job's groups;
  - re-opened jobs refine again;
  - the editor gates on refinement.
