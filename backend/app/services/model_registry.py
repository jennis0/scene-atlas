"""Static registry of HuggingFace-hosted Scene Atlas embedding models.

This is the single source of truth for model metadata used by:
- The runtime backend (model download, selection, API responses)
- scripts/models/export_model_onnx.py (export parameters)
- scripts/models/publish_models_hf.py (HF repo targeting)
"""

HF_NAMESPACE = "jennis0"
REPO_PREFIX = "scene-atlas-"

MODELS: list[dict] = [
    {
        # Identity
        "name": "small",
        "hf_repo": "jennis0/scene-atlas-small",
        # Released by scene-atlas-learning's release pipeline, like medium (see below).
        "release_source": "scene-atlas-learning",
        "hf_subfolder": "onnx",
        "hf_revision": "openclip-vitb32-rc3",
        # User-facing
        "label": "Small",
        "description": "Fast and lightweight (~100 MB download) — works well without a GPU and uses around 160 MB of memory. Tuned for battlemaps and fantasy art.",
        "description_technical": "CLIP ViT-B/32 (LAION-2B) fine-tuned for TTRPG art search — 4-bit GPTQ weights with fp16 activations, 30k-token vocabulary. Needs ONNX Runtime 1.24+.",
        "recommended_hardware": "cpu",  # "cpu" | "gpu" | "any"
        "approx_size_mb": 98,
        "model_id": "laion/CLIP-ViT-B-32-laion2B-s34B-b79K",  # base model the fine-tune starts from
        "embedding_dim": 512,
        "semantic_threshold": 0.15,  # CLIP contrastive loss → higher cosine sims
        "vision_quant": "w4a16",
        "text_quant": "w4a16",
        "text_int8_exclude_layers": 0,
    },
    {
        "name": "medium",
        "hf_repo": "jennis0/scene-atlas-medium",
        # Fine-tuned and released by scene-atlas-learning's release pipeline
        # (`uv run release ... --release medium`), not by the export/publish scripts here.
        # The repo root holds the full transformers checkpoint; only onnx/ is downloaded,
        # pinned to the release tag so later pushes to main can't change installed models.
        "release_source": "scene-atlas-learning",
        "hf_subfolder": "onnx",
        "hf_revision": "siglip2-base-384-rc4",
        "label": "Medium",
        "description": "Best search quality for most machines (~150 MB download). Tuned for battlemaps and fantasy art; faster with a GPU.",
        "description_technical": "SigLIP2-base-patch16-384 fine-tuned for TTRPG art search — 4-bit GPTQ weights with fp16 activations, 52k-token vocabulary. Needs ONNX Runtime 1.24+.",
        "recommended_hardware": "any",
        "approx_size_mb": 154,
        "model_id": "google/siglip2-base-patch16-384",  # base model the fine-tune starts from
        "embedding_dim": 768,
        "semantic_threshold": 0.0,  # SigLIP sigmoid loss → lower cosine sims
        "vision_quant": "w4a16",
        "text_quant": "w4a16",
        "text_int8_exclude_layers": 0,
    },
    {
        "name": "large",
        "hf_repo": "jennis0/scene-atlas-large",
        "label": "Large",
        "description": "Highest search quality, but requires ~1 GB of memory. A GPU is strongly recommended.",
        "description_technical": "SigLIP2-so400m-patch14-384 — vision fp16, text fp16. Best-in-class retrieval; high VRAM requirement.",
        "recommended_hardware": "gpu",
        "approx_size_mb": 1000,
        "model_id": "google/siglip2-so400m-patch14-384",
        "embedding_dim": 1152,
        "semantic_threshold": 0.0,  # SigLIP sigmoid loss → lower cosine sims
        "vision_quant": "fp16",
        "text_quant": "fp16",
        "text_int8_exclude_layers": 0,
    },
]

MODEL_BY_NAME: dict[str, dict] = {m["name"]: m for m in MODELS}
MODEL_NAMES: list[str] = [m["name"] for m in MODELS]

# GPU providers that indicate real hardware acceleration
GPU_PROVIDERS: frozenset[str] = frozenset(
    {"CUDAExecutionProvider", "DmlExecutionProvider", "CoreMLExecutionProvider"}
)

# Ordered priority list for selecting the best GPU provider to report
GPU_PROVIDER_PRIORITY: list[str] = [
    "CUDAExecutionProvider",
    "DmlExecutionProvider",
    "CoreMLExecutionProvider",
]

# Human-readable labels for GPU providers shown in setup UI
GPU_PROVIDER_LABELS: dict[str, str] = {
    "CUDAExecutionProvider": "NVIDIA GPU (CUDA)",
    "DmlExecutionProvider": "GPU (DirectML)",
    "CoreMLExecutionProvider": "Apple Silicon (CoreML)",
}


# Standard ONNX file names used for all Scene Atlas model exports.
# These are the fixed filenames written by export_model_onnx.py and expected
# by publish_models_hf.py and the runtime CLIPService loader.
ENCODER_NAMES: dict[str, str] = {
    "vision": "clip_vision_encoder.onnx",
    "text": "clip_text_encoder.onnx",
}


def is_externally_released(entry: dict) -> bool:
    """True for models built and published outside this repo (see ``release_source``)."""
    return bool(entry.get("release_source"))


def get_model(name: str) -> dict | None:
    """Return model entry by name, or None if not found."""
    return MODEL_BY_NAME.get(name)


def get_default_model(has_gpu: bool) -> str:
    """Return the recommended model name for the detected hardware."""
    return "medium" if has_gpu else "small"


def get_semantic_threshold(model_name: str | None) -> float:
    """Return the semantic search score threshold for a model (0.0 if unknown)."""
    if model_name is None:
        return 0.0
    model = get_model(model_name)
    return model["semantic_threshold"] if model else 0.0


def get_gpu_provider_label(provider: str) -> str:
    """Return a human-readable label for a GPU provider name."""
    return GPU_PROVIDER_LABELS.get(provider, provider)
