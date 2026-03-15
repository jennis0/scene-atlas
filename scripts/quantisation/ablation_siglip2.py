#!/usr/bin/env python3
"""INT8 quantisation ablation experiments for SigLIP2 models.

Covers all SigLIP2 variants (base, large, giant) via the --model flag.
Systematically tests different quantisation configurations and measures
cosine similarity + retrieval rank correlation against the fp32 torch
reference, following the methodology in design/onnx-int8-quantisation.md.

NOTE: Uses AutoProcessor for both torch and ONNX image preprocessing.
AutoProcessor handles SigLIP2 correctly (direct_resize, bilinear).  Text
is lowercased to match production SentencePiece behaviour.

Ablation results are *relative* (config vs config).  For production-
representative numbers, use ``scripts/export_model_onnx.py --image-dir``
which exercises the full ``CLIPService`` preprocessing pipeline.

Usage:
    uv run python -m scripts.quantisation.ablation_siglip2 \\
        --model base --image-dir /path/to/images [--max-images 500] [--seed 42]

    uv run python -m scripts.quantisation.ablation_siglip2 \\
        --model large --image-dir /path/to/images

    uv run python -m scripts.quantisation.ablation_siglip2 \\
        --model giant --image-dir /path/to/images
"""

from __future__ import annotations

import argparse
import tempfile
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path

import numpy as np
import torch
import torch.nn.functional as F
from PIL import Image as PILImage
from tqdm import tqdm
from transformers import AutoModel, AutoProcessor

from scripts.quantisation.queries import TEXT_QUERIES
from scripts.quantisation.utils import (
    ExperimentResult,
    RunMeta,
    add_common_args,
    collect_images,
    cosine_diffs,
    create_ort_session,
    find_layer_nodes,
    get_torch_device,
    print_results_table,
    quantise_encoder,
    rank_correlation,
    save_results,
)

FAMILY = "siglip2"

_ROOT = Path(__file__).resolve().parent.parent.parent

# Per-model configuration.  max_length is a fallback — the torch reference
# reads from model.config.text_config.max_position_embeddings at runtime.
_MODEL_CONFIGS: dict[str, dict] = {
    "base": {
        "model_id": "google/siglip2-base-patch16-224",
        "fp32_dir": _ROOT / "backend" / "models" / "siglip2-base" / "fp32",
        "max_length": 64,
    },
    "large": {
        "model_id": "google/siglip2-so400m-patch14-384",
        "fp32_dir": _ROOT / "backend" / "models" / "siglip2-large" / "fp32",
        "max_length": 64,
    },
    "giant": {
        "model_id": "google/siglip2-giant-opt-patch16-384",
        "fp32_dir": _ROOT / "backend" / "models" / "siglip2-giant" / "fp32",
        "max_length": 64,
    },
}


# ── FP32 ONNX bootstrap ─────────────────────────────────────────────────────


def _export_fp32_if_missing(model, processor, fp32_dir: Path) -> None:
    """Export fp32 ONNX encoders from the already-loaded model if not present.

    The ablation script needs fp32 ONNX files as the base for int8 quantisation
    experiments.  Rather than requiring the user to run export_model_onnx.py
    first, we generate them here from the model that's already in memory.
    """
    vision_path = fp32_dir / "clip_vision_encoder.onnx"
    text_path = fp32_dir / "clip_text_encoder.onnx"
    if vision_path.exists() and text_path.exists():
        return

    from scripts.models.export_model_onnx import export_text, export_vision

    img_proc = processor.image_processor
    size_cfg = img_proc.size
    if isinstance(size_cfg, dict):
        image_size = size_cfg.get("shortest_edge", size_cfg.get("height", 224))
    else:
        image_size = int(size_cfg)
    context_length = model.config.text_config.max_position_embeddings

    fp32_dir.mkdir(parents=True, exist_ok=True)
    print(f"\nFP32 ONNX not found — exporting from loaded model to {fp32_dir}...")
    print(f"  Exporting vision encoder (image_size={image_size})...")
    export_vision(model, "siglip2", image_size, fp32_dir)
    print(f"  Exporting text encoder (context_length={context_length})...")
    export_text(model, "siglip2", context_length, fp32_dir)
    print("  FP32 export complete.")


