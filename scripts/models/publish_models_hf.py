#!/usr/bin/env python3
"""Publish exported ONNX models to Hugging Face Hub.

Uploads model files from backend/models/<name>/ to HF repos under the
configured namespace.  Each model gets its own repo with a flat layout
matching the local directory structure.

Repos are created as **unlisted** (accessible via direct URL / API but
hidden from HF search) since these are derivative quantisations of
third-party models, not original works.

Usage:
    # Publish a specific model:
    uv run python scripts/models/publish_models_hf.py clip-vit-b-32

    # Publish all registered models:
    uv run python scripts/models/publish_models_hf.py --all

    # Dry run (show what would be uploaded):
    uv run python scripts/models/publish_models_hf.py clip-vit-b-32 --dry-run

    # Create/update the HF collection linking all published models:
    uv run python scripts/models/publish_models_hf.py --create-collection

    # List available models:
    uv run python scripts/models/publish_models_hf.py --list

Requires:
    - HF_TOKEN environment variable or `huggingface-cli login`
    - Models must be exported first via scripts/models/export_model_onnx.py
"""

import argparse
import json
import os
from pathlib import Path

from export_model_onnx import ENCODER_NAMES

from backend.app.services.model_registry import (
    HF_NAMESPACE,
    MODEL_BY_NAME,
    REPO_PREFIX,
)
from backend.app.services.model_registry import (
    MODELS as MODEL_REGISTRY,
)

# ── Load .env ────────────────────────────────────────────────────────────────

_ENV_FILE = Path(__file__).resolve().parent.parent.parent / ".env"
if _ENV_FILE.exists():
    for line in _ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip())

# ── Constants ────────────────────────────────────────────────────────────────
MODELS_DIR = Path(__file__).resolve().parent.parent.parent / "backend" / "models"
COLLECTION_TITLE = "Scene Atlas Models"
COLLECTION_DESCRIPTION = (
    "ONNX-exported and quantised vision-language models for Scene Atlas. "
    "These are derivative works — see individual model cards for attribution."
)


# ── CLI ──────────────────────────────────────────────────────────────────────


def parse_args() -> argparse.Namespace:
    names = [m["name"] for m in MODEL_REGISTRY]
    parser = argparse.ArgumentParser(
        description="Publish ONNX models to Hugging Face Hub.",
        epilog=f"Available models: {', '.join(names)}",
    )
    parser.add_argument(
        "models",
        nargs="*",
        metavar="MODEL",
        help="Model name(s) to publish (see --list for available models)",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Publish all registered models",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        dest="list_models",
        help="List available models and exit",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be uploaded without actually uploading",
    )
    parser.add_argument(
        "--create-collection",
        action="store_true",
        help="Create/update the HF collection linking all model repos",
    )
    args = parser.parse_args()

    if args.list_models:
        print("Available models:")
        for m in MODEL_REGISTRY:
            repo_id = f"{HF_NAMESPACE}/{REPO_PREFIX}{m['name']}"
            print(f"  {m['name']:<25} -> {repo_id}")
            print(f"  {'':25}    source: {m['model_id']}")
        raise SystemExit(0)

    if not args.create_collection and not args.all and not args.models:
        parser.error("specify model name(s), --all, or --create-collection")

    if args.all:
        args.models = names

    if args.models:
        for name in args.models:
            if name not in MODEL_BY_NAME:
                parser.error(f"unknown model '{name}' (use --list to see available models)")

    return args


# ── Model card generation ───────────────────────────────────────────────────


