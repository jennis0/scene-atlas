# ONNX INT8 Quantisation: Optimisation Guide

This document captures the methodology, experiments, and key findings from optimising INT8 quantisation of CLIP/SigLIP2 embedding models in this project. It is written as a playbook for future agents to follow when adding new models or re-evaluating quantisation quality.

> **Status (2026-10):** No shipped model uses int8. `small` and `medium` are fine-tuned 4-bit (w4a16) models released by scene-atlas-learning, and `large` is fp16 throughout. The int8 export path (`quantise_encoder_int8`, `text_int8_exclude_layers`) was removed from `export_model_onnx.py` and the registry because nothing could reach it. The findings below remain the reference for any future int8 work; reinstating it means restoring that code from git history (commit `9fa8343` or earlier) and making `scripts/quantisation` (or the parts it needs) tracked.
>
> **Important:** The specific numeric results below are for CLIP ViT-B/32 (`laion/CLIP-ViT-B-32-laion2B-s34B-b79K`). Other architectures (SigLIP2, larger ViT variants) may respond differently to each technique. Always re-run the experiments for each new model.

## Key Resources

- **ONNX Runtime quantisation docs:** https://onnxruntime.ai/docs/performance/model-optimizations/quantization.html
- **ONNX Runtime quantisation examples (image classification):** https://github.com/microsoft/onnxruntime-inference-examples/blob/main/quantization/image_classification/cpu/ReadMe.md
- **Project files:**
  - `backend/app/services/model_registry.py` — `MODELS` registry: per-model `vision_quant`, `text_quant`, `release_source` (single source of truth used by the export script)
  - `scripts/quantisation/` — shared utilities and ablation scripts (Python package). **Internal tooling: listed in `.gitignore` and absent from a clean checkout** (see [Dependency on `scripts/quantisation`](#dependency-on-scriptsquantisation))
    - `utils.py` — metrics (cosine diffs, rank correlation), ORT session factory, results I/O
    - `queries.py` — 103 text queries (single source of truth)
    - `ablation_clip.py` — CLIP ViT-B/32 ablation experiments
    - `ablation_siglip2.py` — SigLIP2-base ablation experiments
  - `scripts/models/export_model_onnx.py` — fp16 export and evaluation pipeline (single script; evaluation gated behind `--image-dir`). Takes registry names as positional arguments, or `--all` / `--list`; refuses externally released models, so in practice only `large`
  - `design/decisions.md` — ADR-014 (ONNX Runtime + quantised models), ADR-016 (multi-model manifests), ADR-017 (Hugging Face distribution)

### Dependency on `scripts/quantisation`

`export_model_onnx.py` uses `scripts.quantisation` only for the `--image-dir` quality evaluation (`queries.TEXT_QUERIES` and helpers from `utils`). `parse_args()` checks for the package and exits with an error naming it before any export work when `--image-dir` is given and it is missing. Exporting `large` without `--image-dir` does not touch the package. `backend/tests/unit/test_quantisation_utils.py` uses `pytest.importorskip`, so it is skipped where the package is absent. Published models are downloaded from Hugging Face at runtime, so the app itself does not depend on the package.

## Quality Metric

**Primary metric (cosine distance):** `abs(1.0 - dot(torch_embedding, onnx_embedding))` — measures embedding drift. Lower is better. A diff of 0.0 means identical embeddings.

**Retrieval metric (rank correlation):** Spearman rho over the top-20 ranked images for each query, plus `pct_top5_preserved` — the fraction of queries where the top-5 image set is unchanged. This directly measures whether quantisation affects search results.

**Thresholds:** max cosine diff < 0.02, mean < 0.005 (for int8). pct_top5_preserved > 90%.

**Important distinction:** Ablation scripts use AutoProcessor for both sides — results are *relative* (config vs config). The `export_model_onnx.py --image-dir` evaluation uses the production `CLIPService` preprocessing pipeline — those results represent production quality.

## Methodology: Phased Approach

Always start with the cheapest experiments and escalate. Each phase is a separate set of changes that can be tested independently.

### Phase 1: Parameter Tuning (minutes, no calibration data needed)

These are single-line changes to `quantize_dynamic()`. Test each independently to measure its isolated impact.

| Parameter | What it does | Expected impact |
|-----------|-------------|-----------------|
| `weight_type=QuantType.QInt8` (vs QUInt8) | Signed weights. Transformer weights are symmetric around zero, so unsigned wastes half the range | Variable — helped CLIP vision, made no difference for CLIP text |
| `per_channel=True` | Per-output-channel scale/zero-point instead of per-tensor | Moderate — this was the single most impactful parameter for CLIP |
| `extra_options={"WeightSymmetric": True}` | Eliminates zero-point, uses full range for magnitude | Negligible for CLIP — no measurable difference |
| `reduce_range=True` | Quantises to 7 bits to avoid AVX2/AVX512 saturation | Negligible for CLIP |

**CLIP ViT-B/32 results (text encoder, single test input):**

| Config | Cosine diff |
|--------|-------------|
| Baseline (QUInt8, defaults) | 0.230 |
| QInt8 only | 0.244 (worse!) |
| QInt8 + per_channel | 0.212 |
| QInt8 + per_channel + symmetric | 0.212 |
| QInt8 + per_channel + symmetric + reduce_range | 0.212 |

**Key finding:** For CLIP, `per_channel` was the only parameter that helped. The others made no measurable difference. The text encoder remained at ~0.21 regardless — a fundamental limitation, not a parameter tuning problem.

### Phase 2: Pre-processing (minutes, no calibration data needed)

The ORT docs recommend running `quant_pre_process()` before quantisation to add shape information to the graph:

```python
from onnxruntime.quantization.preprocess import quant_pre_process
quant_pre_process(input_model, output_model, skip_symbolic_shape=True)
```

> **Note:** Symbolic shape inference fails on CLIP/SigLIP Expand ops (TypeError in `_broadcast_shapes`). Always pass `skip_symbolic_shape=True` for these architectures. ONNX shape inference still runs.

**CLIP ViT-B/32 result:** Zero measurable difference for both vision and text encoders, with or without preprocessing. Every experiment produced identical diffs.

**Export behaviour:** the removed `quantise_encoder_int8()` ran `quant_pre_process(..., skip_symbolic_shape=True)` to a named intermediate file (avoids Windows temp-file issues) before `quantize_dynamic()`. `quantise_encoder_fp16()` skips pre-processing: the fp16 conversion is a type cast, and skipping shape inference also avoids the 2 GB protobuf serialisation limit.

### Phase 3: Node Exclusion (minutes, no calibration data needed)

This is where the breakthrough came. The idea: identify which parts of the model are most sensitive to quantisation and keep them in fp32.

**Experiment design:** Progressively exclude transformer layers from quantisation and measure the impact. Test both "exclude last N layers" and "exclude first N layers".

**Critical finding for CLIP text encoder:**

| Exclusion strategy | Max diff | Mean diff | Size |
|-------------------|----------|-----------|------|
| No exclusion | 0.377 | 0.208 | 62 MB |
| Exclude last 6 layers | 0.211 | — | 116 MB |
| Exclude ALL layers | 0.000 | — | 170 MB |
| **Exclude first 1 layer** | **0.016** | **0.004** | 71 MB |
| Exclude first 2 layers | 0.012 | 0.004 | 80 MB |
| Exclude first 3 layers | 0.011 | 0.004 | 89 MB |

**Key insights:**
1. **Error is uniformly distributed** across all layers — excluding any subset of late layers barely helps
2. **Excluding early layers is dramatically better** than excluding late layers — because early-layer quantisation errors propagate through ALL downstream layers
3. **Layer 0 is the primary culprit** — excluding just layer 0 + the projection drops max diff from 0.38 to 0.016 (a 24x improvement)
4. The final projection layer (`text_projection/MatMul` or `visual_projection/MatMul`) should always be excluded — it's the embedding bottleneck

**How to find node names for exclusion:**
```python
import onnx
model = onnx.load("model.onnx")
matmuls = [n.name for n in model.graph.node if n.op_type == "MatMul"]
# Look for patterns like: /text_model/encoder/layers.0/self_attn/q_proj/MatMul
```

**Implementation pattern:**
```python
exclude = [n for n in matmuls if "layers.0/" in n or "projection/MatMul" in n]
quantize_dynamic(..., nodes_to_exclude=exclude)
```

### Phase 4: Static Quantisation (hours, needs calibration data)

Static quantisation calibrates both weight AND activation ranges using representative data. This is the most complex approach.

**CLIP ViT-B/32 result:** Static quantisation was actually WORSE than dynamic for the text encoder (diff 0.95 vs 0.21). The ORT docs confirm: **dynamic quantisation is recommended for transformer models**, static for CNNs.

**If you try this anyway:**
- Use `quantize_static()` with `quant_format=QuantFormat.QDQ`
- Implement `CalibrationDataReader` subclass for your input type
- Try `CalibrationMethod.MinMax` first (simplest), then `Percentile` (clips outliers)
- The `Percentile` method may fail with `ValueError: range is not finite` — this indicates activation values that don't calibrate cleanly
- Pre-process the model first (required for static quant)
- Always set `optimize_model=False` (not supported in newer ORT versions anyway)

## Architecture-Specific Notes

### Vision vs Text Encoders

The quantisation sensitivity pattern **differs between model families**:

**CLIP ViT-B/32:**
- Vision: 0.004 max diff with QInt8 + per_channel (quantises cleanly)
- Text: 0.38 max diff with the same settings (exclusions required)

**SigLIP2-base:** (opposite pattern!)
- Vision: 0.32 max diff with QInt8 + per_channel (does NOT quantise cleanly)
- Text: 0.0097 max diff with basic QInt8 + per_channel (quantises cleanly, no exclusions needed)

**SigLIP2 vision exclusion sweep — the layer-6 cliff:**

The SigLIP2-base vision encoder has 12 transformer layers (0–11) plus a multi-head attention pooling head. Excluding early layers from quantisation reveals a sharp non-linear threshold:

| Exclusion | img_max | img_mean | Size (MB) |
|-----------|---------|----------|-----------|
| None (baseline) | 0.321 | 0.257 | 94.9 |
| First 1 layer + proj | 0.328 | 0.260 | 128.5 |
| First 3 layers + proj | 0.328 | 0.249 | 169.0 |
| First 5 layers + proj | 0.318 | 0.250 | 209.4 |
| **First 6 layers + proj** | **0.069** | **0.049** | **229.6** |
| First 7 layers + proj | 0.072 | 0.047 | 249.8 |
| First 8 layers + proj | 0.073 | 0.049 | 270.0 |
| Last 1–3 layers + proj | ~0.322 | ~0.258 | 128–169 |

Excluding late layers has zero effect. Excluding 1–5 early layers barely helps (~0.32). But excluding 6 early layers drops the error 4.6× to 0.069 — a phase transition, not a gradual improvement.

**Why:** Quantisation error accumulates through residual connections. Each int8 layer adds a small error to the residual stream that propagates forward. With ≤6 quantised layers remaining, the accumulated error stays below what the attention pooling head can tolerate. With 7+ quantised layers, it crosses a critical threshold. This is a cumulative error budget effect, not a property of any single layer.

**Practical conclusion:** Even the best exclusion strategy (6 layers excluded, 0.069 max diff) produces a 229 MB model that's *larger* than fp16 (177 MB) with *worse* quality (0.069 vs 0.0003). fp16 vision is the clear winner for SigLIP2.

**Recommendation:** Always check vision and text encoders separately for each model family. Don't assume CLIP patterns apply to SigLIP2.

### Larger SigLIP2 Model (large)

The ablation script uses an adaptive layer sweep depth based on actual model depth:

```python
max_sweep = min(n_vision_layers // 2 + 2, n_vision_layers)
```

This is necessary because the existing base sweep (`min(9, n_layers)`) would significantly
under-sweep deeper models:

| Model | Vision layers | Sweep depth |
|-------|--------------|-------------|
| base | 12 | 8 |
| large (so400m) | 27 | 15 |

The base ablation found a sharp "layer-6 cliff" at exactly half the model depth (6 of 12
layers). Sweeping to half-depth ensures the same cliff will be caught at any scale.

**Device note:** The large model's fp32 torch reference is slow on CPU. The ablation script auto-detects CUDA and defaults to GPU when available.
The `quantize_dynamic` call itself always runs on CPU (ORT constraint), but torch
reference inference and ONNX quality measurement run on GPU.

No int8 ablation results exist for `large`; it ships fp16 vision + fp16 text.

### Model Family Differences

**Quantisation strategy differs by family:**
- **CLIP:** fp16 vision + int8 text with first 3 layers + projection exclusion. CLIP vision *does* quantise cleanly to int8 (max diff ~0.004), but the export pipeline uses fp16 vision for consistency across families. If model size is critical, CLIP int8 vision is viable — re-run the CLIP ablation to confirm.
- **SigLIP2-base:** fp16 vision (int8 is unrecoverable — see layer-6 cliff above) + int8 text with first 1 layer + projection exclusion (safety margin — max diff 0.0097 without exclusion may degrade at scale)
- **SigLIP2-large (so400m):** fp16 vision + fp16 text (no int8 study yet — run `ablation_siglip2 --model large`)

The removed `quantise_encoder_int8()` was family-aware: it used `find_layer_nodes()` from `scripts/quantisation/utils.py` to identify exclusion nodes. The last int8 releases excluded the first 3 layers + projection for CLIP and the first 1 layer + projection for SigLIP2-base, with pre-processing before `quantize_dynamic` (see Phase 2).

**Image preprocessing differs:**
- **CLIP:** `shortest_edge_then_crop` with `bicubic` interpolation
- **SigLIP2:** `direct_resize` with `bilinear` interpolation (no center crop)

This is detected from the HF processor's `do_center_crop` attribute and stored in `manifest.json`. The `CLIPService` branches on `resize_mode` at inference time.

**Tokenisation differs:**
- **CLIP:** HuggingFace fast tokenizer (`tokenizer.json`)
- **SigLIP2:** SentencePiece wrapper with lowercasing + EOS token appended

## Experiment Template

When optimising a new model, run experiments in this order:

Steps 1 and 3 need the internal `scripts/quantisation` package (see above). Steps 3 and 4 only produce fp16 exports today; int8 needs the removed export code back.

```bash
# 1. Run ablation (requires real images — cannot be skipped)
uv run python -m scripts.quantisation.ablation_clip --image-dir /path/to/images
uv run python -m scripts.quantisation.ablation_siglip2 --model base --image-dir /path/to/images
uv run python -m scripts.quantisation.ablation_siglip2 --model large --image-dir /path/to/images

# 2. Update the entry in MODELS (backend/app/services/model_registry.py) based on the findings

# 3. Export with quality evaluation (recommended)
uv run python scripts/models/export_model_onnx.py large --image-dir /path/to/images --max-images 500

# 4. Quick export (no evaluation)
uv run python scripts/models/export_model_onnx.py large   # or --all; --list shows names
```

Output is a flat directory per model, `backend/models/<name>/`, containing the ONNX files, `manifest.json` and `tokenizer/`. The backend falls back to this directory in dev when `APP_DATA_DIR/models/<name>/` is absent (see [hf-model-management.md](hf-model-management.md)).

**Ablation experiment checklist:**
1. Baseline: `quantize_dynamic(weight_type=QUInt8)` — establish the starting point
2. QInt8 vs QUInt8 — test signed weights
3. per_channel=True — test per-channel quantisation
4. WeightSymmetric, reduce_range — usually no impact but cheap to test
5. Node exclusion sweep — exclude first N layers (N=0..8+) and measure
6. Attention pooling exclusion (SigLIP2) — test excluding attn_pool nodes specifically
7. Hybrid test — fp16 vision + int8 text vs pure int8
8. Static quantisation — only if dynamic with exclusions isn't sufficient

**Important:** Test with a large, diverse image set (500+ real images) and the full query corpus (103 texts). Small test sets give misleadingly good results. The worst-case query is often unpredictable (e.g., "creature illustration of a beholder" was worst for CLIP).

## Summary of What Worked for CLIP ViT-B/32

| Change | Impact | Status |
|--------|--------|--------|
| QInt8 + per_channel | Vision: 0.04 -> 0.004 | Implemented |
| Exclude early text encoder layers + projection | Text: 0.38 -> 0.016 (layer 0 alone) | Implemented in the last int8 release (first 3 layers) |
| Pre-processing | No measurable difference | Run before int8; not used for fp16 |
| WeightSymmetric / reduce_range | No measurable difference | Not used |
| Static quantisation | Made things worse | Not used |

**Final int8 quality (103 RPG-themed queries):**
- Vision: max diff 0.004, well under 0.02 threshold
- Text: max diff ~0.016, mean ~0.004, within thresholds (max < 0.02, mean < 0.005)
- Size: ~71 MB text + ~85 MB vision = ~156 MB (vs 289 MB fp16, 577 MB fp32)

## Summary of What Worked for SigLIP2-base

**Ablation tested:** 18 configurations across parameter tuning + extended node exclusion sweeps (8 layers + attn_pool), evaluated on real battlemap images + 105 text queries.

| Change | Impact | Status |
|--------|--------|--------|
| QInt8 + per_channel (text) | Text: max 0.0097, mean 0.0027 — passes out of the box | Implemented |
| QUInt8, per_tensor, symmetric, reduce_range | No improvement over baseline | Not used |
| Vision int8 (any config) | Vision: max 0.32+ — unfixable with dynamic quant | Not used |
| Node exclusion sweep (vision, 1–8 layers) | Layer-6 cliff: 0.32→0.069 but still worse than fp16 | Not used (see layer-6 cliff above) |
| Node exclusion (text) | Not needed — text already passes without exclusions | Not used |
| Hybrid: fp16 vision + int8 text | Vision: max 0.00035, Text: max 0.0097 | Implemented |

**Final int8 quality (105 queries, 50 real images):**
- Vision (fp16): max diff 0.000351, mean 0.000181
- Text (int8): max diff 0.009723, mean 0.002742
- Size: 270.4 MB text + 177.5 MB vision = 447.9 MB (vs 716.3 MB fp16, 1431.7 MB fp32)

**Bugs found during investigation:**
1. `resize_mode` default was `shortest_edge_then_crop` — wrong for SigLIP2 which uses `direct_resize`. Caused 0.03-0.08 vision diffs on non-square images.
2. Torch reference missing `return_attention_mask=True` for SigLIP2 tokenizer
3. Torch reference not lowercasing text for SigLIP2 (production pipeline lowercases via SentencePiece wrapper)
4. `embedding_dim` extraction used `config.projection_dim` which is `None` for SigLIP2
5. `model_max_length` for SigLIP2 tokenizer is ~1e30, needs fallback to `max_position_embeddings`
