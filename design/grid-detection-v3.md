# Grid Detection v3: Research and Evaluation

**Status:** research complete (rounds 1–4, 2026-10-15); port not started.
**Decision proposed (after round 4):** a hybrid. Use v3 for images of 1000 px or more and keep `grid_detector.py` for smaller images. This is not yet an ADR; write one when the port lands.
**Prototype:** `grid_v3.py`, trained models, and the evaluation scripts. These are research code and are not tracked in git, matching the convention in `05b2234`. They are in `scripts/grid_research/` (see §6).

This document records why the change is proposed, how it was measured, and what did not work. Read it before touching grid detection.

---

## 1. Why replace the current detector

The current detector (`backend/app/services/grid_detector.py`) runs Canny edge detection followed by autocorrelation at up to 8000 px. Its problems:

- **Cost:** about 1.6 GB peak RSS and up to about 3.6 s CPU per large map. The ingest redesign capped its input at 8000 px and reads at reduced scale to limit memory.
- **False positives on gridless maps:** it fires on 28% of explicitly "No Grid" maps (round 1), set off by floor tiles, seat rows and bolts that line up with the implicit grid.
- **Spurious hex calls:** 17 to 24 per evaluation set.

### How the app uses detection

Detection is driven by what the filename parser can tell (`parser.md` §2):

| What the filename says | What the app runs |
|---|---|
| Gridless | Nothing |
| Gridded, no NxM | Detection for **size only**. This is the most common case and the one that matters most. |
| Nothing | Full **presence and size** detection. This applies to few images. |

Accuracy therefore matters most for *tile counts on maps already known to be gridded*.

## 2. v2 and v3 in brief

**v2** works on one-dimensional profiles streamed from a reduced-scale decode:
- JPEG DCT scaling is used where possible; the full image is never decoded.
- Each axis profile records how much "line" there is at each position.
- A whitened, zero-padded spectrum of each profile is searched with a **harmonic comb**. The fundamental frequency equals the tile count directly, so counts can be read straight off the spectrum.
- The cell size is searched jointly on both axes, so cells are forced to be square.
- The fundamental is chosen by checking odd harmonics.

**v3 = v2 plus four additions:**
- A per-image **null distribution**: comb scores at random non-harmonic frequencies, converted to a z-score.
- **Spatial features**:
  - block coverage of the comb;
  - line-polarity coherence, since a grid overlay has a consistent sign everywhere while tile seams vary;
  - line ratios.
- A small **gradient-boosted classifier** for presence, using those features plus v2's scores.
- A **hex model**: logistic regression over eight hex measures, including a 2-D polar FFT and v2's oblique projections.

There is also an optional **sibling prior** for size-only mode. When other files in the same parsed group carry NxM in their names, those sizes become candidate counts. They act as candidates, never as truth, because siblings often differ: in the user's library, only 1,383 of 19,134 such groups agree on a single size.

## 3. Evaluation method

These are lessons learned; reuse them for any future detector work.

### Labels

- **Gold labels from the catalogue are not verified grids.** One scraper set "square" for any filename ending in `_NxM`, and crops showed no drawn grid. Gold "none" labels, which come from explicit "No Grid" filenames, are reliable.
- **Twin-difference labels are the reference truth.** For gridded and gridless twins with identical dimensions, subtracting the pair isolates the drawn grid. That gives exact line positions, cell size, counts and type. Results:
  - DEV: 364 of 379 twins produced clean labels.
  - Held-out: 281 of 368.
  - Rejected twins are mostly rain overlays or pairs that aren't true twins.
  - One label error was found by crop check (dice_grimorium "GL…line", where the "gridless" file has its own grid).

### Splits and statistics

- DEV and held-out are split by creator and variant group. Near-duplicates are excluded by pHash distance.
- **All thresholds and models were frozen before the held-out data was examined.**
- Confidence intervals are clustered bootstrap by variant group, 2,000 repetitions.

### Synthetic data

Synthetic grids were made by overlaying grids on gridless maps:
- real grid layers transplanted from twins, plus parametric grids, mainly hex;
- at the map's own scale;
- re-encoded as JPEG/WebP;
- some with partial coverage.

Findings:
- **Synthetic data was harder than real data, not easier**: the same model scored F1 0.674 on synthetic vs 0.970 on real twins.
- **It was decisive for hex**: a model trained only on synthetic data scored 0.984 on real DEV hex maps.
- **It hurt the presence classifier**: adding it raised false positives, so that classifier uses none.
- **Rule:** synthetic data is for training and diagnostics only, never for reported metrics.

### Hex test data

