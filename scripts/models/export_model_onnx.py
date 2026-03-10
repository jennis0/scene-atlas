#!/usr/bin/env python3
"""Export embedding models (CLIP, SigLIP2) to ONNX format.

Exports a single production-optimal variant per model (fp16 vision + int8 or
fp16 text, depending on model).  Optionally runs quality evaluation when
``--image-dir`` is provided (torch model stays loaded to avoid double-load).

Outputs ONNX graphs + tokenizer files + manifest.json to backend/models/<name>/.

Usage:
    # Export a specific model by name:
    uv run python scripts/export_model_onnx.py clip-vit-b-32
    uv run python scripts/export_model_onnx.py siglip2-base

    # Export all registered models:
    uv run python scripts/export_model_onnx.py --all

    # Export with quality evaluation (recommended for production):
    uv run python scripts/export_model_onnx.py clip-vit-b-32 --image-dir /path/to/images

    # List available models:
    uv run python scripts/export_model_onnx.py --list
"""

import argparse
import json
import shutil
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F
from transformers import AutoConfig, AutoModel, AutoProcessor

# ── Model registry ───────────────────────────────────────────────────────────
# Each model has a fixed production strategy: vision_quant + text_quant.
# text_int8_exclude_layers: number of early transformer layers to exclude from
# int8 quantisation (0 = no exclusions).  Only relevant when text_quant="int8".