def generate_model_card(entry: dict, manifest: dict, model_sizes: dict) -> str:
    """Generate a HF model card (README.md) with proper attribution."""
    name = entry["name"]
    model_id = entry["model_id"]
    family = manifest.get("model_family", "unknown")
    embedding_dim = manifest.get("embedding_dim", "?")
    image_size = manifest.get("image_size", "?")
    vision_quant = entry["vision_quant"]
    text_quant = entry["text_quant"]

    # Build the size table (single variant, flat layout)
    vision_mb = model_sizes.get("vision", 0) / (1024 * 1024)
    text_mb = model_sizes.get("text", 0) / (1024 * 1024)
    total_mb = vision_mb + text_mb

    # Build manifest table (selected fields)
    manifest_rows = []
    display_keys = [
        "model_family",
        "embedding_dim",
        "image_size",
        "image_mean",
        "image_std",
        "interpolation",
        "resize_mode",
        "tokenizer_type",
        "tokenizer_max_length",
    ]
    for key in display_keys:
        if key in manifest:
            val = manifest[key]
            if isinstance(val, list):
                val = ", ".join(f"{v:.4f}" if isinstance(v, float) else str(v) for v in val)
            manifest_rows.append(f"| `{key}` | `{val}` |")

    manifest_table = "\n".join(manifest_rows)

    card = f"""---
base_model: {model_id}
library_name: onnxruntime
tags:
  - onnx
  - scene-atlas
  - {family}
  - vision-language
  - image-embedding
  - text-embedding
---

# {name} (ONNX)

**This is an ONNX export and quantisation of [{model_id}](https://huggingface.co/{model_id}), not an original model.**

All credit for the original model goes to its authors. This repo exists solely to host
pre-exported ONNX variants for use by [Scene Atlas](https://github.com/jennis0/scene-atlas),
a tabletop RPG scene management tool.

## Source Model

- **Original:** [{model_id}](https://huggingface.co/{model_id})
- **Family:** {family}
- **Embedding dimension:** {embedding_dim}
- **Image size:** {image_size}x{image_size}

## Quantisation

| Encoder | Quantisation | Size |
|---------|-------------|------|
| Vision | {vision_quant} | {vision_mb:.1f} MB |
| Text | {text_quant} | {text_mb:.1f} MB |
| **Total** | | **{total_mb:.1f} MB** |

## Model Parameters

| Parameter | Value |
|-----------|-------|
{manifest_table}

## Usage

These models are intended for use with Scene Atlas. The repo contains
`clip_vision_encoder.onnx`, `clip_text_encoder.onnx`, `manifest.json`,
and a `tokenizer/` directory — all at the repo root.

```python
from huggingface_hub import hf_hub_download

# Download encoder files
hf_hub_download(
    repo_id="{HF_NAMESPACE}/{REPO_PREFIX}{name}",
    filename="clip_vision_encoder.onnx",
)
```

## License

Please refer to the [original model card](https://huggingface.co/{model_id}) for
licensing information.
"""
    return card


# ── File size helpers ────────────────────────────────────────────────────────


def get_model_sizes(model_dir: Path) -> dict:
    """Get file sizes for the flat model directory."""
    vision = model_dir / ENCODER_NAMES["vision"]
    text = model_dir / ENCODER_NAMES["text"]
    return {
        "vision": vision.stat().st_size if vision.exists() else 0,
        "text": text.stat().st_size if text.exists() else 0,
    }


# ── Publish ──────────────────────────────────────────────────────────────────


