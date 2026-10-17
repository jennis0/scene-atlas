#!/usr/bin/env python3
"""Validate FP16 ONNX models with DirectML execution provider.

Loads the vision and text ONNX encoders from a model directory, runs inference
on synthetic inputs using both DmlExecutionProvider and CPUExecutionProvider,
and reports throughput comparison plus any per-op CPU fallback warnings.

This script is standalone and does not import from backend.app.

Usage:
    uv run python scripts/validate_directml.py
    uv run python scripts/validate_directml.py --model-dir backend/models/siglip2-base
    uv run python scripts/validate_directml.py --iterations 20
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
import time
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    import onnxruntime as ort

# Logging setup — capture ORT warnings to detect per-op CPU fallbacks

_ort_fallback_warnings: list[str] = []


class _ORTFallbackHandler(logging.Handler):
    """Captures ORT log lines that indicate a kernel fell back to CPU."""

    _FALLBACK_PATTERNS = [
        re.compile(r"fallback", re.IGNORECASE),
        re.compile(r"kernel.*not.*found", re.IGNORECASE),
        re.compile(r"will be placed on.*CPU", re.IGNORECASE),
        re.compile(r"not supported.*DmlExecutionProvider", re.IGNORECASE),
    ]

    def emit(self, record: logging.LogRecord) -> None:
        msg = self.format(record)
        for pat in self._FALLBACK_PATTERNS:
            if pat.search(msg):
                _ort_fallback_warnings.append(msg)
                break


def _install_ort_log_capture() -> None:
    """Attach our handler to the onnxruntime logger."""
    ort_logger = logging.getLogger("onnxruntime")
    ort_logger.setLevel(logging.DEBUG)
    handler = _ORTFallbackHandler()
    handler.setLevel(logging.DEBUG)
    ort_logger.addHandler(handler)


# CLI

_DEFAULT_MODEL_DIR = Path(__file__).resolve().parent.parent / "backend" / "models" / "clip-vit-b-32"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate FP16 ONNX models with DirectML provider.",
    )
    parser.add_argument(
        "--model-dir",
        type=Path,
        default=_DEFAULT_MODEL_DIR,
        help="Path to model directory containing ONNX files and manifest.json "
        f"(default: {_DEFAULT_MODEL_DIR})",
    )
    parser.add_argument(
        "--iterations",
        type=int,
        default=10,
        help="Number of timed iterations per encoder per provider (default: 10)",
    )
    parser.add_argument(
        "--warmup",
        type=int,
        default=3,
        help="Number of warmup iterations before timing (default: 3)",
    )
    return parser.parse_args()


# Manifest loading


def load_manifest(model_dir: Path) -> dict:
    """Load manifest.json from the model directory."""
    manifest_path = model_dir / "manifest.json"
    if not manifest_path.exists():
        print(f"ERROR: manifest.json not found in {model_dir}", file=sys.stderr)
        sys.exit(1)
    return json.loads(manifest_path.read_text(encoding="utf-8"))


# Session creation


def create_session(
    model_path: Path,
    provider: str,
    verbose: bool = True,
) -> ort.InferenceSession:
    """Create an ORT InferenceSession with the given provider.

    Falls back to CPU if the requested provider is not available.
    """
    import onnxruntime as ort

    sess_opts = ort.SessionOptions()
    if verbose:
        sess_opts.log_severity_level = 0  # Verbose — surfaces fallback warnings

    providers_requested = [provider]
    if provider != "CPUExecutionProvider":
        # Always include CPU as a fallback so the session can still be created
        providers_requested.append("CPUExecutionProvider")

    return ort.InferenceSession(
        str(model_path),
        sess_options=sess_opts,
        providers=providers_requested,
    )


def get_active_provider(sess: ort.InferenceSession) -> str:
    """Return the first (highest-priority) provider actually used."""
    providers = sess.get_providers()
    return providers[0] if providers else "unknown"


# Synthetic input generation


def make_vision_input(image_size: int) -> dict[str, np.ndarray]:
    """Create a synthetic image tensor (random noise, batch=1)."""
    # ORT expects float32 I/O even for fp16 models when keep_io_types=True
    pixel_values = np.random.randn(1, 3, image_size, image_size).astype(np.float32)
    return {"pixel_values": pixel_values}


def make_text_input(max_length: int) -> dict[str, np.ndarray]:
    """Create synthetic tokenised text input (random token IDs, batch=1)."""
    input_ids = np.random.randint(0, 1000, size=(1, max_length)).astype(np.int64)
    attention_mask = np.ones((1, max_length), dtype=np.int64)
    return {"input_ids": input_ids, "attention_mask": attention_mask}


# Benchmarking


def benchmark(
    sess: ort.InferenceSession,
    feed: dict[str, np.ndarray],
    output_names: list[str],
    warmup: int,
    iterations: int,
) -> tuple[float, np.ndarray]:
    """Run warmup + timed iterations.

    Returns (avg_ms, last_output).
    """
    # Warmup
    for _ in range(warmup):
        sess.run(output_names, feed)

    # Timed
    times: list[float] = []
    result = None
    for _ in range(iterations):
        t0 = time.perf_counter()
        result = sess.run(output_names, feed)
        t1 = time.perf_counter()
        times.append((t1 - t0) * 1000)

    avg_ms = sum(times) / len(times)
    return avg_ms, result[0]


# Reporting


def print_header(title: str) -> None:
    print(f"\n{'=' * 70}")
    print(f"  {title}")
    print(f"{'=' * 70}")


def print_throughput_row(label: str, cpu_ms: float, dml_ms: float | None) -> None:
    if dml_ms is not None and cpu_ms > 0:
        speedup = cpu_ms / dml_ms
        print(
            f"  {label:<25} CPU: {cpu_ms:>8.2f} ms   DML: {dml_ms:>8.2f} ms   speedup: {speedup:.2f}x"
        )
    elif dml_ms is not None:
        print(f"  {label:<25} CPU: {'N/A':>8}      DML: {dml_ms:>8.2f} ms")
    else:
        print(
            f"  {label:<25} CPU: {cpu_ms:>8.2f} ms   DML: {'N/A':>8}      (DirectML not available)"
        )


def print_fallback_report() -> None:
    if not _ort_fallback_warnings:
        print("\n  No per-op CPU fallback warnings detected.")
        return
    # Deduplicate
    unique = list(dict.fromkeys(_ort_fallback_warnings))
    print(f"\n  {len(unique)} unique CPU fallback warning(s) detected:")
    for w in unique:
        # Truncate very long lines
        short = w[:200] + "..." if len(w) > 200 else w
        print(f"    - {short}")


# Main


def main() -> None:
    args = parse_args()
    model_dir: Path = args.model_dir.resolve()
    iterations: int = args.iterations
    warmup: int = args.warmup

    # Install log capture before importing ort
    _install_ort_log_capture()

    import onnxruntime as ort

    print(f"ONNX Runtime version: {ort.__version__}")

    # Check available providers
    available = ort.get_available_providers()
    print(f"Available providers:  {', '.join(available)}")

    dml_available = "DmlExecutionProvider" in available
    if not dml_available:
        print(
            "\nWARNING: DmlExecutionProvider is not available. "
            "Install onnxruntime-directml to enable GPU acceleration. "
            "Proceeding with CPU-only benchmark.\n"
        )

    # Load manifest
    manifest = load_manifest(model_dir)
    image_size = manifest["image_size"]
    max_length = manifest["tokenizer_max_length"]
    vision_file = manifest.get("vision_encoder", "clip_vision_encoder.onnx")
    text_file = manifest.get("text_encoder", "clip_text_encoder.onnx")

    vision_path = model_dir / vision_file
    text_path = model_dir / text_file

    for p in [vision_path, text_path]:
        if not p.exists():
            print(f"ERROR: ONNX model not found: {p}", file=sys.stderr)
            sys.exit(1)

    print(f"\nModel directory:  {model_dir}")
    print(f"Model ID:         {manifest.get('model_id', 'unknown')}")
    print(f"Image size:       {image_size}")
    print(f"Max text length:  {max_length}")
    print(f"Iterations:       {iterations}  (warmup: {warmup})")

    # Generate synthetic inputs (reuse across providers for consistency)
    vision_feed = make_vision_input(image_size)
    text_feed = make_text_input(max_length)

    output_names = ["embeddings"]

    # CPU baseline

    print_header("CPU Baseline (CPUExecutionProvider)")

    cpu_vision_sess = create_session(vision_path, "CPUExecutionProvider", verbose=False)
    cpu_text_sess = create_session(text_path, "CPUExecutionProvider", verbose=False)

    print(f"  Provider active: {get_active_provider(cpu_vision_sess)}")

    cpu_vision_ms, cpu_vision_out = benchmark(
        cpu_vision_sess, vision_feed, output_names, warmup, iterations
    )
    print(f"  Vision encoder:  {cpu_vision_ms:.2f} ms/iter  (output shape: {cpu_vision_out.shape})")

    cpu_text_ms, cpu_text_out = benchmark(
        cpu_text_sess, text_feed, output_names, warmup, iterations
    )
    print(f"  Text encoder:    {cpu_text_ms:.2f} ms/iter  (output shape: {cpu_text_out.shape})")

    # DirectML

    dml_vision_ms = None
    dml_text_ms = None
    dml_vision_out = None
    dml_text_out = None

    if dml_available:
        print_header("DirectML (DmlExecutionProvider)")

        # Clear fallback warnings from CPU sessions
        _ort_fallback_warnings.clear()

        dml_vision_sess = create_session(vision_path, "DmlExecutionProvider", verbose=True)
        dml_text_sess = create_session(text_path, "DmlExecutionProvider", verbose=True)

        print(f"  Provider active: {get_active_provider(dml_vision_sess)}")

        dml_vision_ms, dml_vision_out = benchmark(
            dml_vision_sess, vision_feed, output_names, warmup, iterations
        )
        print(
            f"  Vision encoder:  {dml_vision_ms:.2f} ms/iter  (output shape: {dml_vision_out.shape})"
        )

        dml_text_ms, dml_text_out = benchmark(
            dml_text_sess, text_feed, output_names, warmup, iterations
        )
        print(f"  Text encoder:    {dml_text_ms:.2f} ms/iter  (output shape: {dml_text_out.shape})")

        # Numerical comparison: CPU vs DML
        if cpu_vision_out is not None and dml_vision_out is not None:
            vision_cos = float(
                np.dot(cpu_vision_out.flatten(), dml_vision_out.flatten())
                / (np.linalg.norm(cpu_vision_out) * np.linalg.norm(dml_vision_out) + 1e-12)
            )
            print(f"\n  Vision CPU vs DML cosine similarity: {vision_cos:.8f}")

        if cpu_text_out is not None and dml_text_out is not None:
            text_cos = float(
                np.dot(cpu_text_out.flatten(), dml_text_out.flatten())
                / (np.linalg.norm(cpu_text_out) * np.linalg.norm(dml_text_out) + 1e-12)
            )
            print(f"  Text   CPU vs DML cosine similarity: {text_cos:.8f}")

    # Summary

    print_header("Throughput Comparison")
    print_throughput_row("Vision encoder", cpu_vision_ms, dml_vision_ms)
    print_throughput_row("Text encoder", cpu_text_ms, dml_text_ms)

    if dml_vision_ms is not None and dml_text_ms is not None:
        total_cpu = cpu_vision_ms + cpu_text_ms
        total_dml = dml_vision_ms + dml_text_ms
        print("\n  Combined (vision + text):")
        print(
            f"    CPU: {total_cpu:.2f} ms   DML: {total_dml:.2f} ms   speedup: {total_cpu / total_dml:.2f}x"
        )

    # Fallback warnings

    print_header("CPU Fallback Warnings")
    print_fallback_report()

    print()


if __name__ == "__main__":
    main()
