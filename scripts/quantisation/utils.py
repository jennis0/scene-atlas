"""Shared utilities for ONNX model quantisation experiments.

Provides image collection, ORT session creation, metrics, quantisation
helpers, and structured results I/O.  Used by both ablation scripts and
the evaluation harness.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import random
import re
import subprocess
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
from PIL import Image as PILImage

# Allow very large battlemaps without DecompressionBombError
PILImage.MAX_IMAGE_PIXELS = 300_000_000

# ── Thresholds ──────────────────────────────────────────────────────────────

PASS_THRESHOLDS = {
    "fp32": 0.001,
    "fp16": 0.001,
    "int8_max": 0.02,
    "int8_mean": 0.005,
}

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}


# ── Image collection ────────────────────────────────────────────────────────


def collect_images(
    image_dir: Path,
    max_count: int = 500,
    seed: int = 42,
) -> list[Path]:
    """Sample real images from *image_dir* deterministically.

    Uses a single os.walk traversal rather than one rglob per extension to
    minimise NFS round-trips.  Filters out macOS resource-fork artefacts
    (``__MACOSX`` directories, ``._`` filename prefixes).
    """
    if not image_dir.exists():
        raise FileNotFoundError(f"Image directory does not exist: {image_dir}")

    images: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(image_dir):
        # Prune macOS resource-fork directories in-place so os.walk skips them
        dirnames[:] = [d for d in dirnames if d != "__MACOSX"]
        for name in filenames:
            if name.startswith("._"):
                continue
            if Path(name).suffix.lower() in IMAGE_EXTENSIONS:
                images.append(Path(dirpath) / name)

    if not images:
        raise FileNotFoundError(f"No images found in {image_dir}")

    random.seed(seed)
    random.shuffle(images)
    return images[:max_count]


# ── ORT session factory ─────────────────────────────────────────────────────


def create_ort_session(onnx_path: Path, *, device: str = "cpu"):
    """Create an ORT InferenceSession with production-matching options.

    Mirrors the session configuration used in ``clip_service.py``.
    Provider resolution is implemented inline so these scripts remain
    runnable in isolation without importing from the backend app stack.

    Parameters
    ----------
    onnx_path : Path
        Path to the ONNX model file.
    device : str
        ``"cpu"`` (default), ``"cuda"``, ``"directml"``, or ``"coreml"``.
    """
    import onnxruntime as ort

    device = device.strip().lower()

    # Map device name → ORT provider + thread counts
    _PROVIDER_MAP = {
        "cuda": ("CUDAExecutionProvider", 4, 2),
        "directml": ("DmlExecutionProvider", 1, 1),
        "coreml": ("CoreMLExecutionProvider", 1, 1),
    }

    if device in _PROVIDER_MAP:
        provider, intra, inter = _PROVIDER_MAP[device]
        available = set(ort.get_available_providers())
        if provider in available:
            providers = [provider, "CPUExecutionProvider"]
        else:
            print(f"  Warning: {provider} not available, falling back to CPU")
            providers = ["CPUExecutionProvider"]
            intra, inter = 2, 1
    else:
        providers = ["CPUExecutionProvider"]
        intra, inter = 2, 1

    sess_opts = ort.SessionOptions()
    sess_opts.intra_op_num_threads = intra
    sess_opts.inter_op_num_threads = inter
    sess_opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL

    session = ort.InferenceSession(str(onnx_path), sess_opts, providers=providers)
    active = session.get_providers()
    if active != providers:
        print(f"  ⚠ Requested {providers} but active: {active}")
    else:
        print(f"  Provider: {active[0]}")
    return session


def get_torch_device(device: str) -> str:
    """Map a ``--device`` CLI value to a torch device string.

    Torch doesn't support DirectML natively, so ``directml`` maps to ``cpu``.
    """
    device = device.strip().lower()
    if device == "cuda":
        return "cuda"
    return "cpu"


# ── Metrics ──────────────────────────────────────────────────────────────────


def cosine_diffs(
    ref: list[np.ndarray],
    test: list[np.ndarray],
) -> np.ndarray:
    """Compute per-pair cosine distance: ``abs(1 - dot(a, b))``."""
    return np.array([abs(1.0 - float(np.dot(r, t))) for r, t in zip(ref, test, strict=True)])


def rank_correlation(
    ref_img_embs: list[np.ndarray],
    ref_txt_embs: list[np.ndarray],
    test_img_embs: list[np.ndarray],
    test_txt_embs: list[np.ndarray],
    top_k: int = 20,
) -> dict[str, float]:
    """Measure retrieval-level agreement between *ref* and *test* embeddings.

    For each text query, ranks images by dot-product similarity in both
    the reference and test sets, then computes:

    * **top_k_rho** — mean Spearman rho over the top-*k* items only
      (avoids noise from irrelevant items in the tail).
    * **pct_top5_preserved** — fraction of queries where the top-5
      image set is identical (primary quality metric).

    Returns a dict with ``mean_rho``, ``min_rho``, and
    ``pct_top5_preserved``.
    """
    from scipy.stats import spearmanr

    if len(ref_img_embs) < top_k:
        top_k = len(ref_img_embs)
    if top_k < 2:
        return {"mean_rho": 1.0, "min_rho": 1.0, "pct_top5_preserved": 1.0}

    ref_img = np.array(ref_img_embs)  # (N_img, dim)
    test_img = np.array(test_img_embs)

    rhos: list[float] = []
    top5_match = 0
    n_queries = len(ref_txt_embs)

    for ref_q, test_q in zip(ref_txt_embs, test_txt_embs, strict=True):
        ref_sims = ref_img @ ref_q  # (N_img,)
        test_sims = test_img @ test_q

        # Indices sorted by descending similarity
        ref_order = np.argsort(-ref_sims)
        test_order = np.argsort(-test_sims)

        # Top-5 set preservation
        ref_top5 = set(ref_order[:5].tolist())
        test_top5 = set(test_order[:5].tolist())
        if ref_top5 == test_top5:
            top5_match += 1

        # Spearman rho over top-K only
        # Take the union of top-K from both sides to avoid bias
        top_k_indices = list(set(ref_order[:top_k].tolist()) | set(test_order[:top_k].tolist()))
        if len(top_k_indices) < 2:
            rhos.append(1.0)
            continue

        ref_ranks = np.argsort(np.argsort(-ref_sims[top_k_indices]))
        test_ranks = np.argsort(np.argsort(-test_sims[top_k_indices]))

        rho, _ = spearmanr(ref_ranks, test_ranks)
        if np.isnan(rho):
            rho = 1.0  # all items tied — treat as perfect agreement
        rhos.append(float(rho))

    return {
        "mean_rho": float(np.mean(rhos)),
        "min_rho": float(np.min(rhos)) if rhos else 1.0,
        "pct_top5_preserved": top5_match / n_queries if n_queries else 1.0,
    }


# ── Quantisation helpers ────────────────────────────────────────────────────


def find_layer_nodes(onnx_path: Path) -> dict[str, list[str]]:
    """Find MatMul nodes grouped by transformer layer index.

    Returns a dict mapping layer indices (as strings) to lists of node
    names.  Special keys: ``"projection"`` for final projection MatMuls,
    ``"attn_pool"`` for attention-pooling MatMuls (SigLIP2).
    """
    import onnx

    model = onnx.load(str(onnx_path))
    matmuls = [n.name for n in model.graph.node if n.op_type == "MatMul"]

    layers: dict[str, list[str]] = {}
    for name in matmuls:
        match = re.search(r"layers\.(\d+)/", name)
        if match:
            layers.setdefault(match.group(1), []).append(name)
            continue

        # Attention pooling (SigLIP2 vision)
        if "multi_head_attention_pooling" in name.lower() or "attn_pool" in name.lower():
            layers.setdefault("attn_pool", []).append(name)
            continue

        # Projection
        if "projection" in name.lower() or "head" in name.lower():
            layers.setdefault("projection", []).append(name)
            continue

    print(f"    Found {len(matmuls)} MatMul nodes across {len(layers)} groups")
    for k in sorted(
        layers.keys(),
        key=lambda x: (x not in ("projection", "attn_pool"), int(x) if x.isdigit() else 999),
    ):
        print(f"      {k}: {len(layers[k])} nodes")

    return layers


def quantise_encoder(
    fp32_path: Path,
    output_path: Path,
    *,
    weight_type: str = "QInt8",
    per_channel: bool = True,
    symmetric: bool = False,
    reduce_range: bool = False,
    nodes_to_exclude: list[str] | None = None,
) -> None:
    """Quantise a single ONNX encoder to int8.

    On Windows, ``quantize_dynamic`` internally creates a temp file for
    shape inference that fails with ``FileNotFoundError``.  We work
    around this by running ``quant_pre_process`` first to a named file,
    then quantising that.  This has zero measurable effect on quality
    (confirmed in the CLIP ablation — see ``design/onnx-int8-quantisation.md``).
    """
    from onnxruntime.quantization import QuantType, quantize_dynamic
    from onnxruntime.quantization.preprocess import quant_pre_process

    wt = QuantType.QInt8 if weight_type == "QInt8" else QuantType.QUInt8

    extra_options: dict | None = None
    if symmetric:
        extra_options = {"WeightSymmetric": True}

    # Pre-process to a named file to avoid Windows temp file issues
    preprocessed = output_path.parent / f"_pre_{output_path.name}"
    print(f"    Pre-processing {fp32_path.stem}...")
    quant_pre_process(str(fp32_path), str(preprocessed), skip_symbolic_shape=True)

    print(f"    Quantising {fp32_path.stem} ({weight_type}, {'per-channel' if per_channel else 'per-tensor'})...")
    quantize_dynamic(
        model_input=str(preprocessed),
        model_output=str(output_path),
        weight_type=wt,
        per_channel=per_channel,
        reduce_range=reduce_range,
        nodes_to_exclude=nodes_to_exclude or None,
        extra_options=extra_options,
    )

    # Clean up
    preprocessed.unlink(missing_ok=True)


# ── Results I/O ─────────────────────────────────────────────────────────────


@dataclass
class ExperimentResult:
    """Metrics for a single ablation experiment."""

    name: str
    img_max: float
    img_mean: float
    txt_max: float
    txt_mean: float
    top5_preserved: float  # PRIMARY retrieval metric
    top_k_rho: float  # Spearman rho over top-K only
    v_size_mb: float
    t_size_mb: float
    config: dict = field(default_factory=dict)

    @property
    def total_mb(self) -> float:
        return self.v_size_mb + self.t_size_mb

    @property
    def img_pass(self) -> bool:
        return self.img_max < PASS_THRESHOLDS["int8_max"]

    @property
    def txt_pass(self) -> bool:
        return self.txt_max < PASS_THRESHOLDS["int8_max"]


@dataclass
class RunMeta:
    """Metadata for a full ablation run."""

    model_id: str
    family: str
    git_commit: str
    timestamp: str
    platform_info: str
    ort_version: str
    image_count: int
    text_count: int
    seed: int
    image_dir: str

    @classmethod
    def capture(
        cls,
        model_id: str,
        family: str,
        image_count: int,
        text_count: int,
        seed: int,
        image_dir: str,
    ) -> RunMeta:
        """Build metadata from the current environment."""
        import onnxruntime as ort

        try:
            git_commit = (
                subprocess.check_output(
                    ["git", "rev-parse", "--short", "HEAD"],
                    stderr=subprocess.DEVNULL,
                )
                .decode()
                .strip()
            )
        except Exception:
            git_commit = "unknown"

        return cls(
            model_id=model_id,
            family=family,
            git_commit=git_commit,
            timestamp=datetime.now(UTC).isoformat(),
            platform_info=f"{platform.system()} {platform.machine()}",
            ort_version=ort.__version__,
            image_count=image_count,
            text_count=text_count,
            seed=seed,
            image_dir=str(image_dir),
        )


def save_results(
    meta: RunMeta,
    results: list[ExperimentResult],
    output_dir: Path,
    prefix: str,
) -> Path:
    """Write run metadata and experiment results to a timestamped JSON file."""
    output_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    path = output_dir / f"{prefix}_{ts}.json"

    data = {
        "meta": asdict(meta),
        "results": [asdict(r) for r in results],
    }
    path.write_text(json.dumps(data, indent=2))
    print(f"\nResults saved to {path}")
    return path


def print_results_table(results: list[ExperimentResult]) -> None:
    """Print a human-readable summary table to stdout."""
    header = (
        f"{'Experiment':<45} {'Vis Max':>10} {'Vis Mean':>10} "
        f"{'Txt Max':>10} {'Txt Mean':>10} {'Top5%':>7} {'Rho':>7} {'Size':>10}"
    )
    sep = "=" * len(header)

    print(f"\n{sep}")
    print("ABLATION RESULTS SUMMARY")
    print(sep)
    print(header)
    print("-" * len(header))

    for r in results:
        vis_ok = "ok" if r.img_pass else "FAIL"
        txt_ok = "ok" if r.txt_pass else "FAIL"
        print(
            f"{r.name:<45} {r.img_max:>10.6f} {r.img_mean:>10.6f} "
            f"{r.txt_max:>10.6f} {r.txt_mean:>10.6f} "
            f"{r.top5_preserved:>6.1%} {r.top_k_rho:>7.4f} "
            f"{r.total_mb:>8.1f} MB  [{vis_ok}/{txt_ok}]"
        )

    print(sep)
    print(
        f"\nThresholds: max < {PASS_THRESHOLDS['int8_max']}, mean < {PASS_THRESHOLDS['int8_mean']}"
    )

    # Best passing config
    passing = [r for r in results if r.img_pass and r.txt_pass]
    if passing:
        best = min(passing, key=lambda r: r.total_mb)
        print(f"\nBest passing config (smallest): {best.name}")
        print(f"  Vision: max={best.img_max:.6f}, mean={best.img_mean:.6f}")
        print(f"  Text:   max={best.txt_max:.6f}, mean={best.txt_mean:.6f}")
        print(f"  Top-5 preserved: {best.top5_preserved:.1%}, rho: {best.top_k_rho:.4f}")
        print(f"  Size:   {best.total_mb:.1f} MB")
    else:
        print("\nNo configuration passed both thresholds!")
        best_vis = min(results, key=lambda r: r.img_max)
        print(f"Best vision: {best_vis.name} (max={best_vis.img_max:.6f})")


# ── CLI helpers ──────────────────────────────────────────────────────────────


def _detect_device() -> str:
    """Return 'cuda' if a CUDA GPU is available, otherwise 'cpu'."""
    try:
        import torch

        if torch.cuda.is_available():
            return "cuda"
    except ImportError:
        pass
    return "cpu"


def add_common_args(parser: argparse.ArgumentParser) -> None:
    """Add standard CLI arguments shared by all ablation scripts."""
    parser.add_argument(
        "--image-dir",
        type=Path,
        required=True,
        help="Directory containing real images for evaluation (required)",
    )
    parser.add_argument(
        "--max-images",
        type=int,
        default=500,
        help="Maximum number of images to sample (default: 500)",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Random seed for image sampling (default: 42)",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(__file__).resolve().parent.parent / "results",
        help="Directory for JSON results output (default: scripts/results/)",
    )
    parser.add_argument(
        "--device",
        type=str,
        default=_detect_device(),
        choices=["cpu", "cuda", "directml", "coreml"],
        help="Inference device for ONNX + torch (default: auto-detected)",
    )