The parser fix that recognises bare `Hex`, `HexH` and `HexV` in filenames (`parser.md`) turned up 258 partyoftwo hex maps. That replaced the original set of 4.

## 4. Results

### Round 2 (held-out)

| Measure | Current @8k | v2 | v3 |
|---|---|---|---|
| Presence F1, twins (562) | .913 (P .863, R .968) | .942 | **.959** (P .951, R .968) |
| Presence F1, silver (280; filename labels) | .895 | .952 | **.970** |
| Gridded/gridless pairs, both right (281) | .819 | .890 | **.918** |
| Size-only exact tile count (276 maps, twin truth) | .895 | .931 | **.957**; .964 with the sibling prior |
| False positives on explicit "No Grid" (150) | 20 | 6 | 11 |
| Wrong hex calls | 17 | 0 | 5 |
| CPU total / p90, 1,033 images | 357 s / 0.72 s | 167 s / 0.26 s | 288 s / 0.46 s |
| ΔRSS p90 / max | 173 / 619 MB | 76 / 537 MB | 146 / 537 MB |

- **v3 vs current on twins:** F1 +0.047 [+0.025, +0.069]; pairs +0.10 [+0.05, +0.15]; size-only +0.051 [+0.007, +0.101]. No creator is worse.
- **Weakness:** faint hex (the caeora Avernus maps), where current finds 4/4 and v3 finds 0/4.

### Round 3 (small maps, under 1000 px; diagnostic, nothing tuned)

On 77 native small gridded maps:
- v3: recall .79, precision .84.
- Current: recall .44, precision .69.
- Between 750 and 1000 px, v3 recall is .95.

The round-2 advice to keep the current detector for small images rested on 8 images and is withdrawn.

**What makes maps hard is pixels per cell, not image size.** Of v3's 236 misses with known truth:

| Count | Cause |
|---|---|
| 147 | True cell outside the search range: cells under 32 px, which come from big maps downscaled to web size |
| 66 | True cell ranked 5th or lower among comb peaks, mostly maps with 5 or fewer cells per side |
| 16 | True cell was the top peak but the classifier rejected it. The classifier never saw small images in training. |

Downscaled maps with 6–20 px cells aren't usable as VTT maps. Current's higher recall on them is mostly accidental: only about 20% of its hits are within ±1 tile.

### Round 4 (cross-artist generalisation; shipped models)

**Data.**
- Twin pairs were mined from the user's whole library by header scan. Pairs had to have identical dimensions and match on one of these conventions:
  - Czepeku `G_` / `GL_`;
  - Grid / No Grid sibling folders;
  - `_grid` / `_nogrid` and `GD` / `GL` suffixes;
  - Dreadmaps `X_Grid` vs `X`.
- That produced **2,278 twin-labelled images (about 1,180 clean pairs) from 28 creators**, up from 645 pairs and 6 creators.
- The catalogue's `variant_links` and `pair_edges` contain essentially no gridded/gridless pairs.

**Clean labels per creator.**
- Clean rates were high for Czepeku, dww, Limithron and Dreadmaps, and low for Beneos (6%), Spellarena (36%) and Neutral Party (46%).
- 10 creators have fewer than 10 pairs.

**Method.**
- **Sentinel:** 3 creators were locked away before any result was seen: angela_maps, mikwewa and dww, chosen with seed 20261015 from creators with 30–60 pairs.
- **LOCO:** leave-one-creator-out over the other 25. Hyperparameters were fixed. The only choice made from LOCO was the training weighting, unweighted vs creator-balanced, decided by worst-creator F1.

**LOCO results** (14 creators with 10 or more pairs):

| | Worst-creator F1 | Median F1 |
|---|---|---|
| v3 (LR, balanced) | .462 | .924 |
| current | .667 | .917 |
| v2 | .444 | .903 |

- **Selection margin:** the LR was chosen over the GBM on a single image of a 10-pair creator. The GBM had the better median (.931) and did better on Dreadmaps.
- **Where v3 is worse than current:**
  - forgotten_adventures: thin 1–2 px lines on 200 dpi maps, probably blurred away by the 2–4x reduced decode;
  - Dreadmaps: few-cell rooms, plus false positives on plank floors;
  - small margins on mad_cartographer, fablekit, neutral_party and dice_grimorium.
