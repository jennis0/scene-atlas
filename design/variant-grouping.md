# Variant grouping v2: bottom-up tree walk

**Status:** In progress (ADR-028). Replaces `ImageParser.group_files` for maps; groups are
identified once, when an import has finished (§3).
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

A step-by-step technical walkthrough of the algorithm is in
[variant-grouping-algorithm.md](variant-grouping-algorithm.md); this section is the summary.

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

## 3. Where it runs: once, when an import has finished

User decision (2026-10-22): **groups are minted once, at the end of an import, and the pipeline
never changes them afterwards.** The best evidence (pHash renditions, layout, embeddings) exists
only once an image is processed, so grouping waits for it rather than guessing at seal and
correcting later.

1. **Importing.** The seal only parses each path (name, tags, grid hints; `compute_plan`).
   Items are processed as before; a committed image has no group and is
   `images.awaiting_grouping`, listed nowhere (gallery, search, facets, counts, exports:
   `models.listed_images()`). Progress is per file.
2. **Identifying groups.** When the job has nothing open (every file done, a duplicate, failed or
   skipped) its status is `grouping` (`import_jobs.grouped_at IS NULL`). `group_jobs.group_job`
   runs once over all of the job's files, by **detected** type:
   - maps (battlemaps, Auto files the head called maps, and files of a map type that made no
     image) through `group_with_content`, with the images' features;
   - other types (scenes, tokens and art imported as scenes) join their folder's map group when
     the nearest effective folder above them (their own included) that holds maps holds maps of
     one group only (`group_jobs.attach_to_map_groups`; research: 0.98–0.99 precision there).
     They take no subgroup unless they sit in a folder whose maps of that group share a
     sub-group label. The rest go through `ImageParser.group_files`.

   Each group becomes an `ImportGroup` and, if any of its files made an image, a gallery group:
   an existing one with the same `(name, author)` when the name identifies the map
   (`ProposedGroup.name_is_identity`) and no other map group of the import has it, else a new
   one. The images get their group, author, subgroup and search text, and the job is
   `completed`, all in one write transaction (compute before it, outside the lock).
3. **Late files.** Retry, Include (sorted out) and Import as copy re-open the job, which clears
   `grouped_at`; when it has finished again it is grouped again. That run walks every file of the
   job for context, but places only images still awaiting a group, and moves nothing: a file
   keeps the import group it had and its image joins that group's gallery group; an import group
   without one takes the gallery group of this job its proposal overlaps most, else a new one
   (`plan_grouping`, pure).

The phase is durable (a status derived from item counts and `grouped_at`), runs in one
transaction (a crash leaves the job `grouping`, and it is grouped again), and runs one at a time
per job. It is started after the batch that settles a job, after the API actions that can
(cancel, finish without missing files), on every idle wake of the worker, at startup once the
model is ready, and by hourly maintenance. While the model is loading or switching it waits; with
no model it runs without embeddings. Lifecycle: [ingestion.md §5.8](ingestion.md#58-identifying-groups).

**Measured** (WSL, 2026-10-22, 19.8k synthetic map paths, 7,410 groups): the phase took 7.4 s, of
which 2.1 s under the write lock (mostly the image updates and their triggers); the seal's
parsing 3.4 s.

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
vectors in hand is not used. One ships for each bundled model (the image-type heads' encoders).

## 6. User edits

The pipeline never changes a group after it is minted, so user edits need no protection from it:
there is no edit provenance (an earlier design recorded `edited_at`; dropped with refinement).
The group-mutation helpers the groups API uses (reassign, merge, delete if empty, cover repair)
and the grouping phase's `mint_groups` live in `group_service`.

## 7. Scope

**In:**
- maps (battlemap and Auto items the head called maps), by the walk;
- new imports and linked-folder scans (a scan job's images appear after its grouping phase; a
  refreshed image keeps its group).

**Out (for now):**
- other image types where their folder holds several map groups (or none), which keep
  `group_files` (in the same phase);
- suggestions in the UI (computed and logged at DEBUG, not stored);
- regrouping existing libraries: migration 029 stamps every finished job grouped; one still
  running finishes into the groups its seal planned;
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
| `__init__.py` | `group_with_content()` (the pipeline's), `group_by_paths()` (paths only: the research parity bench), `effective_folders()` (seal: a file's siblings) |

### Deviations from E5

The port matched E5 narrow exactly (same partitions on the benchmark test split, 27 recipes, and
on reserved), then took these deliberate changes. Each was checked with the research parity
bench: full-content BCubed stays within noise of E5 (and the paths-only pass improved).

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
- seal: `compute_plan` (parsing only);
- features: `ingest_process`;
- the grouping phase: `group_jobs.py` (lifecycle and triggers: [ingestion.md §5.8](ingestion.md#58-identifying-groups)).

`backend/app/services/` holds the shared pieces: `group_service.py` (group mutations,
`mint_groups`) and `grouping_calibration.py` (per-encoder thresholds).

## 9. Validation

- **Port parity.** scene-atlas-learning wraps the Scene Atlas module as a bench method. It must
  match E5 (±0.005 BCubed F1) on the benchmark test split (realistic, targeted) and on the new
  makers, given the same features.
- **Feature parity.** `phash256` bit-identical to `imagehash` on fixture images; `edge` equal to
  the research descriptor within float16 tolerance.
- **Integration** (`test_grouping_phase.py`):
  - images import ungrouped and unlisted, then appear grouped;
  - twin folders become one group;
  - maps through the walk, scenes through `group_files`;
  - scenes and tokens join the one map group of their folder, not a folder of two;
  - existing-group matching, and names two maps share never match;
  - cancelled imports are grouped; the model being busy waits; a failed write leaves the job
    `grouping`; files changed meanwhile are read again;
  - late files join their group, or a new one, and nothing moves;
  - Undo removes the groups the import minted.