# ── Embedding computation ───────────────────────────────────────────────────


def get_torch_embeddings(
    model,
    processor,
    images: list[Path],
    texts: list[str],
    torch_device: str = "cpu",
    batch_size: int = 32,
) -> tuple[
    list[Path],
    list[np.ndarray],
    list[dict[str, np.ndarray]],
    list[np.ndarray],
    list[np.ndarray],
    int,
]:
    """Read images from NFS once, compute torch reference embeddings, and cache
    preprocessed inputs for reuse across all ONNX experiments.

    Images are processed in batches to maximise GPU utilisation.

    Returns:
        valid_paths      – paths for images that loaded successfully
        pixel_values     – preprocessed image arrays (float32, shape 1×C×H×W), one per image
        text_inputs      – tokenised text dicts (numpy), one per query
        torch_img_embs   – normalised torch image embeddings
        torch_txt_embs   – normalised torch text embeddings
        max_length       – context length from model config
    """
    actual_device = next(model.parameters()).device
    print(f"  Model device: {actual_device}")
    print(f"  Reading and preprocessing {len(images)} images in batches of {batch_size}...")

    PILImage.MAX_IMAGE_PIXELS = 300_000_000

    # ── Load + embed with prefetch ───────────────────────────────────────────
    # NFS reads are submitted to a thread pool so the next batch is fetched
    # while the GPU processes the current one.
    valid_paths: list[Path] = []
    pixel_values: list[np.ndarray] = []
    torch_img_embs: list[np.ndarray] = []

    def _load(p: Path) -> tuple[Path, PILImage.Image | None, str | None]:
        try:
            with PILImage.open(p) as img:
                return p, img.convert("RGB"), None
        except Exception as e:
            return p, None, str(e)

    # Split paths into batches and submit the first batch immediately so it's
    # in-flight while we're still setting up.
    batches = [images[i : i + batch_size] for i in range(0, len(images), batch_size)]
    n_batches = len(batches)

    with ThreadPoolExecutor(max_workers=4) as pool:
        # Pre-submit the first batch of NFS reads
        pending: list[tuple[Path, Future]] = [(p, pool.submit(_load, p)) for p in batches[0]]

        for batch_idx in tqdm(range(n_batches), desc="  Embedding", unit="batch", ncols=80):
            # Submit next batch to the pool before blocking on current results
            if batch_idx + 1 < n_batches:
                next_pending = [(p, pool.submit(_load, p)) for p in batches[batch_idx + 1]]

            # Collect current batch results (NFS reads complete here)
            batch_paths: list[Path] = []
            batch_imgs: list[PILImage.Image] = []
            for _p, future in pending:
                path, img, err = future.result()
                if err:
                    tqdm.write(f"  Skipping {path.name}: {err}")
                    continue
                batch_paths.append(path)
                batch_imgs.append(img)

            pending = next_pending if batch_idx + 1 < n_batches else []

            if not batch_imgs:
                continue

            np_inputs = processor(images=batch_imgs, return_tensors="np")
            batch_pv = np_inputs["pixel_values"]  # (B, C, H, W)

            pt_inputs = {k: torch.from_numpy(v).to(torch_device) for k, v in np_inputs.items()}
            with torch.no_grad():
                features = model.get_image_features(**pt_inputs)
                features = F.normalize(features, p=2, dim=-1)
            embs = features.cpu().numpy()  # (B, dim)

            for i, p in enumerate(batch_paths):
                valid_paths.append(p)
                pixel_values.append(batch_pv[i : i + 1])  # (1, C, H, W) for ONNX reuse
                torch_img_embs.append(embs[i].flatten())

    # Preprocess text once — reused by every ONNX experiment
    max_length = model.config.text_config.max_position_embeddings
    text_inputs: list[dict[str, np.ndarray]] = []
    torch_txt_embs: list[np.ndarray] = []
    for t in texts:
        # SigLIP2 was trained on lowercased text; the production SentencePiece
        # wrapper lowercases, so the torch reference must match.
        np_inputs = processor(
            text=t.lower(),
            return_tensors="np",
            padding="max_length",
            max_length=max_length,
            return_attention_mask=True,
        )
        text_inputs.append(
            {
                "input_ids": np_inputs["input_ids"],
                "attention_mask": np_inputs["attention_mask"],
            }
        )
        pt_inputs = {k: torch.from_numpy(v).to(torch_device) for k, v in np_inputs.items()}
        with torch.no_grad():
            features = model.get_text_features(
                input_ids=pt_inputs["input_ids"],
                attention_mask=pt_inputs["attention_mask"],
            )
            features = F.normalize(features, p=2, dim=-1)
        torch_txt_embs.append(features.cpu().numpy().flatten())

    return valid_paths, pixel_values, text_inputs, torch_img_embs, torch_txt_embs, max_length