- **Where v3 is clearly better:** spellarena, limithron, lost_trails and czepeku. It also has far fewer false positives on gridless maps.
- **Under 1000 px, v3 loses** (P .61, R .37 vs current's .89, .57). This reverses round 3's small-map finding. Round 3's native small set was mostly Czepeku and leaned towards maps v3 finds easily. Round 4's is dominated by Dreadmaps Cora's Cabin. Treat small-map behaviour as creator-dependent and unresolved.
- **Size-only exact** (967 gridded maps): v3 raw .915, v3 + sibling prior .948, current .869, v2 .862. The sibling prior's big win is Dreadmaps (.726 → 1.0), and it slightly hurts a few creators.

**Sentinel, evaluated once:**

| Method | F1 | Pairs |
|---|---|---|
| v3 | **.946** [.925, .971] | .893 |
| current | .897 | .772 |
| v2 | .932 | .866 |

- v3 is at least as good as current on all three sentinel creators.
- **Size-only on the sentinel:** current wins on dww's 8x8 geomorph tiles (.982 vs about .74, half/double errors). v3 wins on angela (.983 vs .879) and mikwewa (1.0 vs .861).

**Hex.**
- v3 made 1 false hex call across all LOCO creators, against 21 for current.
- Hex recall is .99 on partyoftwo. Recall on other hex creators rests on 2–5 images, and faint caeora hex is still missed.

**Shipped models.**
- Refit on all 2,278 images with balanced weighting: presence LR (chosen), presence GBM (alternative) and hex LR.
- They are exported to ONNX and, for the two LRs, to plain JSON (scaler means and scales, coefficients, intercept).
- ONNX matches scikit-learn to within 3e-7 on every training sample, and the JSON LRs match exactly.
- **The final models over-call small images** (27 false positives out of 39 small gridless maps in the smoke test), because the training now includes Cora's Cabin small twins. Routing small images to the current detector is therefore required.

### Things that did not help (do not retry without new evidence)

- **Half/double count correction:** +0.009 on DEV, −0.008 on held-out.
- **Pooling evidence across lighting variants of one map:** no gain.
- **The 2-D polar FFT hex score on its own:** recall .61. It helps only as one input to the hex model.
- **JPEG quality between q75 and q92:** no effect.

## 5. Recommendation and follow-ups

1. **Port v3 as a hybrid.**
   - Use v3 for images of 1000 px or more; keep the current detector below that.
   - Ship the **presence and hex logistic regressions as JSON**. Each is a standard scaler plus a handful of coefficients, so this needs neither ONNX nor pickle. The GBM is only marginally different, so the simpler model wins.
   - Remove the half/double count fix.
   - Use the sibling prior in size-only mode.
   - Build a regression suite from the round 2–4 crops.
2. **Follow-ups, in order of value:**
   - **Thin lines on high-dpi maps** (forgotten_adventures). Choose the decode reduction from expected line width as well as cell size, or add a thin-line feature.
   - **Few-cell maps** (dww geomorph tiles, Dreadmaps Cora's Cabin). Add a full-length thin-line test, and handle half/double errors on 8x8 tiles.
   - **Periodic floors** (Dreadmaps planks). This is the remaining source of false positives.
   - **Small images.** Revisit with a creator-balanced small-map set before removing the hybrid. Round 3 and round 4 disagree.
   - **Hex.** More real hex creators are needed. Faint hex (caeora Avernus) is unsolved.
3. **Do not chase:**
   - cells under about 20 px;
   - grids at or below about 0.2 line opacity, where every method misses about 85%.
4. **Open product question: grid *scale* vs *drawn grid*.**
   - Many "false positives" on gridless maps are the map's real implicit grid. Examples: Czepeku rooms called 7x7, and Crosshead floors called 6x6. In 96 of 122 such cases, v2 returned exactly the filename's NxM.
   - A detected scale is useful to VTT users even on gridless maps.
   - Consider storing "has a drawn grid" and "grid scale" as separate fields.

## 6. Prototype location

The code is in `scripts/grid_research/`, gitignored and local to the main checkout:
- **Prototypes:** `gridalgo/grid_v3_final.py` (ONNX/JSON models, no pickle, half/double fix removed, optional `sibling_prior()`) and `gridalgo/grid_v3.py`.
- **Shipped models:** `gridalgo/v3_final_models/`, containing `presence_lr.json`, `hex_lr.json`, the `*.onnx` exports and `meta.json`.
- **Evaluation:** `gridval/` holds round 1, and `gridval/r2/`, `r3/` and `r4/` hold the later rounds. Round 4 includes `loco_results.json`, `final_r4.json`, `sentinel.json`, the mined `twins_r4.json` and the crop sheets.

The scripts still contain absolute paths from the session scratchpad, and the copied images were deleted. Re-running anything needs path fixes and fresh read-only copies from the library or catalogue.
