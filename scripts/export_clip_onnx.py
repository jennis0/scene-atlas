#!/usr/bin/env python3
"""Export CLIP model to ONNX format with fp32, fp16, and int8 variants.

Requires dev dependencies: torch, transformers, onnxruntime, onnx.
Outputs ONNX graphs + tokenizer files to backend/models/.

Prerequisites:
    The model weights must be downloaded to the HuggingFace cache before
    running this script (local_files_only=True is used to avoid accidental
    network access).  Download once with:

        uv run python -c "
        from transformers import CLIPModel, CLIPProcessor
        CLIPModel.from_pretrained('laion/CLIP-ViT-B-32-laion2B-s34B-b79K')
        CLIPProcessor.from_pretrained('laion/CLIP-ViT-B-32-laion2B-s34B-b79K')
        "

Usage:
    uv run python scripts/export_clip_onnx.py
"""

import json
import shutil
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import torch
import torch.nn as nn
from transformers import CLIPModel, CLIPProcessor

MODEL_NAME = "laion/CLIP-ViT-B-32-laion2B-s34B-b79K"
OUTPUT_DIR = Path(__file__).resolve().parent.parent / "backend" / "models" / "clip-vit-b-32"
# CLIP's maximum token sequence length.  The text encoder is exported with
# this as a *fixed* dimension (only the batch axis is dynamic).  The inference
# service always pads/truncates input_ids and attention_mask to this length.
CONTEXT_LENGTH = 77


# ── Wrapper modules ──────────────────────────────────────────────────────────
# These bake in the projection head and L2 normalisation so that
# onnxruntime .run() returns the final 512-d embedding directly.


class CLIPVisionONNX(nn.Module):
    """pixel_values [B, 3, 224, 224] -> L2-normalised embeddings [B, 512]."""

    def __init__(self, model: CLIPModel):
        super().__init__()
        self.vision_model = model.vision_model
        self.visual_projection = model.visual_projection

    def forward(self, pixel_values: torch.Tensor) -> torch.Tensor:
        vision_outputs = self.vision_model(pixel_values=pixel_values)
        pooled_output = vision_outputs.pooler_output
        image_features = self.visual_projection(pooled_output)
        return torch.nn.functional.normalize(image_features, p=2, dim=-1)


class CLIPTextONNX(nn.Module):
    """input_ids + attention_mask [B, 77] -> L2-normalised embeddings [B, 512]."""

    def __init__(self, model: CLIPModel):
        super().__init__()
        self.text_model = model.text_model
        self.text_projection = model.text_projection

    def forward(self, input_ids: torch.Tensor, attention_mask: torch.Tensor) -> torch.Tensor:
        text_outputs = self.text_model(input_ids=input_ids, attention_mask=attention_mask)
        pooled_output = text_outputs.pooler_output
        text_features = self.text_projection(pooled_output)
        return torch.nn.functional.normalize(text_features, p=2, dim=-1)


# ── Export functions ─────────────────────────────────────────────────────────


def export_vision(model: CLIPModel, output_dir: Path) -> Path:
    """Export vision encoder to ONNX."""
    wrapper = CLIPVisionONNX(model)
    wrapper.eval()
    dummy_input = torch.randn(1, 3, 224, 224)
    out_path = output_dir / "clip_vision_encoder.onnx"

    torch.onnx.export(
        wrapper,
        (dummy_input,),
        str(out_path),
        input_names=["pixel_values"],
        output_names=["embeddings"],
        dynamic_axes={"pixel_values": {0: "batch"}, "embeddings": {0: "batch"}},
        opset_version=18,
        dynamo=False,
        do_constant_folding=True,
    )
    return out_path


def export_text(model: CLIPModel, output_dir: Path) -> Path:
    """Export text encoder to ONNX."""
    wrapper = CLIPTextONNX(model)
    wrapper.eval()
    dummy_ids = torch.zeros(1, CONTEXT_LENGTH, dtype=torch.long)
    dummy_mask = torch.ones(1, CONTEXT_LENGTH, dtype=torch.long)
    out_path = output_dir / "clip_text_encoder.onnx"

    torch.onnx.export(
        wrapper,
        (dummy_ids, dummy_mask),
        str(out_path),
        input_names=["input_ids", "attention_mask"],
        output_names=["embeddings"],
        dynamic_axes={
            "input_ids": {0: "batch"},
            "attention_mask": {0: "batch"},
            "embeddings": {0: "batch"},
        },
        opset_version=18,
        dynamo=False,
        do_constant_folding=True,
    )
    return out_path