MODEL_REGISTRY: list[dict] = [
    {
        "name": "clip-vit-b-32",
        "model_id": "laion/CLIP-ViT-B-32-laion2B-s34B-b79K",
        "vision_quant": "fp16",
        "text_quant": "int8",
        "text_int8_exclude_layers": 3,
    },
    {
        "name": "siglip2-base",
        "model_id": "google/siglip2-base-patch16-224",
        "vision_quant": "fp16",
        "text_quant": "int8",
        "text_int8_exclude_layers": 1,
    },
    {
        "name": "siglip2-so400m",
        "model_id": "google/siglip2-so400m-patch14-384",
        "vision_quant": "fp16",
        "text_quant": "fp16",
        "text_int8_exclude_layers": 0,
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
    parser.add_argument(
        "--image-dir",
        type=Path,
        default=None,
        help="Directory of real images for quality evaluation (optional)",
    )
    parser.add_argument(
        "--max-images",
        type=int,
        default=100,
        help="Maximum images to use for evaluation (default: 100)",
    )
    parser.add_argument(
        "--device",
        type=str,
        default="cpu",
        choices=["cpu", "cuda", "directml", "coreml"],
        help="Device for torch inference during sanity check/evaluation (default: cpu). "
        "ONNX export itself always runs on CPU.",
    )
    args = parser.parse_args()

    if args.list_models:
        print("Available models:")
        for m in MODEL_REGISTRY:
            quant_desc = f"vision={m['vision_quant']}, text={m['text_quant']}"
            if m["text_quant"] == "int8" and m["text_int8_exclude_layers"]:
                quant_desc += f", exclude_layers={m['text_int8_exclude_layers']}"
            print(f"  {m['name']:<25} {m['model_id']}")
            print(f"  {'':25} {quant_desc}")
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


_PROTO_SIZE_LIMIT = 2 * 1024 * 1024 * 1024  # 2 GB protobuf serialisation limit


def _preprocess_for_quantisation(src: Path, dst: Path) -> Path:
    """Run ORT pre-processing (shape inference + graph optimisation) on a model.

    The ONNX Runtime docs recommend this before any quantisation step so that
    tensor shape information is available for higher-quality quantisation.

    Models larger than 2 GB are saved with external data to avoid protobuf
    serialisation limits.
    """
    from onnxruntime.quantization.preprocess import quant_pre_process

    large = src.stat().st_size >= _PROTO_SIZE_LIMIT
    print(f"    Pre-processing {src.name}{'  (large model — external data)' if large else ''}...")
    # Skip symbolic shape inference — it fails on CLIP/SigLIP Expand ops
    quant_pre_process(
        str(src),
        str(dst),
        skip_symbolic_shape=True,
        save_as_external_data=large,
        all_tensors_to_one_file=large,
        external_data_location=f"{dst.name}.data" if large else None,
    )
    return dst


def quantise_encoder_fp16(fp32_path: Path, output_path: Path) -> None:
    """Convert a single fp32 ONNX encoder to fp16."""
    import onnx
    from onnxruntime.transformers.float16 import convert_float_to_float16

    large = fp32_path.stat().st_size >= _PROTO_SIZE_LIMIT
    print(f"  Quantising {fp32_path.name} to fp16...")
    preprocessed = output_path.parent / f"_pre_{fp32_path.name}"
    _preprocess_for_quantisation(fp32_path, preprocessed)

    if large:
        # Load with external data tensors resolved relative to the model file
        model = onnx.load(str(preprocessed), load_external_data=True)
    else:
        model = onnx.load(str(preprocessed))
    model_fp16 = convert_float_to_float16(model, keep_io_types=True)

    if large:
        # After fp16 conversion the model is ~half size but may still exceed
        # 2 GB, so save with external data to be safe.
        onnx.save(
            model_fp16,
            str(output_path),
            save_as_external_data=True,
            all_tensors_to_one_file=True,
            location=f"{output_path.name}.data",
        )
    else:
        onnx.save(model_fp16, str(output_path))

    # Clean up preprocessed files
    preprocessed.unlink(missing_ok=True)
    pre_data = preprocessed.parent / f"{preprocessed.name}.data"
    pre_data.unlink(missing_ok=True)


def quantise_encoder_int8(
    fp32_path: Path, output_path: Path, family: str, exclude_layers: int
) -> None:
    """Quantise a single fp32 ONNX encoder to int8 with layer exclusions.

    Uses ``find_layer_nodes()`` from quantisation utils to identify nodes
    to exclude.  On Windows, pre-processes to a named file to avoid ORT
    temp file issues.
    """
    from onnxruntime.quantization import QuantType, quantize_dynamic
    from onnxruntime.quantization.preprocess import quant_pre_process

    from scripts.quantisation.utils import find_layer_nodes

    print(f"  Quantising {fp32_path.name} to int8 (exclude_layers={exclude_layers})...")

    nodes_to_exclude: list[str] = []
    if exclude_layers > 0:
        layers = find_layer_nodes(fp32_path)
        for i in range(exclude_layers):
            key = str(i)
            if key in layers:
                nodes_to_exclude.extend(layers[key])
        # Always exclude projection nodes for stability
        if "projection" in layers:
            nodes_to_exclude.extend(layers["projection"])
        if nodes_to_exclude:
            print(f"    Excluding {len(nodes_to_exclude)} sensitive nodes from quantisation")

    # Pre-process to a named file to avoid Windows temp file issues
    preprocessed = output_path.parent / f"_pre_{fp32_path.name}"
    large = fp32_path.stat().st_size >= _PROTO_SIZE_LIMIT
    quant_pre_process(
        str(fp32_path),
        str(preprocessed),
        skip_symbolic_shape=True,
        save_as_external_data=large,
        all_tensors_to_one_file=large,
        external_data_location=f"{preprocessed.name}.data" if large else None,
    )

    quantize_dynamic(
        model_input=str(preprocessed),
        model_output=str(output_path),
        weight_type=QuantType.QInt8,
        per_channel=True,
        nodes_to_exclude=nodes_to_exclude or None,
    )
    preprocessed.unlink(missing_ok=True)
    pre_data = preprocessed.parent / f"{preprocessed.name}.data"
    pre_data.unlink(missing_ok=True)


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
        interpolation = "bicubic" if int(resample) == 3 else "bilinear"
    else:
        interpolation = "bicubic"

    # Determine resize mode
    do_center_crop = getattr(img_proc, "do_center_crop", False)
    resize_mode = "shortest_edge_then_crop" if do_center_crop else "direct_resize"

    # Embedding dimension
    embedding_dim = getattr(model.config, "projection_dim", None)
    if embedding_dim is None:
        embedding_dim = getattr(model.config.text_config, "projection_dim", None)
    if embedding_dim is None:
        embedding_dim = model.config.text_config.hidden_size

    # Tokenizer config
    tok_max_length = getattr(tokenizer, "model_max_length", None)
    if tok_max_length is None or tok_max_length > 1_000_000:
        tok_max_length = model.config.text_config.max_position_embeddings

    if family == "siglip2":
        tokenizer_type = "sentencepiece"
        tok_pad_id = getattr(tokenizer, "pad_token_id", 1)
        tok_eos_id = getattr(tokenizer, "eos_token_id", None)
    else:
        tokenizer_type = "huggingface"
        tok_pad_id = getattr(tokenizer, "pad_token_id", 49407)
        tok_eos_id = None

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

    print(f"\n  Sanity check against {onnx_dir}...")

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


# ── Quality evaluation (gated behind --image-dir) ───────────────────────────


def _torch_encode_image(model, processor, family: str, image_path: Path) -> np.ndarray:
    """Encode a single image via the torch model."""
    from PIL import Image as PILImage

    with PILImage.open(image_path) as img:
        image = img.convert("RGB")
    inputs = processor(images=image, return_tensors="pt")
    with torch.no_grad():
        if family == "clip":
            vo = model.vision_model(**inputs)
            features = model.visual_projection(vo.pooler_output)
        else:
            features = model.get_image_features(**inputs)
        return F.normalize(features, p=2, dim=-1).cpu().numpy().flatten()


def _torch_encode_text(model, processor, family: str, text: str, max_length: int) -> np.ndarray:
    """Encode a single text via the torch model."""
    if family == "siglip2":
        text = text.lower()
    inputs = processor(
        text=text,
        return_tensors="pt",
        padding="max_length",
        max_length=max_length,
        return_attention_mask=True,
    )
    with torch.no_grad():
        if family == "clip":
            to = model.text_model(**inputs)
            features = model.text_projection(to.pooler_output)
        else:
            features = model.get_text_features(**inputs)
        return F.normalize(features, p=2, dim=-1).cpu().numpy().flatten()


def _measure_inference_time(fn, args_list: list, warmup: int = 3, repeats: int = 3) -> float:
    """Average inference time in ms."""
    for _ in range(warmup):
        fn(args_list[0])
    total = 0.0
    n = 0
    for args in args_list:
        for _ in range(repeats):
            start = time.perf_counter()
            fn(args)
            total += time.perf_counter() - start
            n += 1
    return (total / n) * 1000


def evaluate_quality(
    model,
    processor,
    family: str,
    max_length: int,
    output_dir: Path,
    image_dir: Path,
    max_images: int,
) -> dict:
    """Run quality evaluation comparing torch reference against ONNX output.

    Returns the quantisation_quality dict to write into the manifest.
    """
    from PIL import Image as PILImage

    from backend.app.services.clip_service import CLIPService
    from scripts.quantisation.queries import TEXT_QUERIES
    from scripts.quantisation.utils import (
        collect_images,
        cosine_diffs,
        rank_correlation,
    )

    print(f"\n{'=' * 70}")
    print("Quality Evaluation")
    print(f"{'=' * 70}")

    # Collect real images
    images = collect_images(image_dir, max_count=max_images)
    print(f"  Using {len(images)} real images from {image_dir}")

    # Load ONNX service from flat output dir
    svc = CLIPService(models_dir=output_dir)

    # --- Compute torch reference embeddings ---
    print("  Computing torch reference embeddings...")
    torch_img_embs = [_torch_encode_image(model, processor, family, p) for p in images]
    torch_txt_embs = [
        _torch_encode_text(model, processor, family, t, max_length) for t in TEXT_QUERIES
    ]

    # --- Compute ONNX embeddings ---
    print("  Computing ONNX embeddings...")
    onnx_img_embs = [np.array(svc.encode_image(p)) for p in images]
    onnx_txt_embs = [np.array(svc.encode_text(t)) for t in TEXT_QUERIES]

    # --- Cosine diffs ---
    img_diffs = cosine_diffs(torch_img_embs, onnx_img_embs)
    txt_diffs = cosine_diffs(torch_txt_embs, onnx_txt_embs)

    # --- Rank correlation ---
    rank_stats = rank_correlation(torch_img_embs, torch_txt_embs, onnx_img_embs, onnx_txt_embs)

    # --- Batch consistency check ---
    print("  Checking batch encoding consistency...")
    if len(images) >= 8:
        batch_paths = images[:8]
        batch_embs = svc.batch_encode_images(batch_paths)
        single_embs = [svc.encode_image(p) for p in batch_paths]
        batch_diffs = [
            abs(1.0 - float(np.dot(np.array(b), np.array(s))))
            for b, s in zip(batch_embs, single_embs, strict=True)
        ]
        max_batch_diff = max(batch_diffs)
    else:
        max_batch_diff = 0.0

    # --- Aspect ratio stress test ---
    print("  Running aspect ratio stress tests...")
    aspect_sizes = [(50, 50), (224, 224), (300, 200), (200, 300), (1000, 1000), (1920, 1080)]
    aspect_diffs: list[float] = []
    with tempfile.TemporaryDirectory(prefix="onnx_aspect_") as tmp:
        for w, h in aspect_sizes:
            img_path = Path(tmp) / f"aspect_{w}x{h}.jpg"
            PILImage.new("RGB", (w, h), (80, 120, 160)).save(img_path, format="JPEG", quality=70)
            t_emb = _torch_encode_image(model, processor, family, img_path)
            o_emb = np.array(svc.encode_image(img_path))
            aspect_diffs.append(abs(1.0 - float(np.dot(t_emb, o_emb))))

    # --- Cross-modal ranking test ---
    print("  Checking cross-modal ranking preservation...")
    with tempfile.TemporaryDirectory(prefix="onnx_rank_") as tmp:
        colors = {
            "green": (20, 150, 30),
            "blue": (30, 30, 200),
            "red": (220, 20, 20),
            "yellow": (220, 220, 30),
        }
        color_paths = {}
        for cname, color in colors.items():
            p = Path(tmp) / f"rank_{cname}.jpg"
            PILImage.new("RGB", (100, 100), color).save(p, format="JPEG", quality=70)
            color_paths[cname] = p

        query = "lush green forest"
        torch_text = _torch_encode_text(model, processor, family, query, max_length)
        onnx_text = np.array(svc.encode_text(query))

        torch_scores = {}
        onnx_scores = {}
        for cname, path in color_paths.items():
            t_img = _torch_encode_image(model, processor, family, path)
            o_img = np.array(svc.encode_image(path))
            torch_scores[cname] = float(np.dot(torch_text, t_img))
            onnx_scores[cname] = float(np.dot(onnx_text, o_img))

        torch_ranking = sorted(torch_scores, key=torch_scores.get, reverse=True)
        onnx_ranking = sorted(onnx_scores, key=onnx_scores.get, reverse=True)
        ranking_preserved = torch_ranking == onnx_ranking

    # --- Model sizes ---
    vision_size = (output_dir / ENCODER_NAMES["vision"]).stat().st_size / (1024 * 1024)
    text_size = (output_dir / ENCODER_NAMES["text"]).stat().st_size / (1024 * 1024)

    # --- Inference timing ---
    print("  Measuring inference timing...")
    image_ms = _measure_inference_time(svc.encode_image, images[:20])
    text_ms = _measure_inference_time(svc.encode_text, list(TEXT_QUERIES[:20]))

    # --- Build quality report ---
    quality = {
        "image": {
            "max_diff": float(img_diffs.max()),
            "mean_diff": float(img_diffs.mean()),
            "var_diff": float(img_diffs.var()),
            "n_samples": len(images),
            "model_size_mb": round(vision_size, 2),
            "avg_inference_ms": round(image_ms, 2),
        },
        "text": {
            "max_diff": float(txt_diffs.max()),
            "mean_diff": float(txt_diffs.mean()),
            "var_diff": float(txt_diffs.var()),
            "n_samples": len(TEXT_QUERIES),
            "model_size_mb": round(text_size, 2),
            "avg_inference_ms": round(text_ms, 2),
        },
        "total_size_mb": round(vision_size + text_size, 2),
        "rank_correlation": {
            "mean_rho": rank_stats["mean_rho"],
            "min_rho": rank_stats["min_rho"],
            "pct_top5_preserved": rank_stats["pct_top5_preserved"],
        },
        "batch_consistency_max_diff": max_batch_diff,
        "aspect_ratio_max_diff": max(aspect_diffs) if aspect_diffs else 0.0,
        "cross_modal_ranking_preserved": ranking_preserved,
    }

    # --- Print human-readable report ---
    img = quality["image"]
    txt = quality["text"]
    print(f"\n  {'':20} {'Max Diff':>12} {'Mean Diff':>12} {'Size':>10} {'Avg Time':>10}")
    print(f"  {'-' * 70}")
    print(
        f"  {'Vision encoder':<20} {img['max_diff']:>12.6f} {img['mean_diff']:>12.6f} "
        f"{img['model_size_mb']:>8.1f} MB {img['avg_inference_ms']:>7.1f} ms"
    )
    print(
        f"  {'Text encoder':<20} {txt['max_diff']:>12.6f} {txt['mean_diff']:>12.6f} "
        f"{txt['model_size_mb']:>8.1f} MB {txt['avg_inference_ms']:>7.1f} ms"
    )
    print(f"  {'-' * 70}")
    print(f"  Total size: {quality['total_size_mb']:.1f} MB")
    rc = quality["rank_correlation"]
    print(
        f"  Rank correlation: mean_rho={rc['mean_rho']:.4f} "
        f"min_rho={rc['min_rho']:.4f} "
        f"top5_preserved={rc['pct_top5_preserved']:.1%}"
    )
    print(f"  Batch consistency max diff: {max_batch_diff:.6f}")
    print(f"  Aspect ratio max diff: {quality['aspect_ratio_max_diff']:.6f}")
    print(f"  Cross-modal ranking preserved: {ranking_preserved}")
    print(f"{'=' * 70}")

    return quality


# ── Size report ──────────────────────────────────────────────────────────────


def print_size_report(output_dir: Path) -> None:
    """Print final model sizes."""
    print(f"\n{'=' * 50}")
    print("Model Sizes")
    print(f"{'=' * 50}")
    for label, key in [("Vision", "vision"), ("Text", "text")]:
        path = output_dir / ENCODER_NAMES[key]
        if path.exists():
            size = path.stat().st_size / (1024 * 1024)
            print(f"  {label:<10} {size:>10.1f} MB")
    tok_dir = output_dir / "tokenizer"
    if tok_dir.exists():
        tok_size = sum(f.stat().st_size for f in tok_dir.rglob("*") if f.is_file())
        print(f"  {'Tokenizer':<10} {tok_size / (1024 * 1024):>10.1f} MB")
    print(f"{'=' * 50}")


# ── Main ─────────────────────────────────────────────────────────────────────


def export_model(
    entry: dict, base_dir: Path, image_dir: Path | None, max_images: int, device: str = "cpu"
) -> None:
    """Export a single model with its production-optimal quantisation."""
    name = entry["name"]
    model_id = entry["model_id"]
    vision_quant = entry["vision_quant"]
    text_quant = entry["text_quant"]
    exclude_layers = entry["text_int8_exclude_layers"]
    output_dir = base_dir / name

    print(f"\n{'=' * 70}")
    print(f"Exporting: {name} ({model_id})")
    print(f"Strategy: vision={vision_quant}, text={text_quant}")
    if text_quant == "int8" and exclude_layers:
        print(f"Text int8 exclusions: first {exclude_layers} layer(s) + projection")
    print(f"{'=' * 70}")

    # Detect model family
    family = detect_family(model_id)
    print(f"Detected model family: {family}")

    # Clean output directory (preserve tokenizer if it exists to speed up re-exports)
    if output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Load model
    print(f"Loading model: {model_id}")
    model = AutoModel.from_pretrained(model_id, local_files_only=False)
    model.eval()
    processor = AutoProcessor.from_pretrained(model_id, local_files_only=False)

    # Extract manifest
    manifest = extract_manifest(model, processor, model_id, family)
    image_size = manifest["image_size"]
    context_length = manifest["tokenizer_max_length"]

    # Step 1: Export fp32 to temp dir
    with tempfile.TemporaryDirectory(prefix=f"onnx_fp32_{name}_") as fp32_tmp:
        fp32_dir = Path(fp32_tmp)
        print(f"\nExporting fp32 vision encoder (image_size={image_size})...")
        export_vision(model, family, image_size, fp32_dir)
        print(f"Exporting fp32 text encoder (context_length={context_length})...")
        export_text(model, family, context_length, fp32_dir)

        # Step 2: Synthetic quality gate (torch vs fp32)
        print("\nSynthetic quality gate (torch vs fp32)...")
        sanity_check(model, processor, family, image_size, context_length, fp32_dir)

        # Step 3: Quantise vision encoder
        fp32_vision = fp32_dir / ENCODER_NAMES["vision"]
        out_vision = output_dir / ENCODER_NAMES["vision"]
        if vision_quant == "fp16":
            quantise_encoder_fp16(fp32_vision, out_vision)
        else:
            raise ValueError(f"Unsupported vision_quant: {vision_quant}")

        # Step 4: Quantise text encoder
        fp32_text = fp32_dir / ENCODER_NAMES["text"]
        out_text = output_dir / ENCODER_NAMES["text"]
        if text_quant == "fp16":
            quantise_encoder_fp16(fp32_text, out_text)
        elif text_quant == "int8":
            quantise_encoder_int8(fp32_text, out_text, family, exclude_layers)
        else:
            raise ValueError(f"Unsupported text_quant: {text_quant}")

    # fp32 temp dir is now cleaned up automatically

    # Step 5: Sanity check quantised models
    print("\nSanity check (quantised)...")
    sanity_check(model, processor, family, image_size, context_length, output_dir)

    # Step 6: Save tokenizer
    print("\nSaving tokenizer...")
    if family == "siglip2":
        save_tokenizer_siglip2(processor, output_dir)
    else:
        save_tokenizer_clip(processor, output_dir)

    # Step 7: Write manifest
    write_manifest(manifest, output_dir)

    # Step 8: Quality evaluation (if --image-dir provided)
    if image_dir is not None:
        # Move model to requested device for evaluation (torch ref is the bottleneck)
        # torch doesn't support DirectML — fall back to CPU for that case
        torch_dev = "cuda" if device == "cuda" else "cpu"
        if torch_dev != "cpu":
            model.to(torch_dev)
            print(f"  Moved torch model to {torch_dev} for evaluation")
        quality = evaluate_quality(
            model, processor, family, context_length, output_dir, image_dir, max_images
        )
        # Update manifest with quality metrics
        manifest["quantisation_quality"] = quality
        write_manifest(manifest, output_dir)

    # Step 9: Size report
    print_size_report(output_dir)
    print(f"\nExport complete: {output_dir}")


def main() -> None:
    args = parse_args()
    base_dir = Path(__file__).resolve().parent.parent / "backend" / "models"

    for name in args.models:
        export_model(MODEL_BY_NAME[name], base_dir, args.image_dir, args.max_images, args.device)

    if len(args.models) > 1:
        print(f"\n{'=' * 70}")
        print(f"All done. Exported {len(args.models)} models to {base_dir}")
        print(f"{'=' * 70}")


if __name__ == "__main__":
    main()
