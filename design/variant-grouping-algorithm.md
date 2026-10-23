# Variant grouping: how the algorithm works

A technical walkthrough of `backend/app/services/variant_grouping/`: what it decides, from which
evidence, in which order, and why. The design and pipeline integration are in
[variant-grouping.md](variant-grouping.md) and ADR-028. The research that produced the algorithm
is scene-atlas-learning's experiment E5, "Joe's tree walk" (`docs/variant-grouping-results.md`).

## 1. The problem it solves

An import is a set of image files under an arbitrary folder tree. The algorithm has to work out
which files are **the same map**, meaning variants (day/night, seasons, themes, props) and
renditions (gridded/gridless, DPI, print/VTT, file format), and give each group a name, an author
and, where the map has floors or rooms, sub-groups.

Nothing about the tree can be assumed. The same library can arrive as:
- `Maker/Map/*`;
- `Forest/Maker/Map/*`;
- `Maker/{Gridded,No Grid}/*`;
- `Maps/*.png`, one flat folder;
- a mixture of these.

Makers' naming conventions vary. Some names carry the map (`Moonlight_Maps_Fey_Pool_Dry01_18x22.jpg`),
some only the variant (`rain.webp`), and some nothing (`IMG_0012.jpg`).

The algorithm combines two families of evidence:

| Evidence | Known | Strengths | Weaknesses |
|---|---|---|---|
| **Paths:** folder tree and file names | from the start | floors, rooms and tiles of one map share names and folders, not pixels | coincidental shared words; packs of unrelated maps in one folder; no names at all |
| **Content:** pHash, edge map, embedding | after each image is processed | renditions and variants of one picture are found whatever they're called | different floors look different; one maker reuses a template across different maps |

On the research benchmark (28k maps, realistic layouts), content alone scores BCubed F1 ≈ 0.95,
paths alone ≈ 0.84 (0.97 for makers whose names are informative), and the combined walk 0.976.
The old `group_files` scored 0.67. On makers it was never tuned on, the walk scores 0.94.

## 2. Principles

These come from the research failures, and every rule below follows from them.

1. **Certain evidence links outright; probable evidence only by agreement.** A pHash twin (≤ 12 of
   256 bits) or an identical identity name joins two files directly. Weaker signals (layout
   similarity, embedding similarity) join only when *both* agree, and never against names that
   say different maps. They are never averaged into one score: averaging a 0-bit pHash with a
   0.6 cosine throws the certainty away (leasealair: F1 0.61 with a fused score, 0.88 with
   certain evidence alone).
2. **A content split stands unless names or folders say otherwise.** If the pixels say two
   layouts, they are two maps, unless a folder or a shared name gives *positive* evidence that
   they are parts of one map. Uninformative names (all identical, or all different) are not
   evidence.
3. **The parent folder is evidence.** Sibling folders under a meaningful parent (Moonlight's
   `Never Ending Wizard Tower/{Beast Prison,Garden,…}`) join as sub-groups of one map when their
   production and theme are consistent. Similarity alone never creates a sub-group; it only
   gates a join that a folder or name proposes.
4. **Containers seal.** Author, topic, generic and collection folders stop the ascent: nothing
   below one is joined across it by folder or name evidence. Only exact renditions cross them.
5. **Assume nothing about the tree.** No folder is assumed to be a maker. Nothing is configured
   per maker. A folder's role is inferred from its name, its files and its siblings.

## 3. Inputs

`group_with_content(files, features, params, parser, known_authors)`:

- **`files`:** `GroupingFile(key, path)`, with the path relative to the import root.
- **`features`:** a `ContentFeatures` per file, any part of which may be missing:
  - `phash256`: 32 bytes, identical to `imagehash.phash(hash_size=16)`;
  - `edge`: 1024 floats. Gradient magnitude on a 64×64 grayscale, pooled to 32×32 and z-scored,
    so the dot product of two unit-normed edges is their correlation;
  - `log_aspect`;
  - `embedding`: from the active model.

  The first two come from the 800 px thumbnail (`backend/pipeline/grouping_features.py`).
- **`params`:** a `GroupingParams` holding the thresholds (§9). `params.embedding` is the
  per-model calibration, or None, which turns the embedding rules off.
- **`known_authors`:** creators already in the library. A folder named after one is an author,
  never a map.

