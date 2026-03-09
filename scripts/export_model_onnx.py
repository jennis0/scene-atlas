#!/usr/bin/env python3
"""Export embedding models (CLIP, SigLIP2) to ONNX format.

Requires dev dependencies: torch, transformers, onnxruntime, onnx.
Outputs ONNX graphs + tokenizer files + manifest.json to backend/models/<output-name>/.

Usage:
    # Export a specific model by name:
    uv run python scripts/export_model_onnx.py clip-vit-b-32
    uv run python scripts/export_model_onnx.py siglip2-base

    # Export all registered models:
    uv run python scripts/export_model_onnx.py --all

    # List available models:
    uv run python scripts/export_model_onnx.py --list
"""

import argparse
import json
import shutil
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F
from transformers import AutoConfig, AutoModel, AutoProcessor

# ── Model registry ───────────────────────────────────────────────────────────

MODEL_REGISTRY: list[dict] = [
    {
        "name": "clip-vit-b-32",
        "model_id": "laion/CLIP-ViT-B-32-laion2B-s34B-b79K",
        "quants": ["fp32", "fp16", "int8"],
    },
    {
        "name": "siglip2-base",
        "model_id": "google/siglip2-base-patch16-224",
        "quants": ["fp32", "fp16", "int8"],
    },
    {
        "name": "siglip2-so400m",
        "model_id": "google/siglip2-so400m-patch14-384",
        "quants": ["fp32", "fp16", "int8"],
    },
]

MODEL_BY_NAME = {m["name"]: m for m in MODEL_REGISTRY}


# ── CLI ──────────────────────────────────────────────────────────────────────


def parse_args() -> argparse.Namespace:
    names = [m["name"] for m in MODEL_REGISTRY]
    parser = argparse.ArgumentParser(
        description="Export embedding models to ONNX.",
        epilog=f"Available models: {', '.join(names)}",
    )
    parser.add_argument(
        "models",
        nargs="*",
        metavar="MODEL",
        help="Model name(s) to export (see --list for available models)",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Export all registered models",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        dest="list_models",
        help="List available models and exit",
    )
    args = parser.parse_args()

    if args.list_models:
        print("Available models:")
        for m in MODEL_REGISTRY:
            print(f"  {m['name']:<25} {m['model_id']}")
            print(f"  {'':25} quants: {', '.join(m['quants'])}")
        raise SystemExit(0)

    if args.all:
        args.models = names
    elif not args.models:
        parser.error("specify model name(s) or --all (use --list to see available models)")

    for name in args.models:
        if name not in MODEL_BY_NAME:
            parser.error(f"unknown model '{name}' (use --list to see available models)")

    return args


# ── Family detection ─────────────────────────────────────────────────────────


def detect_family(model_id: str) -> str:
    """Auto-detect model family from the HuggingFace config class name."""
    config = AutoConfig.from_pretrained(model_id, local_files_only=False)
    class_name = type(config).__name__
    if class_name in ("SiglipConfig", "Siglip2Config"):
        return "siglip2"
    if class_name == "CLIPConfig":
        return "clip"
    raise ValueError(
        f"Unsupported config class '{class_name}' for model '{model_id}'. "
        "Expected CLIPConfig, SiglipConfig, or Siglip2Config."
    )


# ── CLIP wrapper modules ────────────────────────────────────────────────────


class CLIPVisionONNX(nn.Module):
    """pixel_values [B, 3, H, H] -> L2-normalised embeddings [B, D]."""

    def __init__(self, model):
        super().__init__()
        self.vision_model = model.vision_model
        self.visual_projection = model.visual_projection

    def forward(self, pixel_values: torch.Tensor) -> torch.Tensor:
        vision_outputs = self.vision_model(pixel_values=pixel_values)
        pooled_output = vision_outputs.pooler_output
        image_features = self.visual_projection(pooled_output)
        return F.normalize(image_features, p=2, dim=-1)


class CLIPTextONNX(nn.Module):
    """input_ids + attention_mask [B, L] -> L2-normalised embeddings [B, D]."""

    def __init__(self, model):
        super().__init__()
        self.text_model = model.text_model
        self.text_projection = model.text_projection

    def forward(self, input_ids: torch.Tensor, attention_mask: torch.Tensor) -> torch.Tensor:
        text_outputs = self.text_model(input_ids=input_ids, attention_mask=attention_mask)
        pooled_output = text_outputs.pooler_output
        text_features = self.text_projection(pooled_output)
        return F.normalize(text_features, p=2, dim=-1)


