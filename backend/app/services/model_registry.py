"""Static registry of HuggingFace-hosted Scene Atlas embedding models.

The single source of truth for model metadata at runtime (download, selection, API
responses). The models themselves are fine-tuned, exported and published by
scene-atlas-learning's release pipeline (`uv run release ... --release <name>`).
"""

HF_NAMESPACE = "jennis0"
REPO_PREFIX = "scene-atlas-"

MODELS: list[dict] = [
    {
        # Identity
        "name": "small",
        "hf_repo": "jennis0/scene-atlas-small",
        "hf_subfolder": "onnx",
        "hf_revision": "openclip-vitb32-rc3",
        # User-facing
        "label": "Small",
        "description": "Quick on any computer, with good search.",
        "description_technical": "CLIP ViT-B/32 (LAION-2B) fine-tuned for TTRPG art search — 4-bit GPTQ weights with fp16 activations, 30k-token vocabulary. Needs ONNX Runtime 1.24+.",
        "recommended_hardware": "cpu",  # "cpu" | "gpu" | "any"
        # Ratings out of 5 for the model picker, shown as dots: indicative, since speed varies
        # a lot by machine. Speed is image processing (imports), on the processor alone and
        # with a GPU. Basis (scene-atlas-learning
        # docs/model-compression.md): CPU at 2 threads, small ~24 img/s vs medium ~1.6;
        # medium on an RTX 3080 ~200 img/s. Large is unmeasured: ~5x medium by compute.
        "speed": {"cpu": 5, "gpu": 5},
        "search_quality": 3,
        "approx_size_mb": 98,
        "model_id": "laion/CLIP-ViT-B-32-laion2B-s34B-b79K",  # base model the fine-tune starts from
        "embedding_dim": 512,
        "semantic_threshold": 0.15,  # CLIP contrastive loss → higher cosine sims
        "vision_quant": "w4a16",
        "text_quant": "w4a16",
    },
    {
        "name": "medium",
        "hf_repo": "jennis0/scene-atlas-medium",
        # The repo root holds the full transformers checkpoint; only onnx/ is downloaded,
        # pinned to the release tag so later pushes to main can't change installed models.
        "hf_subfolder": "onnx",
        "hf_revision": "siglip2-base-384-rc4",
        "label": "Medium",
        "description": "Better search. Quick with a GPU, much slower without one.",
        "description_technical": "SigLIP2-base-patch16-384 fine-tuned for TTRPG art search — 4-bit GPTQ weights with fp16 activations, 52k-token vocabulary. Needs ONNX Runtime 1.24+.",
        "recommended_hardware": "any",
        "speed": {"cpu": 2, "gpu": 5},
        "search_quality": 4,
        "approx_size_mb": 154,
        "model_id": "google/siglip2-base-patch16-384",  # base model the fine-tune starts from
        "embedding_dim": 768,
        "semantic_threshold": 0.0,  # SigLIP sigmoid loss → lower cosine sims
        "vision_quant": "w4a16",
        "text_quant": "w4a16",
    },
    {
        "name": "large",
        "hf_repo": "jennis0/scene-atlas-large",
        "hf_subfolder": "onnx",
        "hf_revision": "siglip2-l-384-rc4",
        "label": "Large",
        "description": "The best search, but the slowest. Needs a GPU and about 800 MB of memory.",
        "description_technical": "SigLIP2-large-patch16-384 fine-tuned for TTRPG art search — 8-bit weights with fp16 activations, 52k-token vocabulary. Needs ONNX Runtime 1.24+.",
        "recommended_hardware": "gpu",
        "speed": {"cpu": 1, "gpu": 3},
        "search_quality": 5,
        "approx_size_mb": 680,
        "model_id": "google/siglip2-large-patch16-384",  # base model the fine-tune starts from
        "embedding_dim": 1024,
        "semantic_threshold": 0.0,  # SigLIP sigmoid loss → lower cosine sims
        "vision_quant": "w8a16",
        "text_quant": "w8a16",
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