The output is a `Grouping`: groups (`ProposedGroup(keys, name, author, subgroups, reasons,
name_is_identity)`), `suggestions` (joins deliberately not made, each with a reason), and
`decisions` (folder → `FolderDecision`, for debugging).

The output is deterministic and independent of input order: files are sorted by `(path, key)`
first.

## 4. Stage 1: names (`names.py`, `analyse_names`)

### 4.1 Tokens

`tokenize` lowercases and splits a file stem:
- at separators, camelCase, letter↔digit boundaries and acronym boundaries
  (`ChempunklaboratoryVttGL` → `chempunklaboratory vtt gl`);
- `[tag,lists]` and OS copy suffixes (`name (2)`) are removed;
- `22x30` becomes one `<nxm>` marker;
- `Roll20`, `1st` and similar are glued back together.

### 4.2 Identity tokens

`identity_tokens` keeps only the words that could name a map. It drops:
- **axis words:** lighting, time, season, weather, state (`night`, `winter`, `ruined`, `propless`);
- **rendition words:** grid, format, DPI, platform, size (`gridless`, `vtt`, `140dpi`, `print`, `webp`);
- **numbers and sizes;**
- **stopwords;**
- **library words:** `battlemaps`, and `battle map(s)`.

Grid phrases like `no grid` count as rendition words. Consecutive repeats collapse
(`leasealair maps leasealair maps` → `leasealair maps`).

Two exceptions keep numbers that matter:
- **Series numbers are identity:** `Vol4` becomes the token `vol#4`, so `Forest Path Vol4` and
  `Vol6` are different maps.
- **Level designators are not identity:** `strip_level_suffix` cuts a trailing run such as
  `basement`, `upper level` or `floor 2`, so `Inn_Basement` and `Inn_Roof` share the identity
  `inn`. The floor is kept separately as a **level tag**, which later becomes a sub-group label.

Camera and scan counters (`IMG`, `DSC`, `PXL`, `Screenshot`, `Scan`) carry no identity at all.

### 4.3 Removing uninformative tokens before cutting keys

A token every file shares can't help split a set, and leaving it in made whole folders collapse
(leasealair: F1 0.05). It is decided by what is left once the shared token is removed.

- **Global strip.** If at least 80% of the import's named files share a token, and at least 10
  distinct multi-token names remain after removing it (half of the files keeping ≥ 2 tokens),
  it is a house or collection prefix and is removed everywhere (`myvault maps …`). A single
  imported map (`young adventurers hideout …`) leaves only variant words, so it is kept.
- **Hubs.** A leading token run followed by ≥ 6 "heavy" continuations (each with ≥ 4 distinct
  file names), spanning ≥ 3 folders, is a house prefix such as `moonlight maps …`, and is
  stripped. One-token lead hubs need wider coverage and fan-out. Inside a single large folder
  (≥ 20 files), nested hubs are found the same way.
- **Folder IDF (`folder_names`).** For each folder, the tokens in ≥ 80% of its named files are
  *C*. Then:
  - if ≥ 2 distinct keys remain after removing *C*, and most remainders are multi-token names,
    *C* is a **house prefix**: strip it;
  - otherwise *C* is **the map's name**: keep it, and record that the folder is *named after its
    map*, which is positive evidence for rule a5.
- **Folder-name keys.** A 2-token key made only of an enclosing folder's name (two maps under
  `Moonlight Maps/` both keyed `moonlight maps`) is stripped if ≥ 2 different multi-token names
  follow it. This is the folder IDF test for small folders.
- **Generic keys.** A key shared by ≥ 6 files whose names differ only by numbers
  (`NumberedGLMaps_52`) is a numbering, not a map name. Those files get no identity.

### 4.4 Keys

After stripping, each file has:
- a **full identity** (all remaining identity tokens): equal full identities → same-name join (a2);
- a **2-token key** (the first two): equal keys → shared-base join (a4). Two tokens because one
  shared word (`forest`) is too weak;
- a **veto key** (the key with any cut level word put back), used to *veto* layout agreement
  between files that name different maps. It is as strict as the research version even after
  level stripping shortened names;
- **series** (`vol#4`) and a **level tag** (`floor#2`, `roof`).