def publish_model(entry: dict, dry_run: bool = False) -> str:
    """Publish a single model to HF Hub. Returns the repo_id."""
    from huggingface_hub import HfApi

    api = HfApi()
    name = entry["name"]
    repo_id = f"{HF_NAMESPACE}/{REPO_PREFIX}{name}"
    model_dir = MODELS_DIR / name

    # Validate local export exists
    if not model_dir.exists():
        print(f"  ERROR: {model_dir} does not exist. Run export_model_onnx.py first.")
        raise SystemExit(1)

    # Check ONNX files exist (flat layout)
    vision_path = model_dir / ENCODER_NAMES["vision"]
    text_path = model_dir / ENCODER_NAMES["text"]
    manifest_path = model_dir / "manifest.json"
    if not vision_path.exists() or not text_path.exists():
        print(f"  ERROR: ONNX encoder files not found in {model_dir}")
        raise SystemExit(1)
    if not manifest_path.exists():
        print(f"  ERROR: No manifest.json found at {manifest_path}")
        raise SystemExit(1)

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    # Compute sizes
    model_sizes = get_model_sizes(model_dir)

    # Generate model card
    card_content = generate_model_card(entry, manifest, model_sizes)

    print(f"\n{'=' * 70}")
    print(f"Publishing: {name} -> {repo_id}")
    print(f"Source:     {model_dir}")
    print(f"{'=' * 70}")

    if dry_run:
        print("\n[DRY RUN] Would create/update repo:", repo_id)
        print("[DRY RUN] Would upload ONNX files + manifest + tokenizer")
        print("\n[DRY RUN] Model card preview:")
        print("-" * 40)
        print(card_content[:500])
        print("..." if len(card_content) > 500 else "")
        print("-" * 40)
        return repo_id

    # Create repo (idempotent)
    print("\nCreating repo (if needed)...")
    api.create_repo(repo_id=repo_id, exist_ok=True, repo_type="model")

    # Set unlisted visibility
    print("Setting visibility to unlisted...")
    api.update_repo_settings(repo_id=repo_id, private=False)

    # Upload model card
    print("Uploading model card...")
    api.upload_file(
        path_or_fileobj=card_content.encode("utf-8"),
        path_in_repo="README.md",
        repo_id=repo_id,
        commit_message=f"Update model card for {name}",
    )

    # Upload flat model directory (ONNX files + manifest)
    print("Uploading model files...")
    api.upload_folder(
        folder_path=str(model_dir),
        repo_id=repo_id,
        commit_message=f"Upload optimised ONNX models for {name}",
        ignore_patterns=["_pre_*"],  # Exclude preprocessing temp files
    )

    print(f"\nPublished: https://huggingface.co/{repo_id}")
    return repo_id


# ── Collection ───────────────────────────────────────────────────────────────


def create_or_update_collection(dry_run: bool = False) -> None:
    """Create or update the HF collection linking all model repos."""
    from huggingface_hub import (
        HfApi,
        get_collection,
    )

    api = HfApi()

    # Build list of expected repo IDs
    expected_repos = [f"{HF_NAMESPACE}/{REPO_PREFIX}{m['name']}" for m in MODEL_REGISTRY]

    if dry_run:
        print("\n[DRY RUN] Would create/update collection:", COLLECTION_TITLE)
        print("[DRY RUN] Would include repos:")
        for repo_id in expected_repos:
            print(f"  - {repo_id}")
        return

    # Search for existing collection by listing user collections
    existing_collection = None
    try:
        collections = api.list_collections(owner=HF_NAMESPACE)
        for col in collections:
            if col.title == COLLECTION_TITLE:
                existing_collection = col
                break
    except Exception:
        pass  # No existing collections or API error

    if existing_collection:
        print(f"Found existing collection: {existing_collection.slug}")
        # Fetch full collection details
        collection = get_collection(existing_collection.slug)
        existing_items = {item.item_id for item in collection.items}

        for repo_id in expected_repos:
            if repo_id not in existing_items:
                print(f"  Adding {repo_id} to collection...")
                api.add_collection_item(
                    collection_slug=collection.slug,
                    item_id=repo_id,
                    item_type="model",
                )
            else:
                print(f"  {repo_id} already in collection")
    else:
        print(f"Creating new collection: {COLLECTION_TITLE}")
        collection = api.create_collection(
            title=COLLECTION_TITLE,
            description=COLLECTION_DESCRIPTION,
            private=False,
        )
        print(f"  Created: {collection.slug}")

        for repo_id in expected_repos:
            print(f"  Adding {repo_id}...")
            api.add_collection_item(
                collection_slug=collection.slug,
                item_id=repo_id,
                item_type="model",
            )

    print(f"\nCollection URL: https://huggingface.co/collections/{collection.slug}")


# ── Main ─────────────────────────────────────────────────────────────────────


def main() -> None:
    args = parse_args()

    if args.models:
        for name in args.models:
            publish_model(MODEL_BY_NAME[name], dry_run=args.dry_run)

    if args.create_collection:
        create_or_update_collection(dry_run=args.dry_run)

    print("\nDone.")


if __name__ == "__main__":
    main()
