#!/usr/bin/env python3
"""Check ONNX embedding models against the torch reference.

Runs after scripts/export_model_onnx.py to verify that exported ONNX
models (fp32, fp16, int8) produce embeddings numerically equivalent
to the original torch model.  Supports both CLIP and SigLIP2 families.

This is a data-science assessment, NOT a software test.  It lives outside
the pytest suite and runs only when models are freshly generated.

Prerequisites:
    1. Dev deps: torch, transformers (for the reference implementation)
    2. ONNX models exported to backend/models/ (run scripts/export_model_onnx.py)
    3. (Optional) Real images in data/store/images/ for extended checks

Usage:
    uv run python scripts/evaluate_onnx.py
    EMBEDDING_MODEL=siglip2-base uv run python scripts/evaluate_onnx.py
    uv run python scripts/evaluate_onnx.py --models-dir backend/models/clip-vit-b-32 -v
    uv run python scripts/evaluate_onnx.py --variants fp16 int8
"""

import argparse
import json
import logging
import os
import sys
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image as PILImage

from scripts.quantisation.queries import TEXT_QUERIES  # noqa: E402
from scripts.quantisation.utils import rank_correlation as _rank_correlation  # noqa: E402

PROJECT_ROOT = Path(__file__).resolve().parent.parent
_EMBEDDING_MODEL = os.environ.get("EMBEDDING_MODEL", "clip-vit-b-32")
MODELS_DIR_DEFAULT = PROJECT_ROOT / "backend" / "models" / _EMBEDDING_MODEL
IMAGES_DIR_DEFAULT = PROJECT_ROOT / "data" / "store" / "images"

# Read model_id from manifest (if available), fall back to CLIP default
_MANIFEST_PATH = MODELS_DIR_DEFAULT / "fp16" / "manifest.json"
if _MANIFEST_PATH.exists():
    _manifest = json.loads(_MANIFEST_PATH.read_text(encoding="utf-8"))
    MODEL_NAME = _manifest.get("model_id", "laion/CLIP-ViT-B-32-laion2B-s34B-b79K")
else:
    MODEL_NAME = "laion/CLIP-ViT-B-32-laion2B-s34B-b79K"

# Thresholds: abs(1.0 - dot(torch_emb, onnx_emb))
THRESHOLD_FP32 = 0.001
THRESHOLD_FP16 = 0.001
THRESHOLD_INT8_MAX = 0.02
THRESHOLD_INT8_MEAN = 0.005

# Variants that gate the exit code — failures in other variants are warnings only
GATING_VARIANTS = {"fp32", "fp16", "int8"}

VARIANTS = ["fp32", "fp16", "int8"]
VARIANT_THRESHOLDS = {
    "fp32": THRESHOLD_FP32,
    "fp16": THRESHOLD_FP16,
    "int8": THRESHOLD_INT8_MAX,
}

# TEXT_QUERIES is imported from scripts.quantisation.queries (single source of truth)

ASPECT_RATIO_SIZES = [
    (50, 50),  # smaller than 224
    (224, 224),  # exactly 224
    (300, 200),  # landscape
    (200, 300),  # portrait
    (1000, 1000),  # large square
    (1920, 1080),  # 1080p
    (100, 800),  # extreme aspect ratio
]

logger = logging.getLogger(__name__)

# Type alias for check results: (check_name, passed, detail)
CheckResult = tuple[str, bool, str]


# -- Helpers ------------------------------------------------------------------


def _dot(a: list[float], b: list[float]) -> float:
    """Dot product of two vectors."""
    return float(np.dot(np.array(a), np.array(b)))


def _diff(a: list[float], b: list[float]) -> float:
    """abs(1.0 - dot(a, b)) -- measures deviation for L2-normalised vectors."""
    return abs(1.0 - _dot(a, b))


