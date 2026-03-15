#!/usr/bin/env python3
"""Download the default embedding model from HuggingFace for Scene Atlas.

Downloads pre-built ONNX files to APP_DATA_DIR/models/{name}/ using the
model_download_service (writes version.json as a completion marker, consistent
with is_model_downloaded() and the setup-status API).

Idempotent: skips if version.json is already present.

Usage:
    uv run python scripts/models/setup_models.py [model_name]

    model_name: small | medium | large  (default: small)
"""

import sys

# Resolve model name: CLI arg → env var → default
_DEFAULT_MODEL = "small"
if len(sys.argv) > 1:
    _MODEL_NAME = sys.argv[1]
else:
    import os

    _MODEL_NAME = os.environ.get("EMBEDDING_MODEL", _DEFAULT_MODEL)


def main() -> None:
    from backend.app.services.model_download_service import (
        ModelDownloadError,
        download_model,
        get_model_dir,
        is_model_downloaded,
    )
    from backend.app.services.model_registry import MODEL_BY_NAME

    if _MODEL_NAME not in MODEL_BY_NAME:
        print(f"Unknown model '{_MODEL_NAME}'. Valid names: {list(MODEL_BY_NAME)}", file=sys.stderr)
        sys.exit(1)

    if is_model_downloaded(_MODEL_NAME):
        print(f"Model '{_MODEL_NAME}' already present at {get_model_dir(_MODEL_NAME)} — skipping download.")
        return

    print(f"Downloading model '{_MODEL_NAME}' to {get_model_dir(_MODEL_NAME)} …")
    try:
        result = download_model(_MODEL_NAME)
    except ModelDownloadError as exc:
        print(f"Download failed: {exc}", file=sys.stderr)
        sys.exit(1)

    print(f"Model '{_MODEL_NAME}' downloaded successfully (sha: {result['hf_commit_sha']}).")


if __name__ == "__main__":
    main()