def copy_tokenizer(output_dir: Path) -> None:
    """Save tokenizer files alongside the ONNX models."""
    proc = CLIPProcessor.from_pretrained(MODEL_NAME, local_files_only=True)
    tokenizer_dir = output_dir / "tokenizer"
    tokenizer_dir.mkdir(parents=True, exist_ok=True)
    proc.tokenizer.save_pretrained(str(tokenizer_dir))
    print(f"  Tokenizer saved to {tokenizer_dir}")


# ── Quantisation ─────────────────────────────────────────────────────────────


def quantise_fp16(fp32_dir: Path, fp16_dir: Path) -> None:
    """Convert fp32 ONNX models to fp16."""
    import onnx
    from onnxruntime.transformers.float16 import convert_float_to_float16

    fp16_dir.mkdir(parents=True, exist_ok=True)

    for name in ("clip_vision_encoder.onnx", "clip_text_encoder.onnx"):
        print(f"  Quantising {name} to fp16...")
        model = onnx.load(str(fp32_dir / name))
        model_fp16 = convert_float_to_float16(
            model,
            keep_io_types=True,  # keep inputs/outputs as fp32 for compatibility
        )
        onnx.save(model_fp16, str(fp16_dir / name))


def quantise_int8(fp32_dir: Path, int8_dir: Path) -> None:
    """Convert fp32 ONNX models to int8 via dynamic quantisation."""
    from onnxruntime.quantization import QuantType, quantize_dynamic

    int8_dir.mkdir(parents=True, exist_ok=True)

    for name in ("clip_vision_encoder.onnx", "clip_text_encoder.onnx"):
        print(f"  Quantising {name} to int8...")
        quantize_dynamic(
            model_input=str(fp32_dir / name),
            model_output=str(int8_dir / name),
            weight_type=QuantType.QUInt8,
        )


# ── Manifest ─────────────────────────────────────────────────────────────────


def extract_manifest(model: CLIPModel, processor: CLIPProcessor) -> dict:
    """Extract model metadata into a manifest dict.

    The manifest captures all parameters the inference service needs to
    configure itself for this model: image preprocessing, tokenizer settings,
    embedding dimension, and ONNX filenames.
    """
    img_proc = processor.image_processor
    tokenizer = processor.tokenizer

    # Determine image size (CLIPImageProcessor stores size as dict)
    size_cfg = img_proc.size
    if isinstance(size_cfg, dict):
        image_size = size_cfg.get("shortest_edge", size_cfg.get("height", 224))
    else:
        image_size = int(size_cfg)

    # Determine interpolation mode
    # CLIPImageProcessor.resample is a PILImageResampling enum
    resample = getattr(img_proc, "resample", None)
    if resample is not None:
        # PILImageResampling: 3 = BICUBIC, 2 = BILINEAR
        interpolation = "bicubic" if int(resample) == 3 else "bilinear"
    else:
        interpolation = "bicubic"

    # Determine resize mode
    do_center_crop = getattr(img_proc, "do_center_crop", True)
    resize_mode = "shortest_edge_then_crop" if do_center_crop else "direct_resize"

    # Embedding dimension from the projection head
    embedding_dim = model.config.projection_dim

    return {
        "model_id": MODEL_NAME,
        "model_family": "clip",
        "embedding_dim": embedding_dim,
        "image_size": image_size,
        "image_mean": list(img_proc.image_mean),
        "image_std": list(img_proc.image_std),
        "interpolation": interpolation,
        "resize_mode": resize_mode,
        "tokenizer_type": "huggingface",
        "tokenizer_max_length": tokenizer.model_max_length,
        "tokenizer_pad_id": tokenizer.pad_token_id,
        "vision_encoder": "clip_vision_encoder.onnx",
        "text_encoder": "clip_text_encoder.onnx",
        "exported_at": datetime.now(UTC).isoformat(),
    }


def write_manifest(manifest: dict, output_dir: Path) -> None:
    """Write manifest.json to the given directory."""
    path = output_dir / "manifest.json"
    path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"  Manifest written to {path}")


# ── Sanity check ─────────────────────────────────────────────────────────────