def _collect_real_images(images_dir: Path, max_count: int = 50) -> list[Path]:
    """Collect real images from the image store."""
    if not images_dir.exists():
        return []
    images: list[Path] = []
    for ext in ("*.jpg", "*.jpeg", "*.png", "*.webp"):
        images.extend(images_dir.rglob(ext))
        if len(images) >= max_count * 2:
            break
    return sorted(images)[:max_count]


def _create_test_image(
    path: Path,
    width: int = 20,
    height: int = 20,
    color: tuple = (100, 150, 200),
) -> Path:
    """Create a minimal test JPEG file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    img = PILImage.new("RGB", (width, height), color)
    img.save(path, format="JPEG", quality=70)
    return path


# -- Torch reference implementation -------------------------------------------


class _TorchReference:
    """Torch-based reference for comparison (supports CLIP and SigLIP2)."""

    def __init__(self):
        import torch
        from transformers import AutoConfig, AutoModel, AutoProcessor

        self._torch = torch
        config = AutoConfig.from_pretrained(MODEL_NAME, local_files_only=True)
        class_name = type(config).__name__
        self._family = "siglip2" if class_name in ("SiglipConfig", "Siglip2Config") else "clip"

        self.model = AutoModel.from_pretrained(MODEL_NAME, local_files_only=True)
        self.model.eval()
        self.processor = AutoProcessor.from_pretrained(MODEL_NAME, local_files_only=True)
        tok_max_length = getattr(self.processor.tokenizer, "model_max_length", None)
        if tok_max_length is None or tok_max_length > 1_000_000:
            tok_max_length = config.text_config.max_position_embeddings
        self._max_length = tok_max_length
        embedding_dim = getattr(config, "projection_dim", None)
        if embedding_dim is None:
            embedding_dim = getattr(config.text_config, "projection_dim", None)
        if embedding_dim is None:
            embedding_dim = config.text_config.hidden_size
        self.embedding_dim = embedding_dim

    def _encode_image_features(self, inputs):
        F = self._torch.nn.functional
        with self._torch.no_grad():
            if self._family == "clip":
                vo = self.model.vision_model(**inputs)
                features = self.model.visual_projection(vo.pooler_output)
            else:
                features = self.model.get_image_features(**inputs)
            return F.normalize(features, p=2, dim=-1)

    def _encode_text_features(self, inputs):
        F = self._torch.nn.functional
        with self._torch.no_grad():
            if self._family == "clip":
                to = self.model.text_model(**inputs)
                features = self.model.text_projection(to.pooler_output)
            else:
                features = self.model.get_text_features(**inputs)
            return F.normalize(features, p=2, dim=-1)

    def encode_image(self, image_path) -> list[float]:
        with PILImage.open(image_path) as img:
            image = img.convert("RGB")
        inputs = self.processor(images=image, return_tensors="pt")
        del image
        features = self._encode_image_features(inputs)
        return features.cpu().numpy().flatten().tolist()

    def encode_text(self, text: str) -> list[float]:
        # SigLIP2 was trained on lowercased text; the production SentencePiece
        # wrapper lowercases, so the torch reference must match.
        if self._family == "siglip2":
            text = text.lower()
        inputs = self.processor(
            text=text,
            return_tensors="pt",
            padding="max_length",
            max_length=self._max_length,
            return_attention_mask=True,
        )
        features = self._encode_text_features(inputs)
        return features.cpu().numpy().flatten().tolist()

    def batch_encode_images(self, image_paths) -> list[list[float]]:
        images = []
        for p in image_paths:
            with PILImage.open(p) as img:
                images.append(img.convert("RGB"))
        inputs = self.processor(images=images, return_tensors="pt", padding=True)
        del images
        features = self._encode_image_features(inputs)
        return features.cpu().numpy().tolist()


# -- Assessment suites --------------------------------------------------------


def check_image_encoding(
    torch_ref: _TorchReference,
    onnx_services: dict,
    tmp_dir: Path,
    real_images: list[Path],
) -> list[CheckResult]:
    """Compare single image encoding between torch and ONNX variants."""
    results: list[CheckResult] = []

    for variant, svc in onnx_services.items():
        threshold = VARIANT_THRESHOLDS[variant]

        # Synthetic image
        img = _create_test_image(tmp_dir / f"synth_{variant}.jpg", 300, 200, (100, 150, 200))
        torch_emb = torch_ref.encode_image(img)
        onnx_emb = svc.encode_image(img)
        diff = _diff(torch_emb, onnx_emb)
        results.append(
            (
                f"[{variant}] synthetic_image",
                diff < threshold,
                f"diff={diff:.6f} threshold={threshold}",
            )
        )

        # Dimensions and norm
        img = _create_test_image(tmp_dir / f"dim_{variant}.jpg", 100, 100)
        torch_emb = torch_ref.encode_image(img)
        onnx_emb = svc.encode_image(img)
        torch_norm = abs(float(np.linalg.norm(torch_emb)) - 1.0)
        onnx_norm = abs(float(np.linalg.norm(onnx_emb)) - 1.0)
        expected_dim = torch_ref.embedding_dim
        results.append(
            (
                f"[{variant}] image_dimensions_and_norm",
                len(torch_emb) == expected_dim
                and len(onnx_emb) == expected_dim
                and torch_norm < 0.001
                and onnx_norm < 0.001,
                f"torch_dim={len(torch_emb)} onnx_dim={len(onnx_emb)} expected={expected_dim} "
                f"torch_norm_dev={torch_norm:.6f} onnx_norm_dev={onnx_norm:.6f}",
            )
        )

        # Varied aspect ratios
        for w, h in ASPECT_RATIO_SIZES:
            img = _create_test_image(
                tmp_dir / f"aspect_{variant}_{w}x{h}.jpg", w, h, (80, 120, 160)
            )
            torch_emb = torch_ref.encode_image(img)
            onnx_emb = svc.encode_image(img)
            diff = _diff(torch_emb, onnx_emb)
            results.append(
                (
                    f"[{variant}] aspect_{w}x{h}",
                    diff < threshold,
                    f"diff={diff:.6f} threshold={threshold}",
                )
            )

        # Real images (if available)
        for i, img in enumerate(real_images[:20]):
            torch_emb = torch_ref.encode_image(img)
            onnx_emb = svc.encode_image(img)
            diff = _diff(torch_emb, onnx_emb)
            results.append(
                (
                    f"[{variant}] real_image_{i} ({img.name})",
                    diff < threshold,
                    f"diff={diff:.6f} threshold={threshold}",
                )
            )

        # Worst case across all real images
        if real_images:
            max_diff = 0.0
            worst_image = None
            for img in real_images:
                torch_emb = torch_ref.encode_image(img)
                onnx_emb = svc.encode_image(img)
                diff = _diff(torch_emb, onnx_emb)
                if diff > max_diff:
                    max_diff = diff
                    worst_image = img.name
            results.append(
                (
                    f"[{variant}] worst_case_{len(real_images)}_images",
                    max_diff < threshold,
                    f"max_diff={max_diff:.6f} threshold={threshold} worst={worst_image}",
                )
            )

    return results


def check_text_encoding(
    torch_ref: _TorchReference,
    onnx_services: dict,
) -> list[CheckResult]:
    """Compare text encoding between torch and ONNX variants."""
    results: list[CheckResult] = []

    for variant, svc in onnx_services.items():
        threshold = VARIANT_THRESHOLDS[variant]

        # Text queries
        text_diffs: list[float] = []
        for text in TEXT_QUERIES:
            torch_emb = torch_ref.encode_text(text)
            onnx_emb = svc.encode_text(text)
            diff = _diff(torch_emb, onnx_emb)
            text_diffs.append(diff)
            results.append(
                (
                    f"[{variant}] text '{text[:30]}'",
                    diff < threshold,
                    f"diff={diff:.6f} threshold={threshold}",
                )
            )

        # Aggregate mean check for int8
        if variant == "int8" and text_diffs:
            mean_diff = float(np.mean(text_diffs))
            results.append(
                (
                    f"[{variant}] text_mean_diff",
                    mean_diff < THRESHOLD_INT8_MEAN,
                    f"mean_diff={mean_diff:.6f} threshold={THRESHOLD_INT8_MEAN}",
                )
            )

        # Dimensions and norm
        text = "forest cave with water"
        torch_emb = torch_ref.encode_text(text)
        onnx_emb = svc.encode_text(text)
        torch_norm = abs(float(np.linalg.norm(torch_emb)) - 1.0)
        onnx_norm = abs(float(np.linalg.norm(onnx_emb)) - 1.0)
        expected_dim = torch_ref.embedding_dim
        results.append(
            (
                f"[{variant}] text_dimensions_and_norm",
                len(torch_emb) == expected_dim
                and len(onnx_emb) == expected_dim
                and torch_norm < 0.001
                and onnx_norm < 0.001,
                f"torch_dim={len(torch_emb)} onnx_dim={len(onnx_emb)} expected={expected_dim} "
                f"torch_norm_dev={torch_norm:.6f} onnx_norm_dev={onnx_norm:.6f}",
            )
        )

    return results


def check_batch_encoding(
    torch_ref: _TorchReference,
    onnx_services: dict,
    tmp_dir: Path,
    real_images: list[Path],
) -> list[CheckResult]:
    """Compare batch image encoding between torch and ONNX variants."""
    results: list[CheckResult] = []

    for variant, svc in onnx_services.items():
        threshold = VARIANT_THRESHOLDS[variant]

        # Batch dot products (synthetic)
        paths = []
        for i in range(8):
            p = _create_test_image(
                tmp_dir / f"batch_{variant}_{i}.jpg", 150, 150, (30 * i, 100, 200 - 20 * i)
            )
            paths.append(p)

        torch_embs = torch_ref.batch_encode_images(paths)
        onnx_embs = svc.batch_encode_images(paths)

        for i, (t, o) in enumerate(zip(torch_embs, onnx_embs, strict=True)):
            diff = _diff(t, o)
            results.append(
                (
                    f"[{variant}] batch_image_{i}",
                    diff < threshold,
                    f"diff={diff:.6f} threshold={threshold}",
                )
            )

        # Batch vs single consistency (ONNX only, no torch needed)
        consist_paths = []
        for i in range(4):
            p = _create_test_image(
                tmp_dir / f"consist_{variant}_{i}.jpg", 100, 100, (50 * i, 80, 160)
            )
            consist_paths.append(p)

        batch_embs = svc.batch_encode_images(consist_paths)
        single_embs = [svc.encode_image(p) for p in consist_paths]

        batch_threshold = 0.001 if variant == "fp16" else 0.0001
        for i, (batch, single) in enumerate(zip(batch_embs, single_embs, strict=True)):
            diff = _diff(batch, single)
            results.append(
                (
                    f"[{variant}] batch_vs_single_{i}",
                    diff < batch_threshold,
                    f"diff={diff:.6f} threshold={batch_threshold}",
                )
            )

        # Batch real images
        if len(real_images) >= 8:
            batch = real_images[:8]
            torch_embs = torch_ref.batch_encode_images(batch)
            onnx_embs = svc.batch_encode_images(batch)
            for i, (t, o) in enumerate(zip(torch_embs, onnx_embs, strict=True)):
                diff = _diff(t, o)
                results.append(
                    (
                        f"[{variant}] batch_real_{i} ({batch[i].name})",
                        diff < threshold,
                        f"diff={diff:.6f} threshold={threshold}",
                    )
                )

    return results


def check_cross_modal(
    torch_ref: _TorchReference,
    onnx_services: dict,
    tmp_dir: Path,
) -> list[CheckResult]:
    """Verify that text-image similarity rankings are preserved."""
    results: list[CheckResult] = []

    colors = {
        "green": (20, 150, 30),
        "blue": (30, 30, 200),
        "red": (220, 20, 20),
        "yellow": (220, 220, 30),
    }

    for variant, svc in onnx_services.items():
        paths = {}
        for cname, color in colors.items():
            p = _create_test_image(tmp_dir / f"rank_{variant}_{cname}.jpg", 100, 100, color)
            paths[cname] = p

        query = "lush green forest"
        torch_text = np.array(torch_ref.encode_text(query))
        onnx_text = np.array(svc.encode_text(query))

        torch_scores = {}
        onnx_scores = {}
        for cname, path in paths.items():
            t_img = np.array(torch_ref.encode_image(path))
            o_img = np.array(svc.encode_image(path))
            torch_scores[cname] = float(np.dot(torch_text, t_img))
            onnx_scores[cname] = float(np.dot(onnx_text, o_img))

        torch_ranking = sorted(torch_scores, key=torch_scores.get, reverse=True)
        onnx_ranking = sorted(onnx_scores, key=onnx_scores.get, reverse=True)

        results.append(
            (
                f"[{variant}] cross_modal_ranking",
                torch_ranking == onnx_ranking,
                f"torch={torch_ranking} onnx={onnx_ranking}",
            )
        )

    return results


def check_rank_correlation(
    torch_ref: _TorchReference,
    onnx_services: dict,
    real_images: list[Path],
) -> list[CheckResult]:
    """Measure retrieval rank correlation on real images.

    Uses top-20 Spearman rho and top-5 set preservation to verify that
    quantisation does not degrade search result quality.
    """
    results: list[CheckResult] = []

    if len(real_images) < 10:
        return results  # not enough images for meaningful rank stats

    # Pre-compute torch reference embeddings for a query subset + all images
    query_subset = TEXT_QUERIES[:30]  # use first 30 queries for speed
    torch_img_embs = [np.array(torch_ref.encode_image(p)) for p in real_images]
    torch_txt_embs = [np.array(torch_ref.encode_text(t)) for t in query_subset]

    for variant, svc in onnx_services.items():
        onnx_img_embs = [np.array(svc.encode_image(p)) for p in real_images]
        onnx_txt_embs = [np.array(svc.encode_text(t)) for t in query_subset]

        stats = _rank_correlation(
            torch_img_embs,
            torch_txt_embs,
            onnx_img_embs,
            onnx_txt_embs,
        )

        results.append(
            (
                f"[{variant}] rank_top5_preserved",
                stats["pct_top5_preserved"] >= 0.90,
                f"top5_preserved={stats['pct_top5_preserved']:.1%} "
                f"mean_rho={stats['mean_rho']:.4f} "
                f"min_rho={stats['min_rho']:.4f}",
            )
        )

    return results


def _measure_inference_time(
    fn,
    args_list: list,
    warmup: int = 3,
    repeats: int = 3,
) -> float:
    """Measure average inference time in ms over args_list × repeats.

    Runs warmup iterations first (using the first item) to let the runtime
    optimise, then times each item in args_list repeated `repeats` times.
    """
    import time

    # Warmup
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

    return (total / n) * 1000  # ms


def quantisation_report(
    torch_ref: _TorchReference,
    onnx_services: dict,
    models_dir: Path,
    real_images: list[Path],
    tmp_dir: Path,
) -> None:
    """Print quantisation report and write stats into each variant's manifest.

    For each variant, collects:
    - Similarity to original model (mean, variance, max diff) for text and image
    - Per-encoder and total model sizes
    - Average inference time for text and image encoding
    """
    variants = list(onnx_services.keys())

    # Build image set — use real images if available, else synthetics
    image_paths: list[Path] = []
    if real_images:
        image_paths = real_images[:50]
    else:
        for i in range(20):
            p = _create_test_image(
                tmp_dir / f"report_synth_{i}.jpg", 300, 200, (i * 12, 100, 200 - i * 8)
            )
            image_paths.append(p)

    # Pre-compute torch reference embeddings
    torch_image_embs = [torch_ref.encode_image(p) for p in image_paths]
    torch_text_embs = [torch_ref.encode_text(t) for t in TEXT_QUERIES]

    # Collect per-variant stats
    report_data: dict[str, dict] = {}

    for variant, svc in onnx_services.items():
        # --- Similarity ---
        image_diffs = []
        for i, p in enumerate(image_paths):
            onnx_emb = svc.encode_image(p)
            image_diffs.append(_diff(torch_image_embs[i], onnx_emb))

        text_diffs = []
        for i, t in enumerate(TEXT_QUERIES):
            onnx_emb = svc.encode_text(t)
            text_diffs.append(_diff(torch_text_embs[i], onnx_emb))

        i_arr = np.array(image_diffs)
        t_arr = np.array(text_diffs)

        # --- Model sizes ---
        vdir = models_dir / variant
        vision_size = 0.0
        text_size = 0.0
        if vdir.exists():
            for f in vdir.iterdir():
                if not f.is_file():
                    continue
                sz = f.stat().st_size / (1024 * 1024)
                if "vision" in f.name:
                    vision_size = sz
                elif "text" in f.name:
                    text_size = sz

        # --- Inference timing ---
        image_ms = _measure_inference_time(svc.encode_image, image_paths)
        text_ms = _measure_inference_time(svc.encode_text, list(TEXT_QUERIES))

        report_data[variant] = {
            "image": {
                "max_diff": float(i_arr.max()),
                "mean_diff": float(i_arr.mean()),
                "var_diff": float(i_arr.var()),
                "n_samples": len(image_diffs),
                "model_size_mb": round(vision_size, 2),
                "avg_inference_ms": round(image_ms, 2),
            },
            "text": {
                "max_diff": float(t_arr.max()),
                "mean_diff": float(t_arr.mean()),
                "var_diff": float(t_arr.var()),
                "n_samples": len(text_diffs),
                "model_size_mb": round(text_size, 2),
                "avg_inference_ms": round(text_ms, 2),
            },
            "total_size_mb": round(vision_size + text_size, 2),
        }

    # --- Print human-readable report ---
    source = "real" if real_images else "synthetic"
    print(
        f"\n{'=' * 90}\n"
        f"Quantisation Report ({len(image_paths)} {source} images, "
        f"{len(TEXT_QUERIES)} text queries)\n"
        f"{'=' * 90}"
    )

    for variant in variants:
        d = report_data[variant]
        img = d["image"]
        txt = d["text"]
        print(f"\n  {variant.upper()}")
        print(f"  {'-' * 86}")
        print(
            f"  {'':20} {'Max Diff':>12} {'Mean Diff':>12} {'Variance':>12} "
            f"{'Size':>10} {'Avg Time':>10}"
        )
        print(f"  {'-' * 86}")
        print(
            f"  {'Vision encoder':<20} {img['max_diff']:>12.6f} {img['mean_diff']:>12.6f} "
            f"{img['var_diff']:>12.2e} {img['model_size_mb']:>8.1f} MB "
            f"{img['avg_inference_ms']:>7.1f} ms"
        )
        print(
            f"  {'Text encoder':<20} {txt['max_diff']:>12.6f} {txt['mean_diff']:>12.6f} "
            f"{txt['var_diff']:>12.2e} {txt['model_size_mb']:>8.1f} MB "
            f"{txt['avg_inference_ms']:>7.1f} ms"
        )
        print(f"  {'-' * 86}")
        print(f"  {'Total size:':<20} {d['total_size_mb']:.1f} MB")

    print(f"\n{'=' * 90}")

    # --- Write stats into each variant's manifest ---
    for variant in variants:
        manifest_path = models_dir / variant / "manifest.json"
        if not manifest_path.exists():
            continue
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["quantisation_quality"] = report_data[variant]
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        print(f"  Updated {manifest_path} with quantisation stats")


# -- Main ---------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Check ONNX CLIP models against the torch reference"
    )
    parser.add_argument(
        "--models-dir",
        type=Path,
        default=MODELS_DIR_DEFAULT,
        help="Directory containing fp32/fp16/int8 ONNX model subdirectories",
    )
    parser.add_argument(
        "--images-dir",
        type=Path,
        default=IMAGES_DIR_DEFAULT,
        help="Directory containing real images for extended checks",
    )
    parser.add_argument(
        "--variants",
        nargs="+",
        default=VARIANTS,
        choices=VARIANTS,
        help="ONNX variants to check (default: all)",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="Verbose output")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(message)s",
    )

    # Load torch reference
    print(f"Loading torch reference: {MODEL_NAME}")
    torch_ref = _TorchReference()

    # Load ONNX services (skip missing variants)
    from backend.app.services.clip_service import CLIPService

    onnx_services: dict[str, CLIPService] = {}
    for variant in args.variants:
        vdir = args.models_dir / variant
        if not vdir.exists():
            print(f"  SKIP {variant}: {vdir} not found")
            continue
        onnx_services[variant] = CLIPService(models_dir=vdir)
        print(f"  Loaded {variant}")

    if not onnx_services:
        print("ERROR: No ONNX variants found. Run scripts/export_model_onnx.py first.")
        return 1

    real_images = _collect_real_images(args.images_dir)
    print(f"  Found {len(real_images)} real images for checks\n")

    # Run checks
    with tempfile.TemporaryDirectory(prefix="onnx_check_") as tmp_dir:
        tmp = Path(tmp_dir)

        all_results: list[CheckResult] = []

        print("Checking image encoding...")
        all_results.extend(check_image_encoding(torch_ref, onnx_services, tmp, real_images))

        print("Checking text encoding...")
        all_results.extend(check_text_encoding(torch_ref, onnx_services))

        print("Checking batch encoding...")
        all_results.extend(check_batch_encoding(torch_ref, onnx_services, tmp, real_images))

        print("Checking cross-modal consistency...")
        all_results.extend(check_cross_modal(torch_ref, onnx_services, tmp))

        if real_images:
            print("Checking rank correlation on real images...")
            all_results.extend(check_rank_correlation(torch_ref, onnx_services, real_images))

        # Print results summary — distinguish gating failures from warnings
        passed = sum(1 for _, ok, _ in all_results if ok)
        failed_gating = [
            (name, ok, msg)
            for name, ok, msg in all_results
            if not ok and any(f"[{v}]" in name for v in GATING_VARIANTS)
        ]
        failed_warn = [
            (name, ok, msg)
            for name, ok, msg in all_results
            if not ok and not any(f"[{v}]" in name for v in GATING_VARIANTS)
        ]

        if args.verbose:
            print(f"\n{'-' * 70}")
            for name, ok, msg in all_results:
                gating = any(f"[{v}]" in name for v in GATING_VARIANTS)
                status = "PASS" if ok else ("FAIL" if gating else "WARN")
                print(f"  {status}  {name}: {msg}")

        print(f"\n{'=' * 70}")
        print(
            f"Results: {passed} passed, {len(failed_gating)} failed"
            f", {len(failed_warn)} warned, {len(all_results)} total"
        )
        print(f"Gating variants (must pass): {sorted(GATING_VARIANTS)}")

        if failed_gating:
            print("\nFAILED checks (gating):")
            for name, _, msg in failed_gating:
                print(f"  FAIL  {name}: {msg}")

        if failed_warn:
            print("\nWARNING checks (non-gating):")
            for name, _, msg in failed_warn:
                print(f"  WARN  {name}: {msg}")

        # Quantisation report (similarity, size, and timing)
        print("\nRunning quantisation report (timing + stats)...")
        quantisation_report(torch_ref, onnx_services, args.models_dir, real_images, tmp)

        print(f"{'=' * 70}")

    return 1 if failed_gating else 0


if __name__ == "__main__":
    sys.exit(main())