def get_onnx_embeddings(
    onnx_dir: Path,
    pixel_values: list[np.ndarray],
    text_inputs: list[dict[str, np.ndarray]],
) -> tuple[list[np.ndarray], list[np.ndarray]]:
    """Compute ONNX embeddings from pre-processed inputs (no file I/O).

    pixel_values and text_inputs are produced once by get_torch_embeddings
    and reused across all experiments to avoid re-reading from NFS.

    INT8 quantised models have no CUDA kernels and must run on CPU.
    """
    vision_sess = create_ort_session(onnx_dir / "clip_vision_encoder.onnx", device="cpu")
    text_sess = create_ort_session(onnx_dir / "clip_text_encoder.onnx", device="cpu")

    image_embs = [
        vision_sess.run(["embeddings"], {"pixel_values": pv})[0].flatten() for pv in pixel_values
    ]
    text_embs = [text_sess.run(["embeddings"], inp)[0].flatten() for inp in text_inputs]

    return image_embs, text_embs


# ── Experiment runner ────────────────────────────────────────────────────────


def run_ablation(args: argparse.Namespace) -> None:
    """Run the full SigLIP2 ablation experiment suite for the selected model."""
    cfg = _MODEL_CONFIGS[args.model]
    model_id: str = cfg["model_id"]
    fp32_dir: Path = cfg["fp32_dir"]

    print("=" * 80)
    print(f"SigLIP2-{args.model} INT8 Quantisation Ablation")
    print("=" * 80)

    # Resolve devices
    torch_dev = get_torch_device(args.device)
    print(f"  ONNX device: {args.device}, torch device: {torch_dev}")

    # Load model
    print("\nLoading model...")
    model = AutoModel.from_pretrained(model_id, local_files_only=True)
    model.eval()
    model.to(torch_dev)
    processor = AutoProcessor.from_pretrained(model_id, local_files_only=True)

    # Ensure fp32 ONNX files exist — export from the loaded model if not
    _export_fp32_if_missing(model, processor, fp32_dir)

    # Collect test data
    print(f"\nCollecting images from {args.image_dir}...")
    all_images = collect_images(args.image_dir, args.max_images, args.seed)
    print(f"  Collected {len(all_images)} real images")

    with tempfile.TemporaryDirectory(prefix=f"ablation_siglip2_{args.model}_") as tmp:
        # Read images from NFS once, preprocess, and compute torch reference.
        # pixel_values and text_inputs are cached for reuse by all ONNX experiments.
        print("\nComputing torch reference embeddings...")
        all_images, pixel_values, text_inputs, torch_img_embs, torch_txt_embs, max_length = (
            get_torch_embeddings(
                model, processor, all_images, TEXT_QUERIES, torch_dev, args.batch_size
            )
        )
        print(f"  {len(all_images)} images loaded successfully")
        print(f"  Text max_length: {max_length}")

        # Inspect node structure
        print("\n--- Vision encoder node structure ---")
        vision_layers = find_layer_nodes(fp32_dir / "clip_vision_encoder.onnx")
        print("\n--- Text encoder node structure ---")
        find_layer_nodes(fp32_dir / "clip_text_encoder.onnx")

        # ── Define experiments ──────────────────────────────────────────

        experiments: list[dict] = []

        # Phase 1: Parameter tuning
        experiments.append(
            {
                "name": "baseline (QInt8 + per_channel)",
                "vision": {"weight_type": "QInt8", "per_channel": True},
                "text": {"weight_type": "QInt8", "per_channel": True},
            }
        )
        experiments.append(
            {
                "name": "QUInt8 + per_channel",
                "vision": {"weight_type": "QUInt8", "per_channel": True},
                "text": {"weight_type": "QUInt8", "per_channel": True},
            }
        )
        experiments.append(
            {
                "name": "QInt8 + per_tensor",
                "vision": {"weight_type": "QInt8", "per_channel": False},
                "text": {"weight_type": "QInt8", "per_channel": False},
            }
        )
        experiments.append(
            {
                "name": "QInt8 + per_channel + symmetric",
                "vision": {"weight_type": "QInt8", "per_channel": True, "symmetric": True},
                "text": {"weight_type": "QInt8", "per_channel": True, "symmetric": True},
            }
        )
        experiments.append(
            {
                "name": "QInt8 + per_channel + reduce_range",
                "vision": {"weight_type": "QInt8", "per_channel": True, "reduce_range": True},
                "text": {"weight_type": "QInt8", "per_channel": True, "reduce_range": True},
            }
        )

        # Phase 2: Vision encoder node exclusion sweep.
        # Sweep up to half the model depth to ensure we capture any cliff,
        # regardless of model size (base: ~8, large: ~15, giant: ~22).
        layer_indices = sorted([k for k in vision_layers if k.isdigit()], key=int)
        n_vision_layers = len(layer_indices)
        max_sweep = min(n_vision_layers // 2 + 2, n_vision_layers)

        # Exclude first N layers + projection
        for n_layers in range(1, max_sweep + 1):
            exclude: list[str] = []
            for i in range(n_layers):
                exclude.extend(vision_layers.get(str(i), []))
            exclude.extend(vision_layers.get("projection", []))
            experiments.append(
                {
                    "name": f"vision: exclude first {n_layers} layers + proj",
                    "vision": {
                        "weight_type": "QInt8",
                        "per_channel": True,
                        "nodes_to_exclude": exclude,
                    },
                    "text": {"weight_type": "QInt8", "per_channel": True},
                }
            )

        # Exclude projection only
        if "projection" in vision_layers:
            experiments.append(
                {
                    "name": "vision: exclude projection only",
                    "vision": {
                        "weight_type": "QInt8",
                        "per_channel": True,
                        "nodes_to_exclude": vision_layers["projection"],
                    },
                    "text": {"weight_type": "QInt8", "per_channel": True},
                }
            )

        # Exclude last N layers + projection
        for n_layers in [1, 2, 3]:
            exclude = []
            for idx in layer_indices[-n_layers:]:
                exclude.extend(vision_layers[idx])
            exclude.extend(vision_layers.get("projection", []))
            experiments.append(
                {
                    "name": f"vision: exclude last {n_layers} layers + proj",
                    "vision": {
                        "weight_type": "QInt8",
                        "per_channel": True,
                        "nodes_to_exclude": exclude,
                    },
                    "text": {"weight_type": "QInt8", "per_channel": True},
                }
            )

        # Exclude attention pooling (SigLIP2-specific)
        if "attn_pool" in vision_layers:
            experiments.append(
                {
                    "name": "vision: exclude attn_pool only",
                    "vision": {
                        "weight_type": "QInt8",
                        "per_channel": True,
                        "nodes_to_exclude": vision_layers["attn_pool"],
                    },
                    "text": {"weight_type": "QInt8", "per_channel": True},
                }
            )
            # attn_pool + projection
            exclude = vision_layers["attn_pool"] + vision_layers.get("projection", [])
            experiments.append(
                {
                    "name": "vision: exclude attn_pool + proj",
                    "vision": {
                        "weight_type": "QInt8",
                        "per_channel": True,
                        "nodes_to_exclude": exclude,
                    },
                    "text": {"weight_type": "QInt8", "per_channel": True},
                }
            )

        # ── Run experiments ─────────────────────────────────────────────

        print(f"\n{'=' * 80}")
        print(f"Running {len(experiments)} experiments...")
        print(f"{'=' * 80}")

        results: list[ExperimentResult] = []
        for i, exp in enumerate(experiments):
            exp_dir = Path(tmp) / f"exp_{i}"
            exp_dir.mkdir(parents=True, exist_ok=True)

            print(f"\n[{i + 1}/{len(experiments)}] {exp['name']}")

            # Quantise both encoders
            quantise_encoder(
                fp32_dir / "clip_vision_encoder.onnx",
                exp_dir / "clip_vision_encoder.onnx",
                **exp["vision"],
            )
            quantise_encoder(
                fp32_dir / "clip_text_encoder.onnx",
                exp_dir / "clip_text_encoder.onnx",
                **exp["text"],
            )

            # Measure embeddings (uses cached pixel_values/text_inputs — no NFS reads)
            # INT8 models always run on CPU regardless of --device
            onnx_img_embs, onnx_txt_embs = get_onnx_embeddings(exp_dir, pixel_values, text_inputs)

            img_diffs = cosine_diffs(torch_img_embs, onnx_img_embs)
            txt_diffs = cosine_diffs(torch_txt_embs, onnx_txt_embs)

            # Rank correlation
            rank_stats = rank_correlation(
                torch_img_embs,
                torch_txt_embs,
                onnx_img_embs,
                onnx_txt_embs,
            )

            # Model sizes
            v_size = (exp_dir / "clip_vision_encoder.onnx").stat().st_size / (1024 * 1024)
            t_size = (exp_dir / "clip_text_encoder.onnx").stat().st_size / (1024 * 1024)

            result = ExperimentResult(
                name=exp["name"],
                img_max=float(img_diffs.max()),
                img_mean=float(img_diffs.mean()),
                txt_max=float(txt_diffs.max()),
                txt_mean=float(txt_diffs.mean()),
                top5_preserved=rank_stats["pct_top5_preserved"],
                top_k_rho=rank_stats["mean_rho"],
                v_size_mb=v_size,
                t_size_mb=t_size,
                config=exp,
            )
            results.append(result)

            print(
                f"  Vision: max={result.img_max:.6f} mean={result.img_mean:.6f} ({v_size:.1f} MB)"
            )
            print(
                f"  Text:   max={result.txt_max:.6f} mean={result.txt_mean:.6f} ({t_size:.1f} MB)"
            )
            print(f"  Top-5 preserved: {result.top5_preserved:.1%}, rho: {result.top_k_rho:.4f}")

    # Summary
    print_results_table(results)

    # Save structured output
    meta = RunMeta.capture(
        model_id=model_id,
        family=FAMILY,
        image_count=len(all_images),
        text_count=len(TEXT_QUERIES),
        seed=args.seed,
        image_dir=str(args.image_dir),
    )
    save_results(meta, results, args.output_dir, prefix=f"ablation_siglip2_{args.model}")


# ── CLI ──────────────────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(
        description="SigLIP2 INT8 quantisation ablation (base / large / giant)",
    )
    parser.add_argument(
        "--model",
        type=str,
        default="base",
        choices=list(_MODEL_CONFIGS.keys()),
        help="SigLIP2 model variant to ablate (default: base)",
    )
    add_common_args(parser)
    parser.add_argument(
        "--batch-size",
        type=int,
        default=32,
        help="Images per GPU batch for torch reference embeddings (default: 32)",
    )
    args = parser.parse_args()
    run_ablation(args)


if __name__ == "__main__":
    main()