def sanity_check(model: CLIPModel, processor: CLIPProcessor, onnx_dir: Path) -> None:
    """Quick sanity check: compare torch vs ONNX for a dummy input."""
    import onnxruntime as ort

    print(f"\n  Sanity check against {onnx_dir.name} variant...")

    # Vision check
    dummy_pixels = torch.randn(1, 3, 224, 224)
    with torch.no_grad():
        vo = model.vision_model(pixel_values=dummy_pixels)
        torch_emb = model.visual_projection(vo.pooler_output)
        torch_emb = torch.nn.functional.normalize(torch_emb, p=2, dim=-1).numpy()

    sess = ort.InferenceSession(
        str(onnx_dir / "clip_vision_encoder.onnx"),
        providers=["CPUExecutionProvider"],
    )
    (onnx_emb,) = sess.run(["embeddings"], {"pixel_values": dummy_pixels.numpy()})
    vision_dot = float(np.dot(torch_emb[0], onnx_emb[0]))
    print(f"    Vision dot product: {vision_dot:.8f}  (diff from 1.0: {abs(1.0 - vision_dot):.2e})")

    # Text check
    dummy_text = "a dark forest with a river"
    inputs = processor(text=dummy_text, return_tensors="pt", padding="max_length", max_length=77)
    with torch.no_grad():
        to = model.text_model(
            input_ids=inputs["input_ids"], attention_mask=inputs["attention_mask"]
        )
        torch_text_emb = model.text_projection(to.pooler_output)
        torch_text_emb = torch.nn.functional.normalize(torch_text_emb, p=2, dim=-1).numpy()

    text_sess = ort.InferenceSession(
        str(onnx_dir / "clip_text_encoder.onnx"),
        providers=["CPUExecutionProvider"],
    )
    (onnx_text_emb,) = text_sess.run(
        ["embeddings"],
        {
            "input_ids": inputs["input_ids"].numpy(),
            "attention_mask": inputs["attention_mask"].numpy(),
        },
    )
    text_dot = float(np.dot(torch_text_emb[0], onnx_text_emb[0]))
    print(f"    Text dot product:   {text_dot:.8f}  (diff from 1.0: {abs(1.0 - text_dot):.2e})")


# ── Main ─────────────────────────────────────────────────────────────────────


def print_size_table(base_dir: Path) -> None:
    """Print a size comparison table for all variants."""
    print("\n" + "=" * 70)
    print("Model Size Comparison")
    print("=" * 70)
    print(f"  {'Variant':<8} {'Vision':<15} {'Text':<15} {'Total':<15}")
    print("-" * 70)

    for variant in ("fp32", "fp16", "int8"):
        vdir = base_dir / variant
        if not vdir.exists():
            continue
        vision = vdir / "clip_vision_encoder.onnx"
        text = vdir / "clip_text_encoder.onnx"
        v_size = vision.stat().st_size / (1024 * 1024) if vision.exists() else 0
        t_size = text.stat().st_size / (1024 * 1024) if text.exists() else 0
        print(
            f"  {variant:<8} {v_size:>10.1f} MB   {t_size:>10.1f} MB   {v_size + t_size:>10.1f} MB"
        )

    # Tokenizer
    tok_dir = base_dir / "tokenizer"
    if tok_dir.exists():
        tok_size = sum(f.stat().st_size for f in tok_dir.rglob("*") if f.is_file())
        print(f"  {'tokenizer':<8} {'':>15} {'':>15} {tok_size / (1024 * 1024):>10.1f} MB")

    print("=" * 70)


def main() -> None:
    # Clean output directory
    if OUTPUT_DIR.exists():
        shutil.rmtree(OUTPUT_DIR)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    fp32_dir = OUTPUT_DIR / "fp32"
    fp16_dir = OUTPUT_DIR / "fp16"
    int8_dir = OUTPUT_DIR / "int8"
    fp32_dir.mkdir(parents=True, exist_ok=True)

    # Load model
    print(f"Loading model: {MODEL_NAME}")
    model = CLIPModel.from_pretrained(MODEL_NAME, local_files_only=True)
    model.eval()
    processor = CLIPProcessor.from_pretrained(MODEL_NAME, local_files_only=True)

    # Export fp32
    print("\nExporting fp32 vision encoder...")
    export_vision(model, fp32_dir)
    print("Exporting fp32 text encoder...")
    export_text(model, fp32_dir)

    # Save tokenizer (shared across all variants)
    print("\nSaving tokenizer...")
    copy_tokenizer(OUTPUT_DIR)

    # Generate manifest
    print("\nGenerating manifest...")
    manifest = extract_manifest(model, processor)

    # Sanity check fp32
    write_manifest(manifest, fp32_dir)
    sanity_check(model, processor, fp32_dir)

    # Quantise to fp16
    print("\nQuantising to fp16...")
    quantise_fp16(fp32_dir, fp16_dir)
    write_manifest(manifest, fp16_dir)
    sanity_check(model, processor, fp16_dir)

    # Quantise to int8
    print("\nQuantising to int8...")
    quantise_int8(fp32_dir, int8_dir)
    write_manifest(manifest, int8_dir)
    sanity_check(model, processor, int8_dir)

    # Size report
    print_size_table(OUTPUT_DIR)

    print("\nExport complete.")
    print(f"Models at: {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
