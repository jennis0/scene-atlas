#!/usr/bin/env python3
"""Download the default embedding model from HuggingFace for Scene Atlas.

Downloads pre-built ONNX files to backend/models/{name}/ (the dev fallback
path used by CLIPService when DATA_DIR/models/{name}/ does not exist).

Idempotent: skips if the model files are already present.

Usage:
    uv run python scripts/models/setup_models.py [model_name]

    model_name: small | medium | large  (default: small)
"""

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent.parent

# Resolve model name: CLI arg → env var → default
_DEFAULT_MODEL = "small"
if len(sys.argv) > 1:
    _MODEL_NAME = sys.argv[1]
else:
    import os

    _MODEL_NAME = os.environ.get("EMBEDDING_MODEL", _DEFAULT_MODEL)


def main() -> None:
    # Import here so the script can be run with just huggingface-hub installed
    import huggingface_hub

    from backend.app.services.model_registry import ENCODER_NAMES, MODEL_BY_NAME

    if _MODEL_NAME not in MODEL_BY_NAME:
        print(f"Unknown model '{_MODEL_NAME}'. Valid names: {list(MODEL_BY_NAME)}", file=sys.stderr)
        sys.exit(1)

    model_info = MODEL_BY_NAME[_MODEL_NAME]
    dest = _ROOT / "backend" / "models" / _MODEL_NAME

    # Check all expected ONNX files + manifest are present
    required = [dest / f for f in list(ENCODER_NAMES.values()) + ["manifest.json"]]
    if all(p.exists() for p in required):
        print(f"Model '{_MODEL_NAME}' already present at {dest} — skipping download.")
        return

    print(f"Downloading model '{_MODEL_NAME}' from {model_info['hf_repo']} → {dest}")
    huggingface_hub.snapshot_download(
        repo_id=model_info["hf_repo"],
        local_dir=str(dest),
        ignore_patterns=["*.md"],
    )
    print(f"Model '{_MODEL_NAME}' downloaded successfully.")


if __name__ == "__main__":
    main()
