#!/usr/bin/env python3
"""INT8 quantisation ablation experiments for CLIP ViT-B/32.

Systematically tests different quantisation configurations and measures
cosine similarity + retrieval rank correlation against the fp32 torch
reference, following the methodology in design/onnx-int8-quantisation.md.

CLIP's key challenge is the *text* encoder — the vision encoder quantises
cleanly.  This script focuses the exclusion sweep on the text encoder
(first N layers + projection) and also tests hybrid (fp16 vision + int8
text) vs pure int8.

Ablation results are *relative* (config vs config).  For production-
representative numbers, use ``scripts/export_model_onnx.py --image-dir``.

Usage:
    uv run python -m scripts.quantisation.ablation_clip \\
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
    get_torch_device,
    print_results_table,
    quantise_encoder,
    rank_correlation,
    save_results,
)

MODEL_ID = "laion/CLIP-ViT-B-32-laion2B-s34B-b79K"
FAMILY = "clip"

SCRIPT_DIR = Path(__file__).resolve().parent
FP32_DIR = SCRIPT_DIR.parent.parent / "backend" / "models" / "clip-vit-b-32" / "fp32"


# ── Embedding computation ───────────────────────────────────────────────────


def get_torch_embeddings(
    model,
    processor,
    images: list[Path],
    texts: list[str],
    torch_device: str = "cpu",
) -> tuple[list[Path], list[np.ndarray], list[np.ndarray]]:
    """Compute normalised torch reference embeddings for CLIP."""
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
        inputs = {k: v.to(torch_device) for k, v in inputs.items()}
        with torch.no_grad():
            features = model.get_image_features(**inputs)
            features = F.normalize(features, p=2, dim=-1)
        image_embs.append((p, features.cpu().numpy().flatten()))

    if skipped:
        print(f"  Skipped {len(skipped)} images: {skipped[0]}")

    text_embs: list[np.ndarray] = []
    for t in texts:
        # CLIP tokenizer handles casing internally — no lowercasing needed
        inputs = processor(
            text=t,
            return_tensors="pt",
            padding="max_length",
            max_length=77,
            truncation=True,
        )
        inputs = {k: v.to(torch_device) for k, v in inputs.items()}
        with torch.no_grad():
            features = model.get_text_features(
                input_ids=inputs["input_ids"],
                attention_mask=inputs["attention_mask"],
            )
            features = F.normalize(features, p=2, dim=-1)
        text_embs.append(features.cpu().numpy().flatten())

    valid_paths = [p for p, _ in image_embs]
    valid_embs = [e for _, e in image_embs]
    return valid_paths, valid_embs, text_embs


def get_onnx_embeddings(
    onnx_dir: Path,
    images: list[Path],
    texts: list[str],
    processor,
    device: str = "cpu",
) -> tuple[list[np.ndarray], list[np.ndarray]]:
    """Compute ONNX embeddings using production-matching session options."""
    PILImage.MAX_IMAGE_PIXELS = 300_000_000

    vision_sess = create_ort_session(onnx_dir / "clip_vision_encoder.onnx", device=device)
    text_sess = create_ort_session(onnx_dir / "clip_text_encoder.onnx", device=device)

    image_embs: list[np.ndarray] = []
    for p in images:
        with PILImage.open(p) as img:
            image = img.convert("RGB")
        inputs = processor(images=image, return_tensors="np")
        (emb,) = vision_sess.run(["embeddings"], {"pixel_values": inputs["pixel_values"]})
        image_embs.append(emb.flatten())

    text_embs: list[np.ndarray] = []
    for t in texts:
        inputs = processor(
            text=t,
            return_tensors="np",
            padding="max_length",
            max_length=77,
            truncation=True,
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
    """Run the full CLIP ViT-B/32 ablation experiment suite."""
    print("=" * 80)
    print("CLIP ViT-B/32 INT8 Quantisation Ablation")
    print("=" * 80)

    # Resolve devices
    torch_dev = get_torch_device(args.device)
    print(f"  ONNX device: {args.device}, torch device: {torch_dev}")

    # Load model
    print("\nLoading model...")
    model = AutoModel.from_pretrained(MODEL_ID, local_files_only=True)
    model.eval()
    model.to(torch_dev)
    processor = AutoProcessor.from_pretrained(MODEL_ID, local_files_only=True)

    # Collect test data
    all_images = collect_images(args.image_dir, args.max_images, args.seed)
    print(f"  Collected {len(all_images)} real images")

    with tempfile.TemporaryDirectory(prefix="ablation_clip_") as tmp:
        # Torch reference
        print("\nComputing torch reference embeddings...")
        valid_images, torch_img_embs, torch_txt_embs = get_torch_embeddings(
            model, processor, all_images, TEXT_QUERIES, torch_dev
        )
        all_images = valid_images
        print(f"  {len(all_images)} images loaded successfully")

        # Inspect node structure
        print("\n--- Vision encoder node structure ---")
        find_layer_nodes(FP32_DIR / "clip_vision_encoder.onnx")  # print structure
        print("\n--- Text encoder node structure ---")
        text_layers = find_layer_nodes(FP32_DIR / "clip_text_encoder.onnx")

        # ── Define experiments ──────────────────────────────────────────

        experiments: list[dict] = []

        # Phase 1: Parameter tuning (both encoders)
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

        # Phase 2: Text encoder exclusion sweep (CLIP's problem child)
        text_layer_indices = sorted([k for k in text_layers if k.isdigit()], key=int)

        # Exclude first N text layers + projection
        for n_layers in range(1, min(7, len(text_layer_indices) + 1)):
            exclude: list[str] = []
            for i in range(n_layers):
                exclude.extend(text_layers.get(str(i), []))
            exclude.extend(text_layers.get("projection", []))
            experiments.append(
                {
                    "name": f"text: exclude first {n_layers} layers + proj",
                    "vision": {"weight_type": "QInt8", "per_channel": True},
                    "text": {
                        "weight_type": "QInt8",
                        "per_channel": True,
                        "nodes_to_exclude": exclude,
                    },
                }
            )

        # Exclude projection only
        if "projection" in text_layers:
            experiments.append(
                {
                    "name": "text: exclude projection only",
                    "vision": {"weight_type": "QInt8", "per_channel": True},
                    "text": {
                        "weight_type": "QInt8",
                        "per_channel": True,
                        "nodes_to_exclude": text_layers["projection"],
                    },
                }
            )

        # Exclude last N text layers + projection
        for n_layers in [1, 2, 3]:
            if n_layers > len(text_layer_indices):
                break
            exclude = []
            for idx in text_layer_indices[-n_layers:]:
                exclude.extend(text_layers[idx])
            exclude.extend(text_layers.get("projection", []))
            experiments.append(
                {
                    "name": f"text: exclude last {n_layers} layers + proj",
                    "vision": {"weight_type": "QInt8", "per_channel": True},
                    "text": {
                        "weight_type": "QInt8",
                        "per_channel": True,
                        "nodes_to_exclude": exclude,
                    },
                }
            )

        # Phase 3: Hybrid test — fp16 vision + int8 text (with best exclusion)
        # Use first 1 layer + projection exclusion (the historically winning config)
        text_exclude_best: list[str] = []
        text_exclude_best.extend(text_layers.get("0", []))
        text_exclude_best.extend(text_layers.get("projection", []))
        experiments.append(
            {
                "name": "HYBRID: fp16 vision + int8 text (excl L0+proj)",
                "vision": "fp16",  # special marker — copy from fp16 instead of quantising
                "text": {
                    "weight_type": "QInt8",
                    "per_channel": True,
                    "nodes_to_exclude": text_exclude_best,
                },
            }
        )

        # ── Run experiments ─────────────────────────────────────────────

        print(f"\n{'=' * 80}")
        print(f"Running {len(experiments)} experiments...")
        print(f"{'=' * 80}")

        fp16_dir = FP32_DIR.parent / "fp16"

        results: list[ExperimentResult] = []
        for i, exp in enumerate(experiments):
            exp_dir = Path(tmp) / f"exp_{i}"
            exp_dir.mkdir(parents=True, exist_ok=True)

            print(f"\n[{i + 1}/{len(experiments)}] {exp['name']}")

            # Vision encoder
            if exp["vision"] == "fp16":
                # Hybrid mode — copy fp16 vision encoder
                import shutil

                shutil.copy2(
                    str(fp16_dir / "clip_vision_encoder.onnx"),
                    str(exp_dir / "clip_vision_encoder.onnx"),
                )
            else:
                quantise_encoder(
                    FP32_DIR / "clip_vision_encoder.onnx",
                    exp_dir / "clip_vision_encoder.onnx",
                    **exp["vision"],
                )

            # Text encoder
            quantise_encoder(
                FP32_DIR / "clip_text_encoder.onnx",
                exp_dir / "clip_text_encoder.onnx",
                **exp["text"],
            )

            # Measure embeddings
            onnx_img_embs, onnx_txt_embs = get_onnx_embeddings(
                exp_dir, all_images, TEXT_QUERIES, processor, args.device
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
    save_results(meta, results, args.output_dir, prefix="ablation_clip")


# ── CLI ──────────────────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(
        description="CLIP ViT-B/32 INT8 quantisation ablation",
    )
    add_common_args(parser)
    args = parser.parse_args()
    run_ablation(args)


if __name__ == "__main__":
    main()
