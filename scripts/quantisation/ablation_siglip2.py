#!/usr/bin/env python3
"""INT8 quantisation ablation experiments for SigLIP2-base.

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
        --image-dir /path/to/images [--max-images 500] [--seed 42]
"""

from __future__ import annotations

import argparse
import tempfile
from pathlib import Path

import numpy as np
import torch
import torch.nn.functional as F
from PIL import Image as PILImage
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
    print_results_table,
    quantise_encoder,
    rank_correlation,
    save_results,
)

MODEL_ID = "google/siglip2-base-patch16-224"
FAMILY = "siglip2"

# fp32 ONNX models exported by export_model_onnx.py
SCRIPT_DIR = Path(__file__).resolve().parent
FP32_DIR = SCRIPT_DIR.parent.parent / "backend" / "models" / "siglip2-base" / "fp32"


# ── Embedding computation ───────────────────────────────────────────────────


def get_torch_embeddings(
    model,
    processor,
    images: list[Path],
    texts: list[str],
) -> tuple[list[Path], list[np.ndarray], list[np.ndarray]]:
    """Compute normalised torch reference embeddings."""
    print(f"  Computing torch reference for {len(images)} images, {len(texts)} texts...")

    PILImage.MAX_IMAGE_PIXELS = 300_000_000

    image_embs: list[tuple[Path, np.ndarray]] = []
    skipped: list[tuple[str, str]] = []
    for p in images:
        try:
            with PILImage.open(p) as img:
                image = img.convert("RGB")
        except Exception as e:
            skipped.append((p.name, str(e)))
            continue
        inputs = processor(images=image, return_tensors="pt")
        with torch.no_grad():
            features = model.get_image_features(**inputs)
            features = F.normalize(features, p=2, dim=-1)
        image_embs.append((p, features.numpy().flatten()))

    if skipped:
        print(f"  Skipped {len(skipped)} images: {skipped[0]}")

    text_embs: list[np.ndarray] = []
    max_length = model.config.text_config.max_position_embeddings
    for t in texts:
        # SigLIP2 was trained on lowercased text; the production SentencePiece
        # wrapper lowercases, so the torch reference must match.
        inputs = processor(
            text=t.lower(),
            return_tensors="pt",
            padding="max_length",
            max_length=max_length,
            return_attention_mask=True,
        )
        with torch.no_grad():
            features = model.get_text_features(
                input_ids=inputs["input_ids"],
                attention_mask=inputs["attention_mask"],
            )
            features = F.normalize(features, p=2, dim=-1)
        text_embs.append(features.numpy().flatten())

    valid_paths = [p for p, _ in image_embs]
    valid_embs = [e for _, e in image_embs]
    return valid_paths, valid_embs, text_embs


def get_onnx_embeddings(
    onnx_dir: Path,
    images: list[Path],
    texts: list[str],
    processor,
) -> tuple[list[np.ndarray], list[np.ndarray]]:
    """Compute ONNX embeddings using production-matching session options."""
    PILImage.MAX_IMAGE_PIXELS = 300_000_000

    vision_sess = create_ort_session(onnx_dir / "clip_vision_encoder.onnx")
    text_sess = create_ort_session(onnx_dir / "clip_text_encoder.onnx")

    image_embs: list[np.ndarray] = []
    for p in images:
        with PILImage.open(p) as img:
            image = img.convert("RGB")
        inputs = processor(images=image, return_tensors="np")
        (emb,) = vision_sess.run(["embeddings"], {"pixel_values": inputs["pixel_values"]})
        image_embs.append(emb.flatten())

    max_length = 64  # siglip2-base context length
    text_embs: list[np.ndarray] = []
    for t in texts:
        # Lowercase to match production SentencePiece wrapper behaviour
        inputs = processor(
            text=t.lower(),
            return_tensors="np",
            padding="max_length",
            max_length=max_length,
            return_attention_mask=True,
        )
        (emb,) = text_sess.run(
            ["embeddings"],
            {
                "input_ids": inputs["input_ids"],
                "attention_mask": inputs["attention_mask"],
            },
        )
        text_embs.append(emb.flatten())

    return image_embs, text_embs


# ── Experiment runner ────────────────────────────────────────────────────────


def run_ablation(args: argparse.Namespace) -> None:
    """Run the full SigLIP2 ablation experiment suite."""
    print("=" * 80)
    print("SigLIP2-base INT8 Quantisation Ablation")
    print("=" * 80)

    # Load model
    print("\nLoading model...")
    model = AutoModel.from_pretrained(MODEL_ID, local_files_only=True)
    model.eval()
    processor = AutoProcessor.from_pretrained(MODEL_ID, local_files_only=True)

    # Collect test data
    all_images = collect_images(args.image_dir, args.max_images, args.seed)
    print(f"  Collected {len(all_images)} real images")

    with tempfile.TemporaryDirectory(prefix="ablation_siglip2_") as tmp:
        # Torch reference
        print("\nComputing torch reference embeddings...")
        valid_images, torch_img_embs, torch_txt_embs = get_torch_embeddings(
            model, processor, all_images, TEXT_QUERIES
        )
        all_images = valid_images
        print(f"  {len(all_images)} images loaded successfully")

        # Inspect node structure
        print("\n--- Vision encoder node structure ---")
        vision_layers = find_layer_nodes(FP32_DIR / "clip_vision_encoder.onnx")
        print("\n--- Text encoder node structure ---")
        find_layer_nodes(FP32_DIR / "clip_text_encoder.onnx")  # print structure

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

        # Phase 2: Vision encoder node exclusion sweep (extended to 8 layers)
        layer_indices = sorted([k for k in vision_layers if k.isdigit()], key=int)
        n_vision_layers = len(layer_indices)

        # Exclude first N layers + projection
        for n_layers in range(1, min(9, n_vision_layers + 1)):
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
                FP32_DIR / "clip_vision_encoder.onnx",
                exp_dir / "clip_vision_encoder.onnx",
                **exp["vision"],
            )
            quantise_encoder(
                FP32_DIR / "clip_text_encoder.onnx",
                exp_dir / "clip_text_encoder.onnx",
                **exp["text"],
            )

            # Measure embeddings
            onnx_img_embs, onnx_txt_embs = get_onnx_embeddings(
                exp_dir, all_images, TEXT_QUERIES, processor
            )

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
        model_id=MODEL_ID,
        family=FAMILY,
        image_count=len(all_images),
        text_count=len(TEXT_QUERIES),
        seed=args.seed,
        image_dir=str(args.image_dir),
    )
    save_results(meta, results, args.output_dir, prefix="ablation_siglip2")


# ── CLI ──────────────────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(
        description="SigLIP2-base INT8 quantisation ablation",
    )
    add_common_args(parser)
    args = parser.parse_args()
    run_ablation(args)


if __name__ == "__main__":
    main()