Example, leasealair (one folder, 270 files from a collection of other makers' maps):

```
leasealairMaps_LeasealairMaps_Czepeku_ChempunklaboratoryVttGL.jpg
→ tokens   leasealair maps leasealair maps czepeku chempunklaboratory vtt gl
→ identity leasealair maps czepeku chempunklaboratory   (repeats collapsed; vtt, gl dropped)
→ folder IDF: "leasealair", "maps" are in ~100% / 78% of files, and 50+ different names follow
  them, so they are a house prefix and are stripped
→ key "czepeku chempunklaboratory"
```

Before this stripping, every file's key was `leasealair maps` and the whole folder became one
group.

## 5. Stage 2: the effective tree (`tree.py`)

Each folder is classified against its parent's and grandparent's names (`folder_class`):

| Class | Rule | Examples |
|---|---|---|
| **rendition** | only rendition words, or the parent's name plus such words | `Gridded`, `VTT`, `70 DPI (VTT)`, `MA`, `Beast Prison 12x12` under `Beast Prison` |
| **variant** | only axis words (with rendition words) | `Night`, `Gridded Winter` |
| **generic** | identity words all generic | `Maps`, `Downloads`, `Pack 03`, `New folder (2)` |
| **specific** | anything else | `Forest Ponds`, `Moonlight Maps`, `Library` |

Rendition and variant folders are **transparent**: their files belong to the parent. Two more
adjustments:
- near-spellings of the parent's tokens count as the parent's name (`colossas` ≈ `colossus`);
- **mirror siblings** collapse into one effective folder: siblings whose names are equal after
  dropping rendition and axis words, such as `Forest Road Gridded` / `Forest Road Gridless`.

Example: Never Ending Wizard Tower on disk.

```
Never Ending Wizard Tower/
  Beast Prison/
    Beast Prison 12x12/MA/Grid/…      ← "Beast Prison 12x12" = parent name + size → rendition
    Beast Prison 12x12/MA/No Grid/…   ← MA, Grid, No Grid → rendition
    VTT/…                             ← rendition
  Garden/ …
```

The effective tree is `Never Ending Wizard Tower/{Beast Prison, Cross Platform, Garden, Research
Chamber, Teleport Room}`: five room folders, each holding all of its renditions.

`recurring_names` collects effective folder names that appear in ≥ 2 places with ≥ 2 children
each. Those are author or topic folders (`Forests/Czepeku/…` and `Swamps/Czepeku/…`), not maps.

## 6. Stage 3: content evidence (`evidence.py`, `cohesion.py`)

### 6.1 Candidate pairs

Comparing every pair is quadratic, so only candidates are scored:
- **pHash pairs within 20 bits, anywhere in the import.** These are found exactly with a
  multi-index hash (`phash_index.py`): the 256 bits split into 21 chunks, and by pigeonhole any
  pair within 20 bits matches on at least one chunk. Buckets over 256 hashes fall back to
  blocked brute force.
- **Embedding top-25 and edge top-15 neighbours, within each top-level folder.** Ties at the
  k-th neighbour are kept, up to 16 extra. This blocking loses no joins: content joins happen only
  at non-container folders, and the import root is always a container. So pairs across top-level
  folders are only ever used by pHash renditions, which stay global.
- **All pairs** inside folders of ≤ 80 files and subtrees of ≤ 150.

### 6.2 Pair signals

Each candidate gets these signals:
- pHash Hamming bits;
- edge correlation;
- embedding cosine;
- |log aspect| difference.

Two pair-level relations come from them:
- **rendition:** ≤ 12 bits **and** aspect difference ≤ 0.02. Dev precision 0.999.
- **agreement:** edge ≥ 0.70 **and** embedding ≥ the calibrated threshold (≈ 0.70) **and** aspect
  difference ≤ 0.05, unless the two files' veto keys or series say different maps.

A missing feature is never a match: no pHash means no rendition, and no embedding means no
agreement.

### 6.3 Unit-level gates

A **unit** is a set of files already joined. To decide whether two units can join as parts of one
map, `unit_similarity` uses:
- **theme cohesion:** the cosine of the units' mean embeddings. It is raised to the parent
  threshold when their mean edge correlation is ≥ 0.25, i.e. the same building drawn again;
- **production fingerprint:** compatible when the median aspects are within 0.03 and the `NxM`
  sizes agree where both have one.

`cohesive_partition` and `average_linkage` cluster units on that gated similarity.

## 7. Stage 4: the walk (`walk.py`)

Effective folders are processed **deepest first**. Each step works on the current units of the
folder's subtree that are not sealed. Every join records a reason code.

### 7.1 A folder's own files (stage a)

| Code | Join | Evidence |
|---|---|---|
| a1 | rendition | pHash twin (§6.2). Certain. |
| a2 | same-name | equal full identity. Certain. Different level tags join as different floors of one map. |
| a3 | same-layout | agreement (§6.2), counted at unit level: a quarter of the cross pairs between two units must agree |
| a4 | shared-base | the same 2-token key. **Gated** by cohesion in house-prefix folders, and for families spanning more than 8 units (a large family is a series of different maps) |
| a5 | folder-named | the folder's common tokens are the map's name (§4.3): all its named files join |
| a6 | variant-only folder | a specific, non-recurring folder where ≥ 80% of files have no identity (`Golden Forest/Night.webp`, `Day.webp`) is one map |

After stage a, any remaining split stands: different units are different maps, unless stage b
finds positive evidence.

### 7.2 Container or meaningful? (stage B)

A folder is a **container** if any of these holds:
- it is the root;
- its name is generic;
- its name recurs elsewhere in the tree (author or topic);
- its name consists only of house-prefix tokens;
- it holds more than 8 units (60 if it is named after its files).

A container **seals** its subtree: nothing below it joins across it by folder or name evidence.

**Whole-folder exception (c0).** A folder over the unit cap, or named after its files, still joins
whole when **every** unit has an embedding and:
- mean cohesion ≥ ≈ 0.80;
- the 10th percentile ≥ ≈ 0.70;
- ≥ 90% of unit pairs have compatible fingerprints.

This applies only with structural evidence (child folders, or the folder is named after its
files). Limithron's `Coral Reef Shipwreck` is the motivating case.

### 7.3 Meaningful parent (stage b)

A meaningful folder joins its units on:
- **b1–b4:** the same certain and agreement evidence across its children (renditions,
  same-name, agreement, shared base);
- **b5 unnamed parts:** in a folder named after its map, child units whose files have no identity
  of their own (`Isolated Floors/1st_Floor.png`) are parts of that map;
- **c1 parent + cohesion:** units from **different child folders** join, by average linkage on
  the gated unit similarity cut at the calibrated parent threshold (≈ 0.82). Here the parent is
  the evidence and cohesion only the gate. Own files of a folder that isn't named after its map
  never join this way: there is no folder evidence for them (Joe's rule: sub-groups need a
  folder or a meaningful key). Near-misses above ≈ 0.66 become suggestions.

The joined child folders become the group's **sub-groups**.

### 7.4 Cross-tree (narrow mode)

**x1:** a rendition pair anywhere in the import joins, except between two groups that are both
≥ 20 images (that becomes a suggestion).

Everything else that might join across the tree becomes a suggestion with its reason:
- same name across folders;
- same base plus layout;
- same-named folders;
- parent near-misses;
- whole folders cohesive without folder or name evidence.

Suggestions are computed but not shown yet.

### 7.5 Walkthrough: Never Ending Wizard Tower

1. **Each room folder** (`Beast Prison`, …): a1 joins the grid/no-grid and full-res/VTT twins.
   a2 joins equal names (`Beast_Prison_var01` across renditions). a5 fires because the files
   share `beast prison`, the folder's name. Each room becomes one unit.
2. **`Never Ending Wizard Tower`:**
   - **Not a container:** its name is specific, it holds 5 units, it doesn't recur, and it isn't
     a house prefix.
   - **c1 applies:** the five room units are in different child folders, all 12x12 with one
     aspect (fingerprint compatible), and cohesive (cross-room cosine ≈ 0.79, raised by layout
     overlap where rooms reuse the tower's walls).
   - **Result:** they join, and the five rooms become sub-groups.
3. **`Moonlight Maps`:** a container (house-prefix name). It seals the tower off from the maker's
   other maps.

A pack folder of five *different* Moonlight maps fails c1: their cross-map cohesion is ≈ 0.63 and
nothing names them together, so they stay five groups.

## 8. Naming (`naming.py`)

Each group's name, in order of preference:
1. **The folder that names it:**
   - a folder named after its files;
   - an a6 variant-only folder;
   - a folder holding exactly this group, below the top level or joined from its child folders.
2. **The members' common identity**, cleaned by `ImageParser.clean_group_name`, without trailing
   part words or a `by<Author>` marker.
3. **A fallback:** the first member's cleaned stem. `name_is_identity` is then False, so the
   group is never matched to an existing gallery group by name.

The author, in order:
1. a folder named after a known author;
2. a folder named by a stripped house prefix (`Woods/Moonlight Maps/…` gives Moonlight Maps);
3. a `by<Author>` marker in the file name;
4. the top folder.

The folder that names the group is never its author, and leading rendition or variant folders are
skipped. Root files have no author.

Sub-group labels come from joined child folders (`f:<folder>`), or from level tags when a group's
files name ≥ 2 levels (`l:floor#2`, `l:roof`). Labels are never made from content clusters.

## 9. Thresholds and calibration

Encoder-independent thresholds are research-tuned on the benchmark's dev split; they are the
`GroupingParams` defaults:

| Parameter | Value | Meaning |
|---|---|---|
| `rendition_bits` | 12 | pHash bits of 256 |
| `rendition_aspect` | 0.02 | |log aspect| of renditions |
| `agree_edge` | 0.70 | edge correlation for agreement |
| `agree_aspect` | 0.05 | |log aspect| for agreement |
| `agree_fraction` | 0.25 | share of cross pairs that must agree to join units |
| `big_family` | 8 | a shared base over more units is gated |
| `layout_overlap` | 0.25 | mean edge correlation that raises unit cohesion |
| `aspect_tolerance` | 0.03 | fingerprint aspect compatibility |
| `max_units` / `max_units_named` | 8 / 60 | container cap |
| `big_join` | 20 | x1 between two groups this large is a suggestion |
| `candidate_phash_bits`, `knn_embedding`, `knn_edge` | 20, 25, 15 | candidate search |

The embedding thresholds depend on the encoder and ship per model as
`backend/app/data/heads/grouping/<vision encoder sha256>.json`, produced by scene-atlas-learning
(`grouping/e5/calibrate.py`) from embeddings computed the way Scene Atlas computes them:

| Model | agree | parent (c1) | whole folder (c0) | shared base | suggest |
|---|---|---|---|---|---|
| small (B/32 rc3) | 0.673 | 0.787 | 0.771 | 0.652 | 0.630 |
| medium (base-384 rc4) | 0.701 | 0.813 | 0.796 | 0.682 | 0.662 |
| large (L-384 rc4) | 0.696 | 0.818 | 0.797 | 0.677 | 0.657 |

Each set was quantile-mapped from E5's medium values. All three keep E5's quality (test
0.976, new makers 0.943–0.944).

A dev-grid retune was rejected: +0.001 F1 for more wrong joins in same-maker packs (17% → 23%).
With no matching calibration, the embedding rules are off. Test F1 is then 0.85: renditions,
names and folders still work.

## 10. Properties

- **Deterministic and order-independent.** Inputs are sorted, and every set or ordering tie is
  broken explicitly.
- **Faithful to the research.** On the benchmark the port matches E5 to within ±0.002 (0.9765 vs
  E5's 0.9759 after the deliberate fixes). The parity bench lives in scene-atlas-learning.
- **Cost.**
  - Feature extraction: ~2–3 ms per image, during processing.
  - The walk:
    - 20k images over 200 top-level folders: ~2 s;
    - 50k images over 200 top-level folders: ~4 s;
    - one 50k-image flat folder: ~40 s.

    The flat case is the remaining quadratic part: dense embedding and edge kNN.
  - Memory: about 2 GB peak at 50k images.

## 11. Known weaknesses

These are from the research audit; see `results/grouping/e5-audit.md` in scene-atlas-learning.

- **Modular tile sets whose part names look like map names** (czepeku `modular-caves`) split into
  many groups. The joins surface as suggestions.
- **Isolated floors in a flat folder,** with no folder or shared name, stay separate (Joe's rule).
- **Same-named maps from different makers** in one mixed folder (`Forest Ruins`) can join.
- **Packs of 5–6 same-maker maps on one topic** are the riskiest case for c1, with a wrong join
  in roughly a third of packs when the names are kept.
- **Collections of near-identical frames from one source** can chain together (leasealair's Tom
  Cartos maps).
- **Renamed dumps** (`IMG_*` everywhere) rely on content alone: recall ≈ 0.78.

## 12. Debugging a grouping

`Grouping.debug_lines()` prints each effective folder's decision:
- container or meaningful, and why;
- units before → after;
- the name analysis (house prefix or map name);
- the joins by reason code.

Each `ProposedGroup.reasons` counts the reason codes that built it. To see why two files ended up
together, or didn't:
1. Find their effective folder in `decisions`.
2. Check whether a container sealed them apart.
3. Check which rule joined them, or which suggestion withheld the join.
