# Variant grouping v2: bottom-up tree walk

**Status:** In progress (ADR-028). Replaces `ImageParser.group_files` for maps; groups are
identified once, when an import has finished (§3).
**Research:** scene-atlas-learning `docs/variant-grouping-results.md` (experiments E0–E7: the
benchmark, the deliberate deviations of the port, per-model thresholds) and
`docs/superpowers/specs/2026-10-21-variant-grouping-design.md`. The algorithm is Joe's bottom-up
tree walk (E5), made scale-invariant (E6), with scenes added (E7).

## 1. Why

`group_files` groups from paths alone. On the research benchmark (28k maps from four makers,
realistic folder layouts) it scores BCubed F1 0.67; on new makers' real folders 0.58. The
failures are structural:

- the second folder is read as the group whatever it is (packs and topic folders lump);
- a greedy sorted-prefix chain collapses whole makers (`Moonlight_Maps_*`: 55 maps in one group);
- there is no content evidence, so gridded/gridless twins in different folders never join
  and coincidental prefixes never split.

The walk scores 0.98 on the benchmark and about 0.95 on new makers, with no whole-folder lumps
(the research log has the per-experiment numbers).

## 2. The algorithm

The algorithm, step by step and with every rule, is in
[variant-grouping-algorithm.md](variant-grouping-algorithm.md). In short:

- **Maps** are grouped by a bottom-up walk over the *effective* folder tree (rendition and variant
  folders such as `Gridded/` or `Night/` are transparent). In each folder, deepest first, files
  join on certain evidence (pHash renditions, equal identity names), then on agreement (layout
  **and** embedding), shared 2-token name bases and folder names. A content split stands unless
  names or folders give positive evidence.
- A folder is then a **container** (root, generic, recurring, a known author, a house prefix, a
  pack of different productions, or over a safety cap), which seals its subtree, or a
  **meaningful parent** whose units join as sub-groups when production and theme agree. What a
  folder *is* decides, never how much it holds, so a subtree groups the same alone as inside a
  large import.
- **Scenes** are grouped after the maps, so they never change them: they attach to a map group
  by folder or name only, and otherwise start alone and join other scenes on positive evidence.
- Joins nothing proves (similar content without a shared folder or name) become suggestions.

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
   - every other file is a scene, through `group_scenes` (§2): attached to a map group, or grouped
     among themselves. Tokens and assets are skipped by Auto and imported via Include as maps or
     scenes; tokens are more often mistyped maps than scenes (Joe), worth revisiting if a token
     import type is added.

   A scene joining a map group takes no subgroup unless it sits in a folder whose maps of that
   group share a sub-group label.

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
(cancel, finish without missing files), and on every idle wake of the worker. A run that keeps
failing falls back to paths-only grouping after 3 failures. Before grouping, the phase re-embeds
the job's missing vectors (`vector_reconcile.repair_missing`) and, if they are still missing,
waits for them at most 5 minutes (`_VECTOR_WAIT_SECONDS`). While the model is loading or
switching it waits; with no model it runs without embeddings. Lifecycle: [ingestion.md §5.8](ingestion.md#58-identifying-groups).

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

Format `scene-atlas-grouping-calibration/2` (`grouping_calibration.py`, loaded through
`image_type_classifier.BundledHeads`): `encoder_sha256` (also the file's stem), `embedding_dim`,
and `thresholds` with exactly the research's names
`agree_emb`, `coh`, `coh_all`, `coh_key`, `coh_suggest`, `leaf_diff`, `leaf_same_prod`,
`leaf_same`, `scene_agree_emb` (→ `EmbeddingThresholds.agree`, `parent`, `whole_folder`,
`shared_base`, `suggest`, `leaf_different`, `leaf_same_production`, `leaf_same`, `scene_agree`).
The `leaf_*` values and `scene_agree_emb` were tuned on the medium encoder and quantile-mapped onto
the others (`grouping/e6/calibrate_leaf.py`, `grouping/e7/calibrate_encoders.py`). Files are loaded
once; a malformed one is logged and skipped. One ships for each bundled model (the image-type
heads' encoders).

## 6. User edits

The pipeline never changes a group after it is minted, so user edits need no protection from it:
there is no edit provenance (an earlier design recorded `edited_at`; dropped with refinement).
The grouping phase mints its groups inline, in its write transaction (`group_jobs._write`).

## 7. Scope

**In:**

- maps (battlemap and Auto items the head called maps), by the walk; every other file as a scene;
- new imports and linked-folder scans (a scan job's images appear after its grouping phase; a
  refreshed image keeps its group).

**Out (for now):**

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
| `tree.py` | effective tree; `effective_folders()` |
| `params.py` | `GroupingParams`, `EmbeddingThresholds` |
| `schema.py` | `GroupingFile`, `ProposedGroup`, `Suggestion`, `Grouping`, the per-folder `FolderVerdict` (typed) and `FolderDecision` (DEBUG prose) |
| `phash_index.py` | exact pHash radius search (multi-index hashing) |
| `evidence.py` | features, candidate pairs, pair signals; numpy, blocked, CPU |
| `cohesion.py` | unit gates: cohesion, production fingerprint, average linkage, whole-folder test |
| `folders.py` | what each folder is, from its name and its files' names (fixed before the walk) |
| `walk.py` | the walk |
| `naming.py` | group names and authors, via `ImageParser`'s public `clean_group_name` / `author_from_stem` |
| `scenes.py` | `group_scenes()`: scenes attached to map groups or grouped among themselves |
| `__init__.py` | `group_with_content()` (the pipeline's; with no features it groups by paths alone) |

The port's deliberate deviations from the research method are listed in the research log.

`backend/pipeline/` holds the DB glue:

- seal: `compute_plan` (parsing only);
- features: `ingest_process`;
- the grouping phase, minting included: `group_jobs.py` (lifecycle and triggers: [ingestion.md §5.8](ingestion.md#58-identifying-groups)).

`backend/app/services/grouping_calibration.py` holds the per-encoder thresholds.

## 9. Validation

- **Port parity.** scene-atlas-learning runs the Scene Atlas package against its reference
  (`grouping/e6/port_parity.py` for maps, `grouping/e7/port_parity.py` for scenes): identical
  groups, names and scene attachments on seeded small imports and real folders, given the same
  features.
- **Feature parity.** `phash256` bit-identical to `imagehash` on fixture images; `edge` equal to
  the research descriptor within float16 tolerance.
- **Integration** (`test_grouping_phase.py`):
  - images import ungrouped and unlisted, then appear grouped;
  - twin folders become one group;
  - maps through the walk, scenes through `group_scenes`;
  - scenes join the one map group of their folder, not a folder of two;
  - existing-group matching, and names two maps share never match;
  - cancelled imports are grouped; the model being busy waits; a failed write leaves the job
    `grouping`; files changed meanwhile are read again;
  - late files join their group, or a new one, and nothing moves;
  - Undo removes the groups the import minted.
