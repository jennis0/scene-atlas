#!/usr/bin/env python3
"""Set up the default embedding model for Scene Atlas.

Idempotent: checks if the model's ONNX files already exist and skips if they do.
Uses export_model_onnx.py which handles both downloading and exporting.

Usage:
    uv run python scripts/setup_models.py
"""

import os
import subprocess
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_MODEL = "clip-vit-b-32"
_MODEL_NAME = os.environ.get("EMBEDDING_MODEL", _DEFAULT_MODEL)
_MODELS_DIR = _ROOT / "backend" / "models" / _MODEL_NAME

_REQUIRED_FILES = [
    _MODELS_DIR / "clip_vision_encoder.onnx",
    _MODELS_DIR / "clip_text_encoder.onnx",
    _MODELS_DIR / "manifest.json",
]


def models_exist() -> bool:
    return all(p.exists() for p in _REQUIRED_FILES)


def main() -> None:
    if models_exist():
        print(f"ONNX models already present for {_MODEL_NAME} — skipping setup.")
        return

    print(f"ONNX models not found for {_MODEL_NAME} — exporting...")
    script = Path(__file__).parent / "export_model_onnx.py"
    subprocess.run([sys.executable, str(script), _MODEL_NAME], check=True)
    print("Model setup complete.")


if __name__ == "__main__":
    main()