# ── SigLIP2 wrapper modules ─────────────────────────────────────────────────


class SigLIP2VisionONNX(nn.Module):
    """pixel_values [B, 3, H, H] -> L2-normalised embeddings [B, D]."""

    def __init__(self, model):
        super().__init__()
        self.model = model

    def forward(self, pixel_values: torch.Tensor) -> torch.Tensor:
        image_features = self.model.get_image_features(pixel_values=pixel_values)
        return F.normalize(image_features, p=2, dim=-1)


class SigLIP2TextONNX(nn.Module):
    """input_ids + attention_mask [B, L] -> L2-normalised embeddings [B, D]."""

    def __init__(self, model):
        super().__init__()
        self.model = model

    def forward(self, input_ids: torch.Tensor, attention_mask: torch.Tensor) -> torch.Tensor:
        text_features = self.model.get_text_features(
            input_ids=input_ids, attention_mask=attention_mask
        )
        return F.normalize(text_features, p=2, dim=-1)


# ── Export functions ─────────────────────────────────────────────────────────

ENCODER_NAMES = {
    "vision": "clip_vision_encoder.onnx",
    "text": "clip_text_encoder.onnx",
}


def export_vision(model, family: str, image_size: int, output_dir: Path) -> Path:
    """Export vision encoder to ONNX."""
    if family == "clip":
        wrapper = CLIPVisionONNX(model)
    else:
        wrapper = SigLIP2VisionONNX(model)
    wrapper.eval()

    dummy_input = torch.randn(1, 3, image_size, image_size)
    out_path = output_dir / ENCODER_NAMES["vision"]

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


def export_text(model, family: str, context_length: int, output_dir: Path) -> Path:
    """Export text encoder to ONNX."""
    if family == "clip":
        wrapper = CLIPTextONNX(model)
    else:
        wrapper = SigLIP2TextONNX(model)
    wrapper.eval()

    dummy_ids = torch.zeros(1, context_length, dtype=torch.long)
    dummy_mask = torch.ones(1, context_length, dtype=torch.long)
    out_path = output_dir / ENCODER_NAMES["text"]

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


# ── Tokenizer saving ────────────────────────────────────────────────────────


def save_tokenizer_clip(processor, output_dir: Path) -> None:
    """Save HuggingFace fast tokenizer files."""
    tokenizer_dir = output_dir / "tokenizer"
    tokenizer_dir.mkdir(parents=True, exist_ok=True)
    processor.tokenizer.save_pretrained(str(tokenizer_dir))
    print(f"  Tokenizer (huggingface) saved to {tokenizer_dir}")


def save_tokenizer_siglip2(processor, output_dir: Path) -> None:
    """Save SentencePiece model file for SigLIP2."""
    tokenizer_dir = output_dir / "tokenizer"
    tokenizer_dir.mkdir(parents=True, exist_ok=True)

    tokenizer = processor.tokenizer
    # The tokenizer's vocab_file attribute points to the .model file
    sp_model_path = getattr(tokenizer, "vocab_file", None) or getattr(tokenizer, "sp_model", None)
    if sp_model_path is None:
        raise RuntimeError(
            "Could not find sentencepiece model file on the tokenizer. "
            "Checked 'vocab_file' and 'sp_model' attributes."
        )

    src = Path(sp_model_path)
    dst = tokenizer_dir / "spiece.model"
    shutil.copy2(str(src), str(dst))
    print(f"  Tokenizer (sentencepiece) saved to {dst}")


# ── Quantisation ─────────────────────────────────────────────────────────────


def _preprocess_for_quantisation(src: Path, dst: Path) -> Path:
    """Run ORT pre-processing (shape inference + graph optimisation) on a model.

    The ONNX Runtime docs recommend this before any quantisation step so that
    tensor shape information is available for higher-quality quantisation.
    """
    from onnxruntime.quantization.preprocess import quant_pre_process

    print(f"    Pre-processing {src.name}...")
    # Skip symbolic shape inference — it fails on CLIP/SigLIP Expand ops
    # (TypeError in _broadcast_shapes). ONNX shape inference + model
    # optimisation still run and provide the tensor shape info that
    # quantisation needs.
    quant_pre_process(str(src), str(dst), skip_symbolic_shape=True)

    return dst


