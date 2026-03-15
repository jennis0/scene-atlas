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
        # User-facing
        "label": "Small",
        "description": "Fast and lightweight — works well without a GPU and uses around 250 MB of memory.",
        "description_technical": "CLIP ViT-B/32 (LAION-2B) — vision fp16, text int8. Good baseline quality for text-image retrieval.",
        "recommended_hardware": "cpu",  # "cpu" | "gpu" | "any"
        "approx_size_mb": 250,
        # Export/quantisation parameters (used by export_model_onnx.py)
        "model_id": "laion/CLIP-ViT-B-32-laion2B-s34B-b79K",
        "embedding_dim": 512,
        "vision_quant": "fp16",
        "text_quant": "int8",
        "text_int8_exclude_layers": 3,
    },
    {
        "name": "medium",
        "hf_repo": "jennis0/scene-atlas-medium",
        "label": "Medium",
        "description": "Better search quality with moderate memory use (~500 MB). Works on most machines, faster with a GPU.",
        "description_technical": "SigLIP2-base-patch16-224 — vision fp16, text int8. Significantly improved zero-shot retrieval over CLIP.",
        "recommended_hardware": "any",
        "approx_size_mb": 500,
        "model_id": "google/siglip2-base-patch16-224",
        "embedding_dim": 768,
        "vision_quant": "fp16",
        "text_quant": "int8",
        "text_int8_exclude_layers": 1,
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


def get_model(name: str) -> dict | None:
    """Return model entry by name, or None if not found."""
    return MODEL_BY_NAME.get(name)


def get_default_model(has_gpu: bool) -> str:
    """Return the recommended model name for the detected hardware."""
    return "medium" if has_gpu else "small"


def get_gpu_provider_label(provider: str) -> str:
    """Return a human-readable label for a GPU provider name."""
    return GPU_PROVIDER_LABELS.get(provider, provider)
