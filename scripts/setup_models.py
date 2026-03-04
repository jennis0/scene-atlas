#!/usr/bin/env python3
"""Set up CLIP ONNX models for Scene Atlas.

Idempotent: checks if models already exist and skips export if they do.
Downloads the HuggingFace model if not already cached, then exports to ONNX.

Usage:
    uv run python scripts/setup_models.py
"""

import subprocess
import sys
from pathlib import Path

MODELS_DIR = Path(__file__).resolve().parent.parent / "backend" / "models"
MODEL_NAME = "laion/CLIP-ViT-B-32-laion2B-s34B-b79K"

REQUIRED_FILES = [
    MODELS_DIR / "fp16" / "clip_vision_encoder.onnx",
    MODELS_DIR / "fp16" / "clip_text_encoder.onnx",
]


def models_exist() -> bool:
    return all(p.exists() for p in REQUIRED_FILES)


def download_hf_model() -> None:
    print(f"Downloading HuggingFace model: {MODEL_NAME}", flush=True)
    code = (
        "from transformers import CLIPModel, CLIPProcessor; "
        f"CLIPModel.from_pretrained('{MODEL_NAME}'); "
        f"CLIPProcessor.from_pretrained('{MODEL_NAME}')"
    )
    subprocess.run([sys.executable, "-c", code], check=True)
    print("  Download complete.", flush=True)


def export_models() -> None:
    print("Exporting CLIP to ONNX...", flush=True)
    script = Path(__file__).parent / "export_clip_onnx.py"
    subprocess.run([sys.executable, str(script)], check=True)


def main() -> None:
    if models_exist():
        print("CLIP ONNX models already present - skipping setup.")
        return

    print("CLIP ONNX models not found - setting up...")
    download_hf_model()
    export_models()
    print("Model setup complete.")


if __name__ == "__main__":
    main()