def quantise_fp16(fp32_dir: Path, fp16_dir: Path) -> None:
    """Convert fp32 ONNX models to fp16."""
    import onnx
    from onnxruntime.transformers.float16 import convert_float_to_float16

    fp16_dir.mkdir(parents=True, exist_ok=True)

    for name in ENCODER_NAMES.values():
        print(f"  Quantising {name} to fp16...")
        preprocessed = fp16_dir / f"_pre_{name}"
        _preprocess_for_quantisation(fp32_dir / name, preprocessed)

        model = onnx.load(str(preprocessed))
        model_fp16 = convert_float_to_float16(
            model,
            keep_io_types=True,
        )
        onnx.save(model_fp16, str(fp16_dir / name))
        preprocessed.unlink(missing_ok=True)


def _find_int8_exclusions(onnx_path: Path, family: str) -> list[str]:
    """Find nodes that should be excluded from int8 quantisation.

    Model-family-aware: CLIP text encoders need first-layer + projection
    exclusion to prevent error accumulation. SigLIP2 text encoders quantise
    cleanly without exclusions (max diff ~0.01 on 100+ real images).
    """
    if family == "siglip2":
        # SigLIP2 text encoder quantises cleanly — no exclusions needed
        return []

    import onnx

    model = onnx.load(str(onnx_path))
    matmuls = [n.name for n in model.graph.node if n.op_type == "MatMul"]

    # CLIP: exclude first transformer layer (layers.0/) and the final projection
    exclude = [n for n in matmuls if "layers.0/" in n or "projection/MatMul" in n]
    if exclude:
        print(f"    Excluding {len(exclude)} sensitive nodes from quantisation")
    return exclude


def quantise_int8(fp32_dir: Path, fp16_dir: Path, int8_dir: Path, family: str) -> None:
    """Create a hybrid int8 variant: fp16 vision + int8 text.

    SigLIP2 vision doesn't quantise cleanly to int8 (max cosine diff ~0.32).
    CLIP vision quantises well (~0.004) but we use fp16 for consistency.
    The text encoder uses int8 — CLIP needs first-layer + projection
    exclusion; SigLIP2 quantises cleanly without exclusions.

    On Windows, ``quantize_dynamic`` internally creates a temp file for
    shape inference that fails with ``FileNotFoundError``.  We work around
    this by running ``quant_pre_process`` first to a named file, then
    quantising that.
    """
    import shutil

    from onnxruntime.quantization import QuantType, quantize_dynamic
    from onnxruntime.quantization.preprocess import quant_pre_process

    int8_dir.mkdir(parents=True, exist_ok=True)

    # Vision encoder: copy from fp16 (int8 vision has unacceptable quality for SigLIP2)
    vision_name = ENCODER_NAMES["vision"]
    print(f"  Copying {vision_name} from fp16 (hybrid: vision stays fp16)...")
    shutil.copy2(str(fp16_dir / vision_name), str(int8_dir / vision_name))

    # Text encoder: int8 with family-specific exclusions
    text_name = ENCODER_NAMES["text"]
    print(f"  Quantising {text_name} to int8...")
    nodes_to_exclude = _find_int8_exclusions(fp32_dir / text_name, family)

    # Pre-process to a named file to avoid Windows temp file issues
    preprocessed = int8_dir / f"_pre_{text_name}"
    quant_pre_process(str(fp32_dir / text_name), str(preprocessed), skip_symbolic_shape=True)

    quantize_dynamic(
        model_input=str(preprocessed),
        model_output=str(int8_dir / text_name),
        weight_type=QuantType.QInt8,
        per_channel=True,
        nodes_to_exclude=nodes_to_exclude or None,
    )

    preprocessed.unlink(missing_ok=True)


# ── Manifest ─────────────────────────────────────────────────────────────────


def extract_manifest(model, processor, model_id: str, family: str) -> dict:
    """Extract model metadata into a manifest dict."""
    img_proc = processor.image_processor
    tokenizer = processor.tokenizer

    # Determine image size
    size_cfg = img_proc.size
    if isinstance(size_cfg, dict):
        image_size = size_cfg.get("shortest_edge", size_cfg.get("height", 224))
    else:
        image_size = int(size_cfg)

    # Determine interpolation mode
    resample = getattr(img_proc, "resample", None)
    if resample is not None:
        # PILImageResampling: 3 = BICUBIC, 2 = BILINEAR
        interpolation = "bicubic" if int(resample) == 3 else "bilinear"
    else:
        interpolation = "bicubic"

    # Determine resize mode — CLIP uses shortest-edge + center-crop,
    # SigLIP2 resizes directly to (size, size) without cropping.
    do_center_crop = getattr(img_proc, "do_center_crop", False)
    resize_mode = "shortest_edge_then_crop" if do_center_crop else "direct_resize"

    # Embedding dimension — CLIP uses projection_dim on the top-level config,
    # SigLIP/SigLIP2 stores it on the text_config or defaults to hidden_size
    embedding_dim = getattr(model.config, "projection_dim", None)
    if embedding_dim is None:
        embedding_dim = getattr(model.config.text_config, "projection_dim", None)
    if embedding_dim is None:
        # SigLIP2 uses hidden_size as embedding dim when no projection exists
        embedding_dim = model.config.text_config.hidden_size

    # Tokenizer config
    # Some tokenizers report model_max_length as ~1e30 (effectively infinity).
    # Fall back to text_config.max_position_embeddings which is the real limit.
    tok_max_length = getattr(tokenizer, "model_max_length", None)
    if tok_max_length is None or tok_max_length > 1_000_000:
        tok_max_length = model.config.text_config.max_position_embeddings

    if family == "siglip2":
        tokenizer_type = "sentencepiece"
        tok_pad_id = getattr(tokenizer, "pad_token_id", 1)
        # SigLIP2's HF tokenizer appends EOS after text tokens; we need to
        # replicate this in the sentencepiece wrapper at inference time.
        tok_eos_id = getattr(tokenizer, "eos_token_id", None)
    else:
        tokenizer_type = "huggingface"
        tok_pad_id = getattr(tokenizer, "pad_token_id", 49407)
        tok_eos_id = None  # HF fast tokenizer handles EOS internally

    manifest = {
        "model_id": model_id,
        "model_family": family,
        "embedding_dim": embedding_dim,
        "image_size": image_size,
        "image_mean": list(img_proc.image_mean),
        "image_std": list(img_proc.image_std),
        "interpolation": interpolation,
        "resize_mode": resize_mode,
        "tokenizer_type": tokenizer_type,
        "tokenizer_max_length": tok_max_length,
        "tokenizer_pad_id": tok_pad_id,
        "vision_encoder": ENCODER_NAMES["vision"],
        "text_encoder": ENCODER_NAMES["text"],
        "exported_at": datetime.now(UTC).isoformat(),
    }

    # Only include tokenizer_eos_id when set (sentencepiece models)
    if tok_eos_id is not None:
        manifest["tokenizer_eos_id"] = tok_eos_id

    return manifest


def write_manifest(manifest: dict, output_dir: Path) -> None:
    """Write manifest.json to the given directory."""
    path = output_dir / "manifest.json"
    path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"  Manifest written to {path}")


# ── Sanity check ─────────────────────────────────────────────────────────────


def sanity_check(
    model, processor, family: str, image_size: int, context_length: int, onnx_dir: Path
) -> None:
    """Quick sanity check: compare torch vs ONNX for a dummy input."""
    import onnxruntime as ort

    print(f"\n  Sanity check against {onnx_dir.name} variant...")

    # Vision check
    dummy_pixels = torch.randn(1, 3, image_size, image_size)
    with torch.no_grad():
        if family == "clip":
            vo = model.vision_model(pixel_values=dummy_pixels)
            torch_emb = model.visual_projection(vo.pooler_output)
        else:
            torch_emb = model.get_image_features(pixel_values=dummy_pixels)
        torch_emb = F.normalize(torch_emb, p=2, dim=-1).numpy()

    sess = ort.InferenceSession(
        str(onnx_dir / ENCODER_NAMES["vision"]),
        providers=["CPUExecutionProvider"],
    )
    (onnx_emb,) = sess.run(["embeddings"], {"pixel_values": dummy_pixels.numpy()})
    vision_dot = float(np.dot(torch_emb[0], onnx_emb[0]))
    print(f"    Vision dot product: {vision_dot:.8f}  (diff from 1.0: {abs(1.0 - vision_dot):.2e})")

    # Text check
    dummy_text = "a dark forest with a river"
    inputs = processor(
        text=dummy_text,
        return_tensors="pt",
        padding="max_length",
        max_length=context_length,
        return_attention_mask=True,
    )
    with torch.no_grad():
        if family == "clip":
            to = model.text_model(
                input_ids=inputs["input_ids"],
                attention_mask=inputs["attention_mask"],
            )
            torch_text_emb = model.text_projection(to.pooler_output)
        else:
            torch_text_emb = model.get_text_features(
                input_ids=inputs["input_ids"],
                attention_mask=inputs["attention_mask"],
            )
        torch_text_emb = F.normalize(torch_text_emb, p=2, dim=-1).numpy()

    text_sess = ort.InferenceSession(
        str(onnx_dir / ENCODER_NAMES["text"]),
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


# ── Size report ──────────────────────────────────────────────────────────────


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
        vision = vdir / ENCODER_NAMES["vision"]
        text = vdir / ENCODER_NAMES["text"]
        v_size = vision.stat().st_size / (1024 * 1024) if vision.exists() else 0
        t_size = text.stat().st_size / (1024 * 1024) if text.exists() else 0
        print(
            f"  {variant:<8} {v_size:>10.1f} MB   {t_size:>10.1f} MB   {v_size + t_size:>10.1f} MB"
        )

    tok_dir = base_dir / "tokenizer"
    if tok_dir.exists():
        tok_size = sum(f.stat().st_size for f in tok_dir.rglob("*") if f.is_file())
        print(f"  {'tokenizer':<8} {'':>15} {'':>15} {tok_size / (1024 * 1024):>10.1f} MB")

    print("=" * 70)


# ── Main ─────────────────────────────────────────────────────────────────────


def export_model(entry: dict, base_dir: Path) -> None:
    """Export a single model with all its configured quantisations."""
    name = entry["name"]
    model_id = entry["model_id"]
    quants = entry["quants"]
    output_dir = base_dir / name

    print(f"\n{'=' * 70}")
    print(f"Exporting: {name} ({model_id})")
    print(f"Quants: {', '.join(quants)}")
    print(f"{'=' * 70}")

    # Detect model family
    family = detect_family(model_id)
    print(f"Detected model family: {family}")

    # Clean output directory
    if output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    fp32_dir = output_dir / "fp32"
    fp32_dir.mkdir(parents=True, exist_ok=True)

    # Load model
    print(f"Loading model: {model_id}")
    model = AutoModel.from_pretrained(model_id, local_files_only=False)
    model.eval()
    processor = AutoProcessor.from_pretrained(model_id, local_files_only=False)

    # Extract manifest (needed for image_size and context_length)
    manifest = extract_manifest(model, processor, model_id, family)
    image_size = manifest["image_size"]
    context_length = manifest["tokenizer_max_length"]

    # Export fp32 (always needed as base for quantisation)
    print(f"\nExporting fp32 vision encoder (image_size={image_size})...")
    export_vision(model, family, image_size, fp32_dir)
    print(f"Exporting fp32 text encoder (context_length={context_length})...")
    export_text(model, family, context_length, fp32_dir)

    # Save tokenizer (shared across all variants)
    print("\nSaving tokenizer...")
    if family == "siglip2":
        save_tokenizer_siglip2(processor, output_dir)
    else:
        save_tokenizer_clip(processor, output_dir)

    # Write manifest & sanity check fp32
    if "fp32" in quants:
        print("\nGenerating fp32 manifest...")
        write_manifest(manifest, fp32_dir)
        sanity_check(model, processor, family, image_size, context_length, fp32_dir)

    # Quantise to fp16 (always needed as base for int8 hybrid vision encoder)
    fp16_dir = output_dir / "fp16"
    if "fp16" in quants or "int8" in quants:
        print("\nQuantising to fp16...")
        quantise_fp16(fp32_dir, fp16_dir)
        write_manifest(manifest, fp16_dir)
        if "fp16" in quants:
            sanity_check(model, processor, family, image_size, context_length, fp16_dir)

    # Quantise to int8 (hybrid: fp16 vision + int8 text)
    if "int8" in quants:
        int8_dir = output_dir / "int8"
        print("\nQuantising to int8 (hybrid: fp16 vision + int8 text)...")
        quantise_int8(fp32_dir, fp16_dir, int8_dir, family)
        write_manifest(manifest, int8_dir)
        sanity_check(model, processor, family, image_size, context_length, int8_dir)

    # Remove intermediate dirs that weren't requested
    if "fp32" not in quants:
        shutil.rmtree(fp32_dir)
    if "fp16" not in quants and fp16_dir.exists():
        shutil.rmtree(fp16_dir)

    # Size report
    print_size_table(output_dir)
    print(f"\nExport complete: {output_dir}")


def main() -> None:
    args = parse_args()
    base_dir = Path(__file__).resolve().parent.parent / "backend" / "models"

    for name in args.models:
        export_model(MODEL_BY_NAME[name], base_dir)

    if len(args.models) > 1:
        print(f"\n{'=' * 70}")
        print(f"All done. Exported {len(args.models)} models to {base_dir}")
        print(f"{'=' * 70}")


if __name__ == "__main__":
    main()
